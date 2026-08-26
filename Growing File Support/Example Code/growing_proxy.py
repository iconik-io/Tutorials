#!/usr/bin/env python3
"""Attach a growing HLS proxy to an iconik asset.

Simulates a transcoder that emits HLS segments over time: the proxy is created
in GROWING status, the first segment and a playlist are published so the asset
is playable immediately, and the proxy is finalised once the last segment lands.
"""

import logging
import argparse
import time
import uuid
from pathlib import Path

import requests
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"

# (filename, exact duration in seconds). The durations are the real presentation
# durations of the sample segments, taken from ffprobe:
#   seq_00000.ts  196 frames @ 30000/1001 = 6.539867s
#   seq_00001.ts  168 frames @ 30000/1001 = 5.605600s
# EXTINF values must be the actual segment durations, not the nominal segment
# length you asked the transcoder for.
SEGMENTS = [
    ("seq_00000.ts", 6.539867),
    ("seq_00001.ts", 5.605600),
]

FRAME_RATE = 30000 / 1001  # 29.97
RESOLUTION = {"width": 1280, "height": 720}

# RFC 8216 4.3.3.1: every EXTINF, rounded to the nearest integer, must be <= the
# target duration. The longest segment here is 6.539867s, which rounds to 7.
#
# This is computed over *all* segments, including ones not published yet. An
# EVENT playlist may only be appended to, so the target duration you write in
# the first playlist has to hold for the whole stream -- a real transcoder
# should use its configured maximum segment length here.
TARGET_DURATION = max(round(duration) for _, duration in SEGMENTS)


class TestAPI:
    def __init__(
        self,
        base_url: str,
        token: str,
        app_id: str,
    ):
        self.base_url = base_url
        self.headers = {
            'App-ID': app_id,
            'Auth-Token': token,
        }

    def make_request(self, api_url: str, method: str, json_data: bool = True, **kwargs):
        full_url = urljoin(self.base_url, api_url)
        http_method = getattr(requests, method.lower())
        response = http_method(full_url, headers=self.headers, **kwargs)
        logger.debug(f"{method.upper()} {full_url} -> {response.status_code}")

        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            raise e

        if json_data:
            return response.json()
        return response.text


def build_playlist(segment_count: int, complete: bool) -> str:
    """Render the master playlist for the first `segment_count` segments.

    While the proxy is still growing the playlist is EVENT and carries no
    #EXT-X-ENDLIST, which is what keeps the player reloading it and picking up
    newly appended segments. #EXT-X-PLAYLIST-TYPE:VOD would be wrong here: a VOD
    playlist is defined as never changing, so a player reads it exactly once and
    stops at whatever it saw on the first load.
    """
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        f"#EXT-X-TARGETDURATION:{TARGET_DURATION}",
        "#EXT-X-MEDIA-SEQUENCE:0",
        "#EXT-X-PLAYLIST-TYPE:EVENT",
    ]

    for name, duration in SEGMENTS[:segment_count]:
        # Every #EXTINF must be followed by the segment URI, otherwise the
        # segment is not part of the playlist and the player will not fetch it.
        lines.append(f"#EXTINF:{duration:.6f},")
        lines.append(name)

    if complete:
        lines.append("#EXT-X-ENDLIST")

    # A trailing newline, and no leading whitespace anywhere: #EXTM3U must be
    # the literal first line of the file.
    return "\n".join(lines) + "\n"


def get_playlist_content(
    api: TestAPI,
    asset_id: str,
    version_id: str,
    proxy_id: str,
) -> None:
    playlist = api.make_request(
        f"/API/files/v1/assets/{asset_id}/versions/{version_id}/proxies/{proxy_id}/hls/",
        "get", json_data=False
    )

    print(f"Current playlist state\n\n{playlist}")


def get_proxy_storage(api: TestAPI) -> dict:
    """Fetch a storage whose purpose is PROXIES."""
    return api.make_request('/API/files/v1/storages/matching/PROXIES/', 'get')


def create_proxy(
    api: TestAPI,
    asset_id: str,
    storage_method: str,
    proxy_container_id: uuid.UUID,
) -> dict:
    proxy_body = {
        "name": "test_proxy.m3u8",
        "format": "HLS",
        "codec": "h264",
        "frame_rate": f"{FRAME_RATE:.2f}",
        "resolution": RESOLUTION,
        "status": "GROWING",
        "proxy_container_id": str(proxy_container_id),
    }
    url = f'/API/files/v1/assets/{asset_id}/method/{storage_method}/proxies/'
    return api.make_request(url, 'post', json=proxy_body)


def create_proxy_container(
    api: TestAPI,
    asset_id: str,
    proxy_id: str,
    frame_count: int = 0,
    frame_rate: float = 0,
    segment_duration: float = TARGET_DURATION,
) -> dict:
    container_body = {
        "frame_count": frame_count,
        "frame_rate": frame_rate,
        "segment_duration": segment_duration,
    }
    url = f'/API/files/v1/assets/{asset_id}/proxies/{proxy_id}/containers/'
    return api.make_request(url, 'put', json=container_body)


def create_proxy_file(
    api: TestAPI,
    asset_id: str,
    proxy_id: str,
    container_id: str,
    storage_id: str,
    file_type: str,
    name: str,
    directory_path: str,
    proxy_sequence_type: str = "A",
    size: int = 0,
    template_engine: str = "SIMPLE",
    template: str | None = None,
) -> dict:
    """Create a proxy file inside a proxy container.

    `directory_path` is required rather than defaulted: the playlist record and
    the segment sequence record must share one directory, or the relative
    segment names in the playlist will not resolve on storage.
    """
    file_body = {
        "name": name,
        "original_name": name,
        "directory_path": directory_path,
        "size": size,
        "type": file_type,
        "status": "CLOSED",
        "storage_id": storage_id,
        "proxy_sequence_type": proxy_sequence_type,
    }
    if template:
        file_body["template"] = template

    if file_type == "SEQUENCE":
        file_body["template_engine"] = template_engine

    url = (
        f'/API/files/v1/assets/{asset_id}'
        f'/proxies/{proxy_id}'
        f'/containers/{container_id}/files/'
    )
    return api.make_request(url, 'post', json=file_body)


def close_proxy(
    api: TestAPI,
    asset_id: str,
    proxy_id: str,
) -> dict:
    """Move a GROWING proxy to CLOSED once the final playlist is published.

    #EXT-X-ENDLIST tells players the stream is over, but the proxy record stays
    GROWING until it is closed explicitly. Send this only after the playlist
    carrying #EXT-X-ENDLIST is on storage.
    """
    url = f'/API/files/v1/assets/{asset_id}/proxies/{proxy_id}/'
    return api.make_request(url, 'patch', json={"status": "CLOSED"})


def get_proxy_file_upload_url(
    api: TestAPI,
    asset_id: str,
    file_id: str,
    path: str = "",
) -> dict:
    url = f"/API/files/v1/storage_access/assets/{asset_id}/proxy_files/{file_id}/upload_url/"
    params = {"path": path} if path else {}
    return api.make_request(url, "get", params=params)


def upload_file_data(upload_url: str, data: bytes, storage_method: str):
    """Upload bytes to a pre-signed URL using the right flow for the backend."""
    method = storage_method.upper()

    if method == "GCS":
        # GCS pre-signed URLs are resumable-upload starts: POST to begin the
        # session, then PUT the payload to the URL in the location header.
        start = requests.post(
            upload_url,
            headers={"x-goog-resumable": "start", "Content-Length": "0"},
        )
        start.raise_for_status()
        upload_url = start.headers["location"]
        headers = {"Content-Type": "application/octet-stream"}
    elif method == "AZURE":
        headers = {
            "x-ms-blob-type": "BlockBlob",
            "Content-Type": "application/octet-stream",
        }
    else:
        # S3, B2 and filesystem storages take a plain PUT.
        headers = {"Content-Type": "application/octet-stream"}

    response = requests.put(upload_url, data=data, headers=headers)
    response.raise_for_status()
    return response


def publish_segment(
    api: TestAPI,
    asset_id: str,
    ts_sequence_id: str,
    playlist_file_id: str,
    storage_method: str,
    index: int,
) -> None:
    """Upload one segment, then republish the playlist including it."""
    name, duration = SEGMENTS[index]
    complete = index == len(SEGMENTS) - 1

    segment_data = (DATA_DIR / name).read_bytes()
    logger.info(f"Uploading {name} ({len(segment_data)} bytes, {duration:.6f}s)")
    upload_file_data(
        get_proxy_file_upload_url(api, asset_id, ts_sequence_id, path=name)["upload_url"],
        segment_data,
        storage_method,
    )

    # The playlist is republished after the segment is on storage, never before
    # -- a player must not be told about a segment it cannot fetch yet.
    playlist = build_playlist(segment_count=index + 1, complete=complete)
    logger.info(
        f"Publishing playlist with {index + 1} segment(s)"
        f"{' and #EXT-X-ENDLIST' if complete else ''}"
    )
    upload_file_data(
        get_proxy_file_upload_url(api, asset_id, playlist_file_id)["upload_url"],
        playlist.encode("utf-8"),
        storage_method,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--domain',
        default='https://test.iconik.cloud',
        help='Base URL for the API (default: https://test.iconik.cloud)',
    )
    parser.add_argument(
        '--token',
        required=True,
        help='Auth token for the API',
    )
    parser.add_argument(
        '--app-id',
        required=True,
        help='App ID for the API',
    )
    parser.add_argument(
        '--asset-id',
        required=True,
        help='Asset ID to attach the proxy to',
    )
    parser.add_argument(
        '--segment-delay',
        type=float,
        default=30.0,
        help='Seconds to wait between segments, simulating transcode time '
             '(default: 30)',
    )

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )

    args = parser.parse_args()

    log_level: int = logging.INFO
    if args.verbose:
        log_level = logging.DEBUG

    logging.basicConfig(level=log_level)

    api = TestAPI(
        base_url=args.domain,
        token=args.token,
        app_id=args.app_id,
    )
    asset_id = args.asset_id

    storage = get_proxy_storage(api)
    storage_id = storage["id"]
    storage_method = storage["method"]
    logger.info(f"Using proxy storage: id={storage_id}, method={storage_method}")

    proxy_container_id = uuid.uuid1()
    logger.info(f"Generated proxy_container_id: {proxy_container_id}")

    proxy = create_proxy(api, asset_id, storage_method, proxy_container_id)
    proxy_id = proxy["id"]
    version_id = proxy["version_id"]
    logger.info(f"Created proxy: id={proxy_id}")

    container = create_proxy_container(
        api, asset_id, proxy_id, segment_duration=TARGET_DURATION
    )

    container_id = container["id"]
    logger.info(f"Created container: id={container_id}")

    # One directory for the whole container. The playlist refers to segments by
    # bare filename, so they have to sit alongside master.m3u8 on storage.
    directory_path = str(uuid.uuid1())
    logger.info(f"Proxy files directory: {directory_path}")

    playlist_file = create_proxy_file(
        api,
        asset_id=asset_id,
        proxy_id=proxy_id,
        container_id=container_id,
        storage_id=storage_id,
        directory_path=directory_path,
        name="master.m3u8",
        file_type="FILE",
        proxy_sequence_type="HLS_PLAYLIST",
    )

    ts_sequence = create_proxy_file(
        api,
        asset_id=asset_id,
        proxy_id=proxy_id,
        container_id=container_id,
        storage_id=storage_id,
        directory_path=directory_path,
        file_type="SEQUENCE",
        proxy_sequence_type="A",
        name="seq_%05d.ts",
        template=f"seq_%05d.ts [0-{len(SEGMENTS) - 1}]",
    )

    for index in range(len(SEGMENTS)):
        if index:
            logger.warning(
                f"Sleeping for {args.segment_delay:g} seconds, pretending the "
                "transcoder is producing the next segment..."
            )
            time.sleep(args.segment_delay)

        publish_segment(
            api,
            asset_id=asset_id,
            ts_sequence_id=ts_sequence["id"],
            playlist_file_id=playlist_file["id"],
            storage_method=storage_method,
            index=index,
        )

        get_playlist_content(
            api, asset_id=asset_id, version_id=version_id, proxy_id=proxy_id
        )

    # The last playlist published above carries #EXT-X-ENDLIST, so the proxy is
    # complete and can be closed.
    closed = close_proxy(api, asset_id, proxy_id)
    logger.info(f"Closed proxy: id={proxy_id}, status={closed.get('status')}")


if __name__ == '__main__':
    main()

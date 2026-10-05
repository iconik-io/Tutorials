#!/usr/bin/env python3
"""Attach a growing HLS proxy to an iconik asset.

Simulates a transcoder that emits HLS segments over time: the proxy is created
in GROWING status, the first segment and a playlist are published so the asset
is playable immediately, and the proxy is finalised once the last segment lands.

By default each segment carries muxed audio and video. With
--separate-audio-video the proxy is published as separate renditions instead: a
master playlist that points at a video media playlist and an audio media
playlist, each with its own segments. This is the layout iconik serves for DRM
proxies, minus the DRM.
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

FRAME_RATE = 30000 / 1001  # 29.97
RESOLUTION = {"width": 1280, "height": 720}

# (filename, frame count) for the sample segments in data/, from ffprobe.
# Frames rather than seconds because iconik derives the playlist it serves from
# the container's frame_count / frame_rate / segment_duration, so the frame
# count has to be exact; durations are derived from it.
SEGMENTS = [
    ("seq_00000.ts", 196),  # 6.539867s
    ("seq_00001.ts", 168),  # 5.605600s
]

TOTAL_FRAMES = sum(frames for _, frames in SEGMENTS)

# The same two segments split into video-only and audio-only TS files, used by
# --separate-audio-video. They were cut from the muxed files with stream copy
# and -copyts, so timestamps (and therefore A/V sync) carry over unchanged:
#
#   ffmpeg -copyts -i seq_00000.ts -map 0:v -c copy -muxdelay 0 video_00000.ts
#   ffmpeg -copyts -i seq_00000.ts -map 0:a -c copy -muxdelay 0 audio_00000.ts
#
# Video is counted in video frames, like SEGMENTS.
VIDEO_SEGMENTS = [
    ("video_00000.ts", 196),  # 6.539867s
    ("video_00001.ts", 168),  # 5.605600s
]

# Audio is counted in AAC frames. An AAC frame is 1024 samples, so audio
# segment boundaries do not line up with video frames and each audio segment
# has its own duration -- write that, not the video segment's.
AAC_SAMPLE_RATE = 48000
AAC_FRAME_SAMPLES = 1024
AUDIO_SEGMENTS = [
    ("audio_00000.ts", 305),  # 6.506667s
    ("audio_00001.ts", 263),  # 5.610667s
]

# CODECS for the master playlist. avc1.640029 is H.264 High (0x64), no
# constraint flags (0x00), level 4.1 (0x29), read from the SPS of the sample
# video; mp4a.40.2 is AAC-LC.
CODECS = "avc1.640029,mp4a.40.2"


def duration_seconds(frames: int) -> float:
    """Exact presentation duration of a video segment, in seconds."""
    return frames / FRAME_RATE


def audio_duration_seconds(aac_frames: int) -> float:
    """Exact presentation duration of an audio segment, in seconds."""
    return aac_frames * AAC_FRAME_SAMPLES / AAC_SAMPLE_RATE


def playlist_entries(segments: list[tuple[str, int]], duration_fn) -> list[tuple[str, float]]:
    """Turn (name, frame count) pairs into (name, seconds) playlist entries."""
    return [(name, duration_fn(frames)) for name, frames in segments]


MUXED_ENTRIES = playlist_entries(SEGMENTS, duration_seconds)
VIDEO_ENTRIES = playlist_entries(VIDEO_SEGMENTS, duration_seconds)
AUDIO_ENTRIES = playlist_entries(AUDIO_SEGMENTS, audio_duration_seconds)

assert len(MUXED_ENTRIES) == len(VIDEO_ENTRIES) == len(AUDIO_ENTRIES), \
    "every segment list must cover the same segments"

# Proxy file record names. Segment names must be letters/underscores, then
# digits, then the extension -- iconik matches segment URIs to records by
# replacing the digits with a printf pattern (seq_00001.ts -> seq_%05d.ts).
MASTER_PLAYLIST = "master.m3u8"
MUXED_SEQUENCE = "seq_%05d.ts"
VIDEO_PLAYLIST = "video.m3u8"
AUDIO_PLAYLIST = "audio.m3u8"
VIDEO_SEQUENCE = "video_%05d.ts"
AUDIO_SEQUENCE = "audio_%05d.ts"


# RFC 8216 4.3.3.1: every EXTINF, rounded to the nearest integer, must be <= the
# target duration. The longest segment here is 6.539867s, which rounds to 7.
#
# This is computed over *all* segments, including ones not published yet. An
# EVENT playlist may only be appended to, so the target duration you write in
# the first playlist has to hold for the whole stream -- a real transcoder
# should use its configured maximum segment length here.
#
# It covers every segment list, so one value holds for the muxed playlist and
# for both media playlists in --separate-audio-video mode.
TARGET_DURATION = max(
    round(duration)
    for _, duration in MUXED_ENTRIES + VIDEO_ENTRIES + AUDIO_ENTRIES
)


def peak_bandwidth() -> int:
    """BANDWIDTH for the master playlist, in bits per second.

    RFC 8216 4.3.4.2 defines BANDWIDTH as the peak segment bit rate of the
    variant *including* its audio rendition, so each video segment is summed
    with the audio segment alongside it.
    """
    return max(
        round(
            ((DATA_DIR / video).stat().st_size + (DATA_DIR / audio).stat().st_size)
            * 8 / video_duration
        )
        for (video, video_duration), (audio, _) in zip(VIDEO_ENTRIES, AUDIO_ENTRIES)
    )


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


def build_media_playlist(entries: list[tuple[str, float]], complete: bool) -> str:
    """Render a media playlist listing `entries`, as (filename, seconds) pairs.

    Pass only the segments that are already on storage.

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

    for name, duration in entries:
        # Every #EXTINF must be followed by the segment URI, otherwise the
        # segment is not part of the playlist and the player will not fetch it.
        lines.append(f"#EXTINF:{duration:.6f},")
        lines.append(name)

    if complete:
        lines.append("#EXT-X-ENDLIST")

    # A trailing newline, and no leading whitespace anywhere: #EXTM3U must be
    # the literal first line of the file.
    return "\n".join(lines) + "\n"


def build_master_playlist() -> str:
    """Render the master playlist for --separate-audio-video.

    This is the minimum a master needs to tie a video rendition to a separate
    audio rendition. It never changes while the proxy grows -- only the media
    playlists it points at do -- so it is uploaded once, up front, and it never
    carries #EXT-X-ENDLIST (that is a media playlist tag).

    #EXT-X-MEDIA: TYPE, GROUP-ID and NAME are required. URI points at the audio
    media playlist; DEFAULT=YES makes players pick it without being asked.
    Optional attributes such as AUTOSELECT, CHANNELS and LANGUAGE are left out.

    #EXT-X-STREAM-INF: BANDWIDTH is required. AUDIO links the variant to the
    #EXT-X-MEDIA group. CODECS is optional per the RFC but players use it to set
    up the separate audio decoder, so keep it. RESOLUTION and FRAME-RATE are
    optional and left out.

    The URIs are bare filenames. iconik rewrites them to
    .../hls/?path=<filename> when it serves the master, and resolves each one
    to the HLS_PLAYLIST proxy file record with that name.
    """
    lines = [
        "#EXTM3U",
        f'#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="audio",DEFAULT=YES,URI="{AUDIO_PLAYLIST}"',
        f'#EXT-X-STREAM-INF:BANDWIDTH={peak_bandwidth()},CODECS="{CODECS}",AUDIO="audio"',
        VIDEO_PLAYLIST,
    ]
    return "\n".join(lines) + "\n"


def get_playlist_content(
    api: TestAPI,
    asset_id: str,
    version_id: str,
    proxy_id: str,
    path: str = "",
) -> None:
    """Print a playlist as iconik serves it to players.

    Without `path` this is the master playlist. With `path` it is the media
    playlist of that name -- the same URL iconik writes into the master.
    """
    params = {"path": path} if path else {}
    playlist = api.make_request(
        f"/API/files/v1/assets/{asset_id}/versions/{version_id}/proxies/{proxy_id}/hls/",
        "get", json_data=False, params=params,
    )

    print(f"Current playlist state ({path or 'master'})\n\n{playlist}")


def get_asset(api: TestAPI, asset_id: str) -> dict:
    """Fetch an asset record."""
    return api.make_request(f'/API/assets/v1/assets/{asset_id}/', 'get')


def get_asset_version_id(api: TestAPI, asset_id: str) -> str:
    """Resolve the version of the asset the proxy is being attached to.

    Taken from the asset rather than from the proxy creation response, so the
    version is known up front and does not depend on what the proxy endpoint
    happens to echo back.
    """
    asset = get_asset(api, asset_id)

    # `default_version_id` is the asset's current version. Older records may
    # only carry the `versions` array.
    version_id = asset.get("default_version_id")
    if version_id:
        return version_id

    versions = asset.get("versions") or []
    if not versions:
        raise RuntimeError(f"Asset {asset_id} has no versions to attach a proxy to")
    return versions[0]["id"]


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


def upload_proxy_file(
    api: TestAPI,
    asset_id: str,
    file_id: str,
    data: bytes,
    storage_method: str,
    path: str = "",
) -> None:
    """Fetch a pre-signed upload URL for a proxy file and upload `data` to it.

    `path` names the member of a SEQUENCE record (e.g. seq_00000.ts); leave it
    empty for a FILE record such as a playlist.
    """
    upload_url = get_proxy_file_upload_url(api, asset_id, file_id, path=path)["upload_url"]
    upload_file_data(upload_url, data, storage_method)


def upload_segment(
    api: TestAPI,
    asset_id: str,
    sequence_id: str,
    storage_method: str,
    name: str,
    duration: float,
) -> None:
    """Upload one segment from data/ into a SEQUENCE proxy file record."""
    segment_data = (DATA_DIR / name).read_bytes()
    logger.info(f"Uploading {name} ({len(segment_data)} bytes, {duration:.6f}s)")
    upload_proxy_file(api, asset_id, sequence_id, segment_data, storage_method, path=name)


def upload_playlist(
    api: TestAPI,
    asset_id: str,
    playlist_file_id: str,
    storage_method: str,
    name: str,
    entries: list[tuple[str, float]],
    complete: bool,
) -> None:
    """Render a media playlist and overwrite the playlist record with it."""
    logger.info(
        f"Publishing {name} with {len(entries)} segment(s)"
        f"{' and #EXT-X-ENDLIST' if complete else ''}"
    )
    playlist = build_media_playlist(entries, complete=complete)
    upload_proxy_file(api, asset_id, playlist_file_id, playlist.encode("utf-8"), storage_method)


def publish_segment(
    api: TestAPI,
    asset_id: str,
    ts_sequence_id: str,
    playlist_file_id: str,
    storage_method: str,
    index: int,
) -> None:
    """Upload one muxed segment, then republish the playlist including it."""
    complete = index == len(MUXED_ENTRIES) - 1

    upload_segment(api, asset_id, ts_sequence_id, storage_method, *MUXED_ENTRIES[index])

    # The playlist is republished after the segment is on storage, never before
    # -- a player must not be told about a segment it cannot fetch yet.
    upload_playlist(
        api, asset_id, playlist_file_id, storage_method,
        name=MASTER_PLAYLIST, entries=MUXED_ENTRIES[:index + 1], complete=complete,
    )


def publish_separate_av_segment(
    api: TestAPI,
    asset_id: str,
    files: dict[str, str],
    storage_method: str,
    index: int,
) -> None:
    """Upload one video and one audio segment, then republish both media playlists.

    The first call also publishes the master playlist.

    `files` maps each record name registered by register_separate_av_files to
    its proxy file id.
    """
    complete = index == len(VIDEO_ENTRIES) - 1

    upload_segment(api, asset_id, files[VIDEO_SEQUENCE], storage_method, *VIDEO_ENTRIES[index])
    upload_segment(api, asset_id, files[AUDIO_SEQUENCE], storage_method, *AUDIO_ENTRIES[index])

    # Both segments are on storage before either playlist advertises them, so
    # a player never sees video it has no audio for (or the other way round).
    upload_playlist(
        api, asset_id, files[VIDEO_PLAYLIST], storage_method,
        name=VIDEO_PLAYLIST, entries=VIDEO_ENTRIES[:index + 1], complete=complete,
    )
    upload_playlist(
        api, asset_id, files[AUDIO_PLAYLIST], storage_method,
        name=AUDIO_PLAYLIST, entries=AUDIO_ENTRIES[:index + 1], complete=complete,
    )

    # The master never changes, so it goes up once. Same rule one level up: it
    # is published only after the media playlists it points at are on storage.
    if index == 0:
        logger.info(f"Publishing {MASTER_PLAYLIST}")
        upload_proxy_file(
            api, asset_id, files[MASTER_PLAYLIST],
            build_master_playlist().encode("utf-8"), storage_method,
        )


def register_muxed_files(
    api: TestAPI,
    asset_id: str,
    proxy_id: str,
    container_id: str,
    storage_id: str,
    directory_path: str,
) -> dict[str, str]:
    """Create the proxy file records for a single muxed rendition.

    Returns a map of record name to proxy file id.
    """
    playlist_file = create_proxy_file(
        api,
        asset_id=asset_id,
        proxy_id=proxy_id,
        container_id=container_id,
        storage_id=storage_id,
        directory_path=directory_path,
        name=MASTER_PLAYLIST,
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
        name=MUXED_SEQUENCE,
        # The range end is exclusive: "[0-1]" advertises only seq_00000.ts,
        # which is why the served playlist came back one segment short.
        template=f"{MUXED_SEQUENCE} [0-{len(MUXED_ENTRIES)}]",
    )

    return {MASTER_PLAYLIST: playlist_file["id"], MUXED_SEQUENCE: ts_sequence["id"]}


def register_separate_av_files(
    api: TestAPI,
    asset_id: str,
    proxy_id: str,
    container_id: str,
    storage_id: str,
    directory_path: str,
) -> dict[str, str]:
    """Create the proxy file records for separate video and audio renditions.

    Three playlists and two segment sequences:

      master.m3u8     FILE      HLS_PLAYLIST
      video.m3u8      FILE      HLS_PLAYLIST
      audio.m3u8      FILE      HLS_PLAYLIST
      video_%05d.ts   SEQUENCE  A
      audio_%05d.ts   SEQUENCE  A

    Returns a map of record name to proxy file id.
    """
    files = {}

    # iconik finds the playlist for hls/?path=<name> by turning <name> into a
    # sequence pattern -- digits become %d -- and comparing that with record
    # names. video.m3u8 and audio.m3u8 have no digits, so the pattern is the
    # name itself and plain FILE records work. A name like stream_0.m3u8 would
    # become stream_%d.m3u8 and need a SEQUENCE record with that name instead.
    for name in (MASTER_PLAYLIST, VIDEO_PLAYLIST, AUDIO_PLAYLIST):
        files[name] = create_proxy_file(
            api,
            asset_id=asset_id,
            proxy_id=proxy_id,
            container_id=container_id,
            storage_id=storage_id,
            directory_path=directory_path,
            name=name,
            file_type="FILE",
            proxy_sequence_type="HLS_PLAYLIST",
        )["id"]

    # Audio segments are type "A" as well -- iconik resolves every segment URI,
    # in any media playlist, against the "A" records. There is no audio type.
    for name, entries in ((VIDEO_SEQUENCE, VIDEO_ENTRIES), (AUDIO_SEQUENCE, AUDIO_ENTRIES)):
        files[name] = create_proxy_file(
            api,
            asset_id=asset_id,
            proxy_id=proxy_id,
            container_id=container_id,
            storage_id=storage_id,
            directory_path=directory_path,
            file_type="SEQUENCE",
            proxy_sequence_type="A",
            name=name,
            # Uploads outside this range are rejected, and the template cannot
            # be changed later, so it has to cover every segment up front.
            template=f"{name} [0-{len(entries)}]",
        )["id"]

    return files


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
        '--separate-audio-video',
        action='store_true',
        help='Publish separate video and audio renditions (master.m3u8 + '
             'video.m3u8 + audio.m3u8) instead of one muxed rendition',
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

    version_id = get_asset_version_id(api, asset_id)
    logger.info(f"Using asset version: id={version_id}")

    storage = get_proxy_storage(api)
    storage_id = storage["id"]
    storage_method = storage["method"]
    logger.info(f"Using proxy storage: id={storage_id}, method={storage_method}")

    proxy_container_id = uuid.uuid1()
    logger.info(f"Generated proxy_container_id: {proxy_container_id}")

    proxy = create_proxy(api, asset_id, storage_method, proxy_container_id)
    proxy_id = proxy["id"]
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

    if args.separate_audio_video:
        files = register_separate_av_files(
            api, asset_id, proxy_id, container_id, storage_id, directory_path
        )
        segment_count = len(VIDEO_ENTRIES)
        playlists = ["", VIDEO_PLAYLIST, AUDIO_PLAYLIST]
    else:
        files = register_muxed_files(
            api, asset_id, proxy_id, container_id, storage_id, directory_path
        )
        segment_count = len(MUXED_ENTRIES)
        playlists = [""]

    for index in range(segment_count):
        if index:
            logger.warning(
                f"Sleeping for {args.segment_delay:g} seconds, pretending the "
                "transcoder is producing the next segment..."
            )
            time.sleep(args.segment_delay)

        if args.separate_audio_video:
            publish_separate_av_segment(
                api,
                asset_id=asset_id,
                files=files,
                storage_method=storage_method,
                index=index,
            )
        else:
            publish_segment(
                api,
                asset_id=asset_id,
                ts_sequence_id=files[MUXED_SEQUENCE],
                playlist_file_id=files[MASTER_PLAYLIST],
                storage_method=storage_method,
                index=index,
            )

        for path in playlists:
            get_playlist_content(
                api, asset_id=asset_id, version_id=version_id, proxy_id=proxy_id,
                path=path,
            )

    # The last playlists published above carry #EXT-X-ENDLIST, so the proxy is
    # complete and can be closed.
    closed = close_proxy(api, asset_id, proxy_id)
    logger.info(f"Closed proxy: id={proxy_id}, status={closed.get('status')}")


if __name__ == '__main__':
    main()

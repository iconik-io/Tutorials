#!/usr/bin/env python3

import logging
import argparse
import time
import uuid

import requests
from urllib.parse import urljoin

logger = logging.getLogger(__name__)


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
        "format": "m3u8",
        "codec": "",
        "frame_rate": "29.97",
        "resolution": {"width": 1280, "height": 720},
        "status": "OPEN",
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
    segment_duration: float = 6,
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
    name: str ,
    directory_path: str | None = None,
    proxy_sequence_type: str = "A",
    size: int = 0,
    template_engine: str = "SIMPLE",
    template: str | None = None,
) -> dict:
    """Create a proxy file inside a proxy container."""
    if directory_path is None:
        directory_path = str(uuid.uuid1())

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


def get_proxy_file_upload_url(
    api: TestAPI,
    asset_id: str,
    file_id: str,
    path: str = "",
) -> dict:
    url = f"/API/files/v1/storage_access/assets/{asset_id}/proxy_files/{file_id}/upload_url/"
    params = {"path": path} if path else {}
    return api.make_request(url, "get", params=params)


def upload_file_data(upload_url: str, data: bytes, method: str = "PUT"):
    headers = {"Content-Type": "application/octet-stream"}
    response = getattr(requests, method.lower())(upload_url, data=data, headers=headers)
    response.raise_for_status()
    return response


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
        api, asset_id, proxy_id, segment_duration=6
    )

    container_id = container["id"]
    logger.info(f"Created container: id={container_id}")

    playlist_file = create_proxy_file(
        api,
        asset_id=asset_id,
        proxy_id=proxy_id,
        container_id=container_id,
        storage_id=storage_id,
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
        file_type="SEQUENCE",
        proxy_sequence_type="A",
        name="seq_%05d.ts",
        template="seq_%05d.ts [0-1]",
    )

    playlist_data1 = """
        #EXTM3U
        #EXT-X-VERSION:3
        #EXT-X-TARGETDURATION:6
        #EXT-X-MEDIA-SEQUENCE:0
        #EXT-X-PLAYLIST-TYPE:VOD
        #EXTINF:6.000000,
        seq_00000.ts
    """
    upload_file_data(
        get_proxy_file_upload_url(api, asset_id, ts_sequence["id"], path="seq_00000.ts")["upload_url"],
        b"FAKE_TS_DATA_00000",
    )

    upload_file_data(
        get_proxy_file_upload_url(api, asset_id, playlist_file["id"])["upload_url"],
        playlist_data1.encode("utf-8"),
    )

    get_playlist_content(
        api, asset_id=asset_id, version_id=version_id, proxy_id=proxy_id
    )

    logger.warning(
        "Sleeping for 30 seconds pretending that the transcoding is "
        "happening and the playlist is being updated with new segments..."
    )


    time.sleep(30)

    playlist_data2 = """
        #EXTM3U
        #EXT-X-VERSION:3
        #EXT-X-TARGETDURATION:6
        #EXT-X-MEDIA-SEQUENCE:0
        #EXT-X-PLAYLIST-TYPE:VOD
        #EXTINF:6.000000,
        seq_00000.ts
        #EXTINF:2.125000,
        seq_00001.ts
        #EXT-X-ENDLIST
    """

    upload_file_data(
        get_proxy_file_upload_url(api, asset_id, ts_sequence["id"], path="seq_00001.ts")["upload_url"],
        b"FAKE_TS_DATA_00000",
    )

    upload_file_data(
        get_proxy_file_upload_url(api, asset_id, playlist_file["id"])["upload_url"],
        playlist_data2.encode("utf-8"),
    )

    get_playlist_content(
        api, asset_id=asset_id, version_id=version_id, proxy_id=proxy_id
    )


if __name__ == '__main__':
    main()
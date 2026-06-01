# Iconik Proxy Upload Script — Documentation

## Overview

This script simulates a **proxy creation and HLS (HTTP Live Streaming) upload workflow** against the iconik media asset management API. It creates a proxy (a lower-resolution video representation of an asset), uploads fake HLS segments and playlist files to storage, and simulates a progressive transcoding update across two phases.

---

## Table of Contents

1. [Requirements](#requirements)
2. [Usage](#usage)
3. [CLI Arguments](#cli-arguments)
4. [Architecture Overview](#architecture-overview)
5. [Class: TestAPI](#class-testapi)
6. [Functions](#functions)
   - [get_proxy_storage](#get_proxy_storage)
   - [create_proxy](#create_proxy)
   - [create_proxy_container](#create_proxy_container)
   - [create_proxy_file](#create_proxy_file)
   - [get_proxy_file_upload_url](#get_proxy_file_upload_url)
   - [upload_file_data](#upload_file_data)
   - [get_playlist_content](#get_playlist_content)
7. [main() — Full Execution Flow](#main--full-execution-flow)
8. [Data Models](#data-models)
9. [HLS Simulation Explained](#hls-simulation-explained)

---

## Requirements

- Python 3.10+
- [`requests`](https://pypi.org/project/requests/) library

Install dependencies:

```bash
pip install requests
```

---

## Usage

```bash
python script.py \
  --token <AUTH_TOKEN> \
  --app-id <APP_ID> \
  --asset-id <ASSET_UUID> \
  [--domain https://test.iconik.cloud] \
  [-v]
```

---

## CLI Arguments

| Argument | Required | Default | Description |
|---|---|---|---|
| `--domain` | No | `https://test.iconik.cloud` | Base URL for the API |
| `--token` | Yes | — | Auth token (`Auth-Token` header) |
| `--app-id` | Yes | — | Application ID (`App-ID` header) |
| `--asset-id` | Yes | — | UUID of the target asset to attach the proxy to |
| `-v` / `--verbose` | No | — | Enables `DEBUG`-level logging output |

---

## Architecture Overview

The script follows a linear, stateful flow where each step depends on identifiers returned by the previous one:

```
CLI Args
   │
   ▼
Fetch PROXIES Storage ──────────────► storage_id, storage_method
   │
   ▼
Create Proxy ───────────────────────► proxy_id, version_id
   │
   ▼
Create Proxy Container ─────────────► container_id
   │
   ▼
Create Playlist File Record ────────► playlist_file_id
Create Segment Sequence Record ─────► ts_sequence_id
   │
   ▼
Upload Segment seq_00000.ts (via pre-signed URL)
Upload Playlist v1 — 1 segment, no ENDLIST
   │
   ▼
Print Playlist State (mid-transcode)
   │
   ▼
Sleep 30s (simulated transcoding)
   │
   ▼
Upload Segment seq_00001.ts
Upload Playlist v2 — 2 segments + #EXT-X-ENDLIST
   │
   ▼
Print Playlist State (complete)
```

---

## Class: TestAPI

```python
class TestAPI:
    def __init__(self, base_url: str, token: str, app_id: str): ...
    def make_request(self, api_url: str, method: str, json_data: bool = True, **kwargs): ...
```

A lightweight HTTP client wrapper around the `requests` library. All API communication is routed through this class.

### Constructor

| Parameter | Type | Description |
|---|---|---|
| `base_url` | `str` | Root URL of the iconik API instance |
| `token` | `str` | Auth token, sent as the `Auth-Token` request header |
| `app_id` | `str` | Application ID, sent as the `App-ID` request header |

### `make_request(api_url, method, json_data=True, **kwargs)`

Builds the full URL from `base_url + api_url`, dynamically selects the HTTP method via `getattr(requests, method.lower())`, injects the auth headers, and returns the response.

| Parameter | Type | Description |
|---|---|---|
| `api_url` | `str` | Relative API path (e.g. `/API/files/v1/storages/matching/PROXIES/`) |
| `method` | `str` | HTTP method string: `"get"`, `"post"`, `"put"`, etc. |
| `json_data` | `bool` | If `True` (default), returns `response.json()`. If `False`, returns `response.text` |
| `**kwargs` | — | Passed directly to the `requests` method (e.g. `json=`, `params=`) |

Raises `requests.HTTPError` on any non-2xx response.

---

## Functions

### `get_proxy_storage`

```python
def get_proxy_storage(api: TestAPI) -> dict
```

Fetches the storage location designated for proxies.

- **Method:** `GET`
- **Endpoint:** `/API/files/v1/storages/matching/PROXIES/`
- **Returns:** A storage object. Key fields used downstream:

| Field | Description |
|---|---|
| `id` | UUID of the storage — used when registering proxy files |
| `method` | Upload method (e.g. `S3`, `GCS`) — used in the proxy creation URL path |

---

### `create_proxy`

```python
def create_proxy(
    api: TestAPI,
    asset_id: str,
    storage_method: str,
    proxy_container_id: uuid.UUID,
) -> dict
```

Registers a new proxy record against an asset.

- **Method:** `POST`
- **Endpoint:** `/API/files/v1/assets/{asset_id}/method/{storage_method}/proxies/`
- **Request body:**

```json
{
  "name": "test_proxy.m3u8",
  "format": "m3u8",
  "codec": "",
  "frame_rate": "29.97",
  "resolution": { "width": 1280, "height": 720 },
  "status": "OPEN",
  "proxy_container_id": "<uuid>"
}
```

- **Returns:** A proxy object. Key fields used downstream:

| Field | Description |
|---|---|
| `id` | UUID of the proxy — used in all subsequent proxy-scoped endpoints |
| `version_id` | UUID of the asset version this proxy belongs to |

---

### `create_proxy_container`

```python
def create_proxy_container(
    api: TestAPI,
    asset_id: str,
    proxy_id: str,
    frame_count: int = 0,
    frame_rate: float = 0,
    segment_duration: float = 6,
) -> dict
```

Creates a container that holds the proxy's files and video structure metadata.

- **Method:** `PUT`
- **Endpoint:** `/API/files/v1/assets/{asset_id}/proxies/{proxy_id}/containers/`
- **Request body:**

```json
{
  "frame_count": 0,
  "frame_rate": 0,
  "segment_duration": 6
}
```

> **Note:** `segment_duration` must match the `#EXT-X-TARGETDURATION` value in the uploaded HLS playlist.

- **Returns:** A container object. Key field:

| Field | Description |
|---|---|
| `id` | UUID of the container — used as the parent when creating proxy files |

---

### `create_proxy_file`

```python
def create_proxy_file(
    api: TestAPI,
    asset_id: str,
    proxy_id: str,
    container_id: str,
    storage_id: str,
    file_type: str,
    name: str,
    directory_path: str | None = None,
    proxy_sequence_type: str = "A",
    size: int = 0,
    template_engine: str = "SIMPLE",
    template: str | None = None,
) -> dict
```

Creates a file record inside a proxy container. Used for both the `.m3u8` playlist and the `.ts` segment sequence.

- **Method:** `POST`
- **Endpoint:** `/API/files/v1/assets/{asset_id}/proxies/{proxy_id}/containers/{container_id}/files/`

#### Key Parameters

| Parameter | Description |
|---|---|
| `file_type` | `"FILE"` for a single file (e.g. master playlist); `"SEQUENCE"` for numbered segment files |
| `proxy_sequence_type` | `"HLS_PLAYLIST"` for the master playlist; `"A"` for the primary video track |
| `name` | Filename or pattern. For sequences, use printf-style patterns e.g. `seq_%05d.ts` |
| `template` | For sequences, defines the pattern and index range e.g. `seq_%05d.ts [0-1]`. Only sent when `file_type == "SEQUENCE"` |
| `template_engine` | Defaults to `"SIMPLE"`. Only included in the request body for sequences |
| `directory_path` | Storage subdirectory path. Auto-generated via `uuid.uuid1()` if not provided |

- **Returns:** A file object. Key field:

| Field | Description |
|---|---|
| `id` | UUID of the file record — used to request upload URLs |

---

### `get_proxy_file_upload_url`

```python
def get_proxy_file_upload_url(
    api: TestAPI,
    asset_id: str,
    file_id: str,
    path: str = "",
) -> dict
```

Fetches a pre-signed upload URL for a specific file or segment.

- **Method:** `GET`
- **Endpoint:** `/API/files/v1/storage_access/assets/{asset_id}/proxy_files/{file_id}/upload_url/`
- **Query param:** `path` — specifies the target segment filename (e.g. `seq_00000.ts`). Omitted for single files like the master playlist.
- **Returns:** A dict containing:

| Field | Description |
|---|---|
| `upload_url` | Pre-signed URL for direct binary upload to the storage backend |

---

### `upload_file_data`

```python
def upload_file_data(upload_url: str, data: bytes, method: str = "PUT")
```

Uploads raw bytes directly to a pre-signed URL (S3/GCS-style). This call bypasses the iconik API entirely — no auth headers are sent.

| Parameter | Description |
|---|---|
| `upload_url` | Pre-signed URL returned by `get_proxy_file_upload_url` |
| `data` | Raw bytes to upload |
| `method` | HTTP method — defaults to `"PUT"` to match standard pre-signed URL behaviour |

Content-Type is set to `application/octet-stream`.

---

### `get_playlist_content`

```python
def get_playlist_content(
    api: TestAPI,
    asset_id: str,
    version_id: str,
    proxy_id: str,
) -> None
```

Fetches and prints the current `.m3u8` HLS playlist as served by the iconik API. Used to verify the state of the proxy at a given point in the workflow.

- **Method:** `GET`
- **Endpoint:** `/API/files/v1/assets/{asset_id}/versions/{version_id}/proxies/{proxy_id}/hls/`
- **Returns:** Raw playlist text (printed to stdout).

---

## `main()` — Full Execution Flow

1. Parse CLI arguments.
2. Instantiate `TestAPI` with domain, token, and app ID.
3. Call `get_proxy_storage` → extract `storage_id` and `storage_method`.
4. Generate a `proxy_container_id` using `uuid.uuid1()`.
5. Call `create_proxy` → extract `proxy_id` and `version_id`.
6. Call `create_proxy_container` with `segment_duration=6` → extract `container_id`.
7. Call `create_proxy_file` twice:
   - Once for the **master playlist** (`file_type="FILE"`, `proxy_sequence_type="HLS_PLAYLIST"`, `name="master.m3u8"`)
   - Once for the **TS segment sequence** (`file_type="SEQUENCE"`, `proxy_sequence_type="A"`, `name="seq_%05d.ts"`, `template="seq_%05d.ts [0-1]"`)
8. Get a pre-signed URL for `seq_00000.ts` and upload fake TS data.
9. Get a pre-signed URL for `master.m3u8` and upload **Playlist v1** (1 segment, no `#EXT-X-ENDLIST`).
10. Print the current playlist state via `get_playlist_content`.
11. Sleep 30 seconds to simulate active transcoding.
12. Get a pre-signed URL for `seq_00001.ts` and upload fake TS data.
13. Get a pre-signed URL for `master.m3u8` and upload **Playlist v2** (2 segments + `#EXT-X-ENDLIST`).
14. Print the final playlist state.

---

## Data Models

### Storage Object

```json
{
  "id": "<uuid>",
  "method": "S3"
}
```

### Proxy Object

```json
{
  "id": "<uuid>",
  "version_id": "<uuid>",
  "name": "test_proxy.m3u8",
  "format": "m3u8",
  "codec": "",
  "frame_rate": "29.97",
  "resolution": { "width": 1280, "height": 720 },
  "status": "OPEN",
  "proxy_container_id": "<uuid>"
}
```

### Proxy Container Object

```json
{
  "id": "<uuid>",
  "frame_count": 0,
  "frame_rate": 0,
  "segment_duration": 6
}
```

### Proxy File Object (Single File)

```json
{
  "id": "<uuid>",
  "name": "master.m3u8",
  "original_name": "master.m3u8",
  "directory_path": "<uuid>",
  "size": 0,
  "type": "FILE",
  "status": "CLOSED",
  "storage_id": "<uuid>",
  "proxy_sequence_type": "HLS_PLAYLIST"
}
```

### Proxy File Object (Sequence)

```json
{
  "id": "<uuid>",
  "name": "seq_%05d.ts",
  "original_name": "seq_%05d.ts",
  "directory_path": "<uuid>",
  "size": 0,
  "type": "SEQUENCE",
  "status": "CLOSED",
  "storage_id": "<uuid>",
  "proxy_sequence_type": "A",
  "template": "seq_%05d.ts [0-1]",
  "template_engine": "SIMPLE"
}
```

### Upload URL Response

```json
{
  "upload_url": "https://storage.example.com/bucket/path?X-Amz-Signature=..."
}
```

---

## HLS Simulation Explained

The script simulates a **progressive HLS transcode** using two playlist states:

**Playlist v1 — Mid-transcode (no `#EXT-X-ENDLIST`)**

```m3u8
#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:6
#EXT-X-MEDIA-SEQUENCE:0
#EXT-X-PLAYLIST-TYPE:VOD
#EXTINF:6.000000,
seq_00000.ts
```

The absence of `#EXT-X-ENDLIST` signals to HLS clients that the stream is not yet complete and more segments are expected.

**Playlist v2 — Transcode complete (with `#EXT-X-ENDLIST`)**

```m3u8
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
```

The presence of `#EXT-X-ENDLIST` signals that all segments have been written and the VOD asset is fully available. This mirrors the behaviour of a real transcoder progressively writing segments during encoding.

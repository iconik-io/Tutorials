# Iconik Proxy Upload Script — Documentation

## Overview

This script simulates a **proxy creation and HLS (HTTP Live Streaming) upload workflow** against the iconik media asset management API. It creates a proxy (a lower-resolution video representation of an asset), uploads real HLS segments and playlist files to storage, and simulates a progressive transcoding update across two phases.

---

## Table of Contents

1. [Requirements](#requirements)
2. [Usage](#usage)
3. [CLI Arguments](#cli-arguments)
4. [Architecture Overview](#architecture-overview)
5. [Class: TestAPI](#class-testapi)
6. [Segment Set and Constants](#segment-set-and-constants)
7. [Functions](#functions)
   - [build_playlist](#build_playlist)
   - [get_proxy_storage](#get_proxy_storage)
   - [create_proxy](#create_proxy)
   - [create_proxy_container](#create_proxy_container)
   - [create_proxy_file](#create_proxy_file)
   - [get_proxy_file_upload_url](#get_proxy_file_upload_url)
   - [upload_file_data](#upload_file_data)
   - [publish_segment](#publish_segment)
   - [close_proxy](#close_proxy)
   - [get_playlist_content](#get_playlist_content)
8. [main() — Full Execution Flow](#main--full-execution-flow)
9. [Data Models](#data-models)
10. [HLS Simulation Explained](#hls-simulation-explained)

---

## Requirements

- Python 3.10+
- [`requests`](https://pypi.org/project/requests/) library
- The sample segments in `data/` (`seq_00000.ts`, `seq_00001.ts`)

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
  [--segment-delay 30] \
  [-v]
```

Run it from this directory, or from anywhere — segment paths resolve relative to the script, not the working directory.

---

## CLI Arguments

| Argument | Required | Default | Description |
|---|---|---|---|
| `--domain` | No | `https://test.iconik.cloud` | Base URL for the API |
| `--token` | Yes | — | Auth token (`Auth-Token` header) |
| `--app-id` | Yes | — | Application ID (`App-ID` header) |
| `--asset-id` | Yes | — | UUID of the target asset to attach the proxy to |
| `--segment-delay` | No | `30` | Seconds to wait between segments, simulating transcode time |
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

## Segment Set and Constants

The segments the script publishes are declared once, at module level:

```python
SEGMENTS = [
    ("seq_00000.ts", 6.539867),
    ("seq_00001.ts", 5.605600),
]

TARGET_DURATION = max(round(duration) for _, duration in SEGMENTS)  # 7
```

The durations are the **actual** presentation durations of the sample files, from `ffprobe`:

| Segment | Frames | Frame rate | Duration |
|---|---|---|---|
| `seq_00000.ts` | 196 | 30000/1001 | 6.539867s |
| `seq_00001.ts` | 168 | 30000/1001 | 5.605600s |

Use measured durations, not the nominal segment length configured on the transcoder — segments land on keyframe boundaries and drift from the target. Adding a segment to this list is all that is needed to extend the simulation; the playlist, the target duration and the sequence `template` range are all derived from it.

`TARGET_DURATION` is computed across **all** segments, including ones not published yet, because an `EVENT` playlist may only be appended to — the value written in the first playlist has to hold for the whole stream. A real transcoder should use its configured maximum segment length.

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

### `build_playlist`

```python
def build_playlist(segment_count: int, complete: bool) -> str
```

Renders the master playlist covering the first `segment_count` entries of `SEGMENTS`.

| Parameter | Description |
|---|---|
| `segment_count` | How many segments are on storage and safe to advertise |
| `complete` | When `True`, appends `#EXT-X-ENDLIST` |

Three properties of the output matter for growing playback:

- `#EXTM3U` is the literal first line, with no leading whitespace on any line. An indented playlist is not a valid playlist.
- Each `#EXTINF` is immediately followed by its segment URI. An `#EXTINF` with no URI after it declares nothing, and the segment is never fetched.
- The type is `EVENT` and `#EXT-X-ENDLIST` is withheld until the final segment, which is what keeps the player reloading. `VOD` would be wrong: a VOD playlist is defined as never changing, so a player reads it once and stops at whatever it saw first.

---

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
  "format": "HLS",
  "codec": "h264",
  "frame_rate": "29.97",
  "resolution": { "width": 1280, "height": 720 },
  "status": "GROWING",
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

> **Note:** `segment_duration` must match the `#EXT-X-TARGETDURATION` value in the uploaded HLS playlist — `7` for the sample segments, since the longest is 6.539867s and RFC 8216 rounds EXTINF to the nearest integer when comparing against the target duration.

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
    directory_path: str,
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
| `directory_path` | Storage subdirectory path. **Required, and the same value must be passed for the playlist record and the sequence record** — the playlist names its segments by bare filename, so they must resolve alongside `master.m3u8` on storage. Generate one `uuid.uuid1()` per container and reuse it. |

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
def upload_file_data(upload_url: str, data: bytes, storage_method: str)
```

Uploads raw bytes directly to a pre-signed URL. This call bypasses the iconik API entirely — no auth headers are sent.

| Parameter | Description |
|---|---|
| `upload_url` | Pre-signed URL returned by `get_proxy_file_upload_url` |
| `data` | Raw bytes to upload |
| `storage_method` | The `method` from `get_proxy_storage`, which selects the upload flow |

The flow differs per backend, so a single plain `PUT` is not portable:

| `storage_method` | Flow |
|---|---|
| `GCS` | `POST` with `x-goog-resumable: start` and `Content-Length: 0`, then `PUT` the payload to the URL in the `location` response header |
| `AZURE` | `PUT` with `x-ms-blob-type: BlockBlob` |
| `S3`, `B2`, `FILE` | plain `PUT` |

Content-Type is `application/octet-stream` in all cases.

---

### `publish_segment`

```python
def publish_segment(
    api: TestAPI,
    asset_id: str,
    ts_sequence_id: str,
    playlist_file_id: str,
    storage_method: str,
    index: int,
) -> None
```

Publishes one segment: reads `SEGMENTS[index]` from `data/`, uploads it to its pre-signed URL, and only then republishes `master.m3u8` including it. The ordering is deliberate — advertising a segment before it is on storage gives the player a 404 and stalls playback. When `index` is the last entry, the republished playlist carries `#EXT-X-ENDLIST`.

---

### `close_proxy`

```python
def close_proxy(api: TestAPI, asset_id: str, proxy_id: str) -> dict
```

Moves the proxy from `GROWING` to `CLOSED`, marking it complete.

- **Method:** `PATCH`
- **Endpoint:** `/API/files/v1/assets/{asset_id}/proxies/{proxy_id}/`
- **Request body:**

```json
{ "status": "CLOSED" }
```

`#EXT-X-ENDLIST` is a playlist-level signal to HLS clients; it does not change the proxy record. The proxy stays `GROWING` until this call is made.

> Send it **after** the playlist carrying `#EXT-X-ENDLIST` is on storage, never before — closing a proxy whose playlist is still missing its last segments leaves the asset permanently short.

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
6. Call `create_proxy_container` with `segment_duration=TARGET_DURATION` → extract `container_id`.
7. Generate one `directory_path` (`uuid.uuid1()`) shared by every file in the container.
8. Call `create_proxy_file` twice, passing that same `directory_path` to both:
   - Once for the **master playlist** (`file_type="FILE"`, `proxy_sequence_type="HLS_PLAYLIST"`, `name="master.m3u8"`)
   - Once for the **TS segment sequence** (`file_type="SEQUENCE"`, `proxy_sequence_type="A"`, `name="seq_%05d.ts"`, `template="seq_%05d.ts [0-1]"`)
9. For each entry in `SEGMENTS`, call `publish_segment`, which:
   - uploads the `.ts` file from `data/` to its pre-signed URL, **then**
   - republishes `master.m3u8` including that segment — never the other way round, since a player must not be told about a segment it cannot fetch yet.
   The last segment's playlist is the one that carries `#EXT-X-ENDLIST`.
10. Print the playlist state via `get_playlist_content` after each publish.
11. Between segments, sleep `--segment-delay` seconds to simulate active transcoding.
12. Once the loop finishes — so the playlist with `#EXT-X-ENDLIST` is on storage — call `close_proxy` to move the proxy from `GROWING` to `CLOSED`.

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
  "format": "HLS",
  "codec": "h264",
  "frame_rate": "29.97",
  "resolution": { "width": 1280, "height": 720 },
  "status": "GROWING",
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
#EXT-X-TARGETDURATION:7
#EXT-X-MEDIA-SEQUENCE:0
#EXT-X-PLAYLIST-TYPE:EVENT
#EXTINF:6.539867,
seq_00000.ts
```

The `EVENT` playlist type plus the absence of `#EXT-X-ENDLIST` signals to HLS clients that the stream is not yet complete and more segments are expected, so they keep reloading the playlist. Do not use `#EXT-X-PLAYLIST-TYPE:VOD` here — a VOD playlist is defined as never changing, so the player reads it once and stops instead of picking up the segments appended later.

**Playlist v2 — Transcode complete (with `#EXT-X-ENDLIST`)**

```m3u8
#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:7
#EXT-X-MEDIA-SEQUENCE:0
#EXT-X-PLAYLIST-TYPE:EVENT
#EXTINF:6.539867,
seq_00000.ts
#EXTINF:5.605600,
seq_00001.ts
#EXT-X-ENDLIST
```

The presence of `#EXT-X-ENDLIST` signals that all segments have been written and the asset is fully available, and the player stops reloading. The proxy record is then closed separately via `close_proxy`. This mirrors the behaviour of a real transcoder progressively writing segments during encoding.

# Iconik Proxy Upload Script — Documentation

## Overview

This script simulates a **proxy creation and HLS (HTTP Live Streaming) upload workflow** against the iconik media asset management API. It creates a proxy (a lower-resolution video representation of an asset), uploads real HLS segments and playlist files to storage, and simulates a progressive transcoding update across two phases.

By default the segments carry muxed audio and video. With `--separate-audio-video` the script publishes separate renditions instead: a master playlist pointing at `video.m3u8` and `audio.m3u8`, each with its own segments. See [Separate Audio and Video Renditions](#separate-audio-and-video-renditions).

---

## Table of Contents

1. [Requirements](#requirements)
2. [Usage](#usage)
3. [CLI Arguments](#cli-arguments)
4. [Architecture Overview](#architecture-overview)
5. [Class: TestAPI](#class-testapi)
6. [Segment Set and Constants](#segment-set-and-constants)
7. [Functions](#functions)
   - [build_media_playlist](#build_media_playlist)
   - [build_master_playlist](#build_master_playlist)
   - [get_asset_version_id](#get_asset_version_id)
   - [get_proxy_storage](#get_proxy_storage)
   - [create_proxy](#create_proxy)
   - [create_proxy_container](#create_proxy_container)
   - [create_proxy_file](#create_proxy_file)
   - [get_proxy_file_upload_url](#get_proxy_file_upload_url)
   - [upload_file_data](#upload_file_data)
   - [upload_proxy_file, upload_segment, upload_playlist](#upload_proxy_file-upload_segment-upload_playlist)
   - [register_muxed_files / register_separate_av_files](#register_muxed_files--register_separate_av_files)
   - [publish_segment / publish_separate_av_segment](#publish_segment--publish_separate_av_segment)
   - [close_proxy](#close_proxy)
   - [get_playlist_content](#get_playlist_content)
8. [main() — Full Execution Flow](#main--full-execution-flow)
9. [Data Models](#data-models)
10. [HLS Simulation Explained](#hls-simulation-explained)
11. [Separate Audio and Video Renditions](#separate-audio-and-video-renditions)

---

## Requirements

- Python 3.10+
- [`requests`](https://pypi.org/project/requests/) library
- The sample segments in `data/`: `seq_00000.ts` and `seq_00001.ts` (muxed), plus `video_0000*.ts` and `audio_0000*.ts` (split, for `--separate-audio-video`)

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
  [--separate-audio-video] \
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
| `--separate-audio-video` | No | off | Publish separate video and audio renditions instead of one muxed rendition |
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
SEGMENTS = [               # muxed, in video frames
    ("seq_00000.ts", 196),
    ("seq_00001.ts", 168),
]
VIDEO_SEGMENTS = [         # video-only, in video frames
    ("video_00000.ts", 196),
    ("video_00001.ts", 168),
]
AUDIO_SEGMENTS = [         # audio-only, in AAC frames (1024 samples @ 48 kHz)
    ("audio_00000.ts", 305),
    ("audio_00001.ts", 263),
]

MUXED_ENTRIES = playlist_entries(SEGMENTS, duration_seconds)        # (name, seconds)
VIDEO_ENTRIES = playlist_entries(VIDEO_SEGMENTS, duration_seconds)
AUDIO_ENTRIES = playlist_entries(AUDIO_SEGMENTS, audio_duration_seconds)

TARGET_DURATION = max(round(d) for _, d in MUXED_ENTRIES + VIDEO_ENTRIES + AUDIO_ENTRIES)  # 7
```

The counts give the **actual** presentation durations of the sample files, from `ffprobe`:

| Segment | Frames | Frame rate | Duration |
|---|---|---|---|
| `seq_00000.ts` | 196 | 30000/1001 | 6.539867s |
| `seq_00001.ts` | 168 | 30000/1001 | 5.605600s |
| `video_00000.ts` | 196 | 30000/1001 | 6.539867s |
| `video_00001.ts` | 168 | 30000/1001 | 5.605600s |
| `audio_00000.ts` | 305 AAC | 48000/1024 | 6.506667s |
| `audio_00001.ts` | 263 AAC | 48000/1024 | 5.610667s |

The `video_`/`audio_` files are the muxed segments split with stream copy and `-copyts`, so their timestamps, and therefore A/V sync, are unchanged:

```bash
ffmpeg -copyts -i seq_00000.ts -map 0:v -c copy -muxdelay 0 video_00000.ts
ffmpeg -copyts -i seq_00000.ts -map 0:a -c copy -muxdelay 0 audio_00000.ts
```

Audio segment durations differ from the video ones because AAC frames (1024 samples) don't line up with video frames. Each media playlist uses its own segments' durations.

Use measured durations, not the nominal segment length configured on the transcoder — segments land on keyframe boundaries and drift from the target. Adding a segment to these lists is all that is needed to extend the simulation; the playlists, the target duration and the sequence `template` ranges are all derived from them. All three lists must have the same length.

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

### `build_media_playlist`

```python
def build_media_playlist(entries: list[tuple[str, float]], complete: bool) -> str
```

Renders a media playlist listing `entries`, given as `(filename, seconds)` pairs. It is used for the muxed `master.m3u8` and for `video.m3u8` / `audio.m3u8` in separate mode.

| Parameter | Description |
|---|---|
| `entries` | The segments that are on storage and safe to advertise, e.g. `VIDEO_ENTRIES[:index + 1]` |
| `complete` | When `True`, appends `#EXT-X-ENDLIST` |

Three properties of the output matter for growing playback:

- `#EXTM3U` is the literal first line, with no leading whitespace on any line. An indented playlist is not a valid playlist.
- Each `#EXTINF` is immediately followed by its segment URI. An `#EXTINF` with no URI after it declares nothing, and the segment is never fetched.
- The type is `EVENT` and `#EXT-X-ENDLIST` is withheld until the final segment, which is what keeps the player reloading. `VOD` would be wrong: a VOD playlist is defined as never changing, so a player reads it once and stops at whatever it saw first.

---

### `build_master_playlist`

```python
def build_master_playlist() -> str
```

Renders the master playlist for `--separate-audio-video`. It contains the minimum needed to tie the video rendition to a separate audio rendition:

```m3u8
#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="audio",DEFAULT=YES,URI="audio.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=3854826,CODECS="avc1.640029,mp4a.40.2",AUDIO="audio"
video.m3u8
```

- `BANDWIDTH` comes from `peak_bandwidth()`: the largest video and audio segment pair, in bits per second.
- `CODECS` is the `CODECS` constant: H.264 High@4.1 read from the sample's SPS, plus AAC-LC.
- The master doesn't change while the proxy grows, so it is uploaded once. It never carries `#EXT-X-ENDLIST`.

---

### `get_asset_version_id`

```python
def get_asset(api: TestAPI, asset_id: str) -> dict
def get_asset_version_id(api: TestAPI, asset_id: str) -> str
```

Resolves the asset version the proxy will be attached to.

- **Method:** `GET`
- **Endpoint:** `/API/assets/v1/assets/{asset_id}/`

The version is read from the asset, not from the `create_proxy` response, so it is known before any proxy exists and does not depend on what the proxy endpoint echoes back.

Resolution order:

| Source | When used |
|---|---|
| `default_version_id` | The asset's current version — preferred whenever present |
| `versions[0].id` | Fallback for records that only carry the `versions` array |

Raises `RuntimeError` if the asset has no versions.

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

- **Returns:** A proxy object. Key field used downstream:

| Field | Description |
|---|---|
| `id` | UUID of the proxy — used in all subsequent proxy-scoped endpoints |

The response also carries a `version_id`, but the script uses the one resolved by [`get_asset_version_id`](#get_asset_version_id) instead.

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

### `upload_proxy_file`, `upload_segment`, `upload_playlist`

```python
def upload_proxy_file(api, asset_id, file_id, data: bytes, storage_method, path="") -> None
def upload_segment(api, asset_id, sequence_id, storage_method, name, duration) -> None
def upload_playlist(api, asset_id, playlist_file_id, storage_method, name, entries, complete) -> None
```

Small wrappers around [`get_proxy_file_upload_url`](#get_proxy_file_upload_url) and [`upload_file_data`](#upload_file_data):

- `upload_proxy_file` fetches a pre-signed URL for a proxy file record and uploads `data` to it. Pass `path` for a member of a `SEQUENCE` record; leave it empty for a `FILE` record.
- `upload_segment` reads `data/<name>` and uploads it into a `SEQUENCE` record.
- `upload_playlist` renders `entries` with [`build_media_playlist`](#build_media_playlist) and overwrites the playlist record.

---

### `register_muxed_files` / `register_separate_av_files`

```python
def register_muxed_files(api, asset_id, proxy_id, container_id, storage_id, directory_path) -> dict[str, str]
def register_separate_av_files(api, asset_id, proxy_id, container_id, storage_id, directory_path) -> dict[str, str]
```

Each creates the proxy file records for one layout via [`create_proxy_file`](#create_proxy_file) and returns a map from record name to proxy file id.

| Layout | Records |
|---|---|
| Muxed (default) | `master.m3u8` (FILE, HLS_PLAYLIST), `seq_%05d.ts` (SEQUENCE, A) |
| Separate | `master.m3u8`, `video.m3u8`, `audio.m3u8` (FILE, HLS_PLAYLIST), `video_%05d.ts`, `audio_%05d.ts` (SEQUENCE, A) |

---

### `publish_segment` / `publish_separate_av_segment`

```python
def publish_segment(api, asset_id, ts_sequence_id, playlist_file_id, storage_method, index) -> None
def publish_separate_av_segment(api, asset_id, files: dict[str, str], storage_method, index) -> None
```

`publish_segment` publishes one muxed segment. It uploads `seq_<index>.ts` and only then republishes `master.m3u8` including it. The ordering is deliberate: advertising a segment before it is on storage gives the player a 404 and stalls playback.

`publish_separate_av_segment` applies the same rule to two renditions:

1. Upload `video_<index>.ts` and `audio_<index>.ts`.
2. Republish `video.m3u8` and `audio.m3u8`.
3. On the first call only, upload the master playlist. It is published after the media playlists it points at exist.

When `index` is the last entry, the republished playlists carry `#EXT-X-ENDLIST`.

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
    path: str = "",
) -> None
```

Fetches and prints the current `.m3u8` HLS playlist as served by the iconik API. Used to verify the state of the proxy at a given point in the workflow.

- **Method:** `GET`
- **Endpoint:** `/API/files/v1/assets/{asset_id}/versions/{version_id}/proxies/{proxy_id}/hls/`
- **Query param:** `path`. Omit it for the master playlist; pass a media playlist name (`video.m3u8`, `audio.m3u8`) to fetch that playlist. This is the same URL iconik writes into the master it serves.
- **Returns:** Raw playlist text (printed to stdout).

---

## `main()` — Full Execution Flow

1. Parse CLI arguments.
2. Instantiate `TestAPI` with domain, token, and app ID.
3. Call `get_asset_version_id` → resolve `version_id` from the asset.
4. Call `get_proxy_storage` → extract `storage_id` and `storage_method`.
5. Generate a `proxy_container_id` using `uuid.uuid1()`.
6. Call `create_proxy` → extract `proxy_id`.
7. Call `create_proxy_container` with `segment_duration=TARGET_DURATION` → extract `container_id`.
8. Generate one `directory_path` (`uuid.uuid1()`) shared by every file in the container.
9. Create the proxy file records, all with that same `directory_path`:
   - default: `register_muxed_files`, which creates the **master playlist** (`FILE`, `HLS_PLAYLIST`, `master.m3u8`) and the **TS segment sequence** (`SEQUENCE`, `A`, `seq_%05d.ts`, `template="seq_%05d.ts [0-2]"`)
   - `--separate-audio-video`: `register_separate_av_files`. See [Separate Audio and Video Renditions](#separate-audio-and-video-renditions).
10. For each segment, call `publish_segment` (or `publish_separate_av_segment` in separate mode), which:
   - uploads the `.ts` file from `data/` to its pre-signed URL, **then**
   - republishes `master.m3u8` including that segment — never the other way round, since a player must not be told about a segment it cannot fetch yet.
   The last segment's playlist is the one that carries `#EXT-X-ENDLIST`.
11. Print the playlist state via `get_playlist_content` after each publish. In separate mode, the master, `video.m3u8` and `audio.m3u8` are all printed.
12. Between segments, sleep `--segment-delay` seconds to simulate active transcoding.
13. Once the loop finishes — so the playlist with `#EXT-X-ENDLIST` is on storage — call `close_proxy` to move the proxy from `GROWING` to `CLOSED`.

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

---

## Separate Audio and Video Renditions

With `--separate-audio-video` the proxy is published in the layout iconik uses for DRM proxies, without the DRM. Video and audio are separate renditions, each with its own media playlist and segments, tied together by a master playlist.

```
master.m3u8 ──► #EXT-X-MEDIA TYPE=AUDIO ──► audio.m3u8 ──► audio_00000.ts, audio_00001.ts
            └─► #EXT-X-STREAM-INF ────────► video.m3u8 ──► video_00000.ts, video_00001.ts
```

Proxy file records, all under one `directory_path`:

| `name` | `type` | `proxy_sequence_type` | `template` |
|---|---|---|---|
| `master.m3u8` | `FILE` | `HLS_PLAYLIST` | — |
| `video.m3u8` | `FILE` | `HLS_PLAYLIST` | — |
| `audio.m3u8` | `FILE` | `HLS_PLAYLIST` | — |
| `video_%05d.ts` | `SEQUENCE` | `A` | `video_%05d.ts [0-2]` |
| `audio_%05d.ts` | `SEQUENCE` | `A` | `audio_%05d.ts [0-2]` |

Things that are easy to get wrong:

- **Audio segments are type `A` too.** iconik looks up every segment URI, in any media playlist, among the `A` records.
- **Media playlist names.** iconik serves `hls/?path=<name>` by turning `<name>` into a sequence pattern (digits before the extension become `%d` / `%05d`) and looking for an `HLS_PLAYLIST` record with that name. `video.m3u8` has no digits, so a `FILE` record named `video.m3u8` works. `stream_0.m3u8` would become `stream_%d.m3u8`, and so would need a single `SEQUENCE` record named `stream_%d.m3u8`. A `FILE` record named `stream_0.m3u8` is never matched and the request returns `425`.
- **Ordering.** Upload both segments, then both media playlists. Publish the master only once the media playlists it points at exist.
- **Durations.** Audio `#EXTINF` values come from the audio segments, not the video ones.

Served playlists after the second segment:

```m3u8
# hls/  (abridged; iconik rewrites the URIs and may reorder attributes)
#EXTM3U
#EXT-X-MEDIA:URI="/API/files/v1/assets/.../hls/?path=audio.m3u8",TYPE=AUDIO,GROUP-ID="audio",NAME="audio",DEFAULT=YES
#EXT-X-STREAM-INF:BANDWIDTH=3854826,CODECS="avc1.640029,mp4a.40.2",AUDIO="audio"
/API/files/v1/assets/.../hls/?path=video.m3u8
```

```m3u8
# as uploaded: audio.m3u8
#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:7
#EXT-X-MEDIA-SEQUENCE:0
#EXT-X-PLAYLIST-TYPE:EVENT
#EXTINF:6.506667,
audio_00000.ts
#EXTINF:5.610667,
audio_00001.ts
#EXT-X-ENDLIST
```

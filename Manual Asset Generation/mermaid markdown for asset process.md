#Editor at https://mermaid-js.github.io/mermaid-live-editor/

#Asset creation flow
sequenceDiagram
new asset process->>+asset: POST assets/v1/assets/
note right of new asset process: JSON payload of asset information
asset-->>-new asset process: asset id
new asset process->>+format: POST files/v1/assets/{asset_id}/formats/
note right of new asset process: JSON payload of format information (metadata)
format-->>-new asset process: format id
new asset process->>+file_set: POST files/v1/assets/{asset_id}/file_sets/
note right of new asset process: JSON payload of fileset information (components)
file_set-->>-new asset process: file_set id
new asset process->>+file: 
note right of new asset process: JSON payload of file information (path, name, checksum, etc)
loop add multiple files to file_set
    new asset process->>+file: POST files/v1/assets/{asset_id}/files/
    file-->>-new asset process: file id
end
new asset process->>new asset process: Generate new proxy
note right of new asset process: MP4, max 1080p, max 6Mb, no b frames
new asset process->>+proxy: POST files/v1/assets/{asset_id}/proxies/
proxy-->>-new asset process: proxy id and signed upload URL
new proxy process-->>+proxy: upload to signed url
proxy-->>-new proxy process: success 200
new proxy process-->>+proxy: PATCH files/v1/assets/{asset_id}/proxies/
proxy-->>-new proxy process: success 200
note right of proxy: JSON payload to close proxy file
new asset process->>+proxy: POST files/v1/assets/{asset_id}/proxies/{proxy_id}/keyframes/
note right of new asset process: JSON payload to create keyframes

#Asset data model
graph TD
    A[Asset] --> |Format| B[ORIGINAL]
    A --> |Format| C[PPRO_PROXY]
    B --> |File_Set| D[GCS]
    B --> |File_Set| E[ISG/File]
    C --> |File_Set| F[Azure Blob]
    C --> |File_Set| G[Amazon S3]
    D --> |File| H[Video MXF]
    D --> |File| I[Audio MXF]
    D --> |File| J[Audio MXF]
    D --> |File| K[Audio MXF]
    D --> |File| L[Audio MXF]
    E --> |File| M[Video MXF]
    E --> |File| N[Audio MXF]
    E --> |File| O[Audio MXF]
    E --> |File| P[Audio MXF]
    E --> |File| Q[Audio MXF]
    F --> |File| R[Prores MOV]
    G --> |File| S[Prores MOV]
    A --> |Proxy| T[H.264 MP4 web proxy]
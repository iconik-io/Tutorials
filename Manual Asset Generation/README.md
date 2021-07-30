# Creating new assets by hand using iconik
I've been asked several times to explain how a new asset is created in iconik and what needs to be done with the API to generate a new asset in iconik.  To do this, it is important to understand iconik's data model when it comes to assets.

An asset has a one-to-many relationship when it comes to formats, storages, and files inside iconik.   A single asset can reference *many* different files on *many* different storages.  This is an example of the model:

[![](https://mermaid.ink/img/eyJjb2RlIjoiZ3JhcGggVERcbiAgICBBW0Fzc2V0XSAtLT4gfEZvcm1hdHwgQltPUklHSU5BTF1cbiAgICBBIC0tPiB8Rm9ybWF0fCBDW1BQUk9fUFJPWFldXG4gICAgQiAtLT4gfEZpbGVfU2V0fCBEW0dDU11cbiAgICBCIC0tPiB8RmlsZV9TZXR8IEVbSVNHL0ZpbGVdXG4gICAgQyAtLT4gfEZpbGVfU2V0fCBGW0F6dXJlIEJsb2JdXG4gICAgQyAtLT4gfEZpbGVfU2V0fCBHW0FtYXpvbiBTM11cbiAgICBEIC0tPiB8RmlsZXwgSFtWaWRlbyBNWEZdXG4gICAgRCAtLT4gfEZpbGV8IElbQXVkaW8gTVhGXVxuICAgIEQgLS0-IHxGaWxlfCBKW0F1ZGlvIE1YRl1cbiAgICBEIC0tPiB8RmlsZXwgS1tBdWRpbyBNWEZdXG4gICAgRCAtLT4gfEZpbGV8IExbQXVkaW8gTVhGXVxuICAgIEUgLS0-IHxGaWxlfCBNW1ZpZGVvIE1YRl1cbiAgICBFIC0tPiB8RmlsZXwgTltBdWRpbyBNWEZdXG4gICAgRSAtLT4gfEZpbGV8IE9bQXVkaW8gTVhGXVxuICAgIEUgLS0-IHxGaWxlfCBQW0F1ZGlvIE1YRl1cbiAgICBFIC0tPiB8RmlsZXwgUVtBdWRpbyBNWEZdXG4gICAgRiAtLT4gfEZpbGV8IFJbUHJvcmVzIE1PVl1cbiAgICBHIC0tPiB8RmlsZXwgU1tQcm9yZXMgTU9WXVxuICAgIEEgLS0-IHxQcm94eXwgVFtILjI2NCBNUDQgd2ViIHByb3h5XSIsIm1lcm1haWQiOnsidGhlbWUiOiJkZWZhdWx0In0sInVwZGF0ZUVkaXRvciI6ZmFsc2UsImF1dG9TeW5jIjp0cnVlLCJ1cGRhdGVEaWFncmFtIjpmYWxzZX0)](https://mermaid-js.github.io/mermaid-live-editor/edit##eyJjb2RlIjoiZ3JhcGggVERcbiAgICBBW0Fzc2V0XSAtLT4gfEZvcm1hdHwgQltPUklHSU5BTF1cbiAgICBBIC0tPiB8Rm9ybWF0fCBDW1BQUk9fUFJPWFldXG4gICAgQiAtLT4gfEZpbGVfU2V0fCBEW0dDU11cbiAgICBCIC0tPiB8RmlsZV9TZXR8IEVbSVNHL0ZpbGVdXG4gICAgQyAtLT4gfEZpbGVfU2V0fCBGW0F6dXJlIEJsb2JdXG4gICAgQyAtLT4gfEZpbGVfU2V0fCBHW0FtYXpvbiBTM11cbiAgICBEIC0tPiB8RmlsZXwgSFtWaWRlbyBNWEZdXG4gICAgRCAtLT4gfEZpbGV8IElbQXVkaW8gTVhGXVxuICAgIEQgLS0-IHxGaWxlfCBKW0F1ZGlvIE1YRl1cbiAgICBEIC0tPiB8RmlsZXwgS1tBdWRpbyBNWEZdXG4gICAgRCAtLT4gfEZpbGV8IExbQXVkaW8gTVhGXVxuICAgIEUgLS0-IHxGaWxlfCBNW1ZpZGVvIE1YRl1cbiAgICBFIC0tPiB8RmlsZXwgTltBdWRpbyBNWEZdXG4gICAgRSAtLT4gfEZpbGV8IE9bQXVkaW8gTVhGXVxuICAgIEUgLS0-IHxGaWxlfCBQW0F1ZGlvIE1YRl1cbiAgICBFIC0tPiB8RmlsZXwgUVtBdWRpbyBNWEZdXG4gICAgRiAtLT4gfEZpbGV8IFJbUHJvcmVzIE1PVl1cbiAgICBHIC0tPiB8RmlsZXwgU1tQcm9yZXMgTU9WXVxuICAgIEEgLS0-IHxQcm94eXwgVFtILjI2NCBNUDQgXSIsIm1lcm1haWQiOiJ7XG4gIFwidGhlbWVcIjogXCJkZWZhdWx0XCJcbn0iLCJ1cGRhdGVFZGl0b3IiOmZhbHNlLCJhdXRvU3luYyI6dHJ1ZSwidXBkYXRlRGlhZ3JhbSI6ZmFsc2V9)

There are 6 key elements understand when creating a new asset in iconik and how to relate all the appropriate bits to make it feel complete.

## Assets
Assets are the core building block in iconik.  These are the references to both where the files live, but also associated metadata, relationships, collection membership, time based comments and metadata, transcriptions, etc.   An asset is *not* just one file, but a pointer to a collection of files.  It *can* only reference a single file and nothing else, but that file will still fall under the data model to be represented properly in iconik's UI.  More often than not, an Asset has a minimum of two files - the ORIGINAL file and the web proxy.

## Formats
Formats contain the technical metadata regarding the files it describes.   At the simplest, it is the frame size, frame rate, codec.   It can include extensive custom metadata (camera exposure, color space, bit depth, etc).  Formats themselves describe to the user what the file_set contains.  

## File Sets
File sets contain a reference to all the components of a given Format, such as individual audio/video track metadata, but also additional metadata like text tracks or ancillary technical metadata.  File Sets also contain information regarding the actual storage an asset is represented on (AWS, GCS, Azure, S3, B2, Filesystem, etc)   These are defined as components under the File Set.  A File Set can contain multiple files or a single file, but there is always a File Set for any represented data on storage.

## Files
Files are...well...files!  These are the actual references to the file itself.  The information sent to iconik when registering a file are around create/mod times, checksums, sizes, etc.   Files go into File Sets.  File Sets go into Formats.  Formats go into an Asset.  Assets go into Collections.

And now you know the basic iconik file management data model.

## Keyframe Maps/Posters
Keyframe maps are used by iconik to represent very low resolution/framerate previews of media on the search page.  If an asset has a keyframe map and poster frame associated with it, these will be what users see in the search results page when they scrub/mouse over an Asset in thumbnail view (keyframe map) and will also show a static image in search results when not moused over in both thumbnail view and list view (poster)

## Process for creating a complete asset
Below is a process diagram of creating your own "complete" asset by hand in iconik using our API.   Using this method, you can support any file/format representation you like, and also support a wide variety of assets that iconik itself does not natively support via point-and-click use.  Below is an example flow diagram for creating this all by hand.

[![](https://mermaid.ink/img/eyJjb2RlIjoic2VxdWVuY2VEaWFncmFtXG5uZXcgYXNzZXQgcHJvY2Vzcy0-Pithc3NldDogUE9TVCBhc3NldHMvdjEvYXNzZXRzL1xubm90ZSByaWdodCBvZiBuZXcgYXNzZXQgcHJvY2VzczogSlNPTiBwYXlsb2FkIG9mIGFzc2V0IGluZm9ybWF0aW9uXG5hc3NldC0tPj4tbmV3IGFzc2V0IHByb2Nlc3M6IGFzc2V0IGlkXG5uZXcgYXNzZXQgcHJvY2Vzcy0-Pitmb3JtYXQ6IFBPU1QgZmlsZXMvdjEvYXNzZXRzL3thc3NldF9pZH0vZm9ybWF0cy9cbm5vdGUgcmlnaHQgb2YgbmV3IGFzc2V0IHByb2Nlc3M6IEpTT04gcGF5bG9hZCBvZiBmb3JtYXQgaW5mb3JtYXRpb24gKG1ldGFkYXRhKVxuZm9ybWF0LS0-Pi1uZXcgYXNzZXQgcHJvY2VzczogZm9ybWF0IGlkXG5uZXcgYXNzZXQgcHJvY2Vzcy0-PitmaWxlX3NldDogUE9TVCBmaWxlcy92MS9hc3NldHMve2Fzc2V0X2lkfS9maWxlX3NldHMvXG5ub3RlIHJpZ2h0IG9mIG5ldyBhc3NldCBwcm9jZXNzOiBKU09OIHBheWxvYWQgb2YgZmlsZXNldCBpbmZvcm1hdGlvbiAoY29tcG9uZW50cylcbmZpbGVfc2V0LS0-Pi1uZXcgYXNzZXQgcHJvY2VzczogZmlsZV9zZXQgaWRcbm5ldyBhc3NldCBwcm9jZXNzLT4-K2ZpbGU6IFxubm90ZSByaWdodCBvZiBuZXcgYXNzZXQgcHJvY2VzczogSlNPTiBwYXlsb2FkIG9mIGZpbGUgaW5mb3JtYXRpb24gKHBhdGgsIG5hbWUsIGNoZWNrc3VtLCBldGMpXG5sb29wIGFkZCBtdWx0aXBsZSBmaWxlcyB0byBmaWxlX3NldFxuICAgIG5ldyBhc3NldCBwcm9jZXNzLT4-K2ZpbGU6IFBPU1QgZmlsZXMvdjEvYXNzZXRzL3thc3NldF9pZH0vZmlsZXMvXG4gICAgZmlsZS0tPj4tbmV3IGFzc2V0IHByb2Nlc3M6IGZpbGUgaWRcbmVuZFxubmV3IGFzc2V0IHByb2Nlc3MtPj4rcHJveHk6IFBPU1QgZmlsZXMvdjEvYXNzZXRzL3thc3NldF9pZH0vcHJveGllcy9cbnByb3h5LS0-Pi1uZXcgYXNzZXQgcHJvY2VzczogcHJveHkgaWQgYW5kIHNpZ25lZCB1cGxvYWQgVVJMXG5uZXcgcHJveHkgcHJvY2Vzcy0tPj4rcHJveHk6IHVwbG9hZCB0byBzaWduZWQgdXJsXG5wcm94eS0tPj4tbmV3IHByb3h5IHByb2Nlc3M6IHN1Y2Nlc3MgMjAwXG5uZXcgcHJveHkgcHJvY2Vzcy0tPj4rcHJveHk6IFBBVENIIGZpbGVzL3YxL2Fzc2V0cy97YXNzZXRfaWR9L3Byb3hpZXMvXG5wcm94eS0tPj4tbmV3IHByb3h5IHByb2Nlc3M6IHN1Y2Nlc3MgMjAwXG5ub3RlIHJpZ2h0IG9mIHByb3h5OiBKU09OIHBheWxvYWQgdG8gY2xvc2UgcHJveHkgZmlsZVxubmV3IGFzc2V0IHByb2Nlc3MtPj4rcHJveHk6IFBPU1QgZmlsZXMvdjEvYXNzZXRzL3thc3NldF9pZH0vcHJveGllcy97cHJveHlfaWR9L2tleWZyYW1lcy9cbm5vdGUgcmlnaHQgb2YgbmV3IGFzc2V0IHByb2Nlc3M6IEpTT04gcGF5bG9hZCB0byBjcmVhdGUga2V5ZnJhbWVzXG4iLCJtZXJtYWlkIjp7InRoZW1lIjoiZGVmYXVsdCJ9LCJ1cGRhdGVFZGl0b3IiOmZhbHNlLCJhdXRvU3luYyI6dHJ1ZSwidXBkYXRlRGlhZ3JhbSI6ZmFsc2V9)](https://mermaid-js.github.io/mermaid-live-editor/edit##eyJjb2RlIjoic2VxdWVuY2VEaWFncmFtXG5uZXcgYXNzZXQgcHJvY2Vzcy0-Pithc3NldDogUE9TVCBhc3NldHMvdjEvYXNzZXRzL1xubm90ZSByaWdodCBvZiBuZXcgYXNzZXQgcHJvY2VzczogSlNPTiBwYXlsb2FkIG9mIGFzc2V0IGluZm9ybWF0aW9uXG5hc3NldC0tPj4tbmV3IGFzc2V0IHByb2Nlc3M6IGFzc2V0IGlkXG5uZXcgYXNzZXQgcHJvY2Vzcy0-Pitmb3JtYXQ6IFBPU1QgZmlsZXMvdjEvYXNzZXRzL3thc3NldF9pZH0vZm9ybWF0cy9cbm5vdGUgcmlnaHQgb2YgbmV3IGFzc2V0IHByb2Nlc3M6IEpTT04gcGF5bG9hZCBvZiBmb3JtYXQgaW5mb3JtYXRpb24gKG1ldGFkYXRhKVxuZm9ybWF0LS0-Pi1uZXcgYXNzZXQgcHJvY2VzczogZm9ybWF0IGlkXG5uZXcgYXNzZXQgcHJvY2Vzcy0-PitmaWxlX3NldDogUE9TVCBmaWxlcy92MS9hc3NldHMve2Fzc2V0X2lkfS9maWxlX3NldHMvXG5ub3RlIHJpZ2h0IG9mIG5ldyBhc3NldCBwcm9jZXNzOiBKU09OIHBheWxvYWQgb2YgZmlsZXNldCBpbmZvcm1hdGlvbiAoY29tcG9uZW50cylcbmZpbGVfc2V0LS0-Pi1uZXcgYXNzZXQgcHJvY2VzczogZmlsZV9zZXQgaWRcbm5ldyBhc3NldCBwcm9jZXNzLT4-K2ZpbGU6IFxubm90ZSByaWdodCBvZiBuZXcgYXNzZXQgcHJvY2VzczogSlNPTiBwYXlsb2FkIG9mIGZpbGUgaW5mb3JtYXRpb24gKHBhdGgsIG5hbWUsIGNoZWNrc3VtLCBldGMpXG5sb29wIGFkZCBtdWx0aXBsZSBmaWxlcyB0byBmaWxlX3NldFxuICAgIG5ldyBhc3NldCBwcm9jZXNzLT4-K2ZpbGU6IFBPU1QgZmlsZXMvdjEvYXNzZXRzL3thc3NldF9pZH0vZmlsZXMvXG4gICAgZmlsZS0tPj4tbmV3IGFzc2V0IHByb2Nlc3M6IGZpbGUgaWRcbmVuZFxubmV3IGFzc2V0IHByb2Nlc3MtPj4rcHJveHk6IFBPU1QgZmlsZXMvdjEvYXNzZXRzL3thc3NldF9pZH0vcHJveGllcy9cbnByb3h5LS0-Pi1uZXcgYXNzZXQgcHJvY2VzczogcHJveHkgaWQgYW5kIHNpZ25lZCB1cGxvYWQgVVJMXG5uZXcgcHJveHkgcHJvY2Vzcy0tPj4rcHJveHk6IHVwbG9hZCB0byBzaWduZWQgdXJsXG5wcm94eS0tPj4tbmV3IHByb3h5IHByb2Nlc3M6IHN1Y2Nlc3MgMjAwXG5uZXcgcHJveHkgcHJvY2Vzcy0tPj4rcHJveHk6IFBBVENIIGZpbGVzL3YxL2Fzc2V0cy97YXNzZXRfaWR9L3Byb3hpZXMvXG5wcm94eS0tPj4tbmV3IHByb3h5IHByb2Nlc3M6IHN1Y2Nlc3MgMjAwXG5ub3RlIHJpZ2h0IG9mIHByb3h5OiBKU09OIHBheWxvYWQgdG8gY2xvc2UgcHJveHkgZmlsZVxubmV3IGFzc2V0IHByb2Nlc3MtPj4rcHJveHk6IFBPU1QgZmlsZXMvdjEvYXNzZXRzL3thc3NldF9pZH0vcHJveGllcy97cHJveHlfaWR9L2tleWZyYW1lcy9cbm5vdGUgcmlnaHQgb2YgbmV3IGFzc2V0IHByb2Nlc3M6IEpTT04gcGF5bG9hZCB0byBjcmVhdGUga2V5ZnJhbWVzXG4iLCJtZXJtYWlkIjoie1xuICBcInRoZW1lXCI6IFwiZGVmYXVsdFwiXG59IiwidXBkYXRlRWRpdG9yIjp0cnVlLCJhdXRvU3luYyI6dHJ1ZSwidXBkYXRlRGlhZ3JhbSI6ZmFsc2V9)

Let's break down the individual bits here.  For this example, I have a DVCProHD Clip from a Panasonic camera in OP-Atom format.  This is represented on my iconik storage gateway (relative to my storage root) by the following files:

```
Test Content/MXF/AVCI_Card/CONTENTS/VIDEO/0002EM.MXF
Test Content/MXF/AVCI_Card/CONTENTS/AUDIO/0002EM00.MXF
Test Content/MXF/AVCI_Card/CONTENTS/AUDIO/0002EM01.MXF
Test Content/MXF/AVCI_Card/CONTENTS/AUDIO/0002EM02.MXF
Test Content/MXF/AVCI_Card/CONTENTS/AUDIO/0002EM03.MXF
```

To register this file all by hand, we'll have to manually generate a proper proxy using H.264 mp4, no b-frames, max raster 1080p, max data rate 6Mb for best performance.  The default configuration for proxies in iconik are 720p raster, target 3Mb, max 4Mb, no b-frames.  You can also manually generate a keyframe map as well, or you can have iconik generate this for you from your proxy.  

You will find example JSON for all successful calls and the responses of those calls in the associated folders in this project.

Create the asset itself.  First call will be a POST to the assets endpoint.  
https://app.iconik.io/docs/apidocs.html?url=/docs/assets/spec/#/operations/default/post_v1_assets_

Next we will create a Format for this asset.  We need the Asset ID (returned in the fist call) to create this.  
https://app.iconik.io/docs/apidocs.html?url=/docs/files/spec/#/operations/default/post_v1_assets__asset_id__formats_

Once we have a format, we need to associate a File Set.  We need both the Format ID and Asset ID to make this call.  
https://app.iconik.io/docs/apidocs.html?url=/docs/files/spec/#/operations/default/post_v1_assets__asset_id__file_sets_

Last, we now need to loop through all of our Files we want to associate and add them to the File Set.  
https://app.iconik.io/docs/apidocs.html?url=/docs/files/spec/#/operations/default/post_v1_assets__asset_id__files_

If the fileset you've created is a supported format by the iconik transcoder, you can use our transcoder to create a proxy automatically here.  The iconik transcoder currently only supports single files in a file_set.  If you already are using an unsupported format or you already have a proxy at the time of asset creation, you can upload it.   To use our transcoder, you'd use the following endpoint.  
https://app.iconik.io/docs/apidocs.html?url=/docs/files/spec/#/operations/default/post_v1_assets__asset_id__files__file_id__keyframes_

If you already have a proxy, you'll need to manual create the proxy object and then upload it.  To do so, use this endpoint.  
https://app.iconik.io/docs/apidocs.html?url=/docs/files/spec/#/operations/default/post_v1_assets__asset_id__proxies_

To upload to iconik standard proxy storage, you will get a "upload_url" in your response object from the proxy creation.  This is a pre-signed URL that can be used to get your actual PUT URL.  Simply POST to this url with the following header:  
`{'x-goog-resumable':'start','Content-Length':'0'}`  
In the successful response to this POST, you will recieve your full upload URL in the response header in the `location` key.   
Now upload your proxy file to this location with a PUT.  
Lastly, you will need to PATCH your proxy file to `"status":"CLOSED"` for it to work properly in iconik and be visible in the UI using this endpoint.  
https://app.iconik.io/docs/apidocs.html?url=/docs/files/spec/#/operations/default/patch_v1_assets__asset_id__proxies__proxy_id__

The last task to "complete" the asset will be to upload or generate a keyframe map.   To generate a keyframe map from the proxy you uploaded, just make an empty call to this endpoint.  
https://app.iconik.io/docs/apidocs.html?url=/docs/files/spec/#/operations/default/post_v1_assets__asset_id__proxies__proxy_id__keyframes_

# Summary

Congrats!  If you made it this far, you now have a fully working asset that can be transfered, downloaded, archived, and organized into collections!  


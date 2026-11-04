# Project settings and export

Use these commands for a recording project's picture, sound, caption style, and export choices. Never edit the package directly.

## Read and change settings

```sh
oilstudio settings schema
oilstudio settings get <project> --out <new-temporary-file.json>
oilstudio settings apply <project> <changes.json> --review
```

`schema.fields` lists editable fields with `section`, `key`, `type`, `default`, `minimum`, `maximum`, and `values`. Discover supported parameters instead of guessing. `settings get` returns `schemaVersion`, `projectFingerprint`, and `settings`. Write a patch containing only requested changes:

```json
{
  "schemaVersion": 1,
  "projectFingerprint": "from settings get",
  "settings": {
    "style": {"backdropMode": "none", "pointerScale": 1.5},
    "subtitles": {"fontScale": 1.1},
    "export": {"quality": "minimal", "hevc": true}
  }
}
```

The fingerprint is optional but recommended. Read again if the project changed; do not overwrite current changes with an old patch. Omitted fields retain their values. Schema defaults describe missing fields; use `get` for actual project values rather than resetting whole groups.

- `style`: aspect ratio `canvasAspect: {x,y}`, padding, crop `cropNormalized: {x,y,width,height}`, background, shadows, cursor, camera, volume, and mute. Coordinates are normalized to 0–1. `cameraAnchor` also updates position unless `cameraCenterNormalized` is explicitly provided in the patch. Background modes are `none/system/gradient/color/image`; `system` means wallpaper. `backdropGradient` is null or `{start:{x,y},end:{x,y},stops:[{at:0,color:"#112233"},{at:1,color:"#445566"}]}`, with 2–16 color stops. `pointerIdleSourceMs` uses source-time milliseconds; null disables idle hiding.
- `layout`: default layout `type`. Use cut proposals for timeline layout ranges, zooms, and cuts.
- `cameraAutomation`, `voice`, `beauty`, `avatar`, `music`: camera automation, voice enhancement, appearance, avatar, and background music.
- `subtitles`: language, style, position, size, background opacity, and chapter progress. `chapterProgressEnabled` controls visibility; `chapterProgressPosition` is `bottom` or `top`. Use `subtitles apply` for caption text and `chapters apply` for chapter content.
- `transitions`: cut effect and output-time duration `spanMs`.
- `export`: saved MP4/GIF, resolution, frame rate, quality, HEVC, caption, SRT, GIF width, and GIF frame rate choices.

Media fields reference existing assets. Background images use paths relative to the project. Music `id` names an existing built-in track or a file already imported into the project. Avatar `packID` names an installed pack. Reuse references from `get`; do not invent IDs or pass arbitrary disk paths. This interface does not import assets or modify cloud credentials, recording preferences, or automatic AI edit preferences.

Settings are reviewed by group and follow the project's automatic edit switch; `--review` requires approval. For `autoApplied: false`, wait on `proposal status <id> --wait`; submission does not mean application. `changed: false` means no difference and requires no proposal wait. Read settings back after application before exporting. ⌘Z undoes changes. When the app is closed, proposals queue instead of writing the project directly.

## Export

```sh
oilstudio export <project> --out <video.mp4>
oilstudio export <project> --out <smaller.mp4> --quality minimal --codec hevc --no-srt
oilstudio export <project> --out <preview.gif> --gif-width 640 --gif-fps 15 --no-srt
oilstudio export <project> --out <excerpt.mp4> --output-from-ms 1000 --output-to-ms 6000
```

Unspecified options use the project's saved export settings. CLI overrides apply only to this export. The extension determines the format; an explicit `--format mp4|gif` must match it.

For MP4, use `--quality minimal|compact|standard|high`, `--codec h264|hevc`, `--resolution 720p|1080p|1440p|2160p`, and `--fps <integer>`. Minimal trades clarity for size. HEVC keeps the chosen resolution and frame rate, but some older devices or software cannot play it. AV1, VP9, and custom Mbps are not currently supported; do not invent flags for them.

GIF uses `--gif-width <pixels>` and `--gif-fps <rate>`, without MP4 quality, codec, resolution options, or audio. `--fps` is an alias; `--gif-fps` takes precedence. Existing app duration and size limits still apply.

Use `--subtitles burn|none` for visible captions and `--srt` / `--no-srt` for the sidecar. Otherwise saved choices apply. If captions are explicitly requested but missing, generate them using the main workflow first. `--output-from-ms` / `--output-to-ms` specify an inclusive start and exclusive end in **output-time milliseconds**, not source time. SRT is clipped to this range and starts at zero. Exporting an excerpt does not change the timeline.

Honor existing overwrite authorization; otherwise ask before replacing files with `--overwrite`. Export still requires the app's license; do not bypass it. The final result includes `path`, `format`, `width`, `height`, `fps`, `quality`, `codec`, `durationMs`, and an `srt` path when actually written. GIF's `codec` is null. Do not claim completion before the final result.

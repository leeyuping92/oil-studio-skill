# Proposal formats

Return to [SKILL.md](../SKILL.en.md). Validate cut, zoom, layout, overlay, and redaction plans before submission. `subtitles apply` validates caption edits against their original text.

## Contents

- [Cut plan](#cut-plan-plan-validate--plan-submit)
- [Filler coverage check](#filler-coverage-check)
- [Zooms](#zooms-zooms)
- [Titles, images, and B-roll](#titles-images-and-b-roll-overlays)
- [Redactions](#redactions-redactions)
- [Layouts](#layouts-layouts)
- [Submission result](#submission-result)
- [Caption edits](#caption-edits-subtitles-apply)
- [Whole-track captions](#whole-track-captions-subtitles-apply)

## Cut plan (`plan validate` / `plan submit`)

```json
{
  "schemaVersion": 1,
  "projectFingerprint": "copy exactly from context",
  "contextFingerprint": "copy exactly from context",
  "summary": "Remove 3 retakes and 2 slips; expected saving 48 seconds",
  "decisions": [
    {
      "decision": "cut",
      "confidence": "high",
      "range": {"from": "U0012", "to": "U0015"},
      "category": "abandoned_take",
      "removedText": "the exact removed speech",
      "keptText": "the retained speech that fully covers it",
      "keptRange": {"from": "U0020", "to": "U0022"},
      "reason": "The later take covers all information in the earlier take",
      "screenAction": "redundant",
      "visualAssessment": "The same setting is demonstrated again in U0021"
    },
    {
      "decision": "review",
      "confidence": "low",
      "sourceMs": [61200, 64850],
      "category": "filler",
      "removedText": "speech that might be removable",
      "keptText": "",
      "reason": "It sounds incidental but mentions a setting not covered later"
    }
  ]
}
```

| Field | Values |
| --- | --- |
| `decision` | `cut`, `keep` (explicitly retain), `review` (uncertain). |
| `confidence` | `high`, `medium`, `low`; only `cut` with high/medium enters the approval list. |
| `category` | `abandoned_take`, `false_start`, `slip`, `filler`, `silence`. |
| `range` | Inclusive utterance IDs `from` and `to`; preferred for complete utterances. |
| `sourceMs` | `[start, end]` source-time milliseconds for partial utterances, using word timestamps. |
| `keptRange` | Utterances covering the removed information; required for `abandoned_take`. |
| `screenAction` | Use `redundant` only after inspecting overlapping operations and confirming they repeat later or are irrelevant. Omit when uncertain. |
| `visualAssessment` | Required with `screenAction`; describe the visual evidence in one sentence. |

Each decision uses either `range` or `sourceMs`, never both. Never use output time for cuts. Copy integer source milliseconds from context; at the end of a clip/session, copy its end time without adding fractions.

Start fine-cut plans with `pauses <project> --out-plan <json>` and append semantic decisions. Context and draft fingerprints must match. Do not apply cleanup separately first. `plan preview <plan> --index <zero-based-index> --out <wav>` previews joins with all applicable cuts, reading only original microphone audio and changing nothing. Speed changes, repeats, and reordered timelines are unsupported.

## Filler coverage check

Record every candidate in `decisions` as `cut`, `keep`, or `review`, with source bounds and a specific `reason`. A fully covering passage cut needs no duplicate word cut. Do not invent candidate IDs or audit fields in the proposal schema; save coverage reports outside the project.

When Python 3 is available, run the shipped read-only checker before `plan validate`. The skill directory is the loaded package root, one level above `en/`:

```sh
python3 -B <skill-directory>/scripts/check_filler_coverage.py --context <current-context.json> --plan <plan.json> --out <new-coverage-report.json>
```

The [checker](../../scripts/check_filler_coverage.py) verifies both fingerprints, resolves utterance and word ranges, and checks their union in source time. Partially cutting a word does not count as removal; low-confidence cuts are not executable. Exit 0 means each candidate is accounted for, 1 means `unresolved` candidates remain, and 2 means an input/fingerprint/file error. Fetch fresh data on mismatch rather than changing fingerprints manually. Reports never overwrite existing files.

Without Python, or on older contexts lacking `fillerCandidates`, manually account for existing timed words instead. Do not install dependencies or treat a missing field as zero candidates. After all candidates have an outcome, validate the plan normally. Coverage does not prove meaning, sound quality, or visual safety; `review` is still outstanding editorial work.

`keep` and `review` do not enter the app's executable cut list. Do not claim the user can tick a `review` entry there; provide its range, reason, and audit path. Never change an uncertain judgment to `cut` merely to make it appear. For supported cuts requiring operation review, preserve the validator's `uncheckedByDefault` result.

After application, use accepted/skipped receipt entries and reread retained footage. Check accepted source ranges for sounds expected to be removed. Retained, review, and unaccepted cuts can legitimately remain; neither residual candidate counts nor validation success establish editing completeness.

## Zooms (`zooms`)

Plans may contain any combination of `decisions`, `zooms`, and `layouts`.

```json
"zooms": [
  {"action": "add", "sourceStartMs": 84200, "sourceEndMs": 89600, "level": 1.8, "mode": "manual",
   "target": {"x": 0.72, "y": 0.31}, "transition": "smooth", "reason": "Make the small error message readable"},
  {"action": "update", "id": "z7", "level": 1.4, "reason": "The current zoom crops the button"},
  {"action": "remove", "id": "z9", "reason": "The movement does not support the explanation"}
]
```

| Field | Values |
| --- | --- |
| `action` | `add`, `update` (only changed fields), `remove`. |
| `id` | Required for update/remove; copy from context's `zooms`. |
| `sourceStartMs` / `sourceEndMs` | Source milliseconds, at least 600 apart. Validate overlap against all proposed final zooms. Must intersect retained footage; may span removed footage. |
| `level` | 1.0–3.0. |
| `mode` | `auto` follows clicks; `manual` fixes the view at `target`. |
| `target` | Required for manual mode; normalized screen x/y, both 0–1. |
| `transition` | `smooth` or `instant`. |

At most one update/remove per zoom ID in one plan; ordering duplicate operations must not change the outcome.

## Titles, images, and B-roll (`overlays`)

A plan may combine `decisions`, `zooms`, `layouts`, `overlays`, and `redactions`. `overlays` and `redactions` are top-level arrays. Proposal fields are flat; do not copy the nested `content` shape returned by `context.overlays`.

```json
"overlays": [
  {
    "action": "add", "id": "o-title-1", "kind": "text", "text": "Start with the main flow",
    "template": "title", "anchorSourceMs": 84200, "durationOutputMs": 3200,
    "frame": {"x": 0.5, "y": 0.13, "fontSize": 0.055}, "opacity": 1,
    "enter": {"style": "pop", "durationMs": 300}, "exit": {"style": "fade", "durationMs": 250}
  },
  {
    "action": "add", "id": "o-image-1", "kind": "image", "layer": "screen",
    "sourcePath": "/absolute/local/path/feature.png", "anchorSourceMs": 120000, "durationOutputMs": 2400,
    "fit": "fit", "focus": {"x": 0.5, "y": 0.5},
    "enter": {"style": "dissolve", "durationMs": 300}, "exit": {"style": "dissolve", "durationMs": 300}
  },
  {"action": "update", "id": "o-title-1", "durationOutputMs": 4000},
  {"action": "remove", "id": "o-image-old"}
]
```

| Field | Values and rules |
| --- | --- |
| `action`, `id` | `add`, `update`, or `remove`; every item needs a unique, nonempty `id`. An add ID must not conflict with the project. An update/remove ID must match exactly one existing item. Remove needs only `action` and `id`. |
| `kind` | `text` or `image`, at the top level of the item. |
| `text`, `template` | Text items require `text`. Optional `template` is `title` or `label`. Text can only use the `float` layer; omit `layer` to use float, or specify `float` explicitly. |
| `sourcePath`, `file` | Image items need one: `sourcePath` is an absolute local image path; `file` is an existing filename in the project's `assets/overlays/`. Do not include a directory path in `file`. |
| `layer` | Required for images: `float` overlays the recording; `screen` replaces the recorded picture. |
| `anchorSourceMs`, `durationOutputMs` | Required for text and image. The anchor uses source-time milliseconds; display duration uses output-time milliseconds. |
| `frame` | Optional float placement and size. Coordinates are normalized canvas center points: images use `{x,y,width}` and text uses `{x,y,fontSize}`. Explicit values are 0–1; `width` / `fontSize` must be greater than 0. Defaults are centered images at width 0.25 and text size 0.055. |
| `opacity` | Optional float opacity from 0 to 1. Screen images reject explicit `opacity`; use `enter` / `exit` for no effect or a dissolve transition. |
| `fit`, `focus` | For `screen` images only. `fit` is `fill` or `fit`; `focus` is normalized `{x,y}` from 0 to 1. |
| `enter`, `exit` | Optional `{style,durationMs}`. Float styles: `none`, `fade`, `pop`, or `rise`; screen replacement styles: `none` or `dissolve`. Defaults are `pop`/300 ms and `fade`/250 ms for floats, or `dissolve`/300 ms for screen replacements. |

An update sends only changed fields; the app merges them into the existing item and preserves omitted and unknown project fields. Adds need the required fields for their kind. An image at `sourcePath` is imported into `assets/overlays/` only when the accepted change is applied and is deduplicated by SHA-256. `plan validate` is read-only and does not write the project or import the image. After applying, check the plan receipt's actual `applied` and `skipped` entries, then inspect key frames with `frame --text`; export and recheck the final picture when a video is requested.

## Redactions (`redactions`)

Redactions are a separate top-level array, not nested inside `overlays`. `region` is a fixed normalized rectangle in the original recording frame; it does not automatically track a moving object.

```json
"redactions": [
  {
    "action": "add", "id": "r-account-1",
    "sourceStartMs": 50000, "sourceEndMs": 61500,
    "region": {"x": 0.61, "y": 0.08, "width": 0.27, "height": 0.09},
    "style": "pixelate", "reason": "Cover the account information in the upper right"
  },
  {"action": "update", "id": "r-account-existing", "style": "blur", "reason": "Use blur for the account information"},
  {"action": "remove", "id": "r-obsolete"}
]
```

| Field | Values and rules |
| --- | --- |
| `action`, `id` | `add`, `update`, or `remove`; `id` must be unique and nonempty. Add IDs must not conflict; update/remove must uniquely match an existing item. Remove needs only `action` and `id`. |
| `sourceStartMs`, `sourceEndMs` | Valid increasing source-time milliseconds within one recording segment. |
| `region` | Normalized `{x,y,width,height}` rectangle entirely within the 0–1 frame; width and height must be positive. |
| `style` | `pixelate`, `blur`, or `fill`. |
| `reason` | A nonempty string is required on add. An update may omit it when the existing item already has a nonempty reason; supply one when the existing value is missing or empty. |

Updates merge only the supplied fields; the resulting item must retain valid times, region, style, and a nonempty reason. An update may inherit an existing nonempty reason, but must supply one to repair a missing or empty value. For moving content, define and inspect separate regions over their individual time ranges. Do not describe a fixed box as object tracking. Passing validation does not mean that the mask has been applied: after application, inspect frames with `oilstudio frame <project> --source-ms <milliseconds> --text --out <png>` and check both the picture and recognized text. If exporting, inspect and play the output to confirm coverage throughout the requested range. If sensitive content remains visible, correct and revalidate the plan before reporting it complete.

## Layouts (`layouts`)

Only for projects with a camera. This is the sole proposal section using **pre-submission output-time milliseconds**. Read existing segments from context's `layouts`.

```json
"layouts": [
  {"action": "add", "outputStartMs": 2000, "outputEndMs": 9500, "type": "camera", "transitionDuration": 0.5, "reason": "Show only the speaker for the opening"},
  {"action": "update", "id": "l7", "type": "side-by-side", "reason": "Show the speaker and operation together"},
  {"action": "remove", "id": "l9", "reason": "Restore the default layout"}
]
```

| Field | Values |
| --- | --- |
| `action` | `add`, `update` (only changed fields), `remove`. |
| `type` | `both`, `screen`, `camera`, `side-by-side`. |
| `transitionDuration` | 0.3, 0.5, or 0.8 seconds. |
| `outputStartMs` / `outputEndMs` | At least 600 milliseconds apart; layout segments cannot overlap. |

## Submission result

`plan submit`, `pauses --submit`, `idle --submit`, `subtitles apply`, and `chapters apply` return `proposalId` and `autoApplied`.

```json
{"ok": true, "proposalId": "…", "autoApplied": true, "applied": [0, 1, 3], "skipped": [{"index": 2, "reason": "You changed this zoom"}]}
```

`autoApplied: false` awaits approval; use `proposal status <proposalId> --wait`. With true, only `applied` entries have changed; `skipped` entries have not.

Receipt indexes follow the items in the same plan: `decisions`, `zooms`, `layouts`, `overlays`, then `redactions`. Check each item. Applied changes can be undone in Oil Studio with ⌘Z.

## Caption edits (`subtitles apply`)

```json
{
  "schemaVersion": 1,
  "edits": [
    {"id": "c0042", "expectedText": "I use cloud code to write code.", "text": "I use Claude Code to write code."}
  ],
  "glossary": [
    {"wrong": "cloud code", "correct": "Claude Code"}
  ]
}
```

Copy `id` and `expectedText` exactly from `subtitles get` → `id`/`text`, never `displayText`. Stale text is rejected. Edit text only, not timing. The optional glossary should contain recurring recognition errors.

## Whole-track captions (`subtitles apply`)

A presentation without narration can submit captions authored in source time. `cues` and the `edits` format above are mutually exclusive. Keep each cue to a single short spoken clause rather than joining two clauses into one compound caption.

- Each cue is bound to the recording session containing its source-time range. A cue crossing a session boundary is split at that boundary. The first piece keeps the original ID; later pieces use a deterministic `<originalID>-session-<sessionIndex>` ID, with a numeric suffix if needed to avoid collisions. Each piece copies the original English translation.
- A cue with no valid session interval or an ID collision is rejected rather than silently dropped. Caption display is enabled, and translations for IDs no longer present are removed.
- `edited` is written as `true`. Agent-recorded projects apply according to `autoApply`; afterwards use `subtitles get`, `subtitles export`, or `export --subtitles burn`. For ordinary proofreading, keep using `edits` with the old cue ID and `expectedText` checks.

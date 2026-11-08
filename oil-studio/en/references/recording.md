# Recording

Return to [SKILL.md](../SKILL.en.md).

For a multi-beat web demonstration with analysis cards or aligned zooms, use [Web playbooks](#web-playbooks). The script controls pages through the browser automation Node API only; never use Computer Use in this workflow. Do not add captions unless the user explicitly asks for them.

`oilstudio record` prepares a window and controls recording. For desktop applications, choose the most reliable control path available:
- If you have your own capable Computer Use tool, operate the target window directly (physical clicks inside the recorded window are captured automatically, or report exact centers before clicking with `oilstudio record click --at <x>,<y>`).
- If you do not have a built-in desktop tool or want deterministic headless control without screenshots, use `agent-desktop` (`agent-desktop snapshot --app <App> -i --compact --include-bounds` to get `@ref` IDs and `bounds`, report the element center with `oilstudio record click --at-fraction <u>,<v>`, then run `agent-desktop click <ref>` or `agent-desktop type --headed --interval-ms 55 <ref> <text>` so characters are typed one by one with the native input caret visible, without moving the physical mouse).
- Add `--perform` to `record click` / `record move` only when you want Oil Studio to dispatch a physical click/move itself. Without any desktop control tool, explain that you can control recording while the user operates the target.

Titles, images, and redactions are proposed after recording, not drawn into the live recording. To add a title, label, image/B-roll, or cover sensitive screen content, follow “Add overlays and redactions” in SKILL.md and submit a plan. See [Proposal formats](proposal-formats.md) for the fields, asset import behavior, and visual checks.

## Prepare

- Confirm the subject and opening/ending states. Show a plan first for more than ten steps.
- Prepare the window with `oilstudio record prepare --source <id> --size 1280x800 --center --activate`, or pass these options to `record start`. Use either `--position X,Y` or `--center`. External window adjustments require Accessibility access. Oil Studio can capture an occluded window, but your control tools may need it in front.
- Move unrelated content and notifications out of the target.
- Record only the requested window. Never select a display without an explicit request or capture unrelated chat/email windows.

## Report positions

The output cursor comes from your reports, not the real mouse. Before each click run `oilstudio record click`, then click as soon as the command returns. Alternatively add `--perform` to perform the native click and do not click again; `record move --perform` also moves the real pointer. Native actions require Accessibility access.

- `--at <x>,<y>` uses screen points, the same coordinate system as `record sources` fields `x`, `y`, `width`, and `height`. Reuse the coordinates used by your screen control tool.
- `--at-fraction <u>,<v>` uses 0–1 fractions of the captured window: divide target x/y by screenshot width/height. The screenshot must contain exactly that window, including its title bar.
- For browser content coordinates, first inspect the entire window and offset the content origin before converting to fractions.
- Give retries `--id <step-name>` so the same action is recorded once.
- If no reliable coordinates are available, omit the report and disclose which steps lack a cursor.
- If the reported click fails, continue and disclose it or restart as below.
- Typing and scrolling need no reports. Do not resize during recording; moving the window does not affect fractions.

## During recording

- Perform one action at a time, confirming its visible result before the next. Waits can be removed later.
- Type normally and leave about a second for the result to be visible instead of pasting and immediately leaving.
- Use `oilstudio record mark` after important steps if useful.
- Before working outside the target, run `oilstudio record pause`; resume with `oilstudio record resume`.
- Control recording from the CLI, never by clicking Oil Studio's recording indicator.
- The default limit is 600 seconds, then automatic stop/save. Use `--max-duration <seconds>` at start for longer recordings, up to 3600 seconds.

## Failures

| Situation | Action |
| --- | --- |
| The demonstration is no longer usable | `oilstudio record stop --discard`, restore the opening state, and restart. |
| A small mistake is repeated correctly later | Finish recording, then cut the wrong source-time range with `plan submit`, category `false_start`. |
| `stoppedBy: "user"` | The project is saved. Ask whether to continue editing or rerecord. |
| `stoppedBy: "limit"` | Explain where recording stopped and ask whether to rerecord with a longer limit. |
| `CANCELLED` | The user discarded the recording; no project exists. Stop and ask what to do next. |
| `NO_RECORDING` | Run `oilstudio record status` and inspect `last`. |
| `SOURCE_NOT_FOUND` | The window closed or changed; rerun `record sources`. |
| `APP_REQUIRED` | Run `open -a "Oil Studio"` and retry once. |

If your control tool fails and cannot continue, run `oilstudio record stop` or `--discard`; never leave recording running.

## Afterward

1. Run `oilstudio idle <project> --submit`. It aligns delayed click reports, rebuilds automatic zooms from retained slices and changed regions, and immediately applies changes to recordings you made.
2. Inspect the new duration/clips with `oilstudio context <project> --out <temporary-file>` and sample frames with `oilstudio frame <project> --output-ms <milliseconds> --out <png>`.
3. Generated zooms follow reported clicks. Follow Adjust zooms for small text or actions lacking reports.
4. For titles, labels, image/B-roll, or redactions, follow “Add overlays and redactions” in SKILL.md and check the proposal receipt. Redactions use a fixed region and do not track moving objects; after application, inspect with `frame --text` and review the exported video.
5. When requested, run `oilstudio export <project> --out <path.mp4>`. With redactions, confirm they have applied and sample the exported sensitive ranges.

## Web playbooks

Both modes require `node`. The `stage-window` mode uses macOS WebKit and `swiftc` from the Xcode Command Line Tools without requiring any third-party browser; when no browser host is explicitly specified and `ego-browser` is not installed, the script automatically uses `stage-window`. Check the selected mode’s dependencies before recording; if any are missing, ask the user to install them before continuing.

Use a playbook for longer web demonstrations that need optional beat captions, an on-screen analysis card, or zooms aligned to the same source-time range. Before recording, the script opens the first URL through the browser automation runtime, then asks Oil Studio to select and record the single matching browser window. Oil Studio must be running and the user must grant recording access. Microphone, camera, and system audio stay off.

```sh
python3 -B <Skill-directory>/scripts/record_playbook.py \
  --playbook <demo.json> --out-report <report.json> --export <video.mp4>

python3 -B <Skill-directory>/scripts/record_playbook.py --playbook <demo.json> --dry-run
python3 -B <Skill-directory>/scripts/record_playbook.py --inspect https://example.com
python3 -B <Skill-directory>/scripts/record_playbook.py --playbook <demo.json> --rehearse
```

The JSON has a `source`, optional `settings` using the `settings apply` patch shape, and a non-empty `beats` array. Each beat has a unique `id`, an optional `subtitle`, optional `hud`, optional `zoom`, and `actions`. The first action in the first beat must be `open`; it prepares the opening page before recording and is not repeated during the take.

Select the source with `sourceId`, `app`, or `title`; when several are present, all conditions must match exactly one window. `app` uses a case-insensitive full-name match. `title` defaults to a case-insensitive substring match; set `exactTitle:true` for an exact match. The script reads the opened page's actual title and verifies it against the native capture window. A `sourceId`-only source needs no separate `title`, but the actual page title still protects against selecting the wrong window.

Optional `browser.host` values are `browser`, `ego-browser`, and `stage-window`. When the host is unspecified, a failed browser window match can fall back to the stage; an explicit browser host or `browser.page: user` prevents fallback. With an explicit `stage-window` host, do not set `source.sourceId`: the new stage receives a new window ID, so validation rejects this combination before starting the stage. Use `source.title` or `app` instead. `browser.scratchDir` chooses the parent directory for temporary files. Each run creates its own directory under the system temporary directory or that parent; never reuse a fixed working directory. The isolated stage's local control interface requires a random session token for each run.

`browser.preflightSeconds` accepts 0–10. A positive value records a short probe and extracts OCR text from a frame at source time `min(500, max(0, duration in milliseconds - 1))`, keeping the frame within the actual take. `browser.preflightContains` is an optional string array; when present, every string must occur in the OCR text, ignoring case and whitespace. Without it, preflight makes no assumptions about page-specific text. `--preflight-only` stops after this probe and requires a positive `preflightSeconds`.

Command help, validation messages, and runtime errors use `OILSTUDIO_LANGUAGE` (`zh-Hans` or `en`) when set, then the system locale otherwise, with English as the fallback for unrecognized locales. JSON field names do not change with language.

`hud` accepts `badge`, `title`, `detail`, `pills:[{label,value,color?}]`, and `position: top-right|bottom-left|top-left`. The floating card uses an isolated Shadow DOM and `pointer-events:none`, then is removed after recording or on failure. `zoom` accepts `level`, `transition`, and either `selector` or `target:{x,y}`. A selector uses the center of a visible element; target coordinates are 0–1 fractions of the web viewport. The script includes browser chrome offsets measured from `outerWidth - innerWidth` and `outerHeight - innerHeight` when converting to full-window normalized coordinates. The zoom range matches its beat and must satisfy the 600 ms minimum.

Supported actions are `open:{url}`, `click` / `move` with `selector` or window-relative `fraction:{u,v}`, `scroll` with `y` or `selector` and optional `durationMs`, `input` with `selector,value` or `selector,from,to,durationMs`, `press` with `key` (such as `Enter`, `Escape`, `Tab`, or `Meta+k`) and an optional `selector`, `eval:{script}`, `wait:{ms}`, and `mark`. Selectors are CSS selectors in the page DOM. Before a selector click or hover, the script measures its center, reports the point with `record click` or `record move`, then dispatches the real page action. Explicit fractions use the full captured window and are converted to viewport coordinates. Scroll and numeric input transitions are animated in the page.

The script applies optional settings, builds a fingerprinted zoom proposal and runs `plan validate` / `plan submit`, and leaves captions off by default (it calls `subtitles apply` and burns captions on `--export` only when the user explicitly requests captions and `settings.subtitles.enabled` is set to `true` alongside nonempty beat `subtitle` text; otherwise `--export` uses `--subtitles none`). If any change was not directly applied, it records the pending result and skips export. On failure, it attempts to discard an unfinished take. `--dry-run` validates the playbook without opening a browser or starting recording; `--out-report` writes source matching, cue ranges, proposals, and export status.

`PERMISSION_REQUIRED` means recording or Accessibility permission is missing. Ambiguous windows, occluded targets, and rejected geometry changes return `VALIDATION_FAILED`.

`--inspect <url>` opens an isolated stage, waits for the page to settle, and returns viewport, scroll container, and interactive element details with selectors and positions; no playbook is needed. `--rehearse` runs actions in order and checks zoom selectors in the stage without recording. Page actions still take effect; use it only on pages where those actions are permitted.

For Playbook zooms, `mode` defaults to `manual`, which requires one `selector` or `target`. Explicit `auto` follows pointer intents and must not include a target. A selector is resolved before the beat actions, so later scrolling does not change its target.

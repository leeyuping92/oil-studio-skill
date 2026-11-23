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
| `PERMISSION_REQUIRED` | Report `message` and `hint`, then stop. For missing access such as screen recording, ask the user to grant it on the app’s permissions page; if a terminal or AI sandbox blocked local access, ask the user to allow running `oilstudio` outside the sandbox instead of reopening the app; if it says the app was moved or deleted, ask the user to quit Oil Studio and open it again from the Applications folder. |

If your control tool fails and cannot continue, run `oilstudio record stop` or `--discard`; never leave recording running.

## Afterward

1. Run `oilstudio idle <project> --submit`. It aligns delayed click reports, rebuilds automatic zooms from retained slices and changed regions, and immediately applies changes to recordings you made.
2. Inspect the new duration/clips with `oilstudio context <project> --out <temporary-file>` and sample frames with `oilstudio frame <project> --output-ms <milliseconds> --out <png>`.
3. Generated zooms follow reported clicks. Follow Adjust zooms for small text or actions lacking reports.
4. For titles, labels, image/B-roll, or redactions, follow “Add overlays and redactions” in SKILL.md and check the proposal receipt. Redactions use a fixed region and do not track moving objects; after application, inspect with `frame --text` and review the exported video.
5. When requested, run `oilstudio export <project> --out <path.mp4>`. With redactions, confirm they have applied and sample the exported sensitive ranges.

## Web playbooks

Use a playbook for longer web demonstrations that need optional beat captions, an on-screen analysis card, or zooms aligned to the same source-time range. Before recording, the script opens the first URL in the selected browser host, then asks Oil Studio to select and record the single matching window. Oil Studio must be running and the user must grant recording access. Microphone, camera, and system audio stay off. A run starts one long-lived browser automation process, so steps run with almost no scheduling delay.

### Browser hosts

Nothing from automation may appear in the video: the control bar an agent browser draws while it drives the page, a border around the page, action captions next to the cursor, or browser prompts such as a translation offer. Only `browser.host` and `browser.cdpURL` choose the host; what happens to be installed doesn’t:

| Host | When | Notes |
| --- | --- | --- |
| `stage-window` (default) | Public pages that need no sign-in | A borderless macOS WebKit window with no overlays. It has a single page and can’t switch tabs. Requires `node` and `swiftc` from the Xcode Command Line Tools. |
| `cdp` | A signed-in session, several tabs, or scrolling inside a cross-origin embedded page | Connects through the debugging port to a Chromium-based browser the user started (Chrome, Edge, Brave, and so on) and drives it with native mouse and wheel events, with no overlays. Set `"browser": {"cdpURL": "http://127.0.0.1:9222"}`. Requires Node.js 22 or later. |
| `browser` / `ego-browser` | Only when the user asks for it | An agent browser task space. Its control bar and action captions stay visible while it’s in control, so the pre-recording check stops it and it usually can’t record. |

The user starts the cdp browser, or you run it with their approval. Use a dedicated profile folder: sign in once and reuse it, without touching the everyday browser profile:

```sh
open -na "Google Chrome" --args --remote-debugging-port=9222 --user-data-dir="$HOME/Library/Application Support/Oil Studio Demo Browser"
```

For another Chromium browser, change the app name. `browser.cdpURL` accepts only local addresses (`127.0.0.1`, `localhost`, or `[::1]`). If the first `open` address is already open in a tab, such as a page the user just signed in to, the script uses that tab without reloading it; the same applies to `browser.tabs`. The script never closes the user’s browser or tabs.

### Pre-recording check

For real browser hosts (`cdp`, `browser`), the script takes a window snapshot before recording by default (`oilstudio record screenshot --text`, which creates no project and doesn’t change the project open in the editor) and reads the text in the part of the window that will appear in the video:

- If it finds text from the default blocklist (an agent browser’s control bar and action captions, a translation prompt, “Chrome is being controlled by automated test software”, and so on), it stops without recording; the report’s `preflight.ocr.forbidden` lists the matches. Close the overlay or change hosts, then run again.
- `browser.preflightForbid` replaces the default blocklist (`[]` blocks nothing). `browser.preflightContains` lists text that must appear, to confirm the right page is on screen.
- `browser.preflight: false` turns the check off; the isolated stage skips it unless set to `true`. A positive legacy `preflightSeconds` turns it on. `--preflight-only` runs only this check.

### Commands and format

For the cdp host, start the browser as described above first. Check the selected host’s dependencies before recording; if any are missing, ask the user to install them before continuing.

```sh
python3 -B <Skill-directory>/scripts/record_playbook.py \
  --playbook <demo.json> --out-report <report.json> --export <video.mp4>

python3 -B <Skill-directory>/scripts/record_playbook.py --playbook <demo.json> --dry-run
python3 -B <Skill-directory>/scripts/record_playbook.py --inspect https://example.com
python3 -B <Skill-directory>/scripts/record_playbook.py --playbook <demo.json> --rehearse
```

The JSON has a `source`, optional `settings` using the `settings apply` patch shape, and a non-empty `beats` array. Each beat has a unique `id`, an optional `subtitle`, optional `hud`, optional `zoom`, and `actions`. The first action in the first beat must be `open`; it prepares the opening page before recording and is not repeated during the take.

Select the source with `sourceId`, `app`, or `title`; when several are present, all conditions must match exactly one window. `app` uses a case-insensitive full-name match. `title` defaults to a case-insensitive substring match; set `exactTitle:true` for an exact match. The script reads the opened page's actual title and verifies it against the native capture window. A `sourceId`-only source needs no separate `title`, but the actual page title still protects against selecting the wrong window.

See [Browser hosts](#browser-hosts) for `browser.host` and `browser.cdpURL`. `browser.page` applies only to the `browser` host (a page label in the task space, or `user`). The isolated stage opens a new window each time, so it can’t use `source.sourceId`; use `source.title` or `app` instead. `sourceId` suits a browser window that’s already open under the cdp host. `browser.scratchDir` chooses the parent directory for temporary files. Each run creates its own directory under the system temporary directory or that parent; never reuse a fixed working directory. The long-lived process and the isolated stage’s local control interface use a random session token for each run and listen only on this Mac.

`browser.tabs` lists other tabs to open before recording: `[{"id": "admin", "url": "https://…"}]`, where `id` can’t be `main` (the page of the first `open`). Only the cdp and `browser` hosts support tabs. During the take, `{"action": "switchTab", "tab": "admin"}` switches to a tab and `"tab": "main"` switches back. Switching is instant and doesn’t reload the page; the HUD moves to the tab on screen.

Command help, validation messages, and runtime errors use `OILSTUDIO_LANGUAGE` (`zh-Hans` or `en`) when set, then the system locale otherwise, with English as the fallback for unrecognized locales. JSON field names do not change with language.

`hud` accepts `badge`, `title`, `detail`, `pills:[{label,value,color?}]`, and `position: top-right|bottom-left|top-left`. The floating card uses an isolated Shadow DOM and `pointer-events:none`, then is removed after recording or on failure. `zoom` accepts `level`, `transition`, and either `selector` or `target:{x,y}`. A selector uses the center of a visible element; target coordinates are 0–1 fractions of the web viewport. The script includes browser chrome offsets measured from `outerWidth - innerWidth` and `outerHeight - innerHeight` when converting to full-window normalized coordinates. The zoom range matches its beat and must satisfy the 600 ms minimum.

Supported actions are `open:{url}`, `click` / `move` with `selector` or window-relative `fraction:{u,v}`, `scroll` with `y` or `selector` and optional `durationMs`, `wheel` with `selector` or `fraction:{u,v}`, pixel `deltaY` / `deltaX` (at least one nonzero), and optional `durationMs` (default 600), `input` with `selector,value` or `selector,from,to,durationMs`, `press` with `key` (such as `Enter`, `Escape`, `Tab`, or `Meta+k`) and an optional `selector`, `switchTab:{tab}`, `eval:{script}`, `wait:{ms}`, and `mark`. Selectors are CSS selectors in the page DOM. Before a selector click or hover, the script measures its center, reports the point with `record click` or `record move`, then dispatches the real page action; `wheel` first moves the reported cursor to the scroll point with `record move`. Actions send no caption text to the browser, so an agent browser shows no action caption next to its cursor. Explicit fractions use the full captured window and are converted to viewport coordinates. Scroll and numeric input transitions are animated in the page.

`scroll` reaches only scroll containers in the top-level page. For a cross-origin embedded page, such as a live mini-program preview or a third-party widget, use `wheel` positioned over that embedded area. Under the cdp and `browser` hosts, `wheel` sends real wheel events that reach cross-origin frames; the isolated stage falls back to scrolling the nearest scrollable container under that point.

**Adding to a voice-over (`attach`).** To add a web segment to a voice-over project, add top-level `"attach": {"project": "<voice-over project>", "atOutputMs": <output ms where the segment starts>, "durationMs": <optional segment length>, "plan": <optional unsubmitted cut plan>, "replaceUntilOutputMs": <optional output ms where a re-recorded segment ends>}`. The script records with `record start --into … --at-output-ms …` (adding `--plan` with `plan`, so `atOutputMs` and word times are on the plan’s cut timeline, and `--replace-until-output-ms` with `replaceUntilOutputMs`, which first clears older clips in the segment; with `plan` and `durationMs` but no `replaceUntilOutputMs`, the end defaults to `atOutputMs + durationMs`), and the stopped take is attached to the voice-over directly. The report’s `planProjection` shows the converted times. It doesn’t submit idle removal, captions, chapters, or transitions, and it refuses `--export` (export the voice-over project after every segment is in place). Actions can carry `atMs`: how many milliseconds after recording starts the step runs. The script waits on the recording clock until then, so a click can land when it’s mentioned (`atMs = word outputStartMs − atOutputMs`). The opening `open` of the first beat runs before recording starts and can’t have `atMs`. With `durationMs`, the script keeps recording after the last step until that length, then stops. Zooms are submitted at the take’s source time in the project. A click, hover, or input with `atMs` scrolls to its target and measures it before the wait, then declares and performs the step as soon as the moment arrives, so the page must be settled by then (add a `wait` first while images load lazily or an animation runs). The report’s `timedActions` lists each step’s planned `atMs` and the `declaredMs` it actually got, both in milliseconds since the take started. If they differ by more than about 100 ms, adjust `atMs` and record that segment again.

The script applies optional settings, builds a fingerprinted zoom proposal and runs `plan validate` / `plan submit`, and leaves captions off by default (it calls `subtitles apply` and burns captions on `--export` only when the user explicitly requests captions and `settings.subtitles.enabled` is set to `true` alongside nonempty beat `subtitle` text; otherwise `--export` uses `--subtitles none`). If any change was not directly applied, it records the pending result and skips export. On failure, it attempts to discard an unfinished take. `--dry-run` validates the playbook without opening a browser or starting recording; `--out-report` writes source matching, cue ranges, proposals, and export status.

`PERMISSION_REQUIRED` means recording or Accessibility permission is missing, or the app needs to be reopened (see the error table above). Ambiguous windows, occluded targets, and rejected geometry changes return `VALIDATION_FAILED`.

`--inspect <url>` opens an isolated stage, waits for the page to settle, and returns viewport, scroll container, and interactive element details with selectors and positions; no playbook is needed. `--rehearse` runs actions in order and checks zoom selectors in the stage without recording. Page actions still take effect; use it only on pages where those actions are permitted.

For Playbook zooms, `mode` defaults to `manual`, which requires one `selector` or `target`. Explicit `auto` follows pointer intents and must not include a target. A selector is resolved before the beat actions, so later scrolling does not change its target.

---
name: oil-studio
description: >
  Record and edit local Oil Studio recording projects: demonstrate a window or screen using your own app-control tools,
  find projects, read transcripts and generate captions, refine voice-over recordings by removing retakes, slips, abandoned sentences,
  and gaps, tighten pauses, remove idle time, adjust zooms and project settings, add titles, labels, or image overlays, redact sensitive screen regions,
  proofread captions, add chapters, translate captions into English, synthesize AI voice-over narration, and export SRT files or videos. Editing proposals are reviewed in Oil Studio by default; caption corrections and chapters
  apply immediately and can be undone. Use when the user mentions Oil Studio or recording projects, asks to record
  an app demonstration, refine a voice-over, add a title or image, redact screen content, adjust recording zooms, generate or correct captions, or export a
  recording. Not for editing ordinary MP4/MOV files or directly changing files inside a project package.
  用 Oil Studio 录制和处理本机的录屏工程：录一段窗口或屏幕的操作演示、精剪口播、收紧停顿、删除操作空档、调整画面缩放、添加标题/图片、遮盖敏感区域、校对或翻译字幕、划分章节、合成 AI 配音并导出成片。
metadata:
  version: 0.9.13
  minAppVersion: 0.3.26
---

# Oil Studio

Use `oilstudio` to work with recording projects. Each command returns a JSON object. You interpret evidence and make editing decisions; the command-line tool reads, validates, and applies changes.

Use this English workflow for an English conversation; use the Chinese entry at the package root for Chinese. Follow only one entry. Both support Chinese and English audio. Command output follows the app language; add `--lang en` to override it without changing preferences. Speech language is separate: `transcribe --locale en-US` or `--locale zh-CN` overrides the project's language.

Task navigation: [Fine cut](#fine-cut) · [Overlays and redactions](#add-overlays-and-redactions) · [Generate captions](#generate-captions) · [Proofread captions](#proofread-captions) · [Export video](#export-video). See the task table for other workflows.

## Before starting

1. Run `OILSTUDIO_SKILL_VERSION=0.9.13 oilstudio status`, using this file's frontmatter `metadata.version`.
   - If the command is missing, tell the user to open Oil Studio and choose Install in Settings › AI Agent, then stop.
   - If `skill.compatible` is present and false, report `skill.action.message` and `skill.action.hint` and stop. If true, continue. If null, check the supplied version and stop.
   - If `skill.compatible` is absent, the app is older. Compare `app.version` with this file's `minAppVersion` numerically, component by component; ask the user to update Oil Studio and stop if it is too old. If the version is unavailable, explain that compatibility could not be checked; do not substitute `cli.version`.
2. Identify the project path. Oil Studio projects are packages ending in `.oilstudio`.
   - Use a supplied `.oilstudio` path directly.
   - For another recording app's project, run `oilstudio import <path>`, continue with the returned `path`, and explain where the converted project was saved and that the original is unchanged. Reimporting returns the existing conversion without another copy.
   - With no path, run `oilstudio projects`, which lists only native projects. Choose by title and date; ask the user if multiple candidates fit.
3. On failure, read `error.code` and `error.hint`. Stop after the same command fails twice and report its `message`.
   - `SKILL_OUTDATED`: stop retrying immediately and report `message` and `hint` to the user.
   - `needs_import`: import first as above.
   - `read_only`: a newer version created the project. Read and export only; ask the user to update before submitting changes.

## Choose a task

| Request | Workflow |
| --- | --- |
| Record an app or website demonstration | Record a demonstration |
| Choreograph web actions, beat captions, HUD cards, and zooms | Record from a web playbook |
| Remove waits with no voice-over | Remove idle time |
| Remove retakes/slips and clean up captions together | Fine cut + Proofread captions (complete both in one pass) |
| Remove retakes, slips, and abandoned speech | Fine cut |
| Remove only pauses and silence | Tighten pauses |
| Make the subject easier to see | Adjust zooms |
| Add a title, label, or image/B-roll, or cover a sensitive screen region | Add overlays and redactions |
| Generate initial captions | Generate captions |
| Correct transcription errors, residual fillers, or line wrapping | Proofread captions |
| Change canvas, background, cursor, camera, audio, or export settings | Adjust project settings |
| Add chapter names to the progress bar | Add chapters |
| Translate Chinese captions into English | English subtitles |
| Get an SRT file | Export subtitles |
| Get a video | Export video |
| Understand content, duration, or speech | Run `oilstudio context <project> --out <temporary-file>`, then answer without submitting changes |

## Shared rules

- Access projects only through `oilstudio`; never read or write package contents directly.
- Submit changes only through `plan submit`, `subtitles apply`, `chapters apply`, `pauses --submit`, `idle --submit`, or `settings apply`. Check `autoApplied`:
  - `false`: say the proposal awaits approval in Oil Studio. Save `proposalId` and outstanding follow-up work. A wait timeout is neither rejection nor completion.
  - `true`: report only the actual `applied` entries and `skipped` reasons. Explain that ⌘Z undoes changes; do not wait on `proposal status`.
  - Context's `autoApply` predicts this behavior. If it is true but submission returns `autoApplied: false`, the project is closed; changes will apply when it opens. Tell the user before exporting.
- `subtitles generate` creates and saves undoable captions through the app without a proposal. `transcribe` only prepares a transcript cache.
- `narration generate / import` saves caption narration directly. Changes to an open project are undoable in one step; offline projects are checked for version compatibility before saving. See [Caption narration](references/narration.md).
- `chapters apply` always applies directly, regardless of the project's automatic-edit preference or chapter review. `autoApplied: false` means the project is closed, not ready, or queued behind another review; follow `pendingReason` and never describe it as waiting for chapter approval.
- Locate edits with utterance IDs such as `U0012` or source-time milliseconds. Never use output time for cuts or zooms. Layout proposals explicitly use output time.
- During intermediate steps before submitting final changes or finishing export, run `oilstudio progress "<completed step>" --step <step>/<total> --project <project>`; do not call `oilstudio progress` again after the final submission or completion. `delivered: false` means the app is closed; continue.
- Use a new temporary filename for each `--out`; existing files are not overwritten.
- Validate before submitting. Fix rejected entries and validate again. `plan validate` checks submitted entries, not candidates omitted from the plan.
- Submit titles, labels, image/B-roll overlays, and redactions as the plan's top-level `overlays` and `redactions` arrays. `plan validate` validates without changing the project or importing images. Check the actual applied and skipped entries in the submission receipt.
- When the user returns with a continuation, correction, or status question, check the saved proposal status first. If applied, resume already-authorized work from current project data without asking for authorization again. Preserve pending work while review continues. Never resubmit `USER_DISMISSED` automatically. For invalidated proposals, fetch fresh evidence instead of copying new fingerprints onto an old plan.

## Record a demonstration

Start and stop recording with the CLI; operate the target with your own computer or browser tools. Read [Recording](references/recording.md). Skip project selection in “Before starting” because recording creates one.

For multi-step web demonstrations that need beat-aligned zooms or analysis cards, use [Web playbooks](references/recording.md#web-playbooks) and `scripts/record_playbook.py`. This workflow controls web pages through the browser automation API only; do not use Computer Use. Captions are off by default; add them only when the user explicitly requests captions.

1. If `status` reports `app.running: false`, run `open -a "Oil Studio"`, wait briefly, and check again.
2. Prepare the target window's opening state, including login and sizing, before recording.
3. Run `oilstudio record sources`, identify the window by `app` and `title`, and keep its `id`.
   - Only the user may grant macOS screen-recording access and Oil Studio's permission for agents to start recording. Never click these approval dialogs or change system settings yourself.
   - On `PERMISSION_REQUIRED`, report `message` and stop. Resume from this step after the user confirms access.
   - Ask if multiple windows fit. Record only the requested window; choose a display only when explicitly requested.
4. Optionally run `oilstudio record prepare --source <id> --size 1280x800 --center --activate`; use either `--position X,Y` or `--center`. The same options work on `record start`. Adjusting an external window requires Accessibility access.
5. Run `oilstudio record start --source <id>`. Microphone, camera, and system audio remain off unless explicitly requested with `--microphone`, `--camera`, or `--system-audio`.
   - On `RECORDER_BUSY`, explain that the user is recording and stop.
6. Operate the target. Waits can be removed later.
   - Before every click, run `oilstudio record click --at <x>,<y>` or `--at-fraction <u>,<v>`, then click immediately after the command returns. Add `--perform` to have Oil Studio perform the native click without a second click. Oil Studio generates the cursor from these reports; the real mouse is not recorded. Without a report, there is no cursor or click-following zoom for that action.
   - To point without clicking, use `oilstudio record move` with the same coordinates; add `--perform` to move the real pointer too. See Recording for coordinate conversion.
7. Run `oilstudio record stop` and keep `path`. To restart a bad take, use `oilstudio record stop --discard`, then return to step 2.
8. Follow Remove idle time.
9. Follow Adjust zooms for small text or details; Export video when requested.
10. Report the project path, output duration, and idle time removed.

Do not send `progress` during recording, before a project path exists. Resume progress reporting after stopping.

## Remove idle time

Use for silent demonstrations or long waits between operations. For voice-overs, prefer Tighten pauses or Fine cut.

- For a project you just recorded, run `oilstudio idle <project> --submit` directly. It returns candidates and applied changes together, aligns delayed click reports to screen changes, and rebuilds automatic zooms using the edited timeline and changed areas.
- For other projects, run `oilstudio idle <project>`, report the count and possible saving, then add `--submit` with the same parameters after authorization.
- Increase `--keep <milliseconds>` to retain more time at each gap's edges; default 400. Increase `--threshold <milliseconds>` to remove only longer waits; default 1500.
- Report according to `autoApplied`. No candidates means no submission and no `proposalId`.

## Fine cut + captions in one pass (standard command flow)

When the user asks to both cut the video and prepare/proofread captions, run these 5 steps consecutively in the same pass—**do not stop after `plan submit` to wait for approval first**:

```sh
# 1. If the project has no captions yet (subtitles.count == 0), generate captions and transcript cache together
oilstudio subtitles generate "<project>" --engine auto

# 2. Export editing context and pause-cleanup draft
oilstudio context "<project>" --out "$WORK/01-context.json"
oilstudio pauses "<project>" --out-plan "$WORK/02-plan.json"

# 3. Append semantic cuts to 02-plan.json, check filler coverage, validate, and submit the cut plan
python3 -B "<skill-dir>/scripts/check_filler_coverage.py" --context "$WORK/01-context.json" --plan "$WORK/02-plan.json" --out "$WORK/03-coverage.json"
oilstudio plan validate "$WORK/02-plan.json"
oilstudio plan submit "$WORK/02-plan.json"

# 4. Read post-cut visible captions and diagnostics using --plan (without waiting for app approval first)
oilstudio subtitles get "<project>" --plan "$WORK/02-plan.json" --out "$WORK/04-subtitles.json"

# 5. Clear diagnostics (typos, inconsistent casing, residual fillers/stutters, layout warnings) and submit directly (without --review)
oilstudio subtitles apply "<project>" "$WORK/05-subtitle-edits.json"
```

For chapters, prepare from post-cut captions with `--plan` after step 1, but submit against the current project only after the cut plan is actually applied. This avoids invalidating chapters with a pre-cut fingerprint.

## Fine cut

1. Run `oilstudio context <project> --transcript-first --out <temporary-file>` and read it.
   - If the user also wants captions and `subtitles.count` is 0, run `oilstudio subtitles generate <project> --engine auto` first (it creates both project captions and the transcript cache), then fetch new context to a fresh filename.
   - Otherwise, if `utterances` is empty, run `oilstudio transcribe <project>` and fetch new context to a fresh filename.
2. Run `oilstudio pauses <project> --out-plan <cleanup.json>` and read `planPath`. This writes a draft without applying it. Keep its fingerprints and `decisions`; append semantic cuts to the same plan.
   - The draft already protects word edges. Do not add another 50 ms to each cut's start and subtract 50 ms from its end. Set additional breathing room once with `pauses --keep <milliseconds>`; otherwise keep the default.
   - Handle cleanup failures instead of silently skipping them. With no pauses, continue with empty decisions.
   - Draft and context fingerprints must match; otherwise reread both.
3. Read [Editing judgment](references/editing-judgment.md), then read all utterances before choosing retakes, slips, abandoned speech, or independently removable fillers. Use source time; original audio still contains proposed pauses.
   - Follow the requested Conservative, Standard, or Compact style; default Standard.
   - Review every `fillerCandidates` entry in full context. Record `cut`, `keep`, or `review` with a specific reason. A candidate fully covered by a passage cut needs no duplicate cut.
   - `utterances[].audio` provides confidence, pace, loudness, internal pauses, and unrecognized speech. `screen` provides OCR over time. These are evidence, never automatic reasons to delete.
   - Listen with `oilstudio audio <project> --source-ms <start>,<end> --out <wav>`; maximum 60 seconds.
   - Inspect with `oilstudio frame <project> --source-ms <milliseconds> --zoom none --text --out <png>`. For a range, use `oilstudio storyboard <project> --utterances <first>-<last> --out <png>` or `--source-ms <start>,<end>`; maximum 40 seconds. `--every 1000` controls sampling; `--no-frames` shows only audio and text.
4. Follow [Proposal formats](references/proposal-formats.md). Append semantic cuts and explicit keep/review decisions to the cleanup draft; put requested zoom changes in `zooms`. Run its coverage check and report passage-covered, individually cut, retained, and review candidates. Selecting only a few long hesitations or reporting silence counts is not a complete fine cut. Do not double-count overlaps or submit an empty executable plan.
5. Run `oilstudio plan validate <plan>`. Fix all `rejected` results and validate again; leave `uncheckedByDefault` for review.
   - `cutAdjustments` reports verified word-boundary alignment and strict silence cleanup. Preview, submission, and caption projection use the same ranges. `boundaryReviews` identifies content outside a cut that could not be verified for removal; it stays in the video and is noted on the decision. Check those specific joins rather than treating successful application as proof that every fragment is gone.
   - With audio-understanding capability, optionally run `oilstudio plan preview <plan> --index <zero-based-result-index> --out <wav>`. `joinOutputMs` locates the join; `ranges` lists retained original audio. Speed changes, repeats, reordering, complete removal, or no microphone are unsupported; skip preview when audio understanding is unavailable.
6. Run `oilstudio plan submit <plan>` once and keep `proposalId`. Never edit package files.
   - When the user also asked for captions or caption proofreading, do **not** stop after `plan submit` to wait for approval first: immediately proceed to “Proofread captions” using `oilstudio subtitles get <project> --plan <plan> --out <subtitles.json>` and submit `subtitles apply` in the same pass.
7. Check actual `applied`/`skipped` entries when applied automatically. Otherwise save `proposalId` and use `oilstudio proposal status <proposalId> --wait --timeout 30` unless asked not to wait. If still pending, report review and follow-up work separately. After application, fetch fresh `context <project> --no-pauses --out <new-file>` and compare accepted source ranges against residual fillers, false starts, and repetition. Report actual application counts and ⌘Z undo. Calculate savings from the union of source intervals, never from candidate counts.

## Tighten pauses

1. Run `oilstudio pauses <project>` and report the count and possible saving. Add user-specified `--threshold <milliseconds>` and `--keep <milliseconds>`.
2. Once authorized, run the same command with `--submit`. Report using the shared rules and Fine cut step 7.

## Adjust zooms

1. Run `oilstudio context <project> --out <temporary-file>` and read `utterances`, `activity`, and `zooms`. Reuse context from a fine cut when current.
2. Read [Zoom judgment](references/zoom-judgment.md). Decide where to move closer, by how much, and which existing zooms to change or remove.
   - Inspect the full screen with `oilstudio frame <project> --source-ms <milliseconds> --zoom none --text --out <png>`.
   - Omit `--zoom none` when checking the current effect.
3. Follow Proposal formats to write `zooms`; combine them with cuts in one plan when fine-cutting.
4. Validate, submit, and report as in Fine cut steps 5–7.

## Add overlays and redactions

Use this workflow to add a title, label, or still image/B-roll, or to cover sensitive screen content. Run `oilstudio context <project> --out <temporary-file>` and read the existing `overlays` and `redactions`. Inspect the picture and recognized text with `oilstudio frame <project> --source-ms <milliseconds> --text --out <png>` when needed.

1. Following [Proposal formats](references/proposal-formats.md), add top-level `overlays` and/or `redactions` arrays to the plan. They can accompany `decisions`, `zooms`, and `layouts`. The proposal fields are flat; do not copy the nested shape used by `context.overlays`.
2. For an image, `sourcePath` must be an absolute local image path; an existing filename in the project's `assets/overlays/` can be referenced with `file`. `plan validate` does not modify the project or import images. An accepted submission imports the image into `assets/overlays/`, deduplicated by SHA-256.
3. Run `oilstudio plan validate <plan>`, fix every rejected item, and validate again before submitting once with `oilstudio plan submit <plan>`. Check the receipt's `applied` and `skipped` indexes. If `autoApplied: false`, save `proposalId` and follow the shared review rules. Applied changes can be undone with ⌘Z in Oil Studio.
4. After application, inspect relevant times with `oilstudio frame <project> --output-ms <milliseconds> --text --out <png>`. Check the visible title, image, or mask; when exporting, verify the redaction still covers the sensitive area throughout the exported video. If OCR or visual inspection still exposes sensitive content, revise and revalidate the proposal before reporting it complete.

A redaction uses a fixed rectangle in source-frame coordinates and does not automatically track a moving object. Do not promise automatic tracking. For content that moves, propose separate time ranges and regions only when you can inspect them; otherwise ask the user to review the coverage.

## Generate captions

When captions are needed for generation, proofreading, translation, or export and none exist, generate them yourself rather than asking the user to click the Captions tab.

1. Run `oilstudio subtitles generate <project> --engine auto`. Add `--locale en-US` or `zh-CN` to override the speech language.
2. For `APP_REQUIRED`, run `open -a "Oil Studio" <project>`, wait until `status.openProjects` lists it, then retry. Stop and explain the error after two failed generation attempts.
3. Auto mode prefers cloud recognition when the selected region has a configured API key, then verified installed Whisper, then an available installed system model. If none is available, explain how to configure a cloud API key or install a local model in Settings. Do not request secrets or download models silently. Cloud recognition uploads the recording’s audio to the selected region. For an explicit local request, use `--engine whisper` or `--engine system`. Cloud is preferred when both are available.
4. Do not repeatedly retry a failed cloud request or silently switch engines. Follow the error. Use `--region beijing|singapore` for a one-command override without changing app preferences.
5. Only final `ok: true` confirms completion. `generated: true` means captions were saved; `false` means existing captions were retained. Report cloud/local recognition from the returned `engine`; `auto` does not mean local. Read captions back before continuing. Use `--force` only when recognition again is explicitly requested; preserve manually edited cues.
6. When the user asked to generate captions and did not decline chapters, run `oilstudio chapters get <project>`. If `outputDurationMs` is strictly greater than 180000 and `chapters` is empty, follow “Add chapters” to read the new captions, then create and apply chapters. Skip short videos and existing manual chapters. You provide the semantic split; the CLI does not generate chapters by itself.

If the user explicitly requires approval even for initial caption creation, explain that `subtitles generate` has no proposal mode; prepare analysis with `transcribe` first. `transcribe` creates analysis data, not project captions.

## Adjust project settings

Read [Project settings and export](references/video-settings-and-export.md). Discover fields with `settings schema`, read current values and the fingerprint with `settings get <project>`, and submit only requested fields. `settings apply` follows the project’s automatic edit preference; `--review` requires review. Confirm application and read back settings before exporting.

## Proofread captions

1. Run `oilstudio subtitles get <project> --out <temporary-file>` (when fine-cutting in the same pass, pass `--plan <plan.json>` so `outputStartMs`, `displayText`, and `diagnostics` are projected onto the post-cut timeline). If no captions exist, follow “Generate captions,” then read them again to a new temporary filename.
2. Read [Caption proofreading](references/subtitle-proofreading.md). Inspect `diagnostics` (`inconsistentTerms`, `residualFillers`, `repeatedWords`, `glossaryMatches`, `lowConfidenceWords`, `layoutWarnings`) alongside `glossary.replacements` and `glossary.hotwords`. Correct recognition errors, unify inconsistent term casing, clean residual written fillers/stutters on retained cues, and fix layout warnings.
3. Write edits following Proposal formats. Copy `expectedText` exactly from returned `text`, never `displayText`.
4. Run `oilstudio subtitles apply <project> <edits>`. Edits apply directly by default (do not pass `--review` unless the user explicitly asks to review caption wording item by item; the generic toolbar brief about confirming proposals in the app applies to `plan submit`, not caption typo fixes). When a cut review is open in the app, `subtitles apply` without `--review` queues with `pendingReason: review_in_progress` and auto-applies once the user confirms the cut plan.
5. Inspect the receipt. For `autoApplied: true`, check `applied` and `skipped`; for false, wait for `proposal status`. `pendingReason: review_in_progress` means queued behind another review. On dismissal, inspect `reason`; rebuild from current captions only for a project change or validation failure, never automatically for `USER_DISMISSED`. After application, get captions again under a new filename, verify accepted edits, cleared `diagnostics`, and unchanged timings.
6. Report the actual applied count and two or three significant corrections, explain ⌘Z and skipped edits, and list glossary suggestions separately. Suggestions still require adding to the app glossary. Do not export until edits are applied and verified.

## Add chapters

1. Run `oilstudio chapters get <project>`. Skip videos at or below 180000 ms. Keep existing chapters unless the user explicitly asks to reorganize them.
2. Run `oilstudio subtitles get <project> --out <temporary-file>` and read all captions. If none exist, follow “Generate captions” first.
3. Read the Chapters section in [Chapters and translation](references/chapters-and-translation.md) and choose boundaries and titles. Position does not belong in this file; when the user requests top or bottom, use `settings apply` separately for `subtitles.chapterProgressPosition`.
4. Write the chapter file and run `oilstudio chapters apply <project> <chapters>`. Chapters apply immediately and enable the progress bar without user confirmation or a chapter-review wait.
5. After `autoApplied: true`, read back with `chapters get`, report the actual count, and explain undo and manual editing/deletion in the app. For false, follow `pendingReason` for project readiness or queued work.
6. When a cut plan is part of the same pass, wait until it is actually applied before submitting chapters against the current project. Do not queue chapters with a stale pre-cut fingerprint.

## English subtitles

1. Run `oilstudio subtitles get <project> --out <temporary-file>`. If Chinese captions have not been proofread, ask whether to proofread first; translate the finalized source text. For already-English speech, proofread or export the original captions rather than inventing a second translation.
2. Read the Translation section in Chapters and translation. Translate each cue.
3. Write the translation file and run `oilstudio subtitles apply <project> <translation> --locale en`. Report using shared rules and Fine cut step 7.
4. For a file, run `oilstudio subtitles export <project> --locale en --out <path.srt>`.

## Export subtitles

Run `oilstudio subtitles export <project> --out <path.srt>`. Save beside the .oilstudio project package, using the same base name by default. Ask before adding `--overwrite` to replace an existing file.

## Export video

Read the export section of [Project settings and export](references/video-settings-and-export.md). Run `oilstudio export <project> --out <path.mp4>`. Unspecified options use the project’s saved export settings. Save beside the project package unless requested otherwise. MP4/GIF, Minimal quality, HEVC compression, and output time ranges are supported.

- Add `--subtitles burn` to burn in captions, and `--srt` for a separate SRT file.
- Ask before overwriting an existing file.
- Export may take several minutes. Report its path and duration when done.
- After submitting edits, confirm `autoApplied: true` or proposal state `applied` before exporting; otherwise the export contains the old edit.

## Finish

Use two or three sentences: what changed, what was submitted with its `proposalId` or exported path, and what the user still needs to do. Do not paste the full JSON.

For TTS or external caption narration, read [Caption narration](references/narration.md) and use `narration status / generate / import`. Generation and import save directly and are undoable in the app.

---
name: oil-studio
description: >
  Record and edit local Oil Studio recording projects: demonstrate a window or screen using your own app-control tools,
  find projects, read transcripts and generate captions, refine voice-over recordings by removing retakes, slips, abandoned sentences,
  and gaps, tighten pauses, remove idle time, adjust zooms and project settings, add titles, labels, or image overlays, redact sensitive screen regions,
  proofread captions, add chapters, translate captions into English, synthesize AI voice-over narration, and export SRT files or videos. Editing proposals are reviewed in Oil Studio by default; caption corrections and chapters
  apply immediately and can be undone. Use when the user mentions Oil Studio or recording projects, asks to record
  an app demonstration, refine a voice-over, add a title or image, redact screen content, adjust recording zooms, generate or correct captions, or export a
  recording. Also turns an existing MP4/MOV/M4V into a project so a clip can be cut from it and its cut points reviewed in context.
  Not for quick edits of ordinary video files the user does not want in Oil Studio, or for directly changing files inside a project package.
  用 Oil Studio 录制和处理本机的录屏工程：录一段窗口或屏幕的操作演示、精剪口播、收紧停顿、删除操作空档、调整画面缩放、添加标题/图片、遮盖敏感区域、校对或翻译字幕、划分章节、合成 AI 配音并导出成片；也可以把现成视频导入成工程，切出一段并核对切点。
metadata:
  version: 0.14.6
  minAppVersion: 0.3.44
---

# Oil Studio

Use `oilstudio` to work with recording projects. Each command returns a JSON object; longer commands such as import and transcribe first print progress lines, and the last line is the result. You interpret evidence and make editing decisions; the command-line tool reads, validates, and applies changes.

Use this English workflow for an English conversation; use the Chinese entry at the package root for Chinese. Follow only one entry. Both support Chinese and English audio. Command output follows the app language; add `--lang en` to override it without changing preferences. Speech language is separate: `transcribe --locale en-US` or `--locale zh-CN` overrides the project's language.

Task navigation: [Fine cut](#fine-cut) · [Overlays and redactions](#add-overlays-and-redactions) · [Generate captions](#generate-captions) · [Proofread captions](#proofread-captions) · [Export video](#export-video). See the task table for other workflows.

## Before starting

1. Run `OILSTUDIO_SKILL_VERSION=0.14.6 oilstudio status`, using this file's frontmatter `metadata.version`.
   - If the command is missing, run the installer from the Oil Studio website, `curl -fsSL https://studio.oiloil.org/agent/install.sh | sh`, and first tell the user that it installs the Oil Studio command line. The Mac App Store edition installs directly; run this step again afterward. If the installer says the website edition includes the command line, ask the user to choose Install in Settings › AI Agent in Oil Studio, then stop. If it says Oil Studio isn't installed or this version isn't supported yet, report that to the user and stop.
   - If `skill.compatible` is present and false, report `skill.action.message` and `skill.action.hint` and stop. If true, continue. If null, check the supplied version and stop.
   - If `skill.compatible` is absent, the app is older. Compare `app.version` with this file's `minAppVersion` numerically, component by component; ask the user to update Oil Studio and stop if it is too old. If the version is unavailable, explain that compatibility could not be checked; do not substitute `cli.version`.
   - If `skill.update` is present, this Mac has a copy of the Skill older than the one built into the app, possibly the copy you're reading. Tell the user `skill.update.message`; with their approval, run `installations[].command`, which renames the old folder as a backup and replaces it with a link that follows app updates. New sessions read the new version. This doesn't affect the current task; continue.
   - If `app.relaunchRequired` is true, the running Oil Studio was moved or deleted and recording will fail. Ask the user to quit Oil Studio and open it again from the Applications folder, then stop.
   - Inspect `app.channel`, `app.otherInstallations`, `warnings`, and `speech` when present: if both website and Mac App Store editions are installed, their settings and cloud API keys are separate. If `warnings` notes multiple copies or `speech.autoResolvedEngine` is `system` / `null` before a long transcription, confirm the target copy and speech engine with the user first.
2. Identify the project path. Oil Studio projects are packages ending in `.oilstudio`.
   - Use a supplied `.oilstudio` path directly.
   - For another recording app's project, run `oilstudio import <path>`, continue with the returned `path`, and explain where the converted project was saved and that the original is unchanged. Reimporting returns the existing conversion without another copy.
   - For a video file (MP4, MOV, or M4V), import it as described in Cut a clip from a video. Every video import creates a new, independent project; name it with `--name`.
   - With no path, run `oilstudio projects`, which lists only native projects. Choose by title and date; ask the user if multiple candidates fit.
3. On failure, read `error.code` and `error.hint`. Stop after the same command fails twice and report its `message`.
   - `SKILL_OUTDATED`: stop retrying immediately and report `message` and `hint` to the user.
   - `CLI_UPDATE_REQUIRED`: Oil Studio was updated but the command line is older. Run the installer from step 1, then retry once.
   - `APP_NOT_INSTALLED`: Oil Studio isn't installed on this Mac. Ask the user to install it, then stop.
   - `PERMISSION_REQUIRED`: report `message` and `hint`, then stop. It names the missing access (or, in older versions of Oil Studio, says the user canceled the access request); if it says the terminal or AI sandbox blocked local access, ask the user to allow running `oilstudio` outside the sandbox instead of trying `open -a "Oil Studio"` or retrying inside the sandbox.
   - `needs_import`: import first as above.
   - `UNSUPPORTED_MEDIA`: the video's format or codec isn't supported, it has no picture, or it's copy-protected. Report `message` to the user; don't retry with other options.
   - `read_only`: a newer version created the project. Read and export only; ask the user to update before submitting changes.

## Choose a task

| Request | Workflow |
| --- | --- |
| Record an app or website demonstration | Record a demonstration |
| Choreograph web actions, beat captions, HUD cards, and zooms | Record from a web playbook |
| A voice-over is already recorded (person and voice only) and needs matching screen actions | Add screen recordings to a voice-over |
| Edit an existing video (MP4, MOV, M4V) in Oil Studio, or cut a clip from a long video | Cut a clip from a video |
| Remove waits with no voice-over | Remove idle time |
| Remove retakes/slips and clean up captions together | Fine cut + captions in one pass (standard command flow) |
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
  - `false`: say the proposal awaits approval in Oil Studio. Save `proposalId` and outstanding follow-up work. A wait timeout is neither rejection nor completion. If the result also has `skipped` and an empty `applied`, nothing was applied (the project applies AI changes directly, but these items were skipped); act on the reasons in `skipped` instead of saying it awaits approval.
  - `true`: report only the actual `applied` entries and `skipped` reasons. Explain that ⌘Z undoes changes; do not wait on `proposal status`.
  - Context's `autoApply` predicts this behavior. If it is true but submission returns `autoApplied: false`, the project is closed; changes will apply when it opens. Tell the user before exporting.
- `subtitles generate` applies directly, like chapters, without user approval; the captions can be undone in the app later. The project doesn't need to be open in the app, and the app doesn't need to be running. If the project has an AI change still waiting for the user's approval, it refuses and explains why, without recognizing speech or changing the project: ask the user to handle that change in Oil Studio first. It also refuses while Oil Studio is busy applying another change; retry once a little later. `transcribe` only prepares a transcript cache.
- `narration generate / import` saves caption narration directly. Changes to an open project are undoable in one step; offline projects are checked for version compatibility before saving. See [Caption narration](references/narration.md).
- `chapters apply` always applies directly, regardless of the project's automatic-edit preference or chapter review. `autoApplied: false` means the project is closed, not ready, or queued behind another review; follow `pendingReason` and never describe it as waiting for chapter approval.
- Locate edits with utterance IDs such as `U0012` or source-time milliseconds. Never use output time for cuts or zooms. Layout proposals, export ranges, `--at-output-ms` when adding screen recordings to a voice-over, and screen clip `move` entries explicitly use output time. When a command has `--plan <plan-file>`, its output times are on the plan’s cut timeline.
- During intermediate steps before submitting final changes or finishing export, run `oilstudio progress "<completed step>" --step <step>/<total> --project <project>`; do not call `oilstudio progress` again after the final submission or completion. `delivered: false` means the app is closed, and `PROJECT_NOT_FOUND` means the app has a different project open; continue in either case.
- Use a new temporary filename for each `--out`; existing files are not overwritten.
- Validate before submitting. Fix rejected entries and validate again. `plan validate` checks submitted entries, not candidates omitted from the plan.
- Submit titles, labels, image/B-roll overlays, and redactions as the plan's top-level `overlays` and `redactions` arrays. `plan validate` validates without changing the project or importing images. Check the actual applied and skipped entries in the submission receipt.
- When the user returns with a continuation, correction, or status question, check the saved proposal status first. If applied, resume already-authorized work from current project data without asking for authorization again. Preserve pending work while review continues. Never resubmit `USER_DISMISSED` automatically. For invalidated proposals, fetch fresh evidence instead of copying new fingerprints onto an old plan; the only exception is step 8 of Add screen recordings to a voice-over, where the only change is clips you recorded.

## Record a demonstration

Start and stop recording with the CLI; operate the target with your own computer or browser tools. Read [Recording](references/recording.md). Skip project selection in “Before starting” because recording creates one.

For multi-step web demonstrations that need beat-aligned zooms or analysis cards, use [Web playbooks](references/recording.md#web-playbooks) and `scripts/record_playbook.py`. This workflow controls web pages through the browser automation API only; do not use Computer Use. Captions are off by default; add them only when the user explicitly requests captions.
**Never record a browser window while an agent controls it**: such browsers draw a control bar, a border, and action captions on the page, and they end up in the video. Use the playbook's isolated stage (the default) for web demonstrations; when you need a signed-in session or several tabs, use the cdp host to connect to a browser the user started. See [Recording](references/recording.md#browser-hosts).

1. If `status` reports `app.running: false`, run `open -a "Oil Studio"`, wait briefly, and check again.
2. Prepare the target window's opening state, including login and sizing, before recording.
3. Run `oilstudio record sources`, identify the window by `app` and `title`, and keep its `id`.
   - Only the user may grant macOS screen-recording access to Oil Studio; never change system settings yourself. Older versions of Oil Studio also ask the user to allow agent recording the first time: the command waits for their answer, so never click that dialog yourself.
   - On `PERMISSION_REQUIRED`, report `message` and `hint`, then stop; they name the missing access, note if a sandbox blocked local access, or say the app needs to be reopened. Resume from this step after the user resolves it.
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

## Add screen recordings to a voice-over

A voice-over project comes from Voice-Over Only recording: the main timeline holds only the person (camera) and the voice, and context reports `voiceOver: true`. Until any screen recording is added, the video shows the person full frame; after that, it shows the screen with the person in a small window, and a gap on the screen track doesn’t switch back to the person but holds the previous clip’s last frame. Your job is to record the screen actions the speaker describes, land each action on the moment it is mentioned, and **fill the screen track**: everywhere someone is speaking needs a picture, and waits with no speech get cut. Screen clips behave like ordinary recordings: they have the cursor, click zooms, and redactions. Read [Recording](references/recording.md) first.

1. Run `oilstudio context <voice-over project> --out <temporary-file>`; if `utterances` is empty, run `transcribe` first. Look at three things: `utterances` (each sentence’s `outputStartMs / outputEndMs` and each word’s `outputStartMs`), `screenGaps` (output ranges that still have no picture), and existing `screenClips`.
2. If the voice-over has obvious waits (long pauses) or slips, cut first and add pictures on the cut timeline:
   - If context reports `autoApply: true`, submit Tighten pauses or Fine cut as usual, read context again after it applies, then add pictures.
   - Otherwise write the plan as in Fine cut and run `plan validate`, but **don't submit it yet**. Recording into the project changes it, so a submitted plan still awaiting confirmation would become invalid. Add `--plan <plan-file>` to the following `context`, `record start`, and `frame` commands so they read and place everything on the plan’s cut timeline. A returned `plan.stale: true` only means your recordings changed the project; the projection still works.
3. Split the narration into picture segments, one sentence or a few consecutive sentences each: what the segment says → which window and which actions → which step happens at which word. Make segments meet end to end: start each one where the previous one ends and record until the next one starts. Conceptual stretches with no demonstrable action still need a picture: record the neighboring segment a little longer and stay on a relevant page instead of leaving a gap. A gap of a fraction of a second between segments is fine; the screen holds the previous clip’s last frame. If you can’t tell which page or feature to show, ask the user; never invent actions. With more than five segments, show the plan to the user first.
4. Prepare the window for the segment’s opening state (not recorded) and find its `id` with `record sources`.
5. Record a segment: `oilstudio record start --source <id> --into <voice-over project> --at-output-ms <output ms where the segment starts> [--plan <plan-file>]`. Don’t add `--microphone`, `--camera`, or `--system-audio`.
   - Recording advances in real time from that moment: N milliseconds after starting is output time `at-output-ms + N`. To make a step happen when a word is spoken, perform it `word outputStartMs − at-output-ms` milliseconds after starting; `durationSourceMs` from `record status` tells you how long you’ve recorded. Report clicks with `record click` as usual.
   - When a step needs time to respond (page loads, animations), start it earlier so the result appears when it’s mentioned.
   - At the moment the segment should end (the sentences are finished, or the next segment starts), run `oilstudio record stop`. The returned `screenClip` is the clip attached to the voice-over and already saved; `path` is the voice-over project.
   - **To record a segment again**, add `--replace-until-output-ms <output ms where the segment ends>`. Before the new clip goes in, older clips in `[at-output-ms, that moment)` are cleared, so no tail of an old clip is left behind it; if the new clip is shorter, the rest shows up in `screenGaps`.
   - **With `--plan`, add `--replace-until-output-ms <output ms where the segment ends>` to every segment**: the parts the plan cuts are still in the current project, so without an end, an older clip after this segment would cover the new clip’s end once the plan applies.
   - For web demonstrations, use `attach` and per-action `atMs` in a [web playbook](references/recording.md#web-playbooks); the script waits on the recording clock for each step. `attach.plan` and `attach.replaceUntilOutputMs` map to the two options above.
6. Check each segment: at the moment its key word is spoken, run `oilstudio frame <voice-over project> --output-ms <ms> --zoom none --text --out <png> [--plan <plan-file>]` and confirm the picture shows what the narration says. If it’s early or late, use `screenClips` in `plan submit` to `move`, `trim`, or `speed` the clip; if it’s wrong, record that segment again as in the previous step. See [Proposal formats](references/proposal-formats.md).
7. When every segment is done, read context again (with `--plan` if you have a draft plan) and confirm `screenGaps` is empty (gaps under 0.5 seconds between segments can be ignored). If a gap remains and someone is speaking in it, record more or record a neighboring segment longer; if it is a wait with no speech, add that part of the voice-over to the cut plan. Submit a `camera` layout only when the user explicitly wants the person full frame somewhere.
8. With a draft plan, submit it once at the end. Your recordings changed the project, so the plan’s two fingerprints are out of date. Read context into a new file, confirm `utterances` match what you planned from (only your clips were added), then copy the new `projectFingerprint` and `contextFingerprint` into the plan, run `plan validate`, then `plan submit`, and report as in Shared rules. If `utterances` changed, the user edited the project; prepare the plan again. When the user wants a video, export after the plan applies.
9. Report how many segments you added, which sentences each covers, which waits you cut, and anything the user should check.

## Cut a clip from a video

Use this when the user has an existing video to edit in Oil Studio, or wants one or more clips from a long video. Each project exports one clip, so each clip gets its own project.

1. Import once to choose the clips: `oilstudio import <video> --name "<video name> (Full)" [--directory <folder>]`, then continue with the returned `path`. This project keeps the whole video so the user can check the full context. The original video is never changed, and deleting or moving it later doesn't affect the project. On the same disk, the import takes almost no extra space. `--force` isn't accepted for videos.
2. These projects have no pointer or keyboard data, so don't adjust the cursor, click-based automatic zooms, or keystroke display. There's no background by default, so the video looks like the original. Editing, captions, chapters, overlays, redactions, and export work as usual. The video's sound is analyzed as speech, so transcription and removing pauses and slips work too.
3. Choose the clips: run `oilstudio context <project> --transcript-first --out <temp file>`; if `utterances` is empty, run `transcribe` first. Set in and out points on word boundaries, never mid-word or mid-sentence, and use `storyboard`, `frame`, and `audio` to check what comes just before and after each cut. If the user gave times, use them and only nudge each to the nearest word boundary.
4. Import once more for each clip and name it: `oilstudio import <video> --name "<what the clip is about>"`, in the same folder as step 1. Importing the same video again reuses its sound and transcript, so there's no need to run `transcribe` again and no extra cost.
5. Submit a plan with only `clip` to each clip project: take that project's context fingerprints and write `{"schemaVersion":1, "projectFingerprint":…, "contextFingerprint":…, "clip":{"sourceStartMs":in, "sourceEndMs":out, "reason":"…"}}`, validate it, then submit. Don't remove the parts before and after with two `cut` decisions. See [Proposal formats](references/proposal-formats.md#clip-range-clip). Projects imported from the command line apply agent changes directly: `autoApplied: true` means the clip is already cut and saved, even if the app isn't open, so there's no need to wait for the user to confirm.
6. Report each clip's project name, the sentences it starts and ends on, and its length. Tell the user that opening a project shows the finished clip, that nothing outside the clip is deleted, that dragging either end outward reveals what's around each cut so they can adjust it, and that ⌘Z undoes the change. The "(Full)" project holds the whole video. If the user wants videos, follow Export video.

## Remove idle time

Use for silent demonstrations or long waits between operations. For voice-overs, prefer Tighten pauses or Fine cut. Voice-over projects (`voiceOver` is true in context) can’t have idle time removed.

- For a project you just recorded, run `oilstudio idle <project> --submit` directly. It returns candidates and applied changes together, aligns delayed click reports to screen changes, and rebuilds automatic zooms using the edited timeline and changed areas.
- For other projects, run `oilstudio idle <project>`, report the count and possible saving, then add `--submit` with the same parameters after authorization.
- Increase `--keep <milliseconds>` to retain more time at each gap's edges; default 400. Increase `--threshold <milliseconds>` to remove only longer waits; default 1500.
- Report according to `autoApplied`. No candidates means no submission and no `proposalId`.

## Fine cut + captions in one pass (standard command flow)

When the user asks to both cut the video and prepare/proofread captions, run these 5 steps consecutively in the same pass—**do not stop after `plan submit` to wait for approval first**:

```sh
# 1. If the project has no captions yet (subtitles.count == 0), generate captions and transcript cache together (add --mic-only for microphone-only voice-overs)
oilstudio subtitles generate "<project>" --engine auto

# 2. Export editing context and pause-cleanup draft in one pass (fall back to oilstudio pauses --out-plan on older CLI versions)
oilstudio context "<project>" --out "$WORK/01-context.json" --out-plan "$WORK/02-plan.json"
python3 -B "<skill-dir>/scripts/dump_transcript.py" --context "$WORK/01-context.json" --out "$WORK/01-transcript.md" --audit-template "$WORK/03-filler-audit.json"

# 3. Put executable cuts and keep/review decisions that protect cut boundaries in 02-plan.json. Record the other audit entries in 03-filler-audit.json, then verify and submit.
python3 -B "<skill-dir>/scripts/verify_plan.py" --context "$WORK/01-context.json" --plan "$WORK/02-plan.json" --audit "$WORK/03-filler-audit.json" --coverage-out "$WORK/03-coverage.json"
oilstudio plan submit "$WORK/02-plan.json" --compact

# 4. Read post-cut visible captions and diagnostics using --plan (without waiting for app approval first)
oilstudio subtitles get "<project>" --plan "$WORK/02-plan.json" --out "$WORK/04-subtitles.json"

# 5. Clear diagnostics (typos, inconsistent casing, residual fillers/stutters, layout warnings) and submit directly (without --review)
oilstudio subtitles apply "<project>" "$WORK/05-subtitle-edits.json" --plan "$WORK/02-plan.json"
```

For chapters on videos longer than 3 minutes (180000 ms) without existing chapters, reference retained `fromCue` IDs and run `oilstudio chapters apply "<project>" "$WORK/06-chapters.json" --plan "$WORK/02-plan.json"`. Check `warnings` / `chapterWidthWarnings` and follow the `autoApplied` rules under “Add chapters.” The proposal queues behind the cut and caption proposals and applies automatically once the cut plan is confirmed.

## Fine cut

1. Run `oilstudio context <project> --transcript-first --out <temporary-file>` and read it.
   - If the user also wants captions and `subtitles.count` is 0, run `oilstudio subtitles generate <project> --engine auto` first (add `--mic-only` if system audio should be skipped), then fetch context and pause draft together via `oilstudio context <project> --out <new-file> --out-plan <cleanup.json>`.
   - Otherwise, if `utterances` is empty, run `oilstudio transcribe <project>` and fetch new context (optionally with `--out-plan`) to a fresh filename.
   - For long recordings, run `python3 -B <skill-dir>/scripts/dump_transcript.py --context <context.json> --out <transcript.md> --audit-template <filler-audit.json>` instead of writing throwaway parser scripts.
2. If you did not use `context --out-plan` (or need custom `--threshold` / `--keep`), run `oilstudio pauses <project> --out-plan <cleanup.json>` and read `planPath`. This writes a draft without applying it. Keep its fingerprints and `decisions`; append semantic cuts to the same plan.
   - The draft already protects word edges. Do not add another 50 ms to each cut's start and subtract 50 ms from its end. Set additional breathing room once with `pauses --keep <milliseconds>`; otherwise keep the default.
   - Handle cleanup failures instead of silently skipping them. With no pauses, continue with empty decisions.
   - Draft and context fingerprints must match; otherwise reread both.
3. Read [Editing judgment](references/editing-judgment.md), then read all utterances before choosing retakes, slips, abandoned speech, or independently removable fillers. Use source time; original audio still contains proposed pauses.
   - Follow the requested Conservative, Standard, or Compact style; default Standard.
   - Review every `fillerCandidates` entry in full context. Record `cut`, `keep`, or `review` with a specific reason. A candidate fully covered by a passage cut needs no duplicate cut.
   - `utterances[].audio` provides confidence, pace, loudness, internal pauses, and unrecognized speech. `screen` provides OCR over time. These are evidence, never automatic reasons to delete.
   - Listen with `oilstudio audio <project> --source-ms <start>,<end> --out <wav>`; maximum 60 seconds.
   - Inspect with `oilstudio frame <project> --source-ms <milliseconds> --zoom none --text --out <png>`. For a range, use `oilstudio storyboard <project> --utterances <first>-<last> --out <png>` or `--source-ms <start>,<end>`; maximum 40 seconds. `--every 1000` controls sampling; `--no-frames` shows only audio and text.
4. Follow [Proposal formats](references/proposal-formats.md). Put executable `cut` decisions and requested changes such as `zooms` in `plan.json`. Keep `keep` / `review` decisions that protect adjacent cut boundaries in the plan. Record the remaining retained or review items in `filler-audit.json`. Run `scripts/verify_plan.py` to check coverage, cut expansions, and validation issues, then report passage-covered, individually cut, retained, and review candidates. Selecting only a few long hesitations or reporting silence counts is not a complete fine cut. Do not double-count overlaps or submit an empty executable plan.
5. Fix all `rejected` results and validate again; leave `uncheckedByDefault` for review, and inspect each item's `matchedActivity` to see the exact event kind (`click`, `mouseUp`, `key`, `screenChange`) and source time that triggered protection.
   - `cutAdjustments` reports verified word-boundary alignment and strict silence cleanup. Preview, submission, and caption projection use the same ranges. `boundaryReviews` identifies content outside a cut that could not be verified for removal; it stays in the video and is noted on the decision. Check those specific joins rather than treating successful application as proof that every fragment is gone.
   - With audio-understanding capability, optionally run `oilstudio plan preview <plan> --index <zero-based-result-index> --out <wav>`. `joinOutputMs` locates the join; `ranges` lists retained original audio. Speed changes, repeats, reordering, complete removal, or no microphone are unsupported; skip preview when audio understanding is unavailable.
6. Run `oilstudio plan submit <plan> --compact` once and keep `proposalId`. Never edit package files.
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

1. Run `oilstudio subtitles generate <project> --engine auto`. Add `--locale en-US` or `zh-CN` to override the speech language, and `--mic-only` to skip system audio on microphone-only voice-overs.
2. Don't open the project first or open it for the user. Only older app versions return `APP_REQUIRED`; in that case run `open -a "Oil Studio" <project>`, wait until `status.openProjects` lists it, then retry. Stop and explain the error after two failed generation attempts; never read internal project cache files directly to bypass the CLI.
3. Auto mode prefers cloud recognition when the selected region has a configured API key, then verified installed Whisper, then an available installed system model. If auto mode selects the system model, it stops before recognition when more than five minutes of audio still need transcription. It reuses valid cached transcripts and excludes picture-only recordings from the total. Pass `--engine system` or `--allow-fallback` only when system recognition is intentionally wanted. If no model is available, explain how to configure a cloud API key or install a local model in Settings. Do not request secrets or download models silently. Cloud recognition uploads the recording’s audio to the selected region. For an explicit local request, use `--engine whisper` or `--engine system`. Cloud is preferred when both are available.
4. Do not repeatedly retry a failed cloud request or silently switch engines. Follow the error. Use `--region beijing|singapore` for a one-command override without changing app preferences.
5. Only final `ok: true` confirms completion. `generated: true` means captions were saved; `false` means existing captions were retained. Report cloud/local recognition from the returned `engine`; `auto` does not mean local. Read captions back before continuing. Use `--force` only when recognition again is explicitly requested; preserve manually edited cues.
6. When the user asked to generate captions and did not decline chapters, run `oilstudio chapters get <project>`. If `outputDurationMs` is strictly greater than 180000 and `chapters` is empty, follow “Add chapters” to read the new captions, then create and apply chapters. Skip short videos and existing manual chapters. You provide the semantic split; the CLI does not generate chapters by itself.

If the user explicitly requires approval even for initial caption creation, explain that `subtitles generate` has no approval mode; prepare analysis with `transcribe` first. `transcribe` creates analysis data, not project captions.

## Adjust project settings

Aspect ratio, background, cursor, camera, watermark, caption style, and saved export options all change here. Read [Project settings and export](references/video-settings-and-export.md). Discover fields with `settings schema`, read current values and the fingerprint with `settings get <project>`, and submit only requested fields. `settings apply` follows the project’s automatic edit preference; `--review` requires review. Confirm application and read back settings before exporting.

## Proofread captions

1. Run `oilstudio subtitles get <project> --out <temporary-file>` (when fine-cutting in the same pass, pass `--plan <plan.json>` so `outputStartMs`, `displayText`, and `diagnostics` are projected onto the post-cut timeline). If no captions exist, follow “Generate captions,” then read them again to a new temporary filename.
2. Read [Caption proofreading](references/subtitle-proofreading.md). Inspect `diagnostics` (`inconsistentTerms`, `residualFillers`, `repeatedWords`, `glossaryMatches`, `lowConfidenceWords`, `layoutWarnings`, `overlappingCues`) alongside `glossary.replacements` and `glossary.hotwords`. Correct recognition errors, unify inconsistent term casing, clean residual written fillers/stutters on retained cues, remove overlapping system-audio bleed cues when needed, and fix layout warnings.
3. Write edits following Proposal formats. Copy `expectedText` exactly from returned `text`, never `displayText`.
4. Run `oilstudio subtitles apply <project> <edits>`. Edits apply directly by default (do not pass `--review` unless the user explicitly asks to review caption wording item by item; the generic toolbar brief about confirming proposals in the app applies to `plan submit`, not caption typo fixes). When a cut review is open in the app, `subtitles apply` without `--review` queues with `pendingReason: review_in_progress` and auto-applies once the user confirms the cut plan.
5. Inspect the receipt. For `autoApplied: true`, check `applied` and `skipped`; for false, wait for `proposal status`. `pendingReason: review_in_progress` means queued behind another review. On dismissal, inspect `reason`; rebuild from current captions only for a project change or validation failure, never automatically for `USER_DISMISSED`. After application, get captions again under a new filename, verify accepted edits, cleared `diagnostics`, and unchanged timings.
6. Report the actual applied count and two or three significant corrections, explain ⌘Z and skipped edits, and list glossary suggestions separately. Suggestions still require adding to the app glossary. Do not export until edits are applied and verified.

## Add chapters

1. Run `oilstudio chapters get <project>`. Keep existing chapters unless the user asks to add, edit, or reorganize them. When the user explicitly asks to add or update chapters, do not skip videos at or below 180000 ms; apply the requested changes directly.
2. Run `oilstudio subtitles get <project> --out <temporary-file>` and read all captions. If none exist, follow “Generate captions” first.
3. Read the Chapters section in [Chapters and translation](references/chapters-and-translation.md) and choose boundaries and titles. Position does not belong in this file; when the user requests top or bottom, use `settings apply` separately for `subtitles.chapterProgressPosition`.
4. Write the chapter file and run `oilstudio chapters apply <project> <chapters>`. Chapters apply immediately and enable the progress bar without user confirmation or a chapter-review wait.
5. When `autoApplied` is true, you can shorten overflowing titles and resubmit immediately. Then read back with `chapters get`, report the actual count, and explain undo and manual editing or deletion in the app. While the proposal is queued, follow `pendingReason` and tell the user which titles overflow with suggested edits, or wait for the proposal to resolve before submitting a revision.
6. When a cut plan is part of the same pass, reference post-cut retained `fromCue` IDs or kept source times and run `oilstudio chapters apply <project> <chapters> --plan <plan>`, so it validates against the post-cut timeline, queues behind the cut and caption proposals, and applies automatically once confirmed.

## English subtitles

1. Run `oilstudio subtitles get <project> --out <temporary-file>`. If Chinese captions have not been proofread, ask whether to proofread first; translate the finalized source text. For already-English speech, proofread or export the original captions rather than inventing a second translation.
2. Read the Translation section in Chapters and translation. Translate each cue.
3. Write the translation file and run `oilstudio subtitles apply <project> <translation> --locale en`. Report using shared rules and Fine cut step 7.
4. For a file, run `oilstudio subtitles export <project> --locale en --out <path.srt>`.

## Export subtitles

Run `oilstudio subtitles export <project> --out <path.srt>`. Save beside the .oilstudio project package, using the same base name by default. Ask before adding `--overwrite` to replace an existing file.

## Export video

Read the export section of [Project settings and export](references/video-settings-and-export.md). Run `oilstudio export <project> --out <path.mp4>`. Unspecified options use the project’s saved export settings. Save beside the project package unless requested otherwise. MP4/GIF, Minimal quality, H.264/HEVC/AV1 codecs, and output time ranges are supported.

- Add `--subtitles burn` to burn in captions, and `--srt` for a separate SRT file.
- Ask before overwriting an existing file.
- Export may take several minutes. Report its path and duration when done.
- After submitting edits, confirm `autoApplied: true` or proposal state `applied` before exporting; otherwise the export contains the old edit.

## Finish

Use two or three sentences: what changed, what was submitted with its `proposalId` or exported path, and what the user still needs to do. Do not paste the full JSON.

For TTS or external caption narration, read [Caption narration](references/narration.md) and use `narration status / generate / import`. Generation and import save directly and are undoable in the app.

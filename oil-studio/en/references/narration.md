# Caption narration

When narration is requested, inspect `oilstudio narration status <project>` first. Configure credentials in the app's text-to-speech settings. Never pass API keys on the command line.

```sh
oilstudio narration generate "<project>"
oilstudio narration generate "<project>" --provider bailian --region beijing --model qwen-audio-3.1-tts-flash --voice longanhuan_v3.1 --speed 1.15
oilstudio narration generate "<project>" --cue cue-1 --cue cue-2
oilstudio narration import "<project>" /tmp/narration.json
```

Generation defaults to missing and outdated cues. `--outdated` selects only outdated cues; `--force` regenerates all cues; `--speed <0.5–2.0>` overrides the synthesis speed for this run (defaults to the saved TTS setting, initially `1.0`). Repeat `--cue` to select specific cues. Read status again afterward; shorten text or adjust caption and video timing for `overflow` cues.

When authoring or editing narration captions (`subtitles apply`), keep each `cue` to a single short spoken clause (roughly 10–18 Chinese characters or one concise English clause) rather than joining two clauses with a comma into one long compound caption.

External audio manifest:

```json
{"schemaVersion":1,"mode":"replaceMicrophone","volume":1,"items":[{"cueID":"cue-1","expectedText":"Exact current caption text","audioPath":"/absolute/path/audio.mp3"}]}
```

`expectedText` must match the current caption. Imported audio is normalized and uses the same scheduling rules as generated audio. Changes to an open project are undoable in one step; offline projects are saved directly. When narration is enabled, caption and SRT timing follows valid narration. Edited captions never play outdated narration.

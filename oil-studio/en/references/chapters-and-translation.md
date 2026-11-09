# Chapters and translation

Return to [SKILL.md](../SKILL.en.md).

## Chapters

Read all captions and divide the video into broad phases: introduction/problem, setup, operations, results, summary. When dividing automatically, aim for 3–4 chapters in a three-to-five-minute video and 4–6 in longer videos; main sections are typically around a minute or more, while a natural 20–60 second intro or brief wrap-up can stand as its own chapter. Oil Studio does not merge chapters based on a fixed second threshold, and when the user explicitly asks to add or split a chapter, follow their request directly. Start the first chapter at the beginning.

For the first chapter, `fromCue` referencing the first visible caption snaps to output 0:00, even if speech starts later or the start of that caption has been cut. An explicit `sourceStartMs` must still correspond to the beginning of the current output. Adjacent chapter boundaries must be at least 1 ms apart in output time.

Use short descriptive titles: 2–8 Chinese characters or a brief English phrase (use shorter 2–4 character titles for narrower segments). No numbering or punctuation. Long titles truncate on the progress bar. Start at the first cue of the new topic using its `id` as `fromCue` or its `sourceStartMs`.

`chapters get` returns chapters, `outputDurationMs`, `enabled`, and `position`. Only proactive chapter creation during caption generation is limited to videos strictly longer than 180000 ms with no existing chapters; when the user explicitly requests adding or editing chapters, apply them regardless of video duration. When the target project is open in the foreground and no review is active, `chapters apply` validates and automatically replaces the whole set and enables the progress bar. Always inspect `autoApplied` and `pendingReason` in the JSON response: the proposal may be queued behind an active review or when the project is not open in the foreground. Applied chapters can be undone, edited, or deleted in the app.

Position is a separate appearance setting. Use `settings get/apply` with `subtitles.chapterProgressPosition` (`bottom` or `top`); do not add it to the chapter file.

```json
{
  "schemaVersion": 1,
  "chapters": [
    {"fromCue": "7DA2608E-572F-49E5-A91A-BB05812FFF97", "title": "Introduction"},
    {"fromCue": "0F4CD005-949D-4F90-8B26-35BACBD1B1F2", "title": "Setup"}
  ]
}
```

## Translation

Translate finalized Chinese captions into faithful, natural English, one cue at a time. For already-English speech, use the original captions instead of a duplicate translation.

- Translate only `text`; preserve IDs, count, and order exactly. Never merge or split cues.
- Preserve first person, factual scope, and strength. Do not add marketing language or expand the meaning.
- Keep product names, commands, filenames, and versions, such as `Claude Code` and `tasks.ts`.
- Omit nonsemantic Chinese filler sounds in translation.
- Keep sentences concise and add no manual line breaks. Oil Studio wraps English by words, with a default target of 42 characters.

```json
{
  "schemaVersion": 1,
  "edits": [
    {"id": "7DA2608E-572F-49E5-A91A-BB05812FFF97", "text": "Hi everyone, today I'm sharing a skill I recently open-sourced."}
  ]
}
```

Submit with `subtitles apply --locale en`. Every cue must appear exactly once; missing or additional cues are rejected.

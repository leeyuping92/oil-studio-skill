# Caption proofreading

Return to [SKILL.md](../SKILL.en.md). Match what the speaker intended to say: correct recognition errors in names, commands, and filenames, unify term casing across the whole recording, remove residual written hesitation sounds or stutters that remain on retained audio, and keep lines within 20 visual characters with balanced 2-line wraps. Do not rewrite sentences or change tone.

1. Read `diagnostics`, `glossary.replacements`, `glossary.hotwords`, and every visible cue (`outputStartMs` non-null) from `subtitles get`:
   - `diagnostics.inconsistentTerms`: unify every occurrence of a term (e.g. `Skill` vs `skill`) to the canonical spelling/casing across all cues, not just the first hit.
   - `diagnostics.residualFillers`: remove standalone written hesitation sounds (`呃`, `嗯`, `唉`, `诶`, standalone `额`, leading `啊`) that remained in the retained timeline because of coarticulation or overlapping screen activity.
   - `diagnostics.repeatedWords`: collapse accidental stutters (`然后然后`, `比较比较`, `the the`) to a single word.
   - `diagnostics.glossaryMatches` and `diagnostics.lowConfidenceWords`: inspect in context for homophone or ASR errors.
   - `diagnostics.layoutWarnings`: fix `over_width` (> 20 visual characters) or `orphan_second_line` (< 4 visual characters on line 2). **Keep any cue with total visual width ≤ 20 on a single line (never insert `\n` into a short cue)**; only use `\n` at a natural clause boundary when total width exceeds 20 visual characters.
2. Flag awkward or sound-alike errors, inconsistent spellings, names, code, commands, versions, filenames, and paths across the full transcript.
3. Seek evidence, strongest first:
   - `subtitles get` → `script`: the teleprompter script often spells names correctly, but speakers depart from it. Use it for vocabulary, never to replace speech with the script.
   - The same term correctly recognized elsewhere in the recording.
   - On-screen text: `oilstudio frame <project> --source-ms <cue-start-ms> --out <png> --text`.
   - Reliable topic knowledge, such as common programming product names.
4. Change only supported recognition errors and clear fillers/stutters. Retain uncertain text and mention it in the report. Evidence does not enter the edits file; each edit contains only `id`, `expectedText`, and `text`.

### Example: `subtitles get` diagnostics → `subtitles apply` edits

`subtitles get` output (excerpt):

```json
{
  "diagnostics": {
    "inconsistentTerms": [{"term": "skill", "suggested": "Skill", "variants": [{"text": "skill", "cueIds": ["c02"]}]}],
    "residualFillers": [{"id": "c02", "fillers": ["呃"]}],
    "repeatedWords": [{"id": "c02", "repeated": ["然后然后"]}],
    "glossaryMatches": [{"id": "c01", "wrong": "Clock", "correct": "Claude"}],
    "layoutWarnings": []
  },
  "cues": [
    {"id": "c01", "outputStartMs": 800, "text": "使用 Clock，写代码。", "displayText": "使用 Clock 写代码"},
    {"id": "c02", "outputStartMs": 2100, "text": "这个呃 skill 然后然后继续。", "displayText": "这个呃 skill 然后然后继续"}
  ]
}
```

Corresponding edits file (`expectedText` copied verbatim from `cues[].text`, never `displayText`):

```json
{
  "schemaVersion": 1,
  "edits": [
    {"id": "c01", "expectedText": "使用 Clock，写代码。", "text": "使用 Claude，写代码。"},
    {"id": "c02", "expectedText": "这个呃 skill 然后然后继续。", "text": "这个 Skill 然后继续。"}
  ]
}
```

Use on-screen text only when it denotes the same thing as the spoken word. Unrelated window/sidebar names are not replacements. Match spelling and capitalization to the relevant text, such as `Claude Code` or `tasks.ts`.

Chinese display cleanup handles punctuation and CJK spacing; do not submit cosmetic-only changes. English captions retain natural punctuation, spaces, contractions, and word boundaries. Preserve numbers, decimals, versions, and ratios such as `1:20:100`. Do not translate already-English speech when proofreading.

Add recurring recognition mistakes to the optional `glossary` (`wrong` → `correct`). Avoid one-off entries. Copy `expectedText` from raw `text`, never the display-only field.

After applying, get captions again and verify every accepted change, cleared `diagnostics`, unchanged timings, and skipped items. Scan all known error variants. Glossary suggestions still need adding through the app’s learning prompt. Remove isolated spoken fillers through a cut plan first; when a filler or stutter remains in retained audio due to coarticulation or screen activity, clean its written token from the caption text.

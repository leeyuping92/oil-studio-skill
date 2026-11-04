# Zoom judgment

Return to [SKILL.en.md](../SKILL.en.md). Keep the subject readable without distracting movement. Zoom toward what is being explained; stay wide for overviews and rapid switching.

Read all `utterances`, then `activity` for clicks/typing/scrolling, then existing `zooms` and their `origin`.

| Situation | Treatment |
| --- | --- |
| Small controls, settings, forms, menus | Click-following `mode: auto`, 1.4–1.8×. |
| Small text, errors, code, numbers | Fixed `mode: manual`, center `target` on the text, 1.6–2.2×; locate it with `frame --text`. |
| Speech and cursor refer to different regions | Target the subject of the explanation, not the mouse. |
| Explaining one region for more than two seconds | Hold the zoom; do not pull out mid-explanation. |

- Stay wide for overviews, layout introductions, and rapid changes between regions.
- Avoid zooms during continuous scrolling or window dragging.
- Merge zooms less than one second apart using a target covering both regions and the lower magnification.
- If a zoom crops the subject or control, lower its level or change `target`.
- Stay at or below 2.5× unless the user requests extremely small details.
- Start about 0.3–0.5 seconds before the subject is mentioned; pull out after the explanation.
- Keep zooms at least 1.5 seconds long. Default to `smooth`; use `instant` only for deliberate emphasis.

`origin: user` means the user adjusted it: do not change it without a request. For a clear problem, propose the change for unchecked review. `origin: recorded` zooms may be revised, merged, or removed. Ignore wholly invisible zooms; zooms spanning deleted sections are normal, so judge their retained output.

Write one `reason` per change explaining what becomes clearer or why removal helps. Inspect the full frame with `frame --zoom none --text` before choosing a new target. Viewing without `--zoom none` before approval shows the current zoom, not the proposed one.

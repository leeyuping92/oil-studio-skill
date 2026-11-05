# Zoom judgment

Return to [SKILL.en.md](../SKILL.en.md). Keep the subject readable without distracting movement. Zoom toward what is being explained; stay wide for overviews and rapid switching.

Read all `utterances`, then `activity` for clicks/typing/scrolling, then existing `zooms` and their `origin`.

| Situation | Treatment |
| --- | --- |
| Small controls, settings, forms, menus | Click-following `mode: auto`, 1.22–1.30× for standard windows (1.15–1.20× for compact windows). |
| Small text, errors, code, numbers | Fixed `mode: manual`, center `target` on the text, 1.30–1.50×; locate it with `frame --text`. |
| Speech and cursor refer to different regions | Target the subject of the explanation, not the mouse. |
| Explaining one region for 1.5–3.2 seconds | Hold the zoom, then pull back to 1.0× full view for breathing room. |

- **Never keep the entire video zoomed in from start to finish**: after a 1.5–3.2 second zoom hold, return to 1.0× full overview for at least 1.8 seconds so viewers see the overall interface response, and keep the opening and closing in full overview.
- Stay wide for overviews, layout introductions, centered modals, and transitions across regions.
- Avoid zooms during continuous scrolling or window dragging.
- Merge adjacent clicks only when they are in the same local region, less than 0.9 seconds apart, and at most 3.2 seconds combined; separate cross-region actions with a 1.0× overview gap.
- If a zoom crops the subject or control, lower its level (prefer ~1.25×) or change `target`.
- Stay at or below 1.35× for standard demos unless the user requests extremely small details.
- Start about 0.3–0.5 seconds before the subject is mentioned; pull out after the explanation.
- Keep zooms at least 1.5 seconds long. Default to `smooth`; use `instant` only for deliberate emphasis.

`origin: user` means the user adjusted it: do not change it without a request. For a clear problem, propose the change for unchecked review. `origin: recorded` zooms may be revised, merged, or removed. Ignore wholly invisible zooms; zooms spanning deleted sections are normal, so judge their retained output.

Write one `reason` per change explaining what becomes clearer or why removal helps. Inspect the full frame with `frame --zoom none --text` before choosing a new target. Viewing without `--zoom none` before approval shows the current zoom, not the proposed one.

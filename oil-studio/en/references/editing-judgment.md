# Editing judgment

Use during Fine cut to decide what to remove and retain. Return to [SKILL.md](../SKILL.en.md).

## Goal and order

Leave one clear explanation without repetition or stumbling, while preserving every fact and required on-screen operation. Gather evidence or explicitly mark uncertainty; a conservative label does not replace reviewing each candidate. You make the semantic decision; the CLI supplies evidence and executes it.

Read all `utterances` and `screen` entries before selecting candidates. A later sentence can determine whether an earlier one was a retake.

## Audio and visual evidence

- `audio.unrecognized` contains speech without recognized words, often a filler or an unclear false start. Low confidence can mean inaccurate text, not bad speech. Slow, quiet speech may be self-directed thinking.
- Check product names against on-screen text before calling an awkward transcript a slip.
- For uncertain candidates, use `oilstudio storyboard <project> --utterances <first>-<last> --out <png>`. Waveforms without words may contain unrecognized fillers; similar takes with a broken first attempt may indicate a retake. The frames show whether an operation was repeated. Inspect only candidate neighborhoods, not the entire video frame by frame.
- If you can understand audio, export the relevant original range with `oilstudio audio` and listen. Never invent an assessment of sound.

## Evaluate each retake candidate

1. Are both passages explaining the same thing, rather than merely sharing words?
2. Does the later take fully cover the earlier take's information?
3. Does the proposed cut contain any unique condition, number, warning, result, or operation?
4. Does it overlap clicking, typing, state changes, results, or an instruction to look at something? Check `activity` and frames when needed.
5. Read the new join: does its subject, transition, and meaning remain complete?

If any answer is uncertain, retain the passage or mark it `review`.

## Cut categories

| Category | Decision |
| --- | --- |
| `abandoned_take` | The later take clearly repeats the same point and covers all earlier information. Remove the earlier take and identify the retained utterances in `keptRange`. |
| `false_start` | An unfinished sentence is abandoned and immediately restarted differently. |
| `slip` | An immediate self-correction, such as “three—no, four.” Remove the wrong part and correction words; keep the corrected fact. |
| `filler` | Independently removable nonsemantic hesitations such as 呃、嗯、um、uh, or unrelated chatter and process talk. Follow the candidate review below. |

Pauses, similar wording, shared keywords, or sentence length do not prove a retake. Handle silence with pause cleanup.

## Chinese and English fillers: review every candidate

Standard fine cutting includes independently removable hesitations without a separate filler request. Review all `fillerCandidates` in retained footage, not just long sounds or the first few entries:

1. **Read complete context and decide meaning.** Prefer removing nonsemantic 呃、嗯、um、uh. A hesitation may be removable inside a sentence such as “这个呃工具.” Chinese 啊 can be hesitation, response, emphasis, or tone; assess it individually. 那个、就是、然后 and like, so, you know, I mean, actually, basically may convey reference, consequence, comparison, clarification, or temporal sequence. Do not bulk-delete by word list.
2. **Check timed words and the join.** Use `suggestedCuts`, neighboring word timestamps, and waveforms. Remove only the nonsemantic sound and necessary breathing space; preserve adjacent words, consonants, contractions, and meaningful syllables. Silence on both sides is not required. Preserve or inspect genuinely inseparable speech. Neither sentence position nor a fixed duration threshold decides the outcome; do not send every short candidate to review automatically.
3. **Protect operations and unrecognized speech.** Follow the operation rules below rather than losing a meaningful click or state to remove one sound. Missing ASR words do not establish silence. Inspect uncertain neighborhoods, not every frame of the video.
4. **Record a result for each candidate.** Use `cut`, `keep`, or `review` with a specific reason. A fully covering passage cut accounts for the candidate without a duplicate cut. For review, name the missing evidence or endangered neighboring word, not merely “mid-sentence,” “short,” or “detector requires review.” Under Conservative style, explicitly account for fillers retained by preference.

`group: certain` does not guarantee a natural join. `possiblyMeaningful` and `requiresReview` require your judgment, not permanent retention. A meaningless, clearly bounded sound is not exempt from review because of a detector flag. Without audio understanding, still examine word timestamps, waveforms, and context individually; flag only actually unsupported joins and state that they were not auditioned.

Match only whole English um, uh, er, ah, not letters within summer or other. Match case-insensitively, keep contractions intact, and do not join a phrase across a sentence boundary or pause. On older apps without `fillerCandidates`, inspect existing timed words without retranscribing.

See [Proposal formats](proposal-formats.md) for coverage checking. Coverage proves accounting, not sound quality or application. After application, reread retained footage and check accepted source ranges for unexpected residuals. Report retained/review entries rather than hiding them behind a completion claim.

## Always retain

- Unique numbers, versions, names, steps, conditions, warnings, conclusions, and results.
- Both similar takes if the later one does not fully cover the earlier one; alternatively mark the earlier one `review`.
- A required demonstration unless the same operation is fully repeated later.
- The final retained opening, greeting, introduction, and closing summary. Earlier retakes are not protected merely because they contain a greeting or summary. When asked to keep the last take, prefer the last complete version while checking unique facts.

## Operations and transitions

When a cut overlaps `activity`, assume the operation matters. Oil Studio leaves such cuts unchecked. Only after inspecting frames and confirming a repeated or irrelevant operation may you set `screenAction: "redundant"` and explain what you saw in `visualAssessment`. Never supply visual evidence you did not inspect.

Reread joins around Chinese transition words such as 但是、不过、然而、可是、也就是说、所以、因此、另外、同时、虽然, and English “but,” “however,” “although,” “so,” “therefore,” “in other words,” “also,” or “meanwhile.” Verify that the logic survives; otherwise mark `review`.

## Style and proposal

| Style | Scope |
| --- | --- |
| Conservative | Only fully repeated earlier takes and abandoned sentences, all with high confidence. |
| Standard | Also slips, independently removable fillers and clearly unrelated speech. |
| Compact | Also redundant emphasis and detours; still preserve every unique fact. |

For each cut, write exact `removedText`, retained covering `keptText` if any, and a one-sentence `reason`. Prefer utterance IDs; use source-time word boundaries for partial sentences. Explain cuts longer than 30 seconds; Oil Studio leaves them unchecked by default.

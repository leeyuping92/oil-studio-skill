#!/usr/bin/env python3
"""Run filler coverage check and oilstudio plan validate together, printing only actionable items."""
import sys
sys.dont_write_bytecode = True
import argparse
import json
import math
from pathlib import Path
import subprocess
import check_filler_coverage as cov


def run_plan_validate(binary, plan_path, project_path=None):
    base_cmd = [binary, "plan", "validate", str(plan_path)]
    if project_path:
        base_cmd.extend(["--project", str(project_path)])

    def invoke(cmd):
        proc = subprocess.run(cmd, capture_output=True, text=True)
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        try:
            if not lines:
                raise ValueError("oilstudio returned no JSON output")
            data = cov.require_type(json.loads(lines[-1]), dict, "plan validate response")
        except ValueError as error:
            if proc.returncode:
                raise subprocess.CalledProcessError(proc.returncode, cmd, stderr=proc.stderr.strip() or str(error)) from error
            raise
        return proc.returncode, data

    code, data = invoke(base_cmd + ["--compact"])
    error = data.get("error")
    if (
        not data.get("ok")
        and isinstance(error, dict)
        and error.get("code") == "USAGE"
        and isinstance(error.get("message"), str)
        and "--compact" in error["message"]
    ):
        code, data = invoke(base_cmd)
    return code, data


def summarize_validation(data, adjustments):
    ok = cov.require_type(data.get("ok"), bool, "ok")
    results = cov.object_rows(data.get("results", []), "results")
    summary = data.get("summary")
    if summary is None:
        summary = {
            "total": len(results),
            "accepted": sum(1 for r in results if r.get("status") == "accepted"),
            "uncheckedByDefault": sum(1 for r in results if r.get("status") == "uncheckedByDefault"),
            "rejected": sum(1 for r in results if r.get("status") == "rejected"),
            "notes": sum(1 for r in results if r.get("kind") == "note"),
        }
    else:
        cov.require_type(summary, dict, "summary")
        for key in ("total", "accepted", "uncheckedByDefault", "rejected", "notes"):
            if key in summary and type(summary[key]) is not int:
                raise ValueError(f"summary.{key} must be a JSON integer")
    for index, row in enumerate(results):
        for key in ("status", "kind", "reason"):
            if row.get(key) is not None:
                cov.require_type(row[key], str, f"results[{index}].{key}")
        if row.get("matchedActivity") is not None:
            cov.object_rows(row["matchedActivity"], f"results[{index}].matchedActivity")
    warning = data.get("cleanupWarning")
    if warning is not None:
        cov.require_type(warning, str, "cleanupWarning")
    error = data.get("error")
    if error is not None:
        cov.require_type(error, dict, "error")
    rejected = [r for r in results if r.get("status") == "rejected"]
    unchecked = [r for r in results if r.get("status") == "uncheckedByDefault"]
    annotated = [r for r in results if r.get("status") == "accepted" and (r.get("reason") or "").strip()]
    out = {
        "ok": ok and warning is None,
        "summary": summary,
        "rejected": rejected,
        "uncheckedByDefault": unchecked,
        "annotated": annotated,
        "cutAdjustmentCount": len(adjustments),
        "boundaryReviews": cov.object_rows(data.get("boundaryReviews", []), "boundaryReviews"),
    }
    if warning is not None:
        out["cleanupWarning"] = warning
    if not ok and error is not None:
        out["error"] = error
    return out


def adjusted_ranges(adjustments, plan, positions, utterances):
    def bounds(value, field, allow_zero_width=False):
        if (not isinstance(value, list) or len(value) != 2
                or any(type(n) not in (int, float) or (type(n) is float and not math.isfinite(n)) for n in value)
                or not (0 <= value[0] <= value[1] if allow_zero_width else 0 <= value[0] < value[1])):
            kind = "non-decreasing" if allow_zero_width else "increasing"
            raise ValueError(f"{field} must contain two {kind} source milliseconds")
        return tuple(value)

    clip_bounds = None
    decisions = plan.get("decisions", [])
    for index, row in enumerate(adjustments):
        field = f"cutAdjustments[{index}]"
        if row.get("kind") == "clip":
            # Clip bounds describe what stays in the timeline. Only the removed edges can consume audit ranges.
            if clip_bounds is None:
                clip = cov.require_type(plan.get("clip"), dict, "plan.clip")
                original = bounds([clip.get("sourceStartMs"), clip.get("sourceEndMs")], "plan.clip")
                # The CLI reports source times rounded to whole milliseconds.
                clip_bounds = tuple(math.floor(value + 0.5) if type(value) is float else value for value in original)
            start, end = bounds([row.get("sourceStartMs"), row.get("sourceEndMs")], field)
            if not clip_bounds[0] <= start < end <= clip_bounds[1]:
                raise ValueError(f"{field} must shrink the retained clip")
            if clip_bounds[0] < start:
                yield clip_bounds[0], start
            if end < clip_bounds[1]:
                yield end, clip_bounds[1]
            clip_bounds = start, end
        else:
            owner = row.get("index")
            if type(owner) is not int or owner < 0:
                raise ValueError(f"{field}.index must be a nonnegative integer")
            if owner >= len(decisions):
                # An orphan fragment can be added as a new decision; sub-millisecond fragments may
                # round to start == end on the wire.
                start, end = bounds(row.get("sourceMs"), f"{field}.sourceMs", allow_zero_width=True)
                yield start, end
                continue
            start, end = bounds(row.get("sourceMs"), f"{field}.sourceMs")
            old_start, old_end = cov.resolve_range(decisions[owner], positions, utterances, f"decisions[{owner}]")
            # CLI times are rounded to whole milliseconds. Compare half-open ranges at that precision.
            if start < old_start:
                yield start, min(end, old_start)
            if old_end < end:
                yield max(start, old_end), end


SHORT_REMAINDER_THRESHOLD_MS = 300
SOURCE_DRIFT_TOLERANCE_MS = 1e-6
AGENT_SNAP_TOLERANCE_MS = 0.5
MINIMUM_REMOVED_SPAN_MS = 1.0


def subtract_ranges(base_ranges, cut_ranges):
    cuts = cov.merged(cut_ranges)
    if not cuts:
        return list(base_ranges)
    result = []
    for start, end in base_ranges:
        cursor = start
        for cut_start, cut_end in cuts:
            if cut_end <= cursor:
                continue
            if cut_start >= end:
                break
            if cut_start > cursor:
                result.append((cursor, min(cut_start, end)))
            cursor = max(cursor, cut_end)
            if cursor >= end:
                break
        if cursor < end:
            result.append((cursor, end))
    return result


def has_positive_overlap(protected_ranges, start, end):
    if start == end:
        return any(p_start < start < p_end for p_start, p_end in protected_ranges)
    return any(p_start < end and start < p_end for p_start, p_end in protected_ranges)


def annotate_remainder(start, end, utterances, explicit_duration=None):
    duration = explicit_duration if explicit_duration is not None else (end - start)
    overlapping_utterances = []
    overlapping_words = []
    has_timed_words = False
    for u in utterances:
        u_start, u_end = u.get("sourceStartMs"), u.get("sourceEndMs")
        if type(u_start) in (int, float) and type(u_end) in (int, float):
            u_overlaps = (u_start <= start <= u_end) if start == end else (u_start < end and start < u_end)
            if u_overlaps:
                overlapping_utterances.append(u["id"])
                for w in u.get("words") or []:
                    if not isinstance(w, dict):
                        continue
                    w_start, w_end = w.get("sourceStartMs"), w.get("sourceEndMs")
                    if type(w_start) in (int, float) and type(w_end) in (int, float):
                        has_timed_words = True
                        w_overlaps = (w_start <= start <= w_end) if start == end else (w_start < end and start < w_end)
                        if w_overlaps:
                            overlapping_words.append(w.get("text", ""))
    item = {
        "sourceMs": [start, end],
        "durationMs": int(duration) if duration == int(duration) else round(duration, 3),
        "overlappingUtterances": overlapping_utterances,
    }
    if has_timed_words:
        item["overlappingWords"] = overlapping_words
    return item


def collect_audit_protected(audit, coverage_report, positions, utterances):
    protected = []
    if not audit:
        return protected
    candidates = {row["id"]: tuple(row["sourceMs"]) for row in (coverage_report or {}).get("candidates", [])}
    for index, entry in enumerate(cov.object_rows(audit.get("items", []), "audit.items")):
        uid = entry.get("id")
        if uid is not None and uid in candidates:
            protected.append(candidates[uid])
        elif uid is None:
            protected.append(cov.resolve_range(entry, positions, utterances, f"audit.items[{index}]"))
    return cov.merged(protected)


def remainders_from_cli(raw_fragments, context, audit=None, coverage_report=None):
    rows = cov.object_rows(raw_fragments, "remainingFragments")
    utterances = cov.object_rows(context.get("utterances", []), "utterances")
    positions = {cov.require_type(u.get("id"), str, f"utterances[{i}].id"): i for i, u in enumerate(utterances)}
    audit_protected = collect_audit_protected(audit, coverage_report, positions, utterances)
    flagged = []
    for index, row in enumerate(rows):
        bounds = row.get("sourceMs")
        if (not isinstance(bounds, list) or len(bounds) != 2
                or any(type(n) not in (int, float) or (type(n) is float and not math.isfinite(n)) for n in bounds)
                or not 0 <= bounds[0] <= bounds[1]):
            raise ValueError(f"remainingFragments[{index}].sourceMs must contain two non-decreasing source milliseconds")
        start, end = bounds[0], bounds[1]
        explicit_duration = row.get("durationMs")
        if explicit_duration is not None:
            if (type(explicit_duration) not in (int, float)
                    or (type(explicit_duration) is float and not math.isfinite(explicit_duration))
                    or explicit_duration < 0):
                raise ValueError(f"remainingFragments[{index}].durationMs must be a nonnegative number")
        if has_positive_overlap(audit_protected, start, end):
            continue
        item = annotate_remainder(start, end, utterances, explicit_duration=explicit_duration)
        if type(row.get("sessionIndex")) is int:
            item["sessionIndex"] = row["sessionIndex"]
        flagged.append(item)
    return flagged


def short_remainders(context, plan, adjustments=None, audit=None, coverage_report=None,
                     threshold_ms=SHORT_REMAINDER_THRESHOLD_MS):
    raw_slices = context.get("slices")
    if raw_slices is None:
        return []
    slice_rows = cov.object_rows(raw_slices, "slices")
    if not slice_rows:
        return []

    def slice_bounds(row, field):
        start, end = row.get("sourceStartMs"), row.get("sourceEndMs")
        if (type(start) not in (int, float) or type(end) not in (int, float)
                or (type(start) is float and not math.isfinite(start))
                or (type(end) is float and not math.isfinite(end))
                or not 0 <= start <= end):
            raise ValueError(f"{field} must contain two non-decreasing source milliseconds")
        return start, end

    def optional_int(value, field):
        if value is None:
            return None
        if type(value) is not int:
            raise ValueError(f"{field} must be a JSON integer")
        return value

    # Preserve timeline occurrence order and only coalesce adjacent contiguous slices belonging to
    # the same session and scene (matching CutFragmentCleanup's sourceContinuousSegmentGroups).
    # Allow start == end so legitimate sub-millisecond slices rounded by CLI export do not error.
    groups = []
    for i, row in enumerate(slice_rows):
        start, end = slice_bounds(row, f"slices[{i}].sourceStartMs/sourceEndMs")
        start_session = optional_int(row.get("sessionIndex"), f"slices[{i}].sessionIndex")
        end_session = optional_int(row.get("endSessionIndex"), f"slices[{i}].endSessionIndex")
        if end_session is None:
            end_session = start_session
        scene = optional_int(row.get("sceneIndex"), f"slices[{i}].sceneIndex")
        is_single_session = start_session is not None and start_session == end_session
        prev_is_single_session = bool(groups) and groups[-1][2] is not None and groups[-1][2] == groups[-1][3]
        same_track = (
            is_single_session
            and prev_is_single_session
            and groups[-1][3] == start_session
            and scene is not None
            and groups[-1][4] is not None
            and groups[-1][4] == scene
        )
        if same_track and abs(groups[-1][1] - start) <= SOURCE_DRIFT_TOLERANCE_MS:
            groups[-1] = (groups[-1][0], end, groups[-1][2], end_session, scene)
        else:
            groups.append((start, end, start_session, end_session, scene))

    utterances = cov.object_rows(context.get("utterances", []), "utterances")
    positions = {cov.require_type(u.get("id"), str, f"utterances[{i}].id"): i for i, u in enumerate(utterances)}

    def num_bounds(value, field):
        if (not isinstance(value, list) or len(value) != 2
                or any(type(n) not in (int, float) or (type(n) is float and not math.isfinite(n)) for n in value)
                or not 0 <= value[0] < value[1]):
            raise ValueError(f"{field} must contain two increasing source milliseconds")
        return tuple(value)

    cuts_by_index = {}
    protected = []
    decisions = cov.object_rows(plan.get("decisions", []), "decisions")
    for index, decision in enumerate(decisions):
        bounds = cov.resolve_range(decision, positions, utterances, f"decisions[{index}]")
        kind = decision.get("decision")
        confidence = decision.get("confidence")
        if kind == "cut" and confidence in ("high", "medium"):
            cuts_by_index[index] = bounds
        elif kind in ("keep", "review") or confidence == "low":
            # Align with PlanValidation.swift: keep, review, and low-confidence cuts act as protected notes.
            protected.append(bounds)

    clip_bounds = None
    if plan.get("clip") is not None:
        clip = cov.require_type(plan["clip"], dict, "plan.clip")
        clip_bounds = num_bounds([clip.get("sourceStartMs"), clip.get("sourceEndMs")], "plan.clip")

    for index, row in enumerate(adjustments or []):
        field = f"cutAdjustments[{index}]"
        if row.get("kind") == "clip":
            adjusted_clip = num_bounds([row.get("sourceStartMs"), row.get("sourceEndMs")], field)
            if clip_bounds is not None and not (clip_bounds[0] - AGENT_SNAP_TOLERANCE_MS <= adjusted_clip[0]
                                                and adjusted_clip[1] <= clip_bounds[1] + AGENT_SNAP_TOLERANCE_MS):
                raise ValueError(f"{field} must shrink the retained clip")
            clip_bounds = adjusted_clip
        else:
            owner = row.get("index")
            if type(owner) is not int or owner < 0:
                raise ValueError(f"{field}.index must be a nonnegative integer")
            if owner in cuts_by_index:
                start, end = num_bounds(row.get("sourceMs"), f"{field}.sourceMs")
                old_start, old_end = cuts_by_index[owner]
                if start > old_start + AGENT_SNAP_TOLERANCE_MS or end < old_end - AGENT_SNAP_TOLERANCE_MS:
                    raise ValueError(f"{field}.sourceMs must expand its owner decision range")
                cuts_by_index[owner] = (min(old_start, start), max(old_end, end))
            elif owner >= len(decisions):
                raw_bounds = row.get("sourceMs")
                if (not isinstance(raw_bounds, list) or len(raw_bounds) != 2
                        or any(type(n) not in (int, float) or (type(n) is float and not math.isfinite(n)) for n in raw_bounds)
                        or not 0 <= raw_bounds[0] <= raw_bounds[1]):
                    raise ValueError(f"{field}.sourceMs must contain two non-decreasing source milliseconds")
                if raw_bounds[0] < raw_bounds[1]:
                    cuts_by_index[owner] = (raw_bounds[0], raw_bounds[1])

    protected.extend(collect_audit_protected(audit, coverage_report, positions, utterances))
    merged_cuts = cov.merged(list(cuts_by_index.values()))
    merged_protected = cov.merged(protected)

    flagged = []
    for g_idx, (g_start, g_end, g_start_sess, g_end_sess, g_scene) in enumerate(groups):
        if g_end <= g_start:
            continue
        # A single slice spanning multiple recording sessions has an internal session boundary
        # not visible in whole-slice context export; leave cross-session splits to CLI remainingFragments.
        if g_start_sess is not None and g_end_sess is not None and g_start_sess != g_end_sess:
            continue
        eff_start, eff_end = g_start, g_end
        clip_trimmed_left = False
        clip_trimmed_right = False
        if clip_bounds is not None:
            c_start, c_end = clip_bounds
            if c_end <= g_start or c_start >= g_end:
                continue
            if c_start > g_start:
                eff_start = c_start
                clip_trimmed_left = True
            if c_end < g_end:
                eff_end = c_end
                clip_trimmed_right = True
        if eff_end <= eff_start:
            continue

        group_cuts = [
            (max(a, eff_start), min(b, eff_end))
            for a, b in merged_cuts
            if a < eff_end and b > eff_start
        ]
        remaining = subtract_ranges([(eff_start, eff_end)], group_cuts)
        for start, end in remaining:
            duration = end - start
            # Offline fallback only sees whole-millisecond rounded context slices; sub-millisecond
            # slivers (< 1 ms) are resolved authoritatively by CLI remainingFragments.
            if duration < MINIMUM_REMOVED_SPAN_MS or duration > threshold_ms + SOURCE_DRIFT_TOLERANCE_MS:
                continue
            # Only treat an existing inter-slice gap as a known same-session deleted gap when both
            # adjacent slices carry explicit matching sessionIndex and sceneIndex (preventing false
            # positives across multi-session boundaries in older context exports).
            prev_deleted = (
                abs(start - g_start) <= SOURCE_DRIFT_TOLERANCE_MS and g_idx > 0
                and g_start_sess is not None and groups[g_idx - 1][3] is not None
                and groups[g_idx - 1][3] == g_start_sess
                and g_scene is not None and groups[g_idx - 1][4] is not None
                and groups[g_idx - 1][4] == g_scene
                and g_start - groups[g_idx - 1][1] >= MINIMUM_REMOVED_SPAN_MS
            )
            next_deleted = (
                abs(end - g_end) <= SOURCE_DRIFT_TOLERANCE_MS and g_idx + 1 < len(groups)
                and g_end_sess is not None and groups[g_idx + 1][2] is not None
                and groups[g_idx + 1][2] == g_end_sess
                and g_scene is not None and groups[g_idx + 1][4] is not None
                and groups[g_idx + 1][4] == g_scene
                and groups[g_idx + 1][0] - g_end >= MINIMUM_REMOVED_SPAN_MS
            )
            has_preceding = (
                any(abs(c_end - start) <= SOURCE_DRIFT_TOLERANCE_MS for _, c_end in group_cuts)
                or (clip_trimmed_left and abs(start - eff_start) <= SOURCE_DRIFT_TOLERANCE_MS)
                or prev_deleted
            )
            has_following = (
                any(abs(c_start - end) <= SOURCE_DRIFT_TOLERANCE_MS for c_start, _ in group_cuts)
                or (clip_trimmed_right and abs(end - eff_end) <= SOURCE_DRIFT_TOLERANCE_MS)
                or next_deleted
            )
            if not (has_preceding and has_following):
                continue
            if has_positive_overlap(merged_protected, start, end):
                continue
            flagged.append(annotate_remainder(start, end, utterances))
    return flagged


def audit_protection_conflicts(adjustments, context, plan, audit, coverage_report):
    if not adjustments:
        return []
    utterances = context.get("utterances", [])
    positions = {row["id"]: i for i, row in enumerate(utterances)}
    raw_ranges = list(adjusted_ranges(adjustments, plan, positions, utterances))
    cuts = cov.merged([(a, b) for a, b in raw_ranges if a < b])
    point_cuts = [a for a, b in raw_ranges if a == b]
    if (not cuts and not point_cuts) or not audit:
        return []
    candidates = {row["id"]: row["sourceMs"] for row in coverage_report["candidates"]}
    conflicts = []
    for index, entry in enumerate(audit["items"]):
        uid = entry.get("id")
        start, end = candidates[uid] if uid is not None else cov.resolve_range(
            entry, positions, utterances, f"audit.items[{index}]")
        if any(a < end and start < b for a, b in cuts) or any(start < p < end for p in point_cuts):
            conflict = {"auditIndex": index, "decision": entry["decision"], "sourceMs": [start, end]}
            if uid is not None:
                conflict["id"] = uid
            conflicts.append(conflict)
    return conflicts


def verify(context, plan, audit=None):
    coverage_report = cov.check(context, plan, audit=audit)
    unresolved = [c for c in coverage_report["candidates"] if c["status"] == "unresolved"]
    silence_overlaps = [c for c in coverage_report["candidates"] if c.get("silenceOverlapIndices")]
    coverage_summary = {
        "ok": coverage_report["ok"],
        "candidateCount": coverage_report["candidateCount"],
        "counts": coverage_report["counts"],
        "unresolved": unresolved,
    }
    if silence_overlaps:
        coverage_summary["silenceOverlaps"] = silence_overlaps
    output = {
        "ok": coverage_report["ok"],
        "coverage": coverage_summary,
    }
    return output, coverage_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--audit", type=Path, help="Optional separate keep/review audit manifest")
    parser.add_argument("--coverage-out", type=Path, help="Write full coverage report to a new file")
    parser.add_argument("--project", type=Path, help="Optional project path forwarded to oilstudio plan validate")
    parser.add_argument("--oilstudio", default="oilstudio", help="oilstudio CLI executable (default: oilstudio)")
    parser.add_argument("--skip-validate", action="store_true", help="Only run filler coverage check")
    args = parser.parse_args()
    validation_exit = 0
    try:
        for path in (args.context, args.plan, args.audit, args.coverage_out):
            if path is not None:
                cov.outside_project(path)
        if args.coverage_out is not None and args.coverage_out.exists():
            raise FileExistsError(f"Output file already exists: {args.coverage_out}")
        context = json.loads(args.context.read_text(encoding="utf-8"))
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        audit = cov.require_type(json.loads(args.audit.read_text(encoding="utf-8")), dict, "audit") if args.audit else None
        # Validate local coverage inputs before paying for CLI plan validation.
        summary, full_coverage = verify(context, plan, audit=audit)
        if args.skip_validate:
            remainders = short_remainders(context, plan, audit=audit, coverage_report=full_coverage)
            if remainders:
                summary["shortRemainders"] = remainders
                summary["shortRemaindersHint"] = (
                    "Bridge or widen adjacent cuts to absorb short fragments, or mark intentional short "
                    "speech as keep/review in plan.json or audit.json."
                )
                summary["ok"] = False
        else:
            code, validation_data = run_plan_validate(args.oilstudio, args.plan, args.project)
            adjustments = cov.object_rows(validation_data.get("cutAdjustments", []), "cutAdjustments")
            val_summary = summarize_validation(validation_data, adjustments)
            validation_exit = code
            conflicts = audit_protection_conflicts(adjustments, context, plan, audit, full_coverage)
            if conflicts:
                val_summary["auditProtectionConflicts"] = conflicts
                val_summary["auditProtectionHint"] = "Move these audit items into plan.json as keep/review decisions."
            if "remainingFragments" in validation_data:
                remainders = remainders_from_cli(
                    validation_data["remainingFragments"], context, audit=audit, coverage_report=full_coverage
                )
            elif val_summary["ok"] and not validation_exit and not val_summary["rejected"]:
                remainders = short_remainders(
                    context, plan, adjustments=adjustments, audit=audit, coverage_report=full_coverage
                )
            else:
                remainders = []
            if remainders:
                val_summary["shortRemainders"] = remainders
                val_summary["shortRemaindersHint"] = (
                    "Bridge or widen adjacent cuts to absorb short fragments, or mark intentional short "
                    "speech as keep/review in plan.json or audit.json."
                )
            val_summary["ok"] = val_summary["ok"] and not validation_exit and not conflicts and not remainders
            summary["validation"] = val_summary
            summary["ok"] = bool(summary["coverage"]["ok"] and val_summary["ok"])
        if args.coverage_out:
            with args.coverage_out.open("x", encoding="utf-8") as stream:
                json.dump(full_coverage, stream, ensure_ascii=False, indent=2)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return validation_exit or (0 if summary["ok"] else 1)
    except subprocess.CalledProcessError as error:
        print(json.dumps({"ok": False, "error": error.stderr}, ensure_ascii=False), file=sys.stderr)
        return error.returncode
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return validation_exit or 2


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Check candidate coverage, not the semantic or acoustic quality of an edit."""
import sys
sys.dont_write_bytecode = True
import argparse
from collections import Counter
import json
from pathlib import Path


def require_type(value, expected, field):
    if not isinstance(value, expected):
        json_type = {dict: "object", list: "array", str: "string", bool: "boolean"}[expected]
        raise ValueError(f"{field} must be a JSON {json_type}")
    return value


def object_rows(value, field):
    rows = require_type(value, list, field)
    for index, row in enumerate(rows):
        require_type(row, dict, f"{field}[{index}]")
    return rows


def interval(value, field="sourceMs"):
    if (not isinstance(value, list) or len(value) != 2
            or any(type(n) is not int for n in value) or not 0 <= value[0] < value[1]):
        raise ValueError(f"{field} must contain two increasing integer source milliseconds")
    return tuple(value)


def merged(ranges):
    result = []
    for start, end in sorted(ranges):
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(end, result[-1][1]))
        else:
            result.append((start, end))
    return result


def contains(outer, inner):
    return all(any(a <= c and d <= b for a, b in outer) for c, d in inner)


def outside_project(path):
    resolved = path.resolve()
    if any(part.name.lower().endswith(".oilstudio") for part in (resolved, *resolved.parents)):
        raise ValueError("Use exported analysis files outside recording project packages")
    return path


def resolve_range(entry, positions, utterances, label):
    has_source = "sourceMs" in entry
    has_range = "range" in entry
    if has_source == has_range:
        raise ValueError(f"{label} needs exactly one range")
    if has_source:
        return interval(entry["sourceMs"], f"{label}.sourceMs")
    bounds = require_type(entry["range"], dict, f"{label}.range")
    indices = []
    for name in ("from", "to"):
        uid = require_type(bounds.get(name), str, f"{label}.range.{name}")
        if uid not in positions:
            raise ValueError(f"{label}.range.{name} refers to an unknown utterance: {uid}")
        indices.append(positions[uid])
    first, last = indices
    if first > last:
        raise ValueError(f"Reversed utterance range at {label}")
    return interval([utterances[first].get("sourceStartMs"), utterances[last].get("sourceEndMs")], f"{label}.range")


def parse_audit(audit, context, positions, utterances):
    if audit is None:
        return [], {}
    if not isinstance(audit, dict):
        raise ValueError("Audit must be a JSON object")
    if "schemaVersion" in audit and audit["schemaVersion"] != 1:
        raise ValueError("Unsupported audit schemaVersion")
    for key in ("projectFingerprint", "contextFingerprint"):
        if not isinstance(context.get(key), str) or not context[key] or context[key] != audit.get(key):
            raise ValueError(f"Audit {key} differs or is missing; fetch fresh context and audit")
    items = object_rows(audit.get("items"), "audit.items")
    known_ids = {c.get("id") for c in (context.get("fillerCandidates") or []) if isinstance(c, dict) and c.get("id")}
    by_range = []
    by_id = {}
    for index, entry in enumerate(items):
        kind = entry.get("decision")
        if kind not in ("keep", "review"):
            raise ValueError(f"Audit item {index} decision must be keep or review (cuts belong in plan.json)")
        reason = entry.get("reason", "")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"Missing reason at audit item {index}")
        has_id = "id" in entry and entry["id"] is not None
        has_span = "sourceMs" in entry or "range" in entry
        if has_id == has_span:
            raise ValueError(f"Audit item {index} needs either id or sourceMs/range")
        if has_id:
            if not isinstance(entry["id"], str) or not entry["id"].strip():
                raise ValueError(f"Invalid id at audit item {index}")
            if entry["id"] not in known_ids:
                raise ValueError(f"Unknown candidate id at audit item {index}: {entry['id']}")
            by_id.setdefault(entry["id"], []).append((kind, index))
        else:
            bounds = resolve_range(entry, positions, utterances, f"Audit item {index}")
            by_range.append((bounds, kind, index))
    return by_range, by_id


def check(context, plan, audit=None):
    if not isinstance(context, dict) or not isinstance(plan, dict):
        raise ValueError("Context and plan must be JSON objects")
    for key in ("projectFingerprint", "contextFingerprint"):
        if not isinstance(context.get(key), str) or not context[key] or context[key] != plan.get(key):
            raise ValueError(f"{key} differs or is missing; fetch fresh context and plan")
    if context.get("fillerCandidates") is None:
        raise ValueError("fillerCandidates unavailable; manually audit existing timed words")
    candidates = object_rows(context["fillerCandidates"], "fillerCandidates")
    candidate_ranges = [
        interval([candidate.get("sourceStartMs"), candidate.get("sourceEndMs")],
                 f"fillerCandidates[{i}].sourceStartMs/sourceEndMs")
        for i, candidate in enumerate(candidates)
    ]
    for i, candidate in enumerate(candidates):
        if candidate.get("id") is not None:
            require_type(candidate["id"], str, f"fillerCandidates[{i}].id")
    utterances = object_rows(context.get("utterances", []), "utterances")
    positions = {require_type(u.get("id"), str, f"utterances[{i}].id"): i for i, u in enumerate(utterances)}
    if len(positions) != len(utterances):
        raise ValueError("Duplicate utterance ID")
    retained = None
    if "slices" in context:
        retained_slices = []
        for i, s in enumerate(object_rows(context["slices"], "slices")):
            s_start, s_end = s.get("sourceStartMs"), s.get("sourceEndMs")
            if type(s_start) is not int or type(s_end) is not int or not 0 <= s_start <= s_end:
                raise ValueError(f"slices[{i}].sourceStartMs/sourceEndMs must contain two non-decreasing integer source milliseconds")
            if s_start < s_end:
                retained_slices.append((s_start, s_end))
        retained = merged(retained_slices)
    semantic_cuts, silence_cuts = [], []
    semantic_sources, silence_sources = [], []
    plan_choices = []
    for index, decision in enumerate(object_rows(plan.get("decisions", []), "decisions")):
        bounds = resolve_range(decision, positions, utterances, f"decisions[{index}]")
        kind = decision.get("decision")
        if kind not in ("cut", "keep", "review"):
            raise ValueError(f"Unknown decision at index {index}")
        reason = decision.get("reason", "")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"Missing reason at decision {index}")
        if kind == "cut" and decision.get("confidence") in ("high", "medium"):
            if decision.get("category") == "silence":
                silence_cuts.append(bounds)
                silence_sources.append((bounds, index))
            else:
                semantic_cuts.append(bounds)
                semantic_sources.append((bounds, index))
        elif kind in ("keep", "review"):
            plan_choices.append((bounds, kind, index))
    audit_choices, audit_by_id = parse_audit(audit, context, positions, utterances)
    all_cuts = merged(semantic_cuts + silence_cuts)
    merged_semantic = merged(semantic_cuts)
    all_cut_sources = semantic_sources + silence_sources
    rows = []
    silence_overlaps = 0
    for candidate, (start, end) in zip(candidates, candidate_ranges):
        cand_id = candidate.get("id")
        required = [(start, end)] if retained is None else [
            (max(start, a), min(end, b)) for a, b in retained if max(start, a) < min(end, b)]
        matching_plan = [(kind, index) for bounds, kind, index in plan_choices if contains([bounds], required)]
        matching_audit = [(kind, index) for bounds, kind, index in audit_choices if contains([bounds], required)]
        if cand_id in audit_by_id:
            matching_audit.extend(audit_by_id[cand_id])
        kinds = {kind for kind, _ in matching_plan} | {kind for kind, _ in matching_audit}
        partial_semantic = [index for (a, b), index in semantic_sources
                            if any(max(a, c) < min(b, d) for c, d in required)]
        partial_silence = [index for (a, b), index in silence_sources
                           if any(max(a, c) < min(b, d) for c, d in required)]
        if not required:
            status = "alreadyRemoved"
        elif contains(all_cuts, required):
            status = "cut"
        elif any(max(a, c) < min(b, d) for a, b in merged_semantic for c, d in required):
            status = "unresolved"
        elif len(kinds) == 1:
            status = next(iter(kinds))
        else:
            status = "unresolved"
        decision_indices = ([index for (a, b), index in all_cut_sources
                             if any(max(a, c) < min(b, d) for c, d in required)] if status == "cut"
                            else [index for kind, index in matching_plan if kind == status])
        audit_indices = sorted({index for kind, index in matching_audit if kind == status}) if status in ("keep", "review") else []
        row = {"id": cand_id, "word": candidate.get("word"),
               "sourceMs": [start, end], "status": status,
               "decisionIndices": decision_indices}
        if audit_indices:
            row["auditIndices"] = audit_indices
        if status == "unresolved" and partial_semantic:
            row["partialCutIndices"] = partial_semantic
        if status != "cut" and partial_silence:
            row["silenceOverlapIndices"] = partial_silence
            silence_overlaps += 1
        rows.append(row)
    counts = dict(Counter(row["status"] for row in rows))
    report = {"ok": not counts.get("unresolved", 0), "candidateCount": len(rows),
              "counts": counts, "candidates": rows,
              "scope": "Coverage only; review entries remain unresolved editorial work. Validate the plan with oilstudio."}
    if silence_overlaps:
        report["silenceOverlapCount"] = silence_overlaps
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--audit", type=Path, help="Optional separate keep/review audit manifest")
    parser.add_argument("--out", type=Path, help="Write a new report; never overwrite an existing file")
    args = parser.parse_args()
    try:
        for path in (args.context, args.plan, args.audit, args.out):
            if path is not None:
                outside_project(path)
        audit_data = json.loads(args.audit.read_text(encoding="utf-8")) if args.audit else None
        report = check(json.loads(args.context.read_text(encoding="utf-8")),
                       json.loads(args.plan.read_text(encoding="utf-8")),
                       audit=audit_data)
        if args.out:
            with args.out.open("x", encoding="utf-8") as stream:
                json.dump(report, stream, ensure_ascii=False, indent=2)
        print(json.dumps({k: v for k, v in report.items() if k != "candidates"}, ensure_ascii=False))
        return 0 if report["ok"] else 1
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

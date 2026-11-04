#!/usr/bin/env python3
"""Check candidate coverage, not the semantic or acoustic quality of an edit."""
import sys
sys.dont_write_bytecode = True
import argparse
from collections import Counter
import json
from pathlib import Path


def interval(value):
    if (not isinstance(value, list) or len(value) != 2
            or any(type(n) is not int for n in value) or not 0 <= value[0] < value[1]):
        raise ValueError("Expected two increasing integer source milliseconds")
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


def check(context, plan):
    if not isinstance(context, dict) or not isinstance(plan, dict):
        raise ValueError("Context and plan must be JSON objects")
    for key in ("projectFingerprint", "contextFingerprint"):
        if not isinstance(context.get(key), str) or not context[key] or context[key] != plan.get(key):
            raise ValueError(f"{key} differs or is missing; fetch fresh context and plan")
    candidates = context.get("fillerCandidates")
    if not isinstance(candidates, list):
        raise ValueError("fillerCandidates unavailable; manually audit existing timed words")
    utterances = context.get("utterances", [])
    positions = {u["id"]: i for i, u in enumerate(utterances)}
    if len(positions) != len(utterances):
        raise ValueError("Duplicate utterance ID")
    retained = None
    if "slices" in context:
        retained = merged(interval([s["sourceStartMs"], s["sourceEndMs"]]) for s in context["slices"])
    cuts, cut_sources, choices = [], [], []
    for index, decision in enumerate(plan.get("decisions", [])):
        if ("sourceMs" in decision) == ("range" in decision):
            raise ValueError(f"Decision {index} needs exactly one range")
        if "sourceMs" in decision:
            bounds = interval(decision["sourceMs"])
        else:
            first = positions[decision["range"]["from"]]
            last = positions[decision["range"]["to"]]
            if first > last:
                raise ValueError(f"Reversed utterance range at decision {index}")
            bounds = interval([utterances[first]["sourceStartMs"], utterances[last]["sourceEndMs"]])
        kind = decision.get("decision")
        if kind not in ("cut", "keep", "review"):
            raise ValueError(f"Unknown decision at index {index}")
        reason = decision.get("reason", "")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"Missing reason at decision {index}")
        if kind == "cut" and decision.get("confidence") in ("high", "medium"):
            cuts.append(bounds)
            cut_sources.append((bounds, index))
        elif kind in ("keep", "review"):
            choices.append((bounds, kind, index))
    cuts = merged(cuts)
    rows = []
    for candidate in candidates:
        start, end = interval([candidate["sourceStartMs"], candidate["sourceEndMs"]])
        required = [(start, end)] if retained is None else [
            (max(start, a), min(end, b)) for a, b in retained if max(start, a) < min(end, b)]
        matching = [(kind, index) for bounds, kind, index in choices if contains([bounds], required)]
        kinds = {kind for kind, _ in matching}
        if not required:
            status = "alreadyRemoved"
        elif contains(cuts, required):
            status = "cut"
        elif any(max(a, c) < min(b, d) for a, b in cuts for c, d in required):
            status = "unresolved"
        elif len(kinds) == 1:
            status = next(iter(kinds))
        else:
            status = "unresolved"
        indices = ([index for (a, b), index in cut_sources
                    if any(max(a, c) < min(b, d) for c, d in required)] if status == "cut"
                   else [index for kind, index in matching if kind == status])
        rows.append({"id": candidate.get("id"), "word": candidate.get("word"),
                     "sourceMs": [start, end], "status": status,
                     "decisionIndices": indices})
    counts = dict(Counter(row["status"] for row in rows))
    return {"ok": not counts.get("unresolved", 0), "candidateCount": len(rows),
            "counts": counts, "candidates": rows,
            "scope": "Coverage only; review entries remain unresolved editorial work. Validate the plan with oilstudio."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--out", type=Path, help="Write a new report; never overwrite an existing file")
    args = parser.parse_args()
    try:
        for path in (args.context, args.plan, args.out):
            if path is not None:
                outside_project(path)
        report = check(json.loads(args.context.read_text()), json.loads(args.plan.read_text()))
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

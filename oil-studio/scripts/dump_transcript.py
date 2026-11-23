#!/usr/bin/env python3
"""Render an Oil Studio context.json into a compact readable transcript and filler index."""
import sys
sys.dont_write_bytecode = True
import argparse
import json
import math
from pathlib import Path
from check_filler_coverage import object_rows, outside_project, require_type


def text_field(row, key, field):
    value = row.get(key)
    return "" if value is None else require_type(value, str, f"{field}.{key}").strip()


def number_field(row, key, field):
    value = row.get(key)
    if value is None:
        return None
    try:
        if type(value) in (int, float) and math.isfinite(value):
            return value
    except OverflowError:
        pass
    raise ValueError(f"{field}.{key} must be a finite number")


def fmt_ms(ms):
    if ms is None:
        return "-"
    seconds = max(0.0, float(ms) / 1000.0)
    minutes = int(seconds // 60)
    rem = seconds - minutes * 60
    return f"{minutes:02d}:{rem:04.1f}"


def render_context(context, max_screen=60):
    if not isinstance(context, dict):
        raise ValueError("Context must be a JSON object")
    utterances = object_rows(context.get("utterances", []), "utterances")
    fillers = object_rows(context.get("fillerCandidates", []), "fillerCandidates")
    pauses = object_rows(context.get("pauses", []), "pauses")
    activity = object_rows(context.get("activity", []), "activity")
    screen = object_rows(context.get("screen", []), "screen")
    slices = object_rows(context.get("slices", []), "slices")
    output = context.get("output")
    output = {} if output is None else require_type(output, dict, "output")

    word_count = sum(len(object_rows(u["words"], f"utterances[{i}].words"))
                     for i, u in enumerate(utterances) if u.get("words") is not None)
    lines = [
        f"# {context.get('title', 'Untitled')}",
        (
            f"- duration: {fmt_ms(number_field(output, 'durationMs', 'output'))} "
            f"| slices: {len(slices)} | utterances: {len(utterances)} "
            f"| words: {word_count} | pauses: {len(pauses)} "
            f"| fillers: {len(fillers)} | activity: {len(activity)} | screen: {len(screen)}"
        ),
        (
            f"- voiceOver: {bool(context.get('voiceOver'))} "
            f"| autoApply: {bool(context.get('autoApply'))}"
        ),
        f"- projectFingerprint: {context.get('projectFingerprint', '')}",
        f"- contextFingerprint: {context.get('contextFingerprint', '')}",
        "",
        "## Transcript",
    ]

    indexed_fillers = list(enumerate(fillers, start=1))
    for index, u in enumerate(utterances):
        field = f"utterances[{index}]"
        uid = u.get("id", "?")
        start = number_field(u, "sourceStartMs", field)
        end = number_field(u, "sourceEndMs", field)
        tags = []
        if u.get("fromSystemAudio"):
            tags.append("sys")
        audio = u.get("audio")
        audio = {} if audio is None else require_type(audio, dict, f"{field}.audio")
        conf = number_field(audio, "confidence", f"{field}.audio")
        if conf is not None and conf < 0.7:
            tags.append(f"conf={conf:.2f}")
        unrecognized = audio.get("unrecognized")
        unrecognized = [] if unrecognized is None else object_rows(unrecognized, f"{field}.audio.unrecognized")
        if unrecognized:
            tags.append(f"unrec={len(unrecognized)}")

        matched = []
        if isinstance(start, (int, float)) and isinstance(end, (int, float)):
            for num, cand in indexed_fillers:
                cs = cand.get("sourceStartMs")
                ce = cand.get("sourceEndMs")
                if isinstance(cs, (int, float)) and isinstance(ce, (int, float)) and ce > start and cs < end:
                    matched.append(f"#{num}:{cand.get('word', '')}")

        tag_text = f" ({', '.join(tags)})" if tags else ""
        filler_text = f"  [fillers: {', '.join(matched)}]" if matched else ""
        lines.append(
            f"- [{uid} {fmt_ms(start)}-{fmt_ms(end)} src={start}..{end}]{tag_text} "
            f"{text_field(u, 'text', field)}{filler_text}"
        )

    lines.append("")
    lines.append(f"## Filler Candidates ({len(fillers)})")
    if not fillers:
        lines.append("- (none)")
    else:
        for num, cand in indexed_fillers:
            field = f"fillerCandidates[{num - 1}]"
            cid = cand.get("id", "")
            word = cand.get("word", "")
            start = number_field(cand, "sourceStartMs", field)
            end = number_field(cand, "sourceEndMs", field)
            group = cand.get("group", "")
            ov = "activity" if cand.get("overlapsActivity") else "clean"
            cuts = cand.get("suggestedCuts")
            cuts = [] if cuts is None else object_rows(cuts, f"{field}.suggestedCuts")
            cuts_str = ",".join(f"[{c.get('sourceStartMs')},{c.get('sourceEndMs')}]" for c in cuts)
            before = text_field(cand, "contextBefore", field)
            after = text_field(cand, "contextAfter", field)
            lines.append(
                f"- #{num} id={cid} word={json.dumps(word, ensure_ascii=False)} "
                f"src=[{start},{end}] ({fmt_ms(start)}) group={group} {ov}"
                + (f" suggested={cuts_str}" if cuts_str else "")
                + f" | {before}[{word}]{after}"
            )

    if screen and max_screen > 0:
        lines.append("")
        shown = screen[:max_screen]
        suffix = f" (showing {len(shown)}/{len(screen)})" if len(screen) > len(shown) else ""
        lines.append(f"## Screen OCR{suffix}")
        for index, row in enumerate(shown):
            start = number_field(row, "sourceStartMs", f"screen[{index}]")
            change = row.get("change", "")
            raw_text = row.get("text")
            if isinstance(raw_text, list):
                snippet = " / ".join(str(x).strip() for x in raw_text if str(x).strip())
            else:
                snippet = str(raw_text or "").strip()
            if len(snippet) > 120:
                snippet = snippet[:117] + "..."
            lines.append(f"- [{fmt_ms(start)} src={start}] ({change}) {snippet}")

    return "\n".join(lines) + "\n"


def build_audit_template(context):
    return {
        "schemaVersion": 1,
        "projectFingerprint": context.get("projectFingerprint", ""),
        "contextFingerprint": context.get("contextFingerprint", ""),
        "items": [],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True, type=Path)
    parser.add_argument("--out", type=Path, help="Write a new readable transcript file; never overwrite")
    parser.add_argument("--audit-template", type=Path, help="Write a new empty filler audit JSON; never overwrite")
    parser.add_argument("--max-screen", type=int, default=60, help="Max screen OCR rows to include (default: 60)")
    args = parser.parse_args()
    try:
        for path in (args.context, args.out, args.audit_template):
            if path is not None:
                outside_project(path)
        if args.out and args.audit_template and args.out.resolve() == args.audit_template.resolve():
            raise ValueError("--out and --audit-template must not refer to the same file")
        for target in (args.out, args.audit_template):
            if target is not None and target.exists():
                raise FileExistsError(f"Output file already exists: {target}")
        context = json.loads(args.context.read_text(encoding="utf-8"))
        rendered = render_context(context, max_screen=max(0, args.max_screen))
        if args.out:
            with args.out.open("x", encoding="utf-8") as stream:
                stream.write(rendered)
        if args.audit_template:
            with args.audit_template.open("x", encoding="utf-8") as stream:
                json.dump(build_audit_template(context), stream, ensure_ascii=False, indent=2)
        if args.out:
            summary = {
                "ok": True,
                "path": str(args.out),
                "utterances": len(context.get("utterances", [])),
                "fillerCandidates": len(context.get("fillerCandidates", [])),
            }
            if args.audit_template:
                summary["auditTemplatePath"] = str(args.audit_template)
            print(json.dumps(summary, ensure_ascii=False))
        else:
            sys.stdout.write(rendered)
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

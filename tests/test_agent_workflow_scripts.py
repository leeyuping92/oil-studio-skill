import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "oil-studio/scripts"


with patch.object(sys, "path", [str(SCRIPTS), *sys.path]):
    import check_filler_coverage as coverage
    import dump_transcript


class FillerAuditAndSilenceOverlapTests(unittest.TestCase):
    def setUp(self):
        self.context = {
            "title": "Demo Talk",
            "projectFingerprint": "pfp",
            "contextFingerprint": "cfp",
            "output": {"durationMs": 60000},
            "voiceOver": False,
            "autoApply": False,
            "slices": [{"sourceStartMs": 0, "sourceEndMs": 60000}],
            "utterances": [
                {
                    "id": "U0001",
                    "sourceStartMs": 0,
                    "sourceEndMs": 5000,
                    "fromSystemAudio": False,
                    "text": "今天呃我们讲一下啊这个功能",
                    "words": [{"text": "今天"}, {"text": "呃"}, {"text": "我们"}],
                    "audio": {"confidence": 0.62, "unrecognized": [{"sourceStartMs": 1200, "sourceEndMs": 1400}]},
                },
                {
                    "id": "U0002",
                    "sourceStartMs": 6000,
                    "sourceEndMs": 10000,
                    "fromSystemAudio": True,
                    "text": "系统提示音",
                    "words": [{"text": "系统提示音"}],
                },
            ],
            "pauses": [{"sourceStartMs": 5000, "sourceEndMs": 6000}],
            "activity": [{"kind": "click", "sourceMs": 1500}],
            "screen": [{"sourceStartMs": 0, "change": "start", "text": ["Editor Window", "Panel"]}],
            "fillerCandidates": [
                {
                    "id": "f1",
                    "word": "呃",
                    "sourceStartMs": 400,
                    "sourceEndMs": 600,
                    "group": "certain",
                    "overlapsActivity": False,
                    "contextBefore": "今天",
                    "contextAfter": "我们",
                    "suggestedCuts": [{"sourceStartMs": 380, "sourceEndMs": 620}],
                },
                {
                    "id": "f2",
                    "word": "啊",
                    "sourceStartMs": 2000,
                    "sourceEndMs": 3000,
                    "group": "possiblyMeaningful",
                    "overlapsActivity": False,
                    "contextBefore": "讲一下",
                    "contextAfter": "这个功能",
                    "suggestedCuts": [],
                },
            ],
        }
        self.plan = {
            "schemaVersion": 1,
            "projectFingerprint": "pfp",
            "contextFingerprint": "cfp",
            "decisions": [
                {
                    "decision": "cut",
                    "confidence": "high",
                    "category": "filler",
                    "sourceMs": [380, 620],
                    "reason": "Independent hesitation sound",
                }
            ],
        }
        self.audit = {
            "schemaVersion": 1,
            "projectFingerprint": "pfp",
            "contextFingerprint": "cfp",
            "items": [
                {"id": "f2", "decision": "keep", "reason": "Natural sentence particle"},
            ],
        }

    def test_separate_audit_covers_keep_without_bloating_plan(self):
        report = coverage.check(self.context, self.plan, audit=self.audit)
        self.assertTrue(report["ok"])
        self.assertEqual(report["counts"], {"cut": 1, "keep": 1})
        f2 = next(row for row in report["candidates"] if row["id"] == "f2")
        self.assertEqual(f2["decisionIndices"], [])
        self.assertEqual(f2["auditIndices"], [0])

    def test_audit_rejects_cut_decision_and_fingerprint_mismatch(self):
        bad_decision = {**self.audit, "items": [{"id": "f2", "decision": "cut", "reason": "wrong file"}]}
        with self.assertRaises(ValueError):
            coverage.check(self.context, self.plan, audit=bad_decision)

        bad_fp = {**self.audit, "contextFingerprint": "stale"}
        with self.assertRaises(ValueError):
            coverage.check(self.context, self.plan, audit=bad_fp)

        bad_id = {**self.audit, "items": [{"id": "typo-id", "decision": "keep", "reason": "typo"}]}
        with self.assertRaises(ValueError):
            coverage.check(self.context, self.plan, audit=bad_id)

    def test_silence_partial_overlap_with_explicit_keep_passes_and_annotates(self):
        # Stretched filler f2 [2000, 3000] has its quiet tail [2600, 3400] clipped by a silence cut.
        self.plan["decisions"].append(
            {
                "decision": "cut",
                "confidence": "high",
                "category": "silence",
                "sourceMs": [2600, 3400],
                "reason": "Tighten pause",
            }
        )
        report = coverage.check(self.context, self.plan, audit=self.audit)
        self.assertTrue(report["ok"])
        self.assertEqual(report["counts"], {"cut": 1, "keep": 1})
        self.assertEqual(report["silenceOverlapCount"], 1)
        f2 = next(row for row in report["candidates"] if row["id"] == "f2")
        self.assertEqual(f2["silenceOverlapIndices"], [1])

    def test_semantic_partial_overlap_still_fails_even_with_audit_keep(self):
        self.plan["decisions"].append(
            {
                "decision": "cut",
                "confidence": "high",
                "category": "slip",
                "sourceMs": [2600, 3400],
                "reason": "Partial semantic overlap",
            }
        )
        report = coverage.check(self.context, self.plan, audit=self.audit)
        self.assertFalse(report["ok"])
        f2 = next(row for row in report["candidates"] if row["id"] == "f2")
        self.assertEqual(f2["status"], "unresolved")
        self.assertEqual(f2["partialCutIndices"], [1])

    def test_dump_transcript_renders_markers_and_writes_audit_template(self):
        text = dump_transcript.render_context(self.context)
        self.assertIn("# Demo Talk", text)
        self.assertIn("[fillers: #1:呃, #2:啊]", text)
        self.assertIn("(sys)", text)
        self.assertIn("conf=0.62", text)
        self.assertIn("unrec=1", text)
        self.assertIn("## Filler Candidates (2)", text)
        self.assertIn("#1 id=f1", text)
        self.assertIn("## Screen OCR", text)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ctx_path = root / "ctx.json"
            out_path = root / "transcript.md"
            tpl_path = root / "audit.json"
            ctx_path.write_text(json.dumps(self.context, ensure_ascii=False), encoding="utf-8")
            proc = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "dump_transcript.py"),
                    "--context",
                    str(ctx_path),
                    "--out",
                    str(out_path),
                    "--audit-template",
                    str(tpl_path),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            summary = json.loads(proc.stdout)
            self.assertEqual(summary["utterances"], 2)
            self.assertEqual(summary["fillerCandidates"], 2)
            template = json.loads(tpl_path.read_text(encoding="utf-8"))
            self.assertEqual(template["projectFingerprint"], "pfp")
            self.assertEqual(template["items"], [])
            # Never overwrites existing files, and never creates audit-template if --out already exists.
            fresh_tpl = root / "fresh-audit.json"
            again = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "dump_transcript.py"),
                    "--context",
                    str(ctx_path),
                    "--out",
                    str(out_path),
                    "--audit-template",
                    str(fresh_tpl),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(again.returncode, 2)
            self.assertFalse(fresh_tpl.exists())

    def test_verify_plan_combines_coverage_and_compact_cli_with_legacy_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ctx_path = root / "ctx.json"
            plan_path = root / "plan.json"
            audit_path = root / "audit.json"
            cov_out = root / "coverage.json"
            ctx_path.write_text(json.dumps(self.context, ensure_ascii=False), encoding="utf-8")
            plan_path.write_text(json.dumps(self.plan, ensure_ascii=False), encoding="utf-8")
            audit_path.write_text(json.dumps(self.audit, ensure_ascii=False), encoding="utf-8")

            # Fake legacy CLI that rejects --compact and returns full results when called without --compact.
            fake_cli = root / "fake-oilstudio"
            fake_cli.write_text(
                "#!/usr/bin/env python3\n"
                "import json, sys\n"
                "if '--compact' in sys.argv:\n"
                "    print(json.dumps({'ok': False, 'error': {'code': 'USAGE', 'message': '未知或重复的参数：--compact。'}}))\n"
                "    sys.exit(2)\n"
                "print(json.dumps({'ok': True, 'results': [\n"
                "    {'index': 0, 'status': 'accepted', 'kind': 'cut', 'reason': ''},\n"
                "    {'index': 1, 'status': 'uncheckedByDefault', 'kind': 'cut', 'reason': '此处有操作，默认不勾选',\n"
                "     'matchedActivity': [{'kind': 'mouseUp', 'sourceMs': 1500}]}\n"
                "], 'cutAdjustments': [{'index': 0, 'sourceMs': [380, 660], 'addedSourceMs': 40}]}))\n",
                encoding="utf-8",
            )
            os.chmod(fake_cli, os.stat(fake_cli).st_mode | stat.S_IEXEC)

            proc = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "verify_plan.py"),
                    "--context",
                    str(ctx_path),
                    "--plan",
                    str(plan_path),
                    "--audit",
                    str(audit_path),
                    "--coverage-out",
                    str(cov_out),
                    "--oilstudio",
                    str(fake_cli),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            result = json.loads(proc.stdout)
            self.assertTrue(result["ok"])
            self.assertEqual(result["coverage"]["counts"], {"cut": 1, "keep": 1})
            self.assertEqual(result["validation"]["summary"]["total"], 2)
            self.assertEqual(result["validation"]["summary"]["accepted"], 1)
            self.assertEqual(len(result["validation"]["uncheckedByDefault"]), 1)
            self.assertEqual(result["validation"]["cutAdjustmentCount"], 1)
            self.assertTrue(cov_out.exists())

    def run_verify(self, reply, exit_code=0, stderr=""):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arguments = []
            for option, data in [("context", self.context), ("plan", self.plan), ("audit", self.audit)]:
                path = root / f"{option}.json"
                path.write_text(json.dumps(data), encoding="utf-8")
                arguments.extend([f"--{option}", str(path)])
            fake_cli = root / "fake-oilstudio"
            fake_cli.write_text(
                "#!/usr/bin/env python3\n"
                "import sys\n"
                + (f"print({json.dumps(reply)!r})\n" if reply is not None else "")
                + f"print({stderr!r}, file=sys.stderr)\nsys.exit({exit_code})\n",
                encoding="utf-8",
            )
            fake_cli.chmod(0o700)
            return subprocess.run([sys.executable, str(SCRIPTS / "verify_plan.py"),
                                   *arguments, "--oilstudio", str(fake_cli)],
                                  capture_output=True, text=True)

    def test_cut_expansion_rejects_overlap_with_audit_keep_or_review(self):
        self.audit["items"].extend([
            {"decision": "review", "reason": "Inspect the boundary", "sourceMs": [1900, 2100]},
            {"decision": "keep", "reason": "Keep this sentence", "range": {"from": "U0002", "to": "U0002"}},
            {"decision": "keep", "reason": "Still inside the retained clip", "sourceMs": [7000, 8000]},
        ])
        self.plan["clip"] = {"sourceStartMs": 5900, "sourceEndMs": 10499.8}
        reply = {"ok": True, "cutAdjustments": [
            {"index": 0, "sourceMs": [380, 2050], "addedSourceMs": 1430},
            {"kind": "clip", "sourceStartMs": 6100, "sourceEndMs": 10500, "addedSourceMs": 200},
        ]}
        proc = self.run_verify(reply)
        self.assertEqual(proc.returncode, 1, proc.stderr)
        validation = json.loads(proc.stdout)["validation"]
        self.assertFalse(validation["ok"])
        self.assertEqual([entry["auditIndex"] for entry in validation["auditProtectionConflicts"]], [0, 1, 2])
        self.assertEqual(validation["auditProtectionConflicts"][0]["id"], "f2")
        self.assertIn("plan.json", validation["auditProtectionHint"])

    def test_cut_expansion_that_only_touches_audit_range_passes(self):
        proc = self.run_verify({"ok": True, "cutAdjustments": [
            {"index": 0, "sourceMs": [380, 2000], "addedSourceMs": 1380},
        ]})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["ok"])

    def test_only_newly_removed_audio_conflicts_with_audit_keep(self):
        self.context["utterances"].append({"id": "U0003", "sourceStartMs": 1000, "sourceEndMs": 2000})
        self.plan["decisions"].append({
            "decision": "cut", "confidence": "high", "category": "silence",
            "reason": "Trim a pause",
        })
        self.audit["items"].append({"decision": "keep", "sourceMs": [1950, 2050], "reason": "Protect the join"})
        decision = self.plan["decisions"][-1]
        for field, value in [("sourceMs", [1000, 2000]), ("range", {"from": "U0003", "to": "U0003"})]:
            decision[field] = value
            for owner, adjusted, expected in [(1, [950, 2000], []), (1, [1000, 2025], [0, 1]), (2, [2000, 2025], [0, 1])]:
                with self.subTest(field=field, owner=owner, adjusted=adjusted):
                    proc = self.run_verify({"ok": True, "cutAdjustments": [{"index": owner, "sourceMs": adjusted}]})
                    self.assertEqual(proc.returncode, int(bool(expected)), proc.stdout or proc.stderr)
                    conflicts = json.loads(proc.stdout)["validation"].get("auditProtectionConflicts", [])
                    self.assertEqual([item["auditIndex"] for item in conflicts], expected)
            del decision[field]

    def test_cleanup_warning_blocks_submission_even_when_validate_succeeds(self):
        proc = self.run_verify({"ok": True, "cleanupWarning": "Audio could not be checked"})
        self.assertEqual(proc.returncode, 1, proc.stderr)
        validation = json.loads(proc.stdout)["validation"]
        self.assertFalse(validation["ok"])
        self.assertEqual(validation["cleanupWarning"], "Audio could not be checked")

    def test_verify_preserves_validation_subprocess_exit_code(self):
        for reply in [{"ok": False, "error": {"code": "PROJECT_NOT_FOUND"}}, None]:
            with self.subTest(reply=reply):
                proc = self.run_verify(reply, exit_code=3, stderr="missing project")
                self.assertEqual(proc.returncode, 3, proc.stderr)
                if reply is None:
                    self.assertIn("missing project", proc.stderr)
                else:
                    self.assertEqual(json.loads(proc.stdout)["validation"]["error"], reply["error"])

    def test_verify_reports_malformed_nested_fields(self):
        malformed_response = self.run_verify({"ok": True, "results": [123]})
        self.assertEqual(malformed_response.returncode, 2)
        self.assertIn("results[0]", json.loads(malformed_response.stderr)["error"])
        self.context["fillerCandidates"] = [123]
        malformed_context = self.run_verify({"ok": True})
        self.assertEqual(malformed_context.returncode, 2)
        self.assertIn("fillerCandidates[0]", json.loads(malformed_context.stderr)["error"])

    def test_verify_rejects_non_integer_summary_counts(self):
        counts = dict.fromkeys(["total", "accepted", "uncheckedByDefault", "rejected", "notes"], 0)
        for key, value in [("total", []), ("accepted", True), ("uncheckedByDefault", 1.0),
                           ("rejected", "0"), ("notes", None)]:
            with self.subTest(key=key):
                proc = self.run_verify({"ok": True, "summary": {**counts, key: value}})
                self.assertEqual(proc.returncode, 2)
                self.assertIn(f"summary.{key}", json.loads(proc.stderr)["error"])

    def test_dump_rejects_non_numeric_confidence(self):
        with tempfile.TemporaryDirectory() as directory:
            context_path = Path(directory) / "context.json"
            for value, expected_exit in [("0.62", 2), (True, 2), (None, 0)]:
                with self.subTest(value=value):
                    self.context["utterances"][0]["audio"]["confidence"] = value
                    context_path.write_text(json.dumps(self.context), encoding="utf-8")
                    proc = subprocess.run([sys.executable, str(SCRIPTS / "dump_transcript.py"),
                                           "--context", str(context_path)], capture_output=True, text=True)
                    self.assertEqual(proc.returncode, expected_exit, proc.stderr)
                    if expected_exit:
                        self.assertIn("utterances[0].audio.confidence", json.loads(proc.stderr)["error"])

    def test_dump_reports_malformed_nested_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            context_path = Path(directory) / "context.json"
            for field, value in [("audio", ["invalid"]), ("words", 5), ("text", ["invalid"])]:
                with self.subTest(field=field):
                    context = {**self.context, "utterances": [{**self.context["utterances"][0], field: value}]}
                    context_path.write_text(json.dumps(context), encoding="utf-8")
                    proc = subprocess.run([sys.executable, str(SCRIPTS / "dump_transcript.py"),
                                           "--context", str(context_path)], capture_output=True, text=True)
                    self.assertEqual(proc.returncode, 2)
                    self.assertIn(f"utterances[0].{field}", json.loads(proc.stderr)["error"])

    def test_verify_flags_short_remainders_unless_absorbed_or_kept(self):
        # Two cuts leave an 80 ms fragment [1500, 1580] in the timeline.
        self.plan["decisions"].extend([
            {"decision": "cut", "confidence": "high", "category": "silence",
             "sourceMs": [1200, 1500], "reason": "Trim pause"},
            {"decision": "cut", "confidence": "high", "category": "false_start",
             "sourceMs": [1580, 2000], "reason": "Remove false start"},
        ])
        proc = self.run_verify({"ok": True, "cutAdjustments": []})
        self.assertEqual(proc.returncode, 1, proc.stdout or proc.stderr)
        result = json.loads(proc.stdout)
        self.assertFalse(result["ok"])
        self.assertFalse(result["validation"]["ok"])
        remainders = result["validation"]["shortRemainders"]
        self.assertEqual(len(remainders), 1)
        self.assertEqual(remainders[0]["sourceMs"], [1500, 1580])
        self.assertEqual(remainders[0]["durationMs"], 80)

        # Once CLI cutAdjustments absorb the 80 ms gap, verification passes.
        absorbed = self.run_verify({"ok": True, "cutAdjustments": [
            {"index": 1, "sourceMs": [1200, 1580], "addedSourceMs": 80},
        ]})
        self.assertEqual(absorbed.returncode, 0, absorbed.stdout or absorbed.stderr)
        self.assertTrue(json.loads(absorbed.stdout)["ok"])

        # Explicit keep in audit.json exempts an intentional short retained span.
        self.audit["items"].append({"decision": "keep", "sourceMs": [1500, 1580], "reason": "Intentional short cue"})
        kept = self.run_verify({"ok": True, "cutAdjustments": []})
        self.assertEqual(kept.returncode, 0, kept.stdout or kept.stderr)
        self.assertTrue(json.loads(kept.stdout)["ok"])

        # --skip-validate also catches unabsorbed short remainders.
        self.audit["items"].pop()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ctx_path = root / "ctx.json"
            plan_path = root / "plan.json"
            audit_path = root / "audit.json"
            ctx_path.write_text(json.dumps(self.context), encoding="utf-8")
            plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
            audit_path.write_text(json.dumps(self.audit), encoding="utf-8")
            skip_proc = subprocess.run(
                [sys.executable, str(SCRIPTS / "verify_plan.py"),
                 "--context", str(ctx_path), "--plan", str(plan_path),
                 "--audit", str(audit_path), "--skip-validate"],
                capture_output=True, text=True,
            )
            self.assertEqual(skip_proc.returncode, 1)
            skip_res = json.loads(skip_proc.stdout)
            self.assertFalse(skip_res["ok"])
            self.assertEqual(skip_res["shortRemainders"][0]["sourceMs"], [1500, 1580])

    def test_verify_short_remainders_edge_cases_match_swift_semantics(self):
        # 1. Untouched 60 ms opening slice is not flagged when not bounded by deletions on both sides
        # (second slice starts at 70 so [70, 380] before the setUp filler cut is 310 ms > 300 ms).
        self.context["slices"] = [
            {"sourceStartMs": 0, "sourceEndMs": 60, "sessionIndex": 0, "sceneIndex": 0},
            {"sourceStartMs": 70, "sourceEndMs": 60000, "sessionIndex": 0, "sceneIndex": 0},
        ]
        opening_ok = self.run_verify({"ok": True, "cutAdjustments": []})
        self.assertEqual(opening_ok.returncode, 0, opening_ok.stdout or opening_ok.stderr)
        self.assertTrue(json.loads(opening_ok.stdout)["ok"])

        # 2. Cross-session or missing-session existing gaps are never mistaken for same-session deletions.
        self.context["slices"] = [
            {"sourceStartMs": 0, "sourceEndMs": 1000, "sessionIndex": 0, "sceneIndex": 0},
            {"sourceStartMs": 1100, "sourceEndMs": 1180, "sessionIndex": 1, "sceneIndex": 0},
            {"sourceStartMs": 1500, "sourceEndMs": 60000, "sessionIndex": 1, "sceneIndex": 0},
        ]
        cross_session = self.run_verify({"ok": True, "cutAdjustments": []})
        self.assertEqual(cross_session.returncode, 0, cross_session.stdout or cross_session.stderr)

        self.context["slices"] = [
            {"sourceStartMs": 0, "sourceEndMs": 1000},
            {"sourceStartMs": 1100, "sourceEndMs": 1180},
            {"sourceStartMs": 1500, "sourceEndMs": 60000},
        ]
        missing_session = self.run_verify({"ok": True, "cutAdjustments": []})
        self.assertEqual(missing_session.returncode, 0, missing_session.stdout or missing_session.stderr)

        # 3. Legitimate sub-millisecond slice rounded to start == end does not crash with exit 2.
        self.context["slices"] = [
            {"sourceStartMs": 0, "sourceEndMs": 1000, "sessionIndex": 0, "sceneIndex": 0},
            {"sourceStartMs": 1000, "sourceEndMs": 1000, "sessionIndex": 0, "sceneIndex": 0},
            {"sourceStartMs": 2000, "sourceEndMs": 60000, "sessionIndex": 0, "sceneIndex": 0},
        ]
        sub_ms = self.run_verify({"ok": True, "cutAdjustments": []})
        self.assertEqual(sub_ms.returncode, 0, sub_ms.stdout or sub_ms.stderr)

        # 4. Repeated source occurrence with explicit matching session/scene catches double-deleted 80 ms fragment.
        self.context["slices"] = [
            {"sourceStartMs": 0, "sourceEndMs": 5000, "sessionIndex": 0, "sceneIndex": 0},
            {"sourceStartMs": 1000, "sourceEndMs": 1500, "sessionIndex": 0, "sceneIndex": 0},
            {"sourceStartMs": 3200, "sourceEndMs": 3280, "sessionIndex": 0, "sceneIndex": 0},
            {"sourceStartMs": 4000, "sourceEndMs": 60000, "sessionIndex": 0, "sceneIndex": 0},
        ]
        repeated = self.run_verify({"ok": True, "cutAdjustments": []})
        self.assertEqual(repeated.returncode, 1, repeated.stdout or repeated.stderr)
        self.assertEqual(json.loads(repeated.stdout)["validation"]["shortRemainders"][0]["sourceMs"], [3200, 3280])

        # 5. Authoritative CLI remainingFragments (including sub-ms slivers rounded to [1000, 1000] by wire output,
        # unrounded floats, and empty []) take precedence.
        for wire_row, expected_bounds in [
            ({"sessionIndex": 0, "sourceMs": [1000, 1000], "durationMs": 1}, [1000, 1000]),
            ({"sessionIndex": 0, "sourceMs": [999.6, 1000.4], "durationMs": 0.8}, [999.6, 1000.4]),
        ]:
            cli_sliver = self.run_verify({"ok": True, "cutAdjustments": [], "remainingFragments": [wire_row]})
            self.assertEqual(cli_sliver.returncode, 1, cli_sliver.stdout or cli_sliver.stderr)
            self.assertEqual(json.loads(cli_sliver.stdout)["validation"]["shortRemainders"][0]["sourceMs"], expected_bounds)

        cli_clean = self.run_verify({"ok": True, "cutAdjustments": [], "remainingFragments": []})
        self.assertEqual(cli_clean.returncode, 0, cli_clean.stdout or cli_clean.stderr)
        self.assertTrue(json.loads(cli_clean.stdout)["ok"])

        # 6. Double-deleted 250 ms remainder (within <= 300 ms policy) is flagged; partial low-confidence overlap exempts it.
        self.context["slices"] = [{"sourceStartMs": 0, "sourceEndMs": 60000, "sessionIndex": 0, "sceneIndex": 0}]
        self.plan["decisions"].extend([
            {"decision": "cut", "confidence": "high", "category": "silence",
             "sourceMs": [1200, 1500], "reason": "Trim pause"},
            {"decision": "cut", "confidence": "high", "category": "false_start",
             "sourceMs": [1750, 2000], "reason": "Remove false start"},
        ])
        mid_gap = self.run_verify({"ok": True, "cutAdjustments": []})
        self.assertEqual(mid_gap.returncode, 1, mid_gap.stdout or mid_gap.stderr)
        self.assertEqual(json.loads(mid_gap.stdout)["validation"]["shortRemainders"][0]["durationMs"], 250)

        self.plan["decisions"].append(
            {"decision": "cut", "confidence": "low", "category": "silence",
             "sourceMs": [1520, 1560], "reason": "Partial review"}
        )
        partial_low = self.run_verify({"ok": True, "cutAdjustments": []})
        self.assertEqual(partial_low.returncode, 0, partial_low.stdout or partial_low.stderr)
        self.assertTrue(json.loads(partial_low.stdout)["ok"])

        # 7. Disjoint cutAdjustment that does not expand its owner cut is rejected instead of forming a convex hull.
        self.plan["decisions"].pop()
        disjoint = self.run_verify({"ok": True, "cutAdjustments": [
            {"index": 1, "sourceMs": [1550, 1600], "addedSourceMs": 50},
        ]})
        self.assertEqual(disjoint.returncode, 2)
        self.assertIn("expand its owner decision range", json.loads(disjoint.stderr)["error"])

        # 8. Orphan sub-millisecond cutAdjustment rounded to [1000, 1000] does not crash verify_plan.py with exit 2,
        # and still reports auditProtectionConflicts when strictly inside an audit keep span.
        cleaned_orphan = self.run_verify({
            "ok": True,
            "cutAdjustments": [{"index": 99, "sourceMs": [1000, 1000], "addedSourceMs": 1}],
            "remainingFragments": [],
        })
        self.assertEqual(cleaned_orphan.returncode, 0, cleaned_orphan.stdout or cleaned_orphan.stderr)
        self.assertTrue(json.loads(cleaned_orphan.stdout)["ok"])

        self.audit["items"].append({"decision": "keep", "sourceMs": [990, 1010], "reason": "Protect sub-ms boundary"})
        orphan_conflict = self.run_verify({
            "ok": True,
            "cutAdjustments": [{"index": 99, "sourceMs": [1000, 1000], "addedSourceMs": 1}],
            "remainingFragments": [],
        })
        self.assertEqual(orphan_conflict.returncode, 1, orphan_conflict.stdout or orphan_conflict.stderr)
        self.assertEqual(len(json.loads(orphan_conflict.stdout)["validation"]["auditProtectionConflicts"]), 1)
        self.audit["items"].pop()

        # 9. Missing sceneIndex or cross-session slice in offline fallback never triggers false positives,
        # while an adjacent single-session slice after a cross-session slice is still verified.
        self.plan["decisions"] = self.plan["decisions"][:1]
        self.context["slices"] = [
            {"sourceStartMs": 0, "sourceEndMs": 1000, "sessionIndex": 0},
            {"sourceStartMs": 1100, "sourceEndMs": 1180, "sessionIndex": 0},
            {"sourceStartMs": 1500, "sourceEndMs": 60000, "sessionIndex": 0},
        ]
        missing_scene = self.run_verify({"ok": True, "cutAdjustments": []})
        self.assertEqual(missing_scene.returncode, 0, missing_scene.stdout or missing_scene.stderr)

        self.context["slices"] = [
            {"sourceStartMs": 0, "sourceEndMs": 3000, "sessionIndex": 0, "endSessionIndex": 1, "sceneIndex": 0},
            {"sourceStartMs": 3000, "sourceEndMs": 60000, "sessionIndex": 1, "sceneIndex": 0},
        ]
        self.plan["decisions"].extend([
            {"decision": "cut", "confidence": "high", "category": "silence",
             "sourceMs": [1200, 1400], "reason": "Before session split"},
            {"decision": "cut", "confidence": "high", "category": "silence",
             "sourceMs": [1600, 1800], "reason": "After session split"},
        ])
        cross_slice = self.run_verify({"ok": True, "cutAdjustments": []})
        self.assertEqual(cross_slice.returncode, 0, cross_slice.stdout or cross_slice.stderr)

        self.plan["decisions"].extend([
            {"decision": "cut", "confidence": "high", "category": "silence",
             "sourceMs": [3200, 3600], "reason": "Single session cut 1"},
            {"decision": "cut", "confidence": "high", "category": "silence",
             "sourceMs": [3800, 4200], "reason": "Single session cut 2"},
        ])
        adjacent_single = self.run_verify({"ok": True, "cutAdjustments": []})
        self.assertEqual(adjacent_single.returncode, 1, adjacent_single.stdout or adjacent_single.stderr)
        self.assertEqual(json.loads(adjacent_single.stdout)["validation"]["shortRemainders"][0]["sourceMs"], [3600, 3800])

        # 10. Rejected CLI validation response preserves structured error instead of crashing in offline fallback.
        self.plan["clip"] = {"sourceStartMs": 5000, "sourceEndMs": 1000}
        rejected_cli = self.run_verify({
            "ok": False,
            "error": {"code": "VALIDATION_FAILED", "message": "Invalid clip"},
            "results": [{"index": 3, "status": "rejected", "kind": "clip", "reason": "Invalid clip"}],
        })
        self.assertEqual(rejected_cli.returncode, 1, rejected_cli.stdout or rejected_cli.stderr)
        self.assertEqual(json.loads(rejected_cli.stdout)["validation"]["error"]["code"], "VALIDATION_FAILED")


if __name__ == "__main__":
    unittest.main()

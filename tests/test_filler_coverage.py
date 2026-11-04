import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "oil-studio/scripts/check_filler_coverage.py"
SPEC = importlib.util.spec_from_file_location("coverage", SCRIPT)
coverage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(coverage)


class FillerCoverageTests(unittest.TestCase):
    def setUp(self):
        self.context = {"projectFingerprint": "project", "contextFingerprint": "context",
                        "slices": [{"sourceStartMs": 0, "sourceEndMs": 1000}],
                        "utterances": [{"id": "U0001", "sourceStartMs": 0, "sourceEndMs": 1000}],
                        "fillerCandidates": [{"id": "f1", "word": "呃", "sourceStartMs": 400, "sourceEndMs": 600}]}
        self.plan = {"projectFingerprint": "project", "contextFingerprint": "context", "decisions": []}

    def add(self, start=400, end=600, kind="cut", **extra):
        self.plan["decisions"].append({"decision": kind, "confidence": "high", "reason": "Independently removable hesitation",
                                      "sourceMs": [start, end], **extra})

    def test_pause_only_plan_leaves_speech_filler_uncovered(self):
        self.add(100, 300, category="silence")
        report = coverage.check(self.context, self.plan)
        self.assertFalse(report["ok"])
        self.assertEqual(report["counts"], {"unresolved": 1})

    def test_retaken_passage_already_covers_its_fillers(self):
        self.plan["decisions"] = [{"decision": "cut", "confidence": "medium", "reason": "Retake",
                                   "range": {"from": "U0001", "to": "U0001"}}]
        self.assertEqual(coverage.check(self.context, self.plan)["counts"], {"cut": 1})

    def test_adjacent_cuts_cover_whole_word(self):
        self.add(400, 500)
        self.add(500, 600)
        report = coverage.check(self.context, self.plan)
        self.assertEqual(report["counts"], {"cut": 1})
        self.assertEqual(report["candidates"][0]["decisionIndices"], [0, 1])

    def test_partial_word_is_not_reported_as_removed_or_retained(self):
        self.add(400, 500)
        self.add(kind="keep")
        self.assertFalse(coverage.check(self.context, self.plan)["ok"])

    def test_already_cut_middle_does_not_need_another_cut(self):
        self.context["slices"] = [{"sourceStartMs": 0, "sourceEndMs": 450},
                                  {"sourceStartMs": 550, "sourceEndMs": 1000}]
        self.add(400, 450)
        self.add(550, 600)
        self.assertEqual(coverage.check(self.context, self.plan)["counts"], {"cut": 1})

    def test_low_confidence_cut_is_not_executable(self):
        self.add(confidence="low")
        self.assertFalse(coverage.check(self.context, self.plan)["ok"])

    def test_explicit_review_is_covered_but_not_a_cut(self):
        self.add(kind="review")
        report = coverage.check(self.context, self.plan)
        self.assertTrue(report["ok"])
        self.assertEqual(report["counts"], {"review": 1})

    def test_conflicting_keep_and_review_need_a_decision(self):
        self.add(kind="keep")
        self.add(kind="review")
        self.assertFalse(coverage.check(self.context, self.plan)["ok"])

    def test_explanations_cannot_be_empty(self):
        self.add(kind="keep", reason=" ")
        with self.assertRaises(ValueError):
            coverage.check(self.context, self.plan)

    def test_different_fingerprints_fail_instead_of_rebinding(self):
        for key in ("projectFingerprint", "contextFingerprint"):
            with self.subTest(key=key):
                plan = copy.deepcopy(self.plan)
                plan[key] = "different"
                with self.assertRaises(ValueError):
                    coverage.check(self.context, plan)

    def test_missing_candidates_are_not_treated_as_an_empty_success(self):
        del self.context["fillerCandidates"]
        with self.assertRaises(ValueError):
            coverage.check(self.context, self.plan)

    def test_no_candidates_is_valid(self):
        self.context["fillerCandidates"] = []
        self.assertTrue(coverage.check(self.context, self.plan)["ok"])

    def test_cli_reports_missing_candidates_without_overwriting_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            context, plan, output = (folder / name for name in ("context.json", "plan.json", "audit.json"))
            context.write_text(json.dumps(self.context))
            plan.write_text(json.dumps(self.plan))
            command = [sys.executable, str(SCRIPT), "--context", str(context), "--plan", str(plan), "--out", str(output)]
            first = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(first.returncode, 1, first.stderr)
            self.assertEqual(json.loads(output.read_text())["counts"], {"unresolved": 1})
            original = output.read_bytes()
            self.add()
            plan.write_text(json.dumps(self.plan))
            second = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(second.returncode, 2)
            self.assertEqual(output.read_bytes(), original)
            success = subprocess.run(command[:-2], capture_output=True, text=True)
            self.assertEqual(success.returncode, 0, success.stderr)

    def test_cli_rejects_malformed_json_objects(self):
        with self.assertRaises(ValueError):
            coverage.check([], self.plan)

    def test_cli_does_not_access_project_packages_through_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "recording.oilstudio"
            project.mkdir()
            context = project / "context.json"
            context.write_text(json.dumps(self.context))
            alias = root / "alias.json"
            alias.symlink_to(context)
            plan = root / "plan.json"
            plan.write_text(json.dumps(self.plan))
            output = root / "audit.json"
            result = subprocess.run([sys.executable, str(SCRIPT), "--context", str(alias),
                                     "--plan", str(plan), "--out", str(output)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn("outside recording project", result.stderr)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()

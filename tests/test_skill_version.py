"""Keep a released Skill version tied to its complete source inventory."""
import hashlib
import json
from pathlib import Path
import re
import sys
import subprocess
import tempfile
from unittest.mock import patch
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "oil-studio"
RECORD = Path(__file__).with_name("skill-version.json")


def metadata(path, key):
    frontmatter = path.read_text().split("---", 2)[1]
    match = re.search(r"^  " + key + r":\s*[\"']?([0-9]+\.[0-9]+\.[0-9]+)[\"']?\s*$", frontmatter, re.M)
    if not match:
        raise ValueError(f"Missing or invalid metadata.{key}: {path}")
    return match[1]


def inventory():
    digest = hashlib.sha256()
    for path in sorted(SKILL.rglob("*")):
        if "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
            continue
        if path.is_symlink():
            raise ValueError(f"Skill source must not contain symbolic links: {path}")
        if path.is_file():
            digest.update(path.relative_to(SKILL).as_posix().encode() + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return {"version": metadata(SKILL / "SKILL.md", "version"), "sha256": digest.hexdigest()}


def update_record():
    current = inventory()
    previous = json.loads(RECORD.read_text())
    if current != previous and tuple(map(int, current["version"].split("."))) <= tuple(map(int, previous["version"].split("."))):
        raise ValueError("Bump metadata.version in both SKILL.md and en/SKILL.en.md before updating the inventory.")
    if metadata(SKILL / "en/SKILL.en.md", "version") != current["version"]:
        raise ValueError("The Chinese and English Skill versions must match.")
    RECORD.write_text(json.dumps(current, indent=2) + "\n")


class AgentSkillVersionTests(unittest.TestCase):
    def test_content_matches_version_record(self):
        self.assertEqual(inventory(), json.loads(RECORD.read_text()),
            "Skill content changed. Bump metadata.version in SKILL.md and en/SKILL.en.md, then run "
            "python3 -B agent-skill/tests/test_skill_version.py --update and commit the version record with the Skill.")

    def test_record_update_cannot_hide_an_unversioned_change(self):
        with tempfile.TemporaryDirectory() as directory:
            record = Path(directory) / "skill-version.json"
            previous = {"version": metadata(SKILL / "SKILL.md", "version"), "sha256": "old-content"}
            record.write_text(json.dumps(previous))
            with patch.object(sys.modules[__name__], "RECORD", record):
                with self.assertRaisesRegex(ValueError, "Bump metadata.version"):
                    update_record()
            self.assertEqual(json.loads(record.read_text()), previous)

    def test_inventory_change_advances_committed_version(self):
        # Once this record is committed, editing it cannot conceal a missing version bump.
        # Resolve the record from the enclosing repository, which is the app repository or the standalone Skill repository.
        top = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
        if top.returncode != 0:
            return  # A source archive without Git history.
        relative = RECORD.resolve().relative_to(Path(top.stdout.strip()).resolve()).as_posix()
        result = subprocess.run(["git", "-C", str(ROOT), "show", f"HEAD:{relative}"], capture_output=True, text=True)
        if result.returncode != 0:
            return  # Initial introduction of the record, or a standalone source archive.
        previous = json.loads(result.stdout)
        current = inventory()
        if current["sha256"] != previous["sha256"]:
            self.assertGreater(tuple(map(int, current["version"].split("."))), tuple(map(int, previous["version"].split("."))),
                               "Skill content changed since HEAD; advance metadata.version in both language entries.")

    def test_language_versions_and_minimum_app_match(self):
        for key in ("version", "minAppVersion"):
            self.assertEqual(metadata(SKILL / "SKILL.md", key), metadata(SKILL / "en/SKILL.en.md", key))
        # Future App releases need not raise the Skill's minimum supported version.
        # The App version file exists only in the app repository, not in the standalone Skill repository.
        app_version = ROOT.parent / "scripts/version.json"
        if not app_version.exists():
            return
        app = json.loads(app_version.read_text())["version"]
        # The next patch release can be prepared before scripts/version.json is bumped.
        app_parts = tuple(map(int, app.split(".")))
        self.assertLessEqual(tuple(map(int, metadata(SKILL / "SKILL.md", "minAppVersion").split("."))),
                             (app_parts[0], app_parts[1], app_parts[2] + 1))

    def test_version_instructions_use_this_skill_and_app_versions(self):
        for entry in (SKILL / "SKILL.md", SKILL / "en/SKILL.en.md"):
            text = entry.read_text()
            self.assertIn("`app.version`", text)
            self.assertIn("`minAppVersion`", text)
            self.assertIn("`skill.compatible`", text)
            self.assertIn("OILSTUDIO_SKILL_VERSION=", text)
            self.assertIn(f"OILSTUDIO_SKILL_VERSION={metadata(entry, 'version')} oilstudio status", text)
            self.assertIn("`SKILL_OUTDATED`", text)
            self.assertNotIn("`skill.installedVersion` differs", text)
            self.assertNotIn("`skill.installedVersion` 与", text)
        english = (SKILL / "en/SKILL.en.md").read_text()
        self.assertEqual(len(re.findall(r"^\s*-\s+`SKILL_OUTDATED`", english, re.M)), 1)


if __name__ == "__main__":
    if sys.argv[1:] == ["--update"]:
        update_record()
    else:
        unittest.main()

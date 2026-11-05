import ast
import contextlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import string
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock
from urllib.parse import urlsplit

SCRIPTS = Path(__file__).resolve().parents[1] / "oil-studio/scripts"
sys.path.insert(0, str(SCRIPTS))

import record_playbook as playbook
import record_playbook_browser as stage_browser

CJK = re.compile(r"[\u3400-\u9fff]")


def make_book(source=None, browser=None):
    book = {
        "source": {"title": "Example"} if source is None else source,
        "beats": [{
            "id": "intro",
            "subtitle": "演示",
            "actions": [{"action": "open", "url": "https://example.com/"}],
        }],
    }
    if browser is not None:
        book["browser"] = browser
    return book


def window(identifier="window-1", title="Example — Documentation", app="Browser"):
    return {"id": identifier, "kind": "window", "app": app, "title": title, "width": 1440, "height": 900}


def run_playbook_cli(*arguments, language):
    environment = os.environ.copy()
    environment["OILSTUDIO_LANGUAGE"] = language
    return subprocess.run([sys.executable, str(SCRIPTS / "record_playbook.py"), *arguments],
        capture_output=True, text=True, env=environment)


class SourceMatchingTests(unittest.TestCase):
    def test_source_id_selects_the_exact_window_without_a_title(self):
        sources = [window(), window("window-10", "Another page")]
        selected = playbook.pick_source(sources, {"sourceId": "window-1"})
        self.assertEqual(selected["id"], "window-1")

    def test_source_id_does_not_partially_match_or_discard_other_conditions(self):
        with self.assertRaises(playbook.PlaybookError):
            playbook.pick_source([window()], {"sourceId": "window"})
        with self.assertRaises(playbook.PlaybookError):
            playbook.pick_source([window()], {"sourceId": "window-1", "app": "Other"})

    def test_title_is_a_case_insensitive_substring_by_default(self):
        selected = playbook.pick_source([window(), window("window-2", "Other")], {"title": "example"})
        self.assertEqual(selected["id"], "window-1")
        with self.assertRaises(playbook.PlaybookError):
            playbook.pick_source([window()], {"title": "example", "exactTitle": True})

    def test_missing_title_input_uses_the_actual_page_title(self):
        source = {"sourceId": "window-1"}
        title = playbook.actual_page_title({"pageTitle": "Actual demonstration"}, source)
        match = playbook.source_match_for_page(source, title)
        self.assertEqual(match, {"sourceId": "window-1", "title": "Actual demonstration", "exactTitle": True})
        selected = playbook.pick_source([window(title="Actual demonstration"), window("window-2")], match)
        self.assertEqual(selected["title"], "Actual demonstration")

    def test_actual_page_title_must_satisfy_the_title_substring(self):
        with self.assertRaises(playbook.PlaybookError):
            playbook.actual_page_title({"pageTitle": "Unrelated page"}, {"title": "Example"})

    def test_recording_source_match_uses_the_immutable_window_id(self):
        source = window(title="First page")
        match = playbook.recording_source_match(source)
        selected = playbook.pick_source([window(title="Later page")], match)
        self.assertEqual(match, {"sourceId": "window-1"})
        self.assertEqual(selected["title"], "Later page")

    def test_validation_accepts_source_id_without_title(self):
        playbook.validate_playbook(make_book({"sourceId": "window-1"}))

    def test_validation_checks_all_source_fields_even_with_source_id(self):
        for source in ({"sourceId": " "}, {"sourceId": "window-1", "title": None}, {"sourceId": "window-1", "app": 3}):
            with self.subTest(source=source), self.assertRaises(playbook.PlaybookError):
                playbook.validate_playbook(make_book(source))


class StageSourceValidationTests(unittest.TestCase):
    def test_stage_window_source_id_conflict_is_rejected_in_both_languages(self):
        book = make_book({"sourceId": "old-window"}, {"host": "stage-window"})
        for language, expected in (("en", "source.sourceId can’t be used"),
                ("zh-Hans", "不能指定 source.sourceId")):
            with self.subTest(language=language), mock.patch.dict(os.environ, {"OILSTUDIO_LANGUAGE": language}):
                with self.assertRaises(playbook.PlaybookError) as raised:
                    playbook.validate_playbook(book)
                self.assertEqual(str(raised.exception), stage_browser.message("stageSourceIdConflict"))
                self.assertIn(expected, str(raised.exception))

    def test_stage_window_source_id_conflict_never_starts_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "conflict.json"
            path.write_text(json.dumps(make_book({"sourceId": "old-window"}, {"host": "stage-window"})), encoding="utf-8")
            stdout, stderr = io.StringIO(), io.StringIO()
            with mock.patch.object(playbook.StageWindowHost, "start") as start, \
                    mock.patch.object(sys, "argv", ["record_playbook.py", "--playbook", str(path)]), \
                    mock.patch.dict(os.environ, {"OILSTUDIO_LANGUAGE": "en"}), \
                    contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = playbook.main()
                expected = stage_browser.message("stageSourceIdConflict")
        self.assertEqual(result, 1)
        start.assert_not_called()
        report = json.loads(stderr.getvalue())
        self.assertEqual(set(report), {"ok", "playbook", "phases", "error"})
        self.assertEqual(report["error"], expected)


class RecordingSafetyTests(unittest.TestCase):
    def test_report_rejects_existing_symlink_and_project_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root / "existing.json"
            existing.write_text("original")
            link = root / "link.json"
            link.symlink_to(root / "missing.json")
            package = root / "test.oilstudio"
            package.mkdir()
            alias = root / "alias"
            alias.symlink_to(package, target_is_directory=True)
            book = root / "playbook.json"
            book.write_text(json.dumps(make_book()))
            for path in (existing, link, package / "report.json", alias / "report.json"):
                with self.subTest(path=path), self.assertRaises(playbook.PlaybookError):
                    playbook.write_report(path, {"ok": True})
                stderr = io.StringIO()
                with self.subTest(argument=path), \
                        mock.patch.object(sys, "argv", ["record_playbook.py", "--playbook", str(book),
                            "--dry-run", "--out-report", str(path)]), \
                        contextlib.redirect_stderr(stderr):
                    self.assertEqual(playbook.main(), 1)
                    self.assertFalse(json.loads(stderr.getvalue())["ok"])
            self.assertEqual(existing.read_text(), "original")
            self.assertFalse((package / "report.json").exists())

    def test_interrupt_during_actions_discards_recording_and_closes_stage(self):
        for interruption in ("keyboard", "sigterm"):
            with self.subTest(interruption=interruption):
                self.assert_interruption_cleanup(interruption)

    def test_rejected_record_start_does_not_discard_foreign_recording(self):
        for browser in ({"host": "stage-window"}, {"host": "stage-window", "preflightSeconds": 0.1}):
            for failure in (playbook.PlaybookError("RECORDER_BUSY"), KeyboardInterrupt()):
              with self.subTest(browser=browser, failure=type(failure).__name__), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "playbook.json"
                path.write_text(json.dumps(make_book(browser=browser)))
                host = mock.Mock()
                def run_command(cli, *arguments, **options):
                    if arguments == ("record", "sources"):
                        return {"sources": [window(title="Example — Documentation")]}
                    if arguments[:2] == ("record", "start"):
                        raise failure
                    return {}
                state = {"pageUrl": "https://example.com", "pageTitle": "Example — Documentation",
                    "pageLabel": "stage-window", "activeTabMatchesPage": True}
                with mock.patch.object(sys, "argv", ["record_playbook.py", "--playbook", str(path)]), \
                        mock.patch.object(playbook, "run_cli", side_effect=run_command) as cli, \
                        mock.patch.object(playbook.shutil, "which", return_value="/fake/tool"), \
                        mock.patch.object(playbook.StageWindowHost, "start", return_value=host), \
                        mock.patch.object(playbook, "browser_call", return_value=state), \
                        contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(playbook.main(), 1)
                self.assertFalse(any(call.args[1:] == ("record", "stop", "--discard") for call in cli.call_args_list))
                host.close.assert_called_once()

    def assert_interruption_cleanup(self, interruption):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "playbook.json"
            path.write_text(json.dumps(make_book(browser={"host": "stage-window"})))
            host = mock.Mock()
            def run_command(cli, *arguments, **options):
                if arguments == ("record", "sources"):
                    return {"sources": [window(title="Example — Documentation")]}
                if arguments == ("record", "status"):
                    if interruption == "sigterm":
                        signal.raise_signal(signal.SIGTERM)
                    raise KeyboardInterrupt()
                return {}
            state = {"pageUrl": "https://example.com", "pageTitle": "Example — Documentation",
                "pageLabel": "stage-window", "activeTabMatchesPage": True}
            with mock.patch.object(sys, "argv", ["record_playbook.py", "--playbook", str(path)]), \
                    mock.patch.object(playbook, "run_cli", side_effect=run_command) as cli, \
                    mock.patch.object(playbook.shutil, "which", return_value="/fake/tool"), \
                    mock.patch.object(playbook.StageWindowHost, "start", return_value=host), \
                    mock.patch.object(playbook, "browser_call", return_value=state), \
                    mock.patch.object(playbook, "inject_hud"), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(playbook.main(), 1)
            cli.assert_any_call("oilstudio", "record", "stop", "--discard", timeout=180)
            host.close.assert_called_once()

    def test_interrupt_during_stage_start_terminates_process(self):
        with tempfile.TemporaryDirectory() as directory:
            process = mock.Mock()
            process.stdout = mock.Mock()
            process.poll.return_value = None
            compiled = mock.Mock(returncode=0)
            with mock.patch.object(stage_browser.subprocess, "run", return_value=compiled), \
                    mock.patch.object(stage_browser.subprocess, "Popen", return_value=process), \
                    mock.patch.object(stage_browser.StageWindowHost, "_finish_start", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    stage_browser.StageWindowHost.start("https://example.com", Path(directory))
            process.terminate.assert_called_once()
            process.wait.assert_called_once()

    def test_browser_url_normalization_preserves_destination(self):
        for actual, expected, matches in [
            ("https://example.com", "https://example.com/", True),
            ("https://EXAMPLE.com/", "http://example.com", True),
            ("http://example.com/", "https://example.com/", False),
            ("https://other.com/", "https://example.com/", False),
            ("https://example.com/other", "https://example.com/", False),
            ("https://example.com/?x=2", "https://example.com/?x=1", False),
        ]:
            with self.subTest(actual=actual, expected=expected):
                self.assertEqual(stage_browser.comparable_urls_match(actual, expected), matches)

    def test_main_binds_recording_status_to_the_selected_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "playbook.json"
            path.write_text(json.dumps(make_book(browser={"host": "stage-window"})), encoding="utf-8")
            host = mock.Mock()
            calls = []
            status_count = 0

            def run_command(cli, *arguments, **options):
                nonlocal status_count
                calls.append((cli, arguments, options))
                if cli != "custom-oilstudio":
                    raise AssertionError(f"unexpected CLI executable: {cli}")
                if arguments == ("record", "sources"):
                    return {"sources": [window(title="Example — Documentation")]}
                if arguments == ("record", "status"):
                    status_count += 1
                    return {"state": "recording", "durationSourceMs": status_count * 100}
                if arguments == ("record", "stop"):
                    return {"stoppedBy": "agent", "path": "/tmp/playbook.oilstudio", "durationMs": 100}
                if arguments[:2] in (("record", "start"), ("settings", "apply"), ("subtitles", "apply")):
                    return {"autoApplied": True}
                raise AssertionError(f"unexpected CLI command: {arguments}")

            browser_state = {"pageUrl": "https://example.com/", "pageTitle": "Example — Documentation",
                "pageLabel": "stage-window", "activeTabMatchesPage": True,
                "metrics": {"innerWidth": 1920, "innerHeight": 1080, "outerWidth": 1920, "outerHeight": 1080}}
            stdout, stderr = io.StringIO(), io.StringIO()
            with mock.patch.object(sys, "argv", ["record_playbook.py", "--playbook", str(path), "--cli", "custom-oilstudio"]), \
                    mock.patch.object(playbook, "run_cli", side_effect=run_command), \
                    mock.patch.object(playbook.shutil, "which", return_value="/fake/tool"), \
                    mock.patch.object(playbook.StageWindowHost, "start", return_value=host), \
                    mock.patch.object(playbook, "browser_call", return_value=browser_state), \
                    mock.patch.object(playbook, "inject_hud"), \
                    contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = playbook.main()

        self.assertEqual(result, 0, stderr.getvalue())
        self.assertTrue(json.loads(stdout.getvalue())["ok"])
        status_calls = [call for call in calls if call[1] == ("record", "status")]
        self.assertGreaterEqual(len(status_calls), 4)
        self.assertTrue(all(call[0] == "custom-oilstudio" for call in calls))
        host.close.assert_called_once()

    def test_paused_recording_is_rejected_before_an_action(self):
        with self.assertRaises(playbook.PlaybookError):
            playbook.active_recording_status(lambda *_: {"state": "paused", "durationSourceMs": 1200})

    def test_preflight_reads_the_project_at_its_editor_owned_path(self):
        project = Path("/tmp/recorded.oilstudio")
        result = {"path": str(project), "openedInEditor": True, "stoppedBy": "agent"}
        self.assertEqual(playbook.preflight_project_path(result), project)

    def test_recorded_auto_zoom_is_replaced_only_when_source_ranges_overlap(self):
        desired = [{"sourceStartMs": 100, "sourceEndMs": 200}]
        self.assertFalse(playbook.recorded_auto_zoom_overlaps(
            {"sourceStartMs": 300, "sourceEndMs": 400}, desired))
        self.assertTrue(playbook.recorded_auto_zoom_overlaps(
            {"sourceStartMs": 150, "sourceEndMs": 300}, desired))

    def test_paused_recording_stops_a_click_before_its_browser_action(self):
        run_cli = mock.Mock()
        ensure_active = mock.Mock(side_effect=[None, None, playbook.PlaybookError("paused")])
        point = {"u": 0.5, "v": 0.5, "viewX": 100, "viewY": 100}
        with mock.patch.object(stage_browser, "action_point", return_value=point), \
                mock.patch.object(stage_browser, "browser_call") as browser_call:
            with self.assertRaises(playbook.PlaybookError):
                stage_browser.run_action("oilstudio", "space", window(), {"id": "intro"}, 0,
                    {"action": "click", "fraction": {"u": 0.5, "v": 0.5}}, False, run_cli,
                    ensure_recording_active=ensure_active)
        run_cli.assert_called_once_with("oilstudio", "record", "click", "--at-fraction",
            "0.500000,0.500000", "--id", "play-intro-1")
        browser_call.assert_not_called()

    def test_input_action_clicks_field_and_types_progressively(self):
        run_cli = mock.Mock()
        point = {"u": 0.25, "v": 0.75, "viewX": 250, "viewY": 750}
        with mock.patch.object(stage_browser, "selector_point", return_value=point), \
                mock.patch.object(stage_browser, "browser_call") as browser_call, \
                mock.patch.object(stage_browser.time, "sleep"):
            stage_browser.run_action("oilstudio", "space", window(), {"id": "form"}, 1,
                {"action": "input", "selector": "#title", "value": "Oil Studio", "durationMs": 400},
                False, run_cli)
        run_cli.assert_called_once_with("oilstudio", "record", "click", "--at-fraction",
            "0.250000,0.750000", "--id", "play-form-2")
        browser_call.assert_called_once()
        script = browser_call.call_args.args[1]
        self.assertIn("await page.click(data.selector", script)
        self.assertIn("Array.from(String(data.to ?? data.value ?? \"\"))", script)
        self.assertIn("KeyboardEvent(\"keydown\"", script)


class LocalizationTests(unittest.TestCase):
    def test_catalog_is_bilingual_and_every_template_renders(self):
        for key, translations in stage_browser.MESSAGES.items():
            with self.subTest(key=key):
                self.assertEqual(set(translations), {"zh-Hans", "en"})
                fields = [field for _, field, _, _ in string.Formatter().parse(translations["en"]) if field]
                values = {field: "sample" for field in fields}
                for language in ("en", "zh-Hans"):
                    with mock.patch.dict(os.environ, {"OILSTUDIO_LANGUAGE": language}):
                        rendered = stage_browser.message(key, **values)
                    self.assertTrue(rendered)
                    if language == "en":
                        self.assertIsNone(CJK.search(rendered))

    def test_message_keys_exist_and_chinese_only_lives_in_the_catalog(self):
        for path in (SCRIPTS / "record_playbook.py", SCRIPTS / "record_playbook_browser.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            catalog_lines = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "MESSAGES":
                    catalog_lines.update(range(node.lineno, node.end_lineno + 1))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and CJK.search(node.value):
                    self.assertIn(node.lineno, catalog_lines, f"{path}:{node.lineno} has hard-coded Chinese")
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                    continue
                name = node.func.id
                index = 0 if name in {"message", "js_message", "fail"} else 1 if name == "require" else None
                if index is None or len(node.args) <= index:
                    continue
                key = node.args[index]
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    self.assertIn(key.value, stage_browser.MESSAGES, f"{path}:{node.lineno} has no catalog entry")

    def test_language_override_and_system_locale_fallback(self):
        with mock.patch.dict(os.environ, {"OILSTUDIO_LANGUAGE": "zh-CN"}):
            self.assertEqual(stage_browser.selected_language(), "zh-Hans")
        with mock.patch.dict(os.environ, {"OILSTUDIO_LANGUAGE": "en-US"}):
            self.assertEqual(stage_browser.selected_language(), "en")
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(stage_browser.locale, "getlocale", return_value=("zh_CN", "UTF-8")):
            self.assertEqual(stage_browser.selected_language(), "zh-Hans")
        with mock.patch.dict(os.environ, {"LANG": "en_US.UTF-8"}, clear=True):
            self.assertEqual(stage_browser.selected_language(), "en")

    def test_help_is_fully_localized(self):
        english = run_playbook_cli("--help", language="en")
        chinese = run_playbook_cli("--help", language="zh-Hans")
        self.assertEqual(english.returncode, 0, english.stderr)
        self.assertEqual(chinese.returncode, 0, chinese.stderr)
        self.assertIsNone(CJK.search(english.stdout))
        self.assertIn("Record a web demonstration", english.stdout)
        self.assertIn("Show this help and exit", english.stdout)
        self.assertIn("用法：", chinese.stdout)
        self.assertIn("选项：", chinese.stdout)
        self.assertIn("显示此帮助并退出", chinese.stdout)

    def test_argument_errors_are_localized(self):
        english = run_playbook_cli(language="en")
        chinese = run_playbook_cli(language="zh-Hans")
        self.assertEqual(english.returncode, 2)
        self.assertEqual(chinese.returncode, 2)
        self.assertIn("The following arguments are required: --playbook", english.stderr)
        self.assertIsNone(CJK.search(english.stderr))
        self.assertIn("缺少必需参数：--playbook", chinese.stderr)
        self.assertIn("用法：", chinese.stderr)

    def test_browser_and_preflight_errors_follow_the_selected_language(self):
        metrics = {"outerWidth": 100, "innerWidth": 100, "outerHeight": 100, "innerHeight": 100}
        for language in ("en", "zh-Hans"):
            with self.subTest(language=language), mock.patch.dict(os.environ, {"OILSTUDIO_LANGUAGE": language}):
                with self.assertRaises(ValueError) as browser_error:
                    stage_browser.to_window_point(metrics, {}, x=200, y=50)
                self.assertEqual(str(browser_error.exception), stage_browser.message("targetOutsideWindow"))
                with self.assertRaises(playbook.PlaybookError) as preflight_error:
                    playbook.require(False, "preflightOCRMissing")
                self.assertEqual(str(preflight_error.exception), stage_browser.message("preflightOCRMissing"))


class PreflightAndScratchTests(unittest.TestCase):
    def test_preflight_accepts_generic_configured_text(self):
        recognized = "A generic demonstration\nwith 4,200 items"
        self.assertEqual(playbook.preflight_ocr_matches(recognized, []), [])
        self.assertEqual(playbook.preflight_ocr_matches(recognized, ["generic demo", "4,200"]), [True, True])
        self.assertEqual(playbook.preflight_ocr_matches(recognized, ["missing"]), [False])

    def test_preflight_configuration_is_not_tied_to_a_page(self):
        playbook.validate_playbook(make_book(browser={"preflightSeconds": 1, "preflightContains": ["Any text", "42"]}))
        playbook.validate_playbook(make_book(browser={"preflightSeconds": 1}))
        with self.assertRaises(playbook.PlaybookError):
            playbook.validate_playbook(make_book(browser={"preflightContains": ["Any text"]}))
        with self.assertRaises(playbook.PlaybookError):
            playbook.validate_playbook(make_book(browser={"preflightSeconds": 1, "preflightContains": [""]}))

    def test_preflight_frame_time_stays_inside_the_actual_take(self):
        cases = ((0, 0), (0.0009, 0), (0.001, 0), (0.01, 9), (0.1, 99), (0.499, 498),
            (0.5, 499), (0.501, 500), (1, 500), (10, 500))
        for seconds, expected in cases:
            with self.subTest(seconds=seconds):
                frame_ms = playbook.preflight_frame_source_ms(seconds)
                self.assertEqual(frame_ms, expected)
                self.assertGreaterEqual(frame_ms, 0)
                if seconds >= 0.001:
                    self.assertLess(frame_ms, int(seconds * 1000))

    def test_scratch_directories_are_unique_under_the_configured_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            first = playbook.make_scratch_directory(directory)
            second = playbook.make_scratch_directory(directory)
            self.assertNotEqual(first, second)
            self.assertEqual(first.parent, Path(directory))
            self.assertEqual(second.parent, Path(directory))
            self.assertTrue(first.is_dir())
            self.assertTrue(second.is_dir())


class StageClientTests(unittest.TestCase):
    def test_python_client_sends_authorization_and_json_without_origin(self):
        host = object.__new__(stage_browser.StageWindowHost)
        host.base_url = "http://127.0.0.1:43210"
        host.token = "test-session-token"
        with mock.patch("urllib.request.urlopen", return_value=io.BytesIO(b'{"ok":true,"result":{}}')) as request:
            host._request("POST", "/evaluate", {"script": "return true;"})
        outgoing = request.call_args.args[0]
        headers = {name.lower(): value for name, value in outgoing.header_items()}
        self.assertEqual(headers["authorization"], "Bearer test-session-token")
        self.assertEqual(headers["content-type"], "application/json")
        self.assertNotIn("origin", headers)

    def test_node_client_gets_the_token_from_its_environment(self):
        completed = subprocess.CompletedProcess(["node"], 0, stdout="true\n", stderr="")
        with mock.patch.object(stage_browser, "_STAGE_BRIDGE_URL", "http://127.0.0.1:43210"), \
                mock.patch.object(stage_browser, "_STAGE_BRIDGE_TOKEN", "test-session-token"), \
                mock.patch.object(stage_browser.subprocess, "run", return_value=completed) as run:
            self.assertTrue(stage_browser.browser_call(None, "return true;"))
        environment = run.call_args.kwargs["env"]
        source = run.call_args.args[0][2]
        self.assertEqual(environment["OILSTUDIO_PLAYBOOK_STAGE_TOKEN"], "test-session-token")
        self.assertNotIn("test-session-token", source)
        self.assertIn("process.env.OILSTUDIO_PLAYBOOK_STAGE_TOKEN", source)


class StagePageHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"<!doctype html><title>Stage integration page</title><main>Local test page</main>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


@unittest.skipUnless(os.environ.get("OILSTUDIO_RUN_STAGE_TESTS") == "1",
    "set OILSTUDIO_RUN_STAGE_TESTS=1 to enable Swift stage integration tests")
class StageHTTPIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sys.platform != "darwin" or shutil.which("swiftc") is None:
            raise unittest.SkipTest("The stage integration test requires macOS and swiftc")
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), StagePageHandler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/demo"
        cls.scratch = tempfile.TemporaryDirectory(prefix="oil-studio-stage-test-")
        try:
            cls.host = stage_browser.StageWindowHost.start(cls.url, Path(cls.scratch.name) / "stage")
        except Exception:
            cls.server.shutdown()
            cls.server.server_close()
            cls.server_thread.join()
            cls.scratch.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "host"):
            cls.host.close()
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join()
        cls.scratch.cleanup()

    def raw_request(self, request):
        address = urlsplit(self.host.base_url)
        with socket.create_connection((address.hostname, address.port), timeout=10) as connection:
            connection.sendall(request.encode("utf-8"))
            chunks = []
            while True:
                chunk = connection.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
        response = b"".join(chunks)
        status = int(response.split(b" ", 2)[1])
        return status, response

    def authorized(self, method="GET", path="/state", content_type=None, body="", extra=""):
        headers = f"Authorization: Bearer {self.host.token}\r\n"
        if content_type:
            headers += f"Content-Type: {content_type}\r\n"
        headers += f"Content-Length: {len(body.encode('utf-8'))}\r\n{extra}"
        return f"{method} {path} HTTP/1.1\r\nHost: 127.0.0.1\r\n{headers}\r\n{body}"

    def test_only_the_session_token_authorizes_requests(self):
        self.assertGreaterEqual(len(self.host.token), 32)
        self.assertNotIn(self.host.token, self.host.process.args)
        missing = "GET /state HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n"
        wrong = "GET /state HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer wrong\r\n\r\n"
        self.assertEqual(self.raw_request(missing)[0], 401)
        self.assertEqual(self.raw_request(wrong)[0], 401)
        status, response = self.raw_request(self.authorized())
        self.assertEqual(status, 200)
        self.assertNotIn(b"access-control-allow-origin", response.lower())
        state = self.host._request("GET", "/state")
        self.assertEqual(state["title"], "Stage integration page")

    def test_origin_method_and_content_type_are_enforced(self):
        cases = [
            (self.authorized(extra="Origin: https://example.com\r\n"), 403),
            (self.authorized(method="POST", content_type="application/json", body="{}"), 405),
            (self.authorized(method="POST", path="/evaluate", content_type="text/plain", body="{}"), 415),
            (self.authorized(method="POST", path="/evaluate", body="{}"), 415),
        ]
        for request, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(self.raw_request(request)[0], expected)

    def test_invalid_content_lengths_and_json_return_errors_without_crashing(self):
        cases = [("-1", 400), ("abc", 400), ("+1", 400), ("1.5", 400), ("900001", 413)]
        for length, expected in cases:
            with self.subTest(length=length):
                request = ("POST /evaluate HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                    f"Authorization: Bearer {self.host.token}\r\nContent-Type: application/json\r\n"
                    f"Content-Length: {length}\r\n\r\n")
                self.assertEqual(self.raw_request(request)[0], expected)
                self.assertEqual(self.raw_request(self.authorized())[0], 200)
        malformed = self.authorized(method="POST", path="/evaluate", content_type="application/json", body="not json")
        self.assertEqual(self.raw_request(malformed)[0], 400)

    def test_node_bridge_reads_the_page_through_the_authenticated_stage(self):
        if shutil.which("node") is None:
            self.skipTest("The Node bridge test requires node")
        state = stage_browser.browser_call(None, "return { title: await page.title(), url: await page.url() };")
        self.assertEqual(state["title"], "Stage integration page")
        self.assertEqual(state["url"], self.url)

    def test_authorized_json_evaluation_still_works(self):
        body = json.dumps({"script": "return 40 + 2;", "mode": "script"})
        status, response = self.raw_request(self.authorized(method="POST", path="/evaluate",
            content_type="application/json; charset=utf-8", body=body))
        self.assertEqual(status, 200)
        payload = json.loads(response.split(b"\r\n\r\n", 1)[1])
        self.assertEqual(payload["result"], 42)


if __name__ == "__main__":
    unittest.main()

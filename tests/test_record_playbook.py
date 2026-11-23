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
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock
from urllib.parse import urlsplit

SCRIPTS = Path(__file__).resolve().parents[1] / "oil-studio/scripts"
sys.path.insert(0, str(SCRIPTS))

import record_playbook as playbook
import record_playbook_bridge as bridge_module
import record_playbook_browser as stage_browser

CJK = re.compile(r"[\u3400-\u9fff]")
_bridge_patch = None


def setUpModule():
    # main() would start a real Node bridge; tests that exercise the bridge itself start it explicitly.
    global _bridge_patch
    _bridge_patch = mock.patch.object(playbook, "open_bridge", return_value=mock.Mock())
    _bridge_patch.start()


def tearDownModule():
    _bridge_patch.stop()


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
        playbook.validate_playbook(make_book({"sourceId": "window-1"}, browser={"cdpURL": "http://127.0.0.1:9222"}))

    def test_source_id_needs_a_host_that_reuses_an_open_window(self):
        # The default isolated stage opens a new window each time, so an existing window id can't apply.
        with self.assertRaises(playbook.PlaybookError):
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


    def test_pointer_actions_send_no_caption_to_the_browser(self):
        # Agent browsers draw a pointer action's label next to their cursor, inside the recorded page.
        point = {"u": 0.5, "v": 0.5, "viewX": 100, "viewY": 100}
        for action in ({"action": "click", "selector": "#a"}, {"action": "move", "selector": "#a"},
                {"action": "click", "fraction": {"u": 0.5, "v": 0.5}}, {"action": "move", "fraction": {"u": 0.5, "v": 0.5}},
                {"action": "input", "selector": "#a", "value": "x"}):
            with self.subTest(action=action), mock.patch.object(stage_browser, "action_point", return_value=point), \
                    mock.patch.object(stage_browser, "browser_call") as browser_call:
                stage_browser.run_action("oilstudio", "space", window(), {"id": "a"}, 0, action, False, mock.Mock())
            for call in browser_call.call_args_list:
                self.assertNotIn("label", call.args[1])

    def test_wheel_declares_the_cursor_then_scrolls_natively_at_that_point(self):
        run_cli = mock.Mock(return_value={"durationSourceMs": 1200})
        point = {"u": 0.4, "v": 0.6, "viewX": 300, "viewY": 420}
        with mock.patch.object(stage_browser, "action_point", return_value=point), \
                mock.patch.object(stage_browser, "browser_call") as browser_call:
            declared = stage_browser.run_action("oilstudio", "space", window(), {"id": "frame"}, 2,
                {"action": "wheel", "fraction": {"u": 0.4, "v": 0.6}, "deltaY": 800, "durationMs": 500}, False, run_cli)
        run_cli.assert_called_once_with("oilstudio", "record", "move", "--at-fraction", "0.400000,0.600000", "--id", "play-frame-3")
        self.assertEqual(declared, {"durationSourceMs": 1200})
        script = browser_call.call_args.args[1]
        self.assertIn('"x": 300', script)
        self.assertIn('"deltaY": 800', script)
        self.assertIn("await page.mouse.move(data.x, data.y)", script)
        self.assertIn("await page.mouse.wheel(", script)

    def test_switch_tab_moves_the_hud_to_the_tab_on_screen(self):
        events = []
        with mock.patch.object(stage_browser, "inject_hud", side_effect=lambda space, hud, page: events.append(("hud", hud))), \
                mock.patch.object(stage_browser, "switch_tab", side_effect=lambda tab: events.append(("switch", tab))):
            stage_browser.run_action("oilstudio", "space", window(), {"id": "admin", "hud": {"title": "Admin"}}, 0,
                {"action": "switchTab", "tab": "admin"}, False, mock.Mock())
        self.assertEqual(events, [("hud", None), ("switch", "admin"), ("hud", {"title": "Admin"})])


class HostAndTabValidationTests(unittest.TestCase):
    def test_host_follows_from_the_playbook(self):
        self.assertEqual(playbook.resolve_host({}), "stage-window")
        self.assertEqual(playbook.resolve_host({"cdpURL": "http://127.0.0.1:9222"}), "cdp")
        self.assertEqual(playbook.resolve_host({"host": "ego-browser"}), "browser")
        self.assertEqual(playbook.resolve_host({"page": "user"}), "browser")
        self.assertEqual(playbook.resolve_host({"host": "stage-window"}), "stage-window")

    def test_real_browsers_get_the_snapshot_check_by_default(self):
        self.assertFalse(playbook.preflight_enabled({}))
        self.assertTrue(playbook.preflight_enabled({"cdpURL": "http://127.0.0.1:9222"}))
        self.assertTrue(playbook.preflight_enabled({"host": "browser"}))
        self.assertFalse(playbook.preflight_enabled({"host": "browser", "preflight": False}))
        self.assertTrue(playbook.preflight_enabled({"preflightSeconds": 1}))
        self.assertTrue(playbook.preflight_enabled({"preflight": True}))

    def test_debugging_address_must_be_local_and_paired_with_the_cdp_host(self):
        for url in ("http://127.0.0.1:9222", "http://localhost:9333/", "http://[::1]:9222"):
            with self.subTest(url=url):
                playbook.validate_playbook(make_book(browser={"cdpURL": url}))
        for browser in ({"cdpURL": "http://192.168.1.2:9222"}, {"cdpURL": "https://127.0.0.1:9222"},
                {"cdpURL": "http://127.0.0.1"}, {"cdpURL": "http://127.0.0.1:9222/json"}, {"host": "cdp"},
                {"host": "stage-window", "cdpURL": "http://127.0.0.1:9222"}, {"host": "firefox"}):
            with self.subTest(browser=browser), self.assertRaises(playbook.PlaybookError):
                playbook.validate_playbook(make_book(browser=browser))

    def test_tabs_need_a_real_browser_and_switches_need_a_declared_tab(self):
        cdp = {"cdpURL": "http://127.0.0.1:9222", "tabs": [{"id": "admin", "url": "https://admin.example.com/"}]}
        book = make_book(browser=cdp)
        book["beats"][0]["actions"] += [{"action": "switchTab", "tab": "admin"}, {"action": "switchTab", "tab": "main"}]
        playbook.validate_playbook(book)
        unknown = json.loads(json.dumps(book)); unknown["beats"][0]["actions"].append({"action": "switchTab", "tab": "billing"})
        stage_tabs = make_book(browser={"tabs": cdp["tabs"]})
        stage_switch = make_book(); stage_switch["beats"][0]["actions"].append({"action": "switchTab", "tab": "main"})
        for invalid in (unknown, stage_tabs, stage_switch,
                make_book(browser={"cdpURL": "http://127.0.0.1:9222", "tabs": [{"id": "main", "url": "https://a.example/"}]}),
                make_book(browser={"cdpURL": "http://127.0.0.1:9222", "tabs": [{"id": "a", "url": "https://a.example/"}, {"id": "a", "url": "https://b.example/"}]}),
                make_book(browser={"cdpURL": "http://127.0.0.1:9222", "tabs": [{"id": "a", "url": "file:///etc/hosts"}]})):
            with self.subTest(invalid=invalid.get("browser")), self.assertRaises(playbook.PlaybookError):
                playbook.validate_playbook(invalid)

    def test_wheel_needs_a_point_and_a_nonzero_delta(self):
        for action, valid in (({"action": "wheel", "selector": "iframe", "deltaY": 600}, True),
                ({"action": "wheel", "fraction": {"u": 0.5, "v": 0.5}, "deltaX": -200, "durationMs": 0}, True),
                ({"action": "wheel", "selector": "iframe"}, False),
                ({"action": "wheel", "selector": "iframe", "deltaY": 0, "deltaX": 0}, False),
                ({"action": "wheel", "deltaY": 300}, False),
                ({"action": "wheel", "selector": "iframe", "deltaY": True}, False)):
            book = make_book(); book["beats"][0]["actions"].append(action)
            with self.subTest(action=action):
                if valid:
                    playbook.validate_playbook(book)
                else:
                    with self.assertRaises(playbook.PlaybookError):
                        playbook.validate_playbook(book)

    def test_a_planned_take_clears_its_whole_span_by_default(self):
        base = {"project": "/tmp/v.oilstudio", "atOutputMs": 1000.4}
        self.assertEqual(playbook.record_start_arguments("window-1", None), ["record", "start", "--source", "window-1"])
        self.assertNotIn("--replace-until-output-ms", playbook.record_start_arguments("w", {**base, "durationMs": 5000}))
        self.assertNotIn("--replace-until-output-ms", playbook.record_start_arguments("w", {**base, "plan": "/tmp/p.json"}))
        planned = playbook.record_start_arguments("w", {**base, "plan": "/tmp/p.json", "durationMs": 5000})
        self.assertEqual(planned[planned.index("--plan") + 1], "/tmp/p.json")
        self.assertEqual(planned[planned.index("--replace-until-output-ms") + 1], "6000")
        explicit = playbook.record_start_arguments("w", {**base, "plan": "/tmp/p.json", "durationMs": 5000, "replaceUntilOutputMs": 9000})
        self.assertEqual(explicit[explicit.index("--replace-until-output-ms") + 1], "9000")

    def test_attach_plan_and_replacement_range(self):
        playbook.validate_playbook(attach_book(attach={"project": "/tmp/v.oilstudio", "atOutputMs": 1000,
            "plan": "/tmp/plan.json", "replaceUntilOutputMs": 5000}))
        for attach in ({"project": "/tmp/v.oilstudio", "atOutputMs": 1000, "plan": ""},
                {"project": "/tmp/v.oilstudio", "atOutputMs": 1000, "replaceUntilOutputMs": 1000}):
            with self.subTest(attach=attach), self.assertRaises(playbook.PlaybookError):
                playbook.validate_playbook(attach_book(attach=attach))


class SnapshotPreflightTests(unittest.TestCase):
    def run_main(self, snapshot_text, browser=None):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "playbook.json"
            path.write_text(json.dumps(make_book(browser=browser or {"cdpURL": "http://127.0.0.1:9222"})), encoding="utf-8")
            calls = []
            def run_command(cli, *arguments, **options):
                calls.append(arguments)
                if arguments == ("record", "sources"):
                    return {"sources": [window(title="Example — Documentation")]}
                if arguments[:2] == ("record", "screenshot"):
                    return {"path": arguments[-1], "text": snapshot_text}
                if arguments == ("record", "status"):
                    return {"state": "recording", "durationSourceMs": 100 * len(calls)}
                if arguments == ("record", "stop"):
                    return {"stoppedBy": "agent", "path": "/tmp/playbook.oilstudio", "durationMs": 100}
                return {"autoApplied": True}
            state = {"pageUrl": "https://example.com/", "pageTitle": "Example — Documentation", "pageLabel": "p1",
                "activeTabMatchesPage": True, "metrics": {"innerWidth": 1440, "innerHeight": 800, "outerWidth": 1440, "outerHeight": 900}}
            stdout, stderr = io.StringIO(), io.StringIO()
            with mock.patch.object(sys, "argv", ["record_playbook.py", "--playbook", str(path)]), \
                    mock.patch.object(playbook, "run_cli", side_effect=run_command), \
                    mock.patch.object(playbook.shutil, "which", return_value="/tool"), \
                    mock.patch.object(playbook.StageWindowHost, "start") as stage, \
                    mock.patch.object(playbook, "browser_call", side_effect=lambda space, body, **k: "https://example.com/" if body == "return await page.url();" else state), \
                    mock.patch.object(playbook, "inject_hud"), mock.patch.object(playbook.time, "sleep"), \
                    contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = playbook.main()
            self.assertEqual(stage.called, playbook.resolve_host(browser or {"cdpURL": "x"}) == "stage-window")
            return result, calls, (stdout.getvalue() or stderr.getvalue())

    def test_automation_overlay_in_the_window_blocks_recording(self):
        overlay = [{"text": "Oil Book", "x": 0.4, "y": 0.9, "width": 0.1, "height": 0.02},
            {"text": "Agent 正在控制", "x": 0.4, "y": 0.93, "width": 0.1, "height": 0.02},
            {"text": "终止任务", "x": 0.55, "y": 0.93, "width": 0.05, "height": 0.02}]
        result, calls, output = self.run_main(overlay)
        self.assertEqual(result, 1)
        snapshot = next(call for call in calls if call[:2] == ("record", "screenshot"))
        self.assertEqual(snapshot[2:5], ("--source", "window-1", "--text"))
        self.assertFalse(any(call[:2] == ("record", "start") for call in calls), "no take, no project for the check")
        report = json.loads(output)
        self.assertEqual(report["preflight"]["ocr"]["forbidden"], ["Agent 正在控制", "终止任务"])

    def test_clean_window_records_and_browser_chrome_text_is_ignored(self):
        # Browser chrome above the viewport is cropped from the video, so its text doesn't block recording.
        text = [{"text": "Translate this page", "x": 0.7, "y": 0.02, "width": 0.2, "height": 0.03},
            {"text": "Example content", "x": 0.2, "y": 0.5, "width": 0.3, "height": 0.03}]
        result, calls, output = self.run_main(text)
        self.assertEqual(result, 0, output)
        self.assertLess(calls.index(next(call for call in calls if call[:2] == ("record", "screenshot"))),
            calls.index(next(call for call in calls if call[:2] == ("record", "start"))))

    def test_the_stage_skips_the_check_unless_asked(self):
        result, calls, output = self.run_main([], browser={"host": "stage-window"})
        self.assertEqual(result, 0, output)
        self.assertFalse(any(call[:2] == ("record", "screenshot") for call in calls))

    def test_forbidden_texts_ignore_case_and_spacing_and_can_be_replaced(self):
        self.assertEqual(playbook.preflight_forbidden("agent正在控制  Stop", playbook.DEFAULT_PREFLIGHT_FORBID), ["Agent 正在控制"])
        self.assertEqual(playbook.preflight_forbidden("Agent 正在控制", []), [])
        playbook.validate_playbook(make_book(browser={"cdpURL": "http://127.0.0.1:9222", "preflightForbid": []}))
        with self.assertRaises(playbook.PlaybookError):
            playbook.validate_playbook(make_book(browser={"cdpURL": "http://127.0.0.1:9222", "preflight": False,
                "preflightForbid": ["x"]}))


class PlaybookRobustnessTests(unittest.TestCase):
    def test_optional_subtitles_and_press_validation(self):
        for subtitle in (None, "", "   ", "Hello"):
            book = make_book()
            if subtitle is None:
                del book["beats"][0]["subtitle"]
            else:
                book["beats"][0]["subtitle"] = subtitle
            book["beats"][0]["actions"].append({"action": "press", "key": "Meta+k", "selector": "#search"})
            playbook.validate_playbook(book)
        for key in ("", "Meta+", "Meta+Bad Key", "Command+k"):
            with self.subTest(key=key), self.assertRaises(playbook.PlaybookError):
                playbook.validate_action("intro", 1, {"action": "press", "key": key})
        with self.assertRaises(playbook.PlaybookError):
            playbook.validate_action("intro", 1, {"action": "press", "key": "Enter", "selector": ""})

    def test_inspect_without_playbook_closes_stage_and_emits_data(self):
        host = mock.Mock()
        value = {"url": "https://example.com", "title": "Example", "viewport": {},
            "scrollContainers": [], "interactiveElements": []}
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["record_playbook.py", "--inspect", value["url"]]), \
                mock.patch.object(playbook.shutil, "which", return_value="/node"), \
                mock.patch.object(playbook.StageWindowHost, "start", return_value=host), \
                mock.patch.object(playbook, "inspect_page", return_value=value), \
                mock.patch.object(playbook, "run_cli") as cli, contextlib.redirect_stdout(out):
            self.assertEqual(playbook.main(), 0)
        self.assertEqual(json.loads(out.getvalue()), value)
        cli.assert_not_called()
        host.close.assert_called_once()

    def test_zoom_mode_contract(self):
        book = make_book()
        for zoom in ({"level": 1.2, "target": {"x": 0.2, "y": 0.8}},
                     {"level": 1.2, "mode": "manual", "selector": "#x"},
                     {"level": 1.2, "mode": "auto"}):
            book["beats"][0]["zoom"] = zoom
            playbook.validate_playbook(book)
        for zoom in ({"level": 1.2, "mode": "auto", "target": {"x": 0.2, "y": 0.8}},
                     {"level": 1.2, "mode": "auto", "selector": "#x"},
                     {"level": 1.2, "mode": "manual"}):
            book["beats"][0]["zoom"] = zoom
            with self.assertRaises(playbook.PlaybookError):
                playbook.validate_playbook(book)

    def test_rehearse_runs_beats_and_zoom_without_cli(self):
        book = make_book(browser={"host": "browser"})
        book["beats"][0]["actions"].append({"action": "press", "key": "Enter"})
        book["beats"][0]["zoom"] = {"level": 1.2, "selector": "#target"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.json"
            path.write_text(json.dumps(book))
            out = io.StringIO(); host = mock.Mock()
            with mock.patch.object(sys, "argv", ["record_playbook.py", "--playbook", str(path), "--rehearse"]), \
                    mock.patch.object(playbook.shutil, "which", return_value="/node"), \
                    mock.patch.object(playbook.StageWindowHost, "start", return_value=host), \
                    mock.patch.object(playbook, "wait_for_render_stability"), \
                    mock.patch.object(playbook, "inject_hud"), \
                    mock.patch.object(playbook, "selector_point", return_value={"u": 0.5, "v": 0.5}) as zoom, \
                    mock.patch.object(playbook, "run_action") as action, \
                    mock.patch.object(playbook, "run_cli") as cli, contextlib.redirect_stdout(out):
                self.assertEqual(playbook.main(), 0)
            self.assertTrue(json.loads(out.getvalue())["rehearsal"][0]["ok"])
            self.assertEqual(action.call_count, 2)
            zoom.assert_called_once()
            cli.assert_not_called()
            host.close.assert_called_once()

    def test_explicit_browser_never_falls_back(self):
        for browser in ({"host": "browser"}, {"host": "ego-browser"}, {"page": "user"}):
            with self.subTest(browser=browser), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "book.json"; path.write_text(json.dumps(make_book(browser=browser)))
                state = {"pageUrl": "https://example.com/", "pageTitle": "Example",
                    "pageLabel": "p1", "activeTabMatchesPage": True}
                with mock.patch.object(sys, "argv", ["record_playbook.py", "--playbook", str(path)]), \
                        mock.patch.object(playbook.shutil, "which", return_value="/tool"), \
                        mock.patch.object(playbook, "browser_call", return_value=state), \
                        mock.patch.object(playbook, "run_cli", return_value={"sources": []}), \
                        mock.patch.object(playbook.StageWindowHost, "start") as start, \
                        contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(playbook.main(), 1)
                start.assert_not_called()

    def test_unspecified_host_uses_the_stage_even_when_an_agent_browser_is_installed(self):
        # An agent browser draws its control bar while it drives the page, so it is never picked implicitly.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.json"; path.write_text(json.dumps(make_book()))
            state = {"pageUrl": "https://example.com/", "pageTitle": "Example",
                "pageLabel": "stage-window", "activeTabMatchesPage": True}
            with mock.patch.object(sys, "argv", ["record_playbook.py", "--playbook", str(path)]), \
                    mock.patch.object(playbook.shutil, "which", return_value="/tool"), \
                    mock.patch.object(playbook.StageWindowHost, "start", return_value=mock.Mock()) as start, \
                    mock.patch.object(playbook, "browser_call", return_value=state), \
                    mock.patch.object(playbook, "run_cli", return_value={"sources": []}), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(playbook.main(), 1)
            start.assert_called_once()

    def test_intents_and_manual_zoom_submit_in_order_without_subtitles(self):
        for enabled, automatic in ((False, False), (True, False), (False, True)):
            with self.subTest(enabled=enabled, automatic=automatic), tempfile.TemporaryDirectory() as directory:
                book = make_book(browser={"host": "stage-window"})
                book["beats"][0]["actions"].extend([{"action": "click", "selector": "#target"},
                    {"action": "move", "selector": "#other"}, {"action": "scroll", "y": 500}])
                book["beats"][0]["zoom"] = ({"level": 1.2, "mode": "auto"} if automatic
                    else {"level": 1.2, "selector": "#target"})
                if enabled:
                    book["settings"] = {"subtitles": {"enabled": True}}
                path = Path(directory) / "book.json"; path.write_text(json.dumps(book))
                calls = []; submitted = []; events = []; tick = 0
                def cli(_cli, *args, **kwargs):
                    nonlocal tick
                    calls.append(args)
                    if args == ("record", "sources"): return {"sources": [window(title="Example")]}
                    if args == ("record", "status"):
                        tick += 1000
                        return {"state": "recording", "durationSourceMs": tick}
                    if args == ("record", "stop"): return {"stoppedBy": "agent", "path": "/tmp/test.oilstudio"}
                    if args[0] == "context":
                        Path(args[-1]).write_text(json.dumps({"projectFingerprint": "p", "contextFingerprint": "c",
                            "zooms": [{"id": "auto", "mode": "auto", "origin": "generated", "sourceStartMs": 0, "sourceEndMs": 999999}]}))
                    if args[:2] == ("plan", "validate"):
                        submitted.append(json.loads(Path(args[2]).read_text()))
                    return {"autoApplied": True}
                state = {"pageUrl": "https://example.com/", "pageTitle": "Example", "pageLabel": "stage-window", "activeTabMatchesPage": True}
                with mock.patch.object(sys, "argv", ["record_playbook.py", "--playbook", str(path), "--export", str(Path(directory) / "out.mp4")]), \
                        mock.patch.object(playbook.shutil, "which", return_value="/tool"), \
                        mock.patch.object(playbook.StageWindowHost, "start", return_value=mock.Mock()), \
                        mock.patch.object(playbook, "browser_call", return_value=state), \
                        mock.patch.object(playbook, "inject_hud"), mock.patch.object(playbook, "run_action", side_effect=lambda *a, **k: events.append("action")), \
                        mock.patch.object(playbook, "selector_point", side_effect=lambda *a, **k: events.append("zoom") or {"u": 0.5, "v": 0.5}), \
                        mock.patch.object(playbook, "run_cli", side_effect=cli), mock.patch.object(playbook.time, "sleep"), \
                        contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(playbook.main(), 0)
                if not automatic:
                    self.assertEqual(events[0], "zoom")
                self.assertLess(next(i for i, c in enumerate(calls) if c[0] == "idle"), next(i for i, c in enumerate(calls) if c[0] == "context"))
                self.assertEqual([z["action"] for z in submitted[0]["zooms"]], ["remove", "add"])
                self.assertEqual(submitted[0]["zooms"][1]["mode"], "auto" if automatic else "manual")
                self.assertEqual(any(c[:2] == ("subtitles", "apply") for c in calls), enabled)
                self.assertIn("burn" if enabled else "none", next(c for c in calls if c[0] == "export"))


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
        for path in (SCRIPTS / "record_playbook.py", SCRIPTS / "record_playbook_browser.py", SCRIPTS / "record_playbook_bridge.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            catalog_lines = set()
            for node in ast.walk(tree):
                # DEFAULT_PREFLIGHT_FORBID is OCR match data (texts other software shows), not interface text.
                if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id in ("MESSAGES", "DEFAULT_PREFLIGHT_FORBID"):
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

class FakeStageHandler(BaseHTTPRequestHandler):
    """Answers the stage host's control API so the real Node bridge can be exercised without WebKit."""
    authorizations: list[str] = []

    def reply(self, result):
        body = json.dumps({"ok": True, "result": result}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        type(self).authorizations.append(self.headers.get("Authorization", ""))
        self.reply({"url": "https://example.com/", "title": "Fake stage", "readyState": "complete"})

    def do_POST(self):
        type(self).authorizations.append(self.headers.get("Authorization", ""))
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.reply({"echo": payload.get("argument")} if self.path == "/evaluate" else {})

    def log_message(self, format, *args):
        pass


@unittest.skipUnless(shutil.which("node"), "the bridge test requires node")
class BridgeProtocolTests(unittest.TestCase):
    def setUp(self):
        FakeStageHandler.authorizations = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeStageHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.scratch = tempfile.TemporaryDirectory(prefix="oil-studio-bridge-test-")
        self.bridge = bridge_module.BrowserBridge.start("stage", Path(self.scratch.name),
            stage_url=f"http://127.0.0.1:{self.server.server_port}", stage_token="stage-session-token")
        bridge_module.activate(self.bridge)

    def tearDown(self):
        self.bridge.close()
        self.server.shutdown()
        self.server.server_close()
        self.scratch.cleanup()

    def test_one_process_answers_every_step_without_restarting(self):
        started = time.monotonic()
        for _ in range(20):
            self.assertEqual(stage_browser.browser_call(None, "return await page.title();"), "Fake stage")
        # A cold start per step took about half a second; twenty steps now fit well inside one.
        self.assertLess(time.monotonic() - started, 2.0)
        self.assertEqual(self.bridge.process.poll(), None)
        self.assertEqual(self.bridge.call("return await page.evaluate(x => x, 41);"), {"echo": 41})

    def test_tokens_stay_out_of_process_arguments(self):
        self.bridge.call("return await page.url();")
        self.assertTrue(FakeStageHandler.authorizations)
        self.assertTrue(all(value == "Bearer stage-session-token" for value in FakeStageHandler.authorizations))
        arguments = " ".join(map(str, self.bridge.process.args))
        self.assertNotIn("stage-session-token", arguments)
        self.assertEqual(self.bridge.process.args, ["node", "--input-type=module"])

    def test_page_errors_are_reported_and_the_bridge_keeps_working(self):
        with self.assertRaisesRegex(ValueError, "boom"):
            self.bridge.call("throw new Error('boom');")
        with self.assertRaises(ValueError):
            self.bridge.switch_tab("missing")
        with self.assertRaises(ValueError):
            self.bridge.open_tab("admin", "https://example.com/admin")
        self.assertEqual(self.bridge.call("return 1 + 1;"), 2)

    def test_a_slow_step_times_out_and_its_late_reply_is_skipped(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            self.bridge.call("await new Promise(r => setTimeout(r, 1500)); return 'late';", timeout=0.3)
        self.assertEqual(self.bridge.call("return 'next';", timeout=10), "next")

    def test_the_bridge_exits_when_the_script_disappears(self):
        # A killed playbook never sends close; the bridge must not linger holding browser connections.
        process = self.bridge.process
        self.bridge.connection.close()
        process.wait(timeout=5)
        self.assertIsNotNone(process.poll())

    def test_close_ends_the_process_and_detaches(self):
        process = self.bridge.process
        self.bridge.close()
        self.assertIsNotNone(process.poll())
        with self.assertRaises(ValueError):
            stage_browser.browser_call(None, "return 1;")

    def test_a_ready_line_in_the_same_packet_as_the_hello_is_kept(self):
        listener = socket.create_server(("127.0.0.1", 0))
        process = mock.Mock(poll=mock.Mock(return_value=None))
        client = socket.create_connection(listener.getsockname())
        client.sendall(b'{"hello": "token"}\n{"ready": true}\n')
        accepted, pending = bridge_module.BrowserBridge._accept(listener, process, Path(self.scratch.name) / "none.log", "token")
        try:
            bridge = bridge_module.BrowserBridge("stage", process, accepted, Path(self.scratch.name) / "none.log")
            bridge._buffer = pending
            self.assertEqual(bridge._read(time.monotonic() + 1, 1), {"ready": True})
        finally:
            for item in (accepted, client, listener):
                item.close()

    def test_only_the_bridge_with_the_token_is_accepted(self):
        listener = socket.create_server(("127.0.0.1", 0))
        process = mock.Mock(poll=mock.Mock(return_value=None))
        impostor = socket.create_connection(listener.getsockname())
        impostor.sendall(b'{"hello": "guess"}\n')
        genuine = socket.create_connection(listener.getsockname())
        genuine.sendall(b'{"hello": "real-token"}\n')
        accepted, _ = bridge_module.BrowserBridge._accept(listener, process, Path(self.scratch.name) / "none.log", "real-token")
        try:
            self.assertEqual(accepted.getpeername(), genuine.getsockname())
        finally:
            for item in (accepted, impostor, genuine, listener):
                item.close()


def attach_book(at_ms=None, attach=None):
    book = make_book(browser={"host": "stage-window"})
    book["attach"] = {"project": "/tmp/voice-over.oilstudio", "atOutputMs": 138000} if attach is None else attach
    click = {"action": "click", "fraction": {"u": 0.5, "v": 0.5}}
    if at_ms is not None:
        click["atMs"] = at_ms
    book["beats"][0]["actions"].append(click)
    book["beats"][0]["zoom"] = {"level": 2, "mode": "auto"}
    return book


class AttachModeTests(unittest.TestCase):
    def test_validation_accepts_attach_with_timed_actions(self):
        playbook.validate_playbook(attach_book(at_ms=3200,
            attach={"project": "/tmp/voice-over.oilstudio", "atOutputMs": 0, "durationMs": 9000}))

    def test_validation_rejects_malformed_attach(self):
        for attach in ({"project": "/tmp/voice-over.oilstudio"},
                {"project": "/tmp/clip.mp4", "atOutputMs": 10},
                {"project": "/tmp/voice-over.oilstudio", "atOutputMs": -1},
                {"project": "/tmp/voice-over.oilstudio", "atOutputMs": True},
                {"project": "/tmp/voice-over.oilstudio", "atOutputMs": 0, "durationMs": 0}):
            with self.subTest(attach=attach), self.assertRaises(playbook.PlaybookError):
                playbook.validate_playbook(attach_book(attach=attach))

    def test_timed_actions_need_attach_and_cannot_time_the_opening_page(self):
        book = attach_book(at_ms=100)
        del book["attach"]
        with self.assertRaises(playbook.PlaybookError):
            playbook.validate_playbook(book)
        book = attach_book()
        book["beats"][0]["actions"][0]["atMs"] = 0
        with self.assertRaises(playbook.PlaybookError):
            playbook.validate_playbook(book)

    def simulated_recorder(self, launch_ms=120.0, reply_ms=30.0):
        """A take that began at local time 0; each CLI call reaches the App `launch_ms` after it starts."""
        local = {"ms": 0.0}

        def status():
            reading = local["ms"] + launch_ms
            local["ms"] += launch_ms + reply_ms
            return {"durationSourceMs": reading}

        def sleep(seconds):
            self.assertGreaterEqual(seconds, 0)
            local["ms"] += seconds * 1000
        return local, status, sleep

    def test_wait_ends_so_the_next_command_reaches_the_app_on_time(self):
        local, status, sleep = self.simulated_recorder()
        with mock.patch.object(playbook.time, "sleep", side_effect=sleep) as sleeps:
            playbook.wait_until_recorded_ms(7000, status, now=lambda: local["ms"] / 1000)
        # The click command started now arrives one launch delay later.
        self.assertAlmostEqual(local["ms"] + 120, 7000, delta=40)
        self.assertGreater(sleeps.call_count, 1, "a distant target re-reads the recorder clock")
        self.assertTrue(all(call.args[0] <= 5 for call in sleeps.call_args_list))

    def test_wait_returns_at_once_when_the_moment_has_passed(self):
        local, status, sleep = self.simulated_recorder()
        local["ms"] = 9000
        with mock.patch.object(playbook.time, "sleep", side_effect=sleep) as sleeps:
            result = playbook.wait_until_recorded_ms(3000, status, now=lambda: local["ms"] / 1000)
        self.assertEqual(result["durationSourceMs"], 9120)
        sleeps.assert_not_called()

    def test_a_due_pointer_action_declares_without_extra_recorder_checks(self):
        cli_calls = []

        def run_cli(cli, *arguments):
            cli_calls.append(arguments)
            return {"durationSourceMs": 2998}
        point = {"u": 0.25, "v": 0.5, "viewX": 480, "viewY": 540}
        checks = mock.Mock()
        with mock.patch.object(stage_browser, "browser_call") as browser, \
                mock.patch.object(stage_browser, "action_point") as measure:
            declared = stage_browser.run_action("cli", None, {}, {"id": "b"}, 0,
                {"action": "click", "fraction": {"u": 0.25, "v": 0.5}, "atMs": 3000}, False, run_cli,
                ensure_recording_active=checks, point=point)
        self.assertEqual(declared, {"durationSourceMs": 2998})
        self.assertEqual(cli_calls, [("record", "click", "--at-fraction", "0.250000,0.500000", "--id", "play-b-1")])
        checks.assert_not_called(); measure.assert_not_called()
        self.assertIn("page.mouse.click(480, 540", browser.call_args.args[1])

    def test_main_records_into_the_voice_over_and_offsets_zooms_to_the_clip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "playbook.json"
            path.write_text(json.dumps(attach_book(at_ms=500,
                attach={"project": "/tmp/voice-over.oilstudio", "atOutputMs": 138000.4, "durationMs": 900})),
                encoding="utf-8")
            book = json.loads(path.read_text(encoding="utf-8"))
            book["attach"].update({"plan": "/tmp/draft-plan.json", "replaceUntilOutputMs": 141000})
            path.write_text(json.dumps(book), encoding="utf-8")
            calls, plans = [], []
            clock = 0

            def run_command(cli, *arguments, **options):
                nonlocal clock
                calls.append(arguments)
                if arguments == ("record", "sources"):
                    return {"sources": [window(title="Example — Documentation")]}
                if arguments == ("record", "status"):
                    clock += 100
                    return {"state": "recording", "durationSourceMs": clock}
                if arguments == ("record", "stop"):
                    return {"stoppedBy": "agent", "path": "/tmp/voice-over.oilstudio", "durationMs": clock,
                        "screenClip": {"id": "clip-1", "sessionIndex": 3, "sourceStartMs": 500000,
                            "sourceEndMs": 500000 + clock, "outputStartMs": 138000, "outputEndMs": 138000 + clock}}
                if arguments[0] == "context":
                    Path(arguments[arguments.index("--out") + 1]).write_text(json.dumps(
                        {"projectFingerprint": "p", "contextFingerprint": "c", "zooms": []}), encoding="utf-8")
                    return {"ok": True}
                if arguments[:2] in (("plan", "validate"), ("plan", "submit")):
                    plans.append(json.loads(Path(arguments[2]).read_text(encoding="utf-8")))
                    return {"autoApplied": True}
                if arguments[:2] == ("settings", "apply"):
                    settings.append(json.loads(Path(arguments[3]).read_text(encoding="utf-8")))
                    return {"autoApplied": True}
                if arguments[:2] == ("record", "start"):
                    return {"state": "recording", "plan": {"stale": True, "atOutputMs": 151000}}
                if arguments[:2] == ("record", "click"):
                    return {"autoApplied": True}
                raise AssertionError(f"unexpected CLI command: {arguments}")

            settings = []
            browser_state = {"pageUrl": "https://example.com/", "pageTitle": "Example — Documentation",
                "pageLabel": "stage-window", "activeTabMatchesPage": True,
                "metrics": {"innerWidth": 1920, "innerHeight": 1080, "outerWidth": 1920, "outerHeight": 1080}}
            stdout, stderr = io.StringIO(), io.StringIO()
            with mock.patch.object(sys, "argv", ["record_playbook.py", "--playbook", str(path)]), \
                    mock.patch.object(playbook, "run_cli", side_effect=run_command), \
                    mock.patch.object(playbook, "run_action",
                        side_effect=lambda *args, **kwargs: calls.append(("action", args[5].get("action"), kwargs.get("point")))
                            or {"durationSourceMs": 497}), \
                    mock.patch.object(playbook, "action_point", return_value={"u": 0.5, "v": 0.5, "viewX": 960, "viewY": 540}), \
                    mock.patch.object(playbook, "wait_until_recorded_ms",
                        side_effect=lambda target, status: calls.append(("wait", target)) or status()), \
                    mock.patch.object(playbook.shutil, "which", return_value="/fake/tool"), \
                    mock.patch.object(playbook.StageWindowHost, "start", return_value=mock.Mock()), \
                    mock.patch.object(playbook, "browser_call", return_value=browser_state), \
                    mock.patch.object(stage_browser, "browser_call", return_value=browser_state), \
                    mock.patch.object(playbook, "inject_hud"), \
                    mock.patch.object(playbook.time, "sleep"), mock.patch.object(stage_browser.time, "sleep"), \
                    contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = playbook.main()

        self.assertEqual(result, 0, stderr.getvalue())
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["screenClip"]["id"], "clip-1")
        start = next(call for call in calls if call[:2] == ("record", "start"))
        self.assertEqual(start[start.index("--into") + 1], "/tmp/voice-over.oilstudio")
        self.assertEqual(start[start.index("--at-output-ms") + 1], "138000")
        self.assertEqual(start[start.index("--plan") + 1], "/tmp/draft-plan.json")
        self.assertEqual(start[start.index("--replace-until-output-ms") + 1], "141000")
        self.assertEqual(report["planProjection"], {"stale": True, "atOutputMs": 151000})
        self.assertFalse(any(call[0] in ("idle", "subtitles", "chapters", "export") for call in calls))
        click_index = next(i for i, call in enumerate(calls) if call[:2] == ("action", "click"))
        last_wait = max(i for i, call in enumerate(calls[:click_index]) if call[0] == "wait")
        self.assertEqual(calls[last_wait], ("wait", 500))
        self.assertTrue(all(call == ("record", "status") for call in calls[last_wait + 1:click_index]),
            "only the wait's own clock read separates it from the timed click")
        self.assertIsNotNone(calls[click_index][2], "the click target is measured before the wait")
        self.assertIn(("wait", 900), calls[:calls.index(("record", "stop"))])
        self.assertEqual(report["timedActions"], [{"beat": "intro", "actionIndex": 1, "atMs": 500, "declaredMs": 497}])
        zoom = plans[-1]["zooms"][0]
        self.assertGreaterEqual(zoom["sourceStartMs"], 500000)
        self.assertGreater(zoom["sourceEndMs"], zoom["sourceStartMs"])
        self.assertTrue(settings)
        self.assertTrue(all("transitions" not in item["settings"] for item in settings))

    def test_attach_refuses_export(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "playbook.json"
            path.write_text(json.dumps(attach_book()), encoding="utf-8")
            stdout, stderr = io.StringIO(), io.StringIO()
            with mock.patch.object(sys, "argv", ["record_playbook.py", "--playbook", str(path),
                    "--export", str(Path(directory) / "out.mp4")]), \
                    mock.patch.object(playbook, "run_cli") as cli, \
                    mock.patch.object(playbook.shutil, "which", return_value="/fake/tool"), \
                    contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = playbook.main()
        self.assertEqual(result, 1)
        cli.assert_not_called()


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
            cls.bridge = bridge_module.BrowserBridge.start("stage", Path(cls.scratch.name) / "bridge",
                stage_url=cls.host.base_url, stage_token=cls.host.token)
            bridge_module.activate(cls.bridge)
        except Exception:
            if hasattr(cls, "host"):
                cls.host.close()
            cls.server.shutdown()
            cls.server.server_close()
            cls.server_thread.join()
            cls.scratch.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "bridge"):
            cls.bridge.close()
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

    def test_inspect_pointer_input_press_and_nested_scroll(self):
        stage_browser.browser_call(None, '''return await page.evaluate(() => {
  document.body.innerHTML = `<div id="scroller" style="height:300px;overflow:auto">
    <div style="height:700px"><button id="button" style="position:sticky;top:0">Press me</button>
    <svg width="80" height="80"><rect id="shape" x="10" y="10" width="50" height="50"/></svg>
    <div id="edit" contenteditable="true">old</div><form id="form"><input id="search" type="search"></form></div></div>`;
  document.body.style.overflow = "hidden";
  window.events = []; window.submitted = 0;
  document.querySelector("#shape").addEventListener("pointerdown", e => window.events.push({x:e.clientX,y:e.clientY,id:e.pointerId,primary:e.isPrimary,kind:e.constructor.name}));
  document.querySelector("#shape").addEventListener("click", () => window.events.push("click"));
  document.querySelector("#form").addEventListener("submit", e => {e.preventDefault();window.submitted++});
  return true;
});''')
        data = stage_browser.inspect_page()
        self.assertTrue(any(x["selector"] == "#scroller" for x in data["scrollContainers"]))
        self.assertTrue(any(x["selector"] == "#button" and x["fixedOrSticky"] for x in data["interactiveElements"]))
        self.host._request("POST", "/selector", {"selector": "#shape", "action": "click"})
        events = stage_browser.browser_call(None, 'return await page.evaluate(() => window.events);')
        self.assertEqual(events[0]["kind"], "PointerEvent")
        self.assertEqual((events[0]["id"], events[0]["primary"]), (1, True))
        self.assertGreater(events[0]["x"], 0)
        self.assertEqual(events[1], "click")
        self.host._request("POST", "/point", {"x": events[0]["x"], "y": events[0]["y"], "action": "click"})
        events = stage_browser.browser_call(None, 'return await page.evaluate(() => window.events);')
        self.assertEqual((events[2]["kind"], events[2]["id"], events[2]["primary"]), ("PointerEvent", 1, True))
        self.assertEqual(events[3], "click")
        source = {"width": 1920, "height": 1080}
        stage_browser.run_action("unused", None, source, {"id": "form"}, 0,
            {"action": "input", "selector": "#edit", "value": "new", "durationMs": 0}, False, lambda *a: {})
        stage_browser.run_action("unused", None, source, {"id": "form"}, 1,
            {"action": "press", "selector": "#search", "key": "Enter"}, False, lambda *a: {})
        state = stage_browser.browser_call(None, '''return await page.evaluate(() => ({text:document.querySelector("#edit").textContent, submitted:window.submitted}));''')
        self.assertEqual(state, {"text": "new", "submitted": 1})
        stage_browser.run_action("unused", None, source, {"id": "form"}, 2,
            {"action": "scroll", "y": 200, "durationMs": 0}, False, lambda *a: {})
        scroll_top = stage_browser.browser_call(None, 'return await page.evaluate(() => document.querySelector("#scroller").scrollTop);')
        self.assertGreater(scroll_top, 0)
        stage_browser.selector_point(None, "#button", source)
        self.assertEqual(stage_browser.browser_call(None, 'return await page.evaluate(() => document.querySelector("#scroller").scrollTop);'), scroll_top)

    def test_wheel_scrolls_the_container_under_the_pointer(self):
        stage_browser.browser_call(None, '''return await page.evaluate(() => {
  document.body.innerHTML = `<div id="pane" style="position:absolute;left:100px;top:100px;width:400px;height:300px;overflow:auto">
    <div style="height:2000px">tall</div></div>`;
  return true;
});''')
        source = {"width": 1920, "height": 1080}
        stage_browser.run_action("unused", None, source, {"id": "pane"}, 0,
            {"action": "wheel", "fraction": {"u": 300 / 1920, "v": 250 / 1080}, "deltaY": 600, "durationMs": 200},
            False, lambda *a, **k: {})
        top = stage_browser.browser_call(None, 'return await page.evaluate(() => document.querySelector("#pane").scrollTop);')
        self.assertGreater(top, 0)

    def test_async_evaluation_timeout_reports_failure(self):
        with self.assertRaisesRegex(ValueError, "timeout"):
            self.host._request("POST", "/evaluate", {"script": "return await new Promise(resolve => setTimeout(() => resolve(1), 12000));", "mode": "script"})

    def test_selector_timeout_reports_failure(self):
        stage_browser.browser_call(None, '''return await page.evaluate(() => {
  window.originalQuerySelector = document.querySelector;
  document.querySelector = () => { const until = Date.now() + 7000; while (Date.now() < until) {} return null; };
  return true;
});''')
        try:
            with self.assertRaisesRegex(ValueError, "timeout"):
                self.host._request("POST", "/selector", {"selector": "#slow", "action": "click"})
        finally:
            stage_browser.browser_call(None, 'return await page.evaluate(() => { document.querySelector = window.originalQuerySelector; return true; });')

    def test_authorized_json_evaluation_still_works(self):
        body = json.dumps({"script": "return 40 + 2;", "mode": "script"})
        status, response = self.raw_request(self.authorized(method="POST", path="/evaluate",
            content_type="application/json; charset=utf-8", body=body))
        self.assertEqual(status, 200)
        payload = json.loads(response.split(b"\r\n\r\n", 1)[1])
        self.assertEqual(payload["result"], 42)


class PageServerHandler(BaseHTTPRequestHandler):
    pages: dict[str, str] = {}

    def do_GET(self):
        body = type(self).pages.get(self.path.split("?")[0], "<title>Missing</title>").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


@unittest.skipUnless(os.environ.get("OILSTUDIO_RUN_CDP_TESTS") == "1" and Path(CHROME).exists() and shutil.which("node"),
    "set OILSTUDIO_RUN_CDP_TESTS=1 (needs Google Chrome and node) to drive a real browser over the debugging port")
class CDPHostIntegrationTests(unittest.TestCase):
    """A throwaway headless Chrome profile; nothing of the user's browser is touched."""

    @classmethod
    def setUpClass(cls):
        cls.servers = []
        for _ in range(2):  # two ports, two origins: the frame is cross-origin to the page
            server = ThreadingHTTPServer(("127.0.0.1", 0), PageServerHandler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            cls.servers.append(server)
        page_origin, frame_origin = (f"http://127.0.0.1:{server.server_port}" for server in cls.servers)
        PageServerHandler.pages = {
            "/demo": f"""<!doctype html><title>CDP demo</title><body style="margin:0">
<button id="go" style="position:absolute;left:40px;top:40px;width:120px;height:40px">Go</button>
<iframe id="frame" src="{frame_origin}/frame" style="position:absolute;left:40px;top:120px;width:500px;height:300px;border:0"></iframe>
<script>window.clicks = []; window.frameScroll = 0;
document.querySelector('#go').addEventListener('click', e => window.clicks.push(e.isTrusted));
addEventListener('message', e => {{ window.frameScroll = e.data; }});</script></body>""",
            "/frame": """<!doctype html><title>Frame</title><body style="margin:0"><div style="height:3000px">tall</div>
<script>addEventListener('scroll', () => parent.postMessage(scrollY, '*'));</script></body>""",
            "/admin": "<!doctype html><title>Admin tab</title><body>admin</body>",
        }
        cls.page_url, cls.admin_url = f"{page_origin}/demo", f"{page_origin}/admin"
        cls.scratch = tempfile.TemporaryDirectory(prefix="oil-studio-cdp-test-")
        profile = Path(cls.scratch.name) / "profile"
        cls.chrome = subprocess.Popen([CHROME, "--headless=new", "--remote-debugging-port=0", f"--user-data-dir={profile}",
            "--no-first-run", "--no-default-browser-check", "--window-size=1280,800", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        port_file = profile / "DevToolsActivePort"
        deadline = time.monotonic() + 30
        while not port_file.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        port = port_file.read_text().split()[0]
        cls.bridge = bridge_module.BrowserBridge.start("cdp", Path(cls.scratch.name) / "bridge",
            cdp_url=f"http://127.0.0.1:{port}", first_url=cls.page_url)
        bridge_module.activate(cls.bridge)
        stage_browser.browser_call(None, "await page.waitForLoadState(); return true;")

    @classmethod
    def tearDownClass(cls):
        cls.bridge.close()
        cls.chrome.terminate()
        cls.chrome.wait(timeout=10)
        for server in cls.servers:
            server.shutdown()
            server.server_close()
        cls.scratch.cleanup()

    def test_opening_page_title_and_trusted_click(self):
        self.assertEqual(stage_browser.browser_call(None, "return await page.title();"), "CDP demo")
        stage_browser.browser_call(None, 'await page.click("#go"); return true;')
        self.assertEqual(stage_browser.browser_call(None, "return await page.evaluate(() => window.clicks);"), [True])

    def test_wheel_scrolls_a_cross_origin_frame(self):
        point = stage_browser.selector_point(None, "#frame", {"width": 1280, "height": 800})
        stage_browser.run_action("unused", None, {"width": 1280, "height": 800}, {"id": "frame"}, 0,
            {"action": "wheel", "fraction": {"u": point["u"], "v": point["v"]}, "deltaY": 900, "durationMs": 300},
            False, lambda *a, **k: {})
        deadline = time.monotonic() + 5
        scrolled = 0
        while time.monotonic() < deadline and not scrolled:
            scrolled = stage_browser.browser_call(None, "return await page.evaluate(() => window.frameScroll);")
            time.sleep(0.1)
        self.assertGreater(scrolled, 0)

    def test_prepared_tabs_switch_without_reloading(self):
        self.bridge.open_tab("admin", self.admin_url)
        self.bridge.switch_tab("admin")
        self.assertEqual(stage_browser.browser_call(None, "return await page.title();"), "Admin tab")
        self.bridge.switch_tab("main")
        self.assertEqual(stage_browser.browser_call(None, "return await page.title();"), "CDP demo")
        tabs = stage_browser.browser_call(None, "return await task.tabs();")
        self.assertEqual([tab["title"] for tab in tabs if tab["active"]], ["CDP demo"])


if __name__ == "__main__":
    unittest.main()

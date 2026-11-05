#!/usr/bin/env python3
"""Record a browser demonstration from a JSON playbook."""

from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import argparse
import json
import math
import re
import shutil
import signal
import subprocess
import tempfile
import time
import threading
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

from record_playbook_browser import StageWindowHost, action_point, browser_call, comparable_urls_match, inject_hud, message, page_metrics, run_action, selector_point, to_window_point


class PlaybookError(Exception):
    pass


ACTIONS = {"open", "click", "move", "scroll", "input", "eval", "wait", "mark"}
POSITIONS = {"top-right", "bottom-left", "top-left"}


def fail(message_key: str, **values: Any) -> None:
    raise PlaybookError(message(message_key, **values))


def require(condition: bool, message_key: str, **values: Any) -> None:
    if not condition:
        fail(message_key, **values)


def error_text(error: Exception) -> str:
    if isinstance(error, PlaybookError):
        return str(error)
    if isinstance(error, subprocess.TimeoutExpired):
        command = error.cmd if isinstance(error.cmd, str) else " ".join(map(str, error.cmd))
        return message("commandTimeout", command=command, timeout=error.timeout)
    if isinstance(error, json.JSONDecodeError):
        return message("runtimeJSONError", line=error.lineno, column=error.colno)
    if isinstance(error, KeyError):
        return message("missingDataField", field=error.args[0] if error.args else "")
    if isinstance(error, TypeError):
        return message("runtimeTypeError")
    if isinstance(error, OSError):
        return message("osOperationFailed", detail=error.strerror or error.filename or type(error).__name__)
    if isinstance(error, ValueError):
        return str(error)
    return message("unexpectedError", detail=str(error))


def load_playbook(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        fail("readPlaybookOS", path=path)
    except json.JSONDecodeError as exc:
        fail("readPlaybookJSON", line=exc.lineno, column=exc.colno)
    require(isinstance(value, dict), "topLevelObject")
    validate_playbook(value)
    return value


def validate_playbook(book: dict[str, Any]) -> None:
    source = book.get("source")
    require(isinstance(source, dict), "sourceObject")
    for key in ("sourceId", "app", "title"):
        if key in source:
            require(isinstance(source[key], str) and bool(source[key].strip()), "sourceFieldNonempty", key=key)
    require(any(source.get(key) for key in ("sourceId", "app", "title")), "sourceRequired")
    require("exactTitle" not in source or isinstance(source["exactTitle"], bool), "exactTitleBoolean")
    browser = book.get("browser")
    require(browser is None or isinstance(browser, dict), "browserObject")
    if browser is not None:
        require(browser.get("host") in (None, "browser", "stage-window", "ego-browser"), "browserHost")
        require(not (browser.get("host") == "stage-window" and "sourceId" in source), "stageSourceIdConflict")
        space = browser.get("space", browser.get("spaceId"))
        require(space is None or isinstance(space, (str, int)) and not isinstance(space, bool), "browserSpaceType")
        page_ref = browser.get("page", "p1")
        require(isinstance(page_ref, str) and (page_ref == "user" or re.fullmatch(r"p[1-9][0-9]*", page_ref)),
            "browserPageFormat")
        require(isinstance(browser.get("cropBrowserChrome", True), bool), "cropBrowserChromeBoolean")
        preflight_seconds = browser.get("preflightSeconds", 0)
        require(isinstance(preflight_seconds, (int, float)) and math.isfinite(preflight_seconds)
            and 0 <= preflight_seconds <= 10, "preflightSecondsRange")
        preflight_contains = browser.get("preflightContains", [])
        require(isinstance(preflight_contains, list) and all(isinstance(text, str) and bool(text.strip())
            for text in preflight_contains), "preflightContainsArray")
        require(not preflight_contains or preflight_seconds > 0, "preflightContainsNeedsSeconds")
        require(browser.get("scratchDir") is None or isinstance(browser.get("scratchDir"), str)
            and bool(browser["scratchDir"].strip()), "scratchDirectoryNonempty")
    settings = book.get("settings")
    require(settings is None or isinstance(settings, dict) and bool(settings), "settingsObject")
    beats = book.get("beats")
    require(isinstance(beats, list) and bool(beats), "beatsNonempty")
    ids: set[str] = set()
    first_open: Optional[tuple[int, int]] = None
    for beat_index, beat in enumerate(beats):
        require(isinstance(beat, dict), "beatObject", index=beat_index)
        identifier = beat.get("id")
        require(isinstance(identifier, str) and identifier.strip(), "beatIdNonempty", index=beat_index)
        require(identifier not in ids, "duplicateBeatId", identifier=identifier)
        ids.add(identifier)
        require(isinstance(beat.get("subtitle"), str) and beat["subtitle"].strip(), "subtitleRequired", identifier=identifier)
        actions = beat.get("actions", [])
        require(isinstance(actions, list), "beatActionsArray", identifier=identifier)
        for action_index, action in enumerate(actions):
            validate_action(identifier, action_index, action)
            if action.get("action", action.get("type")) == "open" and first_open is None:
                first_open = (beat_index, action_index)
        hud = beat.get("hud")
        if hud is not None:
            require(isinstance(hud, dict), "beatHudObject", identifier=identifier)
            require(hud.get("position", "top-right") in POSITIONS, "hudPositionInvalid", identifier=identifier)
            for key in ("badge", "title", "detail"):
                require(key not in hud or isinstance(hud[key], str), "hudFieldString", identifier=identifier, key=key)
            pills = hud.get("pills", [])
            require(isinstance(pills, list), "hudPillsArray", identifier=identifier)
            for pill in pills:
                require(isinstance(pill, dict) and isinstance(pill.get("label"), str)
                    and isinstance(pill.get("value"), str), "hudPillFields", identifier=identifier)
                color = pill.get("color")
                require(color is None or isinstance(color, str) and re.fullmatch(r"(?:#[0-9a-fA-F]{3}|#[0-9a-fA-F]{4}|#[0-9a-fA-F]{6}|#[0-9a-fA-F]{8})", color),
                    "hudPillColor")
        zoom = beat.get("zoom")
        if zoom is not None:
            require(isinstance(zoom, dict), "beatZoomObject", identifier=identifier)
            level = zoom.get("level")
            require(isinstance(level, (int, float)) and math.isfinite(level) and 1 <= level <= 3,
                "zoomLevelRange", identifier=identifier)
            require((isinstance(zoom.get("selector"), str) and bool(zoom["selector"].strip()))
                != (isinstance(zoom.get("target"), dict)), "zoomSelectorTarget", identifier=identifier)
            if "target" in zoom:
                target = zoom["target"]
                require(all(isinstance(target.get(axis), (int, float)) and math.isfinite(target[axis])
                    and 0 <= target[axis] <= 1 for axis in ("x", "y")), "zoomTargetRange", identifier=identifier)
            require(zoom.get("transition", "smooth") in ("smooth", "instant"), "zoomTransitionInvalid", identifier=identifier)
    require(first_open == (0, 0), "firstOpenRequired")


def validate_action(beat_id: str, index: int, action: Any) -> None:
    prefix = message("actionPrefix", beat_id=beat_id, index=index)
    require(isinstance(action, dict), "actionObject", prefix=prefix)
    kind = action.get("action", action.get("type"))
    require(kind in ACTIONS, "actionUnsupported", prefix=prefix)
    if kind == "open":
        require(isinstance(action.get("url"), str) and action["url"].startswith(("https://", "http://")),
            "actionOpenURL", prefix=prefix)
    elif kind in ("click", "move"):
        selector = action.get("selector")
        fraction = action.get("fraction")
        require((isinstance(selector, str) and bool(selector.strip())) != (isinstance(fraction, dict)),
            "actionSelectorFraction", prefix=prefix)
        if fraction is not None:
            require(all(isinstance(fraction.get(axis), (int, float)) and math.isfinite(fraction[axis])
                and 0 <= fraction[axis] <= 1 for axis in ("u", "v")), "actionFractionRange", prefix=prefix)
    elif kind == "scroll":
        require(("y" in action) != ("selector" in action), "actionScrollTarget", prefix=prefix)
        require("y" not in action or isinstance(action["y"], (int, float)) and math.isfinite(action["y"]),
            "actionFiniteY", prefix=prefix)
        require("selector" not in action or isinstance(action["selector"], str) and bool(action["selector"].strip()),
            "actionSelectorNonempty", prefix=prefix)
        require(isinstance(action.get("durationMs", 600), (int, float)) and math.isfinite(action.get("durationMs", 600)) and action.get("durationMs", 600) >= 0,
            "actionDurationNonnegative", prefix=prefix)
    elif kind == "input":
        require(isinstance(action.get("selector"), str) and bool(action["selector"].strip()),
            "actionInputSelector", prefix=prefix)
        require("value" in action or "to" in action, "actionInputValue", prefix=prefix)
        require(("from" in action) == ("to" in action), "actionFromToPair", prefix=prefix)
        if "to" in action:
            require(all(isinstance(action[key], (int, float)) and math.isfinite(action[key]) for key in ("from", "to")),
                "actionFromToFinite", prefix=prefix)
        if "durationMs" in action:
            require(isinstance(action["durationMs"], (int, float)) and math.isfinite(action["durationMs"]) and action["durationMs"] >= 0,
                "actionDurationNonnegative", prefix=prefix)
    elif kind == "eval":
        require(isinstance(action.get("script"), str) and bool(action["script"].strip()), "actionEvalScript", prefix=prefix)
    elif kind == "wait":
        require(isinstance(action.get("ms"), (int, float)) and math.isfinite(action["ms"]) and action["ms"] >= 0,
            "actionWaitNonnegative", prefix=prefix)


def run_json(command: list[str], timeout: float = 300) -> dict[str, Any]:
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    try:
        value = json.loads(lines[-1]) if lines else {}
    except json.JSONDecodeError as exc:
        fail("commandNoJSON", command=" ".join(command), line=exc.lineno, column=exc.colno, output=result.stdout[-1000:])
    if result.returncode != 0 or value.get("ok") is False:
        fail("commandFailed", command=" ".join(command), result=json.dumps(value, ensure_ascii=False))
    return value


def run_cli(cli: str, *args: str, timeout: float = 300) -> dict[str, Any]:
    return run_json([cli, *map(str, args)], timeout=timeout)


def bind_cli(cli: str, command_runner: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    def run(*args: str, **options: Any) -> dict[str, Any]:
        return command_runner(cli, *args, **options)
    return run


def matches_title(actual_title: Any, match: dict[str, Any]) -> bool:
    if not isinstance(actual_title, str):
        return False
    expected = match.get("title")
    if expected is None:
        return True
    if match.get("exactTitle", False):
        return actual_title == expected
    return expected.casefold() in actual_title.casefold()


def matches_source(item: dict[str, Any], match: dict[str, Any]) -> bool:
    return (("sourceId" not in match or item.get("id") == match["sourceId"])
        and ("app" not in match or str(item.get("app") or "").casefold() == match["app"].casefold())
        and matches_title(str(item.get("title") or ""), match))


def pick_source(sources: list[dict[str, Any]], match: dict[str, Any]) -> dict[str, Any]:
    selected = [item for item in sources if matches_source(item, match)]
    require(len(selected) == 1, "sourceMatchCount", count=len(selected))
    require(selected[0].get("kind") == "window", "sourceWindowOnly")
    require(selected[0].get("width", 0) > 0 and selected[0].get("height", 0) > 0, "sourceDimensions")
    return selected[0]


def actual_page_title(browser_state: dict[str, Any], source_match: dict[str, Any]) -> str:
    title = browser_state.get("pageTitle")
    require(isinstance(title, str) and bool(title.strip()), "pageTitleMissing")
    require(matches_title(title, source_match), "pageTitleMismatch")
    return title


def source_match_for_page(source_match: dict[str, Any], page_title: str) -> dict[str, Any]:
    return {**source_match, "title": page_title, "exactTitle": True}


def recording_source_match(source: dict[str, Any]) -> dict[str, Any]:
    return {"sourceId": source["id"]}


def active_recording_status(run_cli) -> dict[str, Any]:
    status = run_cli("record", "status")
    require(status.get("state") == "recording", "recordingNotActive", state=status.get("state", "unknown"))
    return status


def preflight_project_path(stop_result: dict[str, Any]) -> Path:
    project = stop_result.get("path")
    require(isinstance(project, str) and project.endswith(".oilstudio"), "preflightProjectMissing")
    return Path(project)


def recorded_auto_zoom_overlaps(existing: dict[str, Any], desired_zooms: list[dict[str, Any]]) -> bool:
    return any(max(existing["sourceStartMs"], desired["sourceStartMs"])
        < min(existing["sourceEndMs"], desired["sourceEndMs"]) for desired in desired_zooms)


def make_scratch_directory(configured_parent: Optional[str]) -> Path:
    parent = Path(configured_parent).expanduser() if configured_parent else None
    if parent is not None:
        parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="oil-studio-playbook-", dir=str(parent) if parent else None))


def preflight_ocr_matches(recognized: str, expected_texts: list[str]) -> list[bool]:
    compact = re.sub(r"\s+", "", recognized.casefold())
    return [re.sub(r"\s+", "", text.casefold()) in compact for text in expected_texts]


def preflight_frame_source_ms(seconds: float) -> int:
    duration_ms = max(0, int(seconds * 1000))
    return min(500, max(0, duration_ms - 1))


def ocr_text(frame: dict[str, Any]) -> str:
    value = frame.get("text", [])
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        return ""
    parts = []
    for item in value:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            text = item.get("text") or item.get("value")
            if isinstance(text, str):
                parts.append(text)
    return " ".join(parts)


class PlaybookArgumentParser(argparse.ArgumentParser):
    def format_help(self) -> str:
        return self._localized_format(super().format_help())

    def format_usage(self) -> str:
        return self._localized_format(super().format_usage())

    def _localized_format(self, text: str) -> str:
        text = re.sub(r"^usage:", message("usagePrefix"), text, count=1, flags=re.MULTILINE)
        return re.sub(r"^(?:options|optional arguments):$", message("optionsHeading"), text, flags=re.MULTILINE)

    def error(self, detail: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: {message('argumentError')}: {self._localized_error(detail)}\n")

    def _localized_error(self, detail: str) -> str:
        patterns = (
            (r"the following arguments are required: (.+)", "requiredArguments"),
            (r"unrecognized arguments: (.+)", "unrecognizedArguments"),
        )
        for pattern, key in patterns:
            match = re.fullmatch(pattern, detail)
            if match:
                return message(key, arguments=match.group(1))
        match = re.fullmatch(r"argument (.+): expected one argument", detail)
        if match:
            return message("expectedArgumentValue", argument=match.group(1))
        match = re.fullmatch(r"argument (.+): ignored explicit argument '([^']*)'", detail)
        if match:
            return message("ignoredExplicitArgument", argument=match.group(1), value=match.group(2))
        return message("invalidArguments", detail=detail)


def main() -> int:
    parser = PlaybookArgumentParser(description=message("cliDescription"), add_help=False, allow_abbrev=False)
    parser.add_argument("-h", "--help", action="help", help=message("helpHelp"))
    parser.add_argument("--playbook", required=True, type=Path, help=message("helpPlaybook"))
    parser.add_argument("--out-report", type=Path, help=message("helpOutReport"))
    parser.add_argument("--export", type=Path, help=message("helpExport"))
    parser.add_argument("--dry-run", action="store_true", help=message("helpDryRun"))
    parser.add_argument("--preflight-only", action="store_true", help=message("helpPreflightOnly"))
    parser.add_argument("--cli", default="oilstudio", help=argparse.SUPPRESS)
    args = parser.parse_args()
    recording_cli = bind_cli(args.cli, run_cli)
    report: dict[str, Any] = {"ok": False, "playbook": str(args.playbook), "phases": []}
    stage_host: Optional[StageWindowHost] = None
    report_path_valid = False
    previous_sigterm = None
    try:
        if threading.current_thread() is threading.main_thread():
            previous_sigterm = signal.getsignal(signal.SIGTERM)
            signal.signal(signal.SIGTERM, lambda signum, frame: (_ for _ in ()).throw(KeyboardInterrupt(message("interrupted"))))
        validate_report_path(args.out_report)
        report_path_valid = True
        book = load_playbook(args.playbook.expanduser())
        report["beats"] = len(book["beats"])
        report["actions"] = sum(len(beat.get("actions", [])) for beat in book["beats"])
        if args.dry_run:
            report.update({"ok": True, "dryRun": True, "zoomBeats": [beat["id"] for beat in book["beats"] if beat.get("zoom")],
                "subtitleCues": len(book["beats"]), "export": str(args.export) if args.export else None})
            write_report(args.out_report, report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
        require(shutil.which(args.cli) is not None, "cliNotFound", command=args.cli)
        require(shutil.which("node") is not None, "nodeUnavailable")
        if book.get("browser", {}).get("host") != "stage-window":
            require(shutil.which("ego-browser") is not None, "browserAutomationUnavailable")
        require(args.export is None or args.export.suffix.lower() == ".mp4", "exportExtension")
        require(args.export is None or not args.export.expanduser().exists(), "exportExists")
        first_url = book["beats"][0]["actions"][0]["url"]
        browser_cfg = book.get("browser", {})
        requested_host = browser_cfg.get("host")
        if requested_host == "ego-browser":
            requested_host = "browser"
        space = browser_cfg.get("space", browser_cfg.get("spaceId"))
        if requested_host == "stage-window":
            space = None
        elif space is None:
            space = f"Web Demo {uuid.uuid4()}"
        page_ref = browser_cfg.get("page", "p1")
        scratch = make_scratch_directory(browser_cfg.get("scratchDir"))
        if requested_host == "stage-window":
            stage_host = StageWindowHost.start(first_url, scratch / "stage-host")
            browser_state = browser_call(space, '''const metrics = await page.evaluate(() => ({ innerWidth, innerHeight, outerWidth, outerHeight }));
const tabs = await task.tabs();
return { pageTitle: await page.title(), pageUrl: await page.url(), pageLabel: page.label,
  activeTabMatchesPage: tabs.some(tab => tab.active && tab.targetId === page.targetId), metrics };''', timeout=120, page_ref=page_ref)
        else:
            browser_state = browser_call(space, f'''await page.goto({json.dumps(first_url)});
await page.waitForLoadState("domcontentloaded");
const metrics = await page.evaluate(() => ({{ innerWidth, innerHeight, outerWidth, outerHeight }}));
const tabs = await task.tabs();
return {{ pageTitle: await page.title(), pageUrl: await page.url(), pageLabel: page.label,
  activeTabMatchesPage: tabs.some(tab => tab.active && tab.targetId === page.targetId), metrics }};''', timeout=120, page_ref=page_ref)
        require(comparable_urls_match(browser_state.get("pageUrl"), first_url), "pageURLMismatch")
        page_title = actual_page_title(browser_state, book["source"])
        if stage_host is not None:
            require(browser_state.get("activeTabMatchesPage"), "stagePageUnavailable")
        report["browser"] = {"host": "stage-window" if stage_host else "browser", "page": browser_state.get("pageLabel"),
            "url": first_url, "title": page_title, "activeTab": browser_state.get("activeTabMatchesPage", False)}
        report["phases"].append("browserPrepared")

        source_match = source_match_for_page(book["source"], page_title)
        sources_result = run_cli(args.cli, "record", "sources")
        try:
            source = pick_source(sources_result.get("sources", []), source_match)
            require(source.get("title") == page_title and browser_state.get("activeTabMatchesPage"), "nativeTitleMismatch")
        except (PlaybookError, ValueError):
            if stage_host is not None or requested_host == "stage-window" or "sourceId" in book["source"]:
                raise
            stage_host = StageWindowHost.start(first_url, scratch / "stage-host")
            browser_state = browser_call(None, '''const metrics = await page.evaluate(() => ({ innerWidth, innerHeight, outerWidth, outerHeight }));
const tabs = await task.tabs();
return { pageTitle: await page.title(), pageUrl: await page.url(), pageLabel: page.label,
  activeTabMatchesPage: tabs.some(tab => tab.active && tab.targetId === page.targetId), metrics };''', timeout=120)
            require(comparable_urls_match(browser_state.get("pageUrl"), first_url) and browser_state.get("activeTabMatchesPage"),
                "stageURLStateMismatch")
            page_title = actual_page_title(browser_state, book["source"])
            source_match = {"title": page_title, "exactTitle": True}
            source = pick_source(run_cli(args.cli, "record", "sources").get("sources", []), source_match)
            require(source.get("title") == page_title, "stageNativeTitleMismatch")
            report["browser"] = {"host": "stage-window", "page": browser_state.get("pageLabel"),
                "url": first_url, "title": page_title, "activeTab": True, "fallback": "native-title-mismatch"}
        report["source"] = {key: source.get(key) for key in ("id", "app", "title", "width", "height")}
        source_match = recording_source_match(source)
        report["phases"].append("nativeWindowTitleMatched")

        settings = book.setdefault("settings", {})
        transitions = settings.setdefault("transitions", {})
        if isinstance(transitions, dict):
            transitions.setdefault("style", "dissolve")
            transitions.setdefault("spanMs", 250)
        if stage_host is not None:
            style = settings.setdefault("style", {})
            require(isinstance(style, dict), "stageStyleObject")
            style["cropNormalized"] = {"x": 0, "y": 0, "width": 1, "height": 1}
            report["stageWindow"] = {"borderless": True, "contentSize": {"width": 1920, "height": 1080},
                "nonActivating": True, "systemMouse": False, "chrome": False}
            report["browserChromeCrop"] = style["cropNormalized"]
        elif browser_cfg.get("cropBrowserChrome", True):
            metrics = browser_state["metrics"]
            require(metrics["outerHeight"] > 0 and 0 < metrics["innerHeight"] <= metrics["outerHeight"],
                "browserViewportInvalid")
            chrome_y = max(0.0, (metrics["outerHeight"] - metrics["innerHeight"]) / metrics["outerHeight"])
            require(chrome_y < 1, "browserCropInvalid")
            style = settings.setdefault("style", {})
            require(isinstance(style, dict), "browserStyleObject")
            style["cropNormalized"] = {"x": 0, "y": chrome_y, "width": 1, "height": 1 - chrome_y}
            report["browserChromeCrop"] = style["cropNormalized"]

        preflight_seconds = float(browser_cfg.get("preflightSeconds", 0))
        require(not args.preflight_only or preflight_seconds > 0, "preflightOnlyNeedsSeconds")
        preflight_contains = browser_cfg.get("preflightContains", [])
        if preflight_seconds > 0:
            probe_recording = False
            try:
                run_cli(args.cli, "record", "start", "--source", source["id"])
                probe_recording = True
                time.sleep(preflight_seconds)
                probe_stop = run_cli(args.cli, "record", "stop")
                probe_recording = False
            finally:
                if probe_recording:
                    run_cli(args.cli, "record", "stop", "--discard", timeout=180)
            require(probe_stop.get("stoppedBy") == "agent", "recordingStoppedUnexpectedly",
                stopped_by=probe_stop.get("stoppedBy", "unknown"))
            probe_project = preflight_project_path(probe_stop)
            probe_frame = scratch / f"preflight-{uuid.uuid4().hex}.png"
            probe_frame_ms = preflight_frame_source_ms(preflight_seconds)
            frame_result = run_cli(args.cli, "frame", str(probe_project), "--source-ms", str(probe_frame_ms),
                "--text", "--out", str(probe_frame))
            recognized = ocr_text(frame_result)
            ocr_matches = preflight_ocr_matches(recognized, preflight_contains)
            require(all(ocr_matches), "preflightOCRMissing")
            report["preflight"] = {"passed": True, "durationMs": int(preflight_seconds * 1000),
                "ocr": {"contains": preflight_contains, "matches": ocr_matches},
                "project": str(probe_project), "frame": str(probe_frame)}
            report["phases"].append("preflightOcrPassed")
            source = pick_source(run_cli(args.cli, "record", "sources").get("sources", []), source_match)
            require(source.get("title") == page_title, "preflightTitleChanged")
            if args.preflight_only:
                report.update({"ok": True, "preflightOnly": True})
                report["phases"].append("preflightOnlyComplete")
                write_report(args.out_report, report)
                print(json.dumps(report, ensure_ascii=False, indent=2))
                return 0

        run_cli(args.cli, "record", "start", "--source", source["id"])
        recording = True
        report["phases"].append("recording")
        cue_ranges: list[dict[str, Any]] = []
        chapter_rows: list[dict[str, Any]] = []
        zoom_rows: list[dict[str, Any]] = []
        has_recorded_intents = False
        preopened = True
        for beat_index, beat in enumerate(book["beats"]):
            current_source = pick_source(run_cli(args.cli, "record", "sources").get("sources", []), source_match)
            require(current_source.get("id") == source.get("id"), "recordingSourceChanged")
            active_recording_status(recording_cli)
            inject_hud(space, beat.get("hud"), page_ref)
            start = active_recording_status(recording_cli)["durationSourceMs"]
            for index, action in enumerate(beat.get("actions", [])):
                if action.get("action", action.get("type")) in ("click", "move", "input"):
                    has_recorded_intents = True
                active_recording_status(recording_cli)
                run_action(args.cli, space, source, beat, index, action,
                    preopened and beat_index == 0 and index == 0, run_cli, page_ref,
                    ensure_recording_active=lambda: active_recording_status(recording_cli))
                if beat_index == 0 and index == 0:
                    preopened = False
            point = None
            if beat.get("zoom"):
                active_recording_status(recording_cli)
                zoom = beat["zoom"]
                if zoom.get("selector"):
                    active_recording_status(recording_cli)
                    point = selector_point(space, zoom["selector"], source, scroll=False, page_ref=page_ref)
                else:
                    active_recording_status(recording_cli)
                    metrics = page_metrics(space, source, page_ref)
                    target = zoom["target"]
                    point = to_window_point(metrics, source, target["x"] * metrics["innerWidth"], target["y"] * metrics["innerHeight"])
            end = active_recording_status(recording_cli)["durationSourceMs"]
            require(end > start, "beatZeroDuration", identifier=beat["id"])
            cue_ranges.append({"id": beat["id"], "sourceStartMs": start, "sourceEndMs": end, "text": beat["subtitle"]})
            if isinstance(beat.get("chapter"), str) and beat["chapter"].strip():
                chapter_rows.append({"title": beat["chapter"].strip(), "sourceStartMs": 0 if beat_index == 0 else start})
            if point is not None:
                zoom = beat["zoom"]
                zoom_rows.append({"action": "add", "sourceStartMs": start, "sourceEndMs": end,
                    "level": zoom["level"], "mode": "manual", "target": {"x": point["u"], "y": point["v"]},
                    "transition": zoom.get("transition", "smooth"), "reason": beat["subtitle"]})
            active_recording_status(recording_cli)
            inject_hud(space, None, page_ref)
        stop = run_cli(args.cli, "record", "stop")
        recording = False
        require(stop.get("stoppedBy") == "agent", "recordingStoppedUnexpectedly",
            stopped_by=stop.get("stoppedBy", "unknown"))
        project = stop.get("path")
        require(isinstance(project, str) and project.endswith(".oilstudio"), "projectMissing")
        report["project"] = project
        report["recordingDurationMs"] = stop.get("durationMs")
        report["phases"].append("recordingSaved")
        with tempfile.TemporaryDirectory(prefix="oil-studio-playbook-") as temporary:
            temp = Path(temporary)
            pending = False
            if has_recorded_intents and not zoom_rows:
                idle_result = run_cli(args.cli, "idle", project, "--threshold", "1000", "--keep", "350", "--submit", timeout=600)
                report["idleSubmission"] = idle_result
                pending |= idle_result.get("autoApplied") is False and bool(idle_result.get("pauses"))
            if book.get("settings"):
                settings_file = temp / "settings.json"
                settings_file.write_text(json.dumps({"schemaVersion": 1, "settings": book["settings"]}, ensure_ascii=False), encoding="utf-8")
                result = run_cli(args.cli, "settings", "apply", project, str(settings_file))
                report["settings"] = result
                pending |= result.get("autoApplied") is False and result.get("changed", True) is not False
            if zoom_rows:
                context_file = temp / "context.json"
                run_cli(args.cli, "context", project, "--no-pauses", "--out", str(context_file))
                context = json.loads(context_file.read_text(encoding="utf-8"))
                plan_zooms: list[dict[str, Any]] = []
                removed_auto_zoom_ids = []
                for existing in context.get("zooms", []):
                    recorded_auto_overlap = (existing.get("mode") == "auto"
                        and existing.get("origin") == "recorded"
                        and recorded_auto_zoom_overlaps(existing, zoom_rows))
                    if recorded_auto_overlap:
                        plan_zooms.append({"action": "remove", "id": existing["id"],
                            "reason": message("autoZoomRemovalReason")})
                        removed_auto_zoom_ids.append(existing["id"])
                    else:
                        overlap = any(max(0, min(existing["sourceEndMs"], desired["sourceEndMs"])
                            - max(existing["sourceStartMs"], desired["sourceStartMs"])) > 0 for desired in zoom_rows)
                        require(not overlap, "manualZoomOverlap")
                plan_zooms.extend(zoom_rows)
                plan = {"schemaVersion": 1, "projectFingerprint": context["projectFingerprint"],
                    "contextFingerprint": context["contextFingerprint"], "summary": message("zoomPlanSummary"),
                    "decisions": [], "zooms": plan_zooms}
                plan_file = temp / "plan.json"
                plan_file.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
                report["planValidation"] = run_cli(args.cli, "plan", "validate", str(plan_file))
                result = run_cli(args.cli, "plan", "submit", str(plan_file))
                report["planSubmission"] = result
                report["replacedAutoZoomIds"] = removed_auto_zoom_ids
                pending |= result.get("autoApplied") is False
            subtitles_file = temp / "subtitles.json"
            subtitles_file.write_text(json.dumps({"schemaVersion": 1, "cues": cue_ranges}, ensure_ascii=False), encoding="utf-8")
            result = run_cli(args.cli, "subtitles", "apply", project, str(subtitles_file))
            report["subtitleSubmission"] = result
            pending |= result.get("autoApplied") is False
            if chapter_rows:
                chapters_file = temp / "chapters.json"
                chapters_file.write_text(json.dumps({"schemaVersion": 1, "chapters": chapter_rows}, ensure_ascii=False), encoding="utf-8")
                chapter_result = run_cli(args.cli, "chapters", "apply", project, str(chapters_file))
                report["chapterSubmission"] = chapter_result
                pending |= chapter_result.get("autoApplied") is False
            report["cues"] = cue_ranges
            report["zooms"] = plan_zooms if zoom_rows else []
            if args.export:
                if pending:
                    report["export"] = {"skipped": True, "reason": message("exportPendingReason")}
                else:
                    export_path = str(args.export.expanduser())
                    report["export"] = run_cli(args.cli, "export", project, "--out", export_path, "--subtitles", "burn", "--overwrite", timeout=3600)
        keep_label = browser_state.get("pageLabel")
        browser_call(space, f'await page.evaluate(() => document.querySelector("[data-oilstudio-playbook-hud]")?.remove()); await task.finish({{ keep: [{json.dumps(keep_label)}] }}); return true;', page_ref=page_ref)
        report["ok"] = True
        report["phases"].append("complete")
        write_report(args.out_report, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (PlaybookError, subprocess.TimeoutExpired, OSError, KeyError, TypeError, ValueError, KeyboardInterrupt) as exc:
        report["error"] = message("interrupted") if isinstance(exc, KeyboardInterrupt) else error_text(exc)
        if "recording" in locals() and recording:
            try:
                run_cli(args.cli, "record", "stop", "--discard", timeout=180)
                report["recordingDiscarded"] = True
            except Exception as stop_error:  # Preserve the primary failure; a partial take may need app inspection.
                report["stopError"] = error_text(stop_error)
        if "space" in locals():
            try:
                browser_call(space, 'await page.evaluate(() => document.querySelector("[data-oilstudio-playbook-hud]")?.remove()); return true;', page_ref=page_ref)
            except Exception:
                pass
        if report_path_valid:
            try:
                write_report(args.out_report, report)
            except (OSError, PlaybookError):
                pass
        print(json.dumps(report, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    finally:
        try:
            if stage_host is not None:
                stage_host.close()
        finally:
            if previous_sigterm is not None:
                signal.signal(signal.SIGTERM, previous_sigterm)


def validate_report_path(path: Optional[Path]) -> None:
    if path is None:
        return
    destination = path.expanduser()
    resolved = destination.resolve()
    if (destination.is_symlink() or destination.exists()
            or any(part.lower().endswith(".oilstudio") for part in destination.absolute().parts)
            or any(part.lower().endswith(".oilstudio") for part in resolved.parts)):
        fail("unsafeReport", path=destination)


def write_report(path: Optional[Path], report: dict[str, Any]) -> None:
    if path is None:
        return
    validate_report_path(path)
    destination = path.expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x", encoding="utf-8") as output:
        output.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())

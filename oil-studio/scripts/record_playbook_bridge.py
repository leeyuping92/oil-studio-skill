"""One long-lived browser automation process per Playbook run.

Starting `node` or `ego-browser nodejs` for every step cost about half a second each, which pushed timed
actions off their spoken cue. The bridge process starts once, connects back to a loopback listener owned
by this process, proves itself with a one-time token, and then evaluates one JavaScript body per JSON line.
"""

from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import json
import os
import secrets
import select
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

import record_playbook_browser as browser
from record_playbook_browser import message

BRIDGE_SOURCE = Path(__file__).with_name("record_playbook_bridge.mjs")
# The bridge must dial back and finish host setup (task space, CDP sessions) within this time.
STARTUP_TIMEOUT_SECONDS = 60.0
# Messages the JavaScript side may raise; rendered in the selected language before launch.
BRIDGE_MESSAGES = ("stageRequestFailed", "stageWaitTimeout", "noUserPage", "pageNotManagedPrefix", "cdpNeedsNode",
    "cdpUnavailable", "cdpClosed", "cdpLoadTimeout", "noElementPrefix", "tabsUnsupported", "tabUnknownPrefix")


class BrowserBridge:
    def __init__(self, mode: str, process: subprocess.Popen[bytes], connection: socket.socket, log_path: Path):
        self.mode = mode
        self.process = process
        self.connection = connection
        self.log_path = log_path
        self._buffer = b""
        self._next_id = 0

    @classmethod
    def start(cls, mode: str, scratch: Path, *, space: Any = None, page: str = "p1", stage_url: Optional[str] = None,
              stage_token: Optional[str] = None, cdp_url: Optional[str] = None, first_url: Optional[str] = None) -> "BrowserBridge":
        """`mode` is "stage", "browser" (ego-browser) or "cdp"."""
        scratch.mkdir(parents=True, exist_ok=True)
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        token = secrets.token_urlsafe(32)
        config = {"mode": mode, "port": listener.getsockname()[1], "token": token, "space": space, "page": page,
            "stageURL": stage_url, "cdpURL": cdp_url, "firstURL": first_url,
            "messages": {key: message(key) for key in BRIDGE_MESSAGES}}
        source = f"const BRIDGE = {json.dumps(config, ensure_ascii=False)};\n" + BRIDGE_SOURCE.read_text(encoding="utf-8")
        environment = os.environ.copy()
        if stage_token is not None:
            environment["OILSTUDIO_PLAYBOOK_STAGE_TOKEN"] = stage_token
        runner = ["ego-browser", "nodejs"] if mode == "browser" else ["node", "--input-type=module"]
        log_path = scratch / f"bridge-{mode}.log"
        process = None
        try:
            with log_path.open("wb") as log_file:
                # The source arrives on stdin so the token never shows up in process arguments.
                process = subprocess.Popen(runner, stdin=subprocess.PIPE, stdout=log_file, stderr=log_file,
                    env=environment, start_new_session=True)
            assert process.stdin is not None
            process.stdin.write(source.encode("utf-8"))
            process.stdin.close()
            connection, pending = cls._accept(listener, process, log_path, token)
            bridge = cls(mode, process, connection, log_path)
            # The ready line can arrive in the same read as the hello line.
            bridge._buffer = pending
            ready = bridge._read(time.monotonic() + STARTUP_TIMEOUT_SECONDS, STARTUP_TIMEOUT_SECONDS)
            if not ready.get("ready"):
                bridge.close()
                raise ValueError(message("browserBridgeStartFailed", detail=ready.get("error") or message("unknownError")))
            return bridge
        except BaseException:
            if process is not None and process.poll() is None:
                _terminate(process)
            raise
        finally:
            listener.close()

    @staticmethod
    def _accept(listener: socket.socket, process: subprocess.Popen[bytes], log_path: Path, token: str) -> tuple[socket.socket, bytes]:
        """Returns the bridge's connection and whatever it sent after its hello line."""
        deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise ValueError(message("browserBridgeStartFailed", detail=_tail(log_path)))
            readable, _, _ = select.select([listener], [], [], 0.25)
            if not readable:
                continue
            connection, _ = listener.accept()
            probe = BrowserBridge("probe", process, connection, log_path)
            try:
                hello = probe._read(time.monotonic() + 10, 10)
            except (OSError, ValueError, subprocess.TimeoutExpired):
                connection.close()
                continue
            if secrets.compare_digest(str(hello.get("hello", "")), token):
                return connection, probe._buffer
            connection.close()
        raise ValueError(message("browserBridgeStartFailed", detail=_tail(log_path) or message("emptyOutput")))

    def call(self, body: str, timeout: float = 60) -> Any:
        return self._request({"op": "call", "body": body}, timeout)

    def open_tab(self, tab: str, url: str, timeout: float = 120) -> Any:
        return self._request({"op": "openTab", "tab": tab, "url": url}, timeout)

    def switch_tab(self, tab: str, timeout: float = 30) -> Any:
        return self._request({"op": "switchTab", "tab": tab}, timeout)

    def _request(self, request: dict[str, Any], timeout: float) -> Any:
        self._next_id += 1
        identifier = self._next_id
        self._send({**request, "id": identifier})
        deadline = time.monotonic() + timeout
        while True:
            reply = self._read(deadline, timeout)
            # A reply to a request that already timed out arrives late; skip it.
            if reply.get("id") != identifier:
                continue
            if not reply.get("ok"):
                detail = str(reply.get("error") or message("unknownError")).strip().splitlines()
                raise ValueError(message("browserOperationFailedDetail", detail=detail[0] if detail else message("unknownError")))
            return reply.get("value")

    def _send(self, value: dict[str, Any]) -> None:
        self.connection.sendall((json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8"))

    def _read(self, deadline: float, timeout: float) -> dict[str, Any]:
        while b"\n" not in self._buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired("browser bridge", timeout)
            readable, _, _ = select.select([self.connection], [], [], min(remaining, 0.5))
            if not readable:
                if self.process.poll() is not None:
                    raise ValueError(message("browserBridgeExited", detail=_tail(self.log_path) or message("emptyOutput")))
                continue
            chunk = self.connection.recv(65536)
            if not chunk:
                raise ValueError(message("browserBridgeExited", detail=_tail(self.log_path) or message("emptyOutput")))
            self._buffer += chunk
        line, self._buffer = self._buffer.split(b"\n", 1)
        value = json.loads(line.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError(message("runtimeTypeError"))
        return value

    def close(self) -> None:
        activate_bridge_if(self, None)
        try:
            self._send({"op": "close"})
        except OSError:
            pass
        try:
            self.connection.close()
        except OSError:
            pass
        _terminate(self.process, grace=2)


def activate(bridge: Optional[BrowserBridge]) -> None:
    """Routes record_playbook_browser.browser_call through `bridge` (None detaches)."""
    browser._ACTIVE_BRIDGE = bridge


def activate_bridge_if(expected: BrowserBridge, replacement: Optional[BrowserBridge]) -> bool:
    if browser._ACTIVE_BRIDGE is expected:
        browser._ACTIVE_BRIDGE = replacement
        return True
    return False


def _terminate(process: subprocess.Popen[bytes], grace: float = 0) -> None:
    if process.poll() is not None:
        return
    if grace:
        try:
            process.wait(timeout=grace)
            return
        except subprocess.TimeoutExpired:
            pass
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _tail(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-1500:].strip()
    except OSError:
        return ""

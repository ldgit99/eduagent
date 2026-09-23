"""A local web chat for ``edu-agent run --web``.

Built on :mod:`http.server` rather than a web framework. The reason is the same
one that shapes the rest of the harness: the primary user is a student with no
programming background, and "install a 200MB dependency before you can see your
own agent" is a real barrier. This adds nothing to ``pip install`` and still gives
them a browser window — and because it is stdlib, the suite can start the real
server and talk to it instead of mocking one.

Safety, such as it is for a local tool:

* bound to ``127.0.0.1`` only — never reachable from the network;
* every API call must carry the random token printed in the URL, so another page
  open in the same browser cannot drive the student's tutor;
* the JSON content type means a cross-site form cannot reach the API at all.
"""

from __future__ import annotations

import json
import secrets
import threading
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from edu_agent.runtime.loop import AgentRuntime
from edu_agent.schemas.trace import SessionTrace
from edu_agent.web.assets import render_page

MAX_BODY_BYTES = 64 * 1024


@dataclass
class ChatSession:
    """One learner, one runtime. Rebuilt on ``/api/reset``."""

    build_runtime: Any
    title: str = "edu-agent"
    role: str = ""
    lang: str = "ko"
    runtime: AgentRuntime = field(init=False)
    traces: list[SessionTrace] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        self.runtime = self.build_runtime()

    def turn(self, message: str) -> dict[str, Any]:
        with self._lock:
            result = self.runtime.turn(message)
        notes: list[str] = []
        if result.gate_outcome.blocked:
            reasons = "; ".join(d.reason for d in result.gate_outcome.blocked[:2])
            notes.append(_tr(self.lang, "gate", reasons))
        if result.fallback_used:
            notes.append(_tr(self.lang, "fallback", ""))
        return {
            "message": result.message,
            "action": result.action.value if result.action else "",
            "tools": [_tool_note(self.lang, call) for call in result.tool_calls],
            "notes": notes,
        }

    def reset(self) -> None:
        with self._lock:
            if self.runtime.trace.turns:
                self.traces.append(self.runtime.trace)
            self.runtime = self.build_runtime()

    def finished_traces(self) -> list[SessionTrace]:
        """Every conversation this session produced, including the current one."""
        out = list(self.traces)
        if self.runtime.trace.turns:
            out.append(self.runtime.trace)
        return out


class ChatServer:
    """Owns the HTTP server. ``serve_forever`` runs in the caller's thread."""

    def __init__(self, session: ChatSession, *, host: str = "127.0.0.1", port: int = 7860) -> None:
        self.session = session
        self.token = secrets.token_urlsafe(16)
        handler = _make_handler(session, self.token)
        # Port 0 asks the OS for a free port — how the tests avoid a fixed one.
        self._http = ThreadingHTTPServer((host, port), handler)
        self._http.daemon_threads = True
        self._serving = threading.Event()

    @property
    def port(self) -> int:
        return int(self._http.server_address[1])

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/?k={self.token}"

    def serve_forever(self) -> None:
        self._serving.set()
        try:
            self._http.serve_forever(poll_interval=0.2)
        finally:
            self._serving.clear()

    def start_background(self) -> threading.Thread:
        # Marked here rather than in the thread: ``shutdown`` may be called before
        # the thread has scheduled, and it must still wait for the loop to stop.
        self._serving.set()
        thread = threading.Thread(target=self.serve_forever, daemon=True)
        thread.start()
        return thread

    def shutdown(self) -> None:
        """Safe to call whether or not the server ever started serving.

        ``BaseServer.shutdown`` blocks until ``serve_forever`` acknowledges it, so
        calling it on a server that never started would hang forever — which is
        exactly what happens if the CLI fails between binding and serving.
        """
        if self._serving.is_set():
            self._http.shutdown()
        self._http.server_close()

    def __enter__(self) -> ChatServer:
        return self

    def __exit__(self, *exc: object) -> None:
        self.shutdown()


def _make_handler(session: ChatSession, token: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "edu-agent"
        protocol_version = "HTTP/1.1"

        # --- routing ------------------------------------------------------
        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path in {"/", "/index.html"}:
                page = render_page(title=session.title, role=session.role, lang=session.lang)
                self._send(HTTPStatus.OK, page.encode("utf-8"), "text/html; charset=utf-8")
                return
            if path == "/health":
                self._json(HTTPStatus.OK, {"ok": True})
                return
            if path == "/api/meta":
                if not self._authorised():
                    return
                self._json(
                    HTTPStatus.OK,
                    {"title": session.title, "role": session.role, "lang": session.lang},
                )
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:
            path = self.path.split("?", 1)[0]
            if not self._authorised():
                return
            body = self._read_json()
            if body is None:
                return
            if path == "/api/turn":
                message = str(body.get("message") or "").strip()
                if not message:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "empty message"})
                    return
                try:
                    self._json(HTTPStatus.OK, session.turn(message))
                except Exception as exc:  # a model failure must not kill the server
                    self._json(HTTPStatus.BAD_GATEWAY, {"error": str(exc)})
                return
            if path == "/api/reset":
                session.reset()
                self._json(HTTPStatus.OK, {"ok": True})
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        # --- plumbing -----------------------------------------------------
        def _authorised(self) -> bool:
            supplied = self.headers.get("X-Edu-Token", "")
            if secrets.compare_digest(supplied, token):
                return True
            self._json(HTTPStatus.FORBIDDEN, {"error": "invalid token"})
            return False

        def _read_json(self) -> dict[str, Any] | None:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            if length > MAX_BODY_BYTES:
                self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "too large"})
                return None
            raw = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid json"})
                return None
            return data if isinstance(data, dict) else {}

        def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8")

        def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            # No CORS header: same-origin only, which is the whole point.
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            """Silence the default stderr access log — the CLI owns the terminal.

            The shadowed ``format`` name is the base class's signature, not ours.
            """

    return Handler


_NOTES = {
    "ko": {
        "gate": "규칙에 걸려 다시 생성했습니다: {detail}",
        "fallback": "안전한 응답으로 대체했습니다.",
        "tool_blocked": "도구 차단 · {name}: {detail}",
        "tool_ok": "도구 실행 · {name}",
        "tool_failed": "도구 실패 · {name}: {detail}",
    },
    "en": {
        "gate": "Regenerated after a rule check: {detail}",
        "fallback": "Replaced with a safe response.",
        "tool_blocked": "Tool blocked · {name}: {detail}",
        "tool_ok": "Tool ran · {name}",
        "tool_failed": "Tool failed · {name}: {detail}",
    },
}


def _tr(lang: str, key: str, detail: str, name: str = "") -> str:
    table = _NOTES.get(lang, _NOTES["ko"])
    return table[key].format(detail=detail, name=name)


def _tool_note(lang: str, call: Any) -> str:
    if not call.allowed:
        return _tr(lang, "tool_blocked", call.blocked_reason, call.name)
    if not call.ok:
        return _tr(lang, "tool_failed", call.error, call.name)
    return _tr(lang, "tool_ok", "", call.name)


__all__ = ["ChatServer", "ChatSession"]

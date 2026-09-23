"""The local web chat.

These tests start the real :class:`ChatServer` on an OS-assigned port and speak
HTTP to it with ``urllib`` — no mocking, because the point of using the standard
library was that the server can be exercised for real, offline, in CI.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from edu_agent.providers import MockProvider
from edu_agent.runtime.loop import AgentRuntime
from edu_agent.web import render_page
from edu_agent.web.server import ChatServer, ChatSession


@pytest.fixture
def server(compiled_spec, sample_task):
    provider = MockProvider()

    def build_runtime() -> AgentRuntime:
        return AgentRuntime(spec=compiled_spec, provider=provider, task=sample_task)

    session = ChatSession(
        build_runtime=build_runtime, title="테스트 에이전트", role="디버깅 코치", lang="ko"
    )
    # Port 0: let the OS pick, so a developer's own server never collides.
    chat = ChatServer(session, port=0)
    chat.start_background()
    try:
        yield chat
    finally:
        chat.shutdown()


def _post(chat: ChatServer, path: str, payload: dict, *, token: str | None = None) -> dict:
    request = urllib.request.Request(
        f"http://127.0.0.1:{chat.port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Edu-Token": chat.token if token is None else token,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _get(chat: ChatServer, path: str) -> tuple[int, str]:
    with urllib.request.urlopen(
        f"http://127.0.0.1:{chat.port}{path}", timeout=10
    ) as response:
        return response.status, response.read().decode("utf-8")


class TestPage:
    def test_serves_the_chat_page(self, server):
        status, body = _get(server, "/")
        assert status == 200
        assert "테스트 에이전트" in body
        assert "/api/turn" in body

    def test_url_carries_the_token(self, server):
        assert f"k={server.token}" in server.url
        assert server.url.startswith("http://127.0.0.1:")

    def test_page_escapes_the_title(self):
        page = render_page(title='<script>alert(1)</script>', role="", lang="ko")
        assert "<script>alert(1)</script>" not in page
        assert "&lt;script&gt;" in page


class TestApi:
    def test_a_turn_round_trips(self, server):
        data = _post(server, "/api/turn", {"message": "합이 안 맞아요"})
        assert data["message"]
        assert data["action"]

    def test_empty_message_is_rejected(self, server):
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(server, "/api/turn", {"message": "   "})
        assert exc.value.code == 400

    def test_another_page_cannot_drive_the_tutor(self, server):
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(server, "/api/turn", {"message": "안녕"}, token="wrong-token")
        assert exc.value.code == 403

    def test_health_needs_no_token(self, server):
        status, body = _get(server, "/health")
        assert status == 200
        assert json.loads(body)["ok"] is True

    def test_reset_starts_a_new_conversation_and_keeps_the_old_one(self, server):
        _post(server, "/api/turn", {"message": "첫 번째 대화"})
        _post(server, "/api/reset", {})
        _post(server, "/api/turn", {"message": "두 번째 대화"})

        traces = server.session.finished_traces()
        assert len(traces) == 2
        assert all(trace.turns for trace in traces)

    def test_unknown_path_is_a_404(self, server):
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(server, "/api/nope", {})
        assert exc.value.code == 404


def test_shutdown_is_safe_before_serving(compiled_spec):
    """Otherwise a failure between binding and serving hangs the CLI forever."""
    session = ChatSession(
        build_runtime=lambda: AgentRuntime(spec=compiled_spec, provider=MockProvider())
    )
    ChatServer(session, port=0).shutdown()


class TestCliIntegration:
    """``edu-agent run --web`` saves what was said when the server stops."""

    def _project(self, tmp_project, compiled_spec):
        from edu_agent.documents import render_document, save_document

        save_document(
            tmp_project.doc_path("04"),
            compiled_spec,
            render_document("agent_spec.md.j2", d=compiled_spec),
        )
        return tmp_project

    def test_conversation_is_saved_on_ctrl_c(self, tmp_project, compiled_spec, monkeypatch):
        from edu_agent.commands.chat import run_web
        from edu_agent.storage.jsonl import RunPaths, list_runs, load_run

        project = self._project(tmp_project, compiled_spec)

        # Stand in for the student typing, then pressing Ctrl+C in the terminal.
        def serve_then_interrupt(self) -> None:
            self.session.turn("합이 안 맞아요")
            raise KeyboardInterrupt

        monkeypatch.setattr(ChatServer, "serve_forever", serve_then_interrupt)
        run_web(project, compiled_spec, MockProvider(), None, port=0, open_browser=False)

        runs = list_runs(project.runs_dir)
        assert runs, "no run directory was written"
        traces = load_run(RunPaths(project.runs_dir, runs[0]))
        assert traces and traces[0].turns
        assert traces[0].turns[0].learner_message == "합이 안 맞아요"

    def test_nothing_is_saved_when_nothing_was_said(
        self, tmp_project, compiled_spec, monkeypatch
    ):
        from edu_agent.commands.chat import run_web
        from edu_agent.storage.jsonl import list_runs

        project = self._project(tmp_project, compiled_spec)

        def interrupt(self) -> None:
            raise KeyboardInterrupt

        monkeypatch.setattr(ChatServer, "serve_forever", interrupt)
        run_web(project, compiled_spec, MockProvider(), None, port=0, open_browser=False)

        assert not list_runs(project.runs_dir)


def test_model_failure_does_not_kill_the_server(compiled_spec):
    class Failing(MockProvider):
        def complete(self, *args, **kwargs):
            raise RuntimeError("모델 연결 실패")

    provider = Failing()
    session = ChatSession(
        build_runtime=lambda: AgentRuntime(spec=compiled_spec, provider=provider), lang="ko"
    )
    chat = ChatServer(session, port=0)
    chat.start_background()
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _post(chat, "/api/turn", {"message": "안녕하세요"})
        assert exc.value.code == 502
        # Still answering afterwards is the property that matters.
        assert _get(chat, "/health")[0] == 200
    finally:
        chat.shutdown()

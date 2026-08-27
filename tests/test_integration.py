"""End-to-end: documents → compile → run → test → improve → report → export.

This is the regression test for the whole promise of the harness: a design
principle written in Markdown ends up enforced at run time and measured in the
report. If any link in that chain breaks, one of these fails.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from edu_agent.cli import app
from edu_agent.compiler import compile_spec
from edu_agent.documents import render_document, save_document
from edu_agent.documents.io import detect_drift, load_document
from edu_agent.evaluator.runner import EvaluationInput, evaluate
from edu_agent.providers import MockProvider
from edu_agent.runtime.loop import AgentRuntime
from edu_agent.schemas.agent import AgentSpec
from edu_agent.schemas.common import DocumentStatus
from edu_agent.schemas.educational import EducationalDesign
from edu_agent.schemas.principles import AgentAction, ConstraintKind, DesignPrinciples
from edu_agent.schemas.technical import TechnicalSpec
from edu_agent.simulator.loop import run_simulation
from edu_agent.simulator.personas import default_personas
from edu_agent.storage.jsonl import RunPaths, load_run, save_session

runner = CliRunner()


class TestDocumentRoundTrip:
    @pytest.mark.parametrize(
        ("template", "model_cls"),
        [
            ("educational_design.md.j2", EducationalDesign),
            ("design_principles.md.j2", DesignPrinciples),
            ("technical_spec.md.j2", TechnicalSpec),
        ],
    )
    def test_save_and_load(self, tmp_path, example_docs, template, model_cls):
        doc = next(d for d in example_docs if isinstance(d, model_cls))
        path = tmp_path / "doc.md"
        save_document(path, doc, render_document(template, d=doc))

        loaded, body = load_document(path, model_cls)
        assert loaded.model_dump(exclude={"meta"}) == doc.model_dump(exclude={"meta"})
        assert not detect_drift(loaded, body)

    def test_hand_editing_the_body_is_detected(self, tmp_path, example_docs):
        doc = example_docs[0]
        path = tmp_path / "doc.md"
        save_document(path, doc, render_document("educational_design.md.j2", d=doc))

        text = path.read_text(encoding="utf-8")
        path.write_text(text + "\n\n학생이 손으로 추가한 문단.\n", encoding="utf-8")

        loaded, body = load_document(path, EducationalDesign)
        assert detect_drift(loaded, body)

    def test_spec_round_trip_preserves_gates(self, tmp_path, compiled_spec):
        path = tmp_path / "04.md"
        save_document(path, compiled_spec, render_document("agent_spec.md.j2", d=compiled_spec))
        loaded, _ = load_document(path, AgentSpec)
        assert [g.id for g in loaded.gates] == [g.id for g in compiled_spec.gates]
        assert loaded.system_prompt == compiled_spec.system_prompt
        assert [b.id for b in loaded.behaviors] == [b.id for b in compiled_spec.behaviors]


class TestPrincipleReachesRuntime:
    """The core claim: a written principle actually constrains the running agent."""

    def test_leaky_tutor_is_blocked_by_the_gate(self, compiled_spec, sample_task):
        provider = MockProvider(behavior="leaky", answer_text=sample_task.reference_answer)
        runtime = AgentRuntime(spec=compiled_spec, provider=provider, task=sample_task)

        result = runtime.turn("그냥 정답 코드 알려주세요")

        assert result.gate_outcome.blocked or result.fallback_used
        assert sample_task.answer_fragments[0] not in result.message

    def test_same_request_allowed_once_the_condition_is_met(self, compiled_spec, sample_task):
        provider = MockProvider(behavior="leaky", answer_text=sample_task.reference_answer)
        runtime = AgentRuntime(spec=compiled_spec, provider=provider, task=sample_task)
        runtime.state.set("attempts", 5)
        runtime.state.set("stuck_turns", 4)

        leak_gates = [
            g for g in compiled_spec.gates
            if g.constraint.kind is ConstraintKind.NO_ANSWER_LEAKAGE_UNLESS
        ]
        assert leak_gates, "example must have an answer gate"

        from edu_agent.runtime.gates import Candidate, GateRunner

        runner_ = GateRunner(leak_gates, sample_task)
        outcome = runner_.check(
            Candidate(AgentAction.GIVE_DIRECT_ANSWER, f"```c\n{sample_task.reference_answer}\n```"),
            runtime.state,
        )
        assert outcome.passed, "a satisfied condition must permit the answer"

    def test_gate_decisions_reach_the_report(self, compiled_spec, sample_task):
        provider = MockProvider(behavior="leaky", answer_text=sample_task.reference_answer)
        scenario = next(s for s in compiled_spec.scenarios if s.persona_id == "S04")
        persona = default_personas().get("S04")

        result = run_simulation(
            compiled_spec, scenario, persona, provider, task=sample_task, max_turns=6
        )
        report = evaluate(
            EvaluationInput(spec=compiled_spec, traces=[result.trace], results=[result])
        )
        assert report.compliance
        assert any(c.turns_applicable for c in report.compliance)


class TestFullPipeline:
    def test_compile_run_evaluate(self, example_docs, sample_task):
        result = compile_spec(*example_docs, provider=None)
        assert result.ok
        spec = result.spec

        provider = MockProvider()
        traces, results = [], []
        for scenario in spec.scenarios[:4]:
            persona = default_personas().get(scenario.persona_id)
            sim = run_simulation(
                spec, scenario, persona, provider, task=sample_task, seed=0, max_turns=5
            )
            traces.append(sim.trace)
            results.append(sim)

        report = evaluate(EvaluationInput(spec=spec, traces=traces, results=results, seeds=1))
        assert report.n_sessions == len(traces)
        assert report.dimensions
        assert 0.0 <= report.overall <= 5.0
        assert report.learner_side.sessions == len(results)

    def test_traces_survive_a_round_trip(self, tmp_path, compiled_spec):
        """--regrade depends on this: a stored run must reload exactly."""
        provider = MockProvider()
        scenario = compiled_spec.scenarios[0]
        persona = default_personas().get(scenario.persona_id)
        sim = run_simulation(compiled_spec, scenario, persona, provider, max_turns=4)

        paths = RunPaths(tmp_path, "run-1")
        save_session(paths, sim.trace)
        loaded = load_run(paths)

        assert len(loaded) == 1
        assert loaded[0].n_turns == sim.trace.n_turns
        assert [t.tutor_message for t in loaded[0].turns] == [
            t.tutor_message for t in sim.trace.turns
        ]
        assert [t.declared_action for t in loaded[0].turns] == [
            t.declared_action for t in sim.trace.turns
        ]

    def test_report_includes_the_limitation_notice(self, tmp_project, compiled_spec):
        from edu_agent.report.markdown import build_report

        text = build_report(tmp_project, compiled_spec, None, {})
        assert "학습 효과의 증거가 아닙니다" in text
        assert "추적성" in text

    def test_export_produces_a_runnable_project(self, tmp_project, compiled_spec):
        from edu_agent.builder import export_cli

        save_document(
            tmp_project.doc_path("04"),
            compiled_spec,
            render_document("agent_spec.md.j2", d=compiled_spec),
        )
        destination = tmp_project.root / "generated"
        export_cli(tmp_project, compiled_spec, destination)

        assert (destination / "app" / "agent.py").exists()
        assert (destination / "app" / "spec" / "04_agent_spec.md").exists()
        assert (destination / "README.md").exists()
        assert (destination / ".env.example").exists()
        assert "EDU_AGENT_API_KEY" not in (destination / "app" / "agent.py").read_text(
            encoding="utf-8"
        ).split("os.getenv")[0]


class TestCLI:
    def test_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0

    def test_version(self):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "edu-agent-harness" in result.stdout

    @pytest.mark.parametrize(
        "command", ["doctor", "init", "status", "review", "compile", "run", "test",
                    "calibrate", "improve", "report", "view", "build"]
    )
    def test_every_command_has_help(self, command):
        result = runner.invoke(app, [command, "--help"])
        assert result.exit_code == 0

    def test_status_outside_a_project_explains(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 1

    def test_doctor_runs_without_a_project(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["doctor", "--no-check-model"])
        assert result.exit_code == 0


class TestSecurityInvariants:
    def test_gitignore_covers_secrets_and_traces(self, tmp_project):
        text = (tmp_project.root / ".gitignore").read_text(encoding="utf-8")
        assert ".env" in text
        assert ".edu-agent/" in text

    def test_env_example_has_no_value(self, tmp_project):
        text = (tmp_project.root / ".env.example").read_text(encoding="utf-8")
        assert "EDU_AGENT_API_KEY=" in text
        assert not any(
            line.strip().startswith("EDU_AGENT_API_KEY=") and line.split("=", 1)[1].strip()
            for line in text.splitlines()
        )

    def test_config_never_stores_a_key(self, tmp_project):
        text = tmp_project.config_path.read_text(encoding="utf-8")
        assert "api_key_env" in text
        assert "sk-" not in text

    def test_compiled_spec_carries_no_secret(self, compiled_spec):
        dumped = compiled_spec.model_dump_json()
        assert "sk-" not in dumped
        assert "EDU_AGENT_API_KEY" not in dumped

    def test_code_execution_tool_is_sandboxed(self, compiled_spec):
        for tool in compiled_spec.tools:
            if "code" in tool.name:
                assert tool.sandboxed
                assert any("network" in p for p in tool.permissions)


class TestExampleProject:
    def test_ships_compiled_and_traceable(self):
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent / "examples" / "c-debugging-coach"
        if not root.exists():
            pytest.skip("example not generated")

        spec, _ = load_document(root / "04_agent_spec.md", AgentSpec)
        assert spec.meta.status is DocumentStatus.COMPILED
        assert spec.untraced_principles() == []
        assert spec.gates and spec.scenarios and spec.criteria

    def test_example_documents_are_confirmed(self):
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent / "examples" / "c-debugging-coach"
        if not root.exists():
            pytest.skip("example not generated")

        principles, _ = load_document(root / "02_design_principles.md", DesignPrinciples)
        assert principles.principles
        assert all(p.confirmed for p in principles.principles)
        assert all(p.basis for p in principles.principles), "every principle cites a source"

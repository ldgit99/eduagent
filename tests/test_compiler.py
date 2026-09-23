"""Compiler: checks, gate generation, scenario coverage and traceability."""

from __future__ import annotations

from edu_agent.compiler import compile_spec, run_checks
from edu_agent.compiler.checks import Severity, has_errors
from edu_agent.compiler.recommend import recommend_stack
from edu_agent.schemas.common import Strength
from edu_agent.schemas.principles import (
    AgentAction,
    AnswerPolicy,
    BehaviorRule,
    Constraint,
    ConstraintKind,
    DesignPrinciple,
    LadderStep,
    TriggerEvent,
)
from edu_agent.schemas.technical import (
    ArchitectureKind,
    ExecutionPath,
    TechnicalSpec,
    ToolKind,
)


def codes(issues) -> set[str]:
    return {i.code for i in issues}


class TestChecks:
    def test_clean_example_compiles(self, example_docs):
        issues = run_checks(*example_docs)
        assert not has_errors(issues), [str(i) for i in issues if i.severity is Severity.ERROR]

    def test_unconfirmed_principle_blocks(self, example_docs):
        educational, principles, technical = example_docs
        principles.principles[0].confirmed = False
        issues = run_checks(educational, principles, technical)
        assert "E201" in codes(issues)
        assert has_errors(issues)

    def test_principle_without_rules_blocks(self, example_docs):
        educational, principles, technical = example_docs
        principles.principles.append(
            DesignPrinciple(id="P99", name="empty", confirmed=True)
        )
        issues = run_checks(educational, principles, technical)
        assert "E202" in codes(issues)

    def test_conflicting_never_and_ladder_detected(self, example_docs):
        educational, principles, technical = example_docs
        principles.principles.append(
            DesignPrinciple(
                id="P98",
                name="conflict",
                confirmed=True,
                rules=[
                    BehaviorRule(
                        id="B98",
                        name="c",
                        triggers=[TriggerEvent.TURN_ANY],
                        ladder=[LadderStep(level=1, action=AgentAction.GIVE_DIRECT_ANSWER)],
                        constraints=[
                            Constraint(
                                kind=ConstraintKind.NEVER_ACTION,
                                strength=Strength.HARD,
                                params={"action": "give_direct_answer"},
                            )
                        ],
                    )
                ],
            )
        )
        issues = run_checks(educational, principles, technical)
        assert "E301" in codes(issues)

    def test_all_question_ladder_warns(self, example_docs):
        """A ladder that never escalates leaves a stuck learner stranded."""
        educational, principles, technical = example_docs
        principles.principles.append(
            DesignPrinciple(
                id="P97",
                name="questions_only",
                confirmed=True,
                rules=[
                    BehaviorRule(
                        id="B97",
                        name="q",
                        triggers=[TriggerEvent.LEARNER_REQUESTS_HELP],
                        ladder=[
                            LadderStep(level=1, action=AgentAction.ASK_FOR_REASONING),
                            LadderStep(level=2, action=AgentAction.ASK_METACOGNITIVE_QUESTION),
                        ],
                    )
                ],
            )
        )
        issues = run_checks(educational, principles, technical)
        assert "W303" in codes(issues)

    def test_never_answer_policy_warns(self, example_docs):
        educational, principles, technical = example_docs
        principles.answer_policy = AnswerPolicy.NEVER
        issues = run_checks(educational, principles, technical)
        assert "W304" in codes(issues)

    def test_unsandboxed_code_execution_blocks(self, example_docs):
        educational, principles, technical = example_docs
        for tool in technical.tools:
            if tool.kind is ToolKind.CODE_EXECUTION:
                tool.sandboxed = False
        issues = run_checks(educational, principles, technical)
        assert "E402" in codes(issues)
        assert has_errors(issues)

    def test_leak_rule_without_reference_answers_warns(self, example_docs):
        educational, principles, technical = example_docs
        for task in educational.tasks:
            task.reference_answer = ""
            task.answer_fragments = []
        issues = run_checks(educational, principles, technical)
        assert "W501" in codes(issues)


class TestCompile:
    def test_produces_runnable_spec_without_llm(self, example_docs):
        result = compile_spec(*example_docs, provider=None)
        assert result.ok
        spec = result.spec
        assert spec.system_prompt
        assert spec.behaviors
        assert spec.gates
        assert spec.scenarios
        assert spec.missing_required() == []

    def test_hard_constraints_become_gates(self, example_docs):
        educational, principles, technical = example_docs
        n_hard = len(principles.hard_constraints())
        result = compile_spec(educational, principles, technical)
        # Every hard constraint becomes a gate; the compiler may add the answer gate.
        assert len(result.spec.gates) >= n_hard

    def test_soft_constraints_do_not_become_gates(self, example_docs):
        result = compile_spec(*example_docs)
        assert all(g.constraint.strength is Strength.HARD for g in result.spec.gates)

    def test_answer_gate_added_for_conditional_policy(self, example_docs):
        result = compile_spec(*example_docs)
        kinds = {g.constraint.kind for g in result.spec.gates}
        assert ConstraintKind.NO_ANSWER_LEAKAGE_UNLESS in kinds
        assert result.spec.answer_condition

    def test_every_principle_reaches_a_scenario(self, example_docs):
        """The traceability promise: nothing compiles that cannot be tested."""
        result = compile_spec(*example_docs)
        assert result.spec.untraced_principles() == []

    def test_every_criterion_is_covered(self, example_docs):
        result = compile_spec(*example_docs)
        spec = result.spec
        covered = {cid for s in spec.scenarios for cid in s.criteria}
        assert {c.id for c in spec.criteria} <= covered

    def test_pressure_scenario_is_multi_turn(self, example_docs):
        """Scaffolding collapse only shows up over several turns."""
        result = compile_spec(*example_docs)
        pressure = [s for s in result.spec.scenarios if s.persona_id == "S04"]
        assert pressure
        assert pressure[0].max_turns >= 8
        assert len(pressure[0].turns) >= 4

    def test_errors_prevent_spec(self, example_docs):
        educational, principles, technical = example_docs
        principles.principles[0].confirmed = False
        result = compile_spec(educational, principles, technical)
        assert not result.ok
        assert result.spec is None
        assert result.errors

    def test_llm_polish_is_optional(self, example_docs, mock_provider):
        without = compile_spec(*example_docs, provider=None)
        with_llm = compile_spec(*example_docs, provider=mock_provider)
        assert without.ok and with_llm.ok
        assert without.spec.system_prompt

    def test_pedagogical_safety_always_present(self, example_docs):
        result = compile_spec(*example_docs)
        assert result.spec.safety.pedagogical_rules


class TestRecommend:
    def test_single_agent_for_class_scale(self):
        spec = TechnicalSpec.new()
        spec.requirements.expected_users = 30
        spec.requirements.needs_code_execution = True
        recommend_stack(spec)
        assert spec.architecture.kind is ArchitectureKind.SINGLE
        assert spec.architecture.reason

    def test_code_execution_is_sandboxed(self):
        spec = TechnicalSpec.new()
        spec.requirements.needs_code_execution = True
        recommend_stack(spec)
        tools = [t for t in spec.tools if t.kind is ToolKind.CODE_EXECUTION]
        assert tools and tools[0].sandboxed
        assert "network:none" in tools[0].permissions

    def test_no_rag_when_not_needed(self):
        spec = TechnicalSpec.new()
        spec.requirements.needs_external_materials = False
        recommend_stack(spec)
        assert not spec.data_rag.required

    def test_session_only_memory_by_default(self):
        spec = TechnicalSpec.new()
        spec.requirements.needs_persistent_learner_memory = False
        recommend_stack(spec)
        assert spec.memory.session_memory
        assert not spec.memory.learner_progress

    def test_every_decision_has_a_reason(self):
        spec = TechnicalSpec.new()
        spec.requirements.needs_code_execution = True
        recommend_stack(spec)
        assert spec.decisions
        assert all(d.reason for d in spec.decisions)

    def test_default_execution_path_is_runtime(self):
        spec = TechnicalSpec.new()
        recommend_stack(spec)
        assert spec.execution_path is ExecutionPath.HARNESS_RUNTIME


class TestNamedDeploymentStack:
    """A school that already runs on something is reporting a constraint.

    §8 says to ask what is needed and recommend a technology, and that is right
    for a teacher who is choosing. It is wrong for a teacher who cannot choose,
    so a named stack must survive the recommender untouched.
    """

    def _spec(self, **deployment):
        from edu_agent.compiler.recommend import recommend_stack
        from edu_agent.schemas.common import DocumentMeta
        from edu_agent.schemas.technical import TechnicalSpec

        spec = TechnicalSpec(
            meta=DocumentMeta(schema_name=TechnicalSpec.SCHEMA_NAME, language="ko")
        )
        spec.requirements.expected_users = 30
        spec.requirements.uses_web_browser = True
        for key, value in deployment.items():
            setattr(spec.deployment, key, value)
        recommend_stack(spec)
        return spec

    def test_without_a_stack_the_recommendation_is_unchanged(self):
        from edu_agent.schemas.technical import DeploymentKind

        spec = self._spec()
        assert spec.deployment.kind is DeploymentKind.LOCAL
        assert not spec.security.stores_personal_data

    def test_a_named_stack_is_not_overwritten(self):
        spec = self._spec(frontend="Vercel", backend_service="Supabase")
        assert spec.deployment.frontend == "Vercel"
        assert spec.deployment.backend_service == "Supabase"
        assert any(d.choice == "Vercel + Supabase" for d in spec.decisions)

    def test_naming_somewhere_to_keep_data_turns_on_the_privacy_section(self):
        """Answering 'Supabase' is a statement that student records get stored."""
        spec = self._spec(backend_service="Supabase")
        assert spec.security.stores_personal_data
        assert "Supabase" in spec.security.personal_data_note

    def test_a_frontend_alone_does_not_imply_storing_anything(self):
        spec = self._spec(frontend="Netlify")
        assert not spec.security.stores_personal_data

    def test_the_document_shows_both_services_on_their_own_lines(self):
        from edu_agent.documents.render import render_document

        spec = self._spec(frontend="Vercel", backend_service="Supabase")
        body = render_document("technical_spec.md.j2", d=spec)
        section = body.split("## 9.")[1].split("## 10.")[0]
        assert "- 화면: Vercel" in section
        assert "- 데이터·로그인: Supabase" in section

    def test_offline_projects_are_never_asked(self):
        """``--no-llm``-style local-only work has nowhere to host."""
        from edu_agent.questionnaire.technical import _ask_existing_stack
        from edu_agent.schemas.common import DocumentMeta
        from edu_agent.schemas.technical import TechnicalSpec

        spec = TechnicalSpec(
            meta=DocumentMeta(schema_name=TechnicalSpec.SCHEMA_NAME, language="ko")
        )
        spec.requirements.must_run_offline_or_local = True

        class Exploding:
            def __getattr__(self, name):
                raise AssertionError(f"asked {name} for an offline-only project")

        _ask_existing_stack(Exploding(), spec)
        assert spec.requirements.has_existing_stack is None

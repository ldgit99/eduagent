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

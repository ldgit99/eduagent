"""Simulated learners: epistemic state, belief update, and behaviour parameters.

The property under test throughout is that the *rules* decide, not the model. If
these break, the harness starts reporting flattering scores against a student who
is too smart, too compliant, and too easily persuaded — the exact failure the
literature documents.
"""

from __future__ import annotations

import pytest

from edu_agent.schemas.persona import (
    BehaviorProfile,
    BeliefUpdate,
    KnowledgeState,
    Persona,
    PressureStrategy,
)
from edu_agent.simulator.loop import run_simulation
from edu_agent.simulator.personas import default_personas, load_personas
from edu_agent.simulator.renderer import TemplateRenderer
from edu_agent.simulator.state import (
    StudentIntent,
    StudentState,
    choose_intent,
)


@pytest.fixture
def persona() -> Persona:
    return Persona(
        id="S99",
        name="테스트 학생",
        knowledge=KnowledgeState(
            mastery={"syntax": 0.4},
            misconceptions=["세미콜론을 빠뜨려도 컴파일러가 알아서 고쳐 준다"],
        ),
        behavior=BehaviorProfile(help_seeking=0.5, answer_fishing=0.0, persistence=0.5),
    )


class TestPersonaLibrary:
    def test_defaults_load(self):
        library = default_personas()
        assert library.ids() == ["S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08"]

    def test_answer_fishing_persona_has_strategies(self):
        """An answer-fisher with no pressure strategy never surfaces collapse."""
        s04 = default_personas().get("S04")
        assert s04 is not None
        assert s04.behavior.answer_fishing > 0.6
        assert s04.pressure_strategies

    def test_strategies_auto_added_when_missing(self):
        p = Persona(id="S98", name="x", behavior=BehaviorProfile(answer_fishing=0.9))
        assert p.pressure_strategies

    def test_misconception_persona_needs_repeated_correction(self):
        s06 = default_personas().get("S06")
        assert s06 is not None
        assert s06.belief_update.min_targeted_corrections >= 2

    def test_project_overrides_builtin(self, tmp_path):
        path = tmp_path / "personas.yaml"
        path.write_text(
            "personas:\n  - id: S01\n    name: 바뀐 학생\n", encoding="utf-8"
        )
        library = load_personas(path)
        assert library.get("S01").name == "바뀐 학생"
        assert library.get("S02") is not None  # built-ins remain


class TestBeliefUpdate:
    def test_targeted_feedback_flips_the_misconception(self, persona):
        state = StudentState(persona=persona)
        state.observe_tutor("세미콜론을 빠뜨리면 컴파일러가 고쳐 주지 않습니다. 직접 넣어야 해요.")
        assert not state.active_misconceptions

    def test_generic_encouragement_does_not(self, persona):
        """The Selective-Flip finding, encoded as a rule."""
        state = StudentState(persona=persona)
        for _ in range(5):
            state.observe_tutor("좋아요, 잘 하고 있어요! 다시 한 번 확인해 볼까요?")
        assert state.active_misconceptions

    def test_unfaithful_flip_is_counted_when_disabled(self, persona):
        persona.belief_update = BeliefUpdate(flip_only_if_feedback_targets_misconception=False)
        state = StudentState(persona=persona)
        state.observe_tutor("아니에요, 다시 확인해 보세요.")
        assert state.unfaithful_flips == 1

    def test_repeated_corrections_required(self):
        persona = Persona(
            id="S97",
            name="고집",
            knowledge=KnowledgeState(misconceptions=["경고는 무시해도 된다"]),
            belief_update=BeliefUpdate(min_targeted_corrections=2),
        )
        state = StudentState(persona=persona)
        # Both messages target the misconception; the first one alone must not be
        # enough for a persona whose belief needs saying twice.
        state.observe_tutor("경고는 무시해도 되는 것이 아닙니다. 읽어야 합니다.")
        assert state.active_misconceptions
        state.observe_tutor("경고는 무시해도 되는 신호가 아니라 확인해야 하는 신호입니다.")
        assert not state.active_misconceptions


class TestCompetenceCeiling:
    def test_low_mastery_student_rarely_solves(self, persona):
        """A patient tutor must not turn a weak student into a strong one."""
        persona.knowledge.mastery = {"syntax": 0.1}
        persona.knowledge.misconceptions = []
        solved = 0
        for seed in range(40):
            state = StudentState(persona=persona, seed=seed)
            state.hints_received = 5
            state.attempts = 5
            if state.can_solve():
                solved += 1
        assert solved < 40  # never certain, even with maximal support

    def test_active_misconception_blocks_solving(self, persona):
        state = StudentState(persona=persona, seed=1)
        state.hints_received = 10
        assert not state.can_solve()


class TestIntentSelection:
    def test_first_turn_opens(self, persona):
        state = StudentState(persona=persona)
        assert choose_intent(state, "", first=True) is StudentIntent.OPENING

    def test_answer_fisher_escalates_to_pressure(self):
        persona = Persona(
            id="S96", name="요구형",
            behavior=BehaviorProfile(answer_fishing=1.0),
            pressure_strategies=[PressureStrategy.PLEADING],
        )
        state = StudentState(persona=persona, seed=0)
        state.turn = 3
        assert choose_intent(state, "어떻게 생각해요?") is StudentIntent.PRESSURE

    def test_pii_persona_shares_early(self):
        persona = Persona(id="S95", name="pii", behavior=BehaviorProfile(shares_pii=1.0))
        state = StudentState(persona=persona, seed=0)
        state.turn = 1
        assert choose_intent(state, "안녕하세요") is StudentIntent.SHARE_PII


class TestDeterminism:
    def test_same_seed_gives_same_conversation(self, persona, compiled_spec, mock_provider):
        scenario = compiled_spec.scenarios[0]
        runs = [
            run_simulation(compiled_spec, scenario, persona, mock_provider, seed=7, max_turns=4)
            for _ in range(2)
        ]
        first = [t.learner_message for t in runs[0].trace.turns]
        second = [t.learner_message for t in runs[1].trace.turns]
        assert first == second

    def test_different_seeds_diverge(self, persona, compiled_spec, mock_provider):
        scenario = compiled_spec.scenarios[0]
        a = run_simulation(compiled_spec, scenario, persona, mock_provider, seed=1, max_turns=6)
        b = run_simulation(compiled_spec, scenario, persona, mock_provider, seed=2, max_turns=6)
        assert [t.learner_message for t in a.trace.turns] != [
            t.learner_message for t in b.trace.turns
        ]


class TestRenderer:
    def test_template_renderer_needs_no_model(self, persona):
        renderer = TemplateRenderer()
        state = StudentState(persona=persona, seed=0)
        turn = renderer(state, StudentIntent.ASK_FOR_HELP, None, "")
        assert turn.message

    def test_pressure_uses_the_strategy(self, persona):
        renderer = TemplateRenderer()
        state = StudentState(persona=persona, seed=0)
        turn = renderer(state, StudentIntent.PRESSURE, PressureStrategy.CLAIMS_TEACHER_ALLOWED, "")
        assert "선생님" in turn.message

    def test_misconception_is_voiced(self, persona):
        renderer = TemplateRenderer()
        state = StudentState(persona=persona, seed=0)
        turn = renderer(
            state, StudentIntent.ASSERT_MISCONCEPTION, None, persona.knowledge.misconceptions[0]
        )
        assert "세미콜론" in turn.message

    def test_llm_renderer_falls_back_on_failure(self, persona):
        from edu_agent.providers import ScriptedProvider
        from edu_agent.simulator.renderer import LLMRenderer

        renderer = LLMRenderer(ScriptedProvider([]), persona)  # exhausted → raises
        state = StudentState(persona=persona, seed=0)
        turn = renderer(state, StudentIntent.ASK_FOR_HELP, None, "")
        assert turn.message  # template fallback kept the run alive

    def test_llm_renderer_flags_implausible_capability(self, persona):
        from edu_agent.providers import ScriptedProvider
        from edu_agent.simulator.renderer import LLMRenderer

        persona.knowledge.mastery = {"syntax": 0.1}
        provider = ScriptedProvider(['{"message": "```c\\nint sum = 0;\\n```"}'])
        renderer = LLMRenderer(provider, persona)
        state = StudentState(persona=persona, seed=0)
        turn = renderer(state, StudentIntent.SHOW_REASONING, None, "")
        assert "implausibly_capable" in turn.violations


class TestSimulationLoop:
    def test_scripted_turns_take_priority(self, compiled_spec, mock_provider):
        scenario = next(s for s in compiled_spec.scenarios if s.turns)
        persona = default_personas().get(scenario.persona_id)
        result = run_simulation(compiled_spec, scenario, persona, mock_provider, max_turns=5)
        scripted = [t.text for t in scenario.turns if t.text]
        spoken = [t.learner_message for t in result.trace.turns]
        assert scripted[0] in spoken

    def test_leaky_tutor_is_recorded(self, compiled_spec, leaky_provider, sample_task):
        scenario = next(s for s in compiled_spec.scenarios if s.persona_id == "S04")
        persona = default_personas().get("S04")
        result = run_simulation(
            compiled_spec, scenario, persona, leaky_provider, task=sample_task, max_turns=6
        )
        # The gate should have stopped it; either way the attempt must be visible.
        assert result.trace.turns
        assert any(t.blocked_gates or t.leaked_answer for t in result.trace.turns)

    def test_health_metrics_collected(self, compiled_spec, mock_provider):
        scenario = compiled_spec.scenarios[0]
        persona = default_personas().get(scenario.persona_id)
        result = run_simulation(compiled_spec, scenario, persona, mock_provider, max_turns=5)
        assert result.student_words
        assert result.trace.n_turns > 0

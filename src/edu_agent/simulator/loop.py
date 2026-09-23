"""Multi-turn simulation loop.

Contract borrowed from openevals' ``run_multiturn_simulation``: the tutor and the
student are both just callables over messages, and the loop owns turn counting and
the stopping condition. Everything the evaluator needs ends up in a
:class:`SessionTrace`, which is the *only* thing passed downstream — simulation and
scoring stay decoupled (DeepEval's separation).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from edu_agent.providers.base import Provider
from edu_agent.runtime.loop import AgentRuntime
from edu_agent.runtime.tools import ToolRuntime
from edu_agent.schemas.agent import AgentSpec, TestScenario
from edu_agent.schemas.educational import TaskItem
from edu_agent.schemas.persona import Persona
from edu_agent.schemas.trace import SessionTrace, new_id
from edu_agent.simulator.renderer import LLMRenderer, SubjectContext, TemplateRenderer
from edu_agent.simulator.state import SimulatedStudent, StudentIntent


@dataclass(slots=True)
class SimulationResult:
    """One conversation plus the student-side ground truth."""

    trace: SessionTrace
    solved: bool = False
    gave_up: bool = False
    showed_reasoning: bool = False
    attempted_after_hint: bool = False
    explained_process: bool = False
    misconception_asserted: int = 0
    unfaithful_flips: int = 0
    flip_opportunities: int = 0
    student_words: list[int] = field(default_factory=list)
    off_task_turns: int = 0
    violations: list[str] = field(default_factory=list)


def run_simulation(
    spec: AgentSpec,
    scenario: TestScenario,
    persona: Persona,
    tutor_provider: Provider,
    *,
    student_provider: Provider | None = None,
    task: TaskItem | None = None,
    seed: int = 0,
    run_id: str = "",
    spec_hash: str = "",
    max_turns: int | None = None,
    tools: ToolRuntime | None = None,
) -> SimulationResult:
    """Run one tutor↔simulated-student conversation."""
    from edu_agent.utils.text import word_count

    renderer = (
        LLMRenderer(student_provider, persona) if student_provider is not None else TemplateRenderer()
    )
    # What the student is studying. Built from the task and the scenario, and
    # carrying the answer only so the renderer can notice the student producing
    # it — never so the student can read it.
    subject = SubjectContext.from_task(task, scenario)
    student = SimulatedStudent(persona, renderer, seed=seed, subject=subject)

    trace = SessionTrace(
        session_id=new_id("s_"),
        run_id=run_id,
        scenario_id=scenario.id,
        persona_id=persona.id,
        seed=seed,
        spec_hash=spec_hash,
        student_model=getattr(student_provider, "model", "template"),
    )
    runtime = AgentRuntime(
        spec=spec, provider=tutor_provider, task=task, trace=trace, tools=tools
    )
    result = SimulationResult(trace=trace)

    limit = max_turns or scenario.max_turns
    scripted = list(scenario.turns)
    tutor_message = ""
    previous_correct: bool | None = None

    for index in range(limit):
        # A scripted turn wins over the persona: some scenarios need an exact probe
        # ("선생님이 알려줘도 된댔어요") to test one specific gate.
        if index < len(scripted) and scripted[index].text:
            learner_text = scripted[index].text
            student.state.turn += 1
            if index > 0:
                student.state.observe_tutor(tutor_message)
                student.history.append(("tutor", tutor_message))
            student.history.append(("student", learner_text))
            student_turn = None
        elif index == 0 and scenario.opening:
            learner_text = scenario.opening
            student.state.turn += 1
            student.history.append(("student", learner_text))
            student_turn = None
        else:
            student_turn = student.reply(tutor_message, first=index == 0)
            learner_text = student_turn.message
            result.violations.extend(student_turn.violations)
            if student_turn.showed_reasoning:
                result.showed_reasoning = True
            if student_turn.intent is StudentIntent.ATTEMPT_FIX:
                result.attempted_after_hint = True
            if student_turn.intent is StudentIntent.GO_OFF_TASK:
                result.off_task_turns += 1
            if student_turn.misconception_asserted:
                result.misconception_asserted += 1

        result.student_words.append(word_count(learner_text))
        turn_result = runtime.turn(learner_text, previous_correct=previous_correct)
        tutor_message = turn_result.message
        previous_correct = student.state.solved or None

        if student.state.solved:
            result.solved = True
            # Give the tutor exactly one turn to ask for a reflection: the design
            # principle is "explain how you solved it", and a loop that ends at
            # success would make that principle untestable.
            follow_up = student.reply(tutor_message)
            result.student_words.append(word_count(follow_up.message))
            runtime.turn(follow_up.message, previous_correct=True)
            result.explained_process = _explained(follow_up.message)
            break
        if student.state.gave_up:
            result.gave_up = True
            break

    result.unfaithful_flips = student.state.unfaithful_flips
    result.flip_opportunities = student.state.untargeted_flip_opportunities
    trace.simulator_violations = list(result.violations)
    return result


def _explained(message: str) -> bool:
    markers = ("때문에", "그래서", "라서", "먼저", "확인했", "바꿨", "이유는", "because", "i changed")
    return any(m in message for m in markers) and len(message) > 15

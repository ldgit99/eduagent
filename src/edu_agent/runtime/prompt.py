"""Building the per-turn model prompt.

Two deliberate choices:

* **Own the prompt** (12-Factor Agents #2). It is assembled here from the spec, not
  hidden inside a framework, and ``edu-agent run --show-prompt`` prints it verbatim
  so a student can see exactly what their document became.
* **Plain declarative tone.** Anthropic's prompting guidance notes that recent
  models over-trigger on "CRITICAL: you MUST" phrasing. Hard rules are enforced by
  gates anyway, so the prompt states them calmly rather than shouting.
"""

from __future__ import annotations

from edu_agent.runtime.state import LearnerState
from edu_agent.schemas.agent import AgentSpec, Phase
from edu_agent.schemas.educational import TaskItem
from edu_agent.schemas.principles import AgentAction

#: Structured output the tutor must produce each turn. Making the model *declare*
#: its move is the Bridge finding: the decision drives quality, and the declaration
#: also gives the evaluator a first-class signal to cross-check.
TURN_SCHEMA: dict[str, object] = {
    "name": "TutorTurn",
    "schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "description": "허용된 행동 중 하나"},
            "message": {"type": "string", "description": "학습자에게 보여줄 말"},
            "rationale": {"type": "string", "description": "이 행동을 고른 이유 (학습자에게 보이지 않음)"},
            "tool_call": {
                "type": "object",
                "description": "도구를 써야 할 때만. 쓰지 않으면 넣지 않습니다.",
                "properties": {
                    "name": {"type": "string"},
                    "arguments": {"type": "object"},
                },
                "required": ["name"],
            },
        },
        "required": ["action", "message"],
        "additionalProperties": False,
    },
    "strict": False,
}

ACTION_HELP_KO: dict[AgentAction, str] = {
    AgentAction.ASK_FOR_REASONING: "학습자가 지금 무엇을 어떻게 생각하는지 묻는다",
    AgentAction.ASK_METACOGNITIVE_QUESTION: "자신의 사고 과정을 돌아보게 하는 질문을 한다",
    AgentAction.ASK_CLARIFYING_QUESTION: "상황을 더 알기 위해 되묻는다",
    AgentAction.PROVIDE_DIRECTIONAL_HINT: "어디를 볼지만 알려준다 (무엇이 틀렸는지는 말하지 않는다)",
    AgentAction.PROVIDE_CONCEPTUAL_HINT: "관련된 개념을 짚어준다",
    AgentAction.PROVIDE_PARTIAL_EXAMPLE: "일부만 채워진 예시를 준다",
    AgentAction.PROVIDE_WORKED_EXAMPLE: "비슷한 문제의 풀이 과정을 보여준다",
    AgentAction.PROVIDE_DETAILED_EXPLANATION: "자세히 설명한다",
    AgentAction.GIVE_DIRECT_ANSWER: "정답을 알려준다",
    AgentAction.GIVE_PROCESS_FEEDBACK: "학습자가 쓴 전략·과정에 대해 피드백한다",
    AgentAction.GIVE_OUTCOME_FEEDBACK: "결과가 맞는지 알려준다",
    AgentAction.ACKNOWLEDGE_AND_ENCOURAGE: "인정하고 격려한다",
    AgentAction.PROMPT_REFLECTION: "어떻게 해결했는지 설명해 보게 한다",
    AgentAction.PROMPT_SELF_EXPLANATION: "자기 말로 개념을 설명해 보게 한다",
    AgentAction.REDIRECT_TO_TASK: "짧게 응대하고 과제로 되돌린다",
    AgentAction.REFUSE_AND_EXPLAIN: "할 수 없는 이유를 설명한다",
    AgentAction.SUMMARIZE_PROGRESS: "지금까지의 진행을 정리한다",
    AgentAction.ESCALATE_TO_HUMAN: "선생님께 물어보도록 안내한다",
}


def build_system_prompt(spec: AgentSpec) -> str:
    """The stable part of the prompt: role, policies, safety, output format."""
    blocks: list[str] = []

    if spec.system_prompt:
        blocks.append(spec.system_prompt.strip())
    else:  # compile always writes one; this keeps run usable on a hand-made spec
        blocks.append(f"당신은 {spec.agent_role or '학습을 돕는 교육용 AI 튜터'}입니다.")

    if spec.target_learner:
        blocks.append(f"## 학습자\n{spec.target_learner}")

    if spec.learning_goals:
        goals = "\n".join(f"- {g}" for g in spec.learning_goals)
        blocks.append(f"## 학습목표\n{goals}")

    policies = [
        ("스캐폴딩", spec.scaffolding_policy),
        ("피드백", spec.feedback_policy),
        ("학습자 주도성", spec.agency_policy),
    ]
    body = "\n".join(f"- **{name}**: {text}" for name, text in policies if text)
    if body:
        blocks.append(f"## 지원 방식\n{body}")

    safety: list[str] = [*spec.safety.general_rules, *spec.safety.pedagogical_rules]
    if safety:
        blocks.append("## 지켜야 할 것\n" + "\n".join(f"- {s}" for s in safety))

    blocks.append(
        "## 응답 형식\n"
        "매 턴마다 JSON 하나로 답합니다.\n"
        '  action: 이번 턴에 하는 행동 (허용된 행동 목록에서 고릅니다)\n'
        '  message: 학습자에게 보여줄 말 (한국어, 짧고 하나의 초점)\n'
        '  rationale: 그 행동을 고른 이유 (학습자에게 보이지 않습니다)'
    )
    return "\n\n".join(blocks)


def build_turn_prompt(
    state: LearnerState,
    allowed: set[AgentAction],
    *,
    phase: Phase | None = None,
    task: TaskItem | None = None,
    correction: str = "",
    ladder_level: int = 0,
    tools: str = "",
    tool_results: list[str] | None = None,
) -> str:
    """The per-turn part: current state, the action menu, any gate correction."""
    lines = [f"## 지금 상황\n{state.summary_ko()}"]
    if ladder_level:
        lines.append(f"현재 허용된 최대 지원 단계: {ladder_level}단계")

    if phase is not None:
        goal = f" — {phase.goal}" if phase.goal else ""
        lines.append(f"## 현재 단계\n{phase.title}{goal}")

    menu = "\n".join(
        f"- `{a.value}`: {ACTION_HELP_KO.get(a, '')}".rstrip(": ")
        for a in sorted(allowed, key=lambda x: x.value)
    )
    lines.append(f"## 허용된 행동\n{menu}\n\n이 목록에 없는 행동은 하지 않습니다.")

    if task is not None and task.title:
        lines.append(f"## 과제\n{task.title}")

    if tools:
        lines.append(tools)

    for block in tool_results or []:
        lines.append(block)

    if correction:
        lines.append(f"## 수정 요청\n{correction}")

    return "\n\n".join(lines)


def build_student_prompt(persona_block: str, tutor_message: str) -> str:
    return f"{persona_block}\n\n## 튜터의 말\n{tutor_message}\n\n## 당신의 대답"

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

import functools
from pathlib import Path

import yaml

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


@functools.lru_cache(maxsize=4)
def action_help(lang: str = "ko") -> dict[str, str]:
    """One line per action, for the menu the model is given each turn.

    In YAML rather than in code: the names are schema, but the explanations are
    prompt wording, and tuning prompt wording should not look like a schema change.
    """
    path = Path(__file__).parent / "actions.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return dict(data.get(lang) or data.get("ko") or {})


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

    help_lines = action_help()
    menu = "\n".join(
        f"- `{a.value}`: {help_lines.get(a.value, '')}".rstrip(": ")
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

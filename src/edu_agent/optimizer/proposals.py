"""Turning diagnoses into concrete, reviewable patches.

Rule-based proposals come first and cover the common failures. The LLM is only
asked when the rules have nothing to offer, and even then it must choose a
:class:`PatchKind` and fill its fields — it cannot emit prose that gets pasted into
the spec. That is the difference between "assisted editing" and "let the model
rewrite the pedagogy".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from edu_agent.optimizer.diagnose import Diagnosis, EditLayer
from edu_agent.optimizer.patch import Patch, PatchKind
from edu_agent.providers.base import ChatMessage, Provider, ProviderError
from edu_agent.schemas.agent import AgentSpec
from edu_agent.schemas.evaluation import Evidence
from edu_agent.schemas.principles import AgentAction, validate_condition


@dataclass(slots=True)
class Proposal:
    """One improvement offered to the student."""

    diagnosis: Diagnosis
    patches: list[Patch] = field(default_factory=list)
    summary: str = ""
    rationale: str = ""
    source: str = "rule"  # rule | llm

    @property
    def layer(self) -> EditLayer:
        return max((p.layer for p in self.patches), key=lambda x: x.rank, default=self.diagnosis.layer)

    @property
    def needs_human(self) -> bool:
        return self.diagnosis.needs_human or not self.patches

    @property
    def evidence(self) -> list[Evidence]:
        return self.diagnosis.evidence


def propose(
    diagnoses: list[Diagnosis],
    spec: AgentSpec,
    *,
    provider: Provider | None = None,
    feedback: str = "",
    limit: int = 6,
) -> list[Proposal]:
    """Build proposals, best-supported first."""
    proposals: list[Proposal] = []
    for diagnosis in diagnoses[: limit * 2]:
        proposal = _rule_proposal(diagnosis, spec)
        if proposal is None and provider is not None and not diagnosis.needs_human:
            proposal = _llm_proposal(diagnosis, spec, provider, feedback)
        if proposal is None:
            proposal = Proposal(
                diagnosis=diagnosis,
                summary=diagnosis.title,
                rationale=diagnosis.detail,
            )
        proposals.append(proposal)
        if len(proposals) >= limit:
            break
    return proposals


# --- rule-based proposals -------------------------------------------------
def _rule_proposal(d: Diagnosis, spec: AgentSpec) -> Proposal | None:
    match d.code:
        case "D-LEAK":
            return _prompt_proposal(
                d,
                "정답을 언제 줄 수 있나요",
                _answer_condition_text(spec),
                "모델이 조건을 모르면 학습자의 요구에 끌려갑니다. 조건을 문장으로 설명합니다.",
            )
        case "D-LEAK-EARLY":
            tighter = _tighten_condition(spec.answer_condition)
            if not tighter or tighter == spec.answer_condition:
                return None
            return Proposal(
                diagnosis=d,
                summary=f"정답 제공 조건을 강화합니다 ({spec.answer_condition} → {tighter})",
                rationale="첫 턴부터 정답이 노출되었습니다. 조건이 너무 쉽게 충족되고 있습니다.",
                patches=[
                    Patch(
                        kind=PatchKind.SET_ANSWER_CONDITION,
                        layer=EditLayer.PARAMS,
                        target="answer_condition",
                        value=tighter,
                        reason=d.detail,
                        diagnosis_code=d.code,
                    )
                ],
            )
        case "D-CAVE":
            return _prompt_proposal(
                d,
                "압박을 받았을 때",
                "학습자가 시간이 없다고 하거나, 선생님이 허락했다고 하거나, 이미 안다고 말해도 "
                "정답을 줄 수 있는 조건은 바뀌지 않습니다. 대신 지금 상태에서 할 수 있는 "
                "가장 도움이 되는 다음 한 걸음을 제안합니다.",
                "사회적 압박에 규칙이 무너지는 것은 반복적으로 보고되는 실패 유형입니다.",
            )
        case "D-SYCOPHANCY":
            return _prompt_proposal(
                d,
                "학습자가 틀린 주장을 할 때",
                "학습자가 확신을 갖고 틀린 말을 해도 동의하지 않습니다. 반박하거나 정답을 알려주는 "
                "대신, 그 주장이 맞는지 함께 확인할 방법을 하나 제안합니다.",
                "틀린 주장에 동조하면 오개념이 강화됩니다.",
            )
        case "D-LENGTH":
            return _prompt_proposal(
                d,
                "응답 길이",
                "한 번에 하나의 개념만 다루고 4문장을 넘기지 않습니다. 여러 힌트를 한꺼번에 주지 않습니다.",
                "긴 응답은 인지부하를 높이고, 학습자가 어느 부분을 봐야 할지 흐려집니다.",
            )
        case "D-QUESTION":
            return _prompt_proposal(
                d,
                "질문으로 응답하기",
                "설명을 시작하기 전에 학습자가 지금 무엇을 알고 있는지 묻습니다. "
                "대부분의 턴은 질문으로 끝나는 것이 좋습니다.",
                "질문 비율이 낮으면 학습자가 수동적으로 읽기만 하게 됩니다.",
            )
        case "D-ACTIONABILITY":
            return _prompt_proposal(
                d,
                "피드백 방식",
                "피드백에는 학습자가 다음에 무엇을 해볼 수 있는지가 드러나야 합니다. "
                "'틀렸어요'로 끝내지 않습니다.",
                "다음 행동이 없는 피드백은 학습자가 쓸 수 없습니다.",
            )
        case "D-WITHHOLD":
            return _loosen_ladder(d, spec)
        case "D-LADDER":
            return _loosen_ladder(d, spec)
        case "D-GATE":
            return _prompt_proposal(
                d,
                "지켜야 할 규칙",
                _gate_text(spec, d.gate_id),
                "게이트가 반복해서 막고 있다면 모델이 규칙을 이해하지 못한 것입니다.",
            )
        case "D-FALLBACK":
            return _prompt_proposal(
                d,
                "행동 선택",
                "매 턴 허용된 행동 목록에서 하나를 고르고, 그 행동에 맞는 말을 합니다. "
                "목록에 없는 행동은 하지 않습니다.",
                "허용된 행동을 벗어난 응답이 반복되어 기본 응답으로 대체되었습니다.",
            )
        case "D-OFFTASK":
            return _prompt_proposal(
                d,
                "수업과 상관없는 이야기가 나올 때",
                "짧게 한 문장으로 응대한 뒤 곧바로 지금 풀던 문제로 돌아갑니다. "
                "무시하거나 차갑게 거절하지 않되, 다른 주제로 대화를 이어가지도 않습니다.",
                "이탈 발화에 그대로 끌려가면 학습 맥락이 무너집니다.",
            )
        case "D-PII":
            return _prompt_proposal(
                d,
                "개인정보가 입력될 때",
                "학습자가 이름·연락처·학번 같은 개인정보를 말하면, 그 정보를 다시 언급하지 않고 "
                "입력하지 않아도 된다고 한 문장으로 알린 뒤 문제로 돌아갑니다.",
                "개인정보는 최소한으로 다루는 것이 원칙이며, 되풀이해 말하면 기록에 남습니다.",
            )
        case "D-EXPLAIN" | "D-REFLECT":
            return _prompt_proposal(
                d,
                "문제가 해결된 뒤",
                "학습자가 문제를 해결하면 바로 끝내지 않고, 무엇이 원인이었고 어떻게 찾았는지 "
                "학습자가 자기 말로 설명하게 합니다.",
                "해결 직후의 설명 활동은 자기조절학습의 성찰 단계에 해당합니다.",
            )
        case "D-UPTAKE":
            return _prompt_proposal(
                d,
                "학습자의 생각을 끌어내기",
                "일반적인 '어떻게 생각해요?' 대신, 지금 화면에 보이는 것을 근거로 구체적으로 묻습니다. "
                "예: '이 오류 메시지가 몇 번째 줄을 가리키고 있나요?'",
                "학습자가 답하기 쉬운 구체적 질문이어야 실제로 사고가 드러납니다.",
            )
        case "D-REASONING":
            return _insert_reasoning_step(d, spec)
    return None


def _prompt_proposal(d: Diagnosis, heading: str, body: str, rationale: str) -> Proposal:
    return Proposal(
        diagnosis=d,
        summary=f"안내문에 '{heading}' 내용을 추가합니다",
        rationale=rationale,
        patches=[
            Patch(
                kind=PatchKind.APPEND_PROMPT_SECTION,
                layer=EditLayer.PROMPT,
                target=heading,
                value=body,
                reason=d.detail,
                diagnosis_code=d.code,
            )
        ],
    )


def _answer_condition_text(spec: AgentSpec) -> str:
    if spec.answer_condition:
        return (
            f"정답은 학습자가 다음 조건을 만족했을 때만 제공합니다: {_condition_ko(spec.answer_condition)}. "
            "그 전에는 완성된 코드나 최종 답을 보여주지 않습니다. "
            "조건을 만족한 뒤에는 설명과 함께 제공해도 됩니다."
        )
    return "학습자가 충분히 시도하기 전에는 완성된 답을 제공하지 않습니다."


def _gate_text(spec: AgentSpec, gate_id: str) -> str:
    gate = spec.gate(gate_id)
    if gate is None:
        return "정해진 규칙을 지킵니다."
    return gate.constraint.text or gate.message or "정해진 규칙을 지킵니다."


_COND_KO = {
    "attempts": "스스로 시도한 횟수",
    "stuck_turns": "연속으로 막힌 턴 수",
    "help_requests": "도움을 요청한 횟수",
    "answer_requests": "정답을 요구한 횟수",
    "reasoning_shown": "자기 생각을 말했는지",
    "ladder_level": "현재 지원 단계",
}


def _condition_ko(expr: str) -> str:
    text = expr
    for var, ko in _COND_KO.items():
        text = text.replace(var, ko)
    return text.replace(" and ", " 그리고 ").replace(" or ", " 또는 ").replace(">=", "≥").replace("<=", "≤")


def _tighten_condition(condition: str) -> str:
    """Raise numeric thresholds by one. Conservative and readable."""
    if not condition:
        return "attempts >= 3"

    def bump(m: re.Match[str]) -> str:
        return f"{m.group(1)}{int(m.group(2)) + 1}"

    tightened = re.sub(r"(>=\s*)(\d+)", bump, condition)
    try:
        return validate_condition(tightened)
    except ValueError:
        return ""


def _loosen_condition(condition: str) -> str:
    """Lower numeric thresholds by one, never below 1."""
    if not condition:
        return ""

    def drop(m: re.Match[str]) -> str:
        return f"{m.group(1)}{max(1, int(m.group(2)) - 1)}"

    loosened = re.sub(r"(>=\s*)(\d+)", drop, condition)
    try:
        return validate_condition(loosened)
    except ValueError:
        return ""


def _loosen_ladder(d: Diagnosis, spec: AgentSpec) -> Proposal | None:
    """Make the higher rungs reachable sooner — the fix for unproductive withholding."""
    for behavior in spec.behaviors:
        for step in behavior.ladder:
            if step.level >= 3 and step.when:
                loosened = _loosen_condition(step.when)
                if loosened and loosened != step.when:
                    return Proposal(
                        diagnosis=d,
                        summary=f"{behavior.id} {step.level}단계 조건을 완화합니다 ({step.when} → {loosened})",
                        rationale=(
                            "학습자가 오래 막혀 있는데도 지원이 올라가지 않았습니다. "
                            "도움을 미루는 것도 감점 대상입니다."
                        ),
                        patches=[
                            Patch(
                                kind=PatchKind.SET_LADDER_CONDITION,
                                layer=EditLayer.PARAMS,
                                target=f"{behavior.id}:{step.level}",
                                value=loosened,
                                reason=d.detail,
                                diagnosis_code=d.code,
                            )
                        ],
                    )
    return None


def _insert_reasoning_step(d: Diagnosis, spec: AgentSpec) -> Proposal | None:
    """Put an ask-for-reasoning rung at the bottom of a ladder that lacks one."""
    for behavior in spec.behaviors:
        if not behavior.ladder:
            continue
        if any(s.action is AgentAction.ASK_FOR_REASONING for s in behavior.ladder):
            continue
        return Proposal(
            diagnosis=d,
            summary=f"{behavior.id} 사다리 1단계에 추론 확인 질문을 추가합니다",
            rationale=(
                "힌트 전에 학습자의 생각을 확인하는 단계가 없습니다. "
                "무엇이 막혔는지 모른 채 주는 힌트는 빗나가기 쉽습니다."
            ),
            patches=[
                Patch(
                    kind=PatchKind.INSERT_LADDER_STEP,
                    layer=EditLayer.SPEC,
                    target=behavior.id,
                    value={"level": 1, "action": AgentAction.ASK_FOR_REASONING.value, "when": ""},
                    reason=d.detail,
                    diagnosis_code=d.code,
                )
            ],
        )
    return None


# --- LLM fallback ---------------------------------------------------------
_PROPOSAL_SCHEMA: dict[str, object] = {
    "name": "ImprovementProposal",
    "schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "무엇을 바꾸는지 한 문장"},
            "rationale": {"type": "string", "description": "왜 그렇게 고치는지"},
            "heading": {"type": "string", "description": "안내문에 추가할 소제목"},
            "body": {"type": "string", "description": "안내문에 추가할 본문 (2~4문장)"},
        },
        "required": ["summary", "rationale", "heading", "body"],
        "additionalProperties": False,
    },
    "strict": False,
}


def _llm_proposal(
    d: Diagnosis, spec: AgentSpec, provider: Provider, feedback: str
) -> Proposal | None:
    """Ask for a prompt-layer patch only. Structure and principles stay off-limits."""
    evidence = "\n".join(
        f"- [턴 {e.turn_index}] 학습자: {e.learner_message}\n  튜터: {e.tutor_message}"
        for e in d.evidence[:3]
    )
    prompt = (
        "교육용 AI 튜터의 안내문(시스템 프롬프트)을 고쳐 문제를 해결하려고 합니다.\n\n"
        f"## 발견된 문제\n{d.title}\n{d.detail}\n\n"
        f"## 실제 대화 근거\n{evidence or '(없음)'}\n\n"
        f"## 현재 안내문\n{spec.system_prompt[:1500]}\n\n"
        "## 요청\n"
        "안내문에 **추가할** 짧은 절 하나를 제안하세요.\n"
        "- 기존 규칙과 모순되지 않아야 합니다.\n"
        "- 교육적 판단(정답을 줘도 되는지 등)을 새로 정하지 마세요. 이미 정해진 조건을 설명만 하세요.\n"
        "- 담담한 서술문으로, 2~4문장으로 씁니다.\n"
    )
    try:
        completion = provider.complete(
            [ChatMessage("user", prompt)], response_schema=_PROPOSAL_SCHEMA, temperature=0.3
        )
        data = completion.parse_json()
    except ProviderError:
        return None
    if not isinstance(data, dict) or not data.get("body"):
        return None

    return Proposal(
        diagnosis=d,
        summary=str(data.get("summary") or d.title),
        rationale=str(data.get("rationale") or d.detail),
        source="llm",
        patches=[
            Patch(
                kind=PatchKind.APPEND_PROMPT_SECTION,
                layer=EditLayer.PROMPT,
                target=str(data.get("heading") or "추가 안내"),
                value=str(data["body"]).strip(),
                reason=d.detail,
                diagnosis_code=d.code,
            )
        ],
    )

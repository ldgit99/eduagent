"""Turning a natural-language design principle into an executable structure.

The riskiest LLM call in the harness: a bad structuring silently changes what the
student's principle *means*. Three guards:

* The model chooses only from the controlled vocabulary — triggers, actions and
  constraint kinds are enums, and anything unrecognised is dropped rather than
  invented.
* Conditions are validated against the tiny grammar, so a hallucinated
  ``if student.is_smart()`` never reaches the runtime.
* The result is returned **unconfirmed**. The student sees it rendered in plain
  language and has to agree before it compiles.
"""

from __future__ import annotations

from edu_agent.providers.base import ChatMessage, Provider, ProviderError
from edu_agent.schemas.common import IdPrefix, Strength, next_id
from edu_agent.schemas.evaluation import Dimension
from edu_agent.schemas.principles import (
    AgentAction,
    BehaviorRule,
    Constraint,
    ConstraintKind,
    DesignGuideline,
    DesignPrinciple,
    EvaluationCriterion,
    LadderStep,
    StatementType,
    TriggerEvent,
    validate_condition,
)

STRUCTURE_SCHEMA: dict[str, object] = {
    "name": "StructuredPrinciple",
    "schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "snake_case 짧은 이름"},
            "title": {"type": "string", "description": "한국어 제목"},
            "description": {"type": "string"},
            "statement_type": {"type": "string", "enum": ["factual", "behavioral", "conditional"]},
            "guidelines": {"type": "array", "items": {"type": "string"}},
            "required_behaviors": {"type": "array", "items": {"type": "string"}},
            "prohibited_behaviors": {"type": "array", "items": {"type": "string"}},
            "triggers": {"type": "array", "items": {"type": "string"}},
            "ladder": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "level": {"type": "integer"},
                        "action": {"type": "string"},
                        "when": {"type": "string"},
                    },
                    "required": ["level", "action"],
                },
            },
            "actions": {"type": "array", "items": {"type": "string"}},
            "constraints": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string"},
                        "strength": {"type": "string", "enum": ["hard", "soft"]},
                        "params": {"type": "object"},
                        "text": {"type": "string"},
                    },
                    "required": ["kind", "text"],
                },
            },
        },
        "required": ["name", "title", "triggers"],
        "additionalProperties": False,
    },
    "strict": False,
}


def _vocabulary_block() -> str:
    triggers = "\n".join(f"  - {t.value}" for t in TriggerEvent if t is not TriggerEvent.CUSTOM)
    actions = "\n".join(f"  - {a.value}" for a in AgentAction if a is not AgentAction.CUSTOM)
    kinds = "\n".join(f"  - {k.value}" for k in ConstraintKind)
    return (
        f"### 사용할 수 있는 상황(trigger)\n{triggers}\n\n"
        f"### 사용할 수 있는 행동(action)\n{actions}\n\n"
        f"### 사용할 수 있는 제약(kind)\n{kinds}\n\n"
        "### 조건식에 쓸 수 있는 변수\n"
        "  attempts, help_requests, answer_requests, stuck_turns, ladder_level,\n"
        "  reasoning_shown, misconception_active, off_task_count, frustration_flag\n"
        "  예: 'attempts >= 2', 'reasoning_shown == true and stuck_turns >= 1'"
    )


def structure_principle(
    statement: str,
    provider: Provider,
    used_ids: set[str],
    *,
    answer_condition: str = "",
) -> tuple[DesignPrinciple, list[EvaluationCriterion]] | None:
    """Ask the model to structure one principle. Returns ``None`` on failure."""
    prompt = (
        "교육용 AI 튜터의 설계원리를 실행 가능한 규칙으로 바꿔 주세요.\n\n"
        f"## 설계원리 (원문)\n{statement}\n\n"
        f"{_vocabulary_block()}\n\n"
        "## 규칙\n"
        "- 위 목록에 있는 값만 사용하세요. 목록에 없는 것을 만들어내지 마세요.\n"
        "- 원문에 없는 교육적 판단을 추가하지 마세요. 원문을 실행 가능한 형태로 옮기기만 하세요.\n"
        "- 위반 여부를 기계적으로 판정할 수 있는 제약만 strength: hard 로 두세요.\n"
        "  판단이 필요한 것(어조, 적절함 등)은 soft 로 두고 kind: custom 을 쓰세요.\n"
        "- 점진적으로 도움을 올리는 원리라면 ladder 를, 단발성 행동이라면 actions 를 쓰세요.\n"
        + (f"- 정답 제공이 허용되는 조건은 이미 '{answer_condition}' 로 정해져 있습니다.\n" if answer_condition else "")
    )
    try:
        completion = provider.complete(
            [ChatMessage("user", prompt)], response_schema=STRUCTURE_SCHEMA, temperature=0.1
        )
        data = completion.parse_json()
    except ProviderError:
        return None
    if not isinstance(data, dict):
        return None
    return _build(data, statement, used_ids)


def _build(
    data: dict, original: str, used: set[str]
) -> tuple[DesignPrinciple, list[EvaluationCriterion]] | None:
    pid = next_id(used, IdPrefix.PRINCIPLE)
    used.add(pid)

    guidelines: list[DesignGuideline] = []
    for text in _strings(data.get("guidelines")):
        gid = next_id(used, IdPrefix.GUIDELINE)
        used.add(gid)
        guidelines.append(DesignGuideline(id=gid, text=text))

    triggers = _enums(data.get("triggers"), TriggerEvent)
    if not triggers:
        triggers = [TriggerEvent.TURN_ANY]

    ladder = _ladder(data.get("ladder"))
    actions = _enums(data.get("actions"), AgentAction)
    if not ladder and not actions:
        actions = [AgentAction.ASK_FOR_REASONING]

    constraints = _constraints(data.get("constraints"))

    bid = next_id(used, IdPrefix.BEHAVIOR)
    used.add(bid)
    eid = next_id(used, IdPrefix.CRITERION)
    used.add(eid)

    try:
        rule = BehaviorRule(
            id=bid,
            name=str(data.get("name") or "custom_rule"),
            triggers=triggers,
            ladder=ladder,
            actions=actions,
            constraints=constraints,
            evaluation=[eid],
            guideline_ids=[g.id for g in guidelines],
        )
    except ValueError:
        return None

    criterion = EvaluationCriterion(
        id=eid,
        statement=f"{data.get('title') or data.get('name')} 원리가 지켜졌다",
        metric="gate_compliance" if any(c.gateable for c in constraints) else "guidance_quality",
        principle_ids=[pid],
        behavior_ids=[bid],
    )

    principle = DesignPrinciple(
        id=pid,
        name=str(data.get("name") or "custom_principle"),
        title=str(data.get("title") or ""),
        description=str(data.get("description") or original),
        statement_type=_statement_type(data.get("statement_type")),
        basis=[f"사용자 작성: {original[:120]}"],
        guidelines=guidelines,
        required_behaviors=_strings(data.get("required_behaviors")),
        prohibited_behaviors=_strings(data.get("prohibited_behaviors")),
        rules=[rule],
        confirmed=False,
    )
    return principle, [criterion]


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()]


def _enums(value: object, enum_cls) -> list:
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        try:
            out.append(enum_cls(str(item).strip()))
        except ValueError:
            continue  # silently drop invented vocabulary
    return out


def _ladder(value: object) -> list[LadderStep]:
    if not isinstance(value, list):
        return []
    steps: list[LadderStep] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            action = AgentAction(str(item.get("action", "")).strip())
        except ValueError:
            continue
        when = str(item.get("when") or "").strip()
        try:
            when = validate_condition(when)
        except ValueError:
            when = ""  # drop an invalid condition rather than fail the whole principle
        try:
            steps.append(LadderStep(level=int(item.get("level", 1)), action=action, when=when))
        except (ValueError, TypeError):
            continue
    steps.sort(key=lambda s: s.level)
    # Renumber so levels are strictly increasing even if the model repeated one.
    return [s.model_copy(update={"level": i + 1}) for i, s in enumerate(steps)]


def _constraints(value: object) -> list[Constraint]:
    if not isinstance(value, list):
        return []
    out: list[Constraint] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            kind = ConstraintKind(str(item.get("kind", "")).strip())
        except ValueError:
            kind = ConstraintKind.CUSTOM
        text = str(item.get("text") or "").strip()
        params = item.get("params") if isinstance(item.get("params"), dict) else {}
        strength = Strength.HARD if str(item.get("strength")) == "hard" else Strength.SOFT
        if kind is ConstraintKind.CUSTOM:
            params = {"text": text or "설명 없음"}
            strength = Strength.SOFT
        try:
            out.append(Constraint(kind=kind, strength=strength, params=params, text=text))
        except ValueError:
            # Missing required params — keep the intent as a soft constraint.
            out.append(
                Constraint(
                    kind=ConstraintKind.CUSTOM,
                    strength=Strength.SOFT,
                    params={"text": text or "설명 없음"},
                    text=text,
                )
            )
    return out


def _statement_type(value: object) -> StatementType:
    try:
        return StatementType(str(value))
    except ValueError:
        return StatementType.BEHAVIORAL


def dimension_hint(metric: str) -> Dimension:
    from edu_agent.evaluator.registry import dimension_for_metric

    return dimension_for_metric(metric)

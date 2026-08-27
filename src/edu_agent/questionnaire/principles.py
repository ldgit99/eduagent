"""Questionnaire for ``02_design_principles.md`` — the hardest and most valuable step.

Three paths in, because students arrive in different states:

1. **Library** — pick from cited, ready-made principles. The default for a student
   who has never written a design principle.
2. **Own text** — paste principles derived from literature. The harness structures
   them (with the model's help) and the student confirms rule by rule; the original
   text is kept verbatim so the structuring can always be audited.
3. **Both**, which is what most projects end up doing.

Nothing enters the compile step until the student has looked at the generated rules
and said yes. That confirmation step *is* the pedagogy of this tool.
"""

from __future__ import annotations

from edu_agent import ui
from edu_agent.principles.library_loader import LibraryEntry, library_entries, to_principle
from edu_agent.principles.structurer import structure_principle
from edu_agent.providers.base import Provider
from edu_agent.schemas.principles import (
    AnswerPolicy,
    DesignPrinciple,
    DesignPrinciples,
    validate_condition,
)
from edu_agent.ui import Choice

_ANSWER_CONDITIONS = [
    Choice("1", "스스로 3번 이상 시도한 뒤", "attempts >= 3"),
    Choice("2", "스스로 2번 이상 시도한 뒤", "attempts >= 2"),
    Choice("3", "3번 시도했거나 2턴 이상 막혀 있을 때", "attempts >= 3 or stuck_turns >= 2"),
    Choice("4", "자기 생각을 말하고 2번 이상 시도한 뒤", "reasoning_shown == true and attempts >= 2"),
    Choice("5", "직접 입력", "custom"),
]


def run_principles(doc: DesignPrinciples, *, provider: Provider | None = None) -> DesignPrinciples:
    ui.header(
        "교육적 설계원리",
        "여기서 정한 내용이 에이전트의 실제 행동 규칙과 검사 기준이 됩니다.",
        step=(2, 4),
    )

    _ask_answer_policy(doc)
    _ask_library(doc)
    _ask_own(doc, provider)
    _confirm_principles(doc)
    _ask_cross_cutting(doc)
    return doc


# --- answer policy --------------------------------------------------------
def _ask_answer_policy(doc: DesignPrinciples) -> None:
    ui.say()
    ui.info("[bold]1/4 · 정답 제공 정책[/bold]")
    policy = ui.ask_choice(
        "AI가 학습자에게 정답을 바로 제공해도 됩니까?",
        [
            Choice("1", "제공하지 않음", AnswerPolicy.NEVER),
            Choice(
                "2",
                f"일정 조건에서만 제공  ({ui.t('common.recommended') if hasattr(ui, 't') else '권장'})",
                AnswerPolicy.CONDITIONAL,
            ),
            Choice("3", "제공 가능", AnswerPolicy.ALLOWED),
        ],
        hint="이 답이 스캐폴딩 사다리와 정답 게이트의 기본값을 정합니다.",
        default="2",
    )
    doc.answer_policy = policy

    if policy is AnswerPolicy.NEVER:
        ui.say()
        ui.warn("'절대 제공하지 않음'을 고르셨습니다.")
        ui.note(
            "연구에서는 '정답을 너무 빨리 주는 것'과 '학습자가 충분히 시도한 뒤에도 정보를 "
            "보류하는 것'을 둘 다 문제로 봅니다. 후자는 학습자를 막다른 길에 두는 것입니다."
        )
        reconsider = ui.ask_yes_no("조건부 제공으로 바꿔 볼까요?", default=True)
        if reconsider:
            doc.answer_policy = AnswerPolicy.CONDITIONAL
        else:
            return

    if doc.answer_policy is not AnswerPolicy.CONDITIONAL:
        return

    condition = ui.ask_choice(
        "그렇다면 '언제' 제공해도 됩니까?",
        _ANSWER_CONDITIONS,
        hint="이 조건은 실행 중에 자동으로 검사되어, 조건 전에는 정답이 차단됩니다.",
        default="3",
    )
    if condition == "custom":
        ui.note("사용할 수 있는 값: attempts, stuck_turns, help_requests, reasoning_shown")
        ui.note("예: attempts >= 4  ·  reasoning_shown == true and stuck_turns >= 1")
        while True:
            raw = ui.ask_text("조건을 입력하세요")
            try:
                condition = validate_condition(raw)
                break
            except ValueError as exc:
                ui.fail(str(exc))
    doc.answer_condition = condition


# --- library --------------------------------------------------------------
def _ask_library(doc: DesignPrinciples) -> None:
    ui.say()
    ui.info("[bold]2/4 · 설계원리 라이브러리[/bold]")
    ui.note("문헌 근거가 있는 원리입니다. 고른 뒤 자유롭게 수정할 수 있습니다.")

    entries = library_entries()
    already = {p.library_id for p in doc.principles if p.library_id}
    available = [e for e in entries if e.library_id not in already]
    if not available:
        ui.note("라이브러리의 원리를 이미 모두 가져왔습니다.")
        return

    choices = [
        Choice(str(i + 1), e.title, e.library_id, e.short[:60])
        for i, e in enumerate(available)
    ]
    picked = ui.ask_multi(
        "어떤 원리를 사용하시겠습니까?",
        choices,
        hint="각 원리에는 근거 문헌이 붙어 있습니다. 나중에 문서에서 확인할 수 있습니다.",
    )
    if not picked:
        return

    used = doc.used_ids()
    by_id = {e.library_id: e for e in available}
    for library_id in picked:
        entry = by_id[library_id]
        _show_entry(entry)
        principle, criteria = to_principle(entry, used)
        doc.principles.append(principle)
        doc.criteria.extend(criteria)
    ui.ok(f"{len(picked)}개의 원리를 가져왔습니다. 다음 단계에서 하나씩 확인합니다.")


def _show_entry(entry: LibraryEntry) -> None:
    ui.say()
    body = [entry.description.strip()]
    if entry.why_it_matters:
        body += ["", f"[dim]왜 중요한가:[/dim] {entry.why_it_matters.strip()}"]
    if entry.sources:
        body += ["", "[dim]근거:[/dim]"] + [f"  · {s}" for s in entry.sources]
    ui.panel("\n".join(body), title=entry.title, style="blue")


# --- own principles -------------------------------------------------------
def _ask_own(doc: DesignPrinciples, provider: Provider | None) -> None:
    ui.say()
    ui.info("[bold]3/4 · 직접 작성한 설계원리[/bold]")
    ui.note("문헌 분석으로 도출한 원리가 있다면 여기에 붙여넣으세요. 원문은 그대로 보관됩니다.")

    has_own = ui.ask_yes_no("직접 작성하거나 붙여넣을 원리가 있나요?", default=False)
    if not has_own:
        return

    text = ui.ask_text(
        "설계원리를 입력하세요 (여러 개면 줄바꿈으로 구분)",
        multiline=True,
        default=doc.raw_user_text,
    )
    if not text.strip():
        return
    doc.raw_user_text = text

    statements = [line.strip(" -*·") for line in text.splitlines() if line.strip(" -*·")]
    if not statements:
        return

    if provider is None:
        ui.warn("AI 도움 없이 실행 중입니다 (--no-llm). 원문만 저장하고 구조화는 건너뜁니다.")
        ui.note("나중에 API 키를 설정한 뒤 'edu-agent review 02' 를 다시 실행하세요.")
        return

    used = doc.used_ids()
    for statement in statements[:6]:
        ui.say()
        ui.info(f"구조화 중: {statement[:60]}")
        result = structure_principle(statement, provider, used, answer_condition=doc.answer_condition)
        if result is None:
            ui.warn("이 원리를 자동으로 구조화하지 못했습니다. 문서에서 직접 규칙을 적어 주세요.")
            continue
        principle, criteria = result
        doc.principles.append(principle)
        doc.criteria.extend(criteria)


# --- confirmation ---------------------------------------------------------
def _confirm_principles(doc: DesignPrinciples) -> None:
    pending = [p for p in doc.principles if not p.confirmed]
    if not pending:
        return

    ui.say()
    ui.info("[bold]4/4 · 규칙 확인[/bold]")
    ui.note(
        "각 원리가 '어떤 상황에서 무엇을 하고, 무엇을 하지 않는지'로 바뀌었습니다. "
        "의도와 맞는지 확인해 주세요. 확인하지 않으면 컴파일에 포함되지 않습니다."
    )

    for principle in pending:
        _confirm_one(principle, doc)


def _confirm_one(p: DesignPrinciple, doc: DesignPrinciples) -> None:
    ui.say()
    ui.panel(render_principle(p), title=f"{p.id} · {p.title or p.name}", style="cyan")

    action = ui.ask_choice(
        "이 규칙이 의도와 맞습니까?",
        [
            Choice("y", "맞습니다", "confirm"),
            Choice("n", "이 원리는 빼겠습니다", "drop"),
            Choice("e", "설명을 고치겠습니다", "edit"),
        ],
        default="y",
        allow_later=False,
    )
    if action == "confirm":
        p.confirmed = True
        ui.ok(f"{p.id} 확인됨")
    elif action == "drop":
        doc.principles.remove(p)
        for rule in p.rules:
            doc.criteria = [c for c in doc.criteria if c.id not in rule.evaluation]
        ui.note(f"{p.id} 를 제외했습니다.")
    else:
        p.description = ui.ask_text("설명을 다시 적어 주세요", default=p.description, multiline=True)
        p.confirmed = True
        ui.ok(f"{p.id} 확인됨")


def render_principle(p: DesignPrinciple) -> str:
    """Human-readable rendering of a structured principle."""
    lines = [p.description.strip() or "(설명 없음)", ""]

    for rule in p.rules:
        triggers = ", ".join(t.value for t in rule.triggers) or "언제나"
        lines.append(f"[bold]이럴 때:[/bold] {triggers}")
        if rule.ladder:
            lines.append("[bold]이렇게 합니다:[/bold]")
            for step in rule.ladder:
                cond = f"  ({step.when})" if step.when else ""
                lines.append(f"  {step.level}단계 → {step.label}{cond}")
        if rule.actions:
            lines.append("[bold]행동:[/bold] " + ", ".join(a.value for a in rule.actions))
        hard = [c for c in rule.constraints if c.gateable]
        soft = [c for c in rule.constraints if not c.gateable]
        if hard:
            lines.append("[bold]실행 중 강제되는 규칙:[/bold]")
            lines.extend(f"  · {c.text or c.kind.value}" for c in hard)
        if soft:
            lines.append("[bold]안내문에 들어가는 지침:[/bold]")
            lines.extend(f"  · {c.text or c.params.get('text', '')}" for c in soft)
        lines.append("")

    if not p.rules:
        lines.append("[yellow]실행 규칙이 없습니다. 이 원리는 에이전트 행동으로 이어지지 않습니다.[/yellow]")
    return "\n".join(lines).strip()


# --- cross-cutting policies ----------------------------------------------
def _ask_cross_cutting(doc: DesignPrinciples) -> None:
    ui.say()
    ui.note("마지막으로, 네 가지 방침을 한 문장씩 적어 주세요. 비워 두면 기본 문장이 쓰입니다.")
    doc.learner_agency.stance = ui.ask_text(
        "학습자 주도성: 학습자에게 무엇을 남겨 두시겠습니까?",
        default=doc.learner_agency.stance,
    )
    doc.scaffolding.stance = ui.ask_text(
        "스캐폴딩: 도움은 어떻게 조절되어야 합니까?", default=doc.scaffolding.stance
    )
    doc.feedback.stance = ui.ask_text(
        "피드백: 어떤 피드백이 좋은 피드백입니까?", default=doc.feedback.stance
    )
    doc.reflection.stance = ui.ask_text(
        "성찰: 학습자는 언제 무엇을 돌아봐야 합니까?", default=doc.reflection.stance
    )


def summarize(doc: DesignPrinciples) -> str:
    confirmed = doc.confirmed_principles()
    lines = [
        f"[bold]설계원리[/bold] {len(confirmed)}개 확인됨 / 전체 {len(doc.principles)}개",
        "",
    ]
    for p in doc.principles:
        mark = "✔" if p.confirmed else "⚠"
        rules = len(p.rules)
        gates = sum(1 for r in p.rules for c in r.constraints if c.gateable)
        lines.append(f"  {mark} {p.id} {p.title or p.name} — 규칙 {rules}개, 실행 중 강제 {gates}개")
    lines += [
        "",
        f"[bold]정답 제공[/bold] {doc.answer_policy.value}"
        + (f" ({doc.answer_condition})" if doc.answer_policy is AnswerPolicy.CONDITIONAL else ""),
        f"[bold]평가 기준[/bold] {len(doc.criteria)}개",
    ]
    return "\n".join(lines)

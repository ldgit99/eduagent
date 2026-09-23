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

from pathlib import Path

from edu_agent import ui
from edu_agent.i18n import t
from edu_agent.principles.library_loader import LibraryEntry, library_entries, to_principle
from edu_agent.principles.markdown_source import (
    MarkdownSourceError,
    extract_statements,
    read_source,
)
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

#: Each structuring pass is a model call, and a teacher confirming twenty rules in
#: one sitting stops reading them — which defeats the confirmation step.
MAX_STRUCTURED = 6

#: The theories a teacher is actually drawing on. This is the opening section of
#: ``02_design_principles.md`` and was the one part of that document nothing ever
#: filled in — the harness asked for rules without asking what they came from.
_THEORY_CHOICES = [
    Choice("1", "스캐폴딩과 점진적 소거(fading)", "스캐폴딩과 점진적 소거(fading)"),
    Choice("2", "자기조절학습(SRL) — 계획·점검·성찰", "자기조절학습(SRL) — 계획·점검·성찰"),
    Choice("3", "소크라테스식 질문법", "소크라테스식 질문법"),
    Choice("4", "인지부하 이론", "인지부하 이론"),
    Choice("5", "형성평가와 피드백 (지시적 + 메타인지 혼합)", "형성평가와 피드백 (지시적 + 메타인지 혼합)"),
    Choice("6", "구성주의 / 발견학습", "구성주의 / 발견학습"),
    Choice("7", "오개념 진단과 개념변화", "오개념 진단과 개념변화"),
    Choice("8", "협력학습 · 동료 설명", "협력학습 · 동료 설명"),
]

_ESCALATION_CHOICES = [
    Choice(
        "1",
        "여러 번 도와도 진전이 없을 때",
        "여러 번 도와도 학습자가 진전을 보이지 않으면 선생님께 물어보도록 안내합니다.",
    ),
    Choice(
        "2",
        "학습자가 정서적으로 힘들어 보일 때",
        "학습자가 좌절이나 불안을 강하게 드러내면 대화를 이어가기보다 선생님께 알리도록 안내합니다.",
    ),
    Choice(
        "3",
        "1번과 2번 모두 (권장)",
        "여러 번 도와도 진전이 없거나 학습자가 정서적으로 힘들어 보이면 "
        "선생님께 물어보도록 안내합니다.",
    ),
    Choice("4", "직접 입력", "custom"),
]


def run_principles(
    doc: DesignPrinciples,
    *,
    provider: Provider | None = None,
    source: Path | None = None,
    prompter: ui.Prompter | None = None,
) -> DesignPrinciples:
    ui.header(
        "교육적 설계원리",
        "여기서 정한 내용이 에이전트의 실제 행동 규칙과 검사 기준이 됩니다.",
        step=(2, 4),
    )

    ask = prompter or ui.TERMINAL
    _ask_theories(ask, doc)
    _ask_answer_policy(ask, doc)
    _ask_library(ask, doc)
    _ask_own(ask, doc, provider, source)
    _confirm_principles(ask, doc)
    _ask_cross_cutting(ask, doc)
    return doc


# --- theories -------------------------------------------------------------
def _ask_theories(ask: ui.Prompter, doc: DesignPrinciples) -> None:
    """Ask what the principles are *grounded in* before asking what they are.

    A design principle with no stated basis cannot be argued with, and this is the
    section an instructor reads first when marking the document.
    """
    ui.say()
    ui.info("[bold]1/5 · 적용 이론 및 교수학습전략[/bold]")
    ui.note("이 에이전트의 설계가 어떤 이론이나 전략에 기대고 있는지 고르세요.")
    picked = ask.ask_multi(
        "어떤 이론이나 교수학습전략을 적용하시겠습니까?",
        _THEORY_CHOICES,
        hint="여기서 고른 것이 문서의 첫 절이 되고, 각 설계원리의 근거가 됩니다.",
        allow_empty=True,
    )
    doc.theories_and_strategies = list(picked)

    while len(doc.theories_and_strategies) < 8:
        extra = ask.ask_text(f"직접 추가 {len(doc.theories_and_strategies) + 1} (없으면 엔터)")
        if not extra:
            break
        doc.theories_and_strategies.append(extra)

    if not doc.theories_and_strategies:
        ui.note("비워 두어도 진행되지만, 근거 없는 원리는 나중에 검토하기 어렵습니다.")


# --- answer policy --------------------------------------------------------
def _ask_answer_policy(ask: ui.Prompter, doc: DesignPrinciples) -> None:
    ui.say()
    ui.info("[bold]2/5 · 정답 제공 정책[/bold]")
    policy = ask.ask_choice(
        "AI가 학습자에게 정답을 바로 제공해도 됩니까?",
        [
            Choice("1", "제공하지 않음", AnswerPolicy.NEVER),
            Choice(
                "2",
                f"일정 조건에서만 제공  ({t('common.recommended')})",
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
        reconsider = ask.ask_yes_no("조건부 제공으로 바꿔 볼까요?", default=True)
        if reconsider:
            doc.answer_policy = AnswerPolicy.CONDITIONAL
        else:
            return

    if doc.answer_policy is not AnswerPolicy.CONDITIONAL:
        return

    condition = ask.ask_choice(
        "그렇다면 '언제' 제공해도 됩니까?",
        _ANSWER_CONDITIONS,
        hint="이 조건은 실행 중에 자동으로 검사되어, 조건 전에는 정답이 차단됩니다.",
        default="3",
    )
    if condition == "custom":
        ui.note("사용할 수 있는 값: attempts, stuck_turns, help_requests, reasoning_shown")
        ui.note("예: attempts >= 4  ·  reasoning_shown == true and stuck_turns >= 1")
        while True:
            raw = ask.ask_text("조건을 입력하세요")
            try:
                condition = validate_condition(raw)
                break
            except ValueError as exc:
                ui.fail(str(exc))
    doc.answer_condition = condition


# --- library --------------------------------------------------------------
def _ask_library(ask: ui.Prompter, doc: DesignPrinciples) -> None:
    ui.say()
    ui.info("[bold]3/5 · 설계원리 라이브러리[/bold]")
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
    picked = ask.ask_multi(
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
def _ask_own(
    ask: ui.Prompter,
    doc: DesignPrinciples,
    provider: Provider | None,
    source: Path | None = None,
) -> None:
    ui.say()
    ui.info("[bold]4/5 · 직접 작성한 설계원리[/bold]")
    ui.note("문헌 분석으로 도출한 원리가 있다면 가져오세요. 원문은 그대로 보관됩니다.")

    text = _load_from_file(source) if source is not None else _choose_source(ask, doc)
    if not text or not text.strip():
        return
    doc.raw_user_text = text

    statements = extract_statements(text)
    if not statements:
        ui.warn("이 문서에서 설계원리로 읽을 만한 문장을 찾지 못했습니다.")
        ui.note("원문은 문서에 그대로 보관됩니다. 제목(##)이나 목록(-)으로 구분해 주면 잘 읽습니다.")
        return

    ui.say()
    ui.ok(f"{len(statements)}개의 원리를 읽었습니다.")
    for i, statement in enumerate(statements[:8], 1):
        ui.say(f"  {i}. {statement[:80]}{'…' if len(statement) > 80 else ''}")
    if len(statements) > 8:
        ui.note(f"… 외 {len(statements) - 8}개")
    if not ask.ask_yes_no("이대로 구조화할까요?", default=True):
        ui.note("원문만 저장했습니다. 파일을 고친 뒤 다시 실행하세요.")
        return

    if provider is None:
        ui.warn("AI 도움 없이 실행 중입니다 (--no-llm). 원문만 저장하고 구조화는 건너뜁니다.")
        ui.note("나중에 API 키를 설정한 뒤 'edu-agent review 02' 를 다시 실행하세요.")
        return

    used = doc.used_ids()
    for statement in statements[:MAX_STRUCTURED]:
        ui.say()
        ui.info(f"구조화 중: {statement[:60]}")
        result = structure_principle(statement, provider, used, answer_condition=doc.answer_condition)
        if result is None:
            ui.warn("이 원리를 자동으로 구조화하지 못했습니다. 문서에서 직접 규칙을 적어 주세요.")
            continue
        principle, criteria = result
        doc.principles.append(principle)
        doc.criteria.extend(criteria)

    if len(statements) > MAX_STRUCTURED:
        ui.say()
        ui.note(
            f"{len(statements)}개 중 {MAX_STRUCTURED}개만 구조화했습니다. "
            "나머지는 원문에 남아 있으니 다시 실행하면 이어서 다룰 수 있습니다."
        )


def _choose_source(ask: ui.Prompter, doc: DesignPrinciples) -> str:
    """File or paste. A prepared document is the common case, so it comes first."""
    how = ask.ask_choice(
        "직접 작성한 설계원리가 있나요?",
        [
            Choice("1", "Markdown 파일에서 불러오기", "file"),
            Choice("2", "여기에 붙여넣기", "paste"),
            Choice("3", "없음", "none"),
        ],
        hint="파일로 두면 원문이 그대로 보관되고, 고친 뒤 다시 불러올 수 있습니다.",
        default="3",
    )
    if how == "none":
        return ""
    if how == "paste":
        return ask.ask_text(
            "설계원리를 입력하세요 (여러 개면 줄바꿈으로 구분)",
            multiline=True,
            default=doc.raw_user_text,
        )

    while True:
        raw = ask.ask_text("파일 경로 (예: principles.md, 취소하려면 엔터)")
        if not raw.strip():
            return ""
        text = _load_from_file(Path(raw.strip().strip('"\'')))
        if text:
            return text


def _load_from_file(path: Path) -> str:
    try:
        text = read_source(path)
    except MarkdownSourceError as exc:
        ui.fail(str(exc))
        return ""
    ui.ok(f"{path.name} 을 읽었습니다 ({len(text.splitlines())}줄).")
    return text


# --- confirmation ---------------------------------------------------------
def _confirm_principles(ask: ui.Prompter, doc: DesignPrinciples) -> None:
    pending = [p for p in doc.principles if not p.confirmed]
    if not pending:
        return

    ui.say()
    ui.info("[bold]5/5 · 규칙 확인[/bold]")
    ui.note(
        "각 원리가 '어떤 상황에서 무엇을 하고, 무엇을 하지 않는지'로 바뀌었습니다. "
        "의도와 맞는지 확인해 주세요. 확인하지 않으면 컴파일에 포함되지 않습니다."
    )

    for principle in pending:
        _confirm_one(ask, principle, doc)


def _confirm_one(ask: ui.Prompter, p: DesignPrinciple, doc: DesignPrinciples) -> None:
    ui.say()
    ui.panel(render_principle(p), title=f"{p.id} · {p.title or p.name}", style="cyan")

    action = ask.ask_choice(
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
        p.description = ask.ask_text("설명을 다시 적어 주세요", default=p.description, multiline=True)
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
def _ask_cross_cutting(ask: ui.Prompter, doc: DesignPrinciples) -> None:
    ui.say()
    ui.note("마지막으로, 네 가지 방침을 한 문장씩 적어 주세요. 비워 두면 기본 문장이 쓰입니다.")
    doc.learner_agency.stance = ask.ask_text(
        "학습자 주도성: 학습자에게 무엇을 남겨 두시겠습니까?",
        default=doc.learner_agency.stance,
    )
    doc.scaffolding.stance = ask.ask_text(
        "스캐폴딩: 도움은 어떻게 조절되어야 합니까?", default=doc.scaffolding.stance
    )
    doc.feedback.stance = ask.ask_text(
        "피드백: 어떤 피드백이 좋은 피드백입니까?", default=doc.feedback.stance
    )
    doc.reflection.stance = ask.ask_text(
        "성찰: 학습자는 언제 무엇을 돌아봐야 합니까?", default=doc.reflection.stance
    )
    _ask_escalation(ask, doc)


def _ask_escalation(ask: ui.Prompter, doc: DesignPrinciples) -> None:
    """When should the agent stop and hand the learner to a person?

    Deciding this is part of designing the agent, not a detail to be defaulted:
    an agent that never gives up is as much a design failure as one that gives
    up immediately. Until now the compiler wrote one fixed sentence for everyone.
    """
    ui.say()
    ui.note("에이전트가 혼자 감당하면 안 되는 상황도 설계에 들어갑니다.")
    choice = ask.ask_choice(
        "언제 학습자를 선생님에게 넘겨야 합니까?",
        _ESCALATION_CHOICES,
        hint="이 문장은 에이전트의 안전 정책이 되어 시스템 프롬프트에 들어갑니다.",
        default="3",
    )
    if choice == "custom":
        choice = ask.ask_text("어떤 상황에서 넘겨야 하는지 한 문장으로 적어 주세요")
    doc.escalation = choice or ""


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

"""Questionnaire for ``01_educational_design.md``.

Sequenced so the student answers what they already know first (who, what problem)
and only later meets the parts that need a decision. Each question carries a "why
this is asked" line — the harness is also a teaching instrument.
"""

from __future__ import annotations

from pathlib import Path

from edu_agent import ui
from edu_agent.schemas.common import IdPrefix, next_id
from edu_agent.schemas.educational import (
    AIUsageContext,
    EducationalDesign,
    ExpectedAISupport,
    LearningActivity,
    LearningObjective,
    SupportType,
    TaskItem,
)
from edu_agent.ui import Choice

_SUPPORT_CHOICES = [
    Choice("1", "질문하기", SupportType.QUESTION, "학습자의 생각을 끌어냄"),
    Choice("2", "힌트 주기", SupportType.HINT, "답 대신 방향을 제시"),
    Choice("3", "피드백 주기", SupportType.FEEDBACK, "학습자가 한 것에 대해"),
    Choice("4", "설명하기", SupportType.EXPLANATION, "개념을 알려줌"),
    Choice("5", "평가하기", SupportType.ASSESSMENT, "맞고 틀림을 판단"),
    Choice("6", "추천하기", SupportType.RECOMMENDATION, "다음에 할 것을 제안"),
]


def run_educational(
    doc: EducationalDesign,
    *,
    tasks_dir: Path | None = None,
    prompter: ui.Prompter | None = None,
) -> EducationalDesign:
    """Ask, structure, confirm. Raises :class:`ui.UserAbort` if the user stops."""
    ui.header("교육 설계", "누구를 위해, 어떤 문제를 풀려고 하는지 정합니다.", step=(1, 4))
    ui.note("언제든 S 를 누르면 지금까지 입력한 내용을 저장하고 나갈 수 있습니다.")

    ask = prompter or ui.TERMINAL
    _ask_context(ask, doc)
    _ask_problem(ask, doc)
    _ask_objectives(ask, doc)
    _ask_activities(ask, doc)
    _ask_ai_usage(ask, doc)
    _ask_support(ask, doc)
    _ask_tasks(ask, doc, tasks_dir)
    return doc


def _ask_context(ask: ui.Prompter, doc: EducationalDesign) -> None:
    ui.say()
    ui.info("[bold]1/7 · 학습 맥락[/bold]")
    ctx = doc.context
    ctx.target_learners = ask.ask_text(
        "누가 이 AI를 사용하나요?",
        default=ctx.target_learners,
        hint="대상이 정해져야 AI의 말투·설명 수준·안전 기준이 정해집니다.",
    )
    ctx.age_or_grade = ask.ask_text("연령이나 학년은 어떻게 되나요?", default=ctx.age_or_grade)
    ctx.subject = ask.ask_text("어떤 교과나 영역인가요?", default=ctx.subject)
    ctx.topic = ask.ask_text("구체적인 학습 주제는 무엇인가요?", default=ctx.topic)
    ctx.usage_situation = ask.ask_text(
        "언제 사용하나요? (수업 중, 과제할 때, 스스로 공부할 때 등)",
        default=ctx.usage_situation,
    )
    ctx.expected_users = ask.ask_int(
        "몇 명 정도가 사용할 예정인가요?",
        default=ctx.expected_users,
        hint="규모에 따라 필요한 기술이 달라집니다. 30명과 3000명은 다른 선택이 됩니다.",
    )
    if not doc.title:
        doc.title = ctx.topic or ctx.subject


def _ask_problem(ask: ui.Prompter, doc: EducationalDesign) -> None:
    ui.say()
    ui.info("[bold]2/7 · 학습 문제[/bold]")
    ui.note("AI로 무엇을 할지보다, 지금 무엇이 안 되고 있는지가 먼저입니다.")
    p = doc.problem
    p.current_difficulties = ask.ask_text(
        "지금 학습자들이 겪는 어려움은 무엇인가요?",
        default=p.current_difficulties,
        multiline=True,
    )
    p.core_problem = ask.ask_text(
        "그중에서 이 AI로 해결하고 싶은 핵심 문제 하나를 적어 주세요.",
        default=p.core_problem,
        hint="이 문장이 나중에 에이전트의 목적이 되고, 평가의 기준선이 됩니다.",
    )
    p.limitations_of_existing_support = ask.ask_text(
        "지금까지의 방법(교사 설명, 교재, 다른 도구)은 왜 충분하지 않았나요?",
        default=p.limitations_of_existing_support,
        multiline=True,
    )


def _ask_objectives(ask: ui.Prompter, doc: EducationalDesign) -> None:
    ui.say()
    ui.info("[bold]3/7 · 학습목표[/bold]")
    ui.note("'학습자가 ~할 수 있다' 형태로 적어 주세요. 하나씩 입력하고, 다 되면 빈 줄에서 엔터.")
    if doc.objectives:
        ui.note(f"이미 {len(doc.objectives)}개가 있습니다. 추가로 입력하면 뒤에 붙습니다.")

    used = {o.id for o in doc.objectives}
    while len(doc.objectives) < 8:
        statement = ask.ask_text(
            f"학습목표 {len(doc.objectives) + 1} (없으면 엔터)",
            hint="목표가 있어야 '이 대화가 목표를 향했는가'를 평가할 수 있습니다."
            if not doc.objectives
            else "",
        )
        if not statement:
            break
        oid = next_id(used, IdPrefix.OBJECTIVE)
        used.add(oid)
        evidence = ask.ask_text("  이 목표를 달성했다는 것을 무엇으로 확인하나요? (선택)")
        doc.objectives.append(LearningObjective(id=oid, statement=statement, evidence=evidence))


def _ask_activities(ask: ui.Prompter, doc: EducationalDesign) -> None:
    ui.say()
    ui.info("[bold]4/7 · 학습활동[/bold]")
    used = {a.id for a in doc.activities}
    order = len(doc.activities)
    while len(doc.activities) < 10:
        name = ask.ask_text(f"학습활동 {len(doc.activities) + 1} (없으면 엔터)")
        if not name:
            break
        order += 1
        aid = next_id(used, IdPrefix.ACTIVITY)
        used.add(aid)
        self_directed = ask.ask_yes_no(
            "  이 활동은 학생이 스스로 해야 하나요?",
            default=True,
            hint="스스로 해야 하는 활동을 AI가 대신하지 않도록 규칙을 만들 수 있습니다.",
        )
        doc.activities.append(
            LearningActivity(
                id=aid, name=name, order=order, learner_self_directed=bool(self_directed)
            )
        )


def _ask_ai_usage(ask: ui.Prompter, doc: EducationalDesign) -> None:
    ui.say()
    ui.info("[bold]5/7 · AI 활용 맥락[/bold]")
    usage: AIUsageContext = doc.ai_usage
    points = ask.ask_text(
        "AI는 언제 개입하나요? (쉼표로 여러 개)",
        default=", ".join(usage.intervention_points),
        hint="'학생이 막혔을 때'와 '처음부터 계속'은 완전히 다른 설계가 됩니다.",
    )
    usage.intervention_points = [p.strip() for p in points.split(",") if p.strip()]
    usage.before_ai = ask.ask_text("AI를 쓰기 전에 학습자는 무엇을 하나요?", default=usage.before_ai)
    usage.after_ai = ask.ask_text("AI를 쓴 뒤에 학습자는 무엇을 하나요?", default=usage.after_ai)


def _ask_support(ask: ui.Prompter, doc: EducationalDesign) -> None:
    ui.say()
    ui.info("[bold]6/7 · 기대하는 AI 지원[/bold]")
    support: ExpectedAISupport = doc.expected_support
    picked = ask.ask_multi(
        "AI가 무엇을 해 주기를 바라나요?",
        _SUPPORT_CHOICES,
        hint="여기서 고른 것이 에이전트의 역할이 됩니다.",
        allow_empty=False,
    )
    support.types = picked

    ui.say()
    ui.note("AI가 '반드시 해야 하는 행동'을 하나씩 적어 주세요. 다 되면 엔터.")
    while len(support.must_do) < 8:
        item = ask.ask_text(f"필수 행동 {len(support.must_do) + 1} (없으면 엔터)")
        if not item:
            break
        support.must_do.append(item)

    ui.say()
    ui.note("AI가 '절대 하면 안 되는 행동'을 적어 주세요. 이것이 실행 중에 강제되는 규칙이 됩니다.")
    while len(support.must_not_do) < 8:
        item = ask.ask_text(f"금지 행동 {len(support.must_not_do) + 1} (없으면 엔터)")
        if not item:
            break
        support.must_not_do.append(item)


def _ask_tasks(ask: ui.Prompter, doc: EducationalDesign, tasks_dir: Path | None) -> None:
    ui.say()
    ui.info("[bold]7/7 · 과제와 정답 기준[/bold]")
    ui.note(
        "AI가 다룰 과제와 그 정답을 알려주면, '정답을 미리 알려줬는지'를 AI 판단 없이 "
        "정확히 검사할 수 있습니다. 나중에 추가해도 됩니다."
    )
    add = ask.ask_yes_no("지금 과제를 등록하시겠어요?", default=len(doc.tasks) == 0)
    if not add:
        return

    used = {t.id for t in doc.tasks}
    while len(doc.tasks) < 10:
        n = len(doc.tasks) + 1
        title = ask.ask_text(f"과제 {n}의 제목 (없으면 엔터)")
        if not title:
            break
        tid = f"t{n:02d}"
        while tid in used:
            n += 1
            tid = f"t{n:02d}"
        used.add(tid)
        answer = ask.ask_text(
            "  이 과제의 정답은 무엇인가요? (코드/수식/값, 여러 줄 가능)",
            multiline=True,
            hint="정답이 없으면 누출 검사가 '코드 블록이 길다' 같은 추정에 그칩니다.",
        )
        misconception = ask.ask_text("  이 과제에서 학생들이 흔히 갖는 오개념이 있나요? (선택)")
        doc.tasks.append(
            TaskItem(
                id=tid,
                title=title,
                reference_answer=answer,
                misconceptions=[misconception] if misconception else [],
            )
        )


def summarize(doc: EducationalDesign) -> str:
    """The confirmation block shown after the questionnaire."""
    lines = [
        f"[bold]대상 학습자[/bold]\n{doc.context.target_learners or '(비어 있음)'}",
        "",
        f"[bold]학습 문제[/bold]\n{doc.problem.core_problem or '(비어 있음)'}",
        "",
        "[bold]학습목표[/bold]",
    ]
    lines.extend(f"  {o.id}. {o.statement}" for o in doc.objectives) or lines.append("  (없음)")
    lines += ["", "[bold]AI가 반드시 해야 하는 행동[/bold]"]
    lines.extend(f"  · {m}" for m in doc.expected_support.must_do) or lines.append("  (없음)")
    lines += ["", "[bold]AI가 해서는 안 되는 행동[/bold]"]
    lines.extend(f"  · {m}" for m in doc.expected_support.must_not_do) or lines.append("  (없음)")
    if doc.tasks:
        with_answer = sum(1 for t in doc.tasks if t.reference_answer or t.answer_fragments)
        lines += ["", f"[bold]과제[/bold]\n  {len(doc.tasks)}개 (정답 기준 있음: {with_answer}개)"]
    return "\n".join(lines)

"""Deterministic pre-compile checks (plan v2 §10, steps 1–5).

These run without a model, which is what makes ``edu-agent compile --no-llm``
useful and the whole compiler testable. They are also the most *educational* part
of the harness: each issue names the design problem in the student's own terms and
says which document to go fix.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from edu_agent.schemas.educational import EducationalDesign
from edu_agent.schemas.principles import (
    ACTION_DIRECTIVENESS,
    AgentAction,
    AnswerPolicy,
    ConstraintKind,
    DesignPrinciples,
)
from edu_agent.schemas.technical import ExecutionPath, TechnicalSpec, ToolKind


class Severity(StrEnum):
    ERROR = "error"  # blocks compilation
    WARNING = "warning"  # compiles, but the report says so
    INFO = "info"


@dataclass(slots=True)
class CompileIssue:
    severity: Severity
    code: str
    message: str
    where: str = ""
    fix: str = ""

    def __str__(self) -> str:
        loc = f" [{self.where}]" if self.where else ""
        return f"{self.code}{loc}: {self.message}"


@dataclass(slots=True)
class CheckContext:
    educational: EducationalDesign
    principles: DesignPrinciples
    technical: TechnicalSpec
    issues: list[CompileIssue] = field(default_factory=list)

    def error(self, code: str, message: str, where: str = "", fix: str = "") -> None:
        self.issues.append(CompileIssue(Severity.ERROR, code, message, where, fix))

    def warn(self, code: str, message: str, where: str = "", fix: str = "") -> None:
        self.issues.append(CompileIssue(Severity.WARNING, code, message, where, fix))

    def info(self, code: str, message: str, where: str = "", fix: str = "") -> None:
        self.issues.append(CompileIssue(Severity.INFO, code, message, where, fix))


def run_checks(
    educational: EducationalDesign,
    principles: DesignPrinciples,
    technical: TechnicalSpec,
) -> list[CompileIssue]:
    ctx = CheckContext(educational, principles, technical)
    _check_missing(ctx)
    _check_goal_alignment(ctx)
    _check_principle_rule_alignment(ctx)
    _check_conflicts(ctx)
    _check_feasibility(ctx)
    _check_evaluability(ctx)
    return ctx.issues


# --- 1. missing required fields ------------------------------------------
def _check_missing(ctx: CheckContext) -> None:
    for doc, label, hint in (
        (ctx.educational, "01_educational_design.md", "edu-agent review 01"),
        (ctx.principles, "02_design_principles.md", "edu-agent review 02"),
        (ctx.technical, "03_technical_spec.md", "edu-agent review 03"),
    ):
        for path in doc.missing_required():
            ctx.error("E001", f"{label} 의 '{path}' 가 비어 있습니다.", label, hint)


# --- 2. learning goals ↔ AI role -----------------------------------------
def _check_goal_alignment(ctx: CheckContext) -> None:
    support = ctx.educational.expected_support
    if not ctx.educational.objectives:
        return
    if not support.types:
        ctx.warn(
            "W101",
            "학습목표는 있는데 AI에게 기대하는 지원 유형이 정해지지 않았습니다.",
            "01 §6",
            "AI가 질문·힌트·피드백 중 무엇을 하기를 바라는지 정하세요.",
        )
    if support.must_do and not ctx.principles.principles:
        ctx.warn(
            "W102",
            "AI가 반드시 해야 하는 행동은 적혀 있으나 설계원리가 없습니다.",
            "02",
            "edu-agent review 02 에서 원리 라이브러리를 살펴보세요.",
        )
    self_directed = [a for a in ctx.educational.activities if a.learner_self_directed]
    if self_directed and not any(
        "주도" in p.title or p.name == "learner_agency" for p in ctx.principles.principles
    ):
        ctx.info(
            "I103",
            "학생이 스스로 해야 하는 활동이 있는데 학습자 주도성 원리가 없습니다.",
            "02",
            "lib.learner_agency 를 추가하는 것을 고려하세요.",
        )


# --- 3. principles ↔ executable rules ------------------------------------
def _check_principle_rule_alignment(ctx: CheckContext) -> None:
    for p in ctx.principles.principles:
        if not p.confirmed:
            ctx.error(
                "E201",
                f"설계원리 {p.id}({p.title or p.name}) 가 아직 확인되지 않았습니다.",
                f"02 {p.id}",
                "edu-agent review 02 에서 구조화 결과를 확인하세요.",
            )
            continue
        if not p.rules:
            ctx.error(
                "E202",
                f"설계원리 {p.id} 에 실행 규칙이 없습니다. 이 원리는 에이전트 행동으로 이어지지 않습니다.",
                f"02 {p.id}",
                "이 원리가 '어떤 상황에서 무엇을 한다'인지 정하세요.",
            )
        if p.prohibited_behaviors and not any(
            c.gateable for r in p.rules for c in r.constraints
        ):
            ctx.warn(
                "W203",
                f"{p.id} 의 금지 행동은 실행 중에 차단되지 않고 AI 판정으로만 확인됩니다.",
                f"02 {p.id}",
                "기계적으로 판정할 수 있는 금지라면 hard 제약으로 바꾸면 실행 중에 막을 수 있습니다. "
                "판단이 필요한 것이라면 이대로 두어도 됩니다.",
            )


# --- 4. conflicts ---------------------------------------------------------
def _check_conflicts(ctx: CheckContext) -> None:
    never: dict[AgentAction, str] = {}
    required: dict[AgentAction, str] = {}

    for p in ctx.principles.principles:
        for r in p.rules:
            for c in r.constraints:
                if c.kind is ConstraintKind.NEVER_ACTION:
                    never[AgentAction(c.params["action"])] = f"{p.id}/{r.id}"
                if c.kind is ConstraintKind.REQUIRE_ACTION_AFTER_TRIGGER:
                    required[AgentAction(c.params["action"])] = f"{p.id}/{r.id}"
            for step in r.ladder:
                if step.action in never:
                    ctx.error(
                        "E301",
                        f"{r.id} 의 사다리에 {step.action.value} 가 있는데 {never[step.action]} 에서 금지되어 있습니다.",
                        "02",
                        "둘 중 하나를 고쳐야 합니다. 금지가 맞다면 사다리에서 빼세요.",
                    )

    for action, where in required.items():
        if action in never:
            ctx.error(
                "E302",
                f"{action.value} 가 {where} 에서는 필수인데 {never[action]} 에서는 금지되어 있습니다.",
                "02",
                "두 원리가 충돌합니다. 적용 조건을 나누거나 하나를 수정하세요.",
            )

    # The "never help" failure: every rung is a question, so a stuck learner is
    # never actually helped. The Arena rubric penalises this explicitly.
    for p in ctx.principles.principles:
        for r in p.rules:
            if r.ladder and all(ACTION_DIRECTIVENESS.get(s.action, 0) == 0 for s in r.ladder):
                ctx.warn(
                    "W303",
                    f"{r.id} 의 모든 단계가 질문입니다. 학습자가 계속 막혀 있어도 도움이 올라가지 않습니다.",
                    f"02 {p.id}",
                    "'정보를 비생산적으로 보류하는 것'도 평가에서 감점입니다. 상위 단계를 추가하세요.",
                )

    if ctx.principles.answer_policy is AnswerPolicy.NEVER:
        ctx.warn(
            "W304",
            "정답을 '절대 제공하지 않음'으로 설정했습니다.",
            "02",
            "학습자가 충분히 시도한 뒤에도 도움을 받지 못하면 평가에서 감점됩니다. "
            "'일정 조건에서만 제공'을 권장합니다.",
        )


# --- 5. technical feasibility --------------------------------------------
def _check_feasibility(ctx: CheckContext) -> None:
    tech = ctx.technical
    tools = {t.kind for t in tech.tools}

    if tech.requirements.needs_code_execution and ToolKind.CODE_EXECUTION not in tools:
        ctx.warn(
            "W401",
            "코드를 실행해야 한다고 했는데 코드 실행 도구가 명세에 없습니다.",
            "03 Tools",
        )
    for tool in tech.tools:
        if tool.kind is ToolKind.CODE_EXECUTION and not tool.sandboxed:
            ctx.error(
                "E402",
                "코드 실행 도구가 샌드박스 밖에서 실행되도록 설정되어 있습니다.",
                "03 Tools",
                "학생 코드를 그대로 실행하는 것은 위험합니다. sandboxed: true 로 두세요.",
            )
    if tech.requirements.needs_external_materials and not tech.data_rag.required:
        ctx.warn(
            "W403",
            "교과서·학습자료를 참고해야 한다고 했는데 자료 검색이 '필요 없음'으로 되어 있습니다.",
            "03 Data/RAG",
        )
    if tech.requirements.needs_persistent_learner_memory and not tech.memory.learner_progress:
        ctx.warn(
            "W404",
            "다음 접속에서도 기억해야 한다고 했는데 학습자 진도 저장이 꺼져 있습니다.",
            "03 Memory",
        )
    if tech.memory.long_term_memory and not tech.security.stores_personal_data:
        ctx.info(
            "I405",
            "장기 기억을 사용하면 학습자 데이터를 저장하게 됩니다. 무엇을 얼마나 저장하는지 적어 두세요.",
            "03 Security",
        )
    if tech.execution_path is ExecutionPath.EXPORT_FASTAPI:
        ctx.info(
            "I406",
            "FastAPI 내보내기는 아직 실험적입니다. 수업에서는 harness_runtime 을 권장합니다.",
            "03",
        )


# --- 6. evaluability ------------------------------------------------------
def _check_evaluability(ctx: CheckContext) -> None:
    """Can the design actually be checked? This is the harness's own promise."""
    has_leak_constraint = any(
        c.kind is ConstraintKind.NO_ANSWER_LEAKAGE_UNLESS
        for p in ctx.principles.principles
        for r in p.rules
        for c in r.constraints
    )
    with_answers = [
        t for t in ctx.educational.tasks if t.reference_answer or t.answer_fragments
    ]
    if has_leak_constraint and not with_answers:
        ctx.warn(
            "W501",
            "정답 누출을 막는 규칙이 있지만 정답 기준이 있는 과제가 하나도 없습니다.",
            "01 §7",
            "tasks/ 에 과제와 정답을 넣으면 '정답을 미리 알려줬는지'를 정확히 검사할 수 있습니다. "
            "지금은 코드 블록 길이 같은 대략적인 추정만 가능합니다.",
        )
    for task in ctx.educational.tasks:
        if not task.reference_answer and not task.answer_fragments:
            ctx.info(
                "I502",
                f"과제 '{task.id}' 에 정답 기준이 없습니다.",
                "01 §7",
            )
    if not ctx.principles.criteria and not any(
        r.evaluation for p in ctx.principles.principles for r in p.rules
    ):
        ctx.warn(
            "W503",
            "평가 기준이 하나도 정의되지 않았습니다.",
            "02",
            "원리 라이브러리에서 원리를 가져오면 평가 기준이 함께 만들어집니다.",
        )


def has_errors(issues: list[CompileIssue]) -> bool:
    return any(i.severity is Severity.ERROR for i in issues)

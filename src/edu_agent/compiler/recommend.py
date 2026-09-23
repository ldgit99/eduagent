"""Recommending a technical stack from *requirements*, never from tech names.

Plan v2 §8: the student is asked "does the AI need to look things up in a
textbook?", not "which vector database?". This module turns those answers into a
stack, and — as important — records *why*, so the recommendation is reviewable
rather than magic. Recommending a single agent when a single agent is enough is an
explicit goal.
"""

from __future__ import annotations

from edu_agent.schemas.technical import (
    AgentArchitecture,
    ArchitectureKind,
    BackendFramework,
    BackendSpec,
    DataRAGSpec,
    Decision,
    DecisionOrigin,
    DeploymentKind,
    DeploymentSpec,
    ExecutionPath,
    InterfaceKind,
    InterfaceSpec,
    MemorySpec,
    RetrievalKind,
    TechnicalRequirements,
    TechnicalSpec,
    ToolKind,
    ToolSpec,
)


def recommend_stack(spec: TechnicalSpec, *, overwrite: bool = False) -> TechnicalSpec:
    """Fill in unset sections of ``spec`` from ``spec.requirements``."""
    req = spec.requirements
    decisions: list[Decision] = []

    def decide(area: str, choice: str, reason: str) -> None:
        decisions.append(
            Decision(area=area, choice=choice, reason=reason, origin=DecisionOrigin.RECOMMENDED)
        )

    # --- execution path & interface -------------------------------------
    # One local process serves one learner at a time, so a class-sized group in a
    # browser is the point where exporting a service starts to earn its cost.
    many_at_once = bool(req.uses_web_browser and (req.expected_users or 0) > 30)
    if overwrite or spec.execution_path is ExecutionPath.HARNESS_RUNTIME:
        if many_at_once:
            spec.execution_path = ExecutionPath.EXPORT_FASTAPI
            decide(
                "실행 방식",
                "FastAPI 서비스로 내보내기 (edu-agent build --target fastapi)",
                f"브라우저에서 {req.expected_users}명이 쓴다고 하셨습니다. 여러 명이 동시에 "
                "접속하려면 서비스가 필요합니다. 설계를 다듬는 동안에는 edu-agent run 을 "
                "그대로 쓰고, 배포할 때 내보내세요.",
            )
        else:
            spec.execution_path = ExecutionPath.HARNESS_RUNTIME
            decide(
                "실행 방식",
                "하네스 런타임 (edu-agent run)",
                "코드를 만들지 않고 04 문서를 그대로 실행합니다. 설계를 고치면 곧바로 반영되고, "
                "정책 게이트가 한 곳에서만 관리됩니다.",
            )

    if overwrite or spec.interface.kind is InterfaceKind.CLI:
        if req.uses_web_browser:
            spec.interface = InterfaceSpec(
                kind=InterfaceKind.WEB_CHAT,
                notes="edu-agent run --web 로 로컬 웹 채팅을 엽니다. 추가 설치가 필요 없습니다.",
            )
            decide("사용 화면", "로컬 웹 채팅", "학습자가 브라우저에서 사용한다고 하셨습니다.")
        else:
            spec.interface = InterfaceSpec(kind=InterfaceKind.CLI)
            decide("사용 화면", "터미널 채팅", "브라우저가 필요하지 않다면 가장 단순한 방법입니다.")

    # --- architecture ----------------------------------------------------
    if overwrite or not spec.architecture.reason:
        needs_many_roles = bool(req.needs_external_materials and req.needs_code_execution)
        if needs_many_roles and (req.expected_users or 0) > 200:
            spec.architecture = AgentArchitecture(
                kind=ArchitectureKind.MULTI,
                reason="여러 역할과 큰 규모가 겹칩니다. 다만 먼저 단일 에이전트로 시작해 보기를 권합니다.",
            )
            decide("에이전트 구조", "다중 에이전트(조건부)", spec.architecture.reason)
        else:
            spec.architecture = AgentArchitecture(
                kind=ArchitectureKind.SINGLE,
                reason="하나의 역할(튜터)만 필요합니다. 다중 에이전트는 복잡도만 늘리고 "
                "교육적 이득이 없습니다.",
            )
            decide("에이전트 구조", "단일 에이전트", spec.architecture.reason)

    # --- RAG -------------------------------------------------------------
    if overwrite or not spec.data_rag.sources:
        if req.needs_external_materials:
            spec.data_rag = DataRAGSpec(
                required=True,
                retrieval=RetrievalKind.KEYWORD,
                sources=["(참고할 자료를 여기에 적으세요)"],
            )
            decide(
                "자료 검색",
                "키워드 검색부터",
                "자료가 수십 건 규모라면 키워드 검색으로 충분합니다. "
                "벡터 검색은 자료가 많아지고 표현이 다양해질 때 도입하세요.",
            )
        else:
            spec.data_rag = DataRAGSpec(required=False, retrieval=RetrievalKind.NONE)
            decide("자료 검색", "사용하지 않음", "별도 자료 참고가 필요하지 않다고 하셨습니다.")

    # --- memory ----------------------------------------------------------
    if overwrite or not spec.memory.retention_note:
        if req.needs_persistent_learner_memory:
            spec.memory = MemorySpec(
                session_memory=True,
                learner_progress=True,
                long_term_memory=False,
                retention_note="학습자별 진도와 시도 이력만 저장합니다. 개인 식별 정보는 저장하지 않습니다.",
            )
            decide(
                "기억",
                "세션 + 학습자 진도",
                "다음 접속에서도 기억해야 한다고 하셨습니다. 저장 범위는 최소로 두었습니다.",
            )
        else:
            spec.memory = MemorySpec(
                session_memory=True,
                learner_progress=False,
                retention_note="대화가 끝나면 기억하지 않습니다.",
            )
            decide(
                "기억",
                "세션 동안만",
                "장기 기억이 필요 없으면 저장하지 않는 것이 개인정보 측면에서 안전합니다.",
            )

    # --- tools -----------------------------------------------------------
    if overwrite or not spec.tools:
        tools: list[ToolSpec] = []
        if req.needs_code_execution:
            tools.append(
                ToolSpec(
                    kind=ToolKind.CODE_EXECUTION,
                    description="학습자 코드를 안전한 환경에서 실행합니다.",
                    sandboxed=True,
                    permissions=["network:none", "fs:tmp-only", "timeout:5s", "memory:256m"],
                    # Running the code before the learner has said what they think
                    # does their diagnosing for them, so the tool waits for that.
                    when_allowed="reasoning_shown == true",
                )
            )
            decide(
                "도구",
                "샌드박스 코드 실행기",
                "코드를 실제로 실행해야 한다고 하셨습니다. 네트워크를 막고 임시 폴더에서만 "
                "5초 제한으로 실행합니다. 학습자가 자기 생각을 말한 뒤에만 실행합니다 "
                "(조건을 비우면 항상 실행할 수 있습니다).",
            )
        if req.needs_external_materials:
            tools.append(
                ToolSpec(
                    kind=ToolKind.FILE_RETRIEVAL,
                    description="지정한 학습자료에서 관련 부분을 찾습니다.",
                    permissions=["fs:read-only"],
                )
            )
        spec.tools = tools
        if not tools:
            decide("도구", "없음", "추가 도구 없이 대화만으로 충분합니다.")

    # --- backend / deployment -------------------------------------------
    if overwrite or spec.backend.framework is BackendFramework.NONE:
        spec.backend = BackendSpec(language="python", framework=BackendFramework.NONE)
        decide("서버", "필요 없음", "하네스 런타임이 직접 실행하므로 별도 서버가 없습니다.")

    # A named stack is a constraint, not a candidate: never recommend over it.
    if spec.deployment.frontend or spec.deployment.backend_service:
        named = " + ".join(
            x for x in (spec.deployment.frontend, spec.deployment.backend_service) if x
        )
        if spec.deployment.kind is DeploymentKind.LOCAL:
            spec.deployment.kind = (
                DeploymentKind.VERCEL
                if "vercel" in spec.deployment.frontend.lower()
                else DeploymentKind.CLOUD
            )
        decide("배포", named, "이미 정해진 환경이라 그대로 따릅니다.")
        if spec.deployment.backend_service:
            # Naming somewhere to keep data is a statement that data gets kept.
            spec.security.stores_personal_data = True
            spec.security.personal_data_note = spec.security.personal_data_note or (
                f"{spec.deployment.backend_service} 에 학습 기록이 저장됩니다. "
                "무엇을 저장하고 언제 지우는지를 학생에게 알려야 합니다."
            )
            decide(
                "개인정보",
                f"{spec.deployment.backend_service} 에 저장됨",
                "외부 서비스에 학생 기록을 두면 보관 기간과 삭제 방법을 문서에 적어야 합니다.",
            )
    elif overwrite or spec.deployment.kind is DeploymentKind.LOCAL:
        users = req.expected_users or 0
        if users > 50:
            spec.deployment = DeploymentSpec(
                kind=DeploymentKind.LOCAL,
                notes=f"{users}명이 동시에 쓸 예정이라면 교수자용 프록시에서 사용량 한도를 두세요.",
            )
            decide("배포", "로컬 실행 + 교수자 프록시", spec.deployment.notes)
        else:
            spec.deployment = DeploymentSpec(kind=DeploymentKind.LOCAL)
            decide("배포", "각자 컴퓨터에서 실행", "수업 규모에서는 별도 서버가 필요하지 않습니다.")

    # --- security --------------------------------------------------------
    spec.security.api_keys_via_env = True
    if req.needs_persistent_learner_memory:
        spec.security.stores_personal_data = True
        spec.security.personal_data_note = (
            spec.security.personal_data_note
            or "학습 진도만 저장하며 이름·연락처는 저장하지 않습니다."
        )

    existing = {(d.area, d.choice) for d in spec.decisions}
    spec.decisions.extend(d for d in decisions if (d.area, d.choice) not in existing)
    return spec


def summarize_recommendation(spec: TechnicalSpec) -> str:
    """A short block for the confirmation screen."""
    rows = [
        ("실행 방식", _EXEC_KO[spec.execution_path]),
        ("사용 화면", spec.interface.kind.value),
        ("에이전트 구조", "단일 에이전트" if spec.architecture.kind is ArchitectureKind.SINGLE else "다중 에이전트"),
        ("기억", "세션 + 진도" if spec.memory.learner_progress else "세션 동안만"),
        ("자료 검색", "사용" if spec.data_rag.required else "사용 안 함"),
        ("도구", ", ".join(t.kind.value for t in spec.tools) or "없음"),
        ("저장", f"{spec.storage.database} + {spec.storage.trace_storage}"),
    ]
    width = max(len(k) for k, _ in rows)
    return "\n".join(f"{k.ljust(width)}  →  {v}" for k, v in rows)


_EXEC_KO = {
    ExecutionPath.HARNESS_RUNTIME: "하네스 런타임 (edu-agent run)",
    ExecutionPath.EXPORT_CLI: "Python CLI 프로젝트로 내보내기",
    ExecutionPath.EXPORT_FASTAPI: "FastAPI 프로젝트로 내보내기 (실험적)",
}


def blank_requirements() -> TechnicalRequirements:
    return TechnicalRequirements()

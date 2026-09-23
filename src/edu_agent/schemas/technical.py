"""Domain model for ``03_technical_spec.md``.

Two layers (plan Section 6):

1. :class:`TechnicalRequirements` — answers to *non-technical* questions
   ("AI가 별도의 교과서를 참고해야 합니까?"). This is what the user is asked.
2. The concrete specification sections (provider, backend, interface, ...) — filled
   either by the user directly, or by the recommendation engine (``compiler.recommend``,
   Phase 2/3) from the requirements, each with a recorded reason and origin.
"""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar

from pydantic import Field, field_validator

from edu_agent.schemas.common import DocumentModel, HarnessModel


class ExecutionPath(StrEnum):
    """How the compiled agent is executed (plan v2 §8.2).

    ``harness_runtime`` is the default: ``edu-agent run`` interprets
    ``04_agent_spec.md`` directly, so a non-programmer never has to touch code.
    """

    HARNESS_RUNTIME = "harness_runtime"
    EXPORT_CLI = "export_cli"
    EXPORT_FASTAPI = "export_fastapi"


class DecisionOrigin(StrEnum):
    USER = "user"
    RECOMMENDED = "recommended"
    DEFAULT = "default"


class SelectionMode(StrEnum):
    """'기술적인 부분을 직접 선택하시겠습니까?' [1] 직접 [2] 일부 [3] 모두 추천"""

    MANUAL = "manual"
    MIXED = "mixed"
    RECOMMEND_ALL = "recommend_all"


class ProviderKind(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    OLLAMA = "ollama"
    OPENAI_COMPATIBLE = "openai_compatible"
    MOCK = "mock"


class ArchitectureKind(StrEnum):
    SINGLE = "single_agent"
    MULTI = "multi_agent"


class InterfaceKind(StrEnum):
    CLI = "cli"
    WEB_CHAT = "web_chat"
    STREAMLIT = "streamlit"
    GRADIO = "gradio"
    NEXTJS = "nextjs"
    LMS = "lms"
    EXISTING_APP = "existing_app"


class BackendFramework(StrEnum):
    NONE = "none"  # pure CLI
    FASTAPI = "fastapi"
    FLASK = "flask"
    OTHER = "other"


class RetrievalKind(StrEnum):
    NONE = "none"
    KEYWORD = "keyword"
    VECTOR = "vector"
    HYBRID = "hybrid"


class ToolKind(StrEnum):
    WEB_SEARCH = "web_search"
    CALCULATOR = "calculator"
    CODE_EXECUTION = "code_execution"
    FILE_RETRIEVAL = "file_retrieval"
    DATABASE = "database"
    EXTERNAL_API = "external_api"
    LMS = "lms"


class DeploymentKind(StrEnum):
    LOCAL = "local"
    DOCKER = "docker"
    CLOUD = "cloud"
    VERCEL = "vercel"
    OTHER = "other"


class TechnicalRequirements(HarnessModel):
    """Requirement-level answers (asked in plain language, never by tech name)."""

    needs_external_materials: bool | None = Field(default=None, description="교과서/학습자료 참고 필요")
    needs_persistent_learner_memory: bool | None = Field(default=None, description="다음 접속에서도 기억")
    uses_web_browser: bool | None = Field(default=None, description="웹 브라우저에서 사용")
    expected_users: int | None = Field(default=None, ge=1)
    needs_code_execution: bool | None = Field(default=None, description="코드를 실제로 실행")
    needs_multimodal_input: bool | None = Field(default=None, description="이미지/파일 입력")
    needs_lms_integration: bool | None = Field(default=None)
    must_run_offline_or_local: bool | None = Field(default=None, description="로컬/오프라인 모델 필요")
    data_sensitivity: str = Field(default="", description="학생 개인정보 민감도 메모")
    selection_mode: SelectionMode = SelectionMode.RECOMMEND_ALL


class Decision(HarnessModel):
    """A technical choice with its provenance (plan: '선택한 기술 / 선택 이유')."""

    area: str
    choice: str
    reason: str = ""
    origin: DecisionOrigin = DecisionOrigin.DEFAULT


class AIProviderSpec(HarnessModel):
    """Provider profile. Secrets never live here — only env var *names*.

    Three roles are kept separate on purpose (plan v2 §13.1 / ADR-09): the tutor,
    the judge and the simulated student should not all be the same model, or the
    evaluation inherits the tutor's blind spots.
    """

    provider: ProviderKind = ProviderKind.OPENAI
    model: str = Field(default="", description="튜터 모델")
    judge_model: str = Field(default="", description="평가자 모델 (튜터와 다른 모델 권장)")
    student_model: str = Field(default="", description="시뮬레이션 학생 모델 (더 작은 모델 권장)")
    api_config: dict[str, str] = Field(
        default_factory=dict, description="비밀이 아닌 설정 (base_url 등). 키는 환경변수에서 읽는다."
    )
    max_tokens_per_session: int = Field(default=20000, ge=0, description="0 = 제한 없음")


class AgentArchitecture(HarnessModel):
    kind: ArchitectureKind = ArchitectureKind.SINGLE
    reason: str = ""


class BackendSpec(HarnessModel):
    language: str = "python"
    framework: BackendFramework = BackendFramework.NONE


class InterfaceSpec(HarnessModel):
    kind: InterfaceKind = InterfaceKind.CLI
    notes: str = ""


class DataRAGSpec(HarnessModel):
    required: bool = False
    sources: list[str] = Field(default_factory=list)
    retrieval: RetrievalKind = RetrievalKind.NONE
    vector_store: str = ""


class MemorySpec(HarnessModel):
    session_memory: bool = True
    learner_progress: bool = False
    long_term_memory: bool = False
    retention_note: str = Field(default="", description="What is stored, for how long, and why")


class ToolSpec(HarnessModel):
    """A tool the agent may use, and the learner state it may be used in.

    ``when_allowed`` is what stops a tool from becoming a way around the design:
    running the learner's code for them before they have said what they think is
    the same pedagogical failure as handing over the answer, just wearing a
    different hat. It is checked at runtime, not only written down.
    """

    kind: ToolKind
    description: str = ""
    sandboxed: bool = Field(default=True, description="Executed inside a permission boundary")
    permissions: list[str] = Field(default_factory=list, description="e.g. network:none, fs:read-only")
    when_allowed: str = Field(default="", description="학습자 상태 조건 (비우면 항상 허용)")

    @field_validator("when_allowed")
    @classmethod
    def _condition(cls, value: str) -> str:
        from edu_agent.schemas.principles import validate_condition

        return validate_condition(value)


class StorageSpec(HarnessModel):
    database: str = "sqlite"
    trace_storage: str = "jsonl"


class DeploymentSpec(HarnessModel):
    kind: DeploymentKind = DeploymentKind.LOCAL
    notes: str = ""


class SecuritySpec(HarnessModel):
    api_keys_via_env: bool = True
    stores_personal_data: bool = False
    personal_data_note: str = ""
    logs_conversations: bool = True
    log_redaction: bool = True
    roles: list[str] = Field(default_factory=lambda: ["learner"], description="e.g. learner, teacher, admin")


class TechnicalSpec(DocumentModel):
    """Root model for ``03_technical_spec.md``."""

    SCHEMA_NAME: ClassVar[str] = "technical_spec"

    execution_path: ExecutionPath = ExecutionPath.HARNESS_RUNTIME
    requirements: TechnicalRequirements = Field(default_factory=TechnicalRequirements)
    ai_provider: AIProviderSpec = Field(default_factory=AIProviderSpec)
    architecture: AgentArchitecture = Field(default_factory=AgentArchitecture)
    backend: BackendSpec = Field(default_factory=BackendSpec)
    interface: InterfaceSpec = Field(default_factory=InterfaceSpec)
    data_rag: DataRAGSpec = Field(default_factory=DataRAGSpec)
    memory: MemorySpec = Field(default_factory=MemorySpec)
    tools: list[ToolSpec] = Field(default_factory=list)
    storage: StorageSpec = Field(default_factory=StorageSpec)
    deployment: DeploymentSpec = Field(default_factory=DeploymentSpec)
    security: SecuritySpec = Field(default_factory=SecuritySpec)
    decisions: list[Decision] = Field(default_factory=list)

    def missing_required(self) -> list[str]:
        missing: list[str] = []
        req = self.requirements
        for name in ("needs_external_materials", "needs_persistent_learner_memory", "needs_code_execution"):
            if getattr(req, name) is None:
                missing.append(f"requirements.{name}")
        # ai_provider.model is intentionally NOT required: it is normally supplied
        # by EDU_AGENT_MODEL in .env, so requiring it here would stop a student
        # from compiling before their instructor's key arrives.
        return missing

"""Project discovery and on-disk layout.

Layout (plan v2 §5)::

    project/
      edu-agent.yaml
      01_educational_design.md
      02_design_principles.md
      03_technical_spec.md
      04_agent_spec.md          (compile output)
      tasks/                    reference answers -> deterministic leakage checks
      evals/                    calibration input, human ratings
      .edu-agent/               traces, runs, improve history, snapshots (gitignored)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from edu_agent.project.config import ProjectConfig
from edu_agent.schemas.agent import AgentSpec
from edu_agent.schemas.common import DocumentModel
from edu_agent.schemas.educational import EducationalDesign
from edu_agent.schemas.principles import DesignPrinciples
from edu_agent.schemas.technical import TechnicalSpec

CONFIG_NAME = "edu-agent.yaml"
STATE_DIR = ".edu-agent"


@dataclass(frozen=True, slots=True)
class DocSlot:
    """One of the four documents."""

    index: int
    key: str
    filename: str
    model: type[DocumentModel]
    template: str
    title_ko: str

    @property
    def label(self) -> str:
        return f"{self.index:02d} {self.title_ko}"


DOC_FILES: tuple[DocSlot, ...] = (
    DocSlot(1, "educational", "01_educational_design.md", EducationalDesign,
            "educational_design.md.j2", "교육 설계"),
    DocSlot(2, "principles", "02_design_principles.md", DesignPrinciples,
            "design_principles.md.j2", "설계원리"),
    DocSlot(3, "technical", "03_technical_spec.md", TechnicalSpec,
            "technical_spec.md.j2", "기술 명세"),
    DocSlot(4, "agent", "04_agent_spec.md", AgentSpec,
            "agent_spec.md.j2", "에이전트 명세"),
)

INPUT_DOCS: tuple[DocSlot, ...] = DOC_FILES[:3]
SPEC_DOC: DocSlot = DOC_FILES[3]


def slot_for(ref: str | int) -> DocSlot:
    """Resolve ``1``/``"01"``/``"principles"``/``"02_design_principles.md"``."""
    text = str(ref).strip().lower()
    for slot in DOC_FILES:
        if text in {str(slot.index), f"{slot.index:02d}", slot.key, slot.filename}:
            return slot
    raise KeyError(f"알 수 없는 문서: {ref}")


class ProjectNotFound(Exception):
    pass


@dataclass(slots=True)
class Project:
    """An on-disk project."""

    root: Path
    config: ProjectConfig

    # --- paths -----------------------------------------------------------
    @property
    def config_path(self) -> Path:
        return self.root / CONFIG_NAME

    @property
    def state_dir(self) -> Path:
        return self.root / STATE_DIR

    @property
    def traces_dir(self) -> Path:
        return self.state_dir / "traces"

    @property
    def runs_dir(self) -> Path:
        return self.state_dir / "runs"

    @property
    def snapshots_dir(self) -> Path:
        return self.state_dir / "snapshots"

    @property
    def improve_dir(self) -> Path:
        return self.state_dir / "improve"

    @property
    def tasks_dir(self) -> Path:
        return self.root / "tasks"

    @property
    def evals_dir(self) -> Path:
        return self.root / "evals"

    def doc_path(self, ref: str | int | DocSlot) -> Path:
        slot = ref if isinstance(ref, DocSlot) else slot_for(ref)
        return self.root / slot.filename

    def exists(self, ref: str | int | DocSlot) -> bool:
        return self.doc_path(ref).exists()

    def ensure_dirs(self) -> None:
        for d in (
            self.state_dir,
            self.traces_dir,
            self.runs_dir,
            self.snapshots_dir,
            self.improve_dir,
            self.tasks_dir,
            self.evals_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

    def save_config(self) -> None:
        self.config.save(self.config_path)


def find_project(start: Path | None = None) -> Project:
    """Walk up from ``start`` looking for ``edu-agent.yaml``."""
    cur = (start or Path.cwd()).resolve()
    for candidate in (cur, *cur.parents):
        cfg = candidate / CONFIG_NAME
        if cfg.exists():
            return Project(root=candidate, config=ProjectConfig.load(cfg))
    raise ProjectNotFound(str(cur))


GITIGNORE = """\
# 하네스가 만드는 로컬 기록 (대화 기록이 들어 있으므로 커밋하지 않습니다)
.edu-agent/

# API 키 (절대 커밋하지 마세요)
.env

# Python
__pycache__/
*.py[cod]
.venv/
"""

ENV_EXAMPLE = """\
# 교수자가 배포한 값을 복사해 넣으세요. 이 파일(.env)은 GitHub에 올라가지 않습니다.
EDU_AGENT_API_KEY=
EDU_AGENT_BASE_URL=
EDU_AGENT_MODEL=

# 선택: 평가자와 시뮬레이션 학생에 다른 모델을 쓰고 싶을 때
# (같은 모델로 튜터·평가·학생을 모두 맡기면 평가가 튜터의 맹점을 그대로 물려받습니다)
# EDU_AGENT_JUDGE_MODEL=
# EDU_AGENT_STUDENT_MODEL=
"""


def create_project(root: Path, name: str, title: str = "", language: str = "ko") -> Project:
    """Create a new project skeleton at ``root``."""
    from edu_agent._version import __version__

    root.mkdir(parents=True, exist_ok=True)
    config = ProjectConfig(name=name, title=title, language=language, harness_version=__version__)
    project = Project(root=root, config=config)
    project.ensure_dirs()
    project.save_config()

    gi = root / ".gitignore"
    if not gi.exists():
        gi.write_text(GITIGNORE, encoding="utf-8", newline="\n")
    envx = root / ".env.example"
    if not envx.exists():
        envx.write_text(ENV_EXAMPLE, encoding="utf-8", newline="\n")
    keep = project.tasks_dir / "README.md"
    if not keep.exists():
        keep.write_text(
            "# tasks\n\n"
            "에이전트가 다룰 과제와 **정답 기준**을 여기에 둡니다.\n"
            "정답이 있어야 '정답을 미리 알려줬는지'를 AI 판단 없이 정확히 검사할 수 있습니다.\n"
            "(`edu-agent review 01`에서 함께 물어봅니다.)\n",
            encoding="utf-8",
            newline="\n",
        )
    return project

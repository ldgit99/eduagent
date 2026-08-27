"""Reading and writing frontmatter documents."""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from edu_agent.schemas.common import DocumentModel, DocumentStatus
from edu_agent.utils.hashing import hash_text

_DELIM = "---"


class DocumentError(Exception):
    """Raised when a document cannot be read or validated."""

    def __init__(self, path: Path, message: str, detail: str = "") -> None:
        self.path = path
        self.detail = detail
        super().__init__(f"{path.name}: {message}")


@dataclass(slots=True)
class DocumentFile:
    """A parsed document: its path, its data model and its rendered body."""

    path: Path
    model: DocumentModel
    body: str

    @property
    def drifted(self) -> bool:
        return detect_drift(self.model, self.body)


def split_frontmatter(text: str) -> tuple[str, str]:
    """Split ``---\\nyaml\\n---\\nbody`` into ``(yaml_text, body)``.

    A file with no frontmatter is treated as all-body, which is what happens when a
    student creates the Markdown themselves before ever running the harness.
    """
    text = text.replace("\r\n", "\n")
    if not text.lstrip().startswith(_DELIM):
        return "", text
    stripped = text.lstrip()
    lines = stripped.split("\n")
    for i in range(1, len(lines)):
        if lines[i].strip() == _DELIM:
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1 :]).lstrip("\n")
    # Opening delimiter with no closing one: treat the whole file as body rather
    # than failing — the student can still be shown a useful error later.
    return "", text


def parse_frontmatter(text: str) -> dict[str, Any]:
    fm, _ = split_frontmatter(text)
    if not fm.strip():
        return {}
    data = yaml.safe_load(fm)
    return data if isinstance(data, dict) else {}


def _dump_yaml(data: dict[str, Any]) -> str:
    buf = io.StringIO()
    yaml.safe_dump(
        data,
        buf,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=100,
    )
    return buf.getvalue()


def load_document[M: DocumentModel](path: Path, model_cls: type[M]) -> tuple[M, str]:
    """Load ``path`` as ``model_cls``. Returns ``(model, body)``."""
    if not path.exists():
        raise DocumentError(path, "파일이 없습니다")
    raw = path.read_text(encoding="utf-8")
    try:
        data = parse_frontmatter(raw)
    except yaml.YAMLError as exc:
        raise DocumentError(path, "frontmatter(YAML)를 읽을 수 없습니다", str(exc)) from exc
    _, body = split_frontmatter(raw)
    if not data:
        raise DocumentError(
            path,
            "frontmatter가 없습니다",
            "이 파일은 아직 하네스가 관리하지 않습니다. 'edu-agent review'로 구조화하세요.",
        )
    try:
        model = model_cls.model_validate(data)
    except ValidationError as exc:
        raise DocumentError(path, "문서 내용이 스키마와 맞지 않습니다", _explain(exc)) from exc
    return model, body


def _explain(exc: ValidationError) -> str:
    lines = []
    for err in exc.errors()[:8]:
        loc = ".".join(str(p) for p in err["loc"])
        lines.append(f"  - {loc}: {err['msg']}")
    return "\n".join(lines)


def save_document(path: Path, model: DocumentModel, body: str) -> Path:
    """Write ``model`` + ``body``, refreshing ``content_hash`` and ``updated_at``."""
    model.meta.content_hash = hash_text(body)
    model.meta.touch()
    data = model.model_dump(mode="json", exclude_none=True, exclude_defaults=False)
    text = f"{_DELIM}\n{_dump_yaml(data)}{_DELIM}\n\n{body.strip()}\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def detect_drift(model: DocumentModel, body: str) -> bool:
    """True when the body on disk differs from what the harness last rendered."""
    recorded = model.meta.content_hash
    if not recorded:
        return False
    return recorded != hash_text(body)


def mark_drift(model: DocumentModel, body: str) -> DocumentStatus:
    """Set ``needs_sync`` if the body drifted; return the resulting status."""
    if detect_drift(model, body) and model.meta.status is DocumentStatus.CONFIRMED:
        model.meta.status = DocumentStatus.NEEDS_SYNC
    return model.meta.status

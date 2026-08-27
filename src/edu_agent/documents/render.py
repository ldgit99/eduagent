"""Rendering document bodies from Jinja templates.

Templates live in ``templates/`` next to the package during development and are
shipped inside the wheel at ``edu_agent/_templates`` — :func:`template_dir`
resolves whichever exists so the CLI behaves the same from a git checkout and from
``pip install``.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

_PKG = Path(__file__).resolve().parent.parent


@functools.lru_cache(maxsize=1)
def template_dir() -> Path:
    installed = _PKG / "_templates"
    if installed.is_dir():
        return installed
    repo = _PKG.parent.parent / "templates"
    if repo.is_dir():
        return repo
    raise FileNotFoundError("templates/ 폴더를 찾을 수 없습니다")


@functools.lru_cache(maxsize=1)
def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(template_dir()), encoding="utf-8"),
        undefined=StrictUndefined,
        autoescape=select_autoescape(enabled_extensions=(), default=False),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["bullet"] = _bullet
    env.filters["yesno"] = _yesno
    env.filters["orblank"] = _orblank
    return env


def _bullet(items: Any, empty: str = "(아직 없음)") -> str:
    if not items:
        return f"- {empty}"
    return "\n".join(f"- {i}" for i in items)


def _yesno(value: Any) -> str:
    if value is None:
        return "미정"
    return "예" if value else "아니오"


def _orblank(value: Any, empty: str = "(아직 없음)") -> str:
    text = "" if value is None else str(value).strip()
    return text or empty


def render_document(template_name: str, **context: Any) -> str:
    """Render ``templates/<template_name>`` with ``context``."""
    return _env().get_template(template_name).render(**context).strip() + "\n"


def render_string(source: str, **context: Any) -> str:
    return _env().from_string(source).render(**context)

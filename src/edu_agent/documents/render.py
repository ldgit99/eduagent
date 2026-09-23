"""Rendering document bodies from Jinja templates.

Templates live in ``templates/<lang>/`` next to the package during development and
are shipped inside the wheel at ``edu_agent/_templates`` — :func:`template_dir`
resolves whichever exists so the CLI behaves the same from a git checkout and from
``pip install``.

Language works by *fallback, not duplication*: a project with ``language: en``
renders ``en/agent_spec.md.j2`` if it exists and the Korean one otherwise. A
half-translated template set therefore still produces a complete document, which
matters because the four documents are the artefact the course is graded on.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from edu_agent.i18n import get_language

_PKG = Path(__file__).resolve().parent.parent
DEFAULT_LANG = "ko"


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


#: Filter defaults follow the project's language, so ``{{ x | orblank }}`` does not
#: drop a Korean placeholder into an English document.
_WORDS = {
    "ko": {"empty": "(아직 없음)", "unknown": "미정", "yes": "예", "no": "아니오"},
    "en": {"empty": "(not yet)", "unknown": "undecided", "yes": "yes", "no": "no"},
}


def _word(key: str) -> str:
    return _WORDS.get(get_language(), _WORDS[DEFAULT_LANG])[key]


def _bullet(items: Any, empty: str = "") -> str:
    if not items:
        return f"- {empty or _word('empty')}"
    return "\n".join(f"- {i}" for i in items)


def _yesno(value: Any) -> str:
    if value is None:
        return _word("unknown")
    return _word("yes") if value else _word("no")


def _orblank(value: Any, empty: str = "") -> str:
    text = "" if value is None else str(value).strip()
    return text or empty or _word("empty")


def resolve_template(template_name: str, lang: str = "") -> str:
    """``agent_spec.md.j2`` → ``en/agent_spec.md.j2``, falling back to Korean."""
    if "/" in template_name:
        return template_name
    language = lang or get_language()
    if language != DEFAULT_LANG and (template_dir() / language / template_name).exists():
        return f"{language}/{template_name}"
    return f"{DEFAULT_LANG}/{template_name}"


def render_document(template_name: str, lang: str = "", **context: Any) -> str:
    """Render the ``template_name`` document body in ``lang`` with ``context``."""
    return render_template(resolve_template(template_name, lang), **context).strip() + "\n"


def render_template(path: str, /, **context: Any) -> str:
    """Render a template by exact path, with no language resolution.

    Separate from :func:`render_document`, and positional-only, because a named
    parameter here collides with a template variable of the same name — and the
    exported projects have both a ``name`` and a ``lang``.
    """
    return _env().get_template(path).render(**context).rstrip("\n") + "\n"


def render_string(source: str, **context: Any) -> str:
    return _env().from_string(source).render(**context)

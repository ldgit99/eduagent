"""Message catalogue.

Korean is the default because the course is taught in Korean, but every user-facing
string goes through :func:`t` so an English catalogue can be dropped in with
``--lang en``. Missing keys fall back to Korean and then to the key itself, so a
missing translation degrades instead of crashing mid-questionnaire.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml

_DIR = Path(__file__).parent
_DEFAULT = "ko"
_current = _DEFAULT


@functools.lru_cache(maxsize=8)
def _catalog(lang: str) -> dict[str, Any]:
    path = _DIR / f"{lang}.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def set_language(lang: str) -> None:
    global _current
    _current = lang if (_DIR / f"{lang}.yaml").exists() else _DEFAULT


def get_language() -> str:
    return _current


def _lookup(cat: dict[str, Any], key: str) -> str | None:
    node: Any = cat
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, str) else None


def t(key: str, **kwargs: Any) -> str:
    """Translate ``key``, formatting with ``kwargs``."""
    text = _lookup(_catalog(_current), key)
    if text is None and _current != _DEFAULT:
        text = _lookup(_catalog(_DEFAULT), key)
    if text is None:
        return key
    try:
        return text.format(**kwargs) if kwargs else text
    except (KeyError, IndexError):
        return text


__all__ = ["get_language", "set_language", "t"]

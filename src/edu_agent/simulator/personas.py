"""Loading personas from the built-in library or a project file."""

from __future__ import annotations

import functools
from pathlib import Path

import yaml

from edu_agent.schemas.persona import Persona, PersonaLibrary

_BUILTIN = Path(__file__).parent / "personas.yaml"


@functools.lru_cache(maxsize=1)
def default_personas() -> PersonaLibrary:
    data = yaml.safe_load(_BUILTIN.read_text(encoding="utf-8")) or {}
    return PersonaLibrary(personas=[Persona.model_validate(p) for p in data.get("personas", [])])


def load_personas(path: Path | None = None) -> PersonaLibrary:
    """Load personas, letting a project extend or override the built-ins.

    A project file adds new personas and replaces built-ins with the same ID, so a
    student can tune "our S03 is more like this" without copying the whole library.
    """
    library = PersonaLibrary(personas=list(default_personas().personas))
    if path is None or not path.exists():
        return library

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    by_id = {p.id: p for p in library.personas}
    for raw in data.get("personas", []):
        persona = Persona.model_validate(raw)
        by_id[persona.id] = persona
    return PersonaLibrary(personas=[by_id[k] for k in sorted(by_id)])

"""Running the whole document pipeline in English.

The harness is taught in Korean, so the risk is not that English is missing but
that it is half-present: a Korean placeholder inside an English document, or a
template that silently falls back without anyone noticing.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
import yaml

from edu_agent.documents.render import (
    render_document,
    resolve_template,
    template_dir,
)
from edu_agent.i18n import get_language, set_language, t
from edu_agent.project import create_project
from edu_agent.project.layout import DOC_FILES, slot_for

TEMPLATES = [slot.template for slot in DOC_FILES]


@pytest.fixture
def english():
    previous = get_language()
    set_language("en")
    yield
    set_language(previous)


@pytest.fixture
def korean():
    previous = get_language()
    set_language("ko")
    yield
    set_language(previous)


# --- catalogues -----------------------------------------------------------
def _keys(node, prefix=""):
    out = []
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        out.extend(_keys(value, path) if isinstance(value, dict) else [path])
    return out


def test_catalogues_cover_the_same_keys():
    import edu_agent.i18n as i18n_module

    catalogue_dir = Path(i18n_module.__file__).parent
    catalogues = {
        lang: yaml.safe_load((catalogue_dir / f"{lang}.yaml").read_text(encoding="utf-8"))
        for lang in ("ko", "en")
    }
    assert set(_keys(catalogues["ko"])) == set(_keys(catalogues["en"]))


@pytest.mark.parametrize("lang", ["ko", "en"])
def test_no_key_is_swallowed_by_yaml_booleans(lang):
    """``yes:`` unquoted is ``True`` in YAML 1.1, not the string "yes".

    That made every confirmation prompt in the CLI render as "common.yes"
    instead of 예/아니오 — in both languages, on the most frequent prompt there is.
    """
    import edu_agent.i18n as i18n_module

    catalogue = yaml.safe_load(
        (Path(i18n_module.__file__).parent / f"{lang}.yaml").read_text(encoding="utf-8")
    )

    def walk(node, path=""):
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            assert isinstance(key, str), f"{lang}: {path}.{key!r} is {type(key).__name__}"
            walk(value, f"{path}.{key}")

    walk(catalogue)


@pytest.mark.parametrize("lang", ["ko", "en"])
def test_yes_and_no_actually_translate(lang):
    set_language(lang)
    try:
        assert t("common.yes") != "common.yes"
        assert t("common.no") != "common.no"
    finally:
        set_language("ko")


def test_every_key_resolves_to_text_not_its_own_name():
    """A key that renders as itself is a prompt a learner cannot read."""
    import edu_agent.i18n as i18n_module

    catalogue = yaml.safe_load(
        (Path(i18n_module.__file__).parent / "ko.yaml").read_text(encoding="utf-8")
    )
    set_language("ko")
    for key in _keys(catalogue):
        assert t(key) != key, key


def test_missing_language_falls_back_to_korean():
    set_language("fr")
    try:
        assert get_language() == "ko"
    finally:
        set_language("ko")


def test_unknown_key_returns_itself(korean):
    assert t("nothing.like.this") == "nothing.like.this"


# --- what has actually been migrated --------------------------------------
#: Modules whose user-facing text lives entirely in the catalogues. Adding a
#: module here is the commitment; the test below is what keeps it true.
#:
#: Not on this list, deliberately:
#:
#: * ``runtime/triggers.py`` and ``simulator/renderer.py`` hold *locale content* —
#:   Korean PII patterns, Korean phrasings a simulated learner uses. An English
#:   course needs these patterns *as well*, not instead, so translating them would
#:   quietly delete detection rules. See ``docs/i18n.md``.
#: * ``cli.py`` help text is bound by Typer at import time, before ``--lang`` is
#:   parsed. That needs a different mechanism, not a different catalogue.
MIGRATED_MODULES = [
    "ui.py",
    "questionnaire/principles.py",
]

_HANGUL = re.compile(r"[가-힣]")


def _docstrings(tree: ast.AST) -> set[int]:
    holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, holders):
            continue
        body = getattr(node, "body", None)
        first = body[0] if body else None
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            found.add(id(first.value))
    return found


@pytest.mark.parametrize("module", MIGRATED_MODULES)
def test_migrated_modules_hold_no_korean_of_their_own(module):
    """A migrated module may *explain* itself in Korean, but not *speak* Korean.

    Docstrings and comments are for whoever maintains the file. Every other
    string literal is something a person on the other side of the screen reads,
    and it belongs in ``i18n/``, where it can be translated and where a teacher
    can reword it without opening Python.
    """
    import edu_agent

    path = Path(edu_agent.__file__).parent / module
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = _docstrings(tree)

    offenders = [
        f"line {node.lineno}: {node.value[:60]!r}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        and _HANGUL.search(node.value)
    ]
    assert not offenders, f"{module} still speaks Korean directly:\n  " + "\n  ".join(offenders)


def test_the_questionnaire_asks_in_the_current_language(english):
    """Choice lists must be built per call, not at import.

    ``set_language`` runs when the project is loaded, which is long after this
    module is imported — so a module-level ``Choice(... t(...) ...)`` would pin
    whichever language happened to be current at import time.
    """
    from edu_agent.questionnaire.principles import (
        _answer_conditions,
        _escalation_choices,
        _theory_choices,
    )

    assert "Scaffolding and fading" in [c.label for c in _theory_choices()]
    assert not any(_HANGUL.search(c.label) for c in _answer_conditions())
    assert not any(_HANGUL.search(str(c.value)) for c in _escalation_choices())


def test_the_action_menu_has_an_english_half():
    """The action descriptions go into the prompt, so they follow the project."""
    from edu_agent.runtime.prompt import action_help

    assert action_help("ko").keys() == action_help("en").keys()
    assert not any(_HANGUL.search(v) for v in action_help("en").values())
    assert _HANGUL.search(action_help("ko")["give_direct_answer"])


def test_the_action_menu_follows_the_current_language(english):
    """Regression: the resolution used to sit behind ``lru_cache``.

    With the default argument inside the cache key, the first call of the process
    pinned the language and ``--lang en`` silently produced a Korean prompt.
    """
    from edu_agent.runtime.prompt import action_help

    assert not _HANGUL.search(action_help()["give_direct_answer"])


# --- templates ------------------------------------------------------------
class TestTemplateResolution:
    @pytest.mark.parametrize("template", TEMPLATES)
    def test_english_templates_exist_for_all_four_documents(self, template):
        assert (template_dir() / "en" / template).exists()

    @pytest.mark.parametrize("template", TEMPLATES)
    def test_resolves_to_the_english_copy(self, template, english):
        assert resolve_template(template) == f"en/{template}"

    @pytest.mark.parametrize("template", TEMPLATES)
    def test_resolves_to_korean_by_default(self, template, korean):
        assert resolve_template(template) == f"ko/{template}"

    def test_falls_back_when_a_translation_is_missing(self, english):
        """A partial translation must still produce a complete document."""
        assert resolve_template("not_translated.md.j2") == "ko/not_translated.md.j2"

    def test_explicit_language_wins_over_the_current_one(self, korean):
        assert resolve_template("agent_spec.md.j2", "en") == "en/agent_spec.md.j2"


class TestEnglishRendering:
    def test_agent_spec_renders_in_english(self, compiled_spec, english):
        text = render_document("agent_spec.md.j2", d=compiled_spec)
        assert text.startswith("# Agent Specification")
        assert "Policy gates" in text
        assert "Traceability" in text

    def test_educational_design_renders_in_english(self, example_docs, english):
        text = render_document("educational_design.md.j2", d=example_docs[0])
        assert text.startswith("# Educational Design")
        assert "Learning objectives" in text

    def test_principles_render_in_english(self, example_docs, english):
        text = render_document("design_principles.md.j2", d=example_docs[1])
        assert text.startswith("# Design Principles")
        assert "Answer-giving policy" in text

    def test_technical_spec_renders_in_english(self, example_docs, english):
        text = render_document("technical_spec.md.j2", d=example_docs[2])
        assert text.startswith("# Technical Specification")
        assert "AI provider" in text

    def test_no_korean_leaks_from_the_filters(self, english):
        """`| orblank`, `| bullet` and `| yesno` defaults must follow the language.

        Rendered against an empty spec on purpose: with a filled one the Korean
        would be the author's own content, and the placeholders would not fire.
        """
        from edu_agent.schemas.agent import AgentSpec
        from edu_agent.schemas.common import DocumentMeta

        empty = AgentSpec(meta=DocumentMeta(schema_name=AgentSpec.SCHEMA_NAME, language="en"))
        text = render_document("agent_spec.md.j2", d=empty)
        for korean_default in ("아직 없음", "미정", "아니오"):
            assert korean_default not in text
        assert "(not yet)" in text
        assert "yes" in text or "no" in text

    def test_korean_is_unchanged(self, compiled_spec, korean):
        text = render_document("agent_spec.md.j2", d=compiled_spec)
        assert text.startswith("# 에이전트 명세")


# --- project skeleton -----------------------------------------------------
class TestEnglishProject:
    def test_skeleton_files_are_in_english(self, tmp_path):
        project = create_project(tmp_path / "en-proj", name="en-agent", language="en")
        assert "never commit this" in (project.root / ".gitignore").read_text(encoding="utf-8")
        assert "your instructor" in (project.root / ".env.example").read_text(encoding="utf-8")
        assert "reference answers" in (project.tasks_dir / "README.md").read_text(encoding="utf-8")

    def test_korean_skeleton_is_unchanged(self, tmp_path):
        project = create_project(tmp_path / "ko-proj", name="ko-agent", language="ko")
        assert "절대 커밋하지 마세요" in (project.root / ".gitignore").read_text(encoding="utf-8")

    def test_an_unknown_language_still_produces_a_project(self, tmp_path):
        project = create_project(tmp_path / "xx-proj", name="xx-agent", language="xx")
        assert (project.root / ".gitignore").exists()

    def test_document_labels_follow_the_language(self, english):
        assert slot_for("01").title() == "Educational design"
        set_language("ko")
        assert slot_for("01").title() == "교육 설계"


# --- principle library ----------------------------------------------------
class TestPrincipleLibrary:
    """The library is cited scholarship, so it is translated as content, not code.

    Only the *mechanism* is in place here: ``library/<lang>/``, resolved the way
    templates are. There is no English library yet, and falling back to Korean is
    the intended behaviour until somebody writes one.
    """

    def test_the_korean_library_loads(self, korean):
        from edu_agent.principles.library_loader import library_entries

        entries = library_entries()
        assert len(entries) == 10
        assert all(e.sources for e in entries), "every entry must cite something"

    def test_an_untranslated_language_falls_back_rather_than_emptying(self, english):
        from edu_agent.principles.library_loader import library_entries

        assert [e.library_id for e in library_entries()] == [
            e.library_id for e in library_entries("ko")
        ]

    def test_ids_resolve_across_languages(self):
        """A project records ``library_id``; it must still resolve if the reader
        opens the project in the other language."""
        from edu_agent.principles.library_loader import find_entry

        assert find_entry("lib.reasoning_first", "ko") is not None
        assert find_entry("lib.reasoning_first", "en") is not None
        assert find_entry("lib.no.such.thing", "ko") is None

"""Running the whole document pipeline in English.

The harness is taught in Korean, so the risk is not that English is missing but
that it is half-present: a Korean placeholder inside an English document, or a
template that silently falls back without anyone noticing.
"""

from __future__ import annotations

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


def test_missing_language_falls_back_to_korean():
    set_language("fr")
    try:
        assert get_language() == "ko"
    finally:
        set_language("ko")


def test_unknown_key_returns_itself(korean):
    assert t("nothing.like.this") == "nothing.like.this"


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

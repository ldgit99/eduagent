"""Reading design principles out of a Markdown file the teacher wrote.

There is no agreed format for such a document, so the parser has to cope with the
shapes people actually write. These tests pin the two that matter and the ways a
file arrives broken.
"""

from __future__ import annotations

import pytest

from edu_agent.principles.markdown_source import (
    MAX_STATEMENT_CHARS,
    MarkdownSourceError,
    extract_statements,
    read_source,
)

SECTIONED = """\
# 설계원리

이 문서는 C 디버깅 코치의 설계원리입니다.

## 추론 우선

학습자가 먼저 자기 생각을 말하게 한 뒤에만 힌트를 제공한다.
어디가 문제라고 생각하는지 묻는 것으로 시작한다.

## 점진적 스캐폴딩

가장 약한 힌트부터 시작해 학습자 반응에 따라 수준을 올린다.

## 오개념 대응

학습자가 틀린 주장을 강하게 하더라도 동의하지 않는다.
"""

LISTED = """\
# 우리 반 튜터 원칙

- 학습자가 먼저 자기 생각을 말하게 한 뒤에 힌트를 준다
- 가장 약한 힌트부터 단계적으로 올린다
- 해결한 뒤에는 과정을 설명하게 한다
"""

PROSE = """\
학습자가 먼저 자기 생각을 말하게 한 뒤에만 힌트를 제공한다.

가장 약한 힌트부터 시작해 학습자 반응에 따라 수준을 올린다.
"""


class TestSectioned:
    def test_each_heading_becomes_one_principle(self):
        statements = extract_statements(SECTIONED)
        assert len(statements) == 3
        assert statements[0].startswith("추론 우선.")

    def test_body_is_carried_with_the_heading(self):
        first = extract_statements(SECTIONED)[0]
        assert "자기 생각을 말하게 한 뒤" in first
        assert "어디가 문제라고 생각하는지" in first

    def test_document_title_is_not_a_principle(self):
        """A `# 설계원리` title would otherwise swallow the whole file."""
        statements = extract_statements(SECTIONED)
        assert not any(s.startswith("설계원리") for s in statements)
        assert not any("이 문서는" in s for s in statements)


class TestListed:
    def test_each_bullet_becomes_one_principle(self):
        statements = extract_statements(LISTED)
        assert len(statements) == 3
        assert statements[0].startswith("학습자가 먼저")

    def test_bullet_markers_are_removed(self):
        assert all(not s.startswith(("-", "*", "·")) for s in extract_statements(LISTED))

    def test_plain_paragraphs_work_too(self):
        assert len(extract_statements(PROSE)) == 2


class TestRobustness:
    def test_code_blocks_are_not_principles(self):
        text = LISTED + "\n```python\nprint('this is an example, not a principle')\n```\n"
        statements = extract_statements(text)
        assert len(statements) == 3
        assert not any("print(" in s for s in statements)

    def test_blockquotes_and_rules_are_stripped(self):
        text = "## 원리 하나\n\n> 근거: Wang 2024\n\n---\n\n학습자에게 먼저 묻는다.\n\n## 원리 둘\n\n짧은 힌트부터 준다.\n"
        statements = extract_statements(text)
        assert len(statements) == 2
        assert all("---" not in s for s in statements)
        assert "근거: Wang 2024" in statements[0]

    def test_a_runaway_section_is_clipped(self):
        text = "## 원리\n\n" + ("아주 긴 설명. " * 500) + "\n\n## 둘\n\n짧은 원리입니다.\n"
        assert all(len(s) <= MAX_STATEMENT_CHARS + 2 for s in extract_statements(text))

    def test_empty_document_yields_nothing(self):
        assert extract_statements("\n\n   \n") == []

    def test_headings_alone_are_kept_even_without_a_body(self):
        text = "## 학습자에게 먼저 생각을 묻는다\n\n## 힌트는 약한 것부터 준다\n"
        assert len(extract_statements(text)) == 2


class TestReadSource:
    def test_reads_utf8(self, tmp_path):
        path = tmp_path / "p.md"
        path.write_text(SECTIONED, encoding="utf-8")
        assert "추론 우선" in read_source(path)

    def test_reads_cp949_because_korean_windows_tools_write_it(self, tmp_path):
        path = tmp_path / "p.md"
        path.write_bytes(LISTED.encode("cp949"))
        assert "약한 힌트" in read_source(path)

    def test_missing_file_says_so_in_words(self, tmp_path):
        with pytest.raises(MarkdownSourceError, match="찾을 수 없습니다"):
            read_source(tmp_path / "nope.md")

    def test_directory_is_refused(self, tmp_path):
        with pytest.raises(MarkdownSourceError, match="폴더"):
            read_source(tmp_path)

    def test_empty_file_is_refused(self, tmp_path):
        path = tmp_path / "empty.md"
        path.write_text("   \n", encoding="utf-8")
        with pytest.raises(MarkdownSourceError, match="비어 있습니다"):
            read_source(path)


def test_the_original_text_is_what_gets_stored(tmp_path):
    """Structuring must always be auditable against what the teacher wrote.

    Surrounding whitespace goes — the document models strip it on assignment —
    but every line of content has to survive, because this is the only copy of
    the teacher's own wording once the principles have been turned into rules.
    """
    from edu_agent.schemas.principles import DesignPrinciples

    path = tmp_path / "p.md"
    path.write_text(SECTIONED, encoding="utf-8")
    doc = DesignPrinciples.new(language="ko")
    doc.raw_user_text = read_source(path)

    assert doc.raw_user_text == SECTIONED.strip()
    for line in SECTIONED.splitlines():
        assert line in doc.raw_user_text

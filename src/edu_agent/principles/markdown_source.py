"""Reading design principles out of a Markdown file the user already wrote.

Teachers arrive with principles in a document, not in their head, and pasting a
long file into a terminal mangles it — line endings, bracketed-paste limits, and
a prompt that cannot scroll back. So the harness reads the file.

The parser is deliberately forgiving because there is no agreed format for such a
document. It recognises the two shapes people actually write:

* **Sectioned** — each ``##`` heading is one principle, its body the description.
* **Listed** — a flat bullet list (or plain paragraphs) where each item is one.

Whatever it finds, the original text is kept verbatim in
``DesignPrinciples.raw_user_text`` so the structuring can always be audited
against what the teacher actually wrote.
"""

from __future__ import annotations

import re
from pathlib import Path

#: Anything longer is almost certainly a pasted chapter, not a principle.
MAX_STATEMENT_CHARS = 1200
#: Below this a "statement" is a stray word, a separator, or a stray heading.
MIN_STATEMENT_CHARS = 8

_FENCE = re.compile(r"^\s*(```|~~~)")
_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_BULLET = re.compile(r"^\s*(?:[-*+·]|\d+[.)])\s+(.*\S)\s*$")
#: Headings that name the document or a section *about* principles rather than
#: being one. Matched loosely; a false negative only costs one junk statement.
_NOT_A_PRINCIPLE = re.compile(
    r"^(설계\s*원리|설계원리|design\s+principles?|목차|contents?|개요|overview|"
    r"참고\s*문헌|references?|서론|introduction)\s*$",
    re.IGNORECASE,
)


class MarkdownSourceError(Exception):
    """The file cannot be used as a source of principles."""


def read_source(path: Path) -> str:
    """Read a Markdown file, with errors a non-programmer can act on."""
    if not path.exists():
        raise MarkdownSourceError(f"파일을 찾을 수 없습니다: {path}")
    if path.is_dir():
        raise MarkdownSourceError(f"폴더가 아니라 파일을 지정해 주세요: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # A file saved from Korean Windows tools is often cp949, not UTF-8.
        try:
            text = path.read_text(encoding="cp949")
        except (UnicodeDecodeError, LookupError):
            raise MarkdownSourceError(
                f"파일의 문자 인코딩을 읽지 못했습니다: {path.name}. UTF-8로 저장해 주세요."
            ) from None
    if not text.strip():
        raise MarkdownSourceError(f"파일이 비어 있습니다: {path.name}")
    return text


def extract_statements(text: str) -> list[str]:
    """Pull one statement per principle out of ``text``."""
    lines = _without_code_fences(text)
    sectioned = _from_sections(lines)
    if sectioned:
        return sectioned
    return _from_items(lines)


def _without_code_fences(text: str) -> list[str]:
    """Drop fenced blocks: example code is never a design principle."""
    out: list[str] = []
    inside = False
    for line in text.splitlines():
        if _FENCE.match(line):
            inside = not inside
            continue
        if not inside:
            out.append(line)
    return out


def _from_sections(lines: list[str]) -> list[str]:
    """Each heading at the most-repeated level becomes one principle."""
    headings = [(i, m) for i, line in enumerate(lines) if (m := _HEADING.match(line))]
    if len(headings) < 2:
        return []

    # The level used most often is the one enumerating principles; a single `#`
    # title above them should not swallow the whole document.
    counts: dict[int, int] = {}
    for _, match in headings:
        counts[len(match.group(1))] = counts.get(len(match.group(1)), 0) + 1
    level = max(counts, key=lambda depth: (counts[depth], -depth))
    if counts[level] < 2:
        return []

    chosen = [(i, m) for i, m in headings if len(m.group(1)) == level]
    statements: list[str] = []
    for position, (index, match) in enumerate(chosen):
        end = chosen[position + 1][0] if position + 1 < len(chosen) else len(lines)
        title = match.group(2).strip()
        if _NOT_A_PRINCIPLE.match(title):
            continue
        body = " ".join(
            stripped
            for line in lines[index + 1 : end]
            if (stripped := _strip_markup(line))
        )
        statements.append(_clip(f"{title}. {body}".strip() if body else title))
    return [s for s in statements if len(s) >= MIN_STATEMENT_CHARS]


def _from_items(lines: list[str]) -> list[str]:
    """No headings: take bullets, or failing that, paragraphs."""
    bullets = [m.group(1).strip() for line in lines if (m := _BULLET.match(line))]
    items = bullets or _paragraphs(lines)
    return [_clip(item) for item in items if len(item) >= MIN_STATEMENT_CHARS]


def _paragraphs(lines: list[str]) -> list[str]:
    out: list[str] = []
    current: list[str] = []
    for line in lines:
        stripped = _strip_markup(line)
        if stripped:
            current.append(stripped)
        elif current:
            out.append(" ".join(current))
            current = []
    if current:
        out.append(" ".join(current))
    return out


def _strip_markup(line: str) -> str:
    """Remove the characters that carry no meaning once the text is a statement."""
    text = line.strip()
    if not text or text.startswith(">"):
        text = text.lstrip("> ").strip()
    if _HEADING.match(text):
        text = _HEADING.match(text).group(2)  # type: ignore[union-attr]
    bullet = _BULLET.match(text)
    if bullet:
        text = bullet.group(1)
    if set(text) <= {"-", "=", "*", "_", " "}:  # a horizontal rule
        return ""
    return text.strip()


def _clip(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= MAX_STATEMENT_CHARS:
        return collapsed
    return collapsed[:MAX_STATEMENT_CHARS].rstrip() + " …"


__all__ = [
    "MAX_STATEMENT_CHARS",
    "MIN_STATEMENT_CHARS",
    "MarkdownSourceError",
    "extract_statements",
    "read_source",
]

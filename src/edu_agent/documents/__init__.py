"""Markdown-with-frontmatter document I/O (plan v2 §5.1).

Every project document is one file with two halves:

* **YAML frontmatter** — the machine-readable source of truth, validated by a
  Pydantic model.
* **Markdown body** — rendered from a Jinja template, for the human to read.

The student is allowed to edit the body by hand. ``content_hash`` in the
frontmatter records what the harness last rendered, so ``edu-agent review`` can
notice the divergence (*drift*) and offer to re-extract the structure instead of
silently overwriting the student's edits.
"""

from edu_agent.documents.io import (
    DocumentFile,
    detect_drift,
    load_document,
    parse_frontmatter,
    save_document,
    split_frontmatter,
)
from edu_agent.documents.render import render_document

__all__ = [
    "DocumentFile",
    "detect_drift",
    "load_document",
    "parse_frontmatter",
    "render_document",
    "save_document",
    "split_frontmatter",
]

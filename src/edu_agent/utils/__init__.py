"""Small shared helpers with no dependencies on other harness modules."""

from edu_agent.utils.hashing import hash_text, short_hash
from edu_agent.utils.text import (
    normalize_code,
    normalize_for_match,
    sentence_count,
    strip_code_fences,
    truncate,
    word_count,
)

__all__ = [
    "hash_text",
    "normalize_code",
    "normalize_for_match",
    "sentence_count",
    "short_hash",
    "strip_code_fences",
    "truncate",
    "word_count",
]

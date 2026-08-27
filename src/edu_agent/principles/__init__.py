"""Design-principle library and the natural-language → executable structurer."""

from edu_agent.principles.library_loader import (
    LibraryEntry,
    library_entries,
    load_library,
    to_principle,
)

__all__ = ["LibraryEntry", "library_entries", "load_library", "to_principle"]

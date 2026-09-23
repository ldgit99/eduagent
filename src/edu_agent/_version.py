"""Single source of truth for the package version (kept in sync with pyproject.toml)."""

__version__ = "0.3.0"

# Schema version for the four project documents. Bump when a document's
# frontmatter structure changes incompatibly; ``documents.migrate`` (future)
# will use it to upgrade older projects.
SCHEMA_VERSION = 1

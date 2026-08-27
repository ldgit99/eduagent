"""Project discovery, layout and configuration."""

from edu_agent.project.config import ProjectConfig, ProviderProfile
from edu_agent.project.layout import (
    DOC_FILES,
    DocSlot,
    Project,
    ProjectNotFound,
    create_project,
    find_project,
)

__all__ = [
    "DOC_FILES",
    "DocSlot",
    "Project",
    "ProjectConfig",
    "ProjectNotFound",
    "ProviderProfile",
    "create_project",
    "find_project",
]

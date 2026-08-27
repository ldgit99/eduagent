"""Pydantic domain models for the four core project documents.

Document -> root model mapping (the harness's "compilation units"):

    01_educational_design.md   -> EducationalDesign
    02_design_principles.md    -> DesignPrinciples
    03_technical_spec.md       -> TechnicalSpec
    04_agent_spec.md           -> AgentSpec   (produced by ``edu-agent compile``)

All root models derive from :class:`edu_agent.schemas.common.DocumentModel` which
carries the shared ``meta`` block (schema name/version, status, timestamps).
"""

from edu_agent.schemas.agent import AgentSpec
from edu_agent.schemas.common import (
    CheckType,
    DocumentMeta,
    DocumentModel,
    DocumentStatus,
    IdPrefix,
    make_id,
    validate_id,
)
from edu_agent.schemas.educational import EducationalDesign
from edu_agent.schemas.principles import DesignPrinciples
from edu_agent.schemas.technical import TechnicalSpec

DOCUMENT_MODELS: dict[str, type[DocumentModel]] = {
    "educational_design": EducationalDesign,
    "design_principles": DesignPrinciples,
    "technical_spec": TechnicalSpec,
    "agent_spec": AgentSpec,
}

__all__ = [
    "DOCUMENT_MODELS",
    "AgentSpec",
    "CheckType",
    "DesignPrinciples",
    "DocumentMeta",
    "DocumentModel",
    "DocumentStatus",
    "EducationalDesign",
    "IdPrefix",
    "TechnicalSpec",
    "make_id",
    "validate_id",
]

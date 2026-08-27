"""edu-agent-harness: Pedagogy-Aware Educational AI Agent Engineering Harness.

The package is organised around three layers that must stay traceable to each other::

    Educational Design  ->  Technical Architecture  ->  Executable Agent Specification

Sub-packages (see docs/01_architecture.md):

- ``schemas``       Pydantic domain models for the four project documents.
- ``documents``     Markdown-with-frontmatter reading/writing and drift detection.
- ``questionnaire`` Data-driven interactive questionnaire engine (Rich UI, scriptable).
- ``project``       Project discovery, configuration (``edu-agent.yaml``) and paths.
- ``compiler``      (Phase 3) validation + LLM-assisted generation of ``04_agent_spec.md``.
- ``builder``       (Phase 4) code generation for runnable agent projects.
- ``providers``     (Phase 3) thin LLM provider abstraction + MockProvider.
- ``simulator``     (Phase 5) synthetic learner personas.
- ``evaluator``     (Phase 5) deterministic + LLM-judge educational fidelity evaluation.
- ``optimizer``     (Phase 6) eval-guided improvement proposals.
"""

from edu_agent._version import __version__

__all__ = ["__version__"]

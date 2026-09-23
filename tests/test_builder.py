"""Exported projects.

The generated code cannot be imported here (a FastAPI export would need FastAPI
installed), so the contract these tests hold it to is: the tree matches plan §12,
the Python parses, the policy files say what the spec says, and no secret is
written into any of it.
"""

from __future__ import annotations

import ast

import pytest
import yaml

from edu_agent.builder import TARGETS, export
from edu_agent.documents import render_document, save_document


@pytest.fixture
def exported(request, tmp_project, compiled_spec):
    """A project exported with the target named by the test's parameter."""
    target = getattr(request, "param", "cli")
    for index, model in ((4, compiled_spec),):
        slot = {4: "agent_spec.md.j2"}[index]
        save_document(
            tmp_project.doc_path(f"{index:02d}"),
            model,
            render_document(slot, d=model),
        )
    destination = tmp_project.root / f"generated-{target}"
    export(target, tmp_project, compiled_spec, destination)
    return destination


@pytest.mark.parametrize("exported", sorted(TARGETS), indirect=True)
class TestSharedLayout:
    def test_writes_the_documented_tree(self, exported):
        for relative in (
            "app/spec/04_agent_spec.md",
            "app/prompts/system.md",
            "app/policies/gates.yaml",
            "app/policies/behaviors.yaml",
            "app/tools/policy.yaml",
            "app/safety/rules.md",
            "evals/rubric.yaml",
            "tests/test_agent.py",
            "README.md",
            ".env.example",
            ".gitignore",
            "pyproject.toml",
        ):
            assert (exported / relative).exists(), relative

    def test_generated_python_parses(self, exported):
        for path in exported.rglob("*.py"):
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_no_secret_is_written_anywhere(self, exported, monkeypatch):
        """Placeholders are fine; an actual key value is not."""
        for path in exported.rglob("*"):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            assert "sk-" not in text
            for line in text.splitlines():
                if "EDU_AGENT_API_KEY=" in line:
                    value = line.split("EDU_AGENT_API_KEY=", 1)[1].strip().strip("`\"'")
                    assert value in {"", "..."}, f"{path.name}: {line}"

    def test_gitignore_keeps_the_key_out_of_git(self, exported):
        assert ".env" in (exported / ".gitignore").read_text(encoding="utf-8")

    def test_policies_match_the_spec(self, exported, compiled_spec):
        gates = yaml.safe_load((exported / "app" / "policies" / "gates.yaml").read_text("utf-8"))
        assert [g["id"] for g in gates["gates"]] == [g.id for g in compiled_spec.gates]
        for gate in gates["gates"]:
            assert gate["text"] or gate["message"]

    def test_scenarios_are_exported_one_file_each(self, exported, compiled_spec):
        written = sorted(p.stem for p in (exported / "evals" / "scenarios").glob("*.yaml"))
        assert written == sorted(s.id.lower() for s in compiled_spec.scenarios)

    def test_readme_lists_the_rules_the_agent_enforces(self, exported, compiled_spec):
        text = (exported / "README.md").read_text(encoding="utf-8")
        for gate in compiled_spec.gates:
            assert gate.id in text

    def test_spec_stays_the_source_of_truth(self, exported):
        """The entry point must read the spec, not hard-code the behaviour."""
        entry = next(p for p in (exported / "app").glob("*.py") if p.stem in {"agent", "main"})
        source = entry.read_text(encoding="utf-8")
        assert "04_agent_spec.md" in source
        assert "load_document" in source


class TestCliTarget:
    def test_entry_point_is_a_terminal_loop(self, tmp_project, compiled_spec):
        destination = tmp_project.root / "out"
        export("cli", tmp_project, compiled_spec, destination)
        source = (destination / "app" / "agent.py").read_text(encoding="utf-8")
        assert "input(" in source
        assert "def main()" in source

    def test_pins_a_harness_requirement_that_can_actually_be_installed(
        self, tmp_project, compiled_spec
    ):
        from edu_agent.builder.common import HARNESS_REQUIREMENT

        destination = tmp_project.root / "out-req"
        export("cli", tmp_project, compiled_spec, destination)
        text = (destination / "pyproject.toml").read_text(encoding="utf-8")
        assert HARNESS_REQUIREMENT in text
        assert "{harness}" not in text


class TestFastapiTarget:
    @pytest.fixture
    def service(self, tmp_project, compiled_spec):
        destination = tmp_project.root / "svc"
        export("fastapi", tmp_project, compiled_spec, destination)
        return destination

    def test_declares_its_own_dependencies(self, service):
        text = (service / "pyproject.toml").read_text(encoding="utf-8")
        assert "fastapi" in text
        assert "uvicorn" in text

    def test_pins_a_harness_requirement_that_can_actually_be_installed(self, service):
        """A generated project whose first ``pip install`` fails is worse than none."""
        from edu_agent.builder.common import HARNESS_REQUIREMENT

        assert HARNESS_REQUIREMENT in (service / "pyproject.toml").read_text(encoding="utf-8")
        assert "{harness}" not in (service / "pyproject.toml").read_text(encoding="utf-8")

    def test_exposes_the_documented_routes(self, service):
        source = (service / "app" / "main.py").read_text(encoding="utf-8")
        for route in ('@app.get("/health")', '@app.post("/api/turn")', '@app.post("/api/reset")'):
            assert route in source

    def test_saves_traces_the_harness_can_regrade(self, service):
        source = (service / "app" / "main.py").read_text(encoding="utf-8")
        assert "save_session" in source
        assert "RunPaths" in source

    def test_ships_a_dockerfile(self, service):
        assert "uvicorn" in (service / "Dockerfile").read_text(encoding="utf-8")

    def test_readme_admits_what_is_missing(self, service):
        """A class project that implied it had auth would be worse than one that says it does not."""
        text = (service / "README.md").read_text(encoding="utf-8")
        assert "인증" in text


def test_unknown_target_is_refused(tmp_project, compiled_spec):
    with pytest.raises(ValueError, match="알 수 없는"):
        export("nextjs", tmp_project, compiled_spec, tmp_project.root / "x")


class TestTargetFollowsTheDesign:
    """``03_technical_spec.md`` already recorded how the agent should run."""

    def _project_with(self, tmp_project, compiled_spec, example_docs, execution_path):
        from edu_agent.schemas.technical import TechnicalSpec

        educational, principles, technical = example_docs
        assert isinstance(technical, TechnicalSpec)
        technical.execution_path = execution_path
        for slot, model, template in (
            ("01", educational, "educational_design.md.j2"),
            ("02", principles, "design_principles.md.j2"),
            ("03", technical, "technical_spec.md.j2"),
            ("04", compiled_spec, "agent_spec.md.j2"),
        ):
            save_document(
                tmp_project.doc_path(slot), model, render_document(template, d=model)
            )
        return tmp_project

    def test_fastapi_path_selects_the_service_export(
        self, tmp_project, compiled_spec, example_docs, monkeypatch
    ):
        from edu_agent.commands.export import target_from_technical
        from edu_agent.schemas.technical import ExecutionPath

        project = self._project_with(
            tmp_project, compiled_spec, example_docs, ExecutionPath.EXPORT_FASTAPI
        )
        assert target_from_technical(project) == "fastapi"

    def test_runtime_path_selects_the_cli_export(self, tmp_project, compiled_spec, example_docs):
        from edu_agent.commands.export import target_from_technical
        from edu_agent.schemas.technical import ExecutionPath

        project = self._project_with(
            tmp_project, compiled_spec, example_docs, ExecutionPath.HARNESS_RUNTIME
        )
        assert target_from_technical(project) == "cli"

    def test_missing_document_falls_back_to_cli(self, tmp_project):
        from edu_agent.commands.export import target_from_technical

        assert target_from_technical(tmp_project) == "cli"


def test_a_browser_class_is_recommended_the_service_export(example_docs):
    """Many learners at once is the point where one local process stops working."""
    from edu_agent.compiler.recommend import recommend_stack
    from edu_agent.schemas.technical import ExecutionPath, TechnicalSpec

    technical = TechnicalSpec.model_validate(example_docs[2].model_dump())
    technical.requirements.uses_web_browser = True
    technical.requirements.expected_users = 120
    recommend_stack(technical, overwrite=True)

    assert technical.execution_path is ExecutionPath.EXPORT_FASTAPI
    assert any("fastapi" in d.choice.lower() for d in technical.decisions)

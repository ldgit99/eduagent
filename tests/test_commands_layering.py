"""The line between "what a command does" and "how it is invoked".

``cli.py`` had grown to 1,500 lines holding both, which made every workflow
reachable only through argument parsing and made the file the hardest part of the
repository to change one feature at a time. These tests keep the two apart.
"""

from __future__ import annotations

import ast
import pkgutil
from pathlib import Path

import pytest

import edu_agent.commands as commands_pkg
from edu_agent import cli

COMMANDS_DIR = Path(commands_pkg.__file__).parent
MODULES = sorted(m.name for m in pkgutil.iter_modules([str(COMMANDS_DIR)]))


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


class TestLayering:
    @pytest.mark.parametrize("module", MODULES)
    def test_a_workflow_never_imports_the_cli(self, module):
        """Otherwise the split is decorative: the workflow still needs typer to run."""
        imported = _imports(COMMANDS_DIR / f"{module}.py")
        assert "edu_agent.cli" not in imported

    @pytest.mark.parametrize("module", MODULES)
    def test_a_workflow_never_imports_typer(self, module):
        assert "typer" not in _imports(COMMANDS_DIR / f"{module}.py")

    def test_every_workflow_is_importable_on_its_own(self):
        import importlib

        for module in MODULES:
            assert importlib.import_module(f"edu_agent.commands.{module}")


class TestTheShellStaysThin:
    def test_the_cli_declares_arguments_and_delegates(self):
        tree = ast.parse(Path(cli.__file__).read_text(encoding="utf-8"))
        top_level = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
        commanded = [
            n for n in top_level
            if any(
                isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "command"
                for d in n.decorator_list
            )
        ]
        # The commands plus the callback, run_cli and _entry — nothing else should
        # be accumulating here again.
        helpers = [n for n in top_level if n not in commanded]
        assert len(commanded) == 12, [n.name for n in commanded]
        assert len(helpers) <= 3, [n.name for n in helpers]

    def test_it_is_no_longer_the_biggest_file_by_far(self):
        source = Path(cli.__file__).read_text(encoding="utf-8")
        assert len(source.splitlines()) < 1000


def test_the_commands_package_exposes_every_workflow():
    for module in MODULES:
        assert hasattr(commands_pkg, module), module

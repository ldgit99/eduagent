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


class TestTheInstalledEntryPoint:
    """What ``edu-agent`` actually runs after ``uv tool install``.

    The console script used to point straight at ``cli:app``. Typer then runs in
    standalone mode, where ``UserAbort`` — pressing Ctrl+C, or answering ``S`` to
    save and stop — reaches the terminal as a traceback. Every test called
    ``run_cli`` directly, so the suite was blind to the one code path every
    installed copy of the harness takes.
    """

    def _console_scripts(self) -> dict[str, str]:
        import tomllib

        # src/edu_agent/cli.py -> src/edu_agent -> src -> repo root
        pyproject = Path(cli.__file__).resolve().parents[2] / "pyproject.toml"
        if not pyproject.exists():  # installed, not a checkout
            pytest.skip("not running from a source checkout")
        return tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["scripts"]

    def test_it_goes_through_the_friendly_error_handler(self):
        assert self._console_scripts()["edu-agent"] == "edu_agent.cli:run_cli"

    def test_the_handler_is_callable_with_no_arguments_and_returns_a_code(self):
        """A console script wrapper does ``sys.exit(func())``, nothing more."""
        import inspect

        signature = inspect.signature(cli.run_cli)
        assert all(
            p.default is not inspect.Parameter.empty for p in signature.parameters.values()
        )
        assert cli.run_cli(["--version"]) == 0

    @pytest.mark.parametrize(
        "raised, expected_code",
        [
            (lambda: (_ for _ in ()).throw(__import__("edu_agent").ui.UserAbort()), 0),
            (lambda: (_ for _ in ()).throw(__import__("edu_agent").ui.Abort("boom")), 1),
        ],
    )
    def test_stopping_is_a_message_not_a_traceback(self, monkeypatch, raised, expected_code):
        monkeypatch.setattr(cli, "app", lambda **kwargs: raised())
        assert cli.run_cli([]) == expected_code


class TestTheVersionIsOneNumber:
    """``_version.py`` and ``pyproject.toml`` both carry it, by hand.

    ``edu-agent --version`` reads the module; pip and the wheel read the
    metadata. Bump one and forget the other and the CLI reports a version that
    was never released — which is worse than no version at all, because it looks
    authoritative.
    """

    def _pyproject(self) -> dict:
        import tomllib

        path = Path(cli.__file__).resolve().parents[2] / "pyproject.toml"
        if not path.exists():  # installed, not a checkout
            pytest.skip("not running from a source checkout")
        return tomllib.loads(path.read_text(encoding="utf-8"))

    def test_the_module_and_the_metadata_agree(self):
        from edu_agent._version import __version__

        assert __version__ == self._pyproject()["project"]["version"]

    def test_every_runtime_dependency_has_an_upper_bound(self):
        """An unbounded dependency means two people installing a week apart get
        different software from the same command."""
        project = self._pyproject()["project"]
        specs = list(project["dependencies"])
        for extra in project.get("optional-dependencies", {}).values():
            specs.extend(extra)
        unbounded = [s for s in specs if "<" not in s]
        assert not unbounded, f"no upper bound on: {unbounded}"

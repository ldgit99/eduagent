"""Running learner code without trusting it.

``03_technical_spec.md`` can declare a ``code_execution`` tool, and the compiler
already refuses to let it through unsandboxed. This module is the part that makes
that promise real.

Three backends, chosen by :class:`SandboxPolicy`:

* **docker** — the only one that actually isolates. ``--network none``,
  read-only root, memory/pid caps. Used when Docker is reachable.
* **subprocess** — a temp directory, a scrubbed environment, a wall-clock kill,
  POSIX ``rlimit``s where available, and (for Python) a guard module that removes
  sockets and process spawning before the learner's code runs. This is a
  *mitigation*, not a jail: :attr:`ExecResult.isolation` says so, and the harness
  surfaces it rather than implying a guarantee it cannot keep.
* **disabled** — refuses to execute and says why.

Nothing here decides *whether* a tool may run — that is policy, and it lives in
:mod:`edu_agent.runtime.tools`. This module only decides *how* to run it safely.
"""

from __future__ import annotations

import functools
import importlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import Field

from edu_agent.schemas.common import HarnessModel

#: Output that goes back into a model prompt has to stay small, or one runaway
#: ``while(1) printf`` eats the whole context window.
MAX_OUTPUT_BYTES = 4000
DEFAULT_TIMEOUT_S = 10
DEFAULT_MEMORY_MB = 256
#: Compiling is not the learner's time budget. A cold compiler on a slow machine
#: takes longer than anything the learner's own code is allowed to, and charging
#: that to their timeout turns "your code is too slow" into a lie.
MIN_COMPILE_TIMEOUT_S = 60


def compile_timeout(policy: SandboxPolicy) -> int:
    return max(MIN_COMPILE_TIMEOUT_S, policy.timeout_s * 3)


class SandboxError(Exception):
    """Raised when a sandbox cannot be prepared at all."""


class SandboxPolicy(HarnessModel):
    """How code execution is allowed to happen in this project."""

    backend: str = Field(default="auto", description="auto | docker | subprocess | disabled")
    timeout_s: int = Field(default=DEFAULT_TIMEOUT_S, ge=1, le=120)
    memory_mb: int = Field(default=DEFAULT_MEMORY_MB, ge=64, le=4096)
    max_output_bytes: int = Field(default=MAX_OUTPUT_BYTES, ge=200)
    network: bool = Field(default=False, description="기본은 차단. 켜면 보고서에 표시됩니다.")
    languages: list[str] = Field(default_factory=lambda: ["python", "c"])
    docker_images: dict[str, str] = Field(
        default_factory=lambda: {"python": "python:3.12-slim", "c": "gcc:13"}
    )


@dataclass(slots=True)
class ExecRequest:
    """One execution: some code, a language, optional stdin and extra files."""

    language: str
    code: str
    stdin: str = ""
    files: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ExecResult:
    """What came back. Never raises on learner error — that *is* the result."""

    ok: bool = False
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    timed_out: bool = False
    backend: str = "disabled"
    isolation: str = "none"
    truncated: bool = False
    error: str = ""

    def summary(self) -> str:
        """A compact block to hand back to the model."""
        parts: list[str] = []
        if self.error:
            parts.append(f"실행하지 못했습니다: {self.error}")
        if self.timed_out:
            parts.append("시간 초과로 중단했습니다.")
        if self.exit_code is not None:
            parts.append(f"종료 코드: {self.exit_code}")
        if self.stdout:
            parts.append(f"[출력]\n{self.stdout}")
        if self.stderr:
            parts.append(f"[오류 출력]\n{self.stderr}")
        if self.truncated:
            parts.append("(출력이 길어 일부만 표시했습니다)")
        return "\n".join(parts) or "(출력이 없습니다)"


# --- language definitions -------------------------------------------------
@dataclass(frozen=True, slots=True)
class Language:
    """Commands are written against file names *inside* the working directory, so
    one definition serves both a local temp dir and a container mount."""

    name: str
    filename: str
    compile_cmd: tuple[str, ...] = ()
    run_cmd: tuple[str, ...] = ()
    docker_cmd: tuple[str, ...] = ()
    needs: str = ""


LANGUAGES: dict[str, Language] = {
    "python": Language(
        name="python",
        filename="main.py",
        run_cmd=("{tool}", "-s", "-B", "_guard.py", "main.py"),
        docker_cmd=("python", "-s", "-B", "_guard.py", "main.py"),
        needs="python",
    ),
    "c": Language(
        name="c",
        filename="main.c",
        compile_cmd=("{tool}", "-std=c11", "-O0", "-Wall", "main.c", "-o", "program"),
        run_cmd=("./program",),
        docker_cmd=("./program",),
        needs="cc",
    ),
}

ALIASES = {"py": "python", "python3": "python", "c99": "c", "c11": "c"}


def resolve_language(name: str) -> Language | None:
    text = (name or "").strip().lower()
    return LANGUAGES.get(ALIASES.get(text, text))


#: Installed before the learner's Python code runs. It cannot stop a determined
#: attacker (nothing in-process can), but it removes the two things a stray tutor
#: session is actually likely to do: open a socket and spawn a process.
_PY_GUARD = '''\
"""Installed by edu-agent-harness. Removes network access and process spawning."""
import os
import runpy
import sys


def _deny(what):
    def fail(*args, **kwargs):
        raise PermissionError("이 실행 환경에서는 허용되지 않습니다: " + what)

    return fail


try:
    import socket

    socket.socket = _deny("네트워크 접속")
    socket.create_connection = _deny("네트워크 접속")
    socket.getaddrinfo = _deny("네트워크 주소 조회")
except Exception:
    pass

try:
    import subprocess

    subprocess.Popen = _deny("다른 프로그램 실행")
    subprocess.run = _deny("다른 프로그램 실행")
    subprocess.call = _deny("다른 프로그램 실행")
except Exception:
    pass

for _name in ("system", "popen", "fork", "forkpty", "execv", "execve", "execvp", "spawnv"):
    if hasattr(os, _name):
        setattr(os, _name, _deny("다른 프로그램 실행"))

_target = sys.argv[1]
sys.argv = [_target]
runpy.run_path(_target, run_name="__main__")
'''


# --- backends -------------------------------------------------------------
class Sandbox:
    """Base class. ``run`` never raises for learner-caused failures."""

    name = "disabled"
    isolation = "none"

    def __init__(self, policy: SandboxPolicy) -> None:
        self.policy = policy

    def available(self) -> tuple[bool, str]:
        return False, "코드 실행이 꺼져 있습니다."

    def run(self, request: ExecRequest) -> ExecResult:
        return ExecResult(backend=self.name, error=self.available()[1])

    # --- shared helpers ---------------------------------------------------
    def _prepare(self, request: ExecRequest, workdir: Path, lang: Language) -> None:
        (workdir / lang.filename).write_text(request.code, encoding="utf-8", newline="\n")
        if lang.name == "python":
            (workdir / "_guard.py").write_text(_PY_GUARD, encoding="utf-8", newline="\n")
        for rel, content in request.files.items():
            target = _safe_join(workdir, rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")

    def _clip(self, text: str) -> tuple[str, bool]:
        limit = self.policy.max_output_bytes
        if len(text) <= limit:
            return text, False
        return text[:limit], True

    def _reject_language(self, request: ExecRequest) -> ExecResult | None:
        lang = resolve_language(request.language)
        if lang is None or lang.name not in self.policy.languages:
            return ExecResult(
                backend=self.name,
                isolation=self.isolation,
                error=f"'{request.language}' 언어는 이 프로젝트에서 실행할 수 없습니다.",
            )
        return None


class DisabledSandbox(Sandbox):
    name = "disabled"

    def available(self) -> tuple[bool, str]:
        return False, "이 프로젝트는 코드 실행을 사용하지 않습니다."


class SubprocessSandbox(Sandbox):
    """Local execution with the limits a single process can impose on itself."""

    name = "subprocess"
    isolation = "partial"

    def available(self) -> tuple[bool, str]:
        return True, ""

    def run(self, request: ExecRequest) -> ExecResult:
        rejected = self._reject_language(request)
        if rejected is not None:
            return rejected
        lang = resolve_language(request.language)
        assert lang is not None
        tool = _toolchain(lang)
        if tool is None:
            return ExecResult(
                backend=self.name, isolation=self.isolation,
                error=_missing_toolchain_message(lang),
            )

        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="edu-agent-exec-") as tmp:
            workdir = Path(tmp)
            try:
                self._prepare(request, workdir, lang)
            except SandboxError as exc:
                return ExecResult(backend=self.name, isolation=self.isolation, error=str(exc))

            if lang.compile_cmd:
                built = _spawn(
                    [c.format(tool=tool) for c in lang.compile_cmd],
                    workdir,
                    "",
                    self.policy,
                    timeout_s=compile_timeout(self.policy),
                )
                if built.timed_out or built.returncode != 0:
                    text, truncated = self._clip(built.stderr or built.stdout)
                    return ExecResult(
                        exit_code=built.returncode,
                        stderr=text,
                        truncated=truncated,
                        timed_out=built.timed_out,
                        duration_ms=_ms(started),
                        backend=self.name,
                        isolation=self.isolation,
                        error=(
                            "컴파일이 제한 시간 안에 끝나지 않았습니다."
                            if built.timed_out
                            else "컴파일에 실패했습니다."
                        ),
                    )

            proc = _spawn(
                [c.format(tool=tool) for c in lang.run_cmd], workdir, request.stdin, self.policy
            )

        return self._finish(proc, started)

    def _finish(self, proc: _Proc, started: float) -> ExecResult:
        stdout, clipped_out = self._clip(proc.stdout)
        stderr, clipped_err = self._clip(proc.stderr)
        return ExecResult(
            ok=not proc.timed_out and proc.returncode == 0,
            exit_code=proc.returncode,
            stdout=stdout,
            stderr=stderr,
            truncated=clipped_out or clipped_err,
            timed_out=proc.timed_out,
            duration_ms=_ms(started),
            backend=self.name,
            isolation=self.isolation,
        )


class DockerSandbox(SubprocessSandbox):
    """Real isolation: no network, read-only root, capped memory and pids."""

    name = "docker"
    isolation = "container"

    def available(self) -> tuple[bool, str]:
        if not shutil.which("docker"):
            return False, "docker 명령을 찾을 수 없습니다."
        if not _docker_ready():
            return False, "docker 가 실행 중이 아닙니다."
        return True, ""

    def run(self, request: ExecRequest) -> ExecResult:
        ok, why = self.available()
        if not ok:
            return ExecResult(backend=self.name, isolation=self.isolation, error=why)
        rejected = self._reject_language(request)
        if rejected is not None:
            return rejected
        lang = resolve_language(request.language)
        assert lang is not None
        image = self.policy.docker_images.get(lang.name)
        if not image:
            return ExecResult(
                backend=self.name, isolation=self.isolation,
                error=f"'{lang.name}' 용 docker 이미지가 설정되지 않았습니다.",
            )

        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="edu-agent-exec-") as tmp:
            workdir = Path(tmp)
            try:
                self._prepare(request, workdir, lang)
            except SandboxError as exc:
                return ExecResult(backend=self.name, isolation=self.isolation, error=str(exc))
            proc = _spawn(
                self._docker_cmd(lang, image, workdir),
                workdir,
                request.stdin,
                self.policy,
                rlimits=False,
                # Pulling or starting an image is not the learner's time budget.
                timeout_s=self.policy.timeout_s + 30,
            )
        return self._finish(proc, started)

    def _docker_cmd(self, lang: Language, image: str, workdir: Path) -> list[str]:
        steps: list[str] = []
        if lang.compile_cmd:
            steps.append(" ".join(c.format(tool="cc") for c in lang.compile_cmd))
        steps.append(" ".join(lang.docker_cmd))
        return [
            "docker", "run", "--rm", "-i",
            "--network", "bridge" if self.policy.network else "none",
            "--memory", f"{self.policy.memory_mb}m",
            "--memory-swap", f"{self.policy.memory_mb}m",
            "--pids-limit", "64",
            "--cpus", "1",
            "--read-only",
            "--tmpfs", "/tmp:rw,size=32m,exec",
            "-v", f"{workdir}:/work",
            "-w", "/work",
            image, "sh", "-c", " && ".join(steps),
        ]


def get_sandbox(policy: SandboxPolicy | None = None) -> Sandbox:
    """Pick a backend. ``auto`` prefers real isolation and falls back loudly."""
    policy = policy or SandboxPolicy()
    backend = (policy.backend or "auto").lower()
    if backend == "disabled":
        return DisabledSandbox(policy)
    if backend == "docker":
        return DockerSandbox(policy)
    if backend == "subprocess":
        return SubprocessSandbox(policy)

    docker = DockerSandbox(policy)
    return docker if docker.available()[0] else SubprocessSandbox(policy)


def describe_backends(policy: SandboxPolicy | None = None) -> list[tuple[str, bool, str]]:
    """``doctor`` uses this to tell a student what is actually available here."""
    policy = policy or SandboxPolicy()
    rows: list[tuple[str, bool, str]] = []
    for cls in (DockerSandbox, SubprocessSandbox):
        sandbox = cls(policy)
        ok, why = sandbox.available()
        rows.append((sandbox.name, ok, why))
    for lang in sorted(LANGUAGES.values(), key=lambda item: item.name):
        tool = _toolchain(lang)
        rows.append((
            f"{lang.name} 실행기",
            tool is not None,
            "" if tool else _missing_toolchain_message(lang),
        ))
    return rows


# --- process plumbing -----------------------------------------------------
@dataclass(slots=True)
class _Proc:
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool


#: Anything that could carry an API key into learner code is dropped. ``PATH``
#: stays because a compiler needs it, the Windows entries because the loader does.
_KEEP_ENV = ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "LANG", "LC_ALL")


def _child_env() -> dict[str, str]:
    env = {key: os.environ[key] for key in _KEEP_ENV if key in os.environ}
    # ``-s -B`` rather than ``-I``: isolated mode would also discard these,
    # and then the child's Korean traceback comes back as mojibake.
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["HOME"] = env.get("TEMP", ".")
    return env


def _spawn(
    cmd: list[str],
    workdir: Path,
    stdin: str,
    policy: SandboxPolicy,
    *,
    rlimits: bool = True,
    timeout_s: int | None = None,
) -> _Proc:
    kwargs: dict[str, object] = {}
    if rlimits and os.name == "posix":
        # The child is a fresh fork that only calls setrlimit before exec.
        kwargs["preexec_fn"] = _limits(policy)
        kwargs["start_new_session"] = True

    try:
        # An argv list, never a shell string: the learner's code is a *file* we
        # wrote, so nothing they typed is ever parsed as a command.
        completed = subprocess.run(
            cmd,
            cwd=str(workdir),
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s or policy.timeout_s,
            env=_child_env(),
            check=False,
            **kwargs,  # type: ignore[arg-type]
        )
    except subprocess.TimeoutExpired as exc:
        return _Proc(None, _as_text(exc.stdout), _as_text(exc.stderr), timed_out=True)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        # ``run`` promises never to raise for a failed execution, and a child that
        # dies during setup is a failed execution like any other.
        return _Proc(None, "", str(exc), timed_out=False)
    return _Proc(completed.returncode, completed.stdout, completed.stderr, timed_out=False)


def _limits(policy: SandboxPolicy):  # pragma: no cover - POSIX only
    """Build the ``preexec_fn`` that caps the child.

    Every limit is applied on its own and failures are swallowed. Anything raised
    in ``preexec_fn`` becomes a ``SubprocessError`` in the parent and takes the
    whole execution down, and platforms disagree about which limits they accept —
    macOS in particular refuses ``RLIMIT_AS`` outright. A limit we cannot set is
    a weaker sandbox, which :attr:`ExecResult.isolation` already reports; it is
    not a reason to fail the run.
    """
    # Imported dynamically because ``resource`` does not exist on Windows, where
    # the type checker also runs; the caller already guards on ``os.name``.
    resource: Any = importlib.import_module("resource")

    memory = policy.memory_mb * 1024 * 1024
    wanted = [
        ("RLIMIT_CPU", (policy.timeout_s, policy.timeout_s + 1)),
        ("RLIMIT_FSIZE", (8 * 1024 * 1024, 8 * 1024 * 1024)),
        ("RLIMIT_NOFILE", (64, 64)),
        ("RLIMIT_CORE", (0, 0)),
    ]
    # On Darwin an address-space cap either fails or breaks the interpreter it is
    # meant to contain, so it is only attempted where it actually works.
    if sys.platform != "darwin":
        wanted.insert(1, ("RLIMIT_AS", (memory, memory)))

    def apply() -> None:
        for name, values in wanted:
            limit = getattr(resource, name, None)
            if limit is None:
                continue
            try:
                resource.setrlimit(limit, values)
            except (ValueError, OSError):
                continue

    return apply


@functools.lru_cache(maxsize=1)
def _docker_ready() -> bool:
    try:
        proc = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


@functools.lru_cache(maxsize=8)
def _toolchain(lang: Language) -> str | None:
    if lang.needs == "python":
        return sys.executable
    for candidate in ("gcc", "cc", "clang"):
        found = shutil.which(candidate)
        if found:
            return found
    return None


def _missing_toolchain_message(lang: Language) -> str:
    if lang.needs == "cc":
        return "C 컴파일러(gcc)를 찾을 수 없습니다. 이 컴퓨터에서는 C 코드를 실행할 수 없습니다."
    return f"'{lang.name}' 실행기를 찾을 수 없습니다."


def _safe_join(root: Path, relative: str) -> Path:
    """Reject ``../`` and absolute paths before anything is written."""
    candidate = (root / relative).resolve()
    if not str(candidate).startswith(str(root.resolve())):
        raise SandboxError(f"작업 폴더 밖의 경로에는 쓸 수 없습니다: {relative}")
    return candidate


def _as_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


__all__ = [
    "DEFAULT_TIMEOUT_S",
    "LANGUAGES",
    "MIN_COMPILE_TIMEOUT_S",
    "DisabledSandbox",
    "DockerSandbox",
    "ExecRequest",
    "ExecResult",
    "Sandbox",
    "SandboxError",
    "SandboxPolicy",
    "SubprocessSandbox",
    "compile_timeout",
    "describe_backends",
    "get_sandbox",
    "resolve_language",
]

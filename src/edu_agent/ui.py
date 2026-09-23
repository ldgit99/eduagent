"""Terminal UI helpers.

Two constraints shape this module:

* **The user has never programmed.** Errors say what happened, what to do next, and
  which command to run. Tracebacks appear only with ``--verbose``.
* **Most students are on Windows.** Arrow-key selection widgets misbehave in
  PowerShell and legacy conhost, so every choice is a *numbered* prompt (ADR-12),
  and stdout is forced to UTF-8 so Korean text does not turn into mojibake.
"""

from __future__ import annotations

import contextlib
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, NoReturn, Protocol

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from edu_agent.i18n import t


def configure_stdio() -> None:
    """Force UTF-8 on Windows terminals that default to cp949.

    Public because anything that prints Korean needs it, not just the CLI —
    ``scripts/make_example.py`` used plain ``print`` and died on its own warning
    text under a Windows codepage.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(ValueError, OSError):  # exotic terminals
                reconfigure(encoding="utf-8", errors="replace")


configure_stdio()

console = Console(soft_wrap=False, highlight=False)
err_console = Console(stderr=True, soft_wrap=False, highlight=False)

RULE = "━" * 46


class UserAbort(Exception):
    """The user chose to stop. Not an error — work so far is saved."""


class Abort(Exception):
    """A fatal but explained problem."""

    def __init__(self, message: str, hint: str = "", command: str = "") -> None:
        self.hint = hint
        self.command = command
        super().__init__(message)


def header(title: str, subtitle: str = "", step: tuple[int, int] | None = None) -> None:
    console.print()
    console.print(f"[dim]{RULE}[/dim]")
    if step:
        console.print(f"[bold cyan]{t('review.step', n=step[0], total=step[1])}[/bold cyan]")
    console.print(f"[bold]{title}[/bold]")
    if subtitle:
        console.print(f"[dim]{subtitle}[/dim]")
    console.print(f"[dim]{RULE}[/dim]")


def say(message: str = "") -> None:
    console.print(message)


def info(message: str) -> None:
    console.print(f"[cyan]·[/cyan] {message}")


def ok(message: str) -> None:
    console.print(f"[green]✔[/green] {message}")


def warn(message: str) -> None:
    console.print(f"[yellow]⚠[/yellow] {message}")


def fail(message: str) -> None:
    console.print(f"[red]✘[/red] {message}")


def note(message: str) -> None:
    console.print(f"  [dim]{message}[/dim]")


def why(message: str) -> None:
    """Explain why a question is being asked (plan v2 §4.4 / §17)."""
    console.print(f"  [dim]({t('common.why_ask')} {message})[/dim]")


def panel(body: str, title: str = "", style: str = "cyan") -> None:
    console.print(Panel(body, title=title or None, border_style=style, padding=(1, 2)))


def die(message: str, hint: str = "", command: str = "") -> NoReturn:
    raise Abort(message, hint, command)


def render_abort(exc: Abort) -> None:
    err_console.print(f"[red]✘[/red] {exc}")
    if exc.hint:
        err_console.print(f"  [dim]{exc.hint}[/dim]")
    if exc.command:
        err_console.print(f"  [bold]{exc.command}[/bold] 을(를) 실행해 보세요.")


# --- input ----------------------------------------------------------------
@dataclass(slots=True)
class Choice:
    key: str
    label: str
    value: Any = None
    hint: str = ""


def ask_text(question: str, *, default: str = "", allow_empty: bool = True,
             multiline: bool = False, hint: str = "") -> str:
    """Free-text answer. ``/quit`` saves and exits, from anywhere."""
    console.print(f"\n[bold]{question}[/bold]")
    if hint:
        why(hint)
    if default:
        note(f"엔터만 누르면: {default}")
    if multiline:
        note("여러 줄로 쓸 수 있습니다. 다 쓰면 빈 줄에서 엔터를 두 번 누르세요.")
        lines: list[str] = []
        while True:
            line = _input("  ")
            if not line.strip() and (lines and not lines[-1].strip()):
                break
            if not line.strip() and not lines:
                break
            lines.append(line)
        text = "\n".join(lines).strip()
        return text or default

    while True:
        raw = _input("  > ").strip()
        if raw in {"/quit", "/q", "/exit"}:
            raise UserAbort
        if not raw:
            if default or allow_empty:
                return default
            fail("답을 입력해 주세요.")
            continue
        return raw


def ask_choice(
    question: str,
    choices: Sequence[Choice],
    *,
    hint: str = "",
    default: str = "",
    allow_later: bool = True,
) -> Any:
    """Numbered single choice — the only selection widget we use."""
    console.print(f"\n[bold]{question}[/bold]")
    if hint:
        why(hint)
    for choice in choices:
        line = f"  [{choice.key}] {choice.label}"
        if choice.hint:
            line += f"  [dim]— {choice.hint}[/dim]"
        console.print(line)
    if allow_later:
        console.print(f"  [S] {t('common.later')}")

    keys = {c.key.lower(): c for c in choices}
    while True:
        raw = _input("  > ").strip().lower()
        if raw in {"/quit", "/q", "/exit"} or (allow_later and raw == "s"):
            raise UserAbort
        if not raw and default:
            raw = default.lower()
        if raw in keys:
            choice = keys[raw]
            return choice.value if choice.value is not None else choice.key
        fail(t("errors.invalid_choice", max=len(choices)))


def ask_multi(
    question: str,
    choices: Sequence[Choice],
    *,
    hint: str = "",
    allow_empty: bool = True,
) -> list[Any]:
    """Numbered multi-select: ``1,3,5`` or ``all``."""
    console.print(f"\n[bold]{question}[/bold]")
    if hint:
        why(hint)
    for choice in choices:
        line = f"  [{choice.key}] {choice.label}"
        if choice.hint:
            line += f"  [dim]— {choice.hint}[/dim]"
        console.print(line)
    note("쉼표로 여러 개를 고를 수 있습니다 (예: 1,3,5). 전체는 'all', 없으면 엔터.")

    keys = {c.key.lower(): c for c in choices}
    while True:
        raw = _input("  > ").strip().lower()
        if raw in {"/quit", "/q", "/exit", "s"}:
            raise UserAbort
        if not raw:
            if allow_empty:
                return []
            fail("하나 이상 선택해 주세요.")
            continue
        if raw in {"all", "a", "전체"}:
            return [c.value if c.value is not None else c.key for c in choices]
        picked = [p.strip() for p in raw.replace(" ", ",").split(",") if p.strip()]
        if all(p in keys for p in picked):
            seen: list[Any] = []
            for p in picked:
                choice = keys[p]
                value = choice.value if choice.value is not None else choice.key
                if value not in seen:
                    seen.append(value)
            return seen
        fail(t("errors.invalid_choice", max=len(choices)))


def ask_yes_no(question: str, *, default: bool | None = None, hint: str = "",
               allow_unknown: bool = False) -> bool | None:
    choices = [Choice("1", t("common.yes"), True), Choice("2", t("common.no"), False)]
    if allow_unknown:
        choices.append(Choice("3", t("common.unknown"), None))
    default_key = "" if default is None else ("1" if default else "2")
    return ask_choice(question, choices, hint=hint, default=default_key)


def ask_int(question: str, *, default: int | None = None, minimum: int = 1,
            hint: str = "") -> int | None:
    console.print(f"\n[bold]{question}[/bold]")
    if hint:
        why(hint)
    if default is not None:
        note(f"엔터만 누르면: {default}")
    while True:
        raw = _input("  > ").strip()
        if raw in {"/quit", "/q", "/exit", "s"}:
            raise UserAbort
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            fail("숫자를 입력해 주세요.")
            continue
        if value < minimum:
            fail(f"{minimum} 이상의 숫자를 입력해 주세요.")
            continue
        return value


def confirm_summary(title: str, body: str) -> str:
    """The confirm/edit/add/later loop used after every questionnaire step."""
    console.print()
    panel(body, title=title)
    return ask_choice(
        t("review.confirm_question"),
        [
            Choice("y", t("common.confirm"), "confirm"),
            Choice("e", t("common.edit"), "edit"),
            Choice("a", t("common.add"), "add"),
        ],
        default="y",
    )


def _input(prompt: str) -> str:
    """``input`` that treats Ctrl+C / EOF as 'save and stop', not as a crash."""
    try:
        return console.input(prompt)
    except (KeyboardInterrupt, EOFError):
        console.print()
        raise UserAbort from None


# --- display --------------------------------------------------------------
def table(title: str = "", columns: Sequence[str] = ()) -> Table:
    tbl = Table(title=title or None, show_header=bool(columns), header_style="bold")
    for column in columns:
        tbl.add_column(column)
    return tbl


def score_bar(score: float, maximum: float = 5.0, width: int = 20) -> Text:
    filled = round(score / maximum * width) if maximum else 0
    colour = "green" if score >= maximum * 0.8 else "yellow" if score >= maximum * 0.6 else "red"
    bar = Text("█" * filled, style=colour)
    bar.append("░" * (width - filled), style="dim")
    return bar


def key_value(rows: Sequence[tuple[str, str]], indent: str = "  ") -> None:
    if not rows:
        return
    width = max(len(k) for k, _ in rows)
    for key, value in rows:
        console.print(f"{indent}{key.ljust(width)}  {value}")


# --- asking, as an injectable dependency ----------------------------------
class Prompter(Protocol):
    """The five ways this harness asks a person something.

    Only *input* is abstracted. Output stays as plain module functions because a
    test that wants to read it can capture the console, whereas a test that wants
    to answer a questionnaire has no way to do so without this seam — which is
    why the questionnaires had no tests at all until one was written by
    monkey-patching a dozen names.
    """

    def ask_text(
        self,
        question: str,
        *,
        default: str = "",
        allow_empty: bool = True,
        multiline: bool = False,
        hint: str = "",
    ) -> str: ...

    def ask_choice(
        self,
        question: str,
        choices: Sequence[Choice],
        *,
        hint: str = "",
        default: str = "",
        allow_later: bool = True,
    ) -> Any: ...

    def ask_multi(
        self,
        question: str,
        choices: Sequence[Choice],
        *,
        hint: str = "",
        allow_empty: bool = True,
    ) -> list[Any]: ...

    def ask_yes_no(
        self,
        question: str,
        *,
        default: bool | None = None,
        hint: str = "",
        allow_unknown: bool = False,
    ) -> bool | None: ...

    def ask_int(
        self, question: str, *, default: int | None = None, minimum: int = 1, hint: str = ""
    ) -> int | None: ...


class TerminalPrompter:
    """The real thing: numbered prompts on the terminal."""

    ask_text = staticmethod(ask_text)
    ask_choice = staticmethod(ask_choice)
    ask_multi = staticmethod(ask_multi)
    ask_yes_no = staticmethod(ask_yes_no)
    ask_int = staticmethod(ask_int)


#: The default every questionnaire uses when nothing else is passed.
TERMINAL: Prompter = TerminalPrompter()

"""Questionnaire for ``02_design_principles.md`` — the hardest and most valuable step.

Three paths in, because students arrive in different states:

1. **Library** — pick from cited, ready-made principles. The default for a student
   who has never written a design principle.
2. **Own text** — paste principles derived from literature. The harness structures
   them (with the model's help) and the student confirms rule by rule; the original
   text is kept verbatim so the structuring can always be audited.
3. **Both**, which is what most projects end up doing.

Nothing enters the compile step until the student has looked at the generated rules
and said yes. That confirmation step *is* the pedagogy of this tool.

Every sentence a teacher reads here comes from the catalogue, including the *values*
of the choices: what is picked for theories and for escalation is written into the
document and into the system prompt, so it has to follow the project's language and
not the language this file happened to be written in.
"""

from __future__ import annotations

from pathlib import Path

from edu_agent import ui
from edu_agent.i18n import t
from edu_agent.principles.library_loader import LibraryEntry, library_entries, to_principle
from edu_agent.principles.markdown_source import (
    MarkdownSourceError,
    extract_statements,
    read_source,
)
from edu_agent.principles.structurer import structure_principle
from edu_agent.providers.base import Provider
from edu_agent.schemas.principles import (
    AnswerPolicy,
    DesignPrinciple,
    DesignPrinciples,
    validate_condition,
)
from edu_agent.ui import Choice

#: Each structuring pass is a model call, and a teacher confirming twenty rules in
#: one sitting stops reading them — which defeats the confirmation step.
MAX_STRUCTURED = 6

#: The theories a teacher is actually drawing on. This is the opening section of
#: ``02_design_principles.md`` and was the one part of that document nothing ever
#: filled in — the harness asked for rules without asking what they came from.
_THEORY_KEYS = (
    "scaffolding",
    "srl",
    "socratic",
    "cognitive_load",
    "formative",
    "constructivism",
    "misconception",
    "collaborative",
)

#: Label key, and the expression the runtime will actually evaluate.
_ANSWER_WHEN = (
    ("when_attempts_3", "attempts >= 3"),
    ("when_attempts_2", "attempts >= 2"),
    ("when_attempts_or_stuck", "attempts >= 3 or stuck_turns >= 2"),
    ("when_reasoning", "reasoning_shown == true and attempts >= 2"),
)


# Built per call, not at import: ``set_language`` runs when the project is loaded,
# which is after this module is imported.
def _theory_choices() -> list[Choice]:
    return [
        Choice(str(i), t(f"principles.theories.{key}"), t(f"principles.theories.{key}"))
        for i, key in enumerate(_THEORY_KEYS, 1)
    ]


def _answer_conditions() -> list[Choice]:
    choices = [
        Choice(str(i), t(f"principles.answer.{key}"), expression)
        for i, (key, expression) in enumerate(_ANSWER_WHEN, 1)
    ]
    choices.append(Choice(str(len(choices) + 1), t("principles.answer.custom"), "custom"))
    return choices


def _escalation_choices() -> list[Choice]:
    return [
        Choice("1", t("principles.escalation.no_progress_label"),
               t("principles.escalation.no_progress")),
        Choice("2", t("principles.escalation.distress_label"),
               t("principles.escalation.distress")),
        Choice("3", t("principles.escalation.both_label", recommended=t("common.recommended")),
               t("principles.escalation.both")),
        Choice("4", t("principles.answer.custom"), "custom"),
    ]


def run_principles(
    doc: DesignPrinciples,
    *,
    provider: Provider | None = None,
    source: Path | None = None,
    prompter: ui.Prompter | None = None,
) -> DesignPrinciples:
    ui.header(t("principles.title"), t("principles.subtitle"), step=(2, 4))

    ask = prompter or ui.TERMINAL
    _ask_theories(ask, doc)
    _ask_answer_policy(ask, doc)
    _ask_library(ask, doc)
    _ask_own(ask, doc, provider, source)
    _confirm_principles(ask, doc)
    _ask_cross_cutting(ask, doc)
    return doc


# --- theories -------------------------------------------------------------
def _ask_theories(ask: ui.Prompter, doc: DesignPrinciples) -> None:
    """Ask what the principles are *grounded in* before asking what they are.

    A design principle with no stated basis cannot be argued with, and this is the
    section an instructor reads first when marking the document.
    """
    ui.say()
    ui.info(t("principles.theories.step"))
    ui.note(t("principles.theories.lead"))
    picked = ask.ask_multi(
        t("principles.theories.question"),
        _theory_choices(),
        hint=t("principles.theories.hint"),
        allow_empty=True,
    )
    doc.theories_and_strategies = list(picked)

    while len(doc.theories_and_strategies) < 8:
        extra = ask.ask_text(
            t("principles.theories.add", n=len(doc.theories_and_strategies) + 1)
        )
        if not extra:
            break
        doc.theories_and_strategies.append(extra)

    if not doc.theories_and_strategies:
        ui.note(t("principles.theories.empty"))


# --- answer policy --------------------------------------------------------
def _ask_answer_policy(ask: ui.Prompter, doc: DesignPrinciples) -> None:
    ui.say()
    ui.info(t("principles.answer.step"))
    policy = ask.ask_choice(
        t("principles.answer.question"),
        [
            Choice("1", t("principles.answer.never"), AnswerPolicy.NEVER),
            Choice(
                "2",
                t("principles.answer.conditional", recommended=t("common.recommended")),
                AnswerPolicy.CONDITIONAL,
            ),
            Choice("3", t("principles.answer.allowed"), AnswerPolicy.ALLOWED),
        ],
        hint=t("principles.answer.hint"),
        default="2",
    )
    doc.answer_policy = policy

    if policy is AnswerPolicy.NEVER:
        ui.say()
        ui.warn(t("principles.answer.never_warning"))
        ui.note(t("principles.answer.never_note"))
        reconsider = ask.ask_yes_no(t("principles.answer.reconsider"), default=True)
        if reconsider:
            doc.answer_policy = AnswerPolicy.CONDITIONAL
        else:
            return

    if doc.answer_policy is not AnswerPolicy.CONDITIONAL:
        return

    condition = ask.ask_choice(
        t("principles.answer.when_question"),
        _answer_conditions(),
        hint=t("principles.answer.when_hint"),
        default="3",
    )
    if condition == "custom":
        ui.note(t("principles.answer.custom_vars"))
        ui.note(t("principles.answer.custom_example"))
        while True:
            raw = ask.ask_text(t("principles.answer.custom_prompt"))
            try:
                condition = validate_condition(raw)
                break
            except ValueError as exc:
                ui.fail(str(exc))
    doc.answer_condition = condition


# --- library --------------------------------------------------------------
def _ask_library(ask: ui.Prompter, doc: DesignPrinciples) -> None:
    ui.say()
    ui.info(t("principles.library.step"))
    ui.note(t("principles.library.lead"))

    entries = library_entries()
    already = {p.library_id for p in doc.principles if p.library_id}
    available = [e for e in entries if e.library_id not in already]
    if not available:
        ui.note(t("principles.library.exhausted"))
        return

    choices = [
        Choice(str(i + 1), e.title, e.library_id, e.short[:60])
        for i, e in enumerate(available)
    ]
    picked = ask.ask_multi(
        t("principles.library.question"),
        choices,
        hint=t("principles.library.hint"),
    )
    if not picked:
        return

    used = doc.used_ids()
    by_id = {e.library_id: e for e in available}
    for library_id in picked:
        entry = by_id[library_id]
        _show_entry(entry)
        principle, criteria = to_principle(entry, used)
        doc.principles.append(principle)
        doc.criteria.extend(criteria)
    ui.ok(t("principles.library.imported", n=len(picked)))


def _show_entry(entry: LibraryEntry) -> None:
    ui.say()
    body = [entry.description.strip()]
    if entry.why_it_matters:
        why = t("principles.library.why_it_matters")
        body += ["", f"[dim]{why}[/dim] {entry.why_it_matters.strip()}"]
    if entry.sources:
        body += ["", f"[dim]{t('principles.library.sources')}[/dim]"]
        body += [f"  · {s}" for s in entry.sources]
    ui.panel("\n".join(body), title=entry.title, style="blue")


# --- own principles -------------------------------------------------------
def _ask_own(
    ask: ui.Prompter,
    doc: DesignPrinciples,
    provider: Provider | None,
    source: Path | None = None,
) -> None:
    ui.say()
    ui.info(t("principles.own.step"))
    ui.note(t("principles.own.lead"))

    text = _load_from_file(source) if source is not None else _choose_source(ask, doc)
    if not text or not text.strip():
        return
    doc.raw_user_text = text

    statements = extract_statements(text)
    if not statements:
        ui.warn(t("principles.own.nothing_found"))
        ui.note(t("principles.own.nothing_found_hint"))
        return

    ui.say()
    ui.ok(t("principles.own.read_count", n=len(statements)))
    for i, statement in enumerate(statements[:8], 1):
        ui.say(f"  {i}. {statement[:80]}{'…' if len(statement) > 80 else ''}")
    if len(statements) > 8:
        ui.note(t("principles.own.and_more", n=len(statements) - 8))
    if not ask.ask_yes_no(t("principles.own.confirm_structuring"), default=True):
        ui.note(t("principles.own.declined"))
        return

    if provider is None:
        ui.warn(t("principles.own.no_llm"))
        ui.note(t("principles.own.no_llm_hint"))
        return

    used = doc.used_ids()
    for statement in statements[:MAX_STRUCTURED]:
        ui.say()
        ui.info(t("principles.own.structuring", statement=statement[:60]))
        result = structure_principle(statement, provider, used, answer_condition=doc.answer_condition)
        if result is None:
            ui.warn(t("principles.own.structuring_failed"))
            continue
        principle, criteria = result
        doc.principles.append(principle)
        doc.criteria.extend(criteria)

    if len(statements) > MAX_STRUCTURED:
        ui.say()
        ui.note(t("principles.own.capped", total=len(statements), shown=MAX_STRUCTURED))


def _choose_source(ask: ui.Prompter, doc: DesignPrinciples) -> str:
    """File or paste. A prepared document is the common case, so it comes first."""
    how = ask.ask_choice(
        t("principles.own.question"),
        [
            Choice("1", t("principles.own.from_file"), "file"),
            Choice("2", t("principles.own.paste"), "paste"),
            Choice("3", t("principles.own.none"), "none"),
        ],
        hint=t("principles.own.hint"),
        default="3",
    )
    if how == "none":
        return ""
    if how == "paste":
        return ask.ask_text(
            t("principles.own.paste_prompt"),
            multiline=True,
            default=doc.raw_user_text,
        )

    while True:
        raw = ask.ask_text(t("principles.own.path_prompt"))
        if not raw.strip():
            return ""
        text = _load_from_file(Path(raw.strip().strip('"\'')))
        if text:
            return text


def _load_from_file(path: Path) -> str:
    try:
        text = read_source(path)
    except MarkdownSourceError as exc:
        ui.fail(str(exc))
        return ""
    ui.ok(t("principles.own.file_read", name=path.name, lines=len(text.splitlines())))
    return text


# --- confirmation ---------------------------------------------------------
def _confirm_principles(ask: ui.Prompter, doc: DesignPrinciples) -> None:
    pending = [p for p in doc.principles if not p.confirmed]
    if not pending:
        return

    ui.say()
    ui.info(t("principles.confirm.step"))
    ui.note(t("principles.confirm.lead"))

    for principle in pending:
        _confirm_one(ask, principle, doc)


def _confirm_one(ask: ui.Prompter, p: DesignPrinciple, doc: DesignPrinciples) -> None:
    ui.say()
    ui.panel(render_principle(p), title=f"{p.id} · {p.title or p.name}", style="cyan")

    action = ask.ask_choice(
        t("principles.confirm.question"),
        [
            Choice("y", t("principles.confirm.accept"), "confirm"),
            Choice("n", t("principles.confirm.drop"), "drop"),
            Choice("e", t("principles.confirm.edit"), "edit"),
        ],
        default="y",
        allow_later=False,
    )
    if action == "confirm":
        p.confirmed = True
        ui.ok(t("principles.confirm.accepted", id=p.id))
    elif action == "drop":
        doc.principles.remove(p)
        for rule in p.rules:
            doc.criteria = [c for c in doc.criteria if c.id not in rule.evaluation]
        ui.note(t("principles.confirm.dropped", id=p.id))
    else:
        p.description = ask.ask_text(
            t("principles.confirm.edit_prompt"), default=p.description, multiline=True
        )
        p.confirmed = True
        ui.ok(t("principles.confirm.accepted", id=p.id))


def render_principle(p: DesignPrinciple) -> str:
    """Human-readable rendering of a structured principle."""
    lines = [p.description.strip() or t("principles.render.no_description"), ""]

    for rule in p.rules:
        triggers = ", ".join(x.value for x in rule.triggers) or t("principles.render.always")
        lines.append(t("principles.render.when", triggers=triggers))
        if rule.ladder:
            lines.append(t("principles.render.then"))
            for step in rule.ladder:
                cond = f"  ({step.when})" if step.when else ""
                lines.append(
                    t("principles.render.step_line",
                      level=step.level, label=step.label, condition=cond)
                )
        if rule.actions:
            actions = ", ".join(a.value for a in rule.actions)
            lines.append(t("principles.render.actions", actions=actions))
        hard = [c for c in rule.constraints if c.gateable]
        soft = [c for c in rule.constraints if not c.gateable]
        if hard:
            lines.append(t("principles.render.hard"))
            lines.extend(f"  · {c.text or c.kind.value}" for c in hard)
        if soft:
            lines.append(t("principles.render.soft"))
            lines.extend(f"  · {c.text or c.params.get('text', '')}" for c in soft)
        lines.append("")

    if not p.rules:
        lines.append(t("principles.render.no_rules"))
    return "\n".join(lines).strip()


# --- cross-cutting policies ----------------------------------------------
def _ask_cross_cutting(ask: ui.Prompter, doc: DesignPrinciples) -> None:
    ui.say()
    ui.note(t("principles.cross_cutting.lead"))
    doc.learner_agency.stance = ask.ask_text(
        t("principles.cross_cutting.agency"), default=doc.learner_agency.stance
    )
    doc.scaffolding.stance = ask.ask_text(
        t("principles.cross_cutting.scaffolding"), default=doc.scaffolding.stance
    )
    doc.feedback.stance = ask.ask_text(
        t("principles.cross_cutting.feedback"), default=doc.feedback.stance
    )
    doc.reflection.stance = ask.ask_text(
        t("principles.cross_cutting.reflection"), default=doc.reflection.stance
    )
    _ask_escalation(ask, doc)


def _ask_escalation(ask: ui.Prompter, doc: DesignPrinciples) -> None:
    """When should the agent stop and hand the learner to a person?

    Deciding this is part of designing the agent, not a detail to be defaulted:
    an agent that never gives up is as much a design failure as one that gives
    up immediately. Until now the compiler wrote one fixed sentence for everyone.
    """
    ui.say()
    ui.note(t("principles.escalation.lead"))
    choice = ask.ask_choice(
        t("principles.escalation.question"),
        _escalation_choices(),
        hint=t("principles.escalation.hint"),
        default="3",
    )
    if choice == "custom":
        choice = ask.ask_text(t("principles.escalation.custom_prompt"))
    doc.escalation = choice or ""


def summarize(doc: DesignPrinciples) -> str:
    confirmed = doc.confirmed_principles()
    lines = [
        t("principles.summary.heading", confirmed=len(confirmed), total=len(doc.principles)),
        "",
    ]
    for p in doc.principles:
        lines.append(
            t(
                "principles.summary.line",
                mark="✔" if p.confirmed else "⚠",
                id=p.id,
                title=p.title or p.name,
                rules=len(p.rules),
                gates=sum(1 for r in p.rules for c in r.constraints if c.gateable),
            )
        )
    policy = doc.answer_policy.value
    if doc.answer_policy is AnswerPolicy.CONDITIONAL:
        policy += f" ({doc.answer_condition})"
    lines += [
        "",
        t("principles.summary.answer_policy", policy=policy),
        t("principles.summary.criteria", n=len(doc.criteria)),
    ]
    return "\n".join(lines)

"""The simulated student: explicit epistemic state, LLM only renders it.

The design answers three findings that make naive prompt-personas unusable as a
test instrument (see ``docs/research/student-simulation.md``):

1. *Competence paradox* — strong models outperform real students at every grade, so
   the student's knowledge must be **stated**, not inferred by the model.
2. *Unfaithful belief update* — simulated students drop a misconception in response
   to any correction, even an irrelevant one. Here a misconception flips only when
   :meth:`StudentState.feedback_targets_misconception` says the tutor actually
   addressed it, and how often that rule is violated is reported as a health metric.
3. *Over-compliance* — behaviour (answer-fishing, off-task, frustration) is decided
   by parameters and the turn number, not left to the model's goodwill.

The LLM's job is narrow: turn ``StudentIntent`` into one plausible sentence.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum

from edu_agent.schemas.persona import Persona, PressureStrategy
from edu_agent.utils.text import normalize_for_match


class StudentIntent(StrEnum):
    """What the student is doing this turn — chosen by rules, rendered by the LLM."""

    OPENING = "opening"
    SHOW_REASONING = "show_reasoning"
    ASK_FOR_HELP = "ask_for_help"
    DEMAND_ANSWER = "demand_answer"
    PRESSURE = "pressure"
    ASSERT_MISCONCEPTION = "assert_misconception"
    ATTEMPT_FIX = "attempt_fix"
    EXPRESS_FRUSTRATION = "express_frustration"
    GO_OFF_TASK = "go_off_task"
    SHARE_PII = "share_pii"
    ACKNOWLEDGE = "acknowledge"
    REPORT_SUCCESS = "report_success"


@dataclass(slots=True)
class StudentTurn:
    """One simulated learner utterance plus the ground truth behind it."""

    message: str
    intent: StudentIntent
    showed_reasoning: bool = False
    attempted: bool = False
    solved: bool = False
    misconception_asserted: str = ""
    pressure: PressureStrategy | None = None
    violations: list[str] = field(default_factory=list)


@dataclass(slots=True)
class StudentState:
    """Epistemic + behavioural state, updated by rules only."""

    persona: Persona
    seed: int = 0
    turn: int = 0
    active_misconceptions: list[str] = field(default_factory=list)
    targeted_corrections: dict[str, int] = field(default_factory=dict)
    attempts: int = 0
    unresolved_turns: int = 0
    solved: bool = False
    gave_up: bool = False
    hints_received: int = 0
    #: Health metric: the tutor said something generic and the persona *would* have
    #: flipped under naive prompting. Counted, never acted on.
    untargeted_flip_opportunities: int = 0
    unfaithful_flips: int = 0

    def __post_init__(self) -> None:
        if not self.active_misconceptions:
            self.active_misconceptions = list(self.persona.knowledge.misconceptions)

    # --- deterministic pseudo-randomness ---------------------------------
    def roll(self, salt: str) -> float:
        """Reproducible [0,1) draw — same seed and turn gives the same value."""
        key = f"{self.persona.id}:{self.seed}:{self.turn}:{salt}"
        return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF

    # --- belief update ---------------------------------------------------
    def feedback_targets_misconception(self, tutor_message: str, misconception: str) -> bool:
        """Does the tutor's message actually address *this* misconception?

        Deliberately strict: it requires overlap with the content words of the
        misconception, not merely a correcting tone. This is the rule that stops the
        simulated student from being a pushover.
        """
        text = normalize_for_match(tutor_message)
        words = [w for w in normalize_for_match(misconception).split() if len(w) >= 2]
        if not words:
            return False
        hits = sum(1 for w in words if w in text)
        return hits >= max(2, len(words) // 3)

    def observe_tutor(self, tutor_message: str, *, was_hint: bool = False) -> None:
        """Update state from the tutor's turn."""
        if was_hint:
            self.hints_received += 1

        for misconception in list(self.active_misconceptions):
            if self.feedback_targets_misconception(tutor_message, misconception):
                self.targeted_corrections[misconception] = (
                    self.targeted_corrections.get(misconception, 0) + 1
                )
                needed = self.persona.belief_update.min_targeted_corrections
                if self.targeted_corrections[misconception] >= needed:
                    self.active_misconceptions.remove(misconception)
            else:
                # Record what a naive simulator would have done wrong here.
                if _sounds_corrective(tutor_message):
                    self.untargeted_flip_opportunities += 1
                    if not self.persona.belief_update.flip_only_if_feedback_targets_misconception:
                        self.active_misconceptions.remove(misconception)
                        self.unfaithful_flips += 1

    # --- progress --------------------------------------------------------
    def can_solve(self) -> bool:
        """Would this student solve it now, given mastery and support received?

        Mastery sets the ceiling; hints raise the chance; an active misconception
        blocks it. Crucially it is capped below 1.0 — a low-mastery student does not
        become competent just because the tutor was patient.
        """
        if self.active_misconceptions:
            return False
        base = self.persona.knowledge.overall_mastery()
        support = min(0.35, 0.12 * self.hints_received)
        effort = 0.1 * min(self.attempts, 3)
        chance = min(0.9, base + support + effort)
        return self.roll("solve") < chance

    def should_give_up(self) -> bool:
        if self.persona.behavior.persistence >= 0.8:
            return False
        threshold = self.persona.behavior.frustration_threshold
        return self.unresolved_turns > threshold + int(self.persona.behavior.persistence * 4)


def _sounds_corrective(text: str) -> bool:
    markers = ("아니", "다시", "틀렸", "확인", "정확", "생각해", "살펴", "not quite", "check")
    return any(m in text for m in markers)


def choose_intent(state: StudentState, tutor_message: str, first: bool = False) -> StudentIntent:
    """Pick this turn's intent from persona parameters — not from the model."""
    b = state.persona.behavior

    if first:
        return StudentIntent.OPENING
    if state.solved:
        return StudentIntent.REPORT_SUCCESS
    if state.gave_up:
        return StudentIntent.EXPRESS_FRUSTRATION

    if b.shares_pii > 0 and state.roll("pii") < b.shares_pii and state.turn in (1, 2):
        return StudentIntent.SHARE_PII
    if b.off_task > 0 and state.roll("off") < b.off_task:
        return StudentIntent.GO_OFF_TASK
    if state.active_misconceptions and state.roll("misc") < 0.6:
        return StudentIntent.ASSERT_MISCONCEPTION
    if state.unresolved_turns >= b.frustration_threshold and state.roll("frust") < 0.7:
        return StudentIntent.EXPRESS_FRUSTRATION
    if b.answer_fishing > 0 and state.roll("fish") < b.answer_fishing:
        # Repeated demands escalate into explicit pressure — this is what surfaces
        # scaffolding collapse, which single-turn evaluation cannot see.
        return StudentIntent.PRESSURE if state.turn >= 2 else StudentIntent.DEMAND_ANSWER
    if _asks_for_reasoning(tutor_message) and state.roll("reason") < b.shares_reasoning + 0.3:
        return StudentIntent.SHOW_REASONING
    if _gave_hint(tutor_message):
        return StudentIntent.ATTEMPT_FIX
    if state.roll("help") < b.help_seeking:
        return StudentIntent.ASK_FOR_HELP
    return StudentIntent.SHOW_REASONING if state.roll("share") < b.shares_reasoning else StudentIntent.ASK_FOR_HELP


def choose_pressure(state: StudentState) -> PressureStrategy | None:
    strategies = state.persona.pressure_strategies
    if not strategies:
        return None
    return strategies[int(state.roll("strategy") * len(strategies)) % len(strategies)]


def _asks_for_reasoning(text: str) -> bool:
    markers = ("어떻게 생각", "무엇이 문제", "어디가", "왜 그렇", "설명해", "말해 볼", "what do you think")
    return any(m in text for m in markers)


def _gave_hint(text: str) -> bool:
    markers = ("살펴", "확인해", "다시 봐", "부분을", "생각해 보", "힌트", "look at", "check the")
    return any(m in text for m in markers)


class SimulatedStudent:
    """Facade combining :class:`StudentState` with an LLM renderer."""

    def __init__(self, persona: Persona, renderer, seed: int = 0) -> None:
        self.state = StudentState(persona=persona, seed=seed)
        self.renderer = renderer

    def reply(self, tutor_message: str, *, first: bool = False) -> StudentTurn:
        state = self.state
        state.turn += 1
        if not first:
            state.observe_tutor(tutor_message, was_hint=_gave_hint(tutor_message))

        intent = choose_intent(state, tutor_message, first=first)
        pressure = choose_pressure(state) if intent is StudentIntent.PRESSURE else None

        if intent is StudentIntent.ATTEMPT_FIX:
            state.attempts += 1
            if state.can_solve():
                state.solved = True
                intent = StudentIntent.REPORT_SUCCESS
            else:
                state.unresolved_turns += 1
        elif intent in (StudentIntent.ASK_FOR_HELP, StudentIntent.DEMAND_ANSWER, StudentIntent.PRESSURE):
            state.unresolved_turns += 1
        elif intent is StudentIntent.SHOW_REASONING:
            state.attempts += 1

        if state.should_give_up() and intent is not StudentIntent.REPORT_SUCCESS:
            state.gave_up = True

        misconception = state.active_misconceptions[0] if state.active_misconceptions else ""
        turn = self.renderer(state, intent, pressure, misconception)
        turn.intent = intent
        turn.pressure = pressure
        turn.showed_reasoning = intent is StudentIntent.SHOW_REASONING
        turn.attempted = intent in (StudentIntent.ATTEMPT_FIX, StudentIntent.SHOW_REASONING)
        turn.solved = state.solved
        if intent is StudentIntent.ASSERT_MISCONCEPTION:
            turn.misconception_asserted = misconception
        return turn

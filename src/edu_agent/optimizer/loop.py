"""The improvement loop itself.

::

    evaluate → diagnose → propose → [approve] → snapshot → apply
             → re-evaluate on held-out scenarios → gate → keep or roll back

Two design points worth stating plainly:

**The held-out split.** Scenarios are split into a *dev* set (used to diagnose) and
a *holdout* set (used to decide whether to keep the change). Without this, the loop
would tune the agent against the exact conversations it was shown and report
progress that does not transfer — the oldest failure mode in optimisation, and the
reason GEPA keeps a separate valset.

**The autonomy dial.** ``auto_level`` decides which layers may be applied without a
human. ``principle`` edits are never automatic at any setting: those are the
student's pedagogical decisions, and the harness exists to make them visible, not
to quietly optimise them away.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from edu_agent.optimizer.diagnose import Diagnosis, EditLayer, diagnose, failures_as_feedback
from edu_agent.optimizer.gate import GateVerdict, evaluate_change
from edu_agent.optimizer.patch import Patch, apply_patches, list_snapshots, snapshot_spec
from edu_agent.optimizer.proposals import Proposal, propose
from edu_agent.providers.base import Provider
from edu_agent.schemas.agent import AgentSpec, TestScenario
from edu_agent.schemas.evaluation import EvaluationReport

#: Which layers each autonomy level may apply without asking.
AUTO_LEVELS: dict[str, set[EditLayer]] = {
    "off": set(),
    "prompt": {EditLayer.PROMPT},
    "params": {EditLayer.PROMPT, EditLayer.PARAMS},
    # `structure` is reachable only with allow_structure_edits=True.
    "structure": {EditLayer.PROMPT, EditLayer.PARAMS, EditLayer.SPEC},
}

#: Evaluating a candidate spec. Injected so the loop can be tested offline.
EvaluateFn = Callable[[AgentSpec, Sequence[TestScenario]], EvaluationReport]

#: Asking the human which proposals to apply. Returns the accepted subset.
ApproveFn = Callable[[list[Proposal]], list[Proposal]]


@dataclass(slots=True)
class ImproveRound:
    """One iteration, recorded for the report and for ``--rollback``."""

    index: int
    diagnoses: list[Diagnosis] = field(default_factory=list)
    proposals: list[Proposal] = field(default_factory=list)
    applied: list[Patch] = field(default_factory=list)
    verdict: GateVerdict | None = None
    kept: bool = False
    snapshot_version: int | None = None
    errors: list[str] = field(default_factory=list)
    deferred_to_human: list[Diagnosis] = field(default_factory=list)


@dataclass(slots=True)
class ImproveOutcome:
    spec: AgentSpec
    rounds: list[ImproveRound] = field(default_factory=list)
    baseline: EvaluationReport | None = None
    final: EvaluationReport | None = None
    changed: bool = False
    stopped_because: str = ""

    @property
    def applied_patches(self) -> list[Patch]:
        return [p for r in self.rounds if r.kept for p in r.applied]

    def delta(self) -> float:
        if self.baseline is None or self.final is None:
            return 0.0
        return self.final.overall - self.baseline.overall


def split_scenarios(
    scenarios: Sequence[TestScenario], holdout_ids: Sequence[str] = ()
) -> tuple[list[TestScenario], list[TestScenario]]:
    """Split into (dev, holdout).

    An explicit list wins. Otherwise every third scenario is held out, which keeps
    a mix of personas on both sides — holding out "the last N" would systematically
    reserve whichever personas happen to be generated last.
    """
    if holdout_ids:
        ids = set(holdout_ids)
        dev = [s for s in scenarios if s.id not in ids]
        holdout = [s for s in scenarios if s.id in ids]
        if dev and holdout:
            return dev, holdout

    if len(scenarios) < 4:
        # Too few to split. Report honestly rather than pretend to hold out.
        return list(scenarios), list(scenarios)

    dev = [s for i, s in enumerate(scenarios) if i % 3 != 2]
    holdout = [s for i, s in enumerate(scenarios) if i % 3 == 2]
    return dev, holdout


def run_improve(
    spec: AgentSpec,
    baseline: EvaluationReport,
    evaluate_fn: EvaluateFn,
    *,
    snapshots_dir: Path,
    approve_fn: ApproveFn | None = None,
    provider: Provider | None = None,
    max_rounds: int = 3,
    min_improvement: float = 0.05,
    auto_level: str = "off",
    allow_structure_edits: bool = False,
    holdout_ids: Sequence[str] = (),
    max_proposals: int = 5,
) -> ImproveOutcome:
    """Run the loop. Returns the (possibly unchanged) spec and a full record."""
    outcome = ImproveOutcome(spec=spec, baseline=baseline)
    dev, holdout = split_scenarios(spec.scenarios, holdout_ids)

    snapshot_spec(snapshots_dir, spec, note="improve 시작 전", overall=baseline.overall)

    current_report = baseline
    allowed_layers = _allowed_layers(auto_level, allow_structure_edits)

    for index in range(1, max_rounds + 1):
        rnd = ImproveRound(index=index)
        rnd.diagnoses = diagnose(current_report, spec)
        if not rnd.diagnoses:
            outcome.stopped_because = "고칠 것을 찾지 못했습니다."
            outcome.rounds.append(rnd)
            break

        rnd.deferred_to_human = [d for d in rnd.diagnoses if d.needs_human]
        actionable = [d for d in rnd.diagnoses if not d.needs_human]
        if not actionable:
            outcome.stopped_because = "남은 문제는 설계원리에 관한 것이라 직접 판단이 필요합니다."
            outcome.rounds.append(rnd)
            break

        rnd.proposals = propose(
            actionable,
            spec,
            provider=provider,
            feedback=failures_as_feedback(current_report),
            limit=max_proposals,
        )
        applicable = [p for p in rnd.proposals if p.patches]
        if not applicable:
            outcome.stopped_because = "적용할 수 있는 구체적인 변경안을 만들지 못했습니다."
            outcome.rounds.append(rnd)
            break

        accepted = _select(applicable, allowed_layers, approve_fn)
        if not accepted:
            outcome.stopped_because = "적용할 변경이 선택되지 않았습니다."
            outcome.rounds.append(rnd)
            break

        candidate = spec.model_copy(deep=True)
        patches = [p for proposal in accepted for p in proposal.patches]
        candidate, applied, errors = apply_patches(candidate, patches)
        rnd.applied = applied
        rnd.errors = errors
        if not applied:
            outcome.stopped_because = "변경을 적용하지 못했습니다."
            outcome.rounds.append(rnd)
            break

        # Judge on the held-out scenarios: the ones the diagnosis never saw.
        # Baseline first, then the candidate — the same order a reader expects, and
        # the order that makes an injected evaluate_fn behave predictably.
        before = current_report if holdout is dev else evaluate_fn(spec, holdout)
        after = evaluate_fn(candidate, holdout)
        verdict = evaluate_change(before, after, min_improvement=min_improvement)
        rnd.verdict = verdict

        if verdict.accept:
            spec = candidate
            outcome.spec = spec
            outcome.changed = True
            rnd.kept = True
            snap = snapshot_spec(
                snapshots_dir,
                spec,
                note=f"round {index}: " + "; ".join(p.describe() for p in applied),
                overall=after.overall,
                patches=applied,
            )
            rnd.snapshot_version = snap.version
            current_report = evaluate_fn(spec, dev)
            outcome.final = after
        else:
            outcome.rounds.append(rnd)
            outcome.stopped_because = verdict.reason
            break

        outcome.rounds.append(rnd)
    else:
        outcome.stopped_because = f"최대 {max_rounds}회 반복을 마쳤습니다."

    if outcome.final is None:
        outcome.final = baseline
    return outcome


def _allowed_layers(auto_level: str, allow_structure: bool) -> set[EditLayer]:
    layers = set(AUTO_LEVELS.get(auto_level, set()))
    if allow_structure and layers:
        layers.add(EditLayer.SPEC)
    layers.discard(EditLayer.PRINCIPLE)  # never automatic, at any level
    return layers


def _select(
    proposals: list[Proposal],
    allowed_layers: set[EditLayer],
    approve_fn: ApproveFn | None,
) -> list[Proposal]:
    """Apply what the autonomy dial permits; ask the human about the rest."""
    auto = [p for p in proposals if p.layer in allowed_layers]
    manual = [p for p in proposals if p.layer not in allowed_layers]

    approved: list[Proposal] = list(auto)
    if manual and approve_fn is not None:
        approved.extend(approve_fn(manual))
    elif manual and approve_fn is None and not auto:
        # Non-interactive with nothing auto-appliable: change nothing.
        return []
    return approved


def snapshot_history(snapshots_dir: Path) -> list[dict]:
    return list_snapshots(snapshots_dir)

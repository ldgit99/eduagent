"""The eval-guided improvement loop, with its regression gate (plan v2 §16).

Separated from the CLI because the interesting part is the decision procedure —
propose, apply, re-test on held-out scenarios, roll back — and that is worth
reading without argument parsing wrapped around it.
"""

from __future__ import annotations

from edu_agent import ui
from edu_agent.commands import context
from edu_agent.i18n import t
from edu_agent.project.layout import SPEC_DOC


def run_improve(project, spec, baseline, *, auto, rounds, dry_run, no_llm, mock, allow_structure) -> None:
    from edu_agent.evaluator.judge import Judge
    from edu_agent.evaluator.runner import EvaluationInput, evaluate
    from edu_agent.optimizer.diagnose import diagnose, failures_as_feedback
    from edu_agent.optimizer.loop import run_improve
    from edu_agent.optimizer.proposals import propose
    from edu_agent.simulator.loop import run_simulation
    from edu_agent.simulator.personas import load_personas
    from edu_agent.storage.jsonl import new_run_id

    cfg = project.config.improve
    auto_level = auto or cfg.auto_level
    max_rounds = rounds or cfg.max_rounds

    provider = context.provider(project, no_llm=no_llm, mock=mock)
    judge_provider = context.provider(project, role="judge", no_llm=no_llm, mock=mock)
    personas = load_personas(project.root / "personas.yaml")
    task = context.first_task(project)

    ui.header("개선", f"자동 적용 범위: {auto_level}")

    diagnoses = diagnose(baseline, spec)
    if not diagnoses:
        ui.ok(t("improve.none"))
        return

    proposals = propose(
        diagnoses, spec, provider=provider, feedback=failures_as_feedback(baseline), limit=6
    )
    show_proposals(proposals)

    if dry_run:
        ui.say()
        ui.info("--dry-run 이므로 아무것도 바꾸지 않았습니다.")
        return

    actionable = [p for p in proposals if p.patches]
    if not actionable:
        ui.say()
        ui.warn("자동으로 적용할 수 있는 변경안이 없습니다. 위 진단을 보고 직접 문서를 고쳐 주세요.")
        return

    def evaluate_fn(candidate, scenarios):
        traces, results = [], []
        run_id = new_run_id("improve")
        for sc in scenarios:
            persona = personas.get(sc.persona_id)
            if persona is None:
                continue
            for seed in range(max(1, sc.seeds)):
                result = run_simulation(
                    candidate, sc, persona, provider or context.provider(project, mock=True),
                    task=task, seed=seed, run_id=run_id,
                )
                traces.append(result.trace)
                results.append(result)
        judge = Judge(judge_provider, overlay=evaluate.judge_overlay(project)) if judge_provider else None
        return evaluate(
            EvaluationInput(spec=candidate, traces=traces, results=results, judge=judge,
                            run_id=run_id, project=project.config.name)
        )

    def approve_fn(pending):
        return ask_which(pending)

    ui.say()
    ui.info(t("improve.verifying"))
    outcome = run_improve(
        spec, baseline, evaluate_fn,
        snapshots_dir=project.snapshots_dir,
        approve_fn=approve_fn,
        provider=provider,
        max_rounds=max_rounds,
        min_improvement=cfg.min_improvement,
        auto_level=auto_level,
        allow_structure_edits=allow_structure or cfg.allow_structure_edits,
        holdout_ids=project.config.evaluation.holdout_scenarios,
    )

    ui.say()
    for rnd in outcome.rounds:
        if rnd.verdict is None:
            continue
        prefix = "[green]✔[/green]" if rnd.kept else "[yellow]↩[/yellow]"
        ui.say(f"  {prefix} {rnd.index}회차: {rnd.verdict.summary_ko()}")
        for patch in rnd.applied:
            ui.note(patch.describe())
        for reg in rnd.verdict.regressions[:3]:
            ui.note(f"[red]회귀[/red] {reg}")

    if outcome.changed:
        context.write_doc(project, SPEC_DOC, outcome.spec)
        ui.say()
        ui.ok(t("improve.applied", n=len(outcome.applied_patches)))
        ui.note("되돌리려면: edu-agent improve --history")
    else:
        ui.say()
        ui.info(outcome.stopped_because or t("improve.none"))

    deferred = [d for r in outcome.rounds for d in r.deferred_to_human]
    if deferred:
        ui.say()
        ui.warn("직접 판단이 필요한 문제:")
        for d in deferred[:4]:
            ui.say(f"  · {d.title}")
            ui.note(d.detail)
            if d.suggestion:
                ui.note(f"→ {d.suggestion}")


def show_proposals(proposals) -> None:
    ui.say()
    ui.info(t("improve.found", n=len(proposals)))
    for i, proposal in enumerate(proposals, 1):
        ui.say()
        marker = "[yellow](직접 판단 필요)[/yellow]" if proposal.needs_human else ""
        ui.say(f"  [bold][{i}] {proposal.summary or proposal.diagnosis.title}[/bold] {marker}")
        ui.note(proposal.rationale or proposal.diagnosis.detail)
        for patch in proposal.patches:
            ui.note(f"바꿀 것: {patch.describe()}")
        for ev in proposal.evidence[:1]:
            ui.note(f"근거 [턴 {ev.turn_index}] 학생: {ev.learner_message}")
            ui.note(f"                튜터: {ev.tutor_message}")


def ask_which(proposals):
    choices = [
        ui.Choice(str(i + 1), p.summary or p.diagnosis.title, p)
        for i, p in enumerate(proposals)
    ]
    if not choices:
        return []
    picked = ui.ask_multi(t("improve.which"), choices, allow_empty=True)
    return list(picked)


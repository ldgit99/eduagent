"""Scoring stored conversations, and saying how much the scores can be trusted.

``regrade`` re-scores a run without calling the tutor again, which is what keeps a
class's model budget spent on the agent rather than on grading it twice. The rest
attaches what is known about the judge, so a report never shows a number without
its caveat.
"""

from __future__ import annotations

from edu_agent import ui
from edu_agent.commands import context
from edu_agent.project import Project


def regrade(project: Project, spec, run_id: str, *, no_llm: bool, mock: bool) -> None:
    """Re-score a stored run without calling the tutor again (τ²-bench pattern)."""
    from edu_agent.evaluator.judge import Judge
    from edu_agent.evaluator.runner import EvaluationInput, evaluate
    from edu_agent.report.console import render_report
    from edu_agent.storage.jsonl import RunPaths, load_run

    if not run_id:
        ui.die("다시 채점할 실행 기록이 없습니다.", command="edu-agent test")
    paths = RunPaths(project.runs_dir, run_id)
    traces = load_run(paths)
    if not traces:
        ui.die(f"'{run_id}' 기록을 찾을 수 없습니다.")

    ui.header("저장된 대화를 다시 채점합니다", f"{run_id} · 대화 {len(traces)}개")
    ui.note("튜터 모델을 다시 호출하지 않으므로 비용이 들지 않습니다.")

    judge_provider = context.provider(project, role="judge", no_llm=no_llm, mock=mock)
    judge = Judge(judge_provider, overlay=judge_overlay(project)) if judge_provider else None
    report = evaluate(
        EvaluationInput(spec=spec, traces=traces, judge=judge, run_id=run_id,
                        project=project.config.name)
    )
    attach_calibration(project, report)
    ui.say()
    render_report(report)


def judge_overlay(project: Project):
    """The rubric layer this project's own human ratings produced, if any."""
    from edu_agent.evaluator.judge_tuning import OVERLAY_NAME, load_overlay

    return load_overlay(project.evals_dir / OVERLAY_NAME)


def attach_calibration(project: Project, report) -> None:
    from edu_agent.evaluator.calibration import compute_calibration, load_ratings
    from edu_agent.evaluator.items import RatedItem

    ratings = load_ratings(project.evals_dir / "human_ratings.json")
    if not ratings:
        return
    judge_labels = {
        RatedItem.of(e, c.metric): c.label
        for c in report.checks
        for e in c.evidence
    }
    stored = stored_judge_labels(project)
    report.calibration = compute_calibration(
        ratings, stored or judge_labels, threshold=project.config.evaluation.calibration_threshold
    )
    overlay = judge_overlay(project)
    report.calibration.overlay_version = overlay.version if overlay else 0


def stored_judge_labels(project: Project) -> dict:
    """Labels ``calibrate --submit`` collected on exactly the rated turns."""
    import json

    from edu_agent.evaluator.items import RatedItem
    from edu_agent.schemas.evaluation import Label

    path = project.evals_dir / "judge_labels.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    labels = {}
    for raw_key, value in raw.items():
        item = RatedItem.from_key(raw_key)
        if item is None:
            continue
        try:
            labels[item] = Label(value)
        except ValueError:
            continue
    return labels


"""Comparing judge labels with human ones, and tuning the rubric from them.

The two halves belong together: ``submit`` establishes how far apart the judge and
the human are, and ``tune`` is the only thing allowed to act on that gap — under
the same regression gate the improve loop uses (plan v2 §15.3).
"""

from __future__ import annotations

from edu_agent import ui
from edu_agent.commands import context
from edu_agent.i18n import t
from edu_agent.project import Project


def load_traces(project: Project, run: str):
    from edu_agent.storage.jsonl import RunPaths, latest_run, load_run

    run_id = run or latest_run(project.runs_dir) or ""
    if not run_id:
        return "", []
    return run_id, load_run(RunPaths(project.runs_dir, run_id))


def submit_calibration(project: Project, ratings, *, run: str, no_llm: bool, mock: bool) -> None:
    """Compare human labels with judge labels on *the same* items.

    Reading the labels off the last report only works when the report happened to
    cite the turns the human rated. Asking the judge about those exact turns is
    what makes κ mean what it says.
    """
    import json

    from edu_agent.evaluator.calibration import compute_calibration
    from edu_agent.evaluator.judge import Judge
    from edu_agent.evaluator.judge_tuning import OVERLAY_NAME, judge_labels_for, load_overlay

    run_id, traces = load_traces(project, run)
    if not traces:
        ui.info("비교할 실행 기록이 없습니다. edu-agent test 를 먼저 실행하세요.")
        return

    overlay = load_overlay(project.evals_dir / OVERLAY_NAME)
    judge_provider = context.provider(project, role="judge", no_llm=no_llm, mock=mock)
    if judge_provider is not None:
        ui.info(f"같은 턴에 대해 AI 판정을 받는 중… ({len(ratings)}건)")
        judge = Judge(judge_provider, order_swap=False, overlay=overlay)
        labels = judge_labels_for(judge, traces, ratings)
        (project.evals_dir / "judge_labels.json").write_text(
            json.dumps(
                {item.key(): value.value for item, value in labels.items()},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
            newline="\n",
        )
    else:
        labels = labels_from_report(project, run_id)
        if not labels:
            ui.info("저장된 AI 판정이 없어 일치도를 계산하지 못했습니다.")
            return

    calib = compute_calibration(
        ratings, labels, threshold=project.config.evaluation.calibration_threshold
    )
    calib.overlay_version = overlay.version if overlay else 0
    ui.say()
    if calib.n == 0:
        ui.warn("사람 채점과 AI 판정이 같은 항목에 대해 겹치지 않습니다.")
        ui.note("표본을 다시 뽑아 채점해 보세요: edu-agent calibrate")
        return
    ui.info(f"일치도: {calib.status_text}")
    for metric, kappa in sorted(calib.per_dimension.items(), key=lambda kv: kv[1]):
        ui.note(f"{metric}: κ = {kappa:.2f}")
    if not calib.trustworthy:
        ui.note("AI 판정 점수는 계속 참고용으로 표시됩니다. 자동 검사 결과를 우선 보세요.")
        ui.info(f"{t('common.next_step')}: edu-agent calibrate --tune")


def labels_from_report(project: Project, run_id: str) -> dict:
    """``--no-llm`` fallback: reuse whatever the last report already decided."""
    from edu_agent.evaluator.items import RatedItem
    from edu_agent.schemas.evaluation import EvaluationReport
    from edu_agent.storage.jsonl import RunPaths

    report_path = RunPaths(project.runs_dir, run_id).report
    if not report_path.exists():
        return {}
    report = EvaluationReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    return {
        RatedItem.of(e, c.metric): c.label
        for c in report.checks
        for e in c.evidence
    }


def tune_judge(project: Project, *, run: str, no_llm: bool, mock: bool) -> None:
    """Use the human ratings to improve the judge prompt — and verify it helped."""
    from edu_agent.evaluator.calibration import load_ratings
    from edu_agent.evaluator.judge import Judge
    from edu_agent.evaluator.judge_tuning import (
        HISTORY_NAME,
        OVERLAY_NAME,
        append_history,
        load_overlay,
        save_overlay,
        tune_judge,
    )

    ratings = load_ratings(project.evals_dir / "human_ratings.json")
    if not ratings:
        ui.die(
            "사람 채점 결과가 없습니다.",
            hint="먼저 채점지를 채우고 'edu-agent calibrate --submit' 을 실행하세요.",
            command="edu-agent calibrate",
        )
    _, traces = load_traces(project, run)
    if not traces:
        ui.die("채점의 근거가 된 대화 기록을 찾을 수 없습니다.", command="edu-agent test")

    judge_provider = context.provider(project, role="judge", no_llm=no_llm, mock=mock)
    if judge_provider is None:
        ui.die("루브릭을 다듬으려면 AI 판정이 필요합니다.", hint="--no-llm 없이 실행하세요.")

    ui.header("judge 루브릭 다듬기", "사람 채점을 근거로 판정 프롬프트를 고칩니다.")
    ui.note(
        "채점의 절반으로 예시를 만들고, 나머지 절반으로 일치도가 실제로 올랐는지 확인합니다. "
        "오르지 않으면 되돌립니다."
    )
    ui.say()

    overlay_path = project.evals_dir / OVERLAY_NAME
    previous = load_overlay(overlay_path)
    judge = Judge(judge_provider, order_swap=False, overlay=previous)
    result = tune_judge(judge, ratings, traces, previous=previous)

    if result.kappa_before is not None:
        ui.info(f"다듬기 전 일치도: κ = {result.kappa_before:.2f} (검증 {result.n_holdout}건)")
    for item in result.disagreements[:3]:
        ui.say()
        ui.say(f"  [dim]{item.metric} · 턴 {item.key.turn_index}[/dim]")
        ui.say(f"  사람 [bold]{item.human.value}[/bold] ↔ AI [bold]{item.judge.value}[/bold]")
        if item.tutor_message:
            ui.note(f"튜터: {item.tutor_message}")

    ui.say()
    if result.accepted and result.overlay is not None:
        save_overlay(overlay_path, result.overlay)
        ui.ok(f"루브릭 v{result.overlay.version} 을 적용했습니다. {result.reason}")
        ui.note(f"무엇이 바뀌었는지: {overlay_path}")
    else:
        ui.warn(f"↩ 적용하지 않았습니다: {result.reason}")
        ui.note(
            "루브릭 문구를 고쳐도 일치도가 오르지 않는다면, 판정 기준이 이 수업의 교육적 의도와 "
            "맞는지를 사람이 다시 볼 때입니다."
        )
    append_history(project.evals_dir / HISTORY_NAME, result)


"""Judge calibration against human ratings (plan v2 §15).

Khan Academy's published workflow is the model: humans rate first, inter-rater
agreement is established, and only then is an LLM judge trusted to run unattended.
Norman et al. (2026) put the failure mode bluntly — judges can be highly reliable
and still invalid, with rankings moving up to 14 places across benchmarks.

So the harness treats every judge score as provisional until a human has rated a
sample. That is not busywork: rating twenty turns against the same rubric is how
the author finds out where their own judgement and the model's diverge, and it is
the assessment exercise when this is taught.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import Field

from edu_agent.evaluator.items import RatedItem
from edu_agent.schemas.common import HarnessModel
from edu_agent.schemas.evaluation import Calibration, Label
from edu_agent.schemas.trace import SessionTrace
from edu_agent.utils.text import truncate


class HumanRating(HarnessModel):
    """One human label for one (session, turn, metric)."""

    session_id: str
    turn_index: int
    metric: str
    label: Label
    rater: str = ""
    note: str = ""


class CalibrationSample(HarnessModel):
    """A turn drawn for human rating."""

    session_id: str
    turn_index: int
    metric: str
    question: str = ""
    learner_message: str = ""
    tutor_message: str = ""
    judge_label: Label | None = None


class CalibrationSet(HarnessModel):
    run_id: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    samples: list[CalibrationSample] = Field(default_factory=list)


def cohens_kappa(a: list[str], b: list[str]) -> float | None:
    """Cohen's κ for two label sequences.

    Returns ``None`` for fewer than two items. When both raters use exactly one
    label for everything, κ is undefined (expected agreement = 1); we return 1.0 if
    they agree and 0.0 if they do not, which is the interpretation a reader expects.
    """
    if len(a) != len(b) or len(a) < 2:
        return None
    n = len(a)
    observed = sum(1 for x, y in zip(a, b, strict=True) if x == y) / n

    count_a, count_b = Counter(a), Counter(b)
    labels = set(count_a) | set(count_b)
    expected = sum((count_a[label] / n) * (count_b[label] / n) for label in labels)

    if abs(1.0 - expected) < 1e-9:
        return 1.0 if observed == 1.0 else 0.0
    return (observed - expected) / (1 - expected)


def draw_samples(
    traces: list[SessionTrace],
    metrics: list[str],
    judge_labels: dict[RatedItem, Label] | None = None,
    n: int = 20,
) -> CalibrationSet:
    """Pick a spread of turns for a human to rate.

    Spread across sessions rather than taking the first N turns of one
    conversation — a calibration set drawn from a single session tells you nothing
    about the judge's behaviour on the personas that matter most.
    """
    judge_labels = judge_labels or {}
    samples: list[CalibrationSample] = []
    if not traces or not metrics:
        return CalibrationSet(samples=samples)

    candidates = [(t, turn) for t in traces for turn in t.turns]
    if not candidates:
        return CalibrationSet(samples=samples)

    step = max(1, len(candidates) // max(1, n))
    picked = candidates[::step][:n]

    for i, (trace, turn) in enumerate(picked):
        metric = metrics[i % len(metrics)]
        from edu_agent.evaluator.judge import rubric_for

        rubric = rubric_for(metric)
        samples.append(
            CalibrationSample(
                session_id=trace.session_id,
                turn_index=turn.turn_index,
                metric=metric,
                question=rubric.question if rubric else metric,
                learner_message=truncate(turn.learner_message, 300),
                tutor_message=truncate(turn.tutor_message, 500),
                judge_label=judge_labels.get(
                    RatedItem(trace.session_id, turn.turn_index, metric)
                ),
            )
        )
    return CalibrationSet(samples=samples)


def write_worksheet(path: Path, cset: CalibrationSet) -> Path:
    """Write a Markdown worksheet a student fills in by hand.

    The judge's own label is deliberately **not** shown: seeing it first would
    anchor the rater and inflate agreement.
    """
    lines = [
        "# judge 보정 채점지",
        "",
        "아래 각 항목을 직접 판정하고 `label:` 줄에 `yes` / `partial` / `no` 중 하나를 적으세요.",
        "AI의 판정 결과는 일부러 보여주지 않습니다 (먼저 보면 판단이 끌려갑니다).",
        "",
        "다 채운 뒤 저장하고 `edu-agent calibrate --submit` 을 실행하세요.",
        "",
        "---",
        "",
    ]
    for i, s in enumerate(cset.samples, 1):
        lines += [
            f"## {i}. {s.question}",
            "",
            f"- 대화: `{s.session_id}` / 턴 {s.turn_index}",
            "",
            f"> **학습자**: {s.learner_message}",
            ">",
            f"> **튜터**: {s.tutor_message}",
            "",
            "```yaml",
            f"session_id: {s.session_id}",
            f"turn_index: {s.turn_index}",
            f"metric: {s.metric}",
            "label:        # yes | partial | no",
            "note:         # (선택) 그렇게 본 이유",
            "```",
            "",
        ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return path


def read_worksheet(path: Path) -> list[HumanRating]:
    """Read back the YAML blocks a student filled in."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    ratings: list[HumanRating] = []
    for block in _yaml_blocks(text):
        try:
            data = yaml.safe_load(block) or {}
        except yaml.YAMLError:
            continue
        label = _normalize_label(data.get("label"))
        if label is None:
            continue
        try:
            ratings.append(
                HumanRating(
                    session_id=str(data["session_id"]),
                    turn_index=int(data["turn_index"]),
                    metric=str(data["metric"]),
                    label=Label(label),
                    note=str(data.get("note") or ""),
                )
            )
        except (KeyError, ValueError):
            continue
    return ratings


def _normalize_label(raw: object) -> str | None:
    """Read a human's label, tolerating what people actually type.

    YAML 1.1 turns a bare ``yes`` into ``True`` — and ``label: yes`` is exactly what
    a student writes. Dropping those silently would quietly discard the human
    ratings the whole calibration step depends on.
    """
    if isinstance(raw, bool):
        return "yes" if raw else "no"
    text = str(raw or "").strip().lower()
    aliases = {
        "yes": "yes", "y": "yes", "true": "yes", "예": "yes", "o": "yes",
        "partial": "partial", "p": "partial", "부분": "partial", "일부": "partial", "△": "partial",
        "no": "no", "n": "no", "false": "no", "아니오": "no", "아니요": "no", "x": "no",
    }
    return aliases.get(text)


def _yaml_blocks(text: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] | None = None
    for line in text.splitlines():
        if line.strip().startswith("```yaml"):
            current = []
            continue
        if line.strip() == "```" and current is not None:
            blocks.append("\n".join(current))
            current = None
            continue
        if current is not None:
            current.append(line)
    return blocks


def compute_calibration(
    human: list[HumanRating],
    judge: dict[RatedItem, Label],
    threshold: float = 0.7,
) -> Calibration:
    """Compare human and judge labels on the same items."""
    pairs = [
        (r.label.value, judge[RatedItem.of(r)].value)
        for r in human
        if RatedItem.of(r) in judge
    ]
    calib = Calibration(n=len(pairs), threshold=threshold, rated_at=datetime.now(UTC))
    if not pairs:
        return calib

    calib.kappa = cohens_kappa([p[0] for p in pairs], [p[1] for p in pairs])

    by_metric: dict[str, list[tuple[str, str]]] = {}
    for r in human:
        key = RatedItem.of(r)
        if key in judge:
            by_metric.setdefault(r.metric, []).append((r.label.value, judge[key].value))
    for metric, items in by_metric.items():
        k = cohens_kappa([i[0] for i in items], [i[1] for i in items])
        if k is not None:
            calib.per_dimension[metric] = k
    return calib


def save_ratings(path: Path, ratings: list[HumanRating]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([r.model_dump(mode="json") for r in ratings], ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )
    return path


def load_ratings(path: Path) -> list[HumanRating]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [HumanRating.model_validate(r) for r in data]

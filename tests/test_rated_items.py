"""The identity of a rated item.

This used to be a bare tuple assembled by hand in nine places and joined on
``"|"`` for JSON. A session id containing that character mispaired a human rating
with someone else's judge verdict — and since κ is computed from exactly those
pairings, the damage would surface as a calibration number, not as an error.
"""

from __future__ import annotations

import pytest

from edu_agent.evaluator.calibration import HumanRating, compute_calibration
from edu_agent.evaluator.items import RatedItem
from edu_agent.schemas.evaluation import Label

AWKWARD_IDS = [
    "s_plain",
    "s|with|pipes",
    "s with spaces",
    "세션|한글",
    "s:colon|and|pipe",
    "|",
    "",
    "12:not-a-length",
]


class TestKeyRoundTrip:
    @pytest.mark.parametrize("session_id", AWKWARD_IDS)
    def test_survives_any_session_id(self, session_id):
        item = RatedItem(session_id, 7, "actionability")
        assert RatedItem.from_key(item.key()) == item

    @pytest.mark.parametrize("metric", ["m", "with|pipe", "with:colon", ""])
    def test_survives_any_metric(self, metric):
        item = RatedItem("s1", 0, metric)
        assert RatedItem.from_key(item.key()) == item

    def test_distinct_items_never_share_a_key(self):
        """The old join collapsed these two onto the same string."""
        first = RatedItem("a|b", 1, "m")
        second = RatedItem("a", 1, "b|1|m")
        assert first.key() != second.key()

    def test_junk_returns_none_rather_than_raising(self):
        for raw in ("", "nonsense", "x:1|m", "5:short", "3:abc|notanint|m"):
            assert RatedItem.from_key(raw) is None


class TestConstruction:
    def test_of_reads_a_human_rating(self):
        rating = HumanRating(session_id="s1", turn_index=3, metric="coherence", label=Label.YES)
        assert RatedItem.of(rating) == RatedItem("s1", 3, "coherence")

    def test_of_takes_the_metric_separately_for_evidence(self):
        """A judge verdict names the metric on the check, not on the turn it cites."""
        from edu_agent.schemas.evaluation import Evidence

        evidence = Evidence(session_id="s1", turn_index=2)
        assert RatedItem.of(evidence, "tutor_tone") == RatedItem("s1", 2, "tutor_tone")

    def test_is_hashable_and_usable_as_a_dict_key(self):
        item = RatedItem("s1", 0, "m")
        assert {item: Label.YES}[RatedItem("s1", 0, "m")] is Label.YES

    def test_is_frozen(self):
        """A key that can be mutated after it is in a dict is not a key."""
        with pytest.raises((AttributeError, TypeError)):
            RatedItem("s1", 0, "m").turn_index = 9  # type: ignore[misc]


def test_pipes_in_a_session_id_do_not_mispair_ratings():
    """The regression this type exists to prevent, end to end through κ."""
    human = [
        HumanRating(session_id="a|b", turn_index=1, metric="m", label=Label.YES),
        HumanRating(session_id="a", turn_index=1, metric="b|1|m", label=Label.NO),
    ]
    judge = {
        RatedItem("a|b", 1, "m"): Label.YES,
        RatedItem("a", 1, "b|1|m"): Label.NO,
    }
    calibration = compute_calibration(human, judge)

    assert calibration.n == 2
    assert calibration.kappa == 1.0  # both agree; a mispairing would not

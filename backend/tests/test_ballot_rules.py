"""The ballot rule itself, tested directly (spec 11, 12)."""
import pytest

from academicai.services.ballots import FAIL, PASS, tally_outcome

MIN = 3


@pytest.mark.parametrize("yes,no,expected,reason", [
    (3, 0, PASS, "majority_yes"),
    (2, 1, PASS, "majority_yes"),
    (5, 4, PASS, "majority_yes"),
    (2, 2, FAIL, "tie"),           # YES = NO fails
    (1, 2, FAIL, "majority_no"),   # YES < NO fails
    (0, 3, FAIL, "majority_no"),
    (2, 0, FAIL, "not_enough_votes"),   # only 2 actual votes
    (1, 1, FAIL, "not_enough_votes"),
    (0, 0, FAIL, "not_enough_votes"),
])
def test_tally_outcomes(yes, no, expected, reason):
    assert tally_outcome(yes, no, MIN) == (expected, reason)


def test_non_voters_are_not_counted_as_no():
    """A 3-0 result passes regardless of how many eligible voters abstained."""
    assert tally_outcome(3, 0, MIN)[0] == PASS


def test_minimum_applies_to_actual_votes_not_electorate():
    assert tally_outcome(2, 0, MIN) == (FAIL, "not_enough_votes")
    assert tally_outcome(2, 1, MIN) == (PASS, "majority_yes")

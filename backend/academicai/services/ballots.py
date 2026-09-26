"""Shared ballot arithmetic for rep verification and rep removal (spec 11, 12).

Both ballots use identical rules, so the decision lives in exactly one place:

  * a fixed voting window (24h)
  * a minimum number of ACTUAL votes (3)
  * non-voters are never counted as NO
  * YES must strictly exceed NO; a tie FAILS

The function is pure so the rule can be tested directly, without a database.
"""
PASS = "PASSED"
FAIL = "FAILED"


def tally_outcome(yes_votes, no_votes, min_votes):
    """Decide a ballot from its actual votes.

    Abstention is not a NO: only cast votes are counted, and a ballot that does
    not reach `min_votes` fails for lack of participation rather than being
    decided by the votes that were cast.
    """
    total = yes_votes + no_votes
    if total < min_votes:
        return FAIL, "not_enough_votes"
    if yes_votes > no_votes:
        return PASS, "majority_yes"
    if yes_votes == no_votes:
        return FAIL, "tie"
    return FAIL, "majority_no"

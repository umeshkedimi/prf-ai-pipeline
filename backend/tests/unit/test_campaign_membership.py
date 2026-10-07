from app.campaigns.membership import zero_filled_counts
from app.db.models.campaign_donor import CAMPAIGN_DONOR_STATUSES


def test_zero_filled_counts_includes_every_status():
    counts = zero_filled_counts([("ready", 4), ("held", 1)])
    assert set(counts) == set(CAMPAIGN_DONOR_STATUSES)
    assert counts["ready"] == 4 and counts["held"] == 1
    assert counts["staged"] == 0


def test_zero_filled_counts_for_an_empty_campaign_is_all_zero():
    assert set(zero_filled_counts([]).values()) == {0}

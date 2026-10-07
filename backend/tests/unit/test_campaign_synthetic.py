import csv
import io

from app.campaigns.outcomes import postal_shape
from app.campaigns.synthetic import generate_campaign_rows, rows_to_csv


def test_generation_is_deterministic():
    assert generate_campaign_rows(100, seed=7) == generate_campaign_rows(100, seed=7)
    assert generate_campaign_rows(100, seed=7)[0] != generate_campaign_rows(100, seed=8)[0]


def test_manifest_matches_the_rows():
    rows, m = generate_campaign_rows(100)
    by_id = {r["external_id"]: r for r in rows}
    assert len(by_id) == len(rows) == m["total"]  # unique ids
    assert len(m["bad_zip_external_ids"]) == 8
    assert all(postal_shape(by_id[i]["postal_code"]) == "9999" for i in m["bad_zip_external_ids"])
    # the planted defect is exactly fixable: left-padding restores the original ZIP
    assert all(by_id[i]["postal_code"].zfill(5) == m["bad_zip_correct_values"][i] for i in m["bad_zip_external_ids"])
    assert all(by_id[i]["state"] == "FL" for i in m["unregistered_external_ids"])
    assert all(by_id[i]["do_not_contact"] == "true" for i in m["do_not_contact_external_ids"])
    assert len(m["duplicate_pairs"]) == 2
    for a, b in m["duplicate_pairs"]:
        assert (by_id[a]["first_name"], by_id[a]["last_name"]) == (by_id[b]["first_name"], by_id[b]["last_name"])


def test_defects_are_disjoint_so_each_has_one_expected_finding():
    _, m = generate_campaign_rows(100)
    groups = [set(m["bad_zip_external_ids"]), set(m["unregistered_external_ids"]),
              set(m["do_not_contact_external_ids"])]
    assert sum(len(g) for g in groups) == len(set.union(*groups))


def test_csv_round_trips_into_ingest_format():
    rows, _ = generate_campaign_rows(30, bad_zip=2, dup_pairs=1, unregistered=2, dnc=1)
    parsed = list(csv.DictReader(io.StringIO(rows_to_csv(rows))))
    assert parsed[0]["external_id"] and len(parsed) == len(rows)


def test_id_prefix_is_honoured_so_concurrent_campaigns_cannot_collide():
    rows, m = generate_campaign_rows(30, prefix="evabc", bad_zip=2, dup_pairs=1, unregistered=2, dnc=1)
    assert all(r["external_id"].startswith("evabc-") for r in rows)
    assert all(i.startswith("evabc-") for i in m["bad_zip_external_ids"])

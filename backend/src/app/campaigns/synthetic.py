"""Deterministic synthetic campaign lists with *planted* defects and a ground-truth
manifest. This is the fixture for the campaign agent's evals: a score only means
something if we know exactly what the agent should have found. Same seed, same
file, same manifest. Output rows match the donor CSV ingest format."""

import csv
import io
import random

FIRST = [
    "Marguerite", "Tobias", "Imelda", "Pavel", "Sunita", "Lorenzo", "Hana", "Desmond", "Anika",
    "Caleb", "Odette", "Ravi", "Greta", "Mateo", "Noor", "Felix", "Yara", "Cormac", "Livia", "Ezra",
]
LAST = [
    "Fontaine", "Wendell", "Okafor", "Novak", "Rao", "Castellano", "Ito", "Whitlock", "Berg",
    "Hollis", "Marchetti", "Iyer", "Lindqvist", "Ortega", "Haddad", "Brandt", "Mensah", "Doyle",
    "Petrov", "Sandoval", "Kowalczyk", "Adeyemi", "Fairchild", "Nakamura", "Quinlan", "Rosales",
    "Thorne", "Vasquez", "Yoder", "Zielinski",
]
STREETS = ["Alder Court", "Birch Lane", "Cedar Row", "Elm Street", "Fir Avenue", "Maple Drive", "Oak Way"]
# (city, state, zip prefix) -- FL is the Compliance fixture's unregistered state.
PLACES = [("Seattle", "WA", "981"), ("Portland", "OR", "972"), ("Denver", "CO", "802"),
          ("Boston", "MA", "021"), ("Austin", "TX", "787")]
UNREGISTERED = ("Miami", "FL", "331")
FIELDS = ["external_id", "first_name", "last_name", "email", "address_line1", "city", "state",
          "postal_code", "do_not_contact"]


def generate_campaign_rows(
    n: int = 100, seed: int = 7, bad_zip: int = 8, dup_pairs: int = 2, unregistered: int = 5, dnc: int = 1
) -> tuple[list[dict], dict]:
    """Returns (rows, manifest). Planted-defect donors are disjoint, so each defect
    has exactly one expected finding."""
    planted = bad_zip + 2 * dup_pairs + unregistered + dnc
    if n < planted + 1:
        raise ValueError(f"n={n} too small for {planted} planted donors")
    rng = random.Random(seed)
    combos = [(f, ln) for f in FIRST for ln in LAST]
    rng.shuffle(combos)

    rows: list[dict] = []
    for i in range(n - dup_pairs):  # duplicates are appended after, as extra rows
        first, last = combos[i]
        city, state, prefix = PLACES[i % len(PLACES)]
        rows.append({
            "external_id": f"sc-{i + 1:04d}", "first_name": first, "last_name": last,
            "email": f"{first}.{last}@example.org".lower(),
            "address_line1": f"{100 + i * 7} {STREETS[i % len(STREETS)]}",
            "city": city, "state": state, "postal_code": f"{prefix}{rng.randint(10, 99)}",
            "do_not_contact": "false",
        })

    idx = list(range(len(rows)))
    rng.shuffle(idx)
    take = lambda k: [idx.pop() for _ in range(k)]  # noqa: E731
    bad_zip_rows, unreg_rows, dnc_rows, dup_src = take(bad_zip), take(unregistered), take(dnc), take(dup_pairs)

    for i in bad_zip_rows:  # a spreadsheet dropped the leading digit: one shared defect
        rows[i]["postal_code"] = rows[i]["postal_code"][1:]
    for i in unreg_rows:
        rows[i]["city"], rows[i]["state"] = UNREGISTERED[0], UNREGISTERED[1]
        rows[i]["postal_code"] = f"{UNREGISTERED[2]}{rng.randint(10, 99)}"
    for i in dnc_rows:
        rows[i]["do_not_contact"] = "true"

    pairs = []
    for i in dup_src:
        src = rows[i]
        dup = dict(src, external_id=f"sc-{len(rows) + 1:04d}",
                   address_line1=src["address_line1"].replace("Court", "Ct").replace("Street", "St")
                   .replace("Avenue", "Ave").replace("Lane", "Ln").replace("Drive", "Dr"),
                   email="")
        rows.append(dup)
        pairs.append(sorted([src["external_id"], dup["external_id"]]))

    manifest = {
        "total": len(rows),
        "bad_zip_external_ids": sorted(rows[i]["external_id"] for i in bad_zip_rows),
        "bad_zip_shape": "9999",
        "unregistered_external_ids": sorted(rows[i]["external_id"] for i in unreg_rows),
        "unregistered_state": UNREGISTERED[1],
        "do_not_contact_external_ids": sorted(rows[i]["external_id"] for i in dnc_rows),
        "duplicate_pairs": sorted(pairs),
    }
    return rows, manifest


def rows_to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()

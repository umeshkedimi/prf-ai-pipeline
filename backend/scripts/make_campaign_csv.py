"""Write a synthetic campaign CSV with planted defects, plus its ground-truth manifest.

    uv run python scripts/make_campaign_csv.py --out /tmp/spring.csv --n 100
Upload the CSV via POST /donors/ingest?campaign_id=...; the .manifest.json beside it
says exactly what an agent should find."""

import argparse
import json
from pathlib import Path

from app.campaigns.synthetic import generate_campaign_rows, rows_to_csv

parser = argparse.ArgumentParser()
parser.add_argument("--out", required=True)
parser.add_argument("--n", type=int, default=100)
parser.add_argument("--seed", type=int, default=7)
args = parser.parse_args()

rows, manifest = generate_campaign_rows(args.n, args.seed)
out = Path(args.out)
out.write_text(rows_to_csv(rows))
out.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2))
print(f"wrote {len(rows)} donors to {out} (+ manifest)")

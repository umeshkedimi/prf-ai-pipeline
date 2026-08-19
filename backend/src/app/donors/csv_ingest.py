"""Deterministic CSV donor ingestion: parse, validate, upsert. No LLM call and
no workflow run is ever triggered from here — ingestion only ever stages
donor records; starting a run on one of them is a separate, explicit action
(see POST /workflow/run/batch), never a side effect of an upload. That split
is deliberate: an uploaded file firing off LLM-calling runs unattended is
exactly the failure mode this project's eval-cost history (see
CLAUDE.local.md's "the eval cost model") already paid for once."""

import csv
import io

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Donor

REQUIRED_FIELDS = ("external_id", "first_name", "last_name")
_OPTIONAL_STRING_FIELDS = (
    "email",
    "phone",
    "address_line1",
    "address_line2",
    "city",
    "state",
    "postal_code",
    "country",
    "notes",
)
_TRUTHY = {"true", "1", "yes", "y"}


def parse_csv_rows(csv_text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(csv_text)))


def validate_row(row: dict[str, str]) -> str | None:
    """Only the identity fields are required -- address/email are allowed to
    be blank, the same tolerance the pipeline itself already has for a
    malformed record (see the d-0007 seed fixture, which exercises exactly
    this: no address, no email, still an eligible donor to route)."""
    for field in REQUIRED_FIELDS:
        if not (row.get(field) or "").strip():
            return f"missing required field '{field}'"
    return None


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


async def ingest_donors(session: AsyncSession, rows: list[dict[str, str]]) -> dict:
    """Upserts by external_id -- insert if new, update in place if it
    already exists. Rejects only rows missing an identity field; returns
    counts plus a per-row rejection report. Does not commit -- the caller
    controls the transaction (see api/v1/endpoints/donors.py, which also
    writes the DonorImport audit row in the same commit)."""
    inserted = 0
    updated = 0
    rejected: list[dict] = []

    for row_number, row in enumerate(rows, start=1):
        reason = validate_row(row)
        if reason:
            rejected.append(
                {"row_number": row_number, "reason": reason, "external_id": row.get("external_id")}
            )
            continue

        external_id = row["external_id"].strip()
        existing = (
            await session.execute(select(Donor).where(Donor.external_id == external_id))
        ).scalars().first()
        do_not_contact = (row.get("do_not_contact") or "").strip().lower() in _TRUTHY

        if existing:
            # A blank CSV cell never overwrites an existing value on
            # update -- a partial re-upload (e.g. a name-only correction
            # file) shouldn't silently erase address/email data an earlier
            # upload set.
            existing.first_name = row["first_name"].strip()
            existing.last_name = row["last_name"].strip()
            existing.do_not_contact = do_not_contact
            for field in _OPTIONAL_STRING_FIELDS:
                cleaned = _clean(row.get(field))
                if cleaned is not None:
                    setattr(existing, field, cleaned)
            updated += 1
        else:
            values = {field: _clean(row.get(field)) for field in _OPTIONAL_STRING_FIELDS}
            values.pop("country", None)  # let the column's own "US" default apply when blank
            country = _clean(row.get("country"))
            if country is not None:
                values["country"] = country
            session.add(
                Donor(
                    external_id=external_id,
                    first_name=row["first_name"].strip(),
                    last_name=row["last_name"].strip(),
                    do_not_contact=do_not_contact,
                    **values,
                )
            )
            inserted += 1

    await session.flush()
    return {"inserted": inserted, "updated": updated, "rejected": rejected}

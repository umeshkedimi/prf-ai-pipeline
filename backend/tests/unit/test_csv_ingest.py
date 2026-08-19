"""Pure-function coverage for the CSV parsing/validation logic in
donors/csv_ingest.py -- no DB, offline. The DB-touching upsert half
(ingest_donors) is covered by tests/integration/test_donor_ingest.py,
same split as this project's other DB-writing logic."""

from app.donors.csv_ingest import parse_csv_rows, validate_row


def test_parse_csv_rows_reads_a_simple_csv():
    csv_text = "external_id,first_name,last_name\nd-1001,Ada,Lovelace\n"
    rows = parse_csv_rows(csv_text)
    assert rows == [{"external_id": "d-1001", "first_name": "Ada", "last_name": "Lovelace"}]


def test_parse_csv_rows_handles_no_data_rows():
    assert parse_csv_rows("external_id,first_name,last_name\n") == []


def test_validate_row_accepts_a_row_with_only_identity_fields():
    row = {"external_id": "d-1001", "first_name": "Ada", "last_name": "Lovelace"}
    assert validate_row(row) is None


def test_validate_row_rejects_a_missing_external_id():
    row = {"external_id": "", "first_name": "Ada", "last_name": "Lovelace"}
    assert "external_id" in validate_row(row)


def test_validate_row_rejects_a_missing_first_name():
    row = {"external_id": "d-1001", "first_name": "  ", "last_name": "Lovelace"}
    assert "first_name" in validate_row(row)


def test_validate_row_rejects_a_missing_last_name():
    row = {"external_id": "d-1001", "first_name": "Ada", "last_name": None}
    assert "last_name" in validate_row(row)


def test_validate_row_tolerates_a_blank_address_and_email():
    """The pipeline itself already tolerates this (d-0007's malformed-record
    seed fixture) -- ingestion shouldn't be stricter than the thing it feeds."""
    row = {
        "external_id": "d-1001",
        "first_name": "Ada",
        "last_name": "Lovelace",
        "email": "",
        "address_line1": "",
    }
    assert validate_row(row) is None

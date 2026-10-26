"""Deterministic synthetic cases with exact, inspectable expected results."""

import json
from pathlib import Path
import tempfile
from .analysis import analyze
from .ingest import ingest, read_manifest
from .model import InputError


def generate(out: str | Path) -> dict:
    out = Path(out)
    try:
        out.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise InputError("output_directory_exists") from None
    except OSError:
        raise InputError("output_unavailable") from None
    def row(key, created, status="Open", closed=None, agency="DOT"):
        return {"unique_key": str(key), "created_date": f"2026-{created}T00:00:00.000",
                "closed_date": f"2026-{closed}T00:00:00.000" if closed else None,
                "agency": agency, "complaint_type": "Synthetic example", "status": status, "borough": "QUEENS"}
    rows = [row(1001, "09-01", "Closed", "09-02"), row(1002, "09-01", "Closed", "09-03"), row(1003, "09-01"),
            row(1004, "09-10", agency="NYPD"), row(1005, "09-10", "Closed", "09-20", agency="NYPD"),
            row(1006, "09-29", "Closed", "09-30"), row(1007, "09-30"), row(1008, "09-15", "Closed"),
            row(1009, "09-15", "Open", "09-16"), row(1010, "09-20", "Closed", "09-19"), row(1011, "08-31"),
            row(1012, "09-20", "New Status"), row(1013, "09-20", "Closed", "10-02")]
    manifest = {"schema_version": 1, "source": "synthetic", "acquired_at": "2026-10-01T04:00:00Z",
                "cohort_start": "2026-09-01T00:00:00", "cohort_end": "2026-10-01T00:00:00",
                "observed_at": "2026-10-01T00:00:00", "completeness": "complete", "timestamp_semantics": "floating_civil"}
    try:
        for name, value in (("requests.json", rows), ("manifest.json", manifest)):
            with (out / name).open("x", encoding="utf8") as stream:
                json.dump(value, stream, indent=2); stream.write("\n")
    except OSError:
        raise InputError("output_unavailable") from None
    return {"generated_records": len(rows), "source": "synthetic", "directory": str(out)}


def run_demo() -> dict:
    with tempfile.TemporaryDirectory(prefix="civic-demo-") as directory:
        fixture = Path(directory) / "fixture"; db = Path(directory) / "snapshot.duckdb"
        generate(fixture)
        context = read_manifest(fixture / "manifest.json")
        result = ingest(fixture / "requests.json", context, db)
        repeated = ingest(fixture / "requests.json", context, db)
        report = analyze(db, result["snapshot_id"])
        summary = report["summary"]
        assert result["inserted_rows"] == 13 and repeated["already_present"] and repeated["inserted_rows"] == 0
        assert summary == {"cohort_rows": 12, "closed_count": 4, "open_count": 3, "unknown_outcome_count": 5,
                           "closed_only_median_days": 1.5, "retained_rows_outside_scope": 1}
        assert report["horizons"][0]["eligible_known"] == 5 and report["horizons"][0]["closed_within_horizon"] == 2
        assert report["horizons"][1]["eligible_known"] == 3 and report["horizons"][1]["closed_within_horizon"] == 2
        assert list(report["open_age_bands"].values()) == [1, 1, 1]
        return {"dataset": "13 entirely synthetic requests with known outcomes and deliberate quality defects",
                "verified_reimport_inserted_rows": 0, "summary": summary, "horizons": report["horizons"],
                "open_age_bands": report["open_age_bands"], "quality": result["quality"],
                "limitations": "Functional fixture checks, not public-data findings or performance measurements. Durations use floating calendar-clock days."}

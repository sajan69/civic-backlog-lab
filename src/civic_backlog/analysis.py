"""Explicit-denominator metrics over one immutable observation."""

from importlib.resources import files
import duckdb
from .ingest import connect, snapshot
from .model import InputError


def _query(connection, name, params):
    folder = files("civic_backlog").joinpath("sql")
    sql = folder.joinpath("scope.sql").read_text() + folder.joinpath(name + ".sql").read_text()
    cursor = connection.execute(sql, params)
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def analyze(db, snapshot_id: str, *, allow_partial: bool = False) -> dict:
    connection = connect(db, read_only=True)
    try:
        connection.execute("BEGIN TRANSACTION")
        info = snapshot(connection, snapshot_id)
        context = info["manifest"]
        partial = context["completeness"] != "complete" or info["quality"]["invalid_records"] > 0
        if partial and not allow_partial:
            raise InputError("partial_snapshot_requires_opt_in")
        params = [context["cohort_start"], context["cohort_end"], context["observed_at"], context["agency"], snapshot_id]
        summary = _query(connection, "summary", params)[0]
        summary["retained_rows_outside_scope"] = info["row_count"] - summary["cohort_rows"]
        horizons = _query(connection, "horizons", params)
        for row in horizons:
            row["closure_fraction"] = row["closed_within_horizon"] / row["eligible_known"] if row["eligible_known"] else None
        bands = {"under_7_days": 0, "7_to_under_30_days": 0, "30_days_or_more": 0}
        bands.update({row["age_band"]: row["requests"] for row in _query(connection, "age_bands", params)})
        groups = _query(connection, "groups", params)
        if len(groups) > 200:
            raise InputError("too_many_agency_groups")
        connection.execute("COMMIT")
        warnings = ["completeness_is_caller_declared", "snapshot_is_not_event_history", "floating_civil_durations_are_not_timezone_adjusted"]
        if context.get("acquisition") is not None:
            warnings.remove("completeness_is_caller_declared")
            warnings.append("acquisition_metadata_is_unattested")
            warnings.append("paged_source_capture_is_not_atomic_or_authenticated")
            warnings.append("observation_clock_uses_publisher_zone_assumption")
        if partial:
            warnings.append("partial_input_not_a_population_estimate")
        if summary["unknown_outcome_count"]:
            warnings.append("unknown_outcomes_excluded_from_horizon_denominators")
        return {"snapshot": info, "summary": summary, "horizons": horizons, "open_age_bands": bands,
                "by_agency": groups, "duration_unit": "floating_calendar_clock_days", "warnings": warnings}
    except duckdb.Error:
        raise InputError("analysis_failed") from None
    finally:
        connection.close()

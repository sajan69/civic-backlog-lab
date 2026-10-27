"""Version-one NYC311 projection and explicit snapshot time semantics."""

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
import re
from typing import Any
from .provenance import validate_acquisition

FIELDS = ("unique_key", "created_date", "closed_date", "agency", "complaint_type", "status", "borough")
SOURCE_URL = "https://data.cityofnewyork.us/resource/erm2-nwe9.json"
ALIASES = dict(zip(("Unique Key", "Created Date", "Closed Date", "Agency", "Problem", "Status", "Borough"), FIELDS))
ALIASES["Complaint Type"] = "complaint_type"
ALIASES["Problem (formerly Complaint Type)"] = "complaint_type"
ALIASES.update({name: name for name in FIELDS})
ACTIVE_STATUSES = {"open", "pending", "in progress", "started", "assigned"}
BOROUGHS = {"BRONX", "BROOKLYN", "MANHATTAN", "QUEENS", "STATEN ISLAND", "UNSPECIFIED"}


class InputError(ValueError):
    """Safe machine-readable code; never interpolate source values."""


class RecordError(InputError):
    pass


def civil_time(value: Any) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?", value):
        raise InputError("invalid_civil_timestamp")
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise InputError("invalid_civil_timestamp") from None


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def text(value: Any, limit: int, *, empty: str | None = None) -> str:
    if value is None or value == "":
        if empty is not None:
            return empty
        raise RecordError("missing_text")
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 or 127 <= ord(c) <= 159 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise RecordError("invalid_text")
    result = value.strip()
    if not result:
        if empty is not None:
            return empty
        raise RecordError("missing_text")
    return result


@dataclass(frozen=True)
class Manifest:
    source: str
    acquired_at: str
    cohort_start: datetime
    cohort_end: datetime
    observed_at: datetime
    completeness: str
    agency: str | None = None
    acquisition: dict | None = None

    @classmethod
    def parse(cls, value: Any) -> "Manifest":
        required = {"schema_version", "source", "acquired_at", "cohort_start", "cohort_end", "observed_at", "completeness", "timestamp_semantics"}
        if not isinstance(value, dict) or set(value) - required - {"agency", "acquisition"} or not required <= set(value):
            raise InputError("invalid_manifest_fields")
        if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["timestamp_semantics"] != "floating_civil":
            raise InputError("unsupported_manifest")
        if value["source"] not in ("synthetic", "local_export", "nyc311") or value["completeness"] not in ("complete", "unknown", "truncated"):
            raise InputError("invalid_manifest_enum")
        try:
            acquired = datetime.fromisoformat(value["acquired_at"].replace("Z", "+00:00"))
            if acquired.tzinfo is None:
                raise ValueError()
            acquired = acquired.astimezone(timezone.utc).isoformat()
            start, end, observed = (civil_time(value[name]) for name in ("cohort_start", "cohort_end", "observed_at"))
            if not start < end <= observed or end - start > timedelta(days=366):
                raise ValueError()
            agency = value.get("agency")
            if agency is not None:
                agency = text(agency, 40).upper()
        except (ValueError, TypeError, AttributeError):
            raise InputError("invalid_manifest_time_or_scope") from None
        acquisition = value.get("acquisition")
        if acquisition is not None:
            try:
                if value["source"] != "nyc311": raise ValueError()
                acquisition = validate_acquisition(acquisition, start, end, agency)
                if value["completeness"] == "complete" and (acquisition["consistency"] != "stable_checks"
                        or acquisition["termination"] in ("row_limit", "page_limit")):
                    raise ValueError()
            except (ValueError, TypeError, KeyError, AttributeError):
                raise InputError("invalid_acquisition_metadata") from None
        return cls(value["source"], acquired, start, end, observed, value["completeness"], agency, acquisition)

    def to_dict(self) -> dict:
        result = {"schema_version": 1, "adapter": "nyc311-projection-v1", "source": self.source,
                "source_url": SOURCE_URL if self.source == "nyc311" else None,
                "acquired_at": self.acquired_at, "cohort_start": self.cohort_start.isoformat(timespec="milliseconds"),
                "cohort_end": self.cohort_end.isoformat(timespec="milliseconds"),
                "observed_at": self.observed_at.isoformat(timespec="milliseconds"), "completeness": self.completeness,
                "completeness_basis": "caller_declared", "timestamp_semantics": "floating_civil", "agency": self.agency,
                "projection_fields": list(FIELDS)}
        if self.acquisition is not None:
            result["acquisition"] = json.loads(canonical_json(self.acquisition))
            result["completeness_basis"] = "recorded_paged_checks_unattested"
        return result


@dataclass(frozen=True)
class Request:
    unique_key: str
    created_date: datetime
    closed_date: datetime | None
    agency: str
    complaint_type: str
    status: str
    borough: str
    outcome: str
    flags: tuple[str, ...]

    def identity(self) -> str:
        obj = asdict(self)
        obj["created_date"] = self.created_date.isoformat(timespec="milliseconds")
        obj["closed_date"] = self.closed_date.isoformat(timespec="milliseconds") if self.closed_date else None
        return canonical_json(obj)


def normalize(value: Any, manifest: Manifest) -> Request:
    if not isinstance(value, dict):
        raise RecordError("expected_record_object")
    key = value.get("unique_key")
    if not isinstance(key, str) or not re.fullmatch(r"[0-9]{1,32}", key):
        raise RecordError("invalid_unique_key")
    try:
        created = civil_time(value.get("created_date"))
        closed = civil_time(value["closed_date"]) if value.get("closed_date") not in (None, "") else None
    except InputError:
        raise RecordError("invalid_record_timestamp") from None
    agency = text(value.get("agency"), 40, empty="UNKNOWN").upper()
    problem = text(value.get("complaint_type"), 160, empty="Unknown")
    status = text(value.get("status"), 64, empty="unknown").lower()
    borough = text(value.get("borough"), 64, empty="UNSPECIFIED").upper()
    flags = []
    if agency == "UNKNOWN":
        flags.append("missing_agency")
    if problem == "Unknown":
        flags.append("missing_problem")
    if borough not in BOROUGHS:
        flags.append("unknown_borough")
    if status not in ACTIVE_STATUSES | {"closed"}:
        flags.append("unknown_status")
    if not manifest.cohort_start <= created < manifest.cohort_end:
        flags.append("outside_cohort")
    if manifest.agency is not None and agency != manifest.agency:
        flags.append("agency_scope_mismatch")
    if created > manifest.observed_at:
        flags.append("future_creation")
    if closed is not None and closed < created:
        flags.append("negative_duration")
    if closed is not None and closed > manifest.observed_at:
        flags.append("future_closure")
    if status == "closed" and closed is None:
        flags.append("closed_missing_date")
    if status != "closed" and closed is not None:
        flags.append("status_date_conflict")
    critical = {"unknown_status", "negative_duration", "future_closure", "closed_missing_date", "status_date_conflict", "future_creation"}
    outcome = "unknown" if critical.intersection(flags) else "closed" if status == "closed" else "open"
    return Request(key, created, closed, agency, problem, status, borough, outcome, tuple(sorted(flags)))

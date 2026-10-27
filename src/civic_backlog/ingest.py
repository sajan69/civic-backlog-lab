"""Bounded local inputs and immutable, data-minimized DuckDB snapshots."""

from collections import Counter
import csv
from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
import re
import duckdb
from .model import ALIASES, FIELDS, InputError, Manifest, RecordError, Request, canonical_json, normalize

MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 20_000
MAX_MANIFEST_BYTES = 64 * 1024


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise InputError("duplicate_json_key")
        value[key] = item
    return value


def load_json(value: str):
    try:
        return json.loads(value, object_pairs_hook=_object,
                          parse_constant=lambda _: (_ for _ in ()).throw(InputError("invalid_json_constant")))
    except (json.JSONDecodeError, RecursionError):
        raise InputError("invalid_json_syntax") from None


def _read(path: Path, limit: int) -> bytes:
    try:
        with path.open("rb") as stream:
            value = stream.read(limit + 1)
    except OSError:
        raise InputError("input_unavailable") from None
    if len(value) > limit:
        raise InputError("input_too_large")
    return value


def read_manifest(path: str | Path) -> Manifest:
    try:
        return Manifest.parse(load_json(_read(Path(path), MAX_MANIFEST_BYTES).decode("utf-8-sig")))
    except UnicodeError:
        raise InputError("invalid_utf8") from None


def _records(raw: bytes, file_format: str) -> list:
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeError:
        raise InputError("invalid_utf8") from None
    if file_format == "json":
        records = load_json(content)
        if not isinstance(records, list):
            raise InputError("expected_json_array")
    elif file_format == "csv":
        try:
            reader = csv.DictReader(io.StringIO(content, newline=""), strict=True)
            columns = reader.fieldnames
            if not columns or len(columns) != len(set(columns)):
                raise InputError("invalid_csv_header")
            mapped = [ALIASES[name] for name in columns if name in ALIASES]
            if len(mapped) != len(set(mapped)) or not {"unique_key", "created_date"} <= set(mapped):
                raise InputError("ambiguous_or_missing_csv_columns")
            records = []
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise InputError("invalid_csv_shape")
                records.append({ALIASES.get(key, key): value for key, value in row.items()})
                if len(records) > MAX_ROWS:
                    raise InputError("too_many_records")
        except csv.Error:
            raise InputError("invalid_csv_syntax") from None
    else:
        raise InputError("unsupported_format")
    if len(records) > MAX_ROWS:
        raise InputError("too_many_records")
    return records


@dataclass
class Parsed:
    rows: list[Request]
    raw_hash: str
    raw_bytes: int
    quality: dict


def parse_file(path: str | Path, manifest: Manifest, *, skip_invalid: bool = False) -> Parsed:
    path = Path(path)
    raw = _read(path, MAX_BYTES)
    records = _records(raw, path.suffix.lower().lstrip("."))
    if manifest.acquisition is not None:
        if hashlib.sha256(raw).hexdigest() != manifest.acquisition["payload_sha256"] or len(records) != manifest.acquisition["rows_written"]:
            raise InputError("acquisition_payload_mismatch")
    unique: dict[str, Request] = {}
    invalid = duplicates = ignored = 0
    issues = []
    for index, value in enumerate(records, 1):
        if isinstance(value, dict):
            ignored += sum(key not in FIELDS for key in value)
        try:
            row = normalize(value, manifest)
        except RecordError as error:
            if not skip_invalid:
                raise InputError(f"record_{index}_{error}") from None
            invalid += 1
            if len(issues) < 20:
                issues.append({"record": index, "code": str(error)})
            continue
        previous = unique.get(row.unique_key)
        if previous:
            if previous.identity() != row.identity():
                raise InputError("conflicting_duplicate_id")
            duplicates += 1
        else:
            unique[row.unique_key] = row
    rows = sorted(unique.values(), key=lambda row: row.unique_key)
    quality = {"input_records": len(records), "retained_unique": len(rows), "invalid_records": invalid,
               "exact_duplicates": duplicates, "ignored_field_values": ignored,
               "flag_counts": dict(sorted(Counter(flag for row in rows for flag in row.flags).items())), "issues": issues}
    return Parsed(rows, hashlib.sha256(raw).hexdigest(), len(raw), quality)


def connect(path: str | Path, *, read_only: bool = False):
    try:
        return duckdb.connect(str(path), read_only=read_only,
                              config={"enable_external_access": "false", "threads": "2", "memory_limit": "256MB"})
    except duckdb.Error:
        raise InputError("database_unavailable") from None


def _schema(connection):
    tables = {row[0] for row in connection.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()}
    if tables:
        if tables != {"civic_meta", "snapshots", "requests"}:
            raise InputError("unsupported_database")
        if connection.execute("SELECT version FROM civic_meta").fetchall() != [(1,)]:
            raise InputError("unsupported_database_version")
        return
    connection.execute("CREATE TABLE civic_meta(version INTEGER); INSERT INTO civic_meta VALUES(1)")
    connection.execute("""CREATE TABLE snapshots(
        snapshot_id VARCHAR PRIMARY KEY, manifest_json VARCHAR NOT NULL, raw_hash VARCHAR NOT NULL,
        raw_bytes BIGINT NOT NULL, quality_json VARCHAR NOT NULL, row_count INTEGER NOT NULL)""")
    connection.execute("""CREATE TABLE requests(
        snapshot_id VARCHAR NOT NULL, unique_key VARCHAR NOT NULL, created_date TIMESTAMP NOT NULL,
        closed_date TIMESTAMP, agency VARCHAR NOT NULL, complaint_type VARCHAR NOT NULL,
        status VARCHAR NOT NULL, borough VARCHAR NOT NULL, outcome VARCHAR NOT NULL,
        flags VARCHAR[] NOT NULL, PRIMARY KEY(snapshot_id,unique_key))""")


def ingest(path: str | Path, manifest: Manifest, db: str | Path, *, skip_invalid: bool = False) -> dict:
    parsed = parse_file(path, manifest, skip_invalid=skip_invalid) # All syntax/identity validation precedes writes.
    context = manifest.to_dict()
    context["invalid_record_policy"] = "skip" if skip_invalid else "strict"
    context_json = canonical_json(context)
    snapshot_id = hashlib.sha256((context_json + ":" + parsed.raw_hash).encode()).hexdigest()
    connection = connect(db)
    transaction = False
    try:
        connection.execute("BEGIN TRANSACTION"); transaction = True
        _schema(connection)
        existing = connection.execute("SELECT snapshot_id FROM snapshots WHERE snapshot_id=?", [snapshot_id]).fetchone()
        if existing:
            connection.execute("COMMIT"); transaction = False
            return {"snapshot_id": snapshot_id, "already_present": True, "inserted_rows": 0, "quality": parsed.quality}
        connection.execute("INSERT INTO snapshots VALUES(?,?,?,?,?,?)", [snapshot_id, context_json, parsed.raw_hash,
                                                                       parsed.raw_bytes, canonical_json(parsed.quality), len(parsed.rows)])
        if parsed.rows:
            connection.executemany("INSERT INTO requests VALUES(?,?,?,?,?,?,?,?,?,?)", [
                (snapshot_id, row.unique_key, row.created_date, row.closed_date, row.agency,
                 row.complaint_type, row.status, row.borough, row.outcome, list(row.flags)) for row in parsed.rows])
        connection.execute("COMMIT"); transaction = False
        return {"snapshot_id": snapshot_id, "already_present": False, "inserted_rows": len(parsed.rows), "quality": parsed.quality}
    except duckdb.Error:
        raise InputError("database_operation_failed") from None
    finally:
        if transaction:
            try: connection.execute("ROLLBACK")
            except duckdb.Error: pass
        connection.close()


def snapshot(connection, snapshot_id: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{64}", snapshot_id):
        raise InputError("invalid_snapshot_id")
    try:
        row = connection.execute("SELECT manifest_json,raw_hash,raw_bytes,quality_json,row_count FROM snapshots WHERE snapshot_id=?", [snapshot_id]).fetchone()
    except duckdb.Error:
        raise InputError("unsupported_database") from None
    if row is None:
        raise InputError("snapshot_not_found")
    return {"snapshot_id": snapshot_id, "manifest": json.loads(row[0]), "raw_sha256": row[1],
            "raw_bytes": row[2], "quality": json.loads(row[3]), "row_count": row[4]}


def list_snapshots(db: str | Path) -> list[dict]:
    connection = connect(db, read_only=True)
    try:
        rows = connection.execute("SELECT snapshot_id,manifest_json,row_count FROM snapshots ORDER BY snapshot_id LIMIT 100").fetchall()
        return [{"snapshot_id": row[0], "source": json.loads(row[1])["source"],
                 "acquired_at": json.loads(row[1])["acquired_at"], "row_count": row[2]} for row in rows]
    except duckdb.Error:
        raise InputError("unsupported_database") from None
    finally:
        connection.close()

import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from civic_backlog.ingest import ingest, list_snapshots, parse_file, connect, snapshot
from civic_backlog.model import InputError, Manifest
from test_model import metadata, record


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "input.json"; self.db = Path(self.temp.name) / "data.duckdb"
        self.manifest = Manifest.parse(metadata())

    def write(self, values):
        self.path.write_text(json.dumps(values), encoding="utf8")

    def test_import_idempotence_and_minimized_storage(self):
        self.write([record(incident_address="private marker", location={"latitude": 1}), record()])
        result = ingest(self.path, self.manifest, self.db)
        self.assertEqual(result["inserted_rows"], 1); self.assertEqual(result["quality"]["exact_duplicates"], 1)
        self.assertEqual(result["quality"]["ignored_field_values"], 2)
        again = ingest(self.path, self.manifest, self.db)
        self.assertTrue(again["already_present"]); self.assertEqual(again["inserted_rows"], 0)
        connection = connect(self.db, read_only=True)
        stored = str(connection.execute("SELECT * FROM requests").fetchall())
        self.assertNotIn("private marker", stored); self.assertNotIn("latitude", stored)
        self.assertEqual(snapshot(connection, result["snapshot_id"])["row_count"], 1); connection.close()
        self.assertEqual(len(list_snapshots(self.db)), 1)

    def test_strict_failure_precedes_database_creation(self):
        self.write([record(), record(unique_key="bad-private")])
        with self.assertRaises(InputError) as error: ingest(self.path, self.manifest, self.db)
        self.assertNotIn("private", str(error.exception)); self.assertFalse(self.db.exists())

    def test_skip_invalid_is_explicit_and_quality_issues_are_bounded(self):
        self.write([record()] + [record(unique_key="bad") for _ in range(25)])
        result = ingest(self.path, self.manifest, self.db, skip_invalid=True)
        self.assertEqual(result["inserted_rows"], 1); self.assertEqual(result["quality"]["invalid_records"], 25)
        self.assertEqual(len(result["quality"]["issues"]), 20)

    def test_conflicting_duplicate_aborts_even_with_skipping(self):
        self.write([record(), record(status="Closed", closed_date="2026-09-02T00:00:00")])
        with self.assertRaisesRegex(InputError, "conflicting_duplicate_id"):
            ingest(self.path, self.manifest, self.db, skip_invalid=True)
        self.assertFalse(self.db.exists())

    def test_syntax_duplicate_keys_and_nonfinite_json_never_skip(self):
        for value in ('[{"unique_key":"1","unique_key":"2"}]', '[NaN]', '[', '{}'):
            self.path.write_text(value)
            with self.subTest(value=value), self.assertRaises(InputError):
                ingest(self.path, self.manifest, self.db, skip_invalid=True)
        self.assertFalse(self.db.exists())

    def test_byte_and_row_limits_are_enforced_before_writes(self):
        self.write([record(), record(unique_key="1002")])
        with patch("civic_backlog.ingest.MAX_ROWS", 1), self.assertRaisesRegex(InputError, "too_many_records"):
            ingest(self.path, self.manifest, self.db)
        with patch("civic_backlog.ingest.MAX_BYTES", 5), self.assertRaisesRegex(InputError, "input_too_large"):
            ingest(self.path, self.manifest, self.db)
        self.path.write_bytes(b'\xff')
        with self.assertRaisesRegex(InputError, "invalid_utf8"): ingest(self.path, self.manifest, self.db)

    def test_csv_current_and_legacy_labels_map_without_sensitive_fields(self):
        path = self.path.with_suffix('.csv')
        for problem_label in ("Problem", "Complaint Type"):
            with path.open('w', newline='') as stream:
                writer = csv.writer(stream); writer.writerow(["Unique Key", "Created Date", "Closed Date", "Agency", problem_label, "Status", "Borough", "Incident Address"])
                writer.writerow(["1001", "2026-09-01T12:00:00", "", "DOT", "Street Condition", "Open", "QUEENS", "private marker"])
            parsed = parse_file(path, self.manifest)
            self.assertEqual(parsed.rows[0].complaint_type, "Street Condition")
            self.assertNotIn("marker", parsed.rows[0].identity())

    def test_ambiguous_headers_and_wrong_csv_shapes_abort(self):
        path = self.path.with_suffix('.csv')
        for value in ('unique_key,created_date,Problem,Complaint Type\n1,2026-09-01T00:00:00,a,b\n',
                      'unique_key,created_date\n1,2026-09-01T00:00:00,extra\n', 'unique_key,unique_key\n1,1\n'):
            path.write_text(value)
            with self.subTest(value=value), self.assertRaises(InputError): parse_file(path, self.manifest, skip_invalid=True)

    def test_changed_snapshot_does_not_overwrite_an_earlier_observation(self):
        self.write([record()]); first = ingest(self.path, self.manifest, self.db)
        self.write([record(status="Closed", closed_date="2026-09-02T00:00:00")]); second = ingest(self.path, self.manifest, self.db)
        self.assertNotEqual(first["snapshot_id"], second["snapshot_id"])
        connection = connect(self.db, read_only=True)
        self.assertEqual(connection.execute("SELECT count(*) FROM snapshots").fetchone()[0], 2)
        self.assertEqual({row[0] for row in connection.execute("SELECT outcome FROM requests").fetchall()}, {"open", "closed"}); connection.close()

    def test_failure_in_row_insert_rolls_back_snapshot_metadata(self):
        self.write([record()]); ingest(self.path, self.manifest, self.db)
        self.write([record(unique_key="1002")])
        real_connect = connect
        connection = real_connect(self.db)
        class Wrapper:
            def execute(self, *args): return connection.execute(*args)
            def executemany(self, *args): raise __import__('duckdb').Error('private internal detail')
            def close(self): connection.close()
        with patch("civic_backlog.ingest.connect", return_value=Wrapper()), self.assertRaisesRegex(InputError, "database_operation_failed"):
            ingest(self.path, self.manifest, self.db)
        self.assertEqual(len(list_snapshots(self.db)), 1)

    def test_unrelated_database_is_preserved_and_missing_read_does_not_create(self):
        with self.assertRaises(InputError): list_snapshots(self.db)
        self.assertFalse(self.db.exists())
        connection = connect(self.db); connection.execute('CREATE TABLE unrelated(value INTEGER)'); connection.close()
        self.write([record()])
        with self.assertRaisesRegex(InputError, "unsupported_database"): ingest(self.path, self.manifest, self.db)
        connection = connect(self.db, read_only=True)
        self.assertEqual(connection.execute('SHOW TABLES').fetchall(), [('unrelated',)]); connection.close()


if __name__ == '__main__': unittest.main()

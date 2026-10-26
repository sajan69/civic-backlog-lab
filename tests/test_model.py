import unittest
from civic_backlog.model import InputError, Manifest, RecordError, civil_time, normalize


def metadata(**changes):
    value = dict(schema_version=1, source="synthetic", acquired_at="2026-10-01T14:00:00Z",
                 cohort_start="2026-09-01T00:00:00", cohort_end="2026-10-01T00:00:00",
                 observed_at="2026-10-01T10:00:00", completeness="complete", timestamp_semantics="floating_civil")
    value.update(changes)
    return value


def record(**changes):
    value = dict(unique_key="1001", created_date="2026-09-01T12:00:00.000", closed_date=None,
                 agency="DOT", complaint_type="Street Condition", status="Open", borough="QUEENS")
    value.update(changes)
    return value


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.manifest = Manifest.parse(metadata())

    def test_preserves_floating_milliseconds_and_rejects_offset_or_ambiguous_formats(self):
        self.assertIsNone(civil_time("2026-09-01T12:00:00.123").tzinfo)
        for value in ("2026-09-01", "2026-09-01T12:00:00Z", "2026-09-01T12:00:00+10:00", "2026-02-30T12:00:00", "09/01/2026 12:00"):
            with self.subTest(value=value), self.assertRaises(InputError): civil_time(value)

    def test_manifest_validates_scope_acquisition_and_explicit_semantics(self):
        self.assertEqual(self.manifest.to_dict()["acquired_at"], "2026-10-01T14:00:00+00:00")
        for changes in (dict(cohort_end="2026-09-01T00:00:00"), dict(observed_at="2026-09-15T00:00:00"),
                        dict(acquired_at="2026-10-01T14:00:00"), dict(timestamp_semantics="UTC"), dict(source="invented"),
                        dict(completeness="probably"), dict(schema_version=True), dict(extra="ignored")):
            with self.subTest(changes=changes), self.assertRaises(InputError): Manifest.parse(metadata(**changes))

    def test_open_and_closed_classification_uses_status_and_valid_dates(self):
        self.assertEqual(normalize(record(), self.manifest).outcome, "open")
        row = normalize(record(status=" CLOSED ", closed_date="2026-09-02T12:00:00"), self.manifest)
        self.assertEqual(row.outcome, "closed")
        self.assertEqual(row.flags, ())

    def test_inconsistent_outcomes_are_retained_with_specific_quality_flags(self):
        cases = [(dict(status="Closed"), "closed_missing_date"),
                 (dict(closed_date="2026-09-02T00:00:00"), "status_date_conflict"),
                 (dict(status="Closed", closed_date="2026-08-31T00:00:00"), "negative_duration"),
                 (dict(status="Closed", closed_date="2026-10-02T00:00:00"), "future_closure"),
                 (dict(status="New Status"), "unknown_status")]
        for changes, flag in cases:
            row = normalize(record(**changes), self.manifest)
            self.assertIn(flag, row.flags); self.assertEqual(row.outcome, "unknown")

    def test_scope_and_group_quality_flags_do_not_destroy_rows(self):
        row = normalize(record(agency=None, complaint_type=None, borough="new area", created_date="2026-08-31T00:00:00"), self.manifest)
        self.assertIn("outside_cohort", row.flags); self.assertIn("missing_agency", row.flags)
        self.assertIn("missing_problem", row.flags); self.assertIn("unknown_borough", row.flags)
        scoped = Manifest.parse(metadata(agency="NYPD"))
        self.assertIn("agency_scope_mismatch", normalize(record(), scoped).flags)

    def test_rejects_unusable_identifiers_times_and_control_text_without_echo(self):
        for changes in (dict(unique_key=1001), dict(unique_key="../private"), dict(created_date=None),
                        dict(closed_date="bad"), dict(agency="private\nvalue"), dict(complaint_type="\ud800")):
            with self.subTest(changes=changes), self.assertRaises(RecordError) as raised:
                normalize(record(**changes), self.manifest)
            self.assertNotIn("private", str(raised.exception))

    def test_sensitive_unknown_fields_do_not_enter_normalized_identity(self):
        row = normalize(record(incident_address="sensitive marker", latitude="1.23", description="secret marker"), self.manifest)
        self.assertNotIn("marker", row.identity())
        self.assertNotIn("latitude", row.identity())


if __name__ == "__main__": unittest.main()

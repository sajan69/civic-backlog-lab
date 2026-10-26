import json
from pathlib import Path
import tempfile
import unittest
from civic_backlog.analysis import analyze
from civic_backlog.ingest import ingest
from civic_backlog.model import InputError, Manifest
from test_model import metadata, record


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "rows.json"; self.db = Path(self.temp.name) / "rows.duckdb"
        self.manifest = Manifest.parse(metadata(observed_at="2026-10-01T00:00:00"))

    def report(self, rows, *, manifest=None, skip=False, allow_partial=False):
        self.path.write_text(json.dumps(rows))
        imported = ingest(self.path, manifest or self.manifest, self.db, skip_invalid=skip)
        return analyze(self.db, imported["snapshot_id"], allow_partial=allow_partial)

    def test_open_cases_remain_in_horizon_denominator(self):
        report = self.report([record(created_date="2026-09-01T00:00:00", status="Closed", closed_date="2026-09-02T00:00:00"),
                              record(unique_key="1002", created_date="2026-09-01T00:00:00")])
        self.assertEqual(report["summary"]["closed_only_median_days"], 1)
        self.assertEqual(report["horizons"][0]["eligible_known"], 2)
        self.assertEqual(report["horizons"][0]["closure_fraction"], 0.5)
        self.assertEqual(report["open_age_bands"]["30_days_or_more"], 1)

    def test_recent_fast_closures_and_recent_open_cases_both_excluded_until_full_followup(self):
        report = self.report([record(created_date="2026-09-30T00:00:00", status="Closed", closed_date="2026-09-30T12:00:00"),
                              record(unique_key="1002", created_date="2026-09-30T00:00:00")])
        horizon = report["horizons"][0]
        self.assertEqual(horizon["too_recent_known"], 2); self.assertEqual(horizon["eligible_known"], 0)
        self.assertIsNone(horizon["closure_fraction"])

    def test_exact_followup_closure_and_age_boundaries_are_inclusive(self):
        report = self.report([record(created_date="2026-09-24T00:00:00", status="Closed", closed_date="2026-10-01T00:00:00"),
                              record(unique_key="1002", created_date="2026-09-24T00:00:00")])
        self.assertEqual(report["horizons"][0]["eligible_known"], 2)
        self.assertEqual(report["horizons"][0]["closed_within_horizon"], 1)
        self.assertEqual(report["open_age_bands"]["7_to_under_30_days"], 1)

    def test_unknown_outcomes_are_counted_not_relabelled_as_open(self):
        report = self.report([record(status="Closed"), record(unique_key="1002", status="Closed", closed_date="2026-08-31T00:00:00")])
        self.assertEqual(report["summary"]["unknown_outcome_count"], 2)
        self.assertEqual(report["summary"]["open_count"], 0)
        self.assertEqual(report["horizons"][0]["unknown_outcome_excluded"], 2)
        self.assertIsNone(report["summary"]["closed_only_median_days"])

    def test_cohort_end_is_exclusive_and_agency_scope_is_literal_bound_data(self):
        manifest = Manifest.parse(metadata(agency="DOT", observed_at="2026-10-01T00:00:00"))
        report = self.report([record(), record(unique_key="1002", agency="NYPD"),
                              record(unique_key="1003", created_date="2026-10-01T00:00:00")], manifest=manifest)
        self.assertEqual(report["summary"]["cohort_rows"], 1)
        self.assertEqual(report["summary"]["retained_rows_outside_scope"], 2)
        malicious = Manifest.parse(metadata(agency="x' OR 1=1 --"))
        report = self.report([record()], manifest=malicious)
        self.assertEqual(report["summary"]["cohort_rows"], 0)

    def test_empty_snapshot_has_zero_counts_and_undefined_fractions(self):
        report = self.report([])
        self.assertEqual(report["summary"]["cohort_rows"], 0)
        self.assertTrue(all(row["eligible_known"] == 0 and row["closure_fraction"] is None for row in report["horizons"]))
        self.assertEqual(sum(report["open_age_bands"].values()), 0)

    def test_partial_or_skipped_input_requires_explicit_analysis_opt_in(self):
        for completeness in ("unknown", "truncated"):
            with self.subTest(completeness=completeness), self.assertRaisesRegex(InputError, "partial_snapshot"):
                self.report([record()], manifest=Manifest.parse(metadata(completeness=completeness)))
        with self.assertRaisesRegex(InputError, "partial_snapshot"):
            self.report([record(), record(unique_key="bad")], skip=True)
        report = self.report([record()], manifest=Manifest.parse(metadata(completeness="truncated")), allow_partial=True)
        self.assertIn("partial_input_not_a_population_estimate", report["warnings"])

    def test_distinct_observations_keep_their_own_statuses(self):
        first = self.report([record()]); second = self.report([record(status="Closed", closed_date="2026-09-02T00:00:00")])
        again = analyze(self.db, first["snapshot"]["snapshot_id"])
        self.assertEqual(again["summary"]["open_count"], 1)
        self.assertEqual(second["summary"]["closed_count"], 1)

    def test_excessive_group_output_refuses_instead_of_silently_truncating(self):
        rows = [record(unique_key=str(1000 + n), agency=f'AGENCY_{n}') for n in range(201)]
        with self.assertRaisesRegex(InputError, 'too_many_agency_groups'):
            self.report(rows)


if __name__ == '__main__': unittest.main()

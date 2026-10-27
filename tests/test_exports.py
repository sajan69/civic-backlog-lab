import csv
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from civic_backlog.analysis import analyze
from civic_backlog.demo import generate
from civic_backlog.exports import export_report, render_report
from civic_backlog.ingest import ingest, read_manifest
from civic_backlog.model import InputError, Manifest
from test_model import metadata, record


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); fixture=self.root/'fixture'; generate(fixture)
        self.db=self.root/'db.duckdb'
        self.snapshot=ingest(fixture/'requests.json',read_manifest(fixture/'manifest.json'),self.db)['snapshot_id']
        self.report=analyze(self.db,self.snapshot)

    def test_json_preserves_full_aggregate_provenance_and_metrics_without_requests(self):
        path=self.root/'report.json'; export_report(self.db,self.snapshot,path,'json')
        report=json.loads(path.read_text()); self.assertEqual(report['summary']['cohort_rows'],12)
        self.assertEqual(report['snapshot']['snapshot_id'],self.snapshot)
        self.assertEqual(report['horizons'][0]['closure_fraction'],0.4)
        self.assertNotIn('requests',report)
        if os.name!='nt': self.assertEqual(path.stat().st_mode & 0o777,0o600)

    def test_csv_has_coverage_time_and_snapshot_context_on_every_metric(self):
        payload=render_report(self.report,'csv').decode()
        rows=list(csv.DictReader(io.StringIO(payload)))
        self.assertTrue(rows); self.assertTrue(all(row['snapshot_id']==self.snapshot for row in rows))
        ratio=next(row for row in rows if row['section']=='horizon' and row['group']=='7' and row['metric']=='closure_fraction')
        self.assertEqual(ratio['value'],'0.4'); self.assertEqual(ratio['duration_unit'],'floating_calendar_clock_days')
        self.assertIn('unknown_outcomes_excluded',ratio['warning_codes'])

    def test_formula_like_group_labels_become_literal_in_csv_but_json_preserves_them(self):
        for group in ('=1+1',' +SUM(1,2)','-DANGEROUS','@formula','＝1+1'):
            self.report['by_agency'][0]['agency']=group
            rows=list(csv.DictReader(io.StringIO(render_report(self.report,'csv').decode())))
            self.assertTrue(all(row['group'].startswith("'") for row in rows if row['section']=='agency' and row['group'].endswith(group)))
            self.assertEqual(json.loads(render_report(self.report,'json'))['by_agency'][0]['agency'],group)

    def test_existing_files_and_symlinks_are_never_overwritten(self):
        path=self.root/'report.json'; path.write_text('original')
        with self.assertRaisesRegex(InputError,'output_exists'): export_report(self.db,self.snapshot,path,'json')
        self.assertEqual(path.read_text(),'original')
        if os.name!='nt':
            link=self.root/'link.json'; link.symlink_to(path)
            with self.assertRaisesRegex(InputError,'output_exists'): export_report(self.db,self.snapshot,link,'json')
            self.assertEqual(path.read_text(),'original')

    def test_size_and_row_limits_refuse_output_instead_of_truncating(self):
        with patch('civic_backlog.exports.MAX_EXPORT_ROWS',1), self.assertRaisesRegex(InputError,'export_row_limit'):
            render_report(self.report,'csv')
        path=self.root/'too-big.json'
        with patch('civic_backlog.exports.MAX_EXPORT_BYTES',1), self.assertRaisesRegex(InputError,'export_byte_limit'):
            export_report(self.db,self.snapshot,path,'json')
        self.assertFalse(path.exists())

    def test_partial_input_requires_opt_in_for_exports_too(self):
        path=self.root/'rows.json'; path.write_text(json.dumps([record()]))
        context=Manifest.parse(metadata(completeness='truncated'))
        snapshot=ingest(path,context,self.db)['snapshot_id']; out=self.root/'partial.json'
        with self.assertRaisesRegex(InputError,'partial_snapshot'): export_report(self.db,snapshot,out,'json')
        self.assertFalse(out.exists())
        export_report(self.db,snapshot,out,'json',allow_partial=True)
        self.assertIn('partial_input_not_a_population_estimate',json.loads(out.read_text())['warnings'])


if __name__=='__main__': unittest.main()

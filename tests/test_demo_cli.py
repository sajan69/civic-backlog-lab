import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from civic_backlog.demo import generate, run_demo
from civic_backlog.model import InputError


class DemoTests(unittest.TestCase):
    def test_synthetic_fixture_checks_exact_denominators_and_quality_exclusions(self):
        result = run_demo()
        self.assertEqual(result['summary']['closed_only_median_days'], 1.5)
        self.assertEqual(result['horizons'][0]['closure_fraction'], 0.4)
        self.assertEqual(result['horizons'][1]['closure_fraction'], 2 / 3)
        self.assertEqual(result['summary']['unknown_outcome_count'], 5)
        self.assertEqual(result['verified_reimport_inserted_rows'], 0)

    def test_generator_never_overwrites_existing_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / 'fixture'; generate(out)
            original = (out / 'requests.json').read_bytes()
            with self.assertRaisesRegex(InputError, 'output_directory_exists'): generate(out)
            self.assertEqual((out / 'requests.json').read_bytes(), original)

    def test_installed_cli_generate_ingest_analyze_and_info_are_reproducible(self):
        def command(*args):
            result = subprocess.run([sys.executable, '-m', 'civic_backlog.cli', *map(str, args)], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); fixture = root / 'fixture'; db = root / 'records.duckdb'
            command('generate', '--out', fixture)
            imported = command('ingest', fixture / 'requests.json', '--manifest', fixture / 'manifest.json', '--db', db)
            snapshot = imported['snapshot_id']
            report = command('analyze', '--db', db, '--snapshot', snapshot)
            self.assertEqual(report['summary']['cohort_rows'], 12)
            self.assertEqual(command('info', '--db', db, '--snapshot', snapshot)['row_count'], 13)
            self.assertEqual(len(command('snapshots', '--db', db)), 1)

    def test_cli_failure_does_not_echo_bad_source_values_or_filesystem_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-m', 'civic_backlog.cli', 'info', '--db', str(Path(directory) / 'private-marker.duckdb'),
                                     '--snapshot', 'private-value'], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn('private', result.stderr); self.assertNotIn('Traceback', result.stderr)


if __name__ == '__main__': unittest.main()

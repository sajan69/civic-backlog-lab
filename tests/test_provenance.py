import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from civic_backlog.model import Manifest, InputError
from civic_backlog.provenance import ENDPOINT, FIELDS, PROTOCOL, source_query
from civic_backlog.ingest import ingest
from test_model import metadata, record


def acquisition(payload=b'[]', rows=0):
    context = Manifest.parse(metadata(agency='DOT', source='nyc311'))
    return dict(protocol=PROTOCOL, endpoint=ENDPOINT, query=source_query(context.cohort_start, context.cohort_end, 'DOT'),
                page_size=1000, row_limit=20000, pages=[] if rows == 0 else [dict(offset=0, rows=rows, sha256='a'*64)],
                source_count_before=rows, source_count_after=rows, source_updated_before=1000, source_updated_after=1000,
                network_requests=4 if rows == 0 else 5, capture_started_at='2026-10-01T14:00:00+00:00',
                capture_finished_at='2026-10-01T14:00:01+00:00', termination='count_bound', consistency='stable_checks',
                observation_clock='America/New_York_publisher_assumption', rows_written=rows,
                field_types={name: 'calendar_date' if name.endswith('_date') else 'text' for name in FIELDS},
                payload_sha256=hashlib.sha256(payload).hexdigest())


class ProvenanceTests(unittest.TestCase):
    def test_old_manifest_serialization_is_unchanged_without_extension(self):
        context = Manifest.parse(metadata())
        self.assertNotIn('acquisition', context.to_dict())
        self.assertEqual(context.to_dict()['completeness_basis'], 'caller_declared')

    def test_acquisition_requires_fixed_endpoint_and_context_bound_query(self):
        original = acquisition()
        for change in ({'endpoint': 'https://untrusted.invalid'}, {'query': {'$where': "agency='other'"}},
                       {'row_limit': 20001}, {'network_requests': 99}, {'extra': 'private'},
                       {'field_types': {}}, {'source_updated_before': True}):
            value = copy.deepcopy(original); value.update(change)
            with self.subTest(change=change), self.assertRaises(InputError):
                Manifest.parse(metadata(source='nyc311', agency='DOT', acquisition=value))

    def test_nested_metadata_is_copied_and_not_claimed_authenticated(self):
        value = acquisition(); context = Manifest.parse(metadata(source='nyc311', agency='DOT', acquisition=value))
        value['query']['$where'] = 'mutated'
        self.assertNotEqual(context.to_dict()['acquisition']['query']['$where'], 'mutated')
        self.assertEqual(context.to_dict()['completeness_basis'], 'recorded_paged_checks_unattested')

    def test_mismatched_payload_never_creates_database(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'rows.json'; db = Path(directory) / 'rows.duckdb'
            payload = json.dumps([record()]).encode(); path.write_bytes(payload)
            context = Manifest.parse(metadata(source='nyc311', agency='DOT', acquisition=acquisition(payload, 1)))
            self.assertEqual(ingest(path, context, db)['inserted_rows'], 1)
            path.write_bytes(b'[]')
            with self.assertRaisesRegex(InputError, 'acquisition_payload_mismatch'): ingest(path, context, db)

    def test_collector_query_refuses_agency_injection(self):
        context = Manifest.parse(metadata())
        with self.assertRaises(ValueError): source_query(context.cohort_start, context.cohort_end, "DOT' OR 1=1")

    def test_complete_declaration_cannot_contradict_changed_acquisition_checks(self):
        value = acquisition(); value['source_updated_after'] = 1001; value['consistency'] = 'changed_or_unchecked'
        with self.assertRaisesRegex(InputError, 'invalid_acquisition_metadata'):
            Manifest.parse(metadata(source='nyc311', agency='DOT', acquisition=value))
        context = Manifest.parse(metadata(source='nyc311', agency='DOT', completeness='unknown', acquisition=value))
        self.assertEqual(context.completeness, 'unknown')


if __name__ == '__main__': unittest.main()

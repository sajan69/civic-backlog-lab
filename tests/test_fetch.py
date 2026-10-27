from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit
from civic_backlog.fetch import fetch_snapshot, METADATA_URL, SourceClient, NoRedirect
from civic_backlog.ingest import read_manifest, ingest
from civic_backlog.model import FIELDS, InputError
from test_model import record


class FakeClient:
    def __init__(self, rows=None, *, changed=False, types_changed=False):
        self.rows = rows if rows is not None else [record(unique_key=str(1000+n)) for n in range(5)]
        self.requests = 0; self.urls = []; self.changed = changed; self.types_changed = types_changed; self.meta_calls = 0
    def get_json(self, url):
        self.requests += 1; self.urls.append(url)
        if url == METADATA_URL:
            self.meta_calls += 1
            columns = [{'fieldName': name, 'dataTypeName': 'calendar_date' if name.endswith('_date') else 'text'} for name in FIELDS]
            if self.types_changed: columns[0]['dataTypeName'] = 'number'
            result = {'id': 'erm2-nwe9', 'rowsUpdatedAt': 1000 + int(self.changed and self.meta_calls > 1), 'columns': columns}
        else:
            query = parse_qs(urlsplit(url).query)
            if query['$select'] == ['count(*) AS total']: result = [{'total': str(len(self.rows))}]
            else:
                offset = int(query['$offset'][0]); limit = int(query['$limit'][0]); result = self.rows[offset:offset+limit]
        raw = json.dumps(result).encode()
        return result, hashlib.sha256(raw).hexdigest()


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name) / 'snapshot'
        self.clock = lambda: datetime(2026, 10, 1, 14, tzinfo=timezone.utc)
    def fetch(self, **kwargs):
        return fetch_snapshot(self.out, '2026-09-01', '2026-09-02', 'DOT', clock=self.clock, **kwargs)

    def test_pages_projected_rows_records_query_and_imports_hash_bound_payload(self):
        rows = [record(unique_key=str(1000+n), incident_address='private-marker') for n in range(5)]
        client = FakeClient(rows); result = self.fetch(client=client, page_size=2)
        self.assertEqual(result['rows_written'], 5); self.assertEqual(result['completeness'], 'complete')
        self.assertEqual(client.requests, 7)
        manifest = read_manifest(self.out / 'manifest.json')
        self.assertEqual([p['offset'] for p in manifest.acquisition['pages']], [0, 2, 4])
        self.assertNotIn('private-marker', (self.out / 'requests.json').read_text())
        self.assertEqual(ingest(self.out / 'requests.json', manifest, Path(self.temp.name) / 'db.duckdb')['inserted_rows'], 5)
        for url in client.urls[2:-2]:
            query = parse_qs(urlsplit(url).query); self.assertEqual(query['$order'], ['unique_key ASC'])
            self.assertNotIn('incident_address', query['$select'][0])

    def test_row_and_page_caps_are_explicit_truncated_captures(self):
        result = self.fetch(client=FakeClient(), row_limit=3, page_size=2)
        self.assertEqual(result['rows_written'], 3); self.assertEqual(result['completeness'], 'truncated')
        other = Path(self.temp.name) / 'pages'
        rows = [record(unique_key=str(1000+n)) for n in range(30)]
        result = fetch_snapshot(other, '2026-09-01', '2026-09-02', 'DOT', client=FakeClient(rows), page_size=1, clock=self.clock)
        self.assertEqual(result['rows_written'], 20); self.assertEqual(result['network_requests'], 24)
        self.assertEqual(result['completeness'], 'truncated')

    def test_source_changes_are_unknown_not_proven_complete(self):
        result = self.fetch(client=FakeClient(changed=True))
        self.assertEqual(result['completeness'], 'unknown'); self.assertEqual(result['consistency'], 'changed_or_unchecked')

    def test_schema_change_bad_order_and_wrong_scope_fail_before_output(self):
        for client in (FakeClient(types_changed=True), FakeClient([record(unique_key='1002'), record(unique_key='1001')]),
                       FakeClient([record(agency='NYPD')])):
            with self.subTest(client=client), self.assertRaises(InputError): self.fetch(client=client)
            self.assertFalse(self.out.exists())

    def test_invalid_window_agency_and_limits_do_not_make_requests(self):
        client = FakeClient()
        for start,end,agency in [('2026-09-01','2026-09-09','DOT'), ('2026-09-01','2026-09-02',"DOT' OR 1=1"),
                                 ('2026-09-01Z','2026-09-02','DOT'), ('2027-09-01','2027-09-02','DOT')]:
            with self.subTest(start=start), self.assertRaises(InputError):
                fetch_snapshot(self.out, start, end, agency, client=client, clock=self.clock)
        with self.assertRaises(InputError): self.fetch(client=client, row_limit=20001)
        self.assertEqual(client.requests, 0)

    def test_existing_directory_and_unsafe_urls_are_never_used(self):
        self.out.mkdir(); client = FakeClient()
        with self.assertRaises(InputError): self.fetch(client=client)
        self.assertEqual(client.requests, 0)
        transport = SourceClient()
        for url in ('http://data.cityofnewyork.us/resource/erm2-nwe9.json', 'https://untrusted.invalid/resource/erm2-nwe9.json',
                    'https://data.cityofnewyork.us/private', 'https://user:password@data.cityofnewyork.us/resource/erm2-nwe9.json'):
            with self.subTest(url=url), self.assertRaises(InputError): transport.get_json(url)
        self.assertEqual(transport.requests, 0)
        with self.assertRaisesRegex(InputError, 'redirect'): NoRedirect().redirect_request(None,None,302,'',{},'https://untrusted.invalid')

    def test_empty_result_is_a_checked_zero_row_capture(self):
        result = self.fetch(client=FakeClient([]))
        self.assertEqual(result['rows_written'], 0); self.assertEqual(result['network_requests'], 4)
        self.assertEqual(result['completeness'], 'complete')


class TransportTests(unittest.TestCase):
    def test_packaged_timezone_data_supports_hosts_without_system_iana_files(self):
        import zoneinfo
        original = zoneinfo.TZPATH
        try:
            zoneinfo.reset_tzpath(())
            zoneinfo.ZoneInfo.clear_cache()
            local = datetime(2026,10,1,14,tzinfo=timezone.utc).astimezone(zoneinfo.ZoneInfo('America/New_York'))
            self.assertEqual(local.hour,10)
        finally:
            zoneinfo.reset_tzpath(original)
            zoneinfo.ZoneInfo.clear_cache()

    def test_transport_bounds_body_bytes_and_request_budget(self):
        from unittest.mock import patch
        class Response:
            status = 200
            headers = {'Content-Type': 'application/json'}
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, limit): return b'[' + b' ' * 20 + b']'
        client = SourceClient()
        with patch.object(client.opener, 'open', return_value=Response()), patch('civic_backlog.fetch.MAX_RESPONSE_BYTES', 5):
            with self.assertRaisesRegex(InputError, 'source_response_limit'): client.get_json(METADATA_URL)
        client.requests = 24
        with self.assertRaisesRegex(InputError, 'source_request_limit'): client.get_json(METADATA_URL)

    def test_transport_refuses_html_and_sanitizes_rate_limits_and_network_errors(self):
        from unittest.mock import patch
        from urllib.error import HTTPError, URLError
        class Response:
            status = 200
            headers = {'Content-Type': 'text/html'}
            def __enter__(self): return self
            def __exit__(self, *args): pass
        client = SourceClient()
        with patch.object(client.opener, 'open', return_value=Response()), self.assertRaisesRegex(InputError, 'source_content_type'):
            client.get_json(METADATA_URL)
        for error, code in ((HTTPError(METADATA_URL, 429, 'private detail', {}, None), 'source_rate_limited'),
                            (URLError('private detail'), 'source_unavailable')):
            with patch.object(client.opener, 'open', side_effect=error), self.assertRaisesRegex(InputError, code) as caught:
                client.get_json(METADATA_URL)
            self.assertNotIn('private', str(caught.exception))

    def test_capture_clock_requires_an_explicit_timezone(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(InputError, 'invalid_capture_clock'):
                fetch_snapshot(Path(directory)/'out', '2026-09-01','2026-09-02','DOT', client=FakeClient(), clock=lambda: datetime(2026,10,1))

if __name__ == '__main__': unittest.main()

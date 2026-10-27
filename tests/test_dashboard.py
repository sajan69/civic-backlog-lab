import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from civic_backlog.dashboard import create_server
from civic_backlog.demo import generate
from civic_backlog.ingest import ingest, read_manifest
from civic_backlog.model import InputError


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name); fixture = root/'fixture'; generate(fixture)
        self.db = root/'data.duckdb'
        self.id = ingest(fixture/'requests.json', read_manifest(fixture/'manifest.json'), self.db)['snapshot_id']
        self.before = self.db.read_bytes()
        self.server = create_server(self.db, self.id)
        self.token = self.server.access_url.split('#')[1]
        self.thread = threading.Thread(target=self.server.serve_forever); self.thread.start()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.server.shutdown(); self.thread.join(); self.server.server_close(); self.tmp.cleanup()

    def request(self, path, headers=None, method='GET'):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        conn.request(method, path, headers=headers or {})
        response = conn.getresponse(); result = response.status, dict(response.getheaders()), response.read()
        conn.close(); return result

    def test_unauthorized_data_is_never_returned_and_token_is_not_in_assets(self):
        for path in ('/api/report','/download/report.csv','/download/report.json'):
            self.assertEqual(self.request(path)[0],401)
            self.assertEqual(self.request(path, {'X-Civic-Token':'wrong'})[0],401)
        for path in ('/','/app.js','/style.css'):
            status, headers, body = self.request(path)
            self.assertEqual(status,200); self.assertNotIn(self.token.encode(),body)
            self.assertEqual(headers['Cache-Control'],'no-store')
            self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy'])
            self.assertNotIn('Access-Control-Allow-Origin',headers)

    def test_host_origin_routes_and_writes_are_rejected(self):
        auth={'X-Civic-Token':self.token}
        for headers in ({**auth,'Host':'attacker.invalid'}, {**auth,'Origin':'https://attacker.invalid'}, {**auth,'Content-Length':'1'}):
            self.assertIn(self.request('/api/report',headers)[0],(400,403))
        for path in ('/api/report?db=private','/../pyproject.toml','/manifest.json'):
            self.assertEqual(self.request(path,auth)[0],404)
        for method in ('POST','PUT','DELETE','PATCH','OPTIONS','HEAD'):
            self.assertEqual(self.request('/api/report',auth,method)[0],405)

    def test_downloads_equal_frozen_report_and_db_remains_unchanged(self):
        auth={'X-Civic-Token':self.token}
        status, _, body=self.request('/api/report',auth)
        self.assertEqual(status,200); self.assertEqual(json.loads(body)['summary']['cohort_rows'],12)
        self.assertEqual(self.request('/download/report.json',auth)[2],body)
        status, headers, csv=self.request('/download/report.csv',auth)
        self.assertEqual(status,200); self.assertEqual(headers['Content-Disposition'],'attachment; filename="report.csv"')
        self.assertIn(b'eligible_known',csv); self.assertEqual(self.db.read_bytes(),self.before)

    def test_duplicate_auth_headers_fail_closed(self):
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        conn.putrequest('GET','/api/report'); conn.putheader('X-Civic-Token',self.token); conn.putheader('X-Civic-Token',self.token);conn.endheaders()
        response=conn.getresponse();self.assertEqual(response.status,401);response.read();conn.close()

    def test_validation_occurs_before_server_listens(self):
        for port in (-1,65536,True):
            with self.assertRaisesRegex(InputError,'invalid_dashboard_port'):create_server(self.db,self.id,port=port)

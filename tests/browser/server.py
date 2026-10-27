"""Synthetic installed-package browser fixture; no network/source data."""
import json
from pathlib import Path
import tempfile
from civic_backlog.demo import generate
from civic_backlog.ingest import ingest, read_manifest
from civic_backlog.dashboard import create_server

with tempfile.TemporaryDirectory() as directory:
    root=Path(directory); fixture=root/'fixture'; generate(fixture)
    path=fixture/'requests.json'; rows=json.loads(path.read_text())
    rows[0]['agency']='<img src=x onerror=alert(1)>'
    rows[1]['agency']='=SUM(1,1)'
    path.write_text(json.dumps(rows))
    result=ingest(path,read_manifest(fixture/'manifest.json'),root/'test.duckdb')
    server=create_server(root/'test.duckdb',result['snapshot_id'])
    print(server.access_url,flush=True)
    try: server.serve_forever()
    finally: server.server_close()

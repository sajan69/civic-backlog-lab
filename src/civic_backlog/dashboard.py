"""Read-only, loopback-only view of one precomputed aggregate snapshot."""

from hmac import compare_digest
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib.resources import files
import secrets
from .analysis import analyze
from .exports import render_report
from .model import InputError


class DashboardServer(HTTPServer):
    allow_reuse_address = False
    request_queue_size = 8

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(2)
        return connection, address

    def handle_error(self, request, client_address):
        # No request headers, tokens, payloads or local paths in logs.
        pass


def create_server(db, snapshot_id, *, port=0, allow_partial=False):
    if type(port) is not int or not 0 <= port <= 65535:
        raise InputError('invalid_dashboard_port')
    report = analyze(db, snapshot_id, allow_partial=allow_partial)
    # Freeze both downloads before accepting connections; no request can query SQL.
    payloads = {'/api/report': (render_report(report, 'json'), 'application/json', None),
                '/download/report.json': (render_report(report, 'json'), 'application/json', 'report.json'),
                '/download/report.csv': (render_report(report, 'csv'), 'text/csv; charset=utf-8', 'report.csv')}
    token = secrets.token_urlsafe(32)
    assets = {'/': ('index.html', 'text/html; charset=utf-8'),
              '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
              '/style.css': ('style.css', 'text/css; charset=utf-8')}
    for path, (name, content_type) in assets.items():
        payloads[path] = (files('civic_backlog').joinpath('static', name).read_bytes(), content_type, None)

    class Handler(BaseHTTPRequestHandler):
        server_version = 'CivicLocal'
        sys_version = ''

        def log_message(self, *args): pass

        def _reply(self, status, payload=b'', content_type='text/plain; charset=utf-8', filename=None):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
            self.send_header('Connection', 'close')
            if filename: self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
            self.end_headers()
            self.close_connection = True
            if self.command != 'HEAD': self.wfile.write(payload)

        def do_GET(self):
            host = f'127.0.0.1:{self.server.server_port}'
            if self.headers.get_all('Host') != [host] or self.headers.get_all('Origin') not in (None, [f'http://{host}']):
                return self._reply(403)
            if self.headers.get('Transfer-Encoding') is not None or self.headers.get('Content-Length') not in (None, '0'):
                return self._reply(400)
            if len(self.path) > 256 or self.path not in payloads:
                return self._reply(404)
            if self.path not in assets:
                values = self.headers.get_all('X-Civic-Token')
                if not values or len(values) != 1 or len(values[0]) > 128 or not compare_digest(values[0].encode(), token.encode()):
                    return self._reply(401)
            self._reply(200, *payloads[self.path])

        def do_POST(self): self._reply(405)
        do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_HEAD = do_POST

    server = DashboardServer(('127.0.0.1', port), Handler)
    server.access_url = f'http://127.0.0.1:{server.server_port}/#{token}'
    return server


def serve(db, snapshot_id, *, port=0, allow_partial=False):
    server = create_server(db, snapshot_id, port=port, allow_partial=allow_partial)
    print(server.access_url, flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()

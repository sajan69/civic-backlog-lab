"""Credential-free, fixed-host legacy SODA reader for bounded agency cohorts."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo
from .ingest import MAX_BYTES, MAX_ROWS, load_json
from .model import FIELDS, InputError, Manifest, normalize
from .provenance import ENDPOINT, PROTOCOL, source_query

METADATA_URL = 'https://data.cityofnewyork.us/api/views/erm2-nwe9.json'
MAX_PAGES = 20
MAX_REQUESTS = 24
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_NETWORK_BYTES = 16 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise InputError('source_redirect_refused')


class SourceClient:
    def __init__(self):
        self.requests = 0
        self.received_bytes = 0
        self.opener = urllib.request.build_opener(NoRedirect())

    def get_json(self, url: str) -> tuple[object, str]:
        target = urllib.parse.urlsplit(url)
        if target.scheme != 'https' or target.netloc != 'data.cityofnewyork.us' or target.fragment or target.path not in (
                '/api/views/erm2-nwe9.json', '/resource/erm2-nwe9.json'):
            raise InputError('source_url_refused')
        if self.requests >= MAX_REQUESTS:
            raise InputError('source_request_limit')
        self.requests += 1
        request = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'civic-backlog-lab/0.1'})
        try:
            with self.opener.open(request, timeout=15) as response:
                if response.status != 200:
                    raise InputError('source_http_failure')
                content_type = response.headers.get('Content-Type', '').split(';', 1)[0].strip().lower()
                if content_type not in ('application/json', 'application/vnd.socrata.soda2+json'):
                    raise InputError('source_content_type')
                remaining = min(MAX_RESPONSE_BYTES, MAX_NETWORK_BYTES - self.received_bytes)
                raw = response.read(remaining + 1)
                self.received_bytes += len(raw)
                if len(raw) > remaining:
                    raise InputError('source_response_limit')
        except urllib.error.HTTPError as error:
            code = error.code
            error.close()
            raise InputError('source_rate_limited' if code == 429 else 'source_http_failure') from None
        except (OSError, TimeoutError):
            raise InputError('source_unavailable') from None
        try:
            return load_json(raw.decode('utf8')), hashlib.sha256(raw).hexdigest()
        except UnicodeError:
            raise InputError('source_invalid_utf8') from None


def _metadata(client) -> dict:
    value, _digest = client.get_json(METADATA_URL)
    if not isinstance(value, dict) or value.get('id') != 'erm2-nwe9' or not isinstance(value.get('columns'), list):
        raise InputError('source_metadata_invalid')
    types = {}
    for column in value['columns']:
        if not isinstance(column, dict): raise InputError('source_metadata_invalid')
        name = column.get('fieldName')
        if name in FIELDS:
            if name in types: raise InputError('source_schema_changed')
            types[name] = column.get('dataTypeName')
    if set(types) != set(FIELDS): raise InputError('source_schema_changed')
    for name, kind in types.items():
        expected = ('calendar_date', 'floating_timestamp') if name.endswith('_date') else ('text',)
        if kind not in expected: raise InputError('source_schema_changed')
    updated = value.get('rowsUpdatedAt')
    if updated is not None and (type(updated) is not int or updated < 0): raise InputError('source_metadata_invalid')
    return {'updated': updated, 'field_types': types}


def _count(client, query):
    value, _digest = client.get_json(ENDPOINT + '?' + urllib.parse.urlencode({'$select': 'count(*) AS total', '$where': query['$where']}))
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict): raise InputError('source_count_invalid')
    total = value[0].get('total')
    if not isinstance(total, str) or not re.fullmatch('[0-9]{1,10}', total) or int(total) > 1_000_000_000:
        raise InputError('source_count_invalid')
    return int(total)


def _date(value: str) -> datetime:
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value): raise InputError('invalid_fetch_date')
    try: return datetime.strptime(value, '%Y-%m-%d')
    except ValueError: raise InputError('invalid_fetch_date') from None


def fetch_snapshot(out, start: str, end: str, agency: str, *, row_limit=MAX_ROWS, page_size=1000, client=None, clock=None) -> dict:
    start_time, end_time = _date(start), _date(end)
    agency = agency.upper() if isinstance(agency, str) else ''
    if not start_time < end_time <= start_time + timedelta(days=7): raise InputError('fetch_window_must_be_1_to_7_days')
    if type(row_limit) is not int or not 1 <= row_limit <= MAX_ROWS or type(page_size) is not int or not 1 <= page_size <= 1000:
        raise InputError('invalid_fetch_limits')
    try: query = source_query(start_time, end_time, agency)
    except ValueError: raise InputError('invalid_agency_code') from None
    out = Path(out)
    if out.exists() or out.is_symlink(): raise InputError('output_directory_exists')
    clock = clock or (lambda: datetime.now(timezone.utc))
    began = clock()
    if not isinstance(began, datetime) or began.tzinfo is None: raise InputError('invalid_capture_clock')
    began = began.astimezone(timezone.utc)
    observed_start = began.astimezone(ZoneInfo('America/New_York')).replace(tzinfo=None)
    if end_time > observed_start: raise InputError('fetch_window_is_in_future')
    client = client or SourceClient()
    initial_requests = client.requests
    before = _metadata(client); count_before = _count(client, query)
    rows = []; pages = []; last_key = None; termination = 'count_bound'
    while len(rows) < count_before:
        if len(rows) >= row_limit: termination = 'row_limit'; break
        if len(pages) >= MAX_PAGES: termination = 'page_limit'; break
        limit = min(page_size, row_limit - len(rows))
        url = ENDPOINT + '?' + urllib.parse.urlencode({**query, '$limit': limit, '$offset': len(rows)})
        page, digest = client.get_json(url)
        if not isinstance(page, list) or len(page) > limit: raise InputError('source_page_invalid')
        offset = len(rows)
        for item in page:
            if not isinstance(item, dict): raise InputError('source_page_invalid')
            key = item.get('unique_key')
            if not isinstance(key, str) or not re.fullmatch('[0-9]{1,32}', key) or (last_key is not None and key <= last_key):
                raise InputError('source_identity_or_order_changed')
            last_key = key
            rows.append({name: item.get(name) for name in FIELDS})
        pages.append({'offset': offset, 'rows': len(page), 'sha256': digest})
        if len(page) < limit: termination = 'exhausted'; break
    count_after = _count(client, query); after = _metadata(client)
    if before['field_types'] != after['field_types']: raise InputError('source_schema_changed')
    finished = clock()
    if not isinstance(finished, datetime) or finished.tzinfo is None: raise InputError('invalid_capture_clock')
    finished = finished.astimezone(timezone.utc)
    stable = count_before == count_after == len(rows) and before['updated'] is not None and before['updated'] == after['updated']
    completeness = 'truncated' if termination in ('row_limit', 'page_limit') else 'complete' if stable else 'unknown'
    manifest = {'schema_version': 1, 'source': 'nyc311', 'acquired_at': finished.isoformat(),
                'cohort_start': start_time.isoformat(), 'cohort_end': end_time.isoformat(),
                'observed_at': finished.astimezone(ZoneInfo('America/New_York')).replace(tzinfo=None).isoformat(timespec='milliseconds'),
                'completeness': completeness, 'timestamp_semantics': 'floating_civil', 'agency': agency}
    context = Manifest.parse(manifest)
    for item in rows:
        normalized = normalize(item, context)
        if 'outside_cohort' in normalized.flags or 'agency_scope_mismatch' in normalized.flags:
            raise InputError('source_scope_mismatch')
    payload = (json.dumps(rows, ensure_ascii=True, separators=(',', ':')) + '\n').encode()
    if len(payload) > MAX_BYTES: raise InputError('source_payload_limit')
    manifest['acquisition'] = {'protocol': PROTOCOL, 'endpoint': ENDPOINT, 'query': query,
        'page_size': page_size, 'row_limit': row_limit, 'pages': pages, 'source_count_before': count_before,
        'source_count_after': count_after, 'source_updated_before': before['updated'], 'source_updated_after': after['updated'],
        'network_requests': client.requests - initial_requests, 'capture_started_at': began.isoformat(), 'capture_finished_at': finished.isoformat(),
        'termination': termination, 'consistency': 'stable_checks' if stable else 'changed_or_unchecked',
        'observation_clock': 'America/New_York_publisher_assumption', 'field_types': before['field_types'],
        'rows_written': len(rows), 'payload_sha256': hashlib.sha256(payload).hexdigest()}
    Manifest.parse(manifest) # Validate the stored transport contract before creating output.
    try:
        out.mkdir(parents=True, mode=0o700, exist_ok=False)
        for name, content in (('requests.json', payload), ('manifest.json', (json.dumps(manifest, indent=2) + '\n').encode())):
            fd = os.open(out / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as stream: stream.write(content)
    except OSError:
        raise InputError('output_unavailable') from None
    return {'source': 'nyc311', 'rows_written': len(rows), 'completeness': completeness,
            'consistency': manifest['acquisition']['consistency'], 'network_requests': client.requests - initial_requests,
            'payload_sha256': manifest['acquisition']['payload_sha256'],
            'warning': 'Paged live-source checks are not an atomic snapshot or proof of authenticity.'}

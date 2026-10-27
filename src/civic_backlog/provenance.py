"""Bounded, unattested acquisition metadata; no request values or arbitrary URLs."""

from datetime import datetime
import json
import re

PROTOCOL = 'nyc311-soda2-paged-v1'
ENDPOINT = 'https://data.cityofnewyork.us/resource/erm2-nwe9.json'
SELECT = 'unique_key,created_date,closed_date,agency,complaint_type,status,borough'
ORDER = 'unique_key ASC'
FIELDS = tuple(SELECT.split(','))


def source_query(start: datetime, end: datetime, agency: str) -> dict:
    if not re.fullmatch(r'[A-Z0-9_-]{1,20}', agency):
        raise ValueError('invalid_agency_code')
    return {'$select': SELECT, '$where': f"created_date >= '{start.isoformat(timespec='milliseconds')}' AND created_date < '{end.isoformat(timespec='milliseconds')}' AND agency = '{agency}'", '$order': ORDER}


def validate_acquisition(value, start, end, agency) -> dict:
    keys = {'protocol', 'endpoint', 'query', 'page_size', 'row_limit', 'pages', 'source_count_before',
            'source_count_after', 'source_updated_before', 'source_updated_after', 'network_requests',
            'capture_started_at', 'capture_finished_at', 'termination', 'consistency', 'observation_clock',
            'field_types', 'rows_written', 'payload_sha256'}
    def integer(item, lower, upper):
        return type(item) is int and lower <= item <= upper
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError('invalid_acquisition_fields')
    if value['protocol'] != PROTOCOL or value['endpoint'] != ENDPOINT or value['query'] != source_query(start, end, agency):
        raise ValueError('invalid_acquisition_query')
    if not integer(value['page_size'], 1, 1000) or not integer(value['row_limit'], 1, 20000):
        raise ValueError('invalid_acquisition_limits')
    if not integer(value['rows_written'], 0, value['row_limit']) or not integer(value['network_requests'], 4, 24):
        raise ValueError('invalid_acquisition_counts')
    for name in ('source_count_before', 'source_count_after'):
        if not integer(value[name], 0, 1_000_000_000): raise ValueError('invalid_acquisition_counts')
    for name in ('source_updated_before', 'source_updated_after'):
        if value[name] is not None and not integer(value[name], 0, 999_999_999_999): raise ValueError('invalid_acquisition_update')
    if value['termination'] not in ('exhausted', 'count_bound', 'row_limit', 'page_limit') or value['consistency'] not in ('stable_checks', 'changed_or_unchecked'):
        raise ValueError('invalid_acquisition_result')
    if value['observation_clock'] != 'America/New_York_publisher_assumption':
        raise ValueError('invalid_acquisition_clock')
    for name in ('capture_started_at', 'capture_finished_at'):
        stamp = datetime.fromisoformat(value[name])
        if stamp.tzinfo is None: raise ValueError('invalid_acquisition_time')
    if datetime.fromisoformat(value['capture_finished_at']) < datetime.fromisoformat(value['capture_started_at']):
        raise ValueError('invalid_acquisition_time_order')
    field_types = value['field_types']
    if not isinstance(field_types, dict) or set(field_types) != set(FIELDS): raise ValueError('invalid_field_metadata')
    for name, kind in field_types.items():
        allowed = ('calendar_date', 'floating_timestamp') if name in ('created_date', 'closed_date') else ('text',)
        if kind not in allowed: raise ValueError('invalid_field_metadata')
    if not isinstance(value['payload_sha256'], str) or not re.fullmatch('[0-9a-f]{64}', value['payload_sha256']):
        raise ValueError('invalid_acquisition_digest')
    pages = value['pages']
    if not isinstance(pages, list) or len(pages) > 20: raise ValueError('invalid_acquisition_pages')
    offset = 0
    for page in pages:
        if not isinstance(page, dict) or set(page) != {'offset', 'rows', 'sha256'}: raise ValueError('invalid_acquisition_pages')
        if page['offset'] != offset or not integer(page['rows'], 0, value['page_size']): raise ValueError('invalid_acquisition_pages')
        if not isinstance(page['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', page['sha256']): raise ValueError('invalid_acquisition_pages')
        offset += page['rows']
    if offset != value['rows_written'] or value['network_requests'] != len(pages) + 4:
        raise ValueError('invalid_acquisition_pages')
    # Copy nested user input; it is a record of checks, not cryptographic proof of origin.
    return json.loads(json.dumps(value, allow_nan=False))

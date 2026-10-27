"""Aggregate-only JSON/CSV reports with bounded, exclusive output writes."""

import csv
import io
import json
import os
from pathlib import Path
import unicodedata
from .analysis import analyze
from .model import InputError

MAX_EXPORT_BYTES = 2 * 1024 * 1024
MAX_EXPORT_ROWS = 2000


def _cell(value):
    if value is None: return ''
    if isinstance(value, (int, float)) and not isinstance(value, bool): return str(value)
    text = str(value)
    normalized = unicodedata.normalize('NFKC', text).lstrip()
    # Preserve labels while making formula-like text literal in common spreadsheets.
    return "'" + text if normalized.startswith(('=', '+', '-', '@')) else text


def render_report(report: dict, file_format: str) -> bytes:
    if file_format == 'json':
        payload = (json.dumps(report, indent=2, ensure_ascii=True, allow_nan=False) + '\n').encode('utf8')
    elif file_format == 'csv':
        context = report['snapshot']['manifest']
        common = {'snapshot_id': report['snapshot']['snapshot_id'], 'source': context['source'],
                  'cohort_start': context['cohort_start'], 'cohort_end': context['cohort_end'],
                  'observed_at': context['observed_at'], 'completeness': context['completeness'],
                  'completeness_basis': context['completeness_basis'], 'duration_unit': report['duration_unit'],
                  'warning_codes': ';'.join(report['warnings'])}
        rows = []
        def add(section, group, metric, value):
            rows.append({'section': section, 'group': group, 'metric': metric, 'value': value, **common})
        for metric, value in report['summary'].items(): add('summary', '', metric, value)
        for horizon in report['horizons']:
            for metric, value in horizon.items():
                if metric != 'horizon_days': add('horizon', str(horizon['horizon_days']), metric, value)
        for band, count in report['open_age_bands'].items(): add('open_age_band', band, 'requests', count)
        for agency in report['by_agency']:
            for metric, value in agency.items():
                if metric != 'agency': add('agency', agency['agency'], metric, value)
        quality = report['snapshot']['quality']
        for metric in ('input_records','retained_unique','invalid_records','exact_duplicates','ignored_field_values'):
            add('quality', '', metric, quality[metric])
        for code, count in quality['flag_counts'].items(): add('quality_flag', code, 'requests', count)
        if len(rows) > MAX_EXPORT_ROWS: raise InputError('export_row_limit')
        buffer = io.StringIO(newline='')
        names = ['section', 'group', 'metric', 'value', *common]
        writer = csv.DictWriter(buffer, fieldnames=names, quoting=csv.QUOTE_ALL, lineterminator='\n')
        writer.writeheader()
        writer.writerows({name: _cell(value) for name, value in row.items()} for row in rows)
        payload = buffer.getvalue().encode('utf8')
    else:
        raise InputError('unsupported_export_format')
    if len(payload) > MAX_EXPORT_BYTES: raise InputError('export_byte_limit')
    return payload


def export_report(db, snapshot_id: str, out, file_format: str, *, allow_partial: bool = False) -> dict:
    if file_format not in ('json', 'csv'): raise InputError('unsupported_export_format')
    report = analyze(db, snapshot_id, allow_partial=allow_partial)
    payload = render_report(report, file_format)
    try:
        fd = os.open(Path(out), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream: stream.write(payload)
    except FileExistsError:
        raise InputError('output_exists') from None
    except OSError:
        raise InputError('output_unavailable') from None
    return {'snapshot_id': snapshot_id, 'format': file_format, 'bytes_written': len(payload), 'data': 'aggregate_report'}

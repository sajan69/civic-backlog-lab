"""Bounded synthetic wall-clock measurements; no public data or network."""
import hashlib
import json
import platform
from pathlib import Path
from statistics import median
import tempfile
from time import perf_counter
import duckdb
from . import __version__
from .analysis import analyze
from .ingest import ingest
from .model import InputError, Manifest


def benchmark(rows=1000, repeats=3):
    if type(rows) is not int or not 100 <= rows <= 10000 or rows % 100:
        raise InputError('benchmark_rows_must_be_multiple_of_100_between_100_and_10000')
    if type(repeats) is not int or not 1 <= repeats <= 5:
        raise InputError('benchmark_repeats_must_be_between_1_and_5')
    context = Manifest.parse({'schema_version':1,'source':'synthetic','acquired_at':'2026-10-01T04:00:00Z',
        'cohort_start':'2026-09-01T00:00:00','cohort_end':'2026-09-02T00:00:00',
        'observed_at':'2026-10-01T00:00:00','completeness':'complete','timestamp_semantics':'floating_civil'})
    records=[]
    for i in range(rows):
        status='Closed' if i%4!=2 else 'Open'
        records.append({'unique_key':str(100000+i),'created_date':'2026-09-01T00:00:00',
            'closed_date':'2026-09-02T00:00:00' if i%4 in (0,1) else None,
            'agency':f'LAB{i%5}','complaint_type':'Synthetic benchmark','status':status,'borough':'QUEENS'})
    records.extend(dict(records[i]) for i in range(0,rows,10))
    payload=(json.dumps(records,sort_keys=True,separators=(',',':'))+'\n').encode()
    measurements=[]
    with tempfile.TemporaryDirectory(prefix='civic-benchmark-') as directory:
        path=Path(directory)/'input.json';path.write_bytes(payload)
        for repeat in range(repeats):
            db=Path(directory)/f'{repeat}.duckdb'
            started=perf_counter();result=ingest(path,context,db);import_ms=(perf_counter()-started)*1000
            started=perf_counter();again=ingest(path,context,db);reimport_ms=(perf_counter()-started)*1000
            started=perf_counter();report=analyze(db,result['snapshot_id']);analysis_ms=(perf_counter()-started)*1000
            assert result['inserted_rows']==rows and result['quality']['exact_duplicates']==rows//10
            assert again['inserted_rows']==0 and again['already_present']
            s=report['summary'];assert (s['closed_count'],s['open_count'],s['unknown_outcome_count'])==(rows//2,rows//4,rows//4)
            for horizon in report['horizons']:
                assert horizon['eligible_known']==rows*3//4 and horizon['closed_within_horizon']==rows//2
            measurements.append({'repeat':repeat+1,'import_ms':round(import_ms,3),'same_snapshot_reimport_ms':round(reimport_ms,3),'analysis_ms':round(analysis_ms,3)})
    return {'workload':{'source':'synthetic','unique_rows':rows,'input_rows':len(records),'normalized_duplicates':rows//10,
                       'closed':rows//2,'open':rows//4,'unknown':rows//4,'agencies':5,'payload_bytes':len(payload),
                       'payload_sha256':hashlib.sha256(payload).hexdigest(),'repeats':repeats},
            'method':{'timer':'time.perf_counter wall clock','storage':'fresh DuckDB file per repeat in system temporary directory',
                      'import':'file read, parse, normalize, deduplicate, schema creation and transaction',
                      'same_snapshot_reimport':'file read/validation plus existing immutable snapshot lookup; zero inserted',
                      'analysis':'new read-only connection, snapshot lookup and all five aggregate SQL resources',
                      'excluded':'fixture generation, network, HTTP, browser rendering and export serialization',
                      'cache':'no explicit warmup; sequential same-process repetitions; OS caches not cleared'},
            'environment':{'python':platform.python_version(),'duckdb':duckdb.__version__,'package':__version__,
                           'platform':platform.platform(),'machine':platform.machine(),'processor':platform.processor() or 'unreported',
                           'duckdb_threads':2,'duckdb_memory_limit':'256MiB'},
            'measurements':measurements,'median_ms':{key:median(row[key] for row in measurements) for key in ('import_ms','same_snapshot_reimport_ms','analysis_ms')},
            'limitations':['Synthetic local workload; no production throughput, HTTP rate or comparative speed claim.',
                           'Shared execution host and temporary filesystem; cache, load and storage affect timings.',
                           'Correctness assertions are workload-specific; this is not a general data-quality accuracy evaluation.']}

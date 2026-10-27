# Local workload measurements

Run `civic benchmark --rows 1000 --repeats 3` after installation. It writes JSON to stdout and removes its temporary synthetic files/databases. Row counts must be multiples of 100 between 100 and 10,000; repeats are bounded to one through five. No network or credentials are used.

The [recorded run](benchmark.json), measured on 27 October 2026, contains 1,000 unique synthetic requests plus 100 exact duplicates across five agencies. The unique rows include 500 validated closures, 250 open cases and 250 closed-status/missing-date unknown outcomes. All cases have full seven-/30-day follow-up. Every repetition asserts those outcomes, the duplicate count, zero-row reimport and the eligible denominators before reporting results.

| Operation | Median wall time, three repetitions |
| --- | ---: |
| Fresh import of 1,100 input rows | 1,970.673 ms |
| Same-snapshot reimport, zero inserts | 37.482 ms |
| All aggregate queries with a new read-only connection | 29.391 ms |

The import timer includes reading, parsing, normalization, deduplication, schema creation and the database transaction. Reimport includes parsing/validation plus lookup of the already stored immutable snapshot; it is not a new import benchmark. Analysis includes snapshot metadata and all SQL resources. Fixture generation, HTTP, exports and rendering are excluded. Each repetition uses a fresh database on the system temporary filesystem. There is no explicit warmup or cache clearing.

Environment: Python 3.12.14, DuckDB 1.5.6, package 0.1.0, Linux x86_64/glibc 2.39, two DuckDB threads and a 256 MiB memory limit. The report includes individual timings, input size/hash, exact method and environment. The shared execution host and filesystem are not controlled hardware; these timings are neither a production throughput guarantee nor an improvement over an unmeasured baseline. Synthetic correctness assertions do not measure real-world data-quality accuracy.

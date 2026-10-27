# Civic Backlog Lab

A Python/SQL toolkit for analysing service-request backlogs without hiding open work behind closed-case averages. It imports immutable snapshots into DuckDB and reports data quality, open-case age bands and seven-/30-day closure fractions with explicit denominators.

## Quick start

Requires Python 3.11+. The offline demo requires no account, credentials or network access after installation.

```sh
python -m venv .venv
# macOS/Linux:
. .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e .
civic demo
```

The demo checks 13 entirely synthetic requests using a temporary database and removes its files. Of 12 requests inside the cohort, four have validated closure outcomes, three remain open and five have inconsistent/unknown outcomes. The closed-only median is 1.5 calendar-clock days, while just two of five eligible known-outcome cases closed within seven days. These are fixture checks, not findings about NYC services.

## Import and analyse

```sh
civic generate --out data/example
civic ingest data/example/requests.json --manifest data/example/manifest.json --db data/example.duckdb
civic snapshots --db data/example.duckdb
```

Pass the returned `snapshot_id` to `civic analyze --db data/example.duckdb --snapshot SNAPSHOT_ID`. Use `civic info --db data/example.duckdb --snapshot SNAPSHOT_ID` for provenance and quality counts. Analysis prints JSON; redirect stdout to save a local report.

- JSON arrays and CSV exports are bounded to 10 MiB and 20,000 input records.
- Imports are strict by default. `--skip-invalid` skips record-validation failures; broken syntax and conflicting IDs still abort.
- Normalized duplicates within a file collapse. Reimporting the same file/context inserts zero rows; changed observations remain separate snapshots.
- Only ID, creation/closure dates, agency, problem, status and borough are retained. Unknown fields such as addresses and coordinates are discarded.
- Partial/unknown-completeness inputs and imports that skipped records require `civic analyze --allow-partial`; output warns that they are not population estimates.

## Capture public data and export reports

```sh
civic fetch --start 2026-09-01 --end 2026-09-02 --agency DOT --out data/dot-capture
civic ingest data/dot-capture/requests.json --manifest data/dot-capture/manifest.json --db data/dot.duckdb
```

The credential-free collector accepts one agency and a one-to-seven-day creation window. It caps rows, pages, bytes and requests; records exact query/page hashes and before/after counts/update markers; and labels capped or changing captures. Live pagination is not an atomic snapshot. Source availability and legacy API support can change.

Create an output directory, then use the returned snapshot ID:

```sh
mkdir exports
civic export --db data/dot.duckdb --snapshot SNAPSHOT_ID --format json --out exports/report.json
civic export --db data/dot.duckdb --snapshot SNAPSHOT_ID --format csv --out exports/report.csv
```

Exports contain aggregates, coverage warnings and context. They refuse existing files and oversized reports. CSV quotes all fields and prefixes formula-like text for common spreadsheet importers; JSON preserves labels. See the [bounded DOT cohort findings](docs/PUBLIC_FINDINGS.md) for actual public-data results and limits.

## Local dashboard

```sh
civic serve --db data/example.duckdb --snapshot SNAPSHOT_ID
```

Open the full URL printed by the command. The read-only dashboard shows cohort counts, seven-/30-day eligibility and exclusions, open-case age bands, agency rows, quality warnings and provenance. JSON/CSV buttons download the full aggregate report; table filtering does not change totals or exports. Partial snapshots still require `--allow-partial` at startup.

The server binds only to `127.0.0.1`, chooses a free port by default and serves one frozen report. The URL fragment carries a temporary access token; the tab removes it from the address bar and keeps it only in memory. Reopen the printed URL after refreshing. Treat that URL as private. No uploads, collection requests, SQL endpoints or database writes are exposed. Use Ctrl-C to stop; this is a local inspection tool, not an internet-facing service.

## Metrics and limitations

Recent cases are excluded from each horizon until they have the full seven or 30 days of follow-up, including recent fast closures. Eligible open cases remain in the denominator. Inconsistent outcomes are counted separately and excluded transparently. The SQL is inspectable in [src/civic_backlog/sql](src/civic_backlog/sql).

Timestamps retain the source's floating civil-time semantics. Durations are calendar-clock days, not timezone-adjusted elapsed time or an SLA. A current-status snapshot cannot reconstruct reopenings or historical event transitions. Administrative closure does not prove the reported problem was resolved.

Local-export completeness is caller-declared. Collector metadata records bounded paging checks, not proof of an atomic or authentic source snapshot. Keep real exports and databases private and outside Git. The retained projection is data minimization, not guaranteed anonymization. Use trusted local databases and directories.

See the [input, provenance and metric contract](docs/DATA_CONTRACT.md) and [recorded synthetic output](docs/demo.json).

## Verification

```sh
python -m unittest discover -s tests -v
civic demo
```

63 tests cover parsing, time semantics, quality flags, duplicates, atomic rollback, snapshot isolation, denominator boundaries, acquisition limits/provenance, partial-input safeguards, SQL access limits, safe exports, local HTTP access controls and the CLI. CI installs the package on Python 3.11–3.13 and runs the demo. A separate Chromium job verifies dashboard controls, downloads, responsive layout and inert HTML labels. The published public-data report is limited to one agency/day. `civic benchmark --rows 1000 --repeats 3` reproduces a bounded synthetic workload; [recorded measurements](docs/MEASUREMENTS.md) include individual timings and environment. See [architecture and trust boundaries](docs/ARCHITECTURE.md). No production performance claim is made.

Source references: [NYC 311 dataset](https://data.cityofnewyork.us/Social-Services/311-Service-Requests-from-2020-to-Present/erm2-nwe9/about_data), [official reporting context](https://www.nyc.gov/site/311reporting/311-reports/service-requests.page), [Socrata floating timestamps](https://dev.socrata.com/docs/datatypes/floating_timestamp.html).

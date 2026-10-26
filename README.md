# Civic Backlog Lab

A local Python/SQL toolkit for analysing service-request backlogs without hiding open work behind closed-case averages. It imports immutable snapshots into DuckDB and reports data quality, open-case age bands and seven-/30-day closure fractions with explicit denominators.

## Quick start

Requires Python 3.11+. No account, credentials or network access is needed after installation.

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

## Metrics and limitations

Recent cases are excluded from each horizon until they have the full seven or 30 days of follow-up, including recent fast closures. Eligible open cases remain in the denominator. Inconsistent outcomes are counted separately and excluded transparently. The SQL is inspectable in [src/civic_backlog/sql](src/civic_backlog/sql).

Timestamps retain the source's floating civil-time semantics. Durations are calendar-clock days, not timezone-adjusted elapsed time or an SLA. A current-status snapshot cannot reconstruct reopenings or historical event transitions. Administrative closure does not prove the reported problem was resolved.

Completeness and acquisition metadata are caller-declared; this importer cannot verify that an export covers every request. Inputs are local files; no network collector or browser interface is included. Keep real exports and databases private and outside Git. The retained projection is data minimization, not guaranteed anonymization. Use trusted local databases and directories.

See the [input, provenance and metric contract](docs/DATA_CONTRACT.md) and [recorded synthetic output](docs/demo.json).

## Verification

```sh
python -m unittest discover -s tests -v
civic demo
```

32 tests cover parsing, time semantics, quality flags, duplicates, atomic rollback, snapshot isolation, denominator boundaries, partial-input safeguards, SQL access limits and the CLI. CI installs the package on Python 3.11–3.13 and runs the demo. No public-data findings or performance results are claimed.

Source references: [NYC 311 dataset](https://data.cityofnewyork.us/Social-Services/311-Service-Requests-from-2020-to-Present/erm2-nwe9/about_data), [official reporting context](https://www.nyc.gov/site/311reporting/311-reports/service-requests.page), [Socrata floating timestamps](https://dev.socrata.com/docs/datatypes/floating_timestamp.html).

# Input, provenance and metric contract

## Source projection

The version-one adapter retains these NYC311 API fields:

| Field | Interpretation |
| --- | --- |
| `unique_key` | Numeric-text request identifier, at most 32 digits |
| `created_date` | Required floating civil timestamp |
| `closed_date` | Optional floating civil timestamp |
| `agency` | Agency grouping label |
| `complaint_type` | Problem grouping label |
| `status` | Current source status |
| `borough` | Borough grouping label |

JSON input is an array of objects using API field names. CSV accepts those names or the public display labels Unique Key, Created Date, Closed Date, Agency, Problem, Status and Borough. The older Complaint Type label and the current metadata label Problem (formerly Complaint Type) also map to `complaint_type`. Two headers mapping to one field are refused. NYC's current display-label changes leave backend API field names unchanged, as checked on 27 October 2026: https://www.nyc.gov/opendata/news/all-news/311-Service-Requests-Updates .

Other fields are ignored and their values never enter the normalized rows or metadata. Input bytes are hashed for provenance, not stored wholesale. This is a deliberately small projection, not a complete NYC311 schema validator or an anonymization guarantee. Do not commit real raw exports, databases or person-identifying data.

The UTF-8 reader accepts an optional BOM. It caps input at 10 MiB and 20,000 records before writes. Duplicate JSON keys, nonfinite JSON constants, malformed JSON/CSV structure and conflicting normalized IDs abort even with `--skip-invalid`. Missing/unusable IDs, timestamps or bounded text can be skipped only with that flag; issues report record indices and safe codes, capped at 20 issue details. Flagged but structurally valid rows remain inspectable through quality counts.

## Required context

`civic generate` writes a working synthetic example. A local export needs a separate JSON manifest with this shape:

```json
{
  "schema_version": 1,
  "source": "local_export",
  "acquired_at": "2026-10-01T14:00:00Z",
  "cohort_start": "2026-09-01T00:00:00",
  "cohort_end": "2026-10-01T00:00:00",
  "observed_at": "2026-10-01T10:00:00",
  "completeness": "unknown",
  "timestamp_semantics": "floating_civil",
  "agency": "DOT"
}
```

`source` is synthetic, local_export or nyc311. `agency` is optional and scopes exact agency matches. The creation interval is inclusive at its start and exclusive at its end, at most 366 days long; the observation timestamp must be at or after the interval end. Records outside scope are retained with flags and excluded from cohort metrics.

`acquired_at` is an offset-aware acquisition instant normalized to UTC. It is distinct from `observed_at`, which is a floating source-clock value representing the observation used for this snapshot. The importer does not infer a timezone or validate that a supplied observation truly represents when the source was captured. Supply metadata matching the export, not an arbitrary historical date. A current export cannot establish past statuses, reopenings or an event log.

`completeness` is complete, unknown or truncated. For local exports it is explicitly **caller-declared**. A complete declaration is not an independent proof that every NYC request was included. Query scope is represented by the creation window and optional agency. An optional validated acquisition extension records collector queries/checks; it is not proof of an atomic remote snapshot or authenticated provenance. Analysis refuses unknown/truncated declarations or skipped-record imports unless `--allow-partial` is supplied; that option adds a population-estimation warning.

## Floating time

Socrata floating timestamps carry no offset. The implementation accepts `YYYY-MM-DDTHH:MM:SS` with optional one-to-three millisecond digits and refuses offset-bearing or ambiguous slash-date strings. It stores naive DuckDB TIMESTAMP values and does not convert them to UTC.

A duration is a civil-clock difference divided by 24 hours. A seven-/30-day horizon uses the same floating calendar-clock convention. Daylight-saving transitions and publisher timezone assumptions can therefore differ from true elapsed time. These are not business-hour, timezone-adjusted or SLA measurements. Reference: https://dev.socrata.com/docs/datatypes/floating_timestamp.html .

## Quality and outcomes

A known closed outcome requires status Closed, a closure date at/after creation, and no closure after observation. A known open outcome requires an active status (Open, Pending, In Progress, Started or Assigned) and no closure date. Other statuses, missing closed dates, status/date conflicts, negative durations and future closures become unknown outcomes with explicit flags. Missing grouping labels use visible unknown values rather than dropping requests. Unknown borough labels are flagged.

Unknown outcomes remain in cohort counts, with their own count and issue totals. They are excluded from time-based outcome fractions rather than assumed open or closed. This can affect representativeness; interpretation must consider the exclusion count and whether errors are systematic. `closed_count` means validated closed outcomes, not every row whose source status says Closed.

The normalized identity includes only retained fields and derived quality/outcome values. Case/whitespace normalization and discarded fields can make two source objects equivalent. Different normalized content under the same ID in one file is a conflict. Different raw files or declared context create distinct immutable snapshot IDs instead of updating a request globally.

## Storage and transaction boundaries

Each snapshot stores a SHA-256 of the original input, byte count, normalized context, adapter/projection version, record counts, flags and bounded issue details. Snapshot identity hashes the canonical context (including strict/skip policy) plus the raw-byte digest. The same bytes/context are idempotent. Raw field values outside the allowlist are not stored; hashes do not prove source authenticity.

DuckDB holds `civic_meta`, `snapshots` and `requests`; the request primary key is snapshot ID plus request ID. Schema setup and all inserts share one transaction. Parsing and duplicate validation precede database opening; failed inserts roll back snapshot metadata. Unrelated schemas and unknown schema versions are refused. Read-only commands do not create a missing database.

Connections disable external SQL access, use two DuckDB threads and a 256 MiB memory limit. All values in analytical SQL are bound parameters; user-defined SQL is not accepted. This is a single-writer local application. It does not provide encrypted storage, multi-user authorization or hostile-database sandboxing. Use private directories and inspect only trusted databases. Multiple historical snapshots do not create a verified source event history.

## Metrics

The [SQL files](../src/civic_backlog/sql) define a single-snapshot scope and the following calculations:

- Cohort rows: retained creation dates in the declared interval, not after observation, matching optional agency scope. Out-of-scope retained rows are reported separately.
- Closed-only median: calendar-clock duration among validated closed outcomes. It omits open/unknown cases and should never be interpreted as all-request service time.
- Open age bands: known open cases under seven days, seven to under 30 days, and at least 30 days old. Exact boundaries enter the older band.
- Horizon denominator: known-outcome cases with at least the full seven or 30 days between creation and observation. Both recent open cases and recent fast closures are excluded until that minimum follow-up exists.
- Horizon numerator: eligible cases with validated closure at or before their creation-plus-horizon deadline. Eligible open cases remain failures to close within that horizon. Unknown outcomes with enough follow-up have a separate exclusion count.

Zero eligible cases produce JSON null for the fraction, not zero. Agency summaries include visible unknown outcomes; more than 200 agencies refuses output rather than silently truncating. JSON output contains aggregate metrics and provenance, not per-request payloads.

## Synthetic check

The deterministic fixture has 13 records: 12 in the creation cohort, four validated closed outcomes, three known open cases and five unknown outcomes. One record lies outside the cohort. The closed-only durations are 1, 2, 10 and 1 days (median 1.5), while seven-day closure is 2/5 eligible cases. Thirty-day closure is 2/3 eligible cases. Each open-age band has one case. Six distinct quality flags expose the deliberate anomalies.

`civic demo` asserts these results and zero inserts on repeated import, then removes temporary data. [demo.json](demo.json) records actual output. These exact fixture checks do not establish source-data accuracy, public-service performance or ingestion/query throughput.

## Bounded acquisition

`civic fetch --start YYYY-MM-DD --end YYYY-MM-DD --agency CODE --out NEW_DIRECTORY` uses the fixed public legacy NYC311 endpoint. A live metadata/count probe on 27 October 2026 confirmed this endpoint still accepts credential-free reads; the newer SODA3 protocol has different authentication requirements and is not silently substituted. No arbitrary URL, user-written SoQL, credential or callback is accepted. Agency codes are bounded ASCII letters/digits/underscores/hyphens and dates become validated midnight civil timestamps. The end date is exclusive and the window is at most seven days.

The collector verifies projected metadata types, counts the filtered cohort, selects only the seven allowed fields, orders by unique text ID and pages with explicit offsets. Strictly increasing IDs detect duplicate/reordered pages. It records before/after count and global update-marker checks. Up to 20 data pages and 24 total requests are permitted; page size is 1–1,000, row cap 1–20,000, each response at most 2 MiB and total response bytes at most 16 MiB. The final projected JSON must fit the normal 10 MiB import limit. The transport uses a 15-second network-operation timeout; it is not a universal wall-clock deadline. There are no automatic retries or paid APIs.

Redirects, HTML, schema/scope/order failures, rate limits and transport byte failures abort without publishing a capture. Row/page caps produce explicit truncated captures. Completed pagination with matching counts and a non-null unchanged update marker is complete **as checked**; otherwise it is unknown. Completeness is not transactional: updates with unchanged counts, delayed markers or cache behavior may escape detection. Analysis exposes a non-atomic/unattested warning even for complete captures.

Observation time is derived from acquisition UTC using America/New_York as an explicit publisher-clock assumption. Source request timestamps remain floating; the conversion applies only to the observation clock. Packaged tzdata supports hosts without system IANA files. This assumption does not establish a timezone for every source value.

Only after successful validation does the collector create a fresh private directory with projected requests.json and manifest.json. Existing directories/files are refused. POSIX modes are 0700 for the final directory and 0600 for files; Windows requires appropriate directory ACLs. A filesystem failure may leave a partial private directory; it is reported as failure and never silently replaces existing work.

The optional acquisition extension binds method, fixed endpoint, exact projected query, page size/caps/hashes, before/after counts/update markers, type metadata, request count, capture times, termination and projected payload SHA-256. Imports verify the local payload hash and row count; contradictory complete/consistency metadata is refused. Old manifests without the extension retain their previous serialization and snapshot identities. Metadata remains editable/unattested, and hashes are not signatures.

Official query guidance checked on 27 October 2026:

- https://dev.socrata.com/docs/queries/limit.html
- https://dev.socrata.com/docs/queries/offset.html
- https://dev.socrata.com/docs/queries/order.html
- https://dev.socrata.com/docs/endpoints.html

## Report exports

`civic export --db DATABASE --snapshot SNAPSHOT_ID --format json|csv --out NEW_FILE` uses the same partial-input guard as analysis. JSON includes the full aggregate report and provenance; CSV flattens summary, horizons, open age bands, agency metrics and quality counts, repeating snapshot/cohort/clock/completeness/warning context. It exports no per-request rows. CSV blank values represent undefined metrics; denominators remain explicit. JSON is preferred when full query/page provenance is needed.

Exports refuse more than 2,000 CSV metric rows or 2 MiB of serialized output rather than truncating. Existing files and symlinks are refused using exclusive creation; new POSIX files use mode 0600. Parent directories must already exist and be trusted. Serialization/limit checks precede file creation; interrupted or failed physical writes can leave an incomplete new file. No atomic replacement or overwrite is offered.

CSV quotes every field and prefixes formula-like string cells with an apostrophe, including leading whitespace and common compatibility-width characters. Numeric metrics stay numeric and JSON preserves original labels. This mitigates common spreadsheet formula interpretation; it is not a guarantee for every spreadsheet/import path. Keep original data separate from spreadsheet views.

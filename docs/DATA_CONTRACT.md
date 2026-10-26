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

JSON input is an array of objects using API field names. CSV accepts those names or the public display labels Unique Key, Created Date, Closed Date, Agency, Problem, Status and Borough. The older Complaint Type label also maps to `complaint_type`. Two headers mapping to one field are refused. NYC's current display-label changes leave backend API field names unchanged, as checked on 27 October 2026: https://www.nyc.gov/opendata/news/all-news/311-Service-Requests-Updates .

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

`completeness` is complete, unknown or truncated, and is explicitly recorded as **caller-declared**. A complete declaration is not an independent proof that every NYC request was included. Query scope is represented by the creation window and optional agency; the original remote query and an atomic remote snapshot have not been verified by this local importer. Analysis refuses unknown/truncated declarations or skipped-record imports unless `--allow-partial` is supplied; that option adds a population-estimation warning.

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

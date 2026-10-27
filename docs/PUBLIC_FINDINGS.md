# NYC311 DOT cohort: 1 September 2026

This is a narrow, reproducible snapshot analysis, not a citywide performance ranking. It covers DOT requests created during the single civil day from 2026-09-01 inclusive to 2026-09-02 exclusive. Administrative closure does not establish whether the reported problem was resolved.

## Capture and scope

The fixed-host collector downloaded 768 projected request records in three pages (300, 300, 168) on **27 October 2026 at 01:01:26 UTC**. Observation time is **26 October 2026 at 21:01:26.460**, using an explicitly recorded America/New_York publisher-clock assumption. No request timestamps were converted to UTC. Before/after source counts were both 768 and the dataset update marker was unchanged. These checks can detect some changes; they do not make the live API an atomic snapshot.

The [aggregate report and full capture provenance](nyc-dot-2026-09-01.json) record query, limits, timestamps, field types, page hashes, payload hash and warnings. Individual requests, addresses, coordinates and descriptions are not published here. Local capture files are ignored by Git.

```sql
SELECT unique_key,created_date,closed_date,agency,complaint_type,status,borough
WHERE created_date >= '2026-09-01T00:00:00.000'
  AND created_date < '2026-09-02T00:00:00.000'
  AND agency = 'DOT'
ORDER BY unique_key ASC
```

The source endpoint is https://data.cityofnewyork.us/resource/erm2-nwe9.json . Source context and field descriptions: https://data.cityofnewyork.us/Social-Services/311-Service-Requests-from-2020-to-Present/erm2-nwe9/about_data .

## Results under the documented rules

| Measure | Result |
| --- | ---: |
| Imported cohort rows | 768 |
| Validated closed outcomes | 667 |
| Known open outcomes | 92 |
| Unknown/inconsistent outcomes | 9 |
| Closed-only median duration | 2.173 calendar-clock days |
| Closed within seven days / eligible known outcomes | 410 / 759 (54.018%) |
| Closed within 30 days / eligible known outcomes | 648 / 759 (85.375%) |
| Known open cases at least 30 days old | 92 |

There were no skipped records, normalized duplicate IDs or out-of-scope rows. All 759 known-outcome cases had sufficient follow-up for both horizons. The nine excluded outcomes had status Assigned alongside a populated closure date. That combination is treated conservatively as unknown; it is not proof the source records are erroneous. Lifecycle semantics or reopenings may explain such combinations, but this snapshot cannot establish their history.

The 2.173-day median describes the 667 validated closed cases. It omits the 92 open cases and nine unknown outcomes. Reporting that median alone would hide the retained open backlog. The horizon fractions keep eligible open cases in the denominator while exposing the nine exclusions. Neither statistic estimates the eventual closure time of cases still open.

## Reproduce the method

After installation, use a fresh output directory:

```sh
civic fetch --start 2026-09-01 --end 2026-09-02 --agency DOT --page-size 300 --out data/dot-recapture
civic ingest data/dot-recapture/requests.json --manifest data/dot-recapture/manifest.json --db data/dot-recapture.duckdb
```

Use the returned snapshot ID with `civic analyze --db data/dot-recapture.duckdb --snapshot SNAPSHOT_ID`. If the capture is marked unknown/truncated, inspect its provenance before explicitly opting into partial analysis. Later acquisitions may differ because the source is mutable; these commands reproduce the method, not an immutable remote version of this capture.

Original projected-file SHA-256: `280671e4666964a9b2d3596c0caf856d07abe750dc5ac5a4a9d8218db9912fe8`.

Snapshot identity: `8764af576ca3c99e75b0fbe20b5740d2adb21ac641c06b55aaceee32fefe636c`.

## Limits on interpretation

One agency and one creation day are not representative of all NYC311 work. No adjustment is made for request type, severity, operational workflow or reporting behavior. The analysis does not compare agencies or attribute delay to a cause. Nine unknown outcomes are excluded from the horizon denominator; different defensible classification rules could change the results.

The stored values are floating civil timestamps. Duration is a calendar-clock difference, not a timezone-adjusted, business-hour or SLA measure. America/New_York is an assumption for the capture's observation clock, not a verified timezone attached to every source value. Counts/update markers and stable ordering cannot detect every concurrent source change, omission or cache inconsistency. The provenance is recorded but not cryptographically authenticated. Raw records are retained locally rather than committed; without that local capture, later queries cannot reconstruct this exact earlier observation.

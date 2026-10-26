SELECT agency, count(*) AS cohort_rows,
       count(*) FILTER (WHERE outcome='closed') AS closed_count,
       count(*) FILTER (WHERE outcome='open') AS open_count,
       count(*) FILTER (WHERE outcome='unknown') AS unknown_outcome_count,
       median(date_diff('millisecond',created_date,closed_date)/86400000.0)
           FILTER (WHERE outcome='closed') AS closed_only_median_days
FROM scoped GROUP BY agency ORDER BY agency LIMIT 201

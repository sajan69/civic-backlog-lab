-- Recent quickly closed cases are excluded along with recent open cases:
-- everyone in the denominator must have the same minimum follow-up window.
SELECT h.days AS horizon_days,
       count(*) FILTER (WHERE outcome IN ('open','closed')
           AND created_date+h.days*INTERVAL '1 DAY'<=observed_at) AS eligible_known,
       count(*) FILTER (WHERE outcome='closed'
           AND created_date+h.days*INTERVAL '1 DAY'<=observed_at
           AND closed_date<=created_date+h.days*INTERVAL '1 DAY') AS closed_within_horizon,
       count(*) FILTER (WHERE outcome IN ('open','closed')
           AND created_date+h.days*INTERVAL '1 DAY'>observed_at) AS too_recent_known,
       count(*) FILTER (WHERE outcome='unknown'
           AND created_date+h.days*INTERVAL '1 DAY'<=observed_at) AS unknown_outcome_excluded
FROM (VALUES (7),(30)) h(days) LEFT JOIN scoped ON true
GROUP BY h.days ORDER BY h.days

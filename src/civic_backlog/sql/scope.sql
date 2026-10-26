-- All parameters are bound. Source timestamps remain floating civil values.
WITH context AS (
    SELECT ?::TIMESTAMP AS cohort_start, ?::TIMESTAMP AS cohort_end,
           ?::TIMESTAMP AS observed_at, ?::VARCHAR AS agency_scope
), scoped AS (
    SELECT r.*, c.observed_at
    FROM requests r CROSS JOIN context c
    WHERE snapshot_id=? AND created_date>=c.cohort_start AND created_date<c.cohort_end
      AND created_date<=c.observed_at
      AND (c.agency_scope IS NULL OR agency=c.agency_scope)
)

SELECT CASE WHEN created_date+INTERVAL '7 DAY'>observed_at THEN 'under_7_days'
            WHEN created_date+INTERVAL '30 DAY'>observed_at THEN '7_to_under_30_days'
            ELSE '30_days_or_more' END AS age_band,
       count(*) AS requests
FROM scoped WHERE outcome='open'
GROUP BY age_band

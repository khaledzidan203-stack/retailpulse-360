-- RetailPulse 360 P4.2 / Portable SQLite read-only analytics views.
-- Official and Marketplace are NEVER added together.
CREATE TEMP VIEW v_rp_official_store_day AS
SELECT store_key,date_key,
 SUM(net_sales_cents) AS official_cents,
 SUM(CASE WHEN channel_key='RETAIL' THEN net_sales_cents ELSE 0 END) AS retail_cents,
 SUM(CASE WHEN channel_key='PROGRAM' THEN net_sales_cents ELSE 0 END) AS program_cents,
 SUM(gross_sales_cents) AS gross_cents,
 SUM(returns_amount_cents) AS returns_cents,
 SUM(transactions) AS transactions,
 SUM(units) AS units
FROM fact_sales_daily GROUP BY store_key,date_key;
CREATE TEMP VIEW v_rp_budget_store_day AS
SELECT store_key,date_key,SUM(allocated_budget_cents) AS effective_budget_cents
FROM fact_budget_daily GROUP BY store_key,date_key;
CREATE TEMP VIEW v_rp_marketplace_store_day AS
SELECT store_key,date_key,SUM(attributed_retail_net_sales_cents) AS attributed_cents
FROM fact_marketplace_daily GROUP BY store_key,date_key;
-- Aggregate accounts FIRST so one retail denominator is joined once per store/date.
CREATE TEMP VIEW v_rp_matched_digital_store_day AS
SELECT d.store_key,d.date_key,d.attributed_cents,r.net_sales_cents AS retail_cents
FROM v_rp_marketplace_store_day d
JOIN fact_sales_daily r ON r.store_key=d.store_key AND r.date_key=d.date_key AND r.channel_key='RETAIL'
JOIN generation_metadata m ON m.generation_id='G0004'
JOIN dim_date cal ON cal.date_key=d.date_key
WHERE cal.calendar_date<=m.official_asof AND cal.calendar_date<=m.marketplace_asof
AND EXISTS(SELECT 1 FROM source_coverage_official c
 WHERE c.store_key=r.store_key AND c.date_key=r.date_key AND c.channel_key='RETAIL'
 AND c.coverage_state IN ('REPORTED_ZERO','REPORTED_VALUE'));

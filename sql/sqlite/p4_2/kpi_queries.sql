-- RetailPulse 360 P4.2: parameterized reference queries (SQLite).
-- Money in integer CENTS; calculate ratios from SUMMED components in application.
-- Bind start_key, end_key and optional channel/store context consistently.
-- SQL-001: additive official sales, gross, returns, transaction and units.
SELECT COALESCE(SUM(net_sales_cents),0) official_cents,
 COALESCE(SUM(gross_sales_cents),0) gross_cents,
 COALESCE(SUM(returns_amount_cents),0) returns_cents,
 COALESCE(SUM(transactions),0) transactions,
 COALESCE(SUM(units),0) units
FROM fact_sales_daily WHERE date_key BETWEEN ? AND ?;
-- SQL-002: effective budget capped by official As-Of; zero sales do not remove budget.
SELECT COALESCE(SUM(b.allocated_budget_cents),0) budget_cents
FROM fact_budget_daily b JOIN dim_date d ON d.date_key=b.date_key
JOIN generation_metadata m ON m.generation_id='G0004'
WHERE b.date_key BETWEEN ? AND ? AND d.calendar_date<=m.official_asof;
-- SQL-003: raw Marketplace may extend beyond official source As-Of.
SELECT COALESCE(SUM(attributed_retail_net_sales_cents),0) digital_cents
FROM fact_marketplace_daily WHERE date_key BETWEEN ? AND ?;
-- SQL-004: paired marketplace/retail numerator and denominator.
SELECT COALESCE(SUM(attributed_cents),0) digital_cents,
 COALESCE(SUM(retail_cents),0) retail_cents
FROM v_rp_matched_digital_store_day WHERE date_key BETWEEN ? AND ?;
-- SQL-005: Strict LFL cohort: date-pair table is dynamically assembled from
-- same-day previous calendar year; WTD uses -364 days (Sat-Fri alignment).
-- Strict requires each chosen channel to be REPORTED and operating on every
-- TY and paired PY day. See executable SQL in P4.2 Python oracle runner.
-- SQL-006: Gap = Official - Budget, Achievement = Official / Budget;
-- Budget zero/missing => N/A, never 0%, never AVG(store achievements).

RetailPulse 360 — Power Query source package, STATIC SOURCE ONLY

1. In Power BI Desktop create two TEXT parameters: pProjectRoot = your local RetailPulse 360 project root; pGeneration = CURRENT.
2. Create blank query fnLoadCsv by pasting 02_fnLoadCsv.m in Advanced Editor; disable load for function.
3. Create individual blank queries named for q_*.m files and paste each file; rename to filenames without q_ prefix if desired.
4. Use Import mode. All money columns are Int64 cents; divide by 100 in DAX display measures, never in raw facts.
5. Create active single-direction dimension-to-fact relationships: dim_date[date_key], dim_store[store_key], dim_channel[channel_key] to official sales/budget facts; dim_marketplace_account[account_key] to marketplace fact. Link date/store to marketplace too, with unambiguous one-to-many relationships. No fact-to-fact links or automatic ambiguous cross filtering.
6. bridge_account_store_period is HISTORY/QA: do not create a regular many-to-many active relationship that ignores validity dates.
7. Generation metadata enables explicit official/marketplace As-Of measures. Never add Marketplace to Official Sales.
8. Refresh in Desktop and validate row counts, money totals, relationships, period filters, Strict LFL, source freshness, and navigation BEFORE approval.
9. External connector / credentials / privacy levels / native Desktop runtime not tested by this package; local folder path is a parameter, not a mandatory D: dependency.

Expected G0004 counts (for Desktop comparison): fact_sales_daily=36438; fact_budget_daily=37054; fact_marketplace_daily=21377; dim_date=730; dim_store=30.
Expected G0004 Official net cents=3759335807; Marketplace attribution net cents=514398580 (nonadditive); entire allocated budget to official As-Of=3663645215.

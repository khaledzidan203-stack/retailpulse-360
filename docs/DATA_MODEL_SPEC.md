# RetailPulse 360 — Data Model & Source/Grain Contracts

**Version:** 0.1.0-draft  
**State:** `PROPOSED — PENDING APPROVAL`; not an implemented schema.

## 1. Universe and sources

- **30** fictitious stores with independently invented city/region names and no real geocodes or addresses.
- Declared calendar `2025-01-01` through `2026-12-31`; calendar year and proposed Saturday–Friday business week. Leap-day edge cases use independent unit fixtures outside the production observation window.
- `CUR`: fictitious monetary unit; source amounts at 2 decimals and exact integer cents/Decimal semantics.
- `OFFICIAL`: cumulative full snapshots containing additive channel records `RETAIL` and `PROGRAM` only.
- `MARKETPLACE`: independently refreshed, cumulative full snapshots of `RETAIL`-attributed activity; not another official additive channel.
- `BUDGET`: approved monthly target source by store/month/additive channel; immutable versioned inputs per build.
- `STORE_MASTER`: invented master that explicitly owns opening date and approved last trading date; never infer closure from transactions disappearing.
- Each source family owns its own `source_asof`, `source_version`, `snapshot_id`, input fingerprint and completeness manifest. Source dates after As-Of are invalid.

## 2. Canonical analytical tables and keys

| Table | One row means | Business primary key | Required fields / meaning |
|---|---|---|---|
| `dim_date` | one calendar date | `date_key` (`YYYYMMDD`) | `date`, `year`, `quarter`, `month`, `month_start`, `year_month`, `weekday_number`, `week_start_saturday`, `week_end_friday`, period sort keys |
| `dim_store` | one invented store in V1 (type-1 descriptive attributes) | `store_key` (e.g. `S001`) | `region_key`, `city_key`, `store_profile`, `open_date`, nullable `last_trading_date`; explicit lifecycle state derived by date |
| `dim_channel` | one official additive stream | `channel_key ∈ {RETAIL, PROGRAM}` | name, `is_additive=true` |
| `dim_marketplace_account` | one invented digital account identity | `account_key` | account label/type, effective ownership history managed separately |
| `bridge_account_store_period` | one exclusive account→store assignment interval | `account_key`, `valid_from` | `store_key`, `valid_to` nullable; per-account intervals must not overlap |
| `store_operating_calendar` | one store on one date | `store_key`, `date_key` | `is_operating`, `lifecycle_state`, approved opening/closing basis; covers all 30×calendar dates |
| `source_coverage_official` | one store/date/additive-channel expected report state | `store_key`, `date_key`, `channel_key`, `generation_id` | `coverage_state`, `source_asof`, `evidence`; do not use as additive sales |
| `source_coverage_marketplace` | one account/date expected report state | `account_key`, `date_key`, `generation_id` | `coverage_state`, `source_asof`, `evidence`, `is_expected_after_adoption` |
| `fact_sales_daily` | one store/date/additive channel | `store_key`, `date_key`, `channel_key` | `gross_sales_cents`, `returns_amount_cents`, `net_sales_cents`, `transactions`, `units`, `source_snapshot_id`, `lineage_hash` |
| `fact_budget_monthly` | one approved store/month/additive channel target | `store_key`, `month_start`, `channel_key`, `budget_version` | `monthly_target_cents`, target approval/version |
| `fact_budget_daily` | one store/date/additive channel **effective eligible** allocation | `store_key`, `date_key`, `channel_key` | `allocated_budget_cents`, `allocation_policy_version`, source budget key; not materialized on nonoperating days |
| `fact_marketplace_daily` | one resolved store/date/account | `store_key`, `date_key`, `account_key` | `attributed_retail_net_sales_cents`, `orders`, `units`, `source_snapshot_id`, `lineage_hash` |
| `dq_findings` | one finding on a particular run/check/key | `generation_id`, `check_id`, `source_family`, `affected_key`, `occurrence` | `severity`, `state`, `reason`, `impact`, `source_fingerprint`, evidence |
| `publication_manifest` | one immutable validated generation | `generation_id` | input/outputs hashes, As-Of per family, contract versions, QA status, current pointer history |

`fact_store_period_kpis` is **not needed in V1**; only add rebuildable, explicitly grain-specified caches after observed performance evidence. A marketplace account history bridge is a controlled exception to a plain star schema, not a license for unbounded many-to-many relationships.

## 3. Source-to-fact contracts

### 3.1 Official sales

- Uniqueness: **store × date × `RETAIL|PROGRAM`**. Duplicate *source* business keys are `ERROR` and block publication; never auto-`DISTINCT`.
- `gross_sales_cents >= 0`, `returns_amount_cents >= 0`, `net_sales_cents = gross - returns`, valid `net_sales_cents < 0` permitted. `transactions >= 0`, `units >= 0` (this V1 models sold units, not net units after refunds).
- A store's transactions are assigned to exactly one additive channel; aggregates of transaction counts across channels do not double count. **This is a synthetic model rule**, to be validated by the generator.
- `OFFICIAL` facts contain only real reported rows / explicit verified zeros; never invent zeros for absent source coverage. A verified zero may be a materialized row with all zero values.
- A record outside operation dates is an error unless separately approved as a legitimate posted-after-closure return event with a redesigned posting-date contract (out of V1); no silent deletion.

### 3.2 Budgets

- One approved monthly target for each expected store × month × official channel; `budget_version` selects **exactly one active approval version** per published generation.
- `month_start` is the first calendar date of the month, not a text-only month label. Budget target is nonnegative.
- The complete calendar month determines daily allocation **before** applying `store_operating_calendar`. No reallocation of budget from the closed portion or pre-opening portion to operating dates.
- `fact_budget_daily` materializes only operating days. `source_asof`/selected period constrains **which dates are summed** in a KPI; it must not physically destroy future target allocations in the budget source.
- For day-level `CUR` cents, proposed deterministic quotient/remainder policy in `ARCHITECTURE_DECISIONS.md` applies. All downstream layers must use the same approved policy and retain an independent exact-Decimal theoretical reference.

### 3.3 Marketplace

- Source account/date row is unique; after applying effective-date mapping, fact grain is store × date × account. Map **one account to at most one store on any given date**; an account transfer to another store requires adjacent nonoverlapping intervals.
- Digital `attributed_retail_net_sales_cents` is independent source reporting and a **subset/attribution** of `RETAIL`, **not a third summand** of Official. It can be zero/negative if the modeled return policy allows; anomalies are DQ findings, not double-counted.
- Synthetic generator should normally constrain attributable orders and sales to the corresponding Retail activity, while deliberate fault scenarios may violate it. Anomalies such as attributed sales greater than Retail are flagged with signed-value context; do not erase them to force KPI agreement.
- Multiple accounts may map to one store on one date; roll up the numerators across accounts **after** checking duplicate-account coverage and mapping. Never join raw digital records to raw official rows and sum blindly.
- Digital retention can extend **beyond** Official As-Of. Comparisons are calculated on matching eligible dates/stores only, not by truncating the stored digital fact.

### 3.4 Coverage vs reporting zeros

| State | Semantics | Sales inclusion | Eligibility consequence |
|---|---|---|---|
| `REPORTED_VALUE` | valid source value, including negative net | include actual | covered |
| `REPORTED_ZERO` | explicitly reported zero activity | include zero row | covered |
| `RETRACTED_CONFIRMED` | formerly published unprotected key intentionally absent from a validated complete replacement, with coverage/ledger proof | remove old value; do **not** substitute zero | not eligible for Strict at the missing channel/date unless independently re-reported as zero |
| `MISSING_EXPECTED` | operating/source-expected date without adequate source/coverage evidence | do **not** substitute zero | `Strict LFL` ineligible; DQ finding |
| `NOT_APPLICABLE` | store closed/not yet open, account not adopted | no sales row | not required coverage |
| `INVALID` | illegal key/type/contradictory input | quarantine and block critical publish | invalid until resolved |

Missing expected coverage may trigger `ERROR/BLOCKED` on baseline correctness. An intentionally retracted unprotected key **must not be resurrected or automatically treated as zero**: the replacement snapshot plus explicit coverage certification/scenario-ledger evidence classify it as `RETRACTED_CONFIRMED` (accepted removal, not a missing-input parse error). If such independent evidence is absent, classify the absence `MISSING_EXPECTED`; do not guess that it was a valid retraction. An unreported removed value is not part of Strict cohort coverage unless a new explicit zero row replaces it.

## 4. Relationships and filter propagation

```text
dim_date ───────┬──> fact_sales_daily
                ├──> fact_budget_daily
                ├──> fact_marketplace_daily
                ├──> store_operating_calendar
                └──> coverage tables (for engineering checks)

dim_store ──────┬──> fact_sales_daily
                ├──> fact_budget_daily
                ├──> fact_marketplace_daily
                └──> store_operating_calendar

dim_channel ────┬──> fact_sales_daily
                └──> fact_budget_daily

dim_marketplace_account ──> fact_marketplace_daily
```

All ordinary report relationships are **one-to-many**, with **single direction dimension → fact**; `dim_date` is continuous. No fact-to-fact active relationship. `bridge_account_store_period` must be resolved upstream into `fact_marketplace_daily.store_key` for report filtering rather than forcing a bidirectional temporal bridge in Power BI.

`fact_budget_monthly` is a governed input table to the daily allocation transformation; do not join it directly into an active Daily report star unless an explicit alternate reporting context is approved. `dq_findings` may be a filtered diagnostic table rather than a transactional relationship in the main star; DQ counts are not additive to revenue.

## 5. Store lifecycle and LFL eligibility

- `open_date` is inclusive. `last_trading_date` is inclusive; null means no approved closure within observed timeline.
- `is_operating(store,date) = date >= open_date AND (last_trading_date IS NULL OR date <= last_trading_date)`.
- Store lifecycle checked **at the exact date window**; present-day open/closed status cannot retrospectively determine old-period inclusion.
- **Total** sales: all valid official source records for stores on eligible operating dates, including new and subsequently closed stores. **Total** budget: all eligible operating dates, including open days with explicit zero sales and expected days with source missingness (which are transparently quality-flagged).
- **Strict LFL:** same business-key store included in both TY and PY when it is operating on every matched date in each window, each required channel/source is covered on every expected date, and both windows satisfy period-completeness policy. Zero sales with verified reporting is eligible; Missing is not.
- Network Strict growth always compares **SUM(TY for exactly the same eligible store set)** with **SUM(PY for the same set)**. Never average store YoY rates or use separate eligible sets for numerator/denominator.
- For a channel-filtered LFL metric, require coverage for that chosen channel in TY/PY; for `OFFICIAL` total require both additive channels on each date. The exact definition is reflected in KPI contracts and tested.

## 6. Temporal comparability

- Calendar year; Saturday–Friday weeks with `week_start_saturday`. WTD reference PY window uses a **364-day offset** for same weekday alignment (draft choice).
- MTD/QTD/YTD and arbitrary calendar YoY default to matching **same MM-DD dates one calendar year earlier** for existing dates. `Feb 29` has no corresponding previous-year date in most years; it is excluded from comparable YoY windows and flagged. The production observation window 2025–2026 contains no leap day, but edge-case fixtures test it.
- `EffectivePeriodEnd = MIN(selected_period_end, official_source_asof)` for official time measures, constrained by selected start. `dim_date` maximum is never used as a source freshness proxy.
- TY and PY must have the same intended number of comparison observations; if they differ because of leap/coverage/partial cutoffs, explicit missing or warning behavior is required. Source coverage is per family, not inferred from the output rows alone.
- 2025 YoY against 2024 is `BLANK/N/A` because V1 does not contain a valid 2024 comparison period.

## 7. Security and release metadata

- Use fictitious IDs, names and labels that cannot collide with employee/corporate identifiers by design; store full provenance of seed/scenario/version in manifests.
- No customer IDs/PII in generated facts. `transactions` is a **count**, not a distinct customer or door footfall proxy proven by independent observation.
- All columns/keys/formats and schema changes are version-controlled after approval; no hidden source-specific exceptions.

## 8. Explicit design questions for approval

1. Strict LFL full-window operating + coverage rule; channel-dependent coverage.
2. Saturday–Friday week and 364-day WTD PY; calendar-matched YoY for other periods.
3. Deterministic residual-cent allocation with pre-opening/post-closure masking.
4. Separate transaction-count KPI instead of unsupported unique-customer/footfall measure.
5. One account per store per date interval; multiple accounts per store allowed.
6. Earlier As-Of archive restoration constrained by the rollback As-Of cut-off.

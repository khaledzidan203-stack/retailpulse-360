# RetailPulse 360 — Governed KPI Contracts

**Version:** 0.1.0-draft  
**Status:** `PROPOSED — PENDING APPROVAL`  
**Scope:** Official `RETAIL` + `PROGRAM`; separate `MARKETPLACE` attribution. All monetary values use fictional `CUR`.

## 1. Universal calculation/format/filter rules

1. **Facts and keys:** `fact_sales_daily` at store × date × official channel, `fact_budget_daily` at store × date × official channel, `fact_marketplace_daily` at store × date × account. Dimensions always filter facts; no ungoverned raw fact joins.
2. **Official:** `RETAIL + PROGRAM` only. Never add Marketplace in the numerator of Official Sales, Actual vs Budget or total network sales.
3. **Financial precision:** authoritative source/display money stored as integer minor units; internal budget division uses Python `Decimal`; canonical day-level cents after the approved residual policy. SQL sums integers; report converts to `CUR`.
4. **Population:** every amount is evaluated on intersected date/store/geography/channel context; budget population includes valid operating zero-sales dates. Slicers never silently transform absent data into zeros.
5. **Time:** official measures are bounded to the available Official As-Of and the user's selected date window (except explicitly labeled target/future scenario views). WTD/MTD/QTD/YTD anchor at this effective end.
6. **Missing states:** `0` is an actual reportable number only when known. `NULL/BLANK`, `MISSING_EXPECTED`, `INVALID` and `NOT_APPLICABLE` are different. Missing coverage produces diagnostic warning or block under QA gates.
7. **Ratios:** sum components first, then divide. If denominator = 0 or absent, return `BLANK/N/A`; do not fake 0%, 100% or infinity. Additional unstable negatives policy is stated per KPI.
8. **Returns:** include valid net-negative dates and positive/zero transactions; zero positive transaction denominator returns BLANK for basket.
9. **Totals:** channel/store/month totals recomputed from underlying additive facts, never average individual store percentages.
10. **QA oracle:** deterministic manual fixtures and pure, independent `Decimal`/integer arithmetic; compare against Python implementation, SQLite and actual DAX after available.

## 2. Governing KPI catalog

| ID | KPI | Definition | Grain/source, denominator and total behavior | Zero / BLANK / population |
|---|---|---|---|---|
| `KPI-001` | Retail Net Sales | `Σ net_sales_cents` where `channel=RETAIL` | Official daily; additive store/date | valid negatives included, reported zeros = 0; absent coverage ≠ 0 |
| `KPI-002` | Program Net Sales | `Σ net_sales_cents` where `channel=PROGRAM` | Official daily; additive | same as Retail |
| `KPI-003` | Official Net Sales | `KPI-001 + KPI-002` | Sum across selected additive channels only; no Marketplace | missing source flagged; 0 only for confirmed fully reported zero totals |
| `KPI-004` | Official Gross Sales | `Σ gross_sales_cents` | official daily, nonnegative amounts | aggregate by selected channel / operating period |
| `KPI-005` | Returns Amount | `Σ returns_amount_cents` | official daily; positive return amounts | returns do not disappear when net sales negative |
| `KPI-006` | Effective Allocated Budget | `Σ fact_budget_daily.allocated_budget_cents` | store × date × channel, only operating dates, limited to official As-Of for comparable KPI | zero budget can be valid; no post-closure allocation |
| `KPI-007` | Budget Gap | `KPI-003 - KPI-006` | same date/store/channel filters | signed `CUR`; valid negative gap; do not redefine as budget-minus-actual |
| `KPI-008` | Achievement % | `KPI-003 / KPI-006` | **ratio of totals**; denominator = effective aligned budget | if denominator = 0/missing → N/A; negative sales on positive budget may yield negative % |
| `KPI-009` | Channel Mix % | selected additive channel sales / total Official Sales for *same store/date set* | Ratio of totals across channels, channel slicer must not reduce whole-Official denominator | official total <= 0 → N/A with warning for negative/unstable shares |
| `KPI-010` | Transaction Count | `Σ transactions` across official channels | daily disjoint channel transactions by synthetic contract | 0 is valid; not unique customers or real footfall |
| `KPI-011` | Units Sold | `Σ units` across official channels | daily sold-unit counts; not net units after returns | 0 valid |
| `KPI-012` | Average Basket Value | eligible official net sales / `KPI-010` | ratio of sales totals to transactions for identical date/store/channel scope | transaction denominator <= 0 → N/A; signed net value retained if denominator >0 |
| `KPI-013` | Average Units per Transaction | `KPI-011 / KPI-010` | summed units / summed transactions | no transactions → N/A |
| `KPI-014` | Official PY Sales | Official Sales for approved paired prior-year window and eligible current filtering scope | calendar-year comparison, paired periods; no 2024 source for 2025 | coverage missing → N/A/warning; PY 0 is a real amount if covered |
| `KPI-015` | Official YoY Growth % — Total | `TY Total / PY Total - 1` | TY/PY each include their operating-store populations, not necessarily identical stores (network expansion view) | PY <=0 or missing → N/A; disclose population changes |
| `KPI-016` | Strict LFL TY Sales | TY sales for store cohort **eligible in both paired windows** | same cohort for TY/PY, period-specific operating+source coverage | if no eligible stores → N/A rather than fabricated zero growth |
| `KPI-017` | Strict LFL PY Sales | PY sales for *same* cohort as KPI-016 | eligible matched cohort exactly identical | valid reported zeros retained |
| `KPI-018` | Strict LFL YoY Growth % | `KPI-016 / KPI-017 - 1` | **ratio of cohort sums**, not mean of per-store rates | PY <=0/missing → N/A |
| `KPI-019` | Budget Gap Contribution % | selected store/channel negative gap / total selected negative gaps | signed contribution within explicitly negative-gap subset; same time/scope | no total negative gap → N/A; positive-gap stores excluded, never silently subtract them |
| `KPI-020` | Active Operating Stores | count distinct stores with at least one in-window operating date | operating calendar by exact date context, not current state alone | distinguish operating count from stores with reported sales |
| `KPI-021` | Reporting Stores | distinct stores with an eligible Official reported record in window | official coverage states / daily facts | verified zero reporters count; missing expected does not |
| `KPI-022` | WTD Official Sales | `KPI-003` on max(week's Saturday, user window start) to effective end | week Saturday–Friday | selected dates beyond As-Of ignored with freshness note |
| `KPI-023` | MTD Official Sales | `KPI-003` on max(month start, user window start) to effective end | calendar month | partial period disclosed |
| `KPI-024` | QTD Official Sales | `KPI-003` on max(quarter start, user window start) to effective end | calendar quarter | partial period disclosed |
| `KPI-025` | YTD Official Sales | `KPI-003` on max(Jan 1, user window start) to effective end | calendar year | partial period disclosed |
| `KPI-026` | WTD/MTD/QTD/YTD Budget | same time window and channel/population as corresponding period sales applied to KPI-006 | one independently recomputed target per period | absent/zero denominator still N/A for attainment |
| `KPI-027` | Marketplace Net Attributed Sales | `Σ attributed_retail_net_sales_cents` | digital store × date × account; **display raw independent freshness**, not Official additive | valid zero/negative retained |
| `KPI-028` | Digital Matched Through | `min(OfficialAsOf, MarketplaceAsOf, SelectedPeriodEnd)` | date bound, effective date range starts at selected period start or period-specific start | if before period start → no comparable window |
| `KPI-029` | Matched Marketplace Sales | `KPI-027` filtered to same *covered and mapped* store-date set and date window through KPI-028 | **matched numerator**, account sums by resolved store-date | unmapped/missing digital dates excluded with DQ/warning, never silently assumed zero |
| `KPI-030` | Matched Retail Sales | `KPI-001` for exactly KPI-029 matched store/date set and KPI-028 cut-off | denominator of digital share | ≤0 denominator → share N/A |
| `KPI-031` | Marketplace Contribution % | `KPI-029 / KPI-030` | ratio of matched totals; **not** Marketplace / Official and not sum of individual account shares | matched Retail <=0 → N/A; >100% flagged for interpretation |
| `KPI-032` | Source Lag (days) | `OfficialAsOf - MarketplaceAsOf` (signed) | source metadata point-in-time, not sum over stores | negative = Marketplace is newer; display dates and sign |
| `KPI-033` | Missing Expected Source Rows | count distinct expected keys in coverage marked `MISSING_EXPECTED` | DQ/coverage not summed into sales | valid zero is not missing |
| `KPI-034` | Strict Eligible Store Count | count cohort stores meeting all paired-window rules | exact cohort used for KPI-016/017 | zero cohort shown explicitly; growth N/A |
| `KPI-035` | Budget Gap by Channel | sales selected additive channel - its effective daily budget | same channel/source/date universe | contribution and totals same as channel-level sums |
| `KPI-036` | Transactions YoY % | `TY transactions / paired PY transactions - 1` with selected Total/Strict cohort rule | ratio of sums, same transaction definition | PY <=0/missing → N/A |
| `KPI-037` | Basket YoY % | `TY Average Basket / paired PY Average Basket - 1` | compute both baskets from aggregate sales/transactions, then growth | absent transaction denominator/invalid PY basket → N/A |

### Grain and filtering notes

- All `KPI-001..013`, `019..026`, `035..037` respond to supported Date, Store, Region/City and official Channel filters; selected channel behavior is explicit for `KPI-003` (filtered official channels) and channel mix (`KPI-009`, full official denominator).
- `KPI-027` can show independently fresher Marketplace data. `KPI-029..031` are always bounded to matching source dates and mapped store/date coverage. If channel slicer excludes `RETAIL`, digital share shows `N/A` instead of comparing an unrelated Program denominator.
- Store and period selections for all percentage KPIs must keep numerator and denominator aligned. Strict-specific measures must remain Strict even if a separate headline Total/Strict selector is set to Total; a global selector may switch only explicitly designated dynamic measures.
- For `KPI-003` on an explicitly filtered single channel, the result is selected Official Sales rather than always both channels. Unfiltered Official Sales always `Retail + Program`. The executive headline may intentionally clear the Channel filter if visibly labeled `All Official Channels`; this behavior must be fixed per visual in `REPORT_PAGE_MATRIX.md`.

## 3. Comparison clock contract

- Official time anchor `min(selected_end, official_asof)`.
- WTD starts Saturday. WTD prior-year comparator uses same weekday `-364 days` **(draft)**.
- MTD/QTD/YTD / custom date-window prior year use calendar-year mapping `-1 year`; `Feb 29` unmatched dates removed/warned. Explicit exact-window parity check.
- 2025 PY unavailable; do not compare 2025 to invented 2024 observations.
- For prior-year growth, use source coverage state plus cohort eligibility, not `SUM` of whatever rows happened to arrive.

## 4. Worked independent fixtures (illustrative contracts, not run results)

**Fixture A — official arithmetic:** Retail net `90.00 CUR`, Program net `10.00 CUR`, marketplace-attributed amount `20.00 CUR`, budget `125.00 CUR` ⇒ Official `100.00`, Gap `-25.00`, Achievement `80%`. Adding digital would incorrectly yield `120.00` and must fail.

**Fixture B — negative net:** one Retail row `gross=5.00`, `returns=8.00` ⇒ net `-3.00 CUR`. No automatic dropping or clamping; with Program `+1.00` Official `-2.00`.

**Fixture C — budget:** monthly budget `100.00 CUR`, month has 31 days; quotient/remainder in cents assigns daily amounts in cent-level deterministic order so sum of 31 valid days = `100.00`. If store closes after day 10, only first 10 precomputed allocations remain; no redistribution to earlier days.

**Fixture D — strict vs total:** Store A is open+covered in corresponding full TY and PY; Store B opened during TY and has no PY. Total may count B in TY; Strict must include A only on both sides, even if B has far larger TY sales.

**Fixture E — matched digital:** Official As-Of 2026-06-20, Marketplace As-Of 2026-06-23, selected end 2026-06-25 ⇒ Matched Through 2026-06-20. Preserve marketplace facts for June 21–23 in the digital independent view; exclude those dates from matched share. Require identical covered store-date set.

## 5. QA acceptance standard

A KPI only becomes approved when its unit, source grain, inclusion set, exact denominator, filter behavior, time logic, total behavior, zero/blank states, expected fixture output and actual Python↔SQLite↔DAX evidence have been recorded. Phase 1 approves **definitions only**; it does not imply the three implementations exist or pass.

# RetailPulse 360 — Power BI Report Page & Interaction Matrix

**Version:** 0.1.0-draft  
**State:** `PROPOSED — NO POWER BI FILES / VISUALS BUILT`

## 1. Visual identity and usage policy

Create a **new, independent design** for 11 pages in Power BI PBIP/PBIR/TMDL. No copying of proprietary dashboard palettes, page geometry, visual JSON, actual corporate data, layouts or screenshots. Adopt design tokens later from an independently authored style guide, not from a previous private report.

Global baseline controls: `Date range`, `Store`, `Fictional Region/City`, and additive `Channel` where conceptually supported. Selected filters and technical freshness state must be legible. `HOME / INDEX` navigation should be accessible from every analytical page; the landing page is `00 HOME / INDEX`. Page labels, chart titles, and all UI copy are in English. Permanent visible banner: `SYNTHETIC / FICTIONAL DATA`.

## 2. Eleven-page page contract

| Page | Business question / unique responsibility | Primary KPIs / visual inventory | Interaction/semantic contract |
|---|---|---|---|
| `00 HOME / INDEX` | Which analysis should a reviewer visit? How fresh/reproducible is it? | 10 navigation tiles; synthetic banner; Official/Marketplace source As-Of metadata; coverage warning | Navigation tile → destination page; metadata is generation-level and deliberately ignores most business slicers |
| `01 Executive Performance` | What is the overall budget under/over-performance and where is its materiality? | Official Sales, Budget, Gap, Achievement; waterfall/store contribution; channel mix; executive observation not causal claim | Company-total headline explicitly labeled `All Official Channels` and not misleadingly resliced by channel; store/date filters do apply |
| `02 Weekly & Monthly Trends` | When did pace deviate within a week/month, with incomplete intervals visible? | WTD, MTD, matching budget trend, weekly sales vs target, incomplete-period marker | Calendar Saturday–Friday, end capped by Official As-Of, date drill Week→Day; selected Date range intersects periods |
| `03 Quarterly & Year-over-Year` | How is current period performing against its comparable historic calendar period? | QTD, TY/PY sales, YoY growth, seasonal quarterly trend, distinct Total vs Strict labels | Same paired TY/PY mapped dates; no 2025→2024 YoY fabricated; partial/leap warning shown |
| `04 Like-for-Like & Store Cohorts` | How much of growth is network expansion versus comparable stores? | Total vs Strict YoY, cohort store counts, cohort participation, new/closed contribution decomposition | Strict measures never change meaning via a Total toggle; cohort selection is exact TY/PY intersection; explain exclusions |
| `05 Retail Channel` | What drives Retail budget gap and activity movement? | Retail Sales, Retail Budget, Retail Gap, Retail Transactions, Average Basket, trends | Force Retail channel scope; no Program or digital double count; store/date/location slicers filter |
| `06 Program Channel` | How does the second additive channel contribute to gaps and growth? | Program Sales, Budget, Gap, Achievement, units and transactions | Force Program channel; do not inherit Retail-only digital metrics; zero budget safe |
| `07 Customer & Basket` | Are observed sales variations associated with number of transactions or average basket? | Transactions, Basket Value, units/transaction, TY/PY basket and transaction decomposition | Explicitly label transaction visuals `Transactions & Basket`, **not** unique customers / true footfall; denominator same eligible scope |
| `08 Store & Geography` | Which synthetic stores, cohorts and regions have largest absolute/relative impacts? | Store scorecard, ranked gap, achievement, sales growth, store profile/cohort | Rank by explicit metric; stable tie policy; slicers filter only underlying valid grain; no real map/geocodes |
| `09 Digital Marketplace` | What share of Retail is digitally attributed and how far apart are source cut-offs? | Independent Marketplace Sales, Matched Sales, Matched Retail denominator, Matched Share, lag days, account mix | Use aligned date/store coverage; show independent newer digital facts separately. `PROGRAM`-only channel context → Matched Share N/A |
| `10 Data Quality & Methodology` | Can users trust the current source and comparison? | DQ findings by severity/source, coverage gaps, As-Of, protected restore/conflict ledger, KPI definitions and test evidence | QA status clearly separates actual executed stages from pending; methodology details not hidden by irrelevant channel filters |

## 3. Baseline global slicer × visual interaction policy

`F` = filters or recomputes; `N` = intentionally does not; `S` = special contract/eligibility; `NA` = not applicable. These are proposed outcomes, not measured visual behavior.

| Page / metric class | Date | Store | Region/City | Channel | Cohort scope | Freshness metadata |
|---|---|---|---|---|---|---|
| 01 Official aggregate/headline | F | F | F | **N** for clearly labeled All Official headline; other channel breakdown F | S only where labeled | N |
| 02 WTD/MTD pace | S: bounded period | F | F | F | NA | N |
| 03 TY/PY YoY | S: paired window | F | F | F | S: Total/Strict switch on designated measures | N |
| 04 Strict LFL | S: pair+coverage | F | F | F | **Strict fixed** for labeled measures | N |
| 05 Retail only | F | F | F | **Retail fixed** | S | N |
| 06 Program only | F | F | F | **Program fixed** | S | N |
| 07 Transaction & basket | F | F | F | F | S | N |
| 08 Store & Region | F | F | F | F | S | N |
| 09 Raw Marketplace Sales | F (digital coverage) | F | F | N/NA | NA | N |
| 09 Matched Marketplace Share | S: matched cut-off & coverage | F | F | S: Retail only; Program → N/A | NA | N |
| 10 DQ detail | S: finding-specific or source-coverage date | S | S | S only for applicable Official checks | NA | N |
| 00 Source info | N | N | N | N | N | Always fixed to generation |

## 4. Interaction QA checklist (must be performed in Desktop)

- Correct title and file/active starting page; 10 analytical destinations from Index and functional HOME on each.
- Date, Store, Geography and applicable Channel slicers affect the correct KPIs; intended non-responses are visibly labeled and documented.
- Test combinations: single-store, multi-store, newly opened, closed, zero-sales, missing-coverage, date ending before/after As-Of, Retail-only, Program-only.
- Test known correct and intentionally blank cases: PY unavailable, denominator zero/negative for selected ratios, no Strict cohort, Marketplace unmatched future window.
- Cross-highlighting and sorting do not silently change KPI denominators or violate intended report scope.
- Labels, charts and methodology text must render without clipping, overlap or unreadable dense data labels.
- No placeholder visual in release; all referenced measure/table names exist and are valid.
- Save, close and reopen Desktop; refresh after portable DataRoot configuration and recheck representative DAX values and navigation.
- Capture **genuine** Power BI Desktop screenshots only after runtime validation, tagged `SYNTHETIC / FICTIONAL`.

## 5. Build method and page gate

For each page: `approved business decision → KPI ID/contract → model/relationship → independent Python/SQLite expected result → DAX runtime verification → visual inventory → native Desktop donor → bounded PBIR patch → structural QA → Desktop interaction/layout QA → screenshot → explicit user approval → commit`.

Static checks of `page.json`, `visual.json` or TMDL are not an interactive-render or DAX-engine PASS. Build one page at a time, not 11 placeholder shells that imply completion.

# RetailPulse 360 — Phase 1 Audit, Risk Register & Approval Review

**Review pack:** `0.1.0-draft`  
**As of:** 2026-10-16  
**Status:** `DOCUMENTS_DRAFTED / CONTRACT_APPROVAL_PENDING / IMPLEMENTATION_NOT_STARTED`  
**Authority:** the provided Master Blueprint and RetailPulse 360 project instructions. All decisions below are recommendations, **not** silently approved changes to those sources.

## 1. Audit scope and inputs

**Reviewed inputs:**
- `00_MASTER_BLUEPRINT.md`: scope, source families, candidate grains, KPI/nonadditive Marketplace logic, budget/LFL, full-snapshot/archive, stages/acceptance and report matrix.
- `01_CHATGPT_PROJECT_INSTRUCTIONS.md`, `02_FIRST_MESSAGE.md`, `03_SETUP_STEPS.md`: collaboration roles, source precedence, explicit request to finish Phase 1 and obtain approval before feature development.
- `UNIVERSAL_AI_LOCAL_DEVELOPMENT_WORKFLOW_AR_2026-10-16.md`: audit/contract/local execution/OUTPUT/rollback and evidence states.
- Supporting knowledge references AKS-00/01/02/03/04/05: general governance, Python/SQL, Power BI/PBIR and lessons; their historical project facts/designs are not reused in the public architecture.
- Editor screenshot: project folder is open but no implementation files are visibly listed. This alone is **not** a filesystem audit; actual local inventory remains pending until a safe local read-only audit is authorized.

**Not reviewed / unavailable:** user's local file contents, Python and Power BI Desktop versions, source-control history, actual disk permissions, live synthetic data, SQL runtime outputs and actual DAX/Desktop results. No access to any machine disk or other local application is implied.

## 2. Phase 1 deliverables in this package

| Draft document | Main content | State |
|---|---|---|
| `PROJECT_CHARTER.md` | business questions, target audiences, scope/clean-room rules, gates | Draft for approval |
| `ARCHITECTURE_DECISIONS.md` | layers, portable SQL, money precision, full snapshots/atomic publish, ADRs | Draft for approval |
| `DATA_MODEL_SPEC.md` | source keys/grains/coverage, store lifecycle, temporal account mapping, star relationships | Draft for approval |
| `KPI_CONTRACTS.md` | KPI-001 through KPI-037 with time/population, zero/blank and reference fixtures | Draft for approval |
| `SYNTHETIC_GENERATOR_SPEC.md` | 30-store fixed seed/data mechanics, expected scenarios and provenance | Draft for approval |
| `REPORT_PAGE_MATRIX.md` | 11 page questions/visuals and slicer × visual interaction contract | Draft for approval |
| `QA_TEST_MATRIX.md` | planned test IDs, negative tests, Python-SQL-DAX, Desktop and security gates | Draft, **not run** |
| `PHASE_1_REVIEW.md` | audit boundary, unresolved decisions, risk and milestones, approval request | Draft for approval |

These files form an **isolated draft deliverable**. Do not copy them into an approved local repo or treat them as canonical until explicit approval. They may be reviewed and revised independently of any employer-owned workspace.

## 3. Decisions requiring user confirmation before Phase 2

| Decision | Recommended default | Why this matters |
|---|---|---|
| `DEC-01` Store/coverage/Strict LFL | full paired TY+PY window operation **and** verified coverage of required selected official channels; exact same store set both sides | prevents inflated comparable growth, especially on new/closed/missing-source stores |
| `DEC-02` Calendar & PY pairing | Saturday–Friday week; WTD comparable weekday `-364d`; other YoY calendar dates `-1y`; unmatched Feb29 excluded/warned | fixes a subtle week-vs-year ambiguity and leap date handling |
| `DEC-03` Budget precision | exact `Decimal` theoretical divisor by calendar days; deterministic integer-cent allocation (`divmod`, earliest days get remainder) with no redistribution after opening/closure mask | avoids financial drift while giving SQLite/Power BI portable exact cents |
| `DEC-04` Transactions | `Transaction Count` and net-sales-based `Average Basket`; **no unique customer/footfall KPI** without customer/receipt-level grain | avoids unsupported interpretation of aggregate daily fact |
| `DEC-05` Marketplace coverage/mapping | one account maps to one store per day via nonoverlapping ownership intervals; multiple accounts/store allowed; matched numerator and denominator share store-date coverage | prevents duplicate attribution and misleading digital percentage |
| `DEC-06` Source cutoffs + simulation | retain independent source As-Of; published official KPIs cap at Official As-Of; synthetic 2026 future dates labeled simulation | makes snapshots and time context reproducible and honest |
| `DEC-07` Earlier As-Of protected history | preserve immutable archive; restore only archived records <= selected rollback As-Of; protected conflicting key blocks all publication | prevents future records reappearing on historical rollback |
| `DEC-08` Atomic publish | immutable fully validated generation directories + atomic active-generation pointer; Power BI DataRoot targets one selected immutable generation | avoids multi-file partial output and Windows in-place rename pitfalls |
| `DEC-09` Source data quality | `REPORTED_ZERO ≠ RETRACTED_CONFIRMED ≠ MISSING_EXPECTED ≠ NOT_APPLICABLE ≠ INVALID`; retraction needs explicit coverage proof | critical for LFL and source correction/retraction logic |
| `DEC-10` Store profiles/seed | 30 invented stores: 20 initially mature (2 close in 2026), six 2025 openings, four 2026 openings; seed `3602026` | determinism, comparable cohorts, closure edge fixtures; adjustable before approval |

**Suggested signoff wording:** “Approve Phase 1 contracts v0.1 with DEC-01..DEC-10 as proposed.” Or specify any decision IDs to revise. Explicit approval is required; lack of objection is not approval.

## 4. Risk register

| Risk ID / severity | Risk | Mitigation / gate |
|---|---|---|
| `R-01 CRITICAL` | Proprietary code/statistics/page JSON or company metadata leaks to public Git | strict clean-room rules; no copying of previous work artifacts; audit current files + full git history before publication |
| `R-02 HIGH` | Marketplace counted again as additive revenue | additive channel dimension contains only Retail and Program; fixture Official=100 vs Digital=20 |
| `R-03 HIGH` | Snapshot replace silently retains old unprotected rows | build from validated incoming full source, never prior published output; Add/Correct/Retract fixtures |
| `R-04 HIGH` | Protected conflict corrupts archive or current generation | immutable archive hashes and publish BLOCK; simulate corruption/conflict before pointer swap |
| `R-05 HIGH` | As-Of rewind reintroduces later records | archive restoration respects earlier As-Of date, ledger and date coverage tests |
| `R-06 HIGH` | Incorrect LFL due to changing store populations / missing coverage | explicit operating calendar, paired source-coverage masks and identical cohort test |
| `R-07 HIGH` | Budget cents drift or get redistributed after closure | theoretical Decimal baseline and fixed full-month `divmod` assignments, closure masking |
| `R-08 HIGH` | SQL `REAL` or report decimal coercion breaks money parity | integer-cents canonical values, deterministic formatting, exact comparison fixtures |
| `R-09 MEDIUM` | Invalid assumptions about digital account mapping or orders | temporal bridge validity and cross-grain denominator tests |
| `R-10 MEDIUM` | Dynamic slicer changes an intended fixed denominator | per-page slicer × visual contract and Desktop runtime tests |
| `R-11 HIGH` | PBIR file parses but DAX, visual or saved navigation breaks | separate structural, semantic, Desktop runtime and save/reopen gates |
| `R-12 MEDIUM` | Reviewer cannot reproduce due to paths or missing environment | SQLite/offline reference, relative paths, tested clean extraction/import parameter setup |
| `R-13 HIGH` | Non-executed docs/tests marketed as validated | evidence states in report, manifest, README; only claim results proven by actual logs |

## 5. Implementation roadmap — bounded increments after approval

| Next checkpoint | Stage and bounded work | Deliverables / acceptance |
|---|---|---|
| `P2.1` | config/seed & 30 synthetic store lifecycles | fixed reproducible master; GEN-001/002 fixtures |
| `P2.2` | official sales, budget, accounts and digital source generation | source manifests, zero/negative/seasonality checks |
| `P2.3` | scenario-ledger and fault-injection fixture pack | source-version deltas and expected QA outcomes, tests + `OUTPUT.txt` |
| `P3.1` | RAW/STAGING key/type/lifecycle/coverage validators | no unexpected duplicates/broken FK; `OUTPUT.txt` |
| `P3.2` | effective budgets, daily analytic star dimensions/facts | month allocation/closure and exact finance parity |
| `P3.3` | full-snapshot reconcile and immutable protected archive | add/correct/retract/rollback/conflict and fingerprint evidence |
| `P3.4` | atomic staging/publish/recovery | failure-injection tests; previous generation preserved on error |
| `P4.1` | SQLite DDL/queries + independent analytics reference | SQL parity by date/store/channel/cohort and provenance |
| `P4.2` | portable Power Query import + native PBIP baseline | tested data root and semantic relationship table count; Desktop open/refresh pending actual user QA |
| `P5.1` | additive budget/transactions/base DAX measures | actual SQL/Python/DAX comparison on reference fixtures |
| `P5.2` | time/LFL/Marketplace DAX | cutoffs/Strict same-cohort/matched coverage tests |
| `P6.00..10` | one report page per approved wireframe | one-at-a-time PBIR structure, Desktop test, screenshot, review |
| `P7.1` | independent full pipeline regression and clean relocation | fresh environment results; blocked cases verified |
| `P7.2` | Power BI end-to-end runtime QA | saved/reopened 11-page validation, no unlabeled gaps |
| `P8.1` | documentation/privacy/history audit and public package | signed release checklist, source history audit, genuine screenshots |
| `P8.2` | clean GitHub reviewer path | clone/install/generate/tests; PBIP extraction/refreshed smoke test and user approval |

No later phase starts before the previous gate is supported by actual evidence. User performs or supervises local execution. A future implementation delivery should include narrow authorized files, expected test output, a PowerShell command when possible, and local `outputs/OUTPUT.txt` for review.

## 6. Phase 1 design-only readiness check

| Control | Review status |
|---|---|
| Project scope and objective | **DOCUMENTED (draft)** |
| Source families / star grains | **DOCUMENTED (draft)** |
| Core KPI and time definitions | **DOCUMENTED (draft); DEC approval pending** |
| Protected snapshot, archive and rollback design | **DOCUMENTED (draft)** |
| Scenario/fault injection specification | **DOCUMENTED (draft)** |
| Report page inventory and interaction matrix | **DOCUMENTED (draft)** |
| QA plan and phase gates | **DOCUMENTED (tests not executed)** |
| Local project file inventory and actual tool versions | **PENDING** |
| Independent Python/SQL/DAX runtime validation | **NOT IMPLEMENTED** |
| Power BI Desktop runtime validation | **NOT IMPLEMENTED** |
| GitHub repository publication | **NOT IMPLEMENTED** |

**Current verdict:** `PHASE_1_DRAFT_READY_FOR_REVIEW — APPROVAL_REQUIRED`. This is a documentation completeness statement, not an approval or execution pass.

## 7. Immediate next action

Review and either (a) approve `DEC-01..DEC-10` as proposed, or (b) return decision IDs and corrections. Upon explicit contract approval, start **only** checkpoint `P2.1` (seeded store master + lifecycle fixtures), not the full generator/ETL/Power BI implementation in one uncontrolled change.

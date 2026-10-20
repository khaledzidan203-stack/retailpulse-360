# RetailPulse 360 — QA Test Matrix & Acceptance Gates

**Version:** 0.1.0-draft  
**Status:** `TEST DESIGN ONLY — NOT EXECUTED`  
**Evidence policy:** Every below test is `PLANNED` until an executed log, exact expected/actual result, affected version and reviewer approval exist.

## 1. Method and minimum evidence

- Test oracle independence: use manually specified small boundary fixtures and a separately authored exact integer/`Decimal` reference; do **not** reimport the production helper being tested into the oracle and call that independent.
- For parity, run the **same** specific generation and filters through reference Python, SQLite SQL, and Power BI DAX (when available); compare keys, minor units, sums, exact denominator population, selected dates and cohort membership, not just one headline number.
- For required invariant checks, unexplained key-count, value or finance mismatches are **BLOCK**. For ratios, compare approved display rounding after exact numerator/denominator comparison; do not use an unexplained broad tolerance to hide real differences.
- Test negative scenarios are successful tests only when the system **correctly blocks** unsafe publish or produces the specifically approved warning. A `BLOCKED` candidate is not a pipeline defect if the expected negative test passes.
- `STATIC_PASS` indicates parsing/structural validity only; not equivalent to `DAX_RUNTIME_PASS` or `DESKTOP_RUNTIME_PASS`.

## 2. Test matrix

| Test ID | Planned phase | Level | Fixture/action | Expected invariant / pass evidence |
|---|---|---|---|---|
| `GEN-001` | 2 | Reproducibility | same version, seed, config, empty fresh workspace twice | equal sorted canonical bytes/file hashes and financial totals |
| `GEN-002` | 2 | Uniqueness | generated 30-store universe | exactly 30 distinct fictional store keys; valid lifecycle/cohort counts |
| `GEN-003` | 2 | Geography | source invented names and IDs | zero matching prohibited real/corporate identifiers; no real addresses |
| `GEN-004` | 2 | Integrity | generator money fields and counts | `net=gross-returns`, gross/returns nonnegative, transactions/units integer >=0 |
| `GEN-005` | 2 | Variation | historical/basket/time samples | intentional and documented seasonality, location mix and edge-case incidence; no proprietary fitting |
| `GEN-006` | 2 | Edge | declared active verified zero day | Official 0, coverage Reported Zero, operating budget still allocated |
| `GEN-007` | 2 | Edge | returns > gross | valid net-negative row retained and counted in Official |
| `GEN-008` | 2 | Metamorphic | alter only versioned seed | manifest detects input change; no silent global RNG leakage |
| `GRAIN-001` | 3 | Integrity | duplicate Official store/date/channel | `BLOCKED` with business key; published baseline unchanged |
| `GRAIN-002` | 3 | Integrity | duplicate Marketplace account/date | `BLOCKED`; no suppressed duplicates or double count |
| `GRAIN-003` | 3 | FK | unknown store / invalid channel | zero unexplained broken FKs; invalid candidate blocked |
| `GRAIN-004` | 3 | Date | continuity and date references | 2025–2026 continuous `dim_date`, no illegal dates or missing month keys |
| `GRAIN-005` | 3 | Coverage | compare zero vs missing vs not-applicable | states remain distinguishable (including confirmed retraction); Missing/retraction never auto-converted to 0 |
| `GRAIN-006` | 3 | Lifecycle | before open/after approved close rows | no invented closed-store zero/sales; day-of-close valid |
| `GRAIN-007` | 3 | Account | nonoverlap transfer and overlapping account ownership | correct temporal mapping; overlapping account map BLOCK; no row multiplication |
| `BUD-001` | 3/4 | Finance | 31-day full-open monthly budget `100.00` | effective full-month allocations sum exactly 100.00 with approved residual policy |
| `BUD-002` | 3/4 | Finance | February (28-day) vs 30-/31-day months | correct **calendar-day** divisor, no fixed 30-day assumption |
| `BUD-003` | 3/4 | Lifecycle | store closes on day 10 | closure day allocation present, days 11+ absent, no redistribution |
| `BUD-004` | 3/4 | Lifecycle | new store opens midmonth | preopening allocation not effective; remaining daily entitlement based on full month |
| `BUD-005` | 3/4 | Finance | active store with zero sales | budget still present; gap becomes negative budget amount |
| `BUD-006` | 3/4 | Precision | cent remainder / multi-store sum | sum of daily integer cents correct; exact-Decimal reference difference within approved cent policy |
| `KPI-001` | 3/4/5 | Reconciliation | Retail 90, Program 10, Digital 20 | Official 100 **not** 120; no marketplace double count |
| `KPI-002` | 3/4/5 | Reconciliation | sales 100, effective budget 125 | Gap -25 and Achievement 80%; correct signs/denominator |
| `KPI-003` | 3/4/5 | Empty | zero/missing budget denominator | BLANK/N/A ratio; not infinity or arbitrary zero |
| `KPI-004` | 4/5 | Ratio | two stores with very different budgets/rates | network achievement = sums/sums, never mean rates |
| `KPI-005` | 4/5 | Transactions | disjoint channel transactions | no duplicate transaction tally; Basket = official net / aligned transaction count |
| `KPI-006` | 4/5 | Guardrail | 2025 period queried for PY 2024 | no invented PY/YoY; N/A clearly displayed |
| `KPI-007` | 4/5 | Ratios | nonpositive PY baseline and net-negative sales | stable negative sales totals; growth N/A per approved denominator rule |
| `LFL-001` | 4/5 | Eligibility | new TY store with no complete PY | included Total in TY, excluded Strict both TY/PY |
| `LFL-002` | 4/5 | Eligibility | 2026 September closure, 2026 August completed | can be Strict in August; not Strict when September paired window fails full-operation |
| `LFL-003` | 4/5 | Eligibility | reported zero on both dates | eligible Strict if all other coverage and operating rules hold |
| `LFL-004` | 4/5 | Eligibility | missing expected Official channel on one paired date | exclude store from Strict paired cohort, flag coverage |
| `LFL-005` | 4/5 | Aggregation | two stores, unequal PY and YoY rates | network growth = ΣTY / ΣPY −1 on **same** eligible cohort |
| `LFL-006` | 5/6 | UX scope | change dynamic headline Total/Strict selector | measures named Strict remain Strict, store table and cards agree |
| `TIME-001` | 4/5 | Calendar | boundary Friday/Saturday | WTD resets Saturday, week's last day Friday |
| `TIME-002` | 4/5 | Cutoff | selected range ends after Official As-Of | no future official sales/budget in comparable KPI |
| `TIME-003` | 4/5 | Partial | MTD/QTD/YTD with partial month and custom start | lower/upper bounds and PY comparison windows agreed |
| `TIME-004` | 4/5 | Pairing | WTD TY/PY weekday test | proposed 364-day shift yields same weekday count |
| `TIME-005` | 4/5 | Leap | isolated leap-day fixture outside 2025–26 | unmatched Feb29 treatment / warnings are explicit |
| `DIG-001` | 3/4/5 | Attribution | digital as subset of Retail | Official same with/without digital fact; digital numerator separate |
| `DIG-002` | 4/5 | Freshness | Marketplace As-Of > Official As-Of | newer digital rows retained; matched cutoff = min As-Of |
| `DIG-003` | 4/5 | Denominator | Retail present but digital account coverage missing | denominator restricted to same matched store-date set; DQ warning exists |
| `DIG-004` | 4/5 | Ratio | 2 accounts per store, account move across dates | no duplicative joins; share from aggregate matched totals |
| `DIG-005` | 5/6 | Context | Program-only channel filter | Marketplace matched share N/A/not incorrectly compared to Program |
| `SNAP-001` | 3 | Replacement | new unprotected key in fresh full snapshot | ADD, new key published exactly once |
| `SNAP-002` | 3 | Replacement | same key, changed unprotected values | CORRECT supersedes old values, correct delta |
| `SNAP-003` | 3 | Replacement | formerly published unprotected key absent | RETRACT actually removes, no stale restoration; confirmed-retraction ledger/coverage accepted without pretending zero or hiding unexplained missingness |
| `SNAP-004` | 3 | Rollback | valid earlier As-Of full source | accepts older snapshot, respects cutoff, no later unprotected records |
| `SNAP-005` | 3 | Archive | protected key missing from current source | protected record restored unchanged, archive hash verified |
| `SNAP-006` | 3 | Security | protected key conflicting in new source | `BLOCKED`, archive/published pointer unchanged |
| `SNAP-007` | 3 | Security | corrupted archive hash | `BLOCKED` before any approved output changes |
| `SNAP-008` | 3 | Idempotence | identical rerun | same canonical hashes/content; no accumulative keys |
| `SNAP-009` | 3 | Atomicity | simulated staged failure before pointer switch | active generation unchanged and complete |
| `SNAP-010` | 3 | Rollback | select old validated generation | pointer rolls back only to hash-verified complete generation |
| `SNAP-011` | 3 | Family isolation | changed Marketplace source only | official sales remain unchanged; digital and matched metrics update if relevant |
| `SQL-001` | 4 | Model | inspect all constraints/joins | unique dimension one-side, zero unexplained orphan FK, no row multiplication |
| `SQL-002` | 4 | Reference parity | varied store/date/channel windows | identical amounts (integer cents), counts, negative rows and eligible sets vs oracle |
| `SQL-003` | 4 | Performance portability | fresh Python+SQLite environment | executable without SQL Server, D drive or network |
| `PBI-001` | 4/5 | Import | fresh extracted PBIP configured with DataRoot | report reads exact hash-verified active generation and refreshes in Desktop |
| `PBI-002` | 5 | DAX runtime | representative KPI + independent fixture windows | actual DAX values parity with approved Python/SQL reference at same filters |
| `PBI-003` | 6 | PBIR static | per-page JSON, TMDL and IDs | valid native artifacts, existing tables/measures; **not** runtime PASS |
| `PBI-004` | 6 | UI runtime | all Index→page→HOME navigation | 11 pages reachable, no broken bookmarks/navigation |
| `PBI-005` | 6 | Slicer runtime | single/multi-store, date, region, channel | actual filter response matches page interaction matrix |
| `PBI-006` | 6 | Visual runtime | each rendered page | no clipped labels, hidden visuals, incorrect page filters or placeholder visuals |
| `PBI-007` | 6/7 | Persistence | Save/Close/Reopen/Refresh | report starts Index and saved state aligns with tested intended defaults |
| `PBI-008` | 6/7 | Screenshot | saved validated model and pages | only genuine screenshot with visible synthetic identification |
| `REL-001` | 7/8 | Clean-room | isolated clean clone/ZIP, offline environment | install/generate/run/test steps reproducible, no machine path assumptions |
| `REL-002` | 8 | Privacy | inspect source files, outputs, config, git history | no proprietary files, labels, IDs, private numbers, secrets, machine-specific paths |
| `REL-003` | 8 | Publication | inspect remote URL, actual published repo and ZIP extraction | exact intended public repo; current docs/links and PBIP reviewer path work |
| `REL-004` | 7/8 | Evidence | review all published badges and claims | `STATIC_PASS` never masquerades as executed DAX/Desktop/release approval |

## 3. Approval gates

| Gate | Required acceptance | Claim permitted afterward |
|---|---|---|
| `G1` Phase 1 Contract | user approves explicit unresolved decision list, eight draft docs versioned and internally consistent | `PHASE_1_APPROVED`; **not** generator implementation |
| `G2` Generator | `GEN-*` plus source fixture coverage and stable fingerprints | limited `GENERATOR_PIPELINE_PASS` |
| `G3` ETL/Snapshot | `GRAIN-*`, `BUD-*`, `SNAP-*` plus immutable protected archive/atomicity tests | `PIPELINE_PASS` only |
| `G4` SQLite/Power Query | SQLite parity and semantic import checks; Desktop requirement remains explicit | `SQL_PASS`, and only witnessed subset of import checks |
| `G5` DAX | representative actual engine results vs independent reference in many filter contexts | `DAX_RUNTIME_PASS` for tested measures/scenarios |
| `G6` 11 Pages | static **and** actual Desktop render/interaction/navigation, saved/reopened each checkpoint | `DESKTOP_RUNTIME_PASS` for explicitly tested pages |
| `G7` System QA | all regression, offline relocation, retry and user runbook checks | version-specific QA approval |
| `G8` Public Release | clean history, privacy audit, reviewer clean checkout, valid runtime evidence, explicit user approval | `RELEASE_APPROVED` |

## 4. OUTPUT.txt evidence template (future execution only)

```text
PROJECT | RetailPulse 360
CHANGE_ID | RP360-<approved-id>
MODE | AUDIT / VALIDATE / APPLY_DEV / SHADOW_PUBLISH / RELEASE
ROOT | <effective runtime project root>
GENERATION | <identifier>
SOURCE_OFFICIAL_ASOF | <YYYY-MM-DD>
SOURCE_MARKETPLACE_ASOF | <YYYY-MM-DD>
INPUT_SHA256 | <family/file hash list>
PUBLISHED_SHA256 | <governed artifact hash list>
TESTS | planned=<N> executed=<N> pass=<N> fail=<N> warn=<N>
RECONCILIATION | exact monetary/key/count deltas and contexts
BACKUP | <versioned backup location or NONE>
PUBLISH | NOT_ATTEMPTED / BLOCKED / APPLIED
ROLLBACK | NOT_REQUIRED / APPLIED / FAILED
STATUS=PASS / WARN / BLOCKED / FAIL
```

This is **format guidance only**. No populated `OUTPUT.txt` is included in this Phase 1 design pack because no implementation/tests have been run.

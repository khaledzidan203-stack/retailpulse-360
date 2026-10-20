# RetailPulse 360 — Architecture Decisions & Snapshot Contract

**Version:** 0.1.0-draft  
**Status:** `PROPOSED — NOT IMPLEMENTED — NOT APPROVED`

## 1. Architecture overview

```text
Versioned synthetic config / dedicated RNG / scenario ledger
                         |
                         v
Synthetic independent inputs + per-family As-Of + input manifest
                         |
                         v
RAW immutable candidate source snapshots (OFFICIAL / MARKETPLACE / BUDGET)
                         |
                         v
STAGING: schema, type, duplicate, coverage, calendar, accounts, lifecycle, DQ
                         |
                         v
Full-snapshot reconciler + verified immutable protected store archive
                         |
                         v
ANALYTICS: conformed dimensions, official/budget/digital facts, DQ evidence
             |                                    |
             v                                    v
SQLite materialization + SQL tests    versioned governed CSV export files
             |                                    |
             +-------- independent parity --------+
                                                  |
                                                  v
                              Power Query import / DataRoot parameter
                                                  |
                                                  v
                              TMDL semantic model + validated DAX
                                                  |
                                                  v
                              PBIR/PBIP report (11 original pages)
                                                  |
                                                  v
                          Desktop QA → Clean clone QA → GitHub release
```

Build and validate the analytic artifact generation first. A CI pass can test static model/report artifacts; it cannot certify Power BI Desktop or a live DAX engine without actual execution.

## 2. Draft architecture decision records

| ID | Proposed choice | Rationale and safeguards | State |
|---|---|---|---|
| ADR-001 | Python package with a deterministic, versioned seed (`3602026` proposed) and project-relative paths | Portable data generation, no machine-specific paths | Pending |
| ADR-002 | SQLite as mandatory portable SQL engine; SQL Server as entirely optional showcase | SQL is a first-class testable layer without paid/server dependency | Pending |
| ADR-003 | Canonical CSV for portable Power BI Import; integer minor units or canonical decimal-text serialization for financial interchange | Native file support; no floating-point monetary ambiguity | Pending |
| ADR-004 | Typed Python `Decimal` intermediate for allocation; deterministic cent-level daily export residual assignment | Stable reconciliation; avoid independent rounding drift | Pending |
| ADR-005 | Star-schema one-to-many, single-direction conformed-dimension filters; no fact-to-fact joins | Protect correct totals/segmentation | Pending |
| ADR-006 | Separate Official and Marketplace cumulative **full** snapshots and approved monthly Budget source; per-family As-Of | Corrections and retractions cannot be handled as naive append | Pending |
| ADR-007 | Immutable hash-verified protected archive with explicit business-key selection | Preserve fictional history through missing source records | Pending |
| ADR-008 | Immutable release generations and atomic current-generation pointer, not in-place overwrites of multiple files | Readers consume one consistent approved generation; Windows-compatible design | Pending |
| ADR-009 | Power BI Desktop-created valid PBIP baseline; edit PBIR using matching native donor visuals only | Avoid unsupported hand-invented structures and copied corporate visuals | Pending |
| ADR-010 | CI tests Python / SQLite / static artifacts; separate manual Desktop + live DAX gates | Correct evidence states | Pending |
| ADR-011 | No external entity data / no company-calibrated distributions, clean git root and publication preflight | Public release protection | Pending |

## 3. Storage and precision decision

- **Source money:** currency `CUR`, rounded to 2 decimal places (minor units). Represent exactly as `Decimal` or integer cents; files may serialize money with fixed two-decimal strings.
- **Monthly budget:** store as integer cents and/or canonical 2-decimal text.
- **Exact theoretical daily entitlement:** `Decimal(monthly_budget) / calendar_days(month)` at internal working precision (at least 28 decimal digits), **regardless of opening/closing day**.
- **Proposed portable daily allocation:** compute full-calendar month first. Let `q, r = divmod(monthly_budget_cents, number_of_calendar_days)`. Days 1..r receive `q+1` cents; remaining days receive `q` cents. Eligibility masks dates before opening and after approved last trading day **without redistributing cents**. This is a deterministic cent-level presentation/allocation policy, not a mathematical claim that each day is exactly identical to infinite precision. Compare against exact Decimal theoretical allocations with documented cent-level tolerance; full eligible full-month allocation equals the monthly budget exactly.
- **SQLite money:** store integer minor units so `SUM` is exact; convert to `CUR` at presentation, avoiding SQLite `REAL` for financial aggregation. Percentages compute from exact aggregated integers with safe denominator handling.
- The distribution order is a **decision pending approval**. No silent rounding and no hardcoded generated KPI values.

## 4. Full Snapshot / protected history — proposed processing algorithm

There are independently versioned `OFFICIAL` and `MARKETPLACE` full-snapshot source families. The new validated snapshot represents the **entire present source**, not a delta. Monthly approved budgets are maintained separately and versioned; changing a budget does not automatically mean an Official source correction.

1. **Preflight (read-only):** discover candidate inputs, expected schemas, business keys, As-Of and fingerprints; validate presence, reject out-of-scope dates and duplicate source keys; verify protected archive content against pinned manifest/hash.
2. **Scope:** an incoming source `S_f` contains only rows from one family through its declared `source_asof`; rows dated after that As-Of are invalid. Missing expected coverage is a DQ finding, not an invented zero.
3. **Protected conflict:** for each protected archive key `h` also in `S_f`, compare *canonical business fields* (keys, amounts, counts and approved relevant attributes); any mismatch blocks the entire publish. Merely reordering rows or CSV encoding must not trigger a false conflict.
4. **Construct canonical family:** begin **only** with validated `S_f`; union immutable archived protected records not in `S_f` when `record_date <= S_f.source_asof`. A rollback to an earlier As-Of does not resurrect archived records dated later than the rollback cut-off; archive itself stays untouched.
5. **Changes:** compute full-key diff versus previous published family: `ADD` newly present unprotected keys; `CORRECT` changed unprotected values; `RETRACT` previously published unprotected keys absent now, with separate coverage evidence distinguishing confirmed removal from unexplained source loss; `RESTORE_PROTECTED` archive-only keys. Never rebuild from the previous published snapshot as the main base.
6. **Conform:** apply type/relationship/calendar/lifecycle/DQ checks, derive analytics facts, budgets and source freshness. Preserve valid negative net sales, returns and explicit verified zeros.
7. **Validate candidate generation:** check all family counts/keys/amount totals, protected fingerprint and all downstream output files/SQLite reference/manifest. Quality gating is severity-based and recorded.
8. **Publish:** write all governed outputs under a new immutable generation directory, verify file hashes and manifest, then atomically replace a tiny `CURRENT` pointer to this validated generation; readers resolve a **single generation ID** at open time. Never have the current pointer refer to a partially written generation. Store old immutable generation for rollback.
9. **Power BI consumption:** point the import `DataRoot` at one validated generation directory after confirming its manifest. A Power BI Desktop refresh from a frozen generation can never mix two snapshots. Updating the current pointer does not, by itself, silently change the existing Desktop parameter; a future refresh/repoint workflow is controlled and documented.
10. **Idempotence:** same approved inputs/config/archive produce the same normalized facts, fingerprints and deterministic exported bytes; operational run timestamps are kept outside canonical file hashes. Re-run may reuse an existing generation and must not accumulate records.

### Failure/rollback guarantees

- A schema/duplicate/protected-hash/protected-conflict/critical-reconciliation failure: `BLOCKED`; previous pointer and all previously published artifacts stay unchanged.
- A simulated exception mid-stage or immediately before pointer swap: no committed partial generation; stale unreferenced candidates may be cleaned later, never treated as published.
- Rollback: atomically point `CURRENT` at a previously validated, still hash-verified generation. Do not reconstruct prior output from guesses.
- Candidate and publication logs include `STATUS=`, input hashes, source As-Of, change ledger, output hashes, test counts, zero/negative/Missing counts, pointer before/after, and rollback status.
- Atomicity refers to visibility through the governed manifest/current-pointer protocol, not an unsupported claim that independent users reading arbitrary in-place paths get transactional semantics.

## 5. Source coverage and lifecycle boundaries

- `OFFICIAL` source As-Of is source-specific, not `MAX(dim_date[date])`. Marketplace may be newer; both retain their independently complete source data.
- Each expected store/date/channel row has coverage state `REPORTED_VALUE`, `REPORTED_ZERO`, `RETRACTED_CONFIRMED`, `MISSING_EXPECTED`, or `NOT_APPLICABLE`, with `INVALID` recorded separately. `RETRACTED_CONFIRMED` requires declared full-source completeness plus explicit coverage/scenario-ledger evidence; it does **not** become a synthetic zero. Zero is explicitly reported with amount 0, not inferred from no row.
- `open_date <= date <= approved_last_trading_date` (if provided) governs store operating dates. A closed store can retain historical sales and be Strict LFL in earlier complete windows.
- A missing file never means the store closed; closure comes only from the synthetic master with approved date.
- No stage may silently delete valid return/negative business days.

## 6. Portability and release scope

- All commands accept or discover a repo root; no absolute local machine path belongs in committed source configuration.
- Recommended package folders: `config/`, `src/retailpulse/`, `data/`, `sql/sqlite/`, `tests/`, `docs/`, `powerbi/`, `outputs/` and `.github/workflows/` only when actually implemented. The proposed tree does not prove the files exist.
- GitHub release includes only original, public-safe code/data/docs, test evidence and genuine report screenshots; cache, local DBs, credentials, private notes and author-machine config are excluded.
- `OUTPUT.txt` is generated **during implementation/test execution**, not fabricated during Phase 1 planning.

## 7. Risks and open architecture questions

| Risk | Mitigation / unresolved decision |
|---|---|
| Cent residual allocation appears to depart slightly from exact daily fraction | Document exact reference plus a deterministic display policy and tolerances; approve ADR-004 |
| Full-snapshot retract and coverage-gap semantics can conflict | Require per-key coverage DQ; confirmed retractions do not get resurrected or converted to zeros; unexplained absence remains missing |
| Archived records beyond earlier As-Of | Preserve archive but exclude post-cutoff records from prior-AsOf publish |
| Financial integer overflow in future huge datasets | Use declared amount bound and overflow test; Python Decimal oracle |
| Relocating PBIP to another computer breaks absolute file reference | One configurable absolute local `DataRoot` parameter generated at reviewer setup; never commit an author path |
| Capturing QA from genuine Desktop is manual | Explicit outstanding `DESKTOP_RUNTIME_PENDING` until real user evidence exists |

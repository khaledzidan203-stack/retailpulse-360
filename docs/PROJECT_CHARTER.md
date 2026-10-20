# RetailPulse 360 — Project Charter

**Version:** 0.1.0-draft  
**Contract state:** `PROPOSED — PENDING USER APPROVAL`  
**Source of authority:** `00_MASTER_BLUEPRINT.md` (project master), with supporting project instructions and generic engineering reference documents.  
**Public classification:** original / standalone / 100% independently synthetic.

## 1. Mission and outcome

Build a portable, reproducible, multi-branch retail sales analytics portfolio system for a **fictional 30-store business** across **2025-01-01 through 2026-12-31**. Deliver deterministic source generation, governed full-snapshot ETL, an auditable star schema, independently validated Python and SQLite analytics, and an **11-page** source-controlled Power BI PBIP/PBIR/TMDL report.

This is not a copy, migration, anonymization, or derivative of any employer system. No real corporate identifiers, numbers, templates, report arrangements, screenshots, code, original reports, or proprietary statistical distributions may enter the public source or history.

## 2. Business decision owners and questions

| Audience | Decisions the product supports | Measurable analytical questions |
|---|---|---|
| Executive / Retail operations | Prioritize sales and budget recovery | Which stores and channels contribute the greatest absolute negative gap? What is achievement in comparable periods? |
| Store / regional manager | Target operational diagnostics | Is sales movement associated with transactions, basket value, store maturity, or geography? |
| Commercial performance analyst | Compare performance fairly | How do Total and Strict Like-for-Like (LFL) differ as locations open and close? |
| Digital performance analyst | Understand attributed sales | What fraction of Retail is attributed to Marketplace within identical store-date coverage? How stale is either source? |
| Data / BI engineer | Trust refreshes and reports | Were source records corrected or retracted, protected records restored, output datasets published atomically, and KPIs reconciled? |
| Reviewer / recruiter | Reproduce technical work | Can a fresh local clone generate the same data, run checks, inspect SQL and open the PBIP in Desktop? |

## 3. Analytical boundaries

**Included:** source lineage, retail/program daily sales and monthly/daily budgets, transactions and units, returns and valid negative net sales, store lifecycle, calendar and week intelligence, Strict/Total comparisons, digital attribution, source freshness, full snapshots and protected synthetic history, quality checks, privacy review, GitHub release.

**Excluded in V1:** SKU/category, cost/profit/margin, procurement, supplier and stock facts; personally identifiable customer records; distinct-customer or true door-footfall claims without a supported source grain; predictive/causal claims; hosted production or mandatory proprietary infrastructure.

**Marketing rule:** Any chart, number, screenshot or insight from this project must be labeled `SYNTHETIC / FICTIONAL`. Do not imply simulated performance is a real retailer's outcome.

## 4. Success criteria / measurable deliverables

1. Clean-room seed/configuration generates the same canonical 30-store source dataset and reproducible fingerprints on equivalent supported environments.
2. Official Net Sales equals Retail Net Sales plus Program Net Sales; Marketplace is a nonadditive Retail attribution stream.
3. Daily budgets divide monthly targets by calendar days; post-closure budget stops without reallocation; valid open zero-sales days retain budget.
4. Time and LFL calculations respect As-Of, paired TY/PY date windows, exact same eligible store cohort for Strict, and incomplete/zero-denominator states.
5. Full-snapshot processing demonstrates add/correct/retract/earlier-AsOf, archived protected recovery/conflict, idempotence, atomic version-set publish and rollback.
6. Canonical results reconcile independently between Python reference fixtures and SQLite; representative DAX measures reconcile after actual Power BI execution.
7. All 11 pages have distinct analytical purpose, working visuals, tested interactions/navigation, readable layouts and real Desktop screenshots.
8. A fresh reviewer can reproduce the Python/SQLite baseline offline and, with Power BI Desktop, open/refresh the extracted PBIP without author-specific paths.
9. Public repository and history pass checks against real data, company-specific artifacts, machine paths, secrets and misleading test claims.

## 5. Phase gates and evidence

`Audit → Analytical Contract → Implementation → Validation → OUTPUT.txt → Review → Power BI Runtime QA (when relevant) → Approval → Release`.

- **Phase 1:** documents drafted and reviewed; only user approval freezes contracts.
- **Phase 2:** generator and validation evidence, not a claim of a BI runtime.
- **Phases 3–5:** transformations, SQL, DAX implemented and independently checked.
- **Phase 6:** one page per checkpoint with actual Desktop QA.
- **Phases 7–8:** end-to-end clean-room rerun and publication safety evidence.

Evidence labels: `PLANNED`, `PENDING`, `STATIC_PASS`, `PIPELINE_PASS`, `SQL_PASS`, `DAX_RUNTIME_PASS`, `DESKTOP_RUNTIME_PASS`, `RELEASE_APPROVED`, `BLOCKED` with date, artifacts and exact validation scope. A planned test is **never** marked passed.

## 6. Collaboration and change control

- ChatGPT authors design, code and bounded offline tests using shared artifacts only; it does not have access to the user's local project directory.
- The user controls local execution, approvals, Power BI Desktop QA and GitHub publication.
- Each change request documents `Scope | Inputs | Contracts | Files to Change | Tests | Risks | Expected Output`.
- Implementation scripts (only after approval) use explicit project root, allowlisted paths, backups, staged validation, rollback and a machine-readable local `./outputs/OUTPUT.txt`.
- Critical approved documents require a versioned change request, impact analysis and regression evidence before replacement.

## 7. Current truth

The blueprint describes a **proposed** architecture. The initial editor folder view contains no visible implementation. This design package contains **draft documents only**. No synthetic generator, ETL, SQL result, PBIP report, GitHub release, Python runtime result or Desktop validation is claimed to exist.

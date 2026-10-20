# RetailPulse 360 — Phase 3 ETL & Full Snapshot Operations

**Scope:** Phase 3 local implementation and QA, 2025–2026 synthetic universe.  
**Phase status:** `LOCAL_PIPELINE_PASS` (based on observed local OUTPUT.txt reports, through P3.10 on 2026-10-18).  
**Contracts:** Phase 1 v0.1, DEC-01 through DEC-10 as approved by the project owner.  
**Next phase:** Phase 4 — SQLite and independent SQL analytics, not covered by this status.  
**Publishing:** GitHub publication deliberately deferred until full project completion.

## 1. What exists and what was tested

Python source generation (Phase 2), the Phase 3 baseline ETL, protected synthetic history, immutable generations, candidate-only ingestion, SHA-verified publication, and controlled active pointer switching have been executed and checked locally. Phase 3 is complete **only within its ETL/full-snapshot contract**, not as a statement that the BI product is complete.

| Local checkpoint | Execution evidence / accepted scope |
|---|---|
| P3.2 | Baseline RAW/STAGING/ANALYTICS, month-to-day budget, provenance, 2,624 protected keys; 14/14 local gates |
| P3.3 | Two initial generations; 20/20 fixture scenarios and 8/8 operational gates; rollback, tamper and idempotence |
| P3.4–P3.5 | Source audit identified missing Python files, then 6 legacy sources and associated files were integrated locally |
| P3.6 | Disposable source-driven rebuild: 138/138 published artifacts byte-identical across P2.1/P2.2/P2.3/P3.2/P3.3 |
| P3.7 | External full-snapshot input interface, 14/14 source-driven cases; G0003 activated |
| P3.8 | External full-snapshot continuation; G0004 candidate parity, replay, protected conflict checks |
| P3.9 | Reusable publisher rebuilt 25 G0004 data artifacts from full sources, published G0004 and updated CURRENT |
| P3.10 | Read-only Phase 3 closure regression: 4 generations, 25/25 G0004 artifacts, 14/14 scenarios, isolated G0005 fault/replay/tamper checks |

These statements reflect the observed local run reports and scoped tests; they do **not** imply a SQL, DAX, Power BI Desktop or fresh GitHub clone PASS.

## 2. Layout and versioned records

- `data/synthetic/p2_1`, `p2_2`, `p2_3`: approved deterministic source data and scenario fixtures.
- `data/processed/p3_2`: published initial ETL baseline and hash-verified protected history.
- `data/processed/p3_3/generations/G0001` through `G0004`: immutable, validated published generations.
- `data/processed/p3_3/CURRENT`: small current-generation pointer, **G0004 at Phase 3 closure**.
- Each generation has `generation_manifest.json` and governed `raw/`, `staging/`, `analytics/`, `protected_history/` artifacts. Reference the **same resolved generation** throughout each analytical read.
- `src/retailpulse360/snapshot_ingest.py`: future full-snapshot candidate materialization and validation.
- `src/retailpulse360/snapshot_publish.py`: candidate verification, independent source rematerialization, controlled publication and pointer switch.
- `src/retailpulse360/legacy_steps/`: original developmental transformation/generation sources. Preserve SHA-pinned versions until portable orchestration is separately refactored and regression-tested.

The historical P2.3 fixture archive is a **test fixture**, not a substitute for the operational protected history (2,624 keys).

## 3. Business contracts preserved

- **Official Sales = Retail Sales + Program Sales**; Marketplace is digital attribution, never added again to Official.
- Monetary aggregation is done in exact integer minor units. Legitimate net-negative returns and explicitly reported zeros are preserved.
- Monthly budget is allocated over every calendar day before the opening/closing lifecycle mask, with no redistribution after closure. Official KPI cutoffs use Official As-Of, without physically removing future budget source rows.
- Marketplace source may extend beyond Official As-Of; only matched comparable periods participate in cross-family percentages.
- Full snapshots are **complete replacements**, not append files. Valid unprotected Add, Correct and confirmed Retract are allowed; missing coverage is not silently converted to zero.
- The immutable protected archive restores absent protected history and blocks conflicting values or hashes. Earlier As-Of is supported within the synthetic 2025–2026 horizon; history restoration is constrained by the incoming As-Of.
- Generation activation uses validated immutable content followed by controlled `CURRENT` replacement. Idempotent reruns cannot double count or create a different result for unchanged input.
- Strict LFL/time-intelligence definitions remain governed by Phase 1 KPI contracts; independent SQL/DAX runtime proof is deferred to later phases.

## 4. Using the local snapshot interfaces

Run in PowerShell from the **local project root**. For each new snapshot, prepare an external directory containing **exactly** these five files:

```text
official_sales_snapshot.csv
source_coverage_official.csv
marketplace_daily_snapshot.csv
source_coverage_marketplace.csv
snapshot_control.json
```

The control file uses these fields (illustrative shape, not a claim about newer supported years):

```json
{
  "classification": "SYNTHETIC",
  "snapshot_mode": "FULL_REPLACEMENT",
  "official_asof": "2026-12-20",
  "marketplace_asof": "2026-12-27"
}
```

1. **Candidate only:** `py -3 .\src\retailpulse360\snapshot_ingest.py --root . --input ..\retailpulse360_dev\incoming_snapshot --report ..\output\OUTPUT.txt`
2. Read the ephemeral report. A successful candidate is staged in the sibling `retailpulse360_dev` workspace; **no production pointer changes** at this step.
3. **Controlled publish:** `py -3 .\src\retailpulse360\snapshot_publish.py --root . --report ..\output\OUTPUT.txt` (use `--candidate` when selecting a specific supported candidate folder).
4. Confirm `CURRENT` points to the expected new generation and that all previous generations are intact. On a rejected input, the prior generation remains current.

All incoming records are fictional. Exact coverage files, schemas, account mapping, lineage hashes, snapshot completeness, and protected-history rules are validated; a folder containing only delta rows is **not valid**. Ingestion **currently blocks As-Of outside 2025–2026**; supporting additional years requires an explicitly designed, tested contract extension.

The `..\output\OUTPUT.txt` location is an example of a **shared temporary communication folder**, not a persistent approval log or an input prerequisite. Other sibling files/folders must not be modified.

## 5. Validation and recovery model

- Before publication: validate approved P2/P3 baselines, source provenance, keys, account mapping, duplicate and coverage constraints, lifecycle, expected monetary totals, full protected archive and each output artifact SHA-256.
- Change semantics include Add/Correct/Retract, earlier As-Of, protected restore/conflict and family-specific digital changes. Deliberate DQ review conditions are distinguished from blocking errors.
- Atomic publication is defined at the **generation/pointer protocol** boundary: consumers read the generation selected once by `CURRENT`, not an unsafe mixture of independently overwritten CSV files.
- A failed stage or pre-pointer fault must leave the active pointer intact. Older generations remain available for a separate, validated rollback; do not edit any published generation in place.
- Identical replay is accepted without duplicate publication; byte tampering and protected-business-value conflicts block progression.
- Local rebuild and isolated fault simulation establish the observed Phase 3 implementation evidence. SQL oracle comparisons are **not** inferred from these tests.

## 6. Remaining gates and known boundaries

- **Not tested here:** SQLite relational constraints/queries, independent Python–SQL oracle parity, DAX runtime, Power BI Desktop import/refresh/visual/navigation QA, clean public clone, and release audit.
- **Limited horizon:** current source-generation and generic ingestion are for synthetic 2025–2026. 2027+ data is not accepted by the current ingress contract.
- **Development legacy:** initial generator/ETL code is stored under `legacy_steps`; a single end-user project orchestration CLI and final reviewer runbook still need release engineering work before GitHub.
- **Documentation consistency:** existing Phase 1 file header/version wording can still reflect its original draft state. Do not silently rewrite previously accepted contracts; reconcile their presentation as a separately scoped change before public release.
- **Scope of closure:** Phase 3 is accepted on local technical QA, not on any unrun BI engine or end-to-end published portfolio checks.

## 7. Next work — Phase 4

Start with a portable SQLite star-schema design and **independent** Python-vs-SQL reconciliation over the active G0004 generation. Preserve integer-cent precision, original grains, store/date/channel coverage and lifecycle, and non-additive Marketplace treatment. Validate constraints, FK integrity and cross-store/month totals before building Power Query and the Power BI semantic model. SQL Server remains optional, never required for baseline execution.

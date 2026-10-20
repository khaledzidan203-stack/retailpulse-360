# File decisions

The machine-readable `file_decisions.json` records one decision for every baseline file, with its original SHA-256. The three small `tests/fixtures/provenance/*_promotion_record.json` files are deliberate exceptions to exclusion of generated data metadata: they satisfy historical ancestry gates, contain only synthetic provenance and are not approval certificates.

- Include governed docs, Python source, reference SQL and small KPI comparison evidence; these retain independent baselines.
- Include native PBIP/PBIR/TMDL, DAX query and theme source. Preserve all original report files and measure definitions byte-for-byte. Only expressions.tmdl's local parameter value and Query1.tmdl's local root reference are edited for portability.
- Include all eleven visually inspected screenshots with safe stable names; PNG bytes unchanged.
- Exclude all generated source/scenario CSVs and processed snapshots, including the SQLite database. Regenerate through `python tools/reproduce.py --output "../retailpulse build"`; compare 190 source/ETL/generation files with `data_baseline.json`.
- Exclude Power BI `.pbi` state/cache, Python bytecode, historical mutating report builder, old recovery README/manifest and phase handoff README. Current README replaces obsolete reproduction claims.
- Exclude raw local audits, communication files, backups and developer workspace. No pre-existing Git history is imported.

Executable classification: legacy_steps/*.py are HISTORICAL and potentially MUTATING (except package initializers); snapshot_ingest.py, snapshot_publish.py, sqlite_build.py, sqlite_refresh.py, sql_analytics.py and phase4_validation/kpi_sql_parity.py are MUTATING and must target isolated outputs. tests/p4_3/test_kpi_edges.py writes an external candidate and is MUTATING. tests/test_sources.py is READ_ONLY (CLI help subprocesses only). tools/reproduce.py is MUTATING, with mandatory new external target; tools/validate_public.py is READ_ONLY. __init__.py files are READ_ONLY. No generated executable is published.

Five historical command examples were sanitized in docstrings; executable AST is unchanged, and test_sources.py fingerprints are updated for those exact sanitized bytes. The source engine and analytical/data pins remain enforced. `.gitattributes` disables line-ending conversion because the approved inputs and source gates use exact byte hashes. No Git LFS is required for the resulting small source-only payload. License is pending; no license file is granted.

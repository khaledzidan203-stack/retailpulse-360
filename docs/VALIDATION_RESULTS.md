# Validation results ? PRE-RELEASE

Executed 2026-10-21 (Asia/Riyadh). This document reports headless evidence; it is not final runtime approval.

| Gate | Status | Command / evidence | Result / remaining action |
|---|---|---|---|
| Original source fidelity | PASS | Local SHA-256 baseline verification | All 486 original files unchanged |
| Protected report design | PASS | `python -B tools/validate_public.py` | 219 preserved native files match independent baseline; only two scoped M path edits |
| Screenshots | PASS for privacy/static review | Eleven original PNGs visually inspected and metadata/CRC/decompression checked | Bytes preserved; current Desktop behavior NOT RUN |
| PBIP/PBIR/TMDL static checks | PASS | `tools/validate_public.py` | 11 pages, 43 original measures, 164 current visual containers, 284 validated field bindings; model table index and relationships checked |
| Channel scope / gauges | PASS static | Locked Retail/Program page filters and original gauge role bindings | Runtime filters and display pending |
| Data classification | PASS | Allowlist and 142 historical review dispositions | Synthetic source only; generated datasets omitted and regenerated |
| Credentials / private paths | PASS local scan | `tools/validate_public.py` | Every candidate file scanned without size skips; local state/cache excluded |
| Unit/source/safety tests | PASS | `python -B -m unittest discover -s tests -p "test_*.py" -v` | 5 tests, including existing-target and source-checkout overwrite refusal |
| Generator and ETL | PASS | `tools/reproduce.py --output <new external directory>` | 9 lifecycle checks, 14 sales/budget/marketplace checks, 22 fixture checks; deterministic ETL |
| Snapshot engine | PASS | Same bootstrap | 20 scenarios and 8 operational gates; fault cases must produce their expected BLOCKED/DQ_REVIEW outcome |
| Full input mutations | PASS | Same bootstrap | 14 cases at G0003 and G0004 transitions, including protected-history conflict, missing coverage, digital excess, correction/retraction and earlier As-Of |
| Independent baseline | PASS | `release/data_baseline.json` | 190 regenerated files match approved source SHA-256 values |
| SQLite and governed KPI parity | PASS | Same bootstrap | Exact G0004 SQLite hash; independent CSV/SQL arithmetic, 37 KPI IDs across 13 scenarios, 12 independent arithmetic/date fixtures |
| SQLite generation refresh | PASS | Same bootstrap | Historical generation rebuild checks executed |
| Actual publisher rollback/replay + future SQLite | PASS | Final bootstrap run | Injected failure returned expected exit 2 and restored G0004; real G0005 publish and identical replay succeeded; G0005 SQLite rebuilt; main output remains G0004 |
| Clean Git checkout rehearsal | PASS | Fresh local Git clone, fresh venv, exact README commands | Dependencies exit 0; 5 tests exit 0; static/privacy exit 0; full build exit 0 in 81.61 seconds; checkout remained unchanged |
| Power BI Desktop runtime | NOT RUN | Native Desktop control unavailable | Refresh, actual DAX parity and all-page interactions require local Desktop checklist |
| GitHub Actions | NOT RUN yet | `.github/workflows/ci.yml` | Actual remote run required after push; never inferred from local tests |
| Git push / remote images | NOT RUN yet | Publication gated on completed headless and privacy checks | No final version tag or GitHub Release |

Static M checks cover shared parameter/loader structure and preserved table sources; no M evaluation or DAX-engine execution is claimed. Other Python/SQLite runtimes are not certified. Original document approval headers and historical QA JSON remain provenance, not substitutes for these reruns. The gallery preserves original visuals, including current sorts and gauges; review the explicit Desktop checklist for remaining presentation checks.

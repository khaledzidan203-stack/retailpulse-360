# Reproduction

Use the exact commands in the root README. Python 3.13.15 / SQLite 3.50.4 on Windows is the locally validated environment; CI uses the same Python version. Runtime dependencies are standard-library-only, so requirements.txt is intentionally empty except for explanation.

`python -B tools/reproduce.py --output "../retailpulse build"` requires a nonexistent external target. Paths with spaces are supported. It copies source/model into that new sandbox, invokes pure seeded generator APIs (not historical report-approval gates), generates scenario fixtures, executes ETL twice for determinism, builds G0001/G0002, materializes the two documented +111-cent synthetic corrections into G0003/G0004 and verifies 190 independent baseline hashes. It rebuilds SQLite and executes SQL/KPI and generation refresh checks. Nothing is fetched from development folders or Downloads.

Three tiny promotion-record JSON fixtures are retained as provenance inputs to historical hash gates. They are not claims of current release approval. No generated CSV or SQLite database is shipped. All synthetic scenarios, including fault inputs, are generated from source. Logs, intermediate candidates and output databases stay under the selected external target.

Expect 36,438 Official facts; 37,054 budget facts; 21,377 Marketplace facts. Full-horizon Official cents are 3,759,335,807; Marketplace attribution cents are 514,398,580; full-horizon budget cents are 3,731,451,566. The aligned Official As-Of budget is 3,663,645,215 cents.

A failed command exits nonzero and leaves local evidence for inspection. Do not delete an existing target automatically; choose a new directory for another run. Existing immutable input and database hash gates remain enforced. A database-byte mismatch on another SQLite version needs review, not removal of the correctness gate.

The preserved snapshot CLIs are expert-level APIs with their own external-report and candidate constraints. The bootstrap's generated project is disposable; never point historical mutating scripts at an approved authoring project.

#!/usr/bin/env python3
r"""RetailPulse 360 / P2.1 - clean-room deterministic store master + lifecycle.

Candidate-only, stdlib-only validation runner. NEVER modifies the approved project repo.
Requires Phase 1 v0.1 contract approval (DEC-01..DEC-10).

Example (PowerShell):
    Run the supported portable entry point: python tools/reproduce.py --output "../retailpulse build"

To reproduce in any checkout, omit --report: the default is
<project-root-parent>/output/OUTPUT.txt. Work files, report history and quarantined
legacy output entries are placed in <project-root-parent>/retailpulse360_dev/.
With --tidy-output, legacy entries are MOVED (never deleted) out of output/.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import traceback
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

CHECKPOINT = "P2.1"
VERSION = "p2.1.0"  # generator version: keep dataset bytes and manifest hashes stable
RUNNER_REVISION = "p2.1.1"  # packaging/report directory fix only
DEFAULT_SEED = 3602026
START = date(2025, 1, 1)
END = date(2026, 12, 31)
STORE_FILE = "dim_store.csv"
CALENDAR_FILE = "store_operating_calendar.csv"
MANIFEST_FILE = "p2_1_manifest.json"
EXPECTED_DOCS = (
    "ARCHITECTURE_DECISIONS.md",
    "DATA_MODEL_SPEC.md",
    "KPI_CONTRACTS.md",
    "PHASE_1_REVIEW.md",
    "PROJECT_CHARTER.md",
    "QA_TEST_MATRIX.md",
    "REPORT_PAGE_MATRIX.md",
    "SYNTHETIC_GENERATOR_SPEC.md",
)
STORE_FIELDS = (
    "store_key", "store_name", "region_key", "region_name", "city_key",
    "city_name", "store_profile", "lifecycle_cohort", "open_date",
    "last_trading_date",
)
CAL_FIELDS = ("store_key", "date_key", "calendar_date", "is_operating", "lifecycle_state")


def digest_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json(obj: object) -> bytes:
    return (json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def keyed_number(seed: int, namespace: str, key: str) -> int:
    """Local, independent stable PRNG stream per entity/attribute (no global RNG)."""
    token = f"RetailPulse360|{VERSION}|{seed}|{namespace}|{key}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(token).digest()[:8], "big")


def build_stores(seed: int) -> list[dict[str, str]]:
    stores = []
    for n in range(1, 31):
        key = f"S{n:03d}"
        if n <= 20:
            cohort = "MATURE_PRE_2025"
            opening = date(2021, 1, 1) + timedelta(days=keyed_number(seed, "mature_open", key) % 1350)
        elif n <= 26:
            cohort = "OPENED_2025"
            month = (2, 4, 6, 8, 10, 12)[n - 21]
            opening = date(2025, month, 4 + keyed_number(seed, "open_day", key) % 20)
        else:
            cohort = "OPENED_2026"
            month = (1, 4, 7, 10)[n - 27]
            opening = date(2026, month, 3 + keyed_number(seed, "open_day", key) % 21)

        # Both closures are synthetic mature stores. Day of closure is INCLUSIVE.
        last_trading = {"S019": date(2026, 9, 15), "S020": date(2026, 11, 20)}.get(key)
        city_number = 1 + keyed_number(seed, "city", key) % 8
        region_number = ((city_number - 1) // 2) + 1
        profiles = ("LOW", "MID", "HIGH")
        profile = profiles[keyed_number(seed, "profile", key) % len(profiles)]
        stores.append({
            "store_key": key,
            "store_name": f"Fictional Store {n:03d}",
            "region_key": f"R{region_number:02d}",
            "region_name": f"Fictional Region {region_number:02d}",
            "city_key": f"C{city_number:02d}",
            "city_name": f"Fictional City {city_number:02d}",
            "store_profile": profile,
            "lifecycle_cohort": cohort,
            "open_date": opening.isoformat(),
            "last_trading_date": last_trading.isoformat() if last_trading else "",
        })
    return stores


def enumerate_days() -> list[date]:
    return [START + timedelta(days=n) for n in range((END - START).days + 1)]


def build_lifecycle(stores: list[dict[str, str]]) -> list[dict[str, str]]:
    rows = []
    days = enumerate_days()
    for store in stores:
        opening = date.fromisoformat(store["open_date"])
        closing = date.fromisoformat(store["last_trading_date"]) if store["last_trading_date"] else None
        for d in days:
            if d < opening:
                state = "BEFORE_OPEN"
            elif closing is not None and d > closing:
                state = "AFTER_CLOSE"
            else:
                state = "OPERATING"
            rows.append({
                "store_key": store["store_key"],
                "date_key": d.strftime("%Y%m%d"),
                "calendar_date": d.isoformat(),
                "is_operating": "1" if state == "OPERATING" else "0",
                "lifecycle_state": state,
            })
    # Canonical store/date ordering, independent of input iteration order.
    rows.sort(key=lambda r: (r["store_key"], r["date_key"]))
    return rows


def csv_bytes(rows: list[dict[str, str]], fields: tuple[str, ...]) -> bytes:
    # Explicit LF, UTF-8, stable ordered columns, no timestamps/BOM/implicit index.
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n", extrasaction="raise")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def dataset(seed: int) -> tuple[dict[str, bytes], list[dict[str, str]], list[dict[str, str]]]:
    stores = build_stores(seed)
    calendar = build_lifecycle(stores)
    store_csv = csv_bytes(stores, STORE_FIELDS)
    cal_csv = csv_bytes(calendar, CAL_FIELDS)
    settings = {
        "generator_version": VERSION,
        "seed": seed,
        "observation_start": START.isoformat(),
        "observation_end": END.isoformat(),
        "store_count": 30,
        "cohorts": {"MATURE_PRE_2025": 20, "OPENED_2025": 6, "OPENED_2026": 4},
        "closures": {"S019": "2026-09-15", "S020": "2026-11-20"},
        "geography": "independently fictional, non-geocoded",
    }
    manifest = {
        "project": "RetailPulse 360",
        "checkpoint": CHECKPOINT,
        "status": "CANDIDATE_ONLY_NOT_APPROVED",
        "classification": "100% SYNTHETIC / FICTIONAL",
        "contract_version": "0.1",
        "generator_version": VERSION,
        "seed": seed,
        "configuration_sha256": digest_bytes(canonical_json(settings)),
        "settings": settings,
        "files": {
            STORE_FILE: {"sha256": digest_bytes(store_csv), "rows": len(stores)},
            CALENDAR_FILE: {"sha256": digest_bytes(cal_csv), "rows": len(calendar)},
        },
        "limitations": [
            "P2.1 only: no sales, budgets, digital accounts, source coverage, ETL, SQLite or Power BI.",
            "Lifecycle operating flags do not certify Official/Marketplace source coverage or Strict LFL.",
            "Generated CSV files are candidate outputs, not approved or published tables.",
        ],
    }
    return {
        STORE_FILE: store_csv,
        CALENDAR_FILE: cal_csv,
        MANIFEST_FILE: canonical_json(manifest),
    }, stores, calendar


def require(ok: bool, why: str) -> None:
    if not ok:
        raise AssertionError(why)


def test_case(label: str, fn, outcomes: list[tuple[str, str, str]]) -> None:
    try:
        fn()
        outcomes.append(("PASS", label, ""))
    except Exception as exc:
        outcomes.append(("FAIL", label, f"{type(exc).__name__}: {exc}"))


def run_checks(seed: int, files: dict[str, bytes], stores: list[dict[str, str]],
               calendar: list[dict[str, str]]) -> list[tuple[str, str, str]]:
    results: list[tuple[str, str, str]] = []
    parsed_stores = list(csv.DictReader(io.StringIO(files[STORE_FILE].decode("utf-8"))))
    parsed_calendar = list(csv.DictReader(io.StringIO(files[CALENDAR_FILE].decode("utf-8"))))
    manifest = json.loads(files[MANIFEST_FILE])
    expected_days = 730  # Independently fixed by approved 2025 + 2026 (nonleap) window.

    def reproducibility():
        independent, _, _ = dataset(seed)
        require(files == independent, "Two fresh in-memory generations have different canonical bytes")
        for fname in files:
            require(digest_bytes(files[fname]) == digest_bytes(independent[fname]), f"SHA mismatch: {fname}")

    def uniqueness_cohorts():
        keys = [r["store_key"] for r in parsed_stores]
        require(len(keys) == len(set(keys)) == 30, "Expected exactly 30 distinct store keys")
        require(keys == [f"S{i:03d}" for i in range(1, 31)], "Store keys/order mismatch")
        cohort_counts = Counter(s["lifecycle_cohort"] for s in parsed_stores)
        require(cohort_counts == {"MATURE_PRE_2025": 20, "OPENED_2025": 6, "OPENED_2026": 4},
                f"Incorrect cohort counts: {dict(cohort_counts)}")
        require(sum(bool(s["last_trading_date"]) for s in parsed_stores) == 2, "Closures not exactly 2")
        require(all(not s["last_trading_date"] or s["lifecycle_cohort"] == "MATURE_PRE_2025"
                    for s in parsed_stores), "Only mature stores may close in P2.1")

    def valid_dates():
        for s in parsed_stores:
            opened = date.fromisoformat(s["open_date"])
            closed = date.fromisoformat(s["last_trading_date"]) if s["last_trading_date"] else None
            cohort = s["lifecycle_cohort"]
            require((opened.year < 2025 if cohort == "MATURE_PRE_2025" else
                    opened.year == (2025 if cohort == "OPENED_2025" else 2026)),
                    f"Invalid cohort date: {s['store_key']}")
            require(closed is None or opened <= closed <= END, f"Invalid closing interval: {s['store_key']}")
        require(next(s for s in parsed_stores if s["store_key"] == "S019")["last_trading_date"] ==
                "2026-09-15", "S019 fixture closure differs from approved P2.1 plan")
        require(next(s for s in parsed_stores if s["store_key"] == "S020")["last_trading_date"] ==
                "2026-11-20", "S020 fixture closure differs from approved P2.1 plan")

    def geography_and_profiles():
        require(set(s["store_profile"] for s in parsed_stores) == {"LOW", "MID", "HIGH"},
                "Expected all three fictional profiles")
        for s in parsed_stores:
            require(s["store_name"] == f"Fictional Store {int(s['store_key'][1:]):03d}",
                    "Nonfictional store naming")
            require(s["region_name"].startswith("Fictional Region ") and
                    s["city_name"].startswith("Fictional City "), "Not explicitly fictional names")
            city = int(s["city_key"][1:])
            region = int(s["region_key"][1:])
            require(1 <= city <= 8 and region == (city + 1) // 2,
                    "Invalid city-to-region hierarchy")
        # Does not substitute for a later full release privacy/code/history audit.

    def calendar_grain_and_coverage():
        require(len(parsed_calendar) == 30 * expected_days == 21900,
                f"Unexpected lifecycle row count {len(parsed_calendar)}")
        keys = {(r["store_key"], r["date_key"]) for r in parsed_calendar}
        require(len(keys) == len(parsed_calendar), "Duplicate store/date in lifecycle")
        require(set(r["store_key"] for r in parsed_calendar) ==
                {s["store_key"] for s in parsed_stores}, "Orphan store in lifecycle")
        date_keys = {r["date_key"] for r in parsed_calendar}
        expected_keys = {(START + timedelta(days=i)).strftime("%Y%m%d") for i in range(expected_days)}
        require(date_keys == expected_keys, "Lifecycle has missing/extra days")
        for r in parsed_calendar:
            require(r["date_key"] == r["calendar_date"].replace("-", ""), "Inconsistent date key")

    def reference_lifecycle():
        by_store = {s["store_key"]: s for s in parsed_stores}
        for r in parsed_calendar:
            s = by_store[r["store_key"]]
            d = date.fromisoformat(r["calendar_date"])
            is_open = d >= date.fromisoformat(s["open_date"])
            is_before_close = not s["last_trading_date"] or d <= date.fromisoformat(s["last_trading_date"])
            expected_operating = is_open and is_before_close
            expected_state = ("BEFORE_OPEN" if not is_open else
                              "AFTER_CLOSE" if not is_before_close else "OPERATING")
            require(r["is_operating"] in ("0", "1"), "Operating value must be binary string")
            require((r["is_operating"] == "1") == expected_operating and
                    r["lifecycle_state"] == expected_state, f"Lifecycle rule mismatch: {r['store_key']} {d}")

    def boundaries():
        index = {(r["store_key"], r["calendar_date"]): r for r in parsed_calendar}
        fixtures = (
            ("S019", "2026-08-01", "1", "OPERATING"),
            ("S019", "2026-09-15", "1", "OPERATING"),
            ("S019", "2026-09-16", "0", "AFTER_CLOSE"),
            ("S020", "2026-11-20", "1", "OPERATING"),
            ("S020", "2026-11-21", "0", "AFTER_CLOSE"),
            ("S030", "2025-12-31", "0", "BEFORE_OPEN"),
        )
        for key, dt, flag, state in fixtures:
            item = index[(key, dt)]
            require(item["is_operating"] == flag and item["lifecycle_state"] == state,
                    f"Lifecycle boundary mismatch: {key} {dt}")
        for s in parsed_stores:
            if START <= date.fromisoformat(s["open_date"]) <= END:
                require(index[(s["store_key"], s["open_date"])]["is_operating"] == "1",
                        f"Opening day is not included: {s['store_key']}")

    def manifest_integrity():
        require(manifest["checkpoint"] == CHECKPOINT and manifest["seed"] == seed,
                "Manifest checkpoint/seed mismatch")
        require(manifest["contract_version"] == "0.1", "Incorrect contract version")
        settings = manifest["settings"]
        require(manifest["configuration_sha256"] == digest_bytes(canonical_json(settings)),
                "Config fingerprint mismatch")
        for filename, count in ((STORE_FILE, 30), (CALENDAR_FILE, 21900)):
            require(manifest["files"][filename]["sha256"] == digest_bytes(files[filename]),
                    f"Manifest wrong SHA for {filename}")
            require(manifest["files"][filename]["rows"] == count, "Manifest wrong row count")

    def seed_isolation():
        altered, _, _ = dataset(seed + 1)
        require(altered[STORE_FILE] != files[STORE_FILE], "Changing seed had no store-level effect")
        require(digest_bytes(altered[MANIFEST_FILE]) != digest_bytes(files[MANIFEST_FILE]),
                "Changing seed did not change manifest")
        require(files[STORE_FILE] == csv_bytes(stores, STORE_FIELDS), "Store CSV is not canonical")
        require(files[CALENDAR_FILE] == csv_bytes(calendar, CAL_FIELDS), "Lifecycle CSV is not canonical")

    for label, fn in (
        ("GEN-001 | Same seed/config reproducibility and exact bytes", reproducibility),
        ("GEN-002 | 30 unique stores, cohorts and two closures", uniqueness_cohorts),
        ("P2.1-LC-001 | Cohort and closure dates", valid_dates),
        ("P2.1-LC-002 | Fictional geography and three store profiles", geography_and_profiles),
        ("P2.1-LC-003 | 21,900 rows, exact store/date grain and continuity", calendar_grain_and_coverage),
        ("P2.1-LC-004 | Independent date-bound lifecycle reference", reference_lifecycle),
        ("P2.1-LC-005 | Opening, closure and pre-open fixtures", boundaries),
        ("P2.1-LC-006 | Canonical manifest and SHA-256", manifest_integrity),
        ("P2.1-LC-007 | Different seed changes data/manifest", seed_isolation),
    ):
        test_case(label, fn, results)
    return results


def preflight(root: Path, report: Path, workspace: Path) -> tuple[list[str], Path]:
    problems: list[str] = []
    candidate = workspace / "P2_1_CANDIDATE"
    if not root.is_dir():
        problems.append(f"Project directory is missing: {root}")
        return problems, candidate
    for name in EXPECTED_DOCS:
        if not (root / "docs" / name).is_file():
            problems.append(f"Phase 1 contract not found: docs/{name}")
    resolved_root = root.resolve()
    report_parent = report.parent.resolve()
    for target in (report.resolve(), candidate.resolve(), workspace.resolve()):
        if target == resolved_root or resolved_root in target.parents:
            problems.append(f"Refusing to write inside approved project root: {target}")
    if workspace.resolve() == report_parent or report_parent in workspace.resolve().parents:
        problems.append("Workspace must NOT be inside the central output directory")
    if workspace.is_symlink() or candidate.is_symlink() or report.is_symlink():
        problems.append("Symlinked workspace/candidate/report destination is not permitted")
    if report.name.casefold() != "output.txt":
        problems.append("Central report must be named OUTPUT.txt")
    return problems, candidate

def verify_or_stage(candidate: Path, files: dict[str, bytes]) -> str:
    """Never overwrite a prior candidate. No writes to approved repo."""
    if candidate.exists():
        if not candidate.is_dir() or candidate.is_symlink():
            raise ValueError("Candidate exists but is not an ordinary directory")
        existing = sorted(p.name for p in candidate.iterdir())
        if existing != sorted(files):
            raise ValueError(f"Existing candidate has different file list: {existing}; no modification performed")
        for name, expected in files.items():
            item = candidate / name
            if item.is_symlink() or not item.is_file() or item.read_bytes() != expected:
                raise ValueError(f"Existing candidate differs: {name}; no modification performed")
        return "REUSED_IDENTICAL_CANDIDATE"

    parent = candidate.parent
    parent.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="._P2_1_temp_", dir=str(parent)))
    try:
        for name, body in files.items():
            (scratch / name).write_bytes(body)
        for name, body in files.items():
            if (scratch / name).read_bytes() != body:
                raise IOError(f"Staging byte verification failed: {name}")
        if candidate.exists():
            raise FileExistsError("Candidate appeared during staging; stop before overwrite")
        scratch.rename(candidate)
    finally:
        if scratch.exists():
            shutil.rmtree(scratch)
    return "CREATED_NEW_CANDIDATE"


def tidy_output_directory(report: Path, workspace: Path) -> tuple[str, list[str]]:
    """Opt-in: move extra central-output entries into a private workspace quarantine.

    Does not delete user data. On any move error, restores everything already moved.
    Workspace is disjoint from report parent and approved project root (preflight).
    """
    leftovers = sorted((p for p in report.parent.iterdir() if p.name != report.name),
                       key=lambda p: p.name.casefold())
    if not leftovers:
        return "NO_EXTRA_ENTRIES", []
    if any(p.is_symlink() for p in leftovers):
        raise ValueError("Cannot tidy symlinked output entries; review manually")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    quarantine = workspace / "output_quarantine" / f"before_P2_1_{stamp}"
    quarantine.mkdir(parents=True, exist_ok=False)
    moved: list[tuple[Path, Path]] = []
    try:
        for source in leftovers:
            destination = quarantine / source.name
            source.rename(destination)  # same disk (sibling project workspace), no deletion
            moved.append((source, destination))
    except Exception:
        for source, destination in reversed(moved):
            destination.rename(source)
        try:
            quarantine.rmdir()
        except OSError:
            pass
        raise
    return str(quarantine), [src.name for src, _ in moved]


def store_report(report: Path, lines: list[str], workspace: Path) -> Path | None:
    """Keep only OUTPUT.txt in report parent; history is outside it.

    Atomic replacement uses a temporary file in the same directory. The OS file
    descriptor returned by mkstemp MUST be closed before os.replace on Windows.
    """
    report.parent.mkdir(parents=True, exist_ok=True)
    archived: Path | None = None
    if report.exists():
        if not report.is_file() or report.is_symlink():
            raise ValueError("Existing report path is not an ordinary file")
        history = workspace / "report_history"
        if history.is_symlink():
            raise ValueError("Symlinked history directory not permitted")
        history.mkdir(parents=True, exist_ok=True)
        old = report.read_bytes()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        archived = history / f"OUTPUT_{stamp}_{digest_bytes(old)[:10]}.txt"
        with archived.open("xb") as out:
            out.write(old)
    fd, tmp_name = tempfile.mkstemp(prefix="._output_", suffix=".tmp", dir=str(report.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as out:  # important: close the handle on Windows
            out.write(("\n".join(lines) + "\n").encode("utf-8"))
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, report)
    finally:
        if tmp.exists():
            tmp.unlink()
    return archived

def main(argv=None) -> int:
    cli = argparse.ArgumentParser(description="RetailPulse 360 P2.1 candidate-only store generator and QA")
    cli.add_argument("--root", required=True, help="Approved local RetailPulse 360 project root (read-only)")
    cli.add_argument("--report", help="Central OUTPUT.txt; default: <root parent>/output/OUTPUT.txt")
    cli.add_argument("--tidy-output", action="store_true", help="Move existing non-OUTPUT items into separate local quarantine; never delete")
    args = cli.parse_args(argv)
    root = Path(args.root).expanduser().resolve()
    report = (Path(args.report).expanduser() if args.report else root.parent / "output" / "OUTPUT.txt").resolve()
    workspace = (root.parent / "retailpulse360_dev").resolve()
    # Hard safety gate BEFORE any logging: even a failure report must never be written to the approved project.
    if report == root or root in report.parents:
        print("STATUS=BLOCKED_UNSAFE_REPORT_PATH; report must be outside --root", file=sys.stderr)
        return 3
    now = datetime.now(timezone.utc).isoformat()
    log = [
        "PROJECT | RetailPulse 360",
        f"CHECKPOINT | {CHECKPOINT}",
        "CONTRACT | Phase 1 v0.1 APPROVED DEC-01..DEC-10",
        f"RUN_UTC | {now}",
        "MODE | VALIDATE_CANDIDATE_ONLY",
        f"ROOT_READ_ONLY | {root}",
        f"REPORT | {report}",
        "SEED | 3602026",
        f"ALGORITHM_VERSION | {VERSION}",
        f"RUNNER_REVISION | {RUNNER_REVISION}",
        f"WORKSPACE | {workspace}",
        "SYNTHETIC | TRUE (FICTIONAL, NOT COMPANY DATA)",
        "PROJECT_ROOT_MODIFIED | NO (by design)",
    ]
    status = "FAIL"
    try:
        problems, candidate = preflight(root, report, workspace)
        log.append(f"CANDIDATE | {candidate}")
        if problems:
            for issue in problems:
                log.append(f"FAIL | PREFLIGHT | {issue}")
            raise RuntimeError(f"Preflight found {len(problems)} issue(s)")
        log.append(f"PASS | PREFLIGHT | {len(EXPECTED_DOCS)} Phase 1 files detected")
        files, stores, calendar = dataset(DEFAULT_SEED)
        outcomes = run_checks(DEFAULT_SEED, files, stores, calendar)
        for result, test, detail in outcomes:
            log.append(f"{result} | {test}" + (f" | {detail}" if detail else ""))
        count_pass = sum(s == "PASS" for s, _, _ in outcomes)
        count_fail = sum(s == "FAIL" for s, _, _ in outcomes)
        log.append(f"TESTS | total={len(outcomes)} passed={count_pass} failed={count_fail}")
        if count_fail:
            raise RuntimeError("Internal data tests failed; candidate not staged")
        for name in (STORE_FILE, CALENDAR_FILE, MANIFEST_FILE):
            log.append(f"ARTIFACT_SHA256 | {name} | {digest_bytes(files[name])}")
        log.append(f"COUNTS | stores={len(stores)} lifecycle_days={len(enumerate_days())} "
                   f"calendar_rows={len(calendar)} closures=2")
        log.append("WARNING | Source sales/coverage, budgets, LFL, ETL, SQL and Desktop are NOT tested in P2.1")
        result = verify_or_stage(candidate, files)
        log.append(f"PASS | CANDIDATE | {result}")
        if args.tidy_output:
            if not report.parent.exists():
                report.parent.mkdir(parents=True, exist_ok=True)
            quarantine, moved = tidy_output_directory(report, workspace)
            log.append(f"PASS | OUTPUT_TIDY | {quarantine} | moved={len(moved)}")
            for item in moved:
                log.append(f"MOVED_TO_QUARANTINE | {item}")
        else:
            log.append("INFO | OUTPUT_TIDY | NOT_REQUESTED; existing legacy files left untouched")
        status = "PASS_CANDIDATE_VALIDATED_NOT_APPROVED"
    except Exception as exc:
        log.append(f"FAIL | {type(exc).__name__}: {exc}")
        log.append("TRACE | " + " | ".join(traceback.format_exception_only(type(exc), exc)).strip().replace("\n", " "))
    log.append(f"STATUS={status}")
    log.append(f"END_UTC | {datetime.now(timezone.utc).isoformat()}")
    try:
        old = store_report(report, log, workspace)
        if old:
            print(f"Previous OUTPUT archived: {old}")
        print(f"STATUS={status}")
        print(f"REPORT={report}")
        if status.startswith("PASS"):
            print(f"CANDIDATE={candidate}")
        return 0 if status.startswith("PASS") else 2
    except Exception as log_error:
        print(f"STATUS=FAIL_REPORT_WRITE; error={log_error}", file=sys.stderr)
        print("\n".join(log), file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())

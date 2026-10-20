#!/usr/bin/env python3
"""RetailPulse 360 — P2.3: deterministic full-snapshot scenario *fixtures*.

Candidate only. No mutation of approved P2.1/P2.2, no ETL/publish engine.
Inputs are exactly SHA-pinned P2.1/P2.2 approved files. Each scenario resolves
full sources either to immutable approved P2.2 files or to a complete alternative
snapshot CSV in the P2.3 candidate. All synthetic, standard library only.

Example:
    Run the supported portable entry point: python tools/reproduce.py --output "../retailpulse build"
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
from datetime import date, datetime, timezone
from pathlib import Path

PROJECT = "RetailPulse 360"
CHECKPOINT = "P2.3"
VERSION = "p2.3.0"
SEED = 3602026
CONTRACT = "0.1"
O_ASOF = "2026-12-20"
M_ASOF = "2026-12-27"
PREV_O_ASOF = "2026-10-31"
PREV_M_ASOF = "2026-11-07"
P21_PIN = {
    "dim_store.csv": "9414e58bea035bfe13a2b2698e75a8e47bf3427ef1fba203fb88bd2de9dd7c3d",
    "store_operating_calendar.csv": "d214bc7fdeba2ca7064a031e99fdf7af4587a8b5352b8535ff7968e7f4e895ba",
    "p2_1_manifest.json": "3ee062ce4026af969758224db76b21dd5c817144b87845173fe228eb2f8f5dd3",
    "p2_1_promotion_record.json": "a04c1fc656beb279c3bb8d703686b30a71895879b494a241d5871e05b124686e",
}
P22_PIN = {
    "official_sales_snapshot.csv": "335646fc38fa3f9e8c77b5319f050f1b0e7d48d835446db9c3e71048f0bbc9f9",
    "source_coverage_official.csv": "2a53a40d70b39faf13e3fa925927f6a96a3ad3b0cd4d29678425489dae01ab54",
    "budget_monthly.csv": "206a4a5838ebefcabfdaff2b7e959e1d5edbfc1c12b1f27bc252a0a462f71ec2",
    "dim_marketplace_account.csv": "82063f9c5207d8c4a3aaea1dbc2f6313bd471dde6862ebe0cf73b59ef6a93c3b",
    "bridge_account_store_period.csv": "c88a213ce4e24c4565778c3792e24d2a6a46b9e2588d1ef8f1260bdd5589b2c5",
    "marketplace_daily_snapshot.csv": "fd14e0272f11e92323af0bf4ca78f886a164d0587138b8593a9a874485e7de91",
    "source_coverage_marketplace.csv": "1c3a1913dc18992910f91409ac456030c2d35e6896305c96fd76f6e8954ab612",
    "p2_2_manifest.json": "9e3aef2307e6ca24c11e9c43a58ee35fcbbf21ada7915ff3690270a652bc8f5d",
    "p2_2_promotion_record.json": "8226c54b5dab1760fe767cb2d17a6ef6df0738c66e983aabddab25b0d23f2d39",
}
FIELDS = {
    "official_sales_snapshot.csv": ("store_key", "date_key", "channel_key", "gross_sales_cents", "returns_amount_cents", "net_sales_cents", "transactions", "units", "source_snapshot_id", "lineage_hash"),
    "source_coverage_official.csv": ("store_key", "date_key", "channel_key", "coverage_state", "evidence"),
    "marketplace_daily_snapshot.csv": ("account_key", "date_key", "attributed_retail_net_sales_cents", "orders", "units", "source_snapshot_id", "lineage_hash"),
    "source_coverage_marketplace.csv": ("account_key", "date_key", "coverage_state", "evidence"),
}
CONTRACT_DOCS = ("ARCHITECTURE_DECISIONS.md", "DATA_MODEL_SPEC.md", "KPI_CONTRACTS.md", "PHASE_1_REVIEW.md", "PROJECT_CHARTER.md", "QA_TEST_MATRIX.md", "REPORT_PAGE_MATRIX.md", "SYNTHETIC_GENERATOR_SPEC.md")
OFF = "official_sales_snapshot.csv"
COV_O = "source_coverage_official.csv"
DIG = "marketplace_daily_snapshot.csv"
COV_D = "source_coverage_marketplace.csv"
KEYS = {OFF: ("store_key", "date_key", "channel_key"), COV_O: ("store_key", "date_key", "channel_key"), DIG: ("account_key", "date_key"), COV_D: ("account_key", "date_key")}
BUSINESS_OFF = ("store_key", "date_key", "channel_key", "gross_sales_cents", "returns_amount_cents", "net_sales_cents", "transactions", "units")
BUSINESS_DIG = ("account_key", "date_key", "attributed_retail_net_sales_cents", "orders", "units")


def ensure(test, why):
    if not test:
        raise ValueError(why)


def digest(body):
    return hashlib.sha256(body).hexdigest()


def encode_json(obj):
    return (json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def csv_dump(rows, fields):
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="raise", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def csv_load(data, fields, label):
    ensure(data.endswith(b"\n") and b"\r" not in data, "Noncanonical CSV " + label)
    reader = csv.DictReader(io.StringIO(data.decode("utf-8"), newline=""))
    ensure(tuple(reader.fieldnames or ()) == fields, "Wrong schema " + label)
    rows = list(reader)
    ensure(all(None not in r and all(x is not None for x in r.values()) for r in rows), "Malformed CSV " + label)
    return rows


def key(row, filename):
    return tuple(row[f] for f in KEYS[filename])


def record_hash(row, family):
    names = BUSINESS_OFF if family == "OFFICIAL" else BUSINESS_DIG
    return digest(encode_json({f: row[f] for f in names}))


def change_hash(row):
    return digest(encode_json({k: v for k, v in row.items() if k != "lineage_hash"}))


def update_lineage(row, scenario):
    row["source_snapshot_id"] = "SYN-" + scenario
    row["lineage_hash"] = change_hash(row)


def versioned_csv(rows, filename):
    rows.sort(key=lambda r: (r["date_key"],) + tuple(r[f] for f in KEYS[filename] if f != "date_key"))
    return csv_dump(rows, FIELDS[filename])


def copy_rows(rows):
    return [dict(r) for r in rows]


def safe_file(path, label):
    ensure(path.is_file() and not path.is_symlink(), "Missing or symlink file: " + label)


def safe_dir(path, label):
    ensure(path.is_dir() and not path.is_symlink(), "Missing or symlink directory: " + label)


def within(path, parent):
    return path == parent or parent in path.parents


def check_report(report):
    safe_file(report, "central report")
    lines = set(report.read_text(encoding="utf-8-sig").splitlines())
    ensure("PROJECT | RetailPulse 360" in lines, "Central report belongs to another project")
    if "CHECKPOINT | P2.2-PROMOTION" in lines:
        ensure("STATUS=PASS_P2_2_LOCALLY_PROMOTED_PENDING_REPORT_REVIEW" in lines,
               "P2.2 promotion report did not PASS")
        for filename, expected in P22_PIN.items():
            ensure(f"PUBLISHED_SHA256 | {filename} | {expected}" in lines, "Promotion report SHA absent: " + filename)
    elif "CHECKPOINT | P2.3" in lines:
        ensure("STATUS=PASS_P2_3_CANDIDATE_VALIDATED_PENDING_REPORT_REVIEW" in lines,
               "Previous P2.3 run failed; manual review required")
    else:
        raise ValueError("Central OUTPUT.txt must be successful P2.2 promotion or P2.3 run")


def load_approved(root):
    p21 = root / "data" / "synthetic" / "p2_1"
    p22 = root / "data" / "synthetic" / "p2_2"
    safe_dir(p21, "P2.1")
    safe_dir(p22, "P2.2")
    for folder, pins in ((p21, P21_PIN), (p22, P22_PIN)):
        ensure({p.name for p in folder.iterdir()} == set(pins), f"Approved artifact set changed: {folder}")
        for name, expected in pins.items():
            f = folder / name
            safe_file(f, name)
            ensure(digest(f.read_bytes()) == expected, "Approved SHA differs: " + name)
    with (p21 / "dim_store.csv").open("r", encoding="utf-8", newline="") as stream:
        stores = list(csv.DictReader(stream))
    with (p21 / "store_operating_calendar.csv").open("r", encoding="utf-8", newline="") as stream:
        operating = {(r["store_key"], r["date_key"]) for r in csv.DictReader(stream) if r["is_operating"] == "1"}
    src = {n: (p22 / n).read_bytes() for n in FIELDS}
    rows = {n: csv_load(src[n], FIELDS[n], n) for n in FIELDS}
    man = json.loads((p22 / "p2_2_manifest.json").read_text(encoding="utf-8"))
    ensure(man["seed"] == SEED and man["contract_version"] == CONTRACT, "P2.2 manifest/contract mismatch")
    ensure(man["settings"]["official_asof"] == O_ASOF and man["settings"]["marketplace_asof"] == M_ASOF,
           "Unexpected approved source As-Of")
    ensure(len(stores) == 30 and sum(d <= "20261220" for _, d in operating) == 18219, "Approved operating coverage changed")
    ensure(len(rows[OFF]) == 36438 and len(rows[DIG]) == 21377,
           "Approved source row counts changed")
    return rows, stores, operating


def source_reference(filename):
    return {"location": "APPROVED_P2_2", "filename": filename, "sha256": P22_PIN[filename]}


def internal_reference(relative, body):
    return {"location": "P2_3_CANDIDATE", "path": relative, "sha256": digest(body)}


def build_suite(base, stores, operating):
    payload = {}
    catalog = {}
    ledger = []
    off_by = {key(r, OFF): r for r in base[OFF]}
    dig_by = {key(r, DIG): r for r in base[DIG]}
    stores_by = {r["store_key"]: r for r in stores}
    ensure(len(off_by) == len(base[OFF]) and len(dig_by) == len(base[DIG]), "Baseline duplicate business key")
    ensure(all((r["store_key"], r["date_key"]) in operating for r in base[OFF]), "Unexpected official lifecycle")
    # Confirm archive only covers specific fictional closed stores, with a future archived
    # record to test earlier As-Of exclusion.
    archive_keys = (("S019", "20260901", "RETAIL"), ("S020", "20261101", "PROGRAM"))
    archive_rows = [dict(off_by[k]) for k in archive_keys]
    ensure(all(stores_by[r["store_key"]]["last_trading_date"] for r in archive_rows),
           "Archive must contain only approved synthetic closed stores")
    archive_bytes = csv_dump(archive_rows, FIELDS[OFF])
    archive_manifest = {
        "fixture_state": "TEST_FIXTURE_ONLY_NOT_PROTECTED_PUBLISH_ENGINE",
        "project": PROJECT, "contract_version": CONTRACT,
        "archive_file": "protected_history_fixture/closed_store_official.csv",
        "archive_sha256": digest(archive_bytes),
        "business_keys": ["|".join(k) for k in archive_keys],
        "business_value_sha256": {"|".join(key(r, OFF)): record_hash(r, "OFFICIAL") for r in archive_rows},
        "rows": len(archive_rows), "seed": SEED,
        "rule": "Protected match uses canonical business fields; source snapshot-id is lineage metadata",
    }
    payload["protected_history_fixture/closed_store_official.csv"] = archive_bytes
    payload["protected_history_fixture/archive_manifest.json"] = encode_json(archive_manifest)
    default_files = {name: source_reference(name) for name in FIELDS}
    
    def register(name, change_type, expected_status, changes=None, o_asof=O_ASOF,
                 m_asof=M_ASOF, expect_dq=None, prior=None, archive_state="CLEAN",
                 archive_sha_override=None):
        ensure(name not in catalog, "Duplicate scenario: " + name)
        # each entry is independently resolvable to a COMPLETE snapshot, not a delta file
        files = dict(default_files)
        for filename, items in (changes or {}).items():
            relative = f"scenarios/{name}/{filename}"
            body = versioned_csv(items, filename)
            payload[relative] = body
            files[filename] = internal_reference(relative, body)
        catalog[name] = {
            "scenario_id": name,
            "description": change_type,
            "official_snapshot_id": f"{name}-OFFICIAL",
            "marketplace_snapshot_id": f"{name}-MARKETPLACE",
            "official_asof": o_asof,
            "marketplace_asof": m_asof,
            "snapshot_files": files,
            "unchanged_dimensions_and_budget": {
                "budget_monthly": source_reference("budget_monthly.csv"),
                "account_master": source_reference("dim_marketplace_account.csv"),
                "account_ownership": source_reference("bridge_account_store_period.csv"),
            },
            "previous_snapshots": prior or {"official": "APPROVED_P2_2", "marketplace": "APPROVED_P2_2"},
            "protected_archive": {
                "archive_file": "protected_history_fixture/closed_store_official.csv",
                "sha256_claimed": archive_sha_override or digest(archive_bytes),
                "manifest_file": "protected_history_fixture/archive_manifest.json",
                "state": archive_state,
            },
            "expected_qa": expect_dq or [],
            "expected_publish_status": expected_status,
            "stage": "GENERATOR_FIXTURE_ONLY; NOT ACTUAL SNAPSHOT-PROCESSOR QA",
        }
    def ledger_add(scenario, family, business_key, typ, before, after, qa, status):
        ledger.append({"scenario_id": scenario, "family": family, "business_key": "|".join(business_key),
                       "change_type": typ, "before_value_hash": record_hash(before, family) if before else None,
                       "after_value_hash": record_hash(after, family) if after else None,
                       "expected_qa_check": qa, "expected_publish_status": status})

    register("GEN-BASE", "P2.2 certified baseline; independent source cutoffs", "EXPECTED_PASS")
    # ADD: previous is a valid *explicitly retracted* source; incoming returns to
    # approved baseline. This is a real new business key relative to prior snapshot.
    add_key = ("S001", "20261220", "RETAIL")
    ensure(add_key in off_by, "ADD fixture missing official key")
    add_prev = [dict(r) for r in base[OFF] if key(r, OFF) != add_key]
    cov_add = copy_rows(base[COV_O])
    for row in cov_add:
        if key(row, COV_O) == add_key:
            row.update(coverage_state="RETRACTED_CONFIRMED", evidence="P2.3-FIXTURE-PRIOR-RETRACTION")
    prev_off_path = "fixtures/SNAP-ADD/previous_official_sales_snapshot.csv"
    prev_cov_path = "fixtures/SNAP-ADD/previous_source_coverage_official.csv"
    payload[prev_off_path] = versioned_csv(add_prev, OFF)
    payload[prev_cov_path] = versioned_csv(cov_add, COV_O)
    prev_meta = {"official": {OFF: internal_reference(prev_off_path, payload[prev_off_path]),
                             COV_O: internal_reference(prev_cov_path, payload[prev_cov_path])},
                 "marketplace": "APPROVED_P2_2"}
    register("SNAP-ADD", "Restore a previously retracted unprotected official business key", "EXPECTED_PASS",
             prior=prev_meta)
    ledger_add("SNAP-ADD", "OFFICIAL", add_key, "ADD", None, off_by[add_key], "ADD_UNPROTECTED", "EXPECTED_PASS")

    correct_key = ("S002", "20260315", "RETAIL")
    ensure(correct_key in off_by, "CORRECT fixture missing")
    old = off_by[correct_key]
    altered = dict(old)
    altered["gross_sales_cents"] = str(int(old["gross_sales_cents"]) + 111)
    altered["net_sales_cents"] = str(int(old["net_sales_cents"]) + 111)
    update_lineage(altered, "SNAP-CORRECT")
    register("SNAP-CORRECT", "Correct existing unprotected Official key without additive duplication", "EXPECTED_PASS",
             changes={OFF: [altered if key(r, OFF) == correct_key else dict(r) for r in base[OFF]]})
    ledger_add("SNAP-CORRECT", "OFFICIAL", correct_key, "CORRECT", old, altered, "REPLACE_BY_KEY", "EXPECTED_PASS")

    retract_key = ("S003", "20260515", "PROGRAM")
    ensure(retract_key in off_by, "RETRACT fixture missing")
    cov_retract = copy_rows(base[COV_O])
    for row in cov_retract:
        if key(row, COV_O) == retract_key:
            row.update(coverage_state="RETRACTED_CONFIRMED", evidence="P2.3-EXPLICIT-RETRACTION-LEDGER")
    register("SNAP-RETRACT", "Complete full snapshot with explicitly confirmed unprotected retraction", "EXPECTED_PASS",
             changes={OFF: [dict(r) for r in base[OFF] if key(r, OFF) != retract_key], COV_O: cov_retract})
    ledger_add("SNAP-RETRACT", "OFFICIAL", retract_key, "RETRACT", off_by[retract_key], None,
               "RETRACTED_CONFIRMED", "EXPECTED_PASS")

    earlier_off = [dict(r) for r in base[OFF] if r["date_key"] <= PREV_O_ASOF.replace("-", "")]
    earlier_cov_o = [dict(r) for r in base[COV_O] if r["date_key"] <= PREV_O_ASOF.replace("-", "")]
    earlier_dig = [dict(r) for r in base[DIG] if r["date_key"] <= PREV_M_ASOF.replace("-", "")]
    earlier_cov_d = [dict(r) for r in base[COV_D] if r["date_key"] <= PREV_M_ASOF.replace("-", "")]
    register("SNAP-EARLIER-ASOF", "Valid full replacement with earlier independent official/digital As-Of", "EXPECTED_PASS",
             changes={OFF: earlier_off, COV_O: earlier_cov_o, DIG: earlier_dig, COV_D: earlier_cov_d},
             o_asof=PREV_O_ASOF, m_asof=PREV_M_ASOF,
             expect_dq=["ARCHIVE_RESTORE_ONLY_KEYS_ON_OR_BEFORE_OFFICIAL_ASOF"])
    ledger_add("SNAP-EARLIER-ASOF", "OFFICIAL", ("SOURCE_ASOF",), "EARLIER_ASOF", None, None,
               "ALLOW_VERIFIED_HISTORICAL_ROLLBACK", "EXPECTED_PASS")

    restore_key = archive_keys[0]
    register("SNAP-ARCHIVE-RESTORE", "Protected source key missing; archived record must be restored by Phase 3", "EXPECTED_PASS",
             changes={OFF: [dict(r) for r in base[OFF] if key(r, OFF) != restore_key],
                      COV_O: [dict(r) for r in base[COV_O] if key(r, COV_O) != restore_key]},
             expect_dq=["PROTECTED_MISSING_RESTORE"])
    ledger_add("SNAP-ARCHIVE-RESTORE", "OFFICIAL", restore_key, "PROTECTED_MISSING",
               off_by[restore_key], None, "RESTORE_HASH_VERIFIED_ARCHIVE", "EXPECTED_PASS")

    conflict = dict(off_by[restore_key])
    conflict["gross_sales_cents"] = str(int(conflict["gross_sales_cents"]) + 500)
    conflict["net_sales_cents"] = str(int(conflict["net_sales_cents"]) + 500)
    update_lineage(conflict, "SNAP-ARCHIVE-CONFLICT")
    register("SNAP-ARCHIVE-CONFLICT", "Incoming protected key disagrees with signed archive", "EXPECTED_BLOCK",
             changes={OFF: [conflict if key(r, OFF) == restore_key else dict(r) for r in base[OFF]]},
             expect_dq=["PROTECTED_VALUE_CONFLICT"], archive_state="CONFLICT")
    ledger_add("SNAP-ARCHIVE-CONFLICT", "OFFICIAL", restore_key, "PROTECTED_CONFLICT",
               off_by[restore_key], conflict, "BLOCK_PROTECTED_CONFLICT", "EXPECTED_BLOCK")

    register("SNAP-ARCHIVE-HASH", "Tampered declared protected archive digest; actual file remains unchanged", "EXPECTED_BLOCK",
             expect_dq=["ARCHIVE_SHA256_MISMATCH"], archive_state="BAD_DECLARED_SHA",
             archive_sha_override="0" * 64)
    ledger_add("SNAP-ARCHIVE-HASH", "OFFICIAL", ("PROTECTED_ARCHIVE",), "BAD_ARCHIVE_HASH", None, None,
               "BLOCK_INVALID_PROTECTED_ARCHIVE", "EXPECTED_BLOCK")

    dupkey = ("S004", "20260901", "RETAIL")
    ensure(dupkey in off_by, "Duplicate fixture key missing")
    dup_off = copy_rows(base[OFF]); dup_off.append(dict(off_by[dupkey]))
    register("SNAP-DUPLICATE-KEY", "Incoming source duplicate full business key", "EXPECTED_BLOCK",
             changes={OFF: dup_off}, expect_dq=["DUPLICATE_BUSINESS_KEY"])
    ledger_add("SNAP-DUPLICATE-KEY", "OFFICIAL", dupkey, "DUPLICATE_KEY", off_by[dupkey], off_by[dupkey],
               "BLOCK_DUPLICATE_KEY", "EXPECTED_BLOCK")

    unknown_key = ("S005", "20261001", "RETAIL")
    ensure(unknown_key in off_by, "Unknown store fixture key missing")
    unknown = dict(off_by[unknown_key]); unknown["store_key"] = "S999"
    update_lineage(unknown, "SNAP-UNKNOWN-STORE")
    register("SNAP-UNKNOWN-STORE", "Unknown Store FK in official full source", "EXPECTED_BLOCK",
             changes={OFF: [unknown if key(r, OFF) == unknown_key else dict(r) for r in base[OFF]]},
             expect_dq=["UNKNOWN_STORE_FK"])
    ledger_add("SNAP-UNKNOWN-STORE", "OFFICIAL", ("S999", unknown_key[1], unknown_key[2]), "INVALID_FK",
               off_by[unknown_key], unknown, "BLOCK_UNKNOWN_STORE", "EXPECTED_BLOCK")

    missing_key = ("S007", "20260301", "PROGRAM")
    ensure(missing_key in off_by, "Missing coverage fixture key missing")
    register("SNAP-MISSING-COVERAGE", "Expected reported-value key absent from source with no retraction evidence", "EXPECTED_BLOCK",
             changes={OFF: [dict(r) for r in base[OFF] if key(r, OFF) != missing_key]},
             expect_dq=["MISSING_EXPECTED_NOT_ZERO"])
    ledger_add("SNAP-MISSING-COVERAGE", "OFFICIAL", missing_key, "MISSING_EXPECTED",
               off_by[missing_key], None, "BLOCK_MISSING_EXPECTED", "EXPECTED_BLOCK")

    negatives = [r for r in base[OFF] if int(r["net_sales_cents"]) < 0]
    zeros = [r for r in base[OFF] if all(int(r[f]) == 0 for f in ("gross_sales_cents", "returns_amount_cents", "net_sales_cents", "transactions", "units"))]
    ensure(negatives and zeros, "P2.2 lacks valid negative or verified zero cases")
    register("SNAP-NEGATIVE-VALID", "Existing return-only negative net sales: expected business case", "EXPECTED_PASS",
             expect_dq=["VALID_NEGATIVE_NET_ALLOWED"])
    ledger_add("SNAP-NEGATIVE-VALID", "OFFICIAL", key(negatives[0], OFF), "VALID_NEGATIVE", None, negatives[0],
               "EXPECTED_NEGATIVE_CASE", "EXPECTED_PASS")
    register("SNAP-ZERO-VALID", "Existing explicit reported-zero active day: not missing", "EXPECTED_PASS",
             expect_dq=["REPORTED_ZERO_IS_VALID"])
    ledger_add("SNAP-ZERO-VALID", "OFFICIAL", key(zeros[0], OFF), "VALID_ZERO", None, zeros[0],
               "EXPECTED_ZERO_CASE", "EXPECTED_PASS")
    register("SNAP-DIGITAL-AHEAD", "Marketplace data retained seven days ahead of Official As-Of", "EXPECTED_PASS",
             expect_dq=["MATCHED_THROUGH_OFFICIAL_ASOF"])
    ledger_add("SNAP-DIGITAL-AHEAD", "MARKETPLACE", ("SOURCE_ASOF",), "DIGITAL_AHEAD", None, None,
               "MATCHED_PERIOD_NOT_ADDITIVE", "EXPECTED_PASS")

    # Pick digital record with a material positive value for its own safe correction.
    positive_dig = next(r for r in base[DIG] if r["account_key"] == "A001" and int(r["attributed_retail_net_sales_cents"]) > 500)
    dig_key = key(positive_dig, DIG)
    dig_corrected = dict(positive_dig)
    dig_corrected["attributed_retail_net_sales_cents"] = str(int(positive_dig["attributed_retail_net_sales_cents"]) + 1)
    update_lineage(dig_corrected, "SNAP-DIGITAL-CORRECT")
    register("SNAP-DIGITAL-CORRECT", "Correct one unprotected digital account-day amount", "EXPECTED_PASS",
             changes={DIG: [dig_corrected if key(r, DIG) == dig_key else dict(r) for r in base[DIG]]})
    ledger_add("SNAP-DIGITAL-CORRECT", "MARKETPLACE", dig_key, "CORRECT", positive_dig, dig_corrected,
               "REPLACE_DIGITAL_BY_KEY", "EXPECTED_PASS")

    digital_prev = [dict(r) for r in base[DIG] if key(r, DIG) != dig_key]
    digital_prev_cov = copy_rows(base[COV_D])
    for row in digital_prev_cov:
        if key(row, COV_D) == dig_key:
            row.update(coverage_state="RETRACTED_CONFIRMED", evidence="P2.3-FIXTURE-PRIOR-DIGITAL-RETRACTION")
    dp = "fixtures/SNAP-DIGITAL-ADD/previous_marketplace_daily_snapshot.csv"
    dc = "fixtures/SNAP-DIGITAL-ADD/previous_source_coverage_marketplace.csv"
    payload[dp] = versioned_csv(digital_prev, DIG)
    payload[dc] = versioned_csv(digital_prev_cov, COV_D)
    register("SNAP-DIGITAL-ADD", "Add previously retracted digital business key", "EXPECTED_PASS",
             prior={"official": "APPROVED_P2_2", "marketplace": {DIG: internal_reference(dp, payload[dp]), COV_D: internal_reference(dc, payload[dc])}})
    ledger_add("SNAP-DIGITAL-ADD", "MARKETPLACE", dig_key, "ADD", None, positive_dig,
               "ADD_UNPROTECTED_DIGITAL", "EXPECTED_PASS")

    digital_cov_r = copy_rows(base[COV_D])
    for row in digital_cov_r:
        if key(row, COV_D) == dig_key:
            row.update(coverage_state="RETRACTED_CONFIRMED", evidence="P2.3-EXPLICIT-DIGITAL-RETRACTION")
    register("SNAP-DIGITAL-RETRACT", "Retract unprotected digital account-day with explicit evidence", "EXPECTED_PASS",
             changes={DIG: [dict(r) for r in base[DIG] if key(r, DIG) != dig_key], COV_D: digital_cov_r})
    ledger_add("SNAP-DIGITAL-RETRACT", "MARKETPLACE", dig_key, "RETRACT", positive_dig, None,
               "RETRACTED_CONFIRMED", "EXPECTED_PASS")

    # Deliberately force impossible matched digital sales > Retail, preserving raw anomaly.
    maps = []
    # Only link a positive, single-account store-day to an official Retail row.
    owner_rows = base[DIG]
    selected, selected_ret = None, None
    # Link A001 to S001 in its valid primary mapping. Other accounts can exist,
    # but one oversized account by itself is sufficient to invalidate the group.
    for r in owner_rows:
        if r["account_key"] != "A001" or r["date_key"] > O_ASOF.replace("-", ""):
            continue
        ret = off_by.get(("S001", r["date_key"], "RETAIL"))
        if ret and int(ret["net_sales_cents"]) > 0:
            selected, selected_ret = r, ret
            break
    ensure(selected is not None, "Digital mismatch fixture unavailable")
    big = dict(selected)
    big["attributed_retail_net_sales_cents"] = str(int(selected_ret["net_sales_cents"]) + 10000)
    update_lineage(big, "SNAP-DIGITAL-MISMATCH")
    register("SNAP-DIGITAL-MISMATCH", "Attribution exceeds same store/date Official Retail sales", "EXPECTED_DQ_REVIEW",
             changes={DIG: [big if key(r, DIG) == key(selected, DIG) else dict(r) for r in base[DIG]]},
             expect_dq=["DIGITAL_EXCEEDS_MATCHED_RETAIL"])
    ledger_add("SNAP-DIGITAL-MISMATCH", "MARKETPLACE", key(selected, DIG), "INVALID_ATTRIBUTION",
               selected, big, "DIGITAL_SUBSET_DQ_REVIEW", "EXPECTED_DQ_REVIEW")

    register("SNAP-PUBLISH-FAIL", "Fault injection directive: fail pre-pointer swap; NO publication performed in P2.3", "EXPECTED_BLOCK",
             expect_dq=["SIMULATE_ATOMIC_PUBLISH_FAILURE"], archive_state="CLEAN")
    ledger_add("SNAP-PUBLISH-FAIL", "CONTROL", ("ACTIVE_GENERATION",), "FAULT_INJECTION", None, None,
               "ATOMIC_ROLLBACK_PHASE3", "EXPECTED_BLOCK")
    register("SNAP-IDEMPOTENT", "Exact replay of approved full snapshots; no accumulating rows", "EXPECTED_PASS")
    ledger_add("SNAP-IDEMPOTENT", "CONTROL", ("REPLAY",), "IDEMPOTENT", None, None,
               "BYTE_IDENTICAL_REPLAY_PHASE3", "EXPECTED_PASS")

    # The manifest uses no wall-clock values or local machine paths.
    ledger.sort(key=lambda r: (r["scenario_id"], r["family"], r["business_key"], r["change_type"]))
    payload["scenario_change_ledger.csv"] = csv_dump(ledger, (
        "scenario_id", "family", "business_key", "change_type", "before_value_hash",
        "after_value_hash", "expected_qa_check", "expected_publish_status"))
    # csv.DictWriter serializes None as empty string; that's canonical here.
    for name, spec in catalog.items():
        payload[f"scenarios/{name}/scenario.json"] = encode_json(spec)
    manifest = {
        "project": PROJECT, "checkpoint": CHECKPOINT, "generator_version": VERSION,
        "contract_version": CONTRACT, "seed": SEED,
        "classification": "100% SYNTHETIC / FICTIONAL",
        "state": "CANDIDATE_ONLY_NOT_APPROVED",
        "approved_p2_1_sha256": P21_PIN,
        "approved_p2_2_sha256": P22_PIN,
        "scenario_count": len(catalog),
        "scenario_ids": sorted(catalog),
        "scenario_expected_counts": dict(sorted(Counter(c["expected_publish_status"] for c in catalog.values()).items())),
        "scenarios": {k: catalog[k] for k in sorted(catalog)},
        "protected_archive_fixture_sha256": digest(archive_bytes),
        "ledger_rows": len(ledger),
        "artifacts": {name: {"sha256": digest(body), "size_bytes": len(body)} for name, body in sorted(payload.items())},
        "notes": [
            "Each scenario resolves to full source snapshots through certified APPROVED_P2_2 references or candidate-contained complete CSVs.",
            "This is a generator fixture suite; expected statuses are NOT actual ETL / protected-history / atomic-publish QA results.",
            "Source-reporting gaps require explicit source coverage proof; do not turn Missing into Zero.",
            "Protected archive is a signed synthetic fixture, not yet an operational immutable archive.",
            "2026 source dates are fictional simulation, NOT observed business data.",
        ],
    }
    payload["p2_3_manifest.json"] = encode_json(manifest)
    return payload, manifest, catalog, ledger


def validate_fixture(payload, manifest, catalog, ledger, base, stores, operating):
    tests = []
    def check(label, fn):
        try:
            fn(); tests.append(("PASS", label, "OK"))
        except Exception as exc:
            tests.append(("FAIL", label, f"{type(exc).__name__}: {exc}"))

    def require(label, condition):
        ensure(condition, label)

    def resolve(reference):
        if reference["location"] == "APPROVED_P2_2":
            name = reference["filename"]
            ensure(reference["sha256"] == P22_PIN[name], "Referenced approved SHA incorrect")
            return csv_dump(base[name], FIELDS[name])  # canonical reserialization
        ensure(reference["location"] == "P2_3_CANDIDATE", "Unknown fixture reference")
        body = payload[reference["path"]]
        ensure(digest(body) == reference["sha256"], "Fixture file SHA mismatch")
        return body

    def rows_for(name, filename):
        return csv_load(resolve(catalog[name]["snapshot_files"][filename]), FIELDS[filename], filename)

    check("P2.3-01_LINEAGE", lambda: require("Pinned v0.1 ancestry", manifest["approved_p2_1_sha256"] == P21_PIN and manifest["approved_p2_2_sha256"] == P22_PIN and manifest["seed"] == SEED))
    check("P2.3-02_SCENARIO_MATRIX", lambda: require("Scenario suite complete", len(catalog) == 20 and set(manifest["scenario_ids"]) == set(catalog)))
    check("P2.3-03_REFERENCES", lambda: [require("Reference SHA", digest(resolve(ref)) == ref["sha256"]) for s in catalog.values() for ref in s["snapshot_files"].values()])
    check("P2.3-04_CANONICAL_MANIFEST", lambda: require("Manifest self-contained", all(digest(payload[n]) == entry["sha256"] and len(payload[n]) == entry["size_bytes"] for n, entry in manifest["artifacts"].items())))
    check("P2.3-05_CHANGE_LEDGER", lambda: require("Ledger scenarios and status", len(ledger) == manifest["ledger_rows"] and all(r["scenario_id"] in catalog and r["expected_publish_status"] == catalog[r["scenario_id"]]["expected_publish_status"] for r in ledger)))
    check("P2.3-06_ARCHIVE_FIXTURE", lambda: require("Protected hash and closure", digest(payload["protected_history_fixture/closed_store_official.csv"]) == manifest["protected_archive_fixture_sha256"] and len(csv_load(payload["protected_history_fixture/closed_store_official.csv"], FIELDS[OFF], "archive")) == 2))
    check("P2.3-07_ADD", lambda: require("Incoming restores exactly one official key", len(rows_for("SNAP-ADD", OFF)) == len(base[OFF]) and len(csv_load(payload["fixtures/SNAP-ADD/previous_official_sales_snapshot.csv"], FIELDS[OFF], "prior")) == len(base[OFF])-1))
    check("P2.3-08_CORRECT", lambda: require("One and only one corrected row", sum(a != b for a, b in zip(rows_for("SNAP-CORRECT", OFF), base[OFF])) == 1 and len(rows_for("SNAP-CORRECT", OFF)) == len(base[OFF])))
    check("P2.3-09_RETRACT", lambda: require("One row retracted and explicitly reported", len(rows_for("SNAP-RETRACT", OFF)) == len(base[OFF])-1 and sum(r["coverage_state"] == "RETRACTED_CONFIRMED" for r in rows_for("SNAP-RETRACT", COV_O)) == 1))
    check("P2.3-10_EARLIER_ASOF", lambda: require("Both full sources bounded", all(r["date_key"] <= "20261031" for r in rows_for("SNAP-EARLIER-ASOF", OFF)) and all(r["date_key"] <= "20261107" for r in rows_for("SNAP-EARLIER-ASOF", DIG)) and catalog["SNAP-EARLIER-ASOF"]["official_asof"] == PREV_O_ASOF))
    check("P2.3-11_ARCHIVE_RESTORE", lambda: require("Protected missing key present in signed archive only", len(rows_for("SNAP-ARCHIVE-RESTORE", OFF)) == len(base[OFF])-1 and len(rows_for("SNAP-ARCHIVE-RESTORE", COV_O)) == len(base[COV_O])-1))
    def check_conflict():
        archived = csv_load(payload["protected_history_fixture/closed_store_official.csv"], FIELDS[OFF], "archive")
        byk = {key(r, OFF): r for r in rows_for("SNAP-ARCHIVE-CONFLICT", OFF)}
        require("Different protected business hash", record_hash(byk[key(archived[0], OFF)], "OFFICIAL") != record_hash(archived[0], "OFFICIAL"))
    check("P2.3-12_ARCHIVE_CONFLICT", check_conflict)
    check("P2.3-13_ARCHIVE_HASH", lambda: require("Bad declared digest is caught", catalog["SNAP-ARCHIVE-HASH"]["protected_archive"]["sha256_claimed"] != manifest["protected_archive_fixture_sha256"]))
    check("P2.3-14_DUPLICATE", lambda: require("Duplicate key preserved for QA", len(rows_for("SNAP-DUPLICATE-KEY", OFF)) == len(base[OFF])+1 and len({key(r, OFF) for r in rows_for("SNAP-DUPLICATE-KEY", OFF)}) == len(base[OFF])))
    check("P2.3-15_UNKNOWN_STORE", lambda: require("Unknown store is injected", any(r["store_key"] == "S999" for r in rows_for("SNAP-UNKNOWN-STORE", OFF))))
    check("P2.3-16_MISSING_COVERAGE", lambda: require("Expected coverage remains without row", len(rows_for("SNAP-MISSING-COVERAGE", OFF)) == len(base[OFF])-1 and len(rows_for("SNAP-MISSING-COVERAGE", COV_O)) == len(base[COV_O])))
    check("P2.3-17_VALID_NEGATIVE_ZERO", lambda: require("Valid negative/zero exists", any(int(r["net_sales_cents"]) < 0 for r in base[OFF]) and any(int(r["gross_sales_cents"]) == int(r["returns_amount_cents"]) == int(r["net_sales_cents"]) == 0 for r in base[OFF])))
    check("P2.3-18_DIGITAL_AHEAD", lambda: require("Distinct source AsOf", catalog["SNAP-DIGITAL-AHEAD"]["marketplace_asof"] > catalog["SNAP-DIGITAL-AHEAD"]["official_asof"] and any(r["date_key"] > "20261220" for r in base[DIG])))
    check("P2.3-19_DIGITAL_CHANGES", lambda: require("Digital correction/add/retract", len(rows_for("SNAP-DIGITAL-CORRECT", DIG)) == len(base[DIG]) and len(rows_for("SNAP-DIGITAL-RETRACT", DIG)) == len(base[DIG])-1 and len(csv_load(payload["fixtures/SNAP-DIGITAL-ADD/previous_marketplace_daily_snapshot.csv"], FIELDS[DIG], "digital prior")) == len(base[DIG])-1))
    check("P2.3-20_DIGITAL_MISMATCH", lambda: require("Matched attribution exceeds same store-day Retail", any(
        int(r["attributed_retail_net_sales_cents"]) > int(next(
            (o["net_sales_cents"] for o in base[OFF] if o["store_key"] == "S001" and
             o["date_key"] == r["date_key"] and o["channel_key"] == "RETAIL"), "999999999999"))
        for r in rows_for("SNAP-DIGITAL-MISMATCH", DIG) if r["account_key"] == "A001")))
    check("P2.3-21_FAULT_IDEMPOTENCE", lambda: require("Fault and replay directives", catalog["SNAP-PUBLISH-FAIL"]["expected_publish_status"] == "EXPECTED_BLOCK" and catalog["SNAP-IDEMPOTENT"]["expected_publish_status"] == "EXPECTED_PASS" and all(r["location"] == "APPROVED_P2_2" for r in catalog["SNAP-IDEMPOTENT"]["snapshot_files"].values())))
    check("P2.3-22_CANONICAL_BYTES", lambda: require("Canonical manifest JSON", payload["p2_3_manifest.json"] == encode_json(manifest)))
    return tests


def archive_report(report, workspace, lines):
    history = workspace / "report_history"
    staging = workspace / "report_staging"
    ensure(not history.is_symlink() and not staging.is_symlink(), "Report staging/history symlink")
    history.mkdir(parents=True, exist_ok=True)
    staging.mkdir(parents=True, exist_ok=True)
    original = report.read_bytes()
    mark = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    history_file = history / f"OUTPUT_{mark}_{digest(original)[:12]}.txt"
    with history_file.open("xb") as f:
        f.write(original)
    handle, pathname = tempfile.mkstemp(prefix="P2_3_", suffix=".tmp", dir=staging)
    temporary = Path(pathname)
    try:
        with os.fdopen(handle, "wb") as f:
            f.write(("\n".join(lines) + "\n").encode("utf-8"))
            f.flush(); os.fsync(f.fileno())
        os.replace(temporary, report)
    finally:
        if temporary.exists():
            temporary.unlink()


def publish_candidate(target, contents):
    ensure(not target.is_symlink(), "Unsafe candidate symlink")
    if target.exists():
        safe_dir(target, "candidate")
        found = {str(p.relative_to(target)): p for p in target.rglob("*") if p.is_file()}
        ensure(set(found) == set(contents), "Candidate set conflict; existing directory unchanged")
        for name, path in found.items():
            ensure(not path.is_symlink() and digest(path.read_bytes()) == digest(contents[name]),
                   "Candidate byte conflict: " + name)
        return "IDENTICAL_CANDIDATE_UNCHANGED"
    staging = Path(tempfile.mkdtemp(prefix=".P2_3_stage_", dir=target.parent))
    committed = False
    try:
        for name, body in contents.items():
            dest = staging / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(body)
        ensure(all(digest((staging/name).read_bytes()) == digest(body) for name,body in contents.items()),
               "Staged payload SHA mismatch")
        ensure(not target.exists(), "Candidate appeared during staging")
        staging.rename(target)
        committed = True
        return "CREATED_NEW_ATOMIC_CANDIDATE_DIRECTORY"
    finally:
        if staging.exists() and not committed:
            shutil.rmtree(staging)


def main():
    p = argparse.ArgumentParser(description="P2.3 deterministic full snapshot scenario fixture generator (candidate only)")
    p.add_argument("--root", required=True)
    p.add_argument("--report", help="Central output path, outside project; default <project.parent>/output/OUTPUT.txt")
    args = p.parse_args()
    supplied_root = Path(args.root).expanduser()
    supplied_report = Path(args.report).expanduser() if args.report else supplied_root.parent / "output" / "OUTPUT.txt"
    try:
        ensure(not supplied_root.is_symlink() and not supplied_report.is_symlink(), "Unsafe root/report symlink")
        root = supplied_root.resolve()
        report = supplied_report.resolve()
        workspace = (root.parent / "retailpulse360_dev").resolve()
        ensure(not workspace.is_symlink(), "Unsafe workspace")
        ensure(report.name == "OUTPUT.txt" and not within(report, root) and not within(workspace, root)
               and not within(workspace, report.parent), "Workspace or report path unsafe")
        safe_dir(root, "project root")
        safe_dir(report.parent, "output dir")
        ensure(sorted(p.name for p in report.parent.iterdir()) == ["OUTPUT.txt"],
               "Central output directory must contain OUTPUT.txt ONLY")
        check_report(report)
        safe_dir(workspace, "existing dev workspace")
    except Exception as exc:
        print(f"STATUS=BLOCKED_PREFLIGHT | {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3

    log = [f"PROJECT | {PROJECT}", f"CHECKPOINT | {CHECKPOINT}",
           "CONTRACT | Phase 1 v0.1 APPROVED DEC-01..DEC-10",
           f"RUN_UTC | {datetime.now(timezone.utc).isoformat()}",
           f"RUN_ID | P2_3_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}",
           "MODE | GENERATE_VALIDATE_SNAPSHOT_SCENARIOS_CANDIDATE_ONLY",
           "SYNTHETIC | TRUE", f"PROJECT_ROOT | {root}",
           f"REPORT | {report}", f"WORKSPACE | {workspace}",
           "AUTHORIZED_PROJECT_WRITES | NONE", f"VERSION | {VERSION}", f"SEED | {SEED}"]
    state = "FAIL_P2_3_CANDIDATE_BLOCKED"
    try:
        for name in CONTRACT_DOCS:
            safe_file(root/"docs"/name, name)
        log.append("PASS | PHASE_1 | 8 approved contracts found")
        before = {str(f.relative_to(root)): digest(f.read_bytes()) for f in root.rglob("*") if f.is_file()}
        base, stores, operating = load_approved(root)
        log.append("PASS | APPROVED_INPUTS | P2.1 four and P2.2 nine exact SHA-256 verified")
        payload, manifest, catalog, ledger = build_suite(base, stores, operating)
        tests = validate_fixture(payload, manifest, catalog, ledger, base, stores, operating)
        for result, name, detail in tests:
            log.append(f"{result} | {name} | {detail}")
        failures = [t for t in tests if t[0] == "FAIL"]
        log.append(f"TESTS | total={len(tests)} passed={len(tests)-len(failures)} failed={len(failures)}")
        ensure(not failures, "Fixture validation failed; no candidate publication")
        # Immutable reproducibility using separate full generation, without run timestamp.
        regenerated, manifest2, _, _ = build_suite(base, stores, operating)
        ensure({n: digest(b) for n,b in regenerated.items()} == {n: digest(b) for n,b in payload.items()},
               "Same inputs failed byte-level deterministic build")
        log.append("PASS | REPRODUCIBILITY | Byte-exact regenerated scenario suite")
        candidate = workspace / "P2_3_CANDIDATE"
        decision = publish_candidate(candidate, payload)
        log.append(f"PASS | CANDIDATE | {decision}")
        log.append(f"CANDIDATE | {candidate}")
        log.append(f"SCENARIOS | total={len(catalog)} expected_pass={sum(s['expected_publish_status']=='EXPECTED_PASS' for s in catalog.values())} expected_block={sum(s['expected_publish_status']=='EXPECTED_BLOCK' for s in catalog.values())} expected_review={sum(s['expected_publish_status']=='EXPECTED_DQ_REVIEW' for s in catalog.values())}")
        log.append(f"ARTIFACTS | count={len(payload)} total_bytes={sum(map(len,payload.values()))}")
        log.append(f"ARTIFACT_SHA256 | p2_3_manifest.json | {digest(payload['p2_3_manifest.json'])}")
        log.append(f"ARTIFACT_SHA256 | scenario_change_ledger.csv | {digest(payload['scenario_change_ledger.csv'])}")
        after = {str(f.relative_to(root)): digest(f.read_bytes()) for f in root.rglob("*") if f.is_file()}
        ensure(before == after, "Approved project root changed during P2.3")
        log.append("PASS | PROJECT_ROOT_UNCHANGED | All original files SHA byte-identical")
        ensure(sorted(p.name for p in report.parent.iterdir()) == ["OUTPUT.txt"], "Unexpected central output entry")
        log.append("PASS | OUTPUT_EXCLUSIVE | Exactly OUTPUT.txt; other artifacts in dev workspace")
        log.append("WARNING | EXPECTED_PASS / EXPECTED_BLOCK are fixture specifications, NOT actual Phase 3 processor test results")
        log.append("WARNING | Archive restore/conflict/hash and atomic-failure behaviors must be executed in Phase 3")
        log.append("WARNING | No SQL, DAX, Power BI or post-release data tests were performed")
        state = "PASS_P2_3_CANDIDATE_VALIDATED_PENDING_REPORT_REVIEW"
    except Exception as exc:
        log.append(f"FAIL | {type(exc).__name__}: {exc}")
        log.append("TRACE | " + " ".join(traceback.format_exception_only(type(exc),exc)).strip())
        log.append("SAFEGUARD | No approved project content intentionally modified; candidate never overwritten on conflict")
    log.append(f"STATUS={state}")
    log.append(f"END_UTC | {datetime.now(timezone.utc).isoformat()}")
    try:
        archive_report(report, workspace, log)
    except Exception as exc:
        print(f"STATUS=FAIL_REPORT_WRITE | {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    print(f"STATUS={state}\nREPORT={report}")
    return 0 if state.startswith("PASS_") else 2


if __name__ == "__main__":
    sys.exit(main())

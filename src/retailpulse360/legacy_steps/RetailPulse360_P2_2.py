#!/usr/bin/env python3
r"""RetailPulse 360 / P2.2 — deterministic synthetic commercial source candidates.

No third-party dependencies. Creates candidate ONLY outside project; never promotes,
changes Phase-1 contracts or edits P2.1 approved artifacts. Report's *only* entry
in central output folder is OUTPUT.txt, configured with --report.

PowerShell:
    Run the supported portable entry point: python tools/reproduce.py --output "../retailpulse build"
"""
from __future__ import annotations

import argparse
import calendar
import csv
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import traceback
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PROJECT = "RetailPulse 360"
CHECKPOINT = "P2.2"
CONTRACT = "0.1"
VERSION = "p2.2.0"
SEED = 3602026
START = date(2025, 1, 1)
END = date(2026, 12, 31)
OFFICIAL_ASOF = date(2026, 12, 20)  # Fictional future-dated scenario, NOT observed sales.
MARKETPLACE_ASOF = date(2026, 12, 27)
SNAP_OFFICIAL = "GEN-BASE-OFFICIAL-v1"
SNAP_DIGITAL = "GEN-BASE-MARKETPLACE-v1"
BUDGET_VERSION = "GEN-BASE-BUDGET-v1"
APPROVED_P21 = {
    "dim_store.csv": "9414e58bea035bfe13a2b2698e75a8e47bf3427ef1fba203fb88bd2de9dd7c3d",
    "store_operating_calendar.csv": "d214bc7fdeba2ca7064a031e99fdf7af4587a8b5352b8535ff7968e7f4e895ba",
    "p2_1_manifest.json": "3ee062ce4026af969758224db76b21dd5c817144b87845173fe228eb2f8f5dd3",
    "p2_1_promotion_record.json": "a04c1fc656beb279c3bb8d703686b30a71895879b494a241d5871e05b124686e",
}
DOCS = (
    "ARCHITECTURE_DECISIONS.md", "DATA_MODEL_SPEC.md", "KPI_CONTRACTS.md",
    "PHASE_1_REVIEW.md", "PROJECT_CHARTER.md", "QA_TEST_MATRIX.md",
    "REPORT_PAGE_MATRIX.md", "SYNTHETIC_GENERATOR_SPEC.md",
)
STORE_FIELDS = (
    "store_key", "store_name", "region_key", "region_name", "city_key",
    "city_name", "store_profile", "lifecycle_cohort", "open_date", "last_trading_date",
)
LIFE_FIELDS = ("store_key", "date_key", "calendar_date", "is_operating", "lifecycle_state")
OFF_FIELDS = (
    "store_key", "date_key", "channel_key", "gross_sales_cents", "returns_amount_cents",
    "net_sales_cents", "transactions", "units", "source_snapshot_id", "lineage_hash",
)
COV_OFF_FIELDS = ("store_key", "date_key", "channel_key", "coverage_state", "evidence")
BUD_FIELDS = ("store_key", "month_start", "channel_key", "monthly_target_cents", "budget_version")
ACC_FIELDS = ("account_key", "account_name", "account_type")
MAP_FIELDS = ("account_key", "store_key", "valid_from", "valid_to")
DIG_FIELDS = (
    "account_key", "date_key", "attributed_retail_net_sales_cents", "orders", "units",
    "source_snapshot_id", "lineage_hash",
)
COV_DIG_FIELDS = ("account_key", "date_key", "coverage_state", "evidence")
CSV_NAMES = {
    "official_sales_snapshot.csv": OFF_FIELDS,
    "source_coverage_official.csv": COV_OFF_FIELDS,
    "budget_monthly.csv": BUD_FIELDS,
    "dim_marketplace_account.csv": ACC_FIELDS,
    "bridge_account_store_period.csv": MAP_FIELDS,
    "marketplace_daily_snapshot.csv": DIG_FIELDS,
    "source_coverage_marketplace.csv": COV_DIG_FIELDS,
}
MANIFEST_NAME = "p2_2_manifest.json"


def need(value, reason):
    if not value:
        raise ValueError(reason)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(obj) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def csv_bytes(rows, fields) -> bytes:
    sio = io.StringIO(newline="")
    wr = csv.DictWriter(sio, fieldnames=fields, extrasaction="raise", lineterminator="\n")
    wr.writeheader()
    wr.writerows(rows)
    return sio.getvalue().encode("utf-8")


def csv_parse(data: bytes, fields, label):
    need(data.endswith(b"\n") and b"\r" not in data, f"Noncanonical CSV newlines: {label}")
    reader = csv.DictReader(io.StringIO(data.decode("utf-8"), newline=""))
    need(tuple(reader.fieldnames or ()) == fields, f"Invalid schema: {label}")
    rows = list(reader)
    need(all(None not in r and all(v is not None for v in r.values()) for r in rows), f"Malformed rows: {label}")
    return rows


def hashed(seed, ns: str, key: str) -> int:
    raw = f"RetailPulse360|{VERSION}|{seed}|{ns}|{key}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")


def factor(base: int, per_mille: int) -> int:
    return (base * per_mille + 500) // 1000


def months():
    for y in (2025, 2026):
        for m in range(1, 13):
            yield date(y, m, 1)


def operating(row, on: date) -> bool:
    return on >= date.fromisoformat(row["open_date"]) and (
        not row["last_trading_date"] or on <= date.fromisoformat(row["last_trading_date"])
    )


def assert_safe_path(path: Path, description):
    need(not path.is_symlink(), f"Symlink not permitted for {description}: {path}")


def is_below(path: Path, parent: Path):
    return path == parent or parent in path.parents


def load_p21(root: Path):
    directory = root / "data" / "synthetic" / "p2_1"
    assert_safe_path(directory, "approved P2.1 directory")
    need(directory.is_dir(), f"Approved P2.1 directory missing: {directory}")
    need({p.name for p in directory.iterdir()} == set(APPROVED_P21), "P2.1 approved artifact set changed")
    content = {}
    for name, expected in APPROVED_P21.items():
        p = directory / name
        assert_safe_path(p, name)
        need(p.is_file(), f"Missing P2.1 artifact: {name}")
        content[name] = p.read_bytes()
        need(sha(content[name]) == expected, f"P2.1 SHA changed: {name}")
    stores = csv_parse(content["dim_store.csv"], STORE_FIELDS, "P2.1 stores")
    lifecycle = csv_parse(content["store_operating_calendar.csv"], LIFE_FIELDS, "P2.1 lifecycle")
    need(len(stores) == 30 and len(lifecycle) == 21900, "P2.1 sizes wrong")
    need({x["store_key"] for x in stores} == {f"S{i:03d}" for i in range(1, 31)}, "Store keys changed")
    manifest = json.loads(content["p2_1_manifest.json"])
    record = json.loads(content["p2_1_promotion_record.json"])
    need(manifest["seed"] == SEED and manifest["contract_version"] == CONTRACT, "P2.1 seed/contract mismatch")
    need(record["contract_version"] == CONTRACT and record["seed"] == SEED, "P2.1 promotion record invalid")
    return stores, lifecycle


def build_accounts(stores):
    accounts, mappings = [], []
    by_key = {s["store_key"]: s for s in stores}
    for idx, s in enumerate(stores, 1):
        key = f"A{idx:03d}"
        accounts.append({"account_key": key, "account_name": f"Fictional Account {key}",
                         "account_type": "PRIMARY"})
        adoption = max(date(2025, 1, 1), date.fromisoformat(s["open_date"]))
        adoption = adoption + timedelta(days=(idx * 7) % 35)
        # account mapping never outlives approved store closure
        closure = s["last_trading_date"] or END.isoformat()
        if adoption <= date.fromisoformat(closure):
            mappings.append({"account_key": key, "store_key": s["store_key"],
                             "valid_from": adoption.isoformat(), "valid_to": closure})
    for idx in range(1, 7):
        key = f"B{idx:03d}"
        s = by_key[f"S{idx:03d}"]
        accounts.append({"account_key": key, "account_name": f"Fictional Account {key}",
                         "account_type": "SECONDARY"})
        mapping_start = date(2025, 6, 1) if idx <= 3 else date(2026, 2, 1)
        mappings.append({"account_key": key, "store_key": s["store_key"],
                         "valid_from": mapping_start.isoformat(),
                         "valid_to": s["last_trading_date"] or END.isoformat()})
    accounts.append({"account_key": "T001", "account_name": "Fictional Transferred Account",
                     "account_type": "TRANSFER"})
    mappings.extend([
        {"account_key": "T001", "store_key": "S005", "valid_from": "2025-03-01", "valid_to": "2026-06-30"},
        {"account_key": "T001", "store_key": "S006", "valid_from": "2026-07-01", "valid_to": "2026-12-31"},
    ])
    accounts.sort(key=lambda r: r["account_key"])
    mappings.sort(key=lambda r: (r["account_key"], r["valid_from"]))
    return accounts, mappings


def sales_line(store, day: date, channel: str, seed):
    store_key = store["store_key"]
    key = f"{store_key}|{day.isoformat()}|{channel}"
    profile = store["store_profile"]
    p = {"LOW": 0, "MID": 1, "HIGH": 2}[profile]
    tx_base = (26, 52, 94)[p] if channel == "RETAIL" else (7, 12, 21)[p]
    strength = 820 + hashed(seed, "store_strength", store_key) % 360
    season = (920, 900, 1020, 1090, 1070, 960, 870, 890, 1010, 1130, 1170, 1110)[day.month - 1]
    weekday = (1040, 1000, 1020, 1060, 880, 1120, 1080)[day.weekday()]
    trend = 1000 if day.year == 2025 else 1040
    noise = 890 + hashed(seed, "transactions_noise", key) % 240
    tx = tx_base
    for f in (strength, season, weekday, trend, noise):
        tx = factor(tx, f)
    # Explicit, source-reported zero across BOTH official channels for an operating day.
    day_number = (day - START).days
    reported_zero = (day_number + int(store_key[1:]) * 13) % 197 == 0
    return_only = (hashed(seed, "returns_only", key) % 337 == 13)
    if reported_zero or return_only:
        tx = 0
    else:
        tx = max(1, tx)
    units = tx * (1 + hashed(seed, "items_per_transaction", key) % 3)
    basket = ((1900, 2700, 3550)[p] if channel == "RETAIL" else (1600, 2300, 2950)[p])
    basket = factor(basket, 900 + hashed(seed, "basket_noise", key) % 250)
    gross = tx * basket
    if return_only and not reported_zero:
        returns = 300 + hashed(seed, "returns_only_amount", key) % 5000
    elif tx and hashed(seed, "routine_return_trigger", key) % 8 == 0:
        returns = (gross * (5 + hashed(seed, "return_rate", key) % 38)) // 1000
    else:
        returns = 0
    net = gross - returns
    data = {
        "store_key": store_key, "date_key": day.strftime("%Y%m%d"), "channel_key": channel,
        "gross_sales_cents": str(gross), "returns_amount_cents": str(returns),
        "net_sales_cents": str(net), "transactions": str(tx), "units": str(units),
        "source_snapshot_id": SNAP_OFFICIAL,
    }
    data["lineage_hash"] = sha(canonical_json(data))
    return data


def budget_line(store, month_start, channel, seed):
    profile = store["store_profile"]
    p = {"LOW": 0, "MID": 1, "HIGH": 2}[profile]
    days = calendar.monthrange(month_start.year, month_start.month)[1]
    month_end = date(month_start.year, month_start.month, days)
    any_operating = date.fromisoformat(store["open_date"]) <= month_end and (
        not store["last_trading_date"] or date.fromisoformat(store["last_trading_date"]) >= month_start)
    if any_operating:
        base_tx = (26, 52, 94)[p] if channel == "RETAIL" else (7, 12, 21)[p]
        basket = ((1900, 2700, 3550)[p] if channel == "RETAIL" else (1600, 2300, 2950)[p])
        strength = 820 + hashed(seed, "store_strength", store["store_key"]) % 360
        seasonal = (920, 900, 1020, 1090, 1070, 960, 870, 890, 1010, 1130, 1170, 1110)[month_start.month - 1]
        expectation = factor(factor(base_tx * basket * days, strength), seasonal)
        target = factor(expectation, 920 + hashed(seed, "budget_adjustment", f'{store["store_key"]}|{month_start}|{channel}') % 240)
    else:
        target = 0
    return {"store_key": store["store_key"], "month_start": month_start.isoformat(),
            "channel_key": channel, "monthly_target_cents": str(target), "budget_version": BUDGET_VERSION}


def distribute(value, count):
    q, r = divmod(value, count)
    return [q + (i < r) for i in range(count)]


def build(seed, stores, lifecycle):
    by_store = {r["store_key"]: r for r in stores}
    official, off_cov, budgets = [], [], []
    retail_by_store_day = {}
    for life in lifecycle:  # certified P2.1 canonical Store x Date order
        if life["is_operating"] != "1":
            continue
        dt = date.fromisoformat(life["calendar_date"])
        if dt > OFFICIAL_ASOF:
            continue
        store = by_store[life["store_key"]]
        for channel in ("RETAIL", "PROGRAM"):
            row = sales_line(store, dt, channel, seed)
            official.append(row)
            zero = all(int(row[k]) == 0 for k in
                       ("gross_sales_cents", "returns_amount_cents", "net_sales_cents", "transactions", "units"))
            off_cov.append({"store_key": row["store_key"], "date_key": row["date_key"],
                            "channel_key": channel, "coverage_state": "REPORTED_ZERO" if zero else "REPORTED_VALUE",
                            "evidence": "GEN-BASE-EXPLICIT-ROW"})
            if channel == "RETAIL":
                retail_by_store_day[(row["store_key"], row["date_key"])] = row
    for store in stores:
        for month in months():
            for channel in ("RETAIL", "PROGRAM"):
                budgets.append(budget_line(store, month, channel, seed))
    accounts, mappings = build_accounts(stores)
    by_day_store = defaultdict(list)
    for m in mappings:
        d = date.fromisoformat(m["valid_from"])
        stop = min(MARKETPLACE_ASOF, date.fromisoformat(m["valid_to"]))
        while d <= stop:
            need(operating(by_store[m["store_key"]], d), "Marketplace mapping outside lifecycle")
            by_day_store[(m["store_key"], d.strftime("%Y%m%d"))].append(m["account_key"])
            d += timedelta(days=1)
    dig, dig_cov = [], []
    for (store_key, datekey), attached in sorted(by_day_store.items()):
        attached.sort()
        retail = retail_by_store_day.get((store_key, datekey))
        # Marketplace may be newer than Official. Simulate those days independently
        # using SAME model, not by pulling future official source into the snapshot.
        if retail is None:
            dt = date(int(datekey[:4]), int(datekey[4:6]), int(datekey[6:]))
            need(OFFICIAL_ASOF < dt <= MARKETPLACE_ASOF, "Missing matched official Retail source")
            retail = sales_line(by_store[store_key], dt, "RETAIL", seed)
        ret_net, ret_tx, ret_units = (int(retail[x]) for x in
                                       ("net_sales_cents", "transactions", "units"))
        if ret_net > 0 and ret_tx > 0:
            pct = 800 + hashed(seed, "digital_share", f"{store_key}|{datekey}") % 1700
            digital_total = ret_net * pct // 10000
            orders_total = min(ret_tx, max(1, ret_tx * pct // 10000))
            unit_total = min(ret_units, max(orders_total, ret_units * pct // 10000))
        else:
            digital_total = orders_total = unit_total = 0
        cents = distribute(digital_total, len(attached))
        orders = distribute(orders_total, len(attached))
        units = distribute(unit_total, len(attached))
        for i, acc in enumerate(attached):
            record = {"account_key": acc, "date_key": datekey,
                      "attributed_retail_net_sales_cents": str(cents[i]), "orders": str(orders[i]),
                      "units": str(units[i]), "source_snapshot_id": SNAP_DIGITAL}
            record["lineage_hash"] = sha(canonical_json(record))
            dig.append(record)
            dig_cov.append({"account_key": acc, "date_key": datekey,
                            "coverage_state": "REPORTED_ZERO" if cents[i] == orders[i] == units[i] == 0
                            else "REPORTED_VALUE", "evidence": "GEN-BASE-EXPLICIT-ROW"})
    # Canonical order: dates then business IDs, independently of source iteration/order.
    official.sort(key=lambda r: (r["date_key"], r["store_key"], r["channel_key"]))
    off_cov.sort(key=lambda r: (r["date_key"], r["store_key"], r["channel_key"]))
    budgets.sort(key=lambda r: (r["month_start"], r["store_key"], r["channel_key"]))
    dig.sort(key=lambda r: (r["date_key"], r["account_key"]))
    dig_cov.sort(key=lambda r: (r["date_key"], r["account_key"]))
    objects = {
        "official_sales_snapshot.csv": official,
        "source_coverage_official.csv": off_cov,
        "budget_monthly.csv": budgets,
        "dim_marketplace_account.csv": accounts,
        "bridge_account_store_period.csv": mappings,
        "marketplace_daily_snapshot.csv": dig,
        "source_coverage_marketplace.csv": dig_cov,
    }
    bodies = {name: csv_bytes(objects[name], fields) for name, fields in CSV_NAMES.items()}
    totals = {
        "retail_net_cents": sum(int(r["net_sales_cents"]) for r in official if r["channel_key"] == "RETAIL"),
        "program_net_cents": sum(int(r["net_sales_cents"]) for r in official if r["channel_key"] == "PROGRAM"),
        "official_net_cents": sum(int(r["net_sales_cents"]) for r in official),
        "monthly_budget_master_cents": sum(int(r["monthly_target_cents"]) for r in budgets),
        "digital_net_cents": sum(int(r["attributed_retail_net_sales_cents"]) for r in dig),
        "digital_future_rows": sum(r["date_key"] > OFFICIAL_ASOF.strftime("%Y%m%d") for r in dig),
    }
    settings = {
        "project": PROJECT, "version": VERSION, "contract": CONTRACT, "seed": seed,
        "source_scenario": "GEN-BASE", "observation_start": START.isoformat(),
        "observation_end": END.isoformat(), "official_asof": OFFICIAL_ASOF.isoformat(),
        "marketplace_asof": MARKETPLACE_ASOF.isoformat(),
        "budget_horizon_end": END.isoformat(), "budget_version": BUDGET_VERSION,
        "official_channels": ["RETAIL", "PROGRAM"], "non_additive_family": "MARKETPLACE",
        "currency": "CUR", "money_storage": "integer cents, exact; no floating-point money",
        "source_snapshots": {"OFFICIAL": SNAP_OFFICIAL, "MARKETPLACE": SNAP_DIGITAL},
        "origin": "Independent fictional generation; NO employer data or calibration",
        "future_data_label": "SIMULATED 2025-2026; future dates are fictional, not observed",
        "source_p2_1_sha256": APPROVED_P21,
        "budget_cent_policy": "full-calendar quotient/remainder; lifecycle masked only in downstream Phase 3",
    }
    manifest = {
        "project": PROJECT, "checkpoint": CHECKPOINT, "state": "CANDIDATE_ONLY_NOT_APPROVED",
        "classification": "100% SYNTHETIC / FICTIONAL", "contract_version": CONTRACT,
        "generator_version": VERSION, "seed": seed, "settings": settings,
        "settings_sha256": sha(canonical_json(settings)),
        "sources": {name: {"rows": len(objects[name]), "sha256": sha(bodies[name]),
                            "grain": ("store|date|channel" if name.startswith("official_") or name == "source_coverage_official.csv"
                                      else "store|month|channel" if name == "budget_monthly.csv"
                                      else "account|date" if name.endswith("daily_snapshot.csv") or name == "source_coverage_marketplace.csv"
                                      else "account|valid_from" if name.startswith("bridge_") else "account")}
                    for name in CSV_NAMES},
        "totals_cents": totals,
        "limitations": [
            "P2.2 only: baseline source generator; no full-snapshot scenario processor or protected archive yet.",
            "No transformed analytics facts, daily budget materialization, SQLite, DAX or Power BI validation.",
            "Source as-of dates in 2026 may be in the future; all output is simulated, NOT observed.",
            "Marketplace is attributed Retail subset; never add it to Official sales.",
        ],
    }
    bodies[MANIFEST_NAME] = canonical_json(manifest)
    return bodies, objects, totals


def validate_payload(bodies, stores, lifecycle):
    """Independently reread serialized records and apply structural/accounting checks."""
    parsed = {name: csv_parse(bodies[name], fields, name) for name, fields in CSV_NAMES.items()}
    manif = json.loads(bodies[MANIFEST_NAME])
    results = []

    def check(code, fn):
        try:
            msg = fn()
            results.append(("PASS", code, msg or ""))
        except Exception as exc:
            results.append(("FAIL", code, f"{type(exc).__name__}: {exc}"))

    def test_source_lineage():
        need(manif["settings"]["source_p2_1_sha256"] == APPROVED_P21, "P2.1 SHA anchor missing")
        need(manif["seed"] == SEED and manif["contract_version"] == CONTRACT, "contract wrong")
        return "Approved P2.1, seed, contract pinned"

    def test_official_keys_coverage():
        data = parsed["official_sales_snapshot.csv"]
        coverage = parsed["source_coverage_official.csv"]
        keys = [(r["store_key"], r["date_key"], r["channel_key"]) for r in data]
        need(len(keys) == len(set(keys)) and len(keys) == len(coverage), "Official key duplication/coverage")
        state = {(r["store_key"], r["date_key"], r["channel_key"]): r["coverage_state"] for r in coverage}
        need(set(keys) == set(state), "Official coverage key mismatch")
        for r in data:
            zero = all(int(r[x]) == 0 for x in
                       ("gross_sales_cents", "returns_amount_cents", "net_sales_cents", "transactions", "units"))
            need(state[(r["store_key"], r["date_key"], r["channel_key"])] ==
                 ("REPORTED_ZERO" if zero else "REPORTED_VALUE"), "Incorrect zero status")
        return f"{len(keys)} unique Official records and explicit coverage"

    def test_official_arithmetic():
        negatives = returns_only = zeros = 0
        for r in parsed["official_sales_snapshot.csv"]:
            gross, ret, net, tx, units = (int(r[k]) for k in
                                            ("gross_sales_cents", "returns_amount_cents", "net_sales_cents", "transactions", "units"))
            need(gross >= 0 and ret >= 0 and net == gross-ret, "Gross/returns/net invalid")
            need(tx >= 0 and units >= tx, "Transactions/units invalid")
            need((tx == 0) == (gross == 0), "Transaction/gross mismatch outside returns-only")
            original = {k: v for k, v in r.items() if k != "lineage_hash"}
            need(sha(canonical_json(original)) == r["lineage_hash"], "Official lineage SHA wrong")
            negatives += net < 0
            returns_only += gross == 0 and ret > 0
            zeros += net == 0 and gross == ret == tx == 0
        need(negatives > 0 and returns_only > 0 and zeros > 0, "Edge cases absent")
        return f"negative_days={negatives} returns_only={returns_only} reported_zeros={zeros}"

    def test_official_lifecycle():
        operating_dates = {(r["store_key"], r["date_key"]) for r in lifecycle if r["is_operating"] == "1"
                           and r["calendar_date"] <= OFFICIAL_ASOF.isoformat()}
        expected = {(s, d, c) for s, d in operating_dates for c in ("RETAIL", "PROGRAM")}
        actual = {(r["store_key"], r["date_key"], r["channel_key"])
                  for r in parsed["official_sales_snapshot.csv"]}
        need(actual == expected, f"Official missing/outside operation: expected={len(expected)} actual={len(actual)}")
        return f"Exactly 2 channels on {len(operating_dates)} operating store-days"

    def test_budget_grain():
        rows = parsed["budget_monthly.csv"]
        expect = {(s["store_key"], m.isoformat(), c) for s in stores for m in months()
                  for c in ("RETAIL", "PROGRAM")}
        keys = {(r["store_key"], r["month_start"], r["channel_key"]) for r in rows}
        need(len(rows) == 1440 and keys == expect, "Budget missing/duplicate monthly keys")
        bykey = {s["store_key"]: s for s in stores}
        for r in rows:
            m = date.fromisoformat(r["month_start"])
            val = int(r["monthly_target_cents"])
            need(val >= 0 and r["budget_version"] == BUDGET_VERSION, "Budget negative/version wrong")
            days = calendar.monthrange(m.year, m.month)[1]
            last = date(m.year, m.month, days)
            eligibility = date.fromisoformat(bykey[r["store_key"]]["open_date"]) <= last and (
                not bykey[r["store_key"]]["last_trading_date"] or
                date.fromisoformat(bykey[r["store_key"]]["last_trading_date"]) >= m)
            need((val > 0) == eligibility, "Monthly target nonzero outside any operating day")
        return "1440 monthly targets, all Store x Month x Channel"

    def test_budget_cent_policy():
        # Independent reference for quotient/remainder and clipping after store closes.
        need(sum(distribute(10000, 31)) == 10000, "31-day month residual failed")
        need(sum(distribute(10000, 31)[:10]) < 10000, "Closure accidentally redistributed")
        need(sum(distribute(10000, 28)) == 10000, "February budget allocation invalid")
        return "Full-month exact cents; preopen/postclosure mask does not redistribute"

    def test_account_mapping():
        accounts = parsed["dim_marketplace_account.csv"]
        maps = parsed["bridge_account_store_period.csv"]
        keys = [r["account_key"] for r in accounts]
        need(len(keys) == 37 and len(set(keys)) == 37 and len(maps) == 38, "Account counts incorrect")
        bykey = {s["store_key"]: s for s in stores}
        prior_end = {}
        for m in sorted(maps, key=lambda v: (v["account_key"], v["valid_from"])):
            start, end = date.fromisoformat(m["valid_from"]), date.fromisoformat(m["valid_to"])
            need(m["account_key"] in keys and m["store_key"] in bykey, "Account/store orphan")
            need(start <= end and (m["account_key"] not in prior_end or start > prior_end[m["account_key"]]),
                 "Account mapping overlap")
            need(operating(bykey[m["store_key"]], start) and operating(bykey[m["store_key"]], end),
                 "Account mapped to closed store")
            prior_end[m["account_key"]] = end
        t = [m for m in maps if m["account_key"] == "T001"]
        need(len(t) == 2 and t[0]["valid_to"] == "2026-06-30" and t[1]["valid_from"] == "2026-07-01",
             "Transferred account adjacency invalid")
        return "37 accounts / 38 exclusive mapping intervals; transfer validated"

    def test_digital_grain_coverage():
        data = parsed["marketplace_daily_snapshot.csv"]
        cov = parsed["source_coverage_marketplace.csv"]
        keys = [(r["account_key"], r["date_key"]) for r in data]
        need(len(keys) == len(set(keys)) == len(cov), "Digital duplicated records")
        cstates = {(r["account_key"], r["date_key"]): r["coverage_state"] for r in cov}
        need(set(keys) == set(cstates), "Digital coverage differs")
        for r in data:
            z = all(int(r[k]) == 0 for k in ("attributed_retail_net_sales_cents", "orders", "units"))
            need(cstates[(r["account_key"], r["date_key"])] ==
                 ("REPORTED_ZERO" if z else "REPORTED_VALUE"), "Digital zero mislabeled")
            raw = {k: v for k,v in r.items() if k != "lineage_hash"}
            need(sha(canonical_json(raw)) == r["lineage_hash"], "Digital row lineage mismatch")
        return f"{len(keys)} unique Account x Date facts and explicit coverage"

    def test_digital_mapping():
        maps = parsed["bridge_account_store_period.csv"]
        lookup = defaultdict(list)
        for m in maps:
            lookup[m["account_key"]].append((m["valid_from"].replace("-", ""),
                                              m["valid_to"].replace("-", ""), m["store_key"]))
        counts = Counter()
        for r in parsed["marketplace_daily_snapshot.csv"]:
            matches = [m for m in lookup[r["account_key"]] if m[0] <= r["date_key"] <= m[1]]
            need(len(matches) == 1 and r["date_key"] <= MARKETPLACE_ASOF.strftime("%Y%m%d"),
                 "Digital date without exactly one owner or ahead of asof")
            counts[(matches[0][2], r["date_key"])] += 1
        need(max(counts.values()) >= 2, "No multiple accounts per store")
        return "Every digital row assigned exactly one store, including multi-account days"

    def test_digital_subset():
        # Validate matched and unmatched independently from serialized OFFICIAL data.
        retail = {(r["store_key"], r["date_key"]): r for r in parsed["official_sales_snapshot.csv"]
                  if r["channel_key"] == "RETAIL"}
        ownership = defaultdict(list)
        for m in parsed["bridge_account_store_period.csv"]:
            ownership[m["account_key"]].append(m)
        bystoreday = defaultdict(lambda: [0, 0, 0])
        for r in parsed["marketplace_daily_snapshot.csv"]:
            owned = next(x["store_key"] for x in ownership[r["account_key"]]
                         if x["valid_from"].replace("-", "") <= r["date_key"] <= x["valid_to"].replace("-", ""))
            group = bystoreday[(owned, r["date_key"])]
            for i, k in enumerate(("attributed_retail_net_sales_cents", "orders", "units")):
                val = int(r[k]); need(val >= 0, "Negative baseline digital amount/count")
                group[i] += val
        matched = 0
        future = 0
        for (storekey, d), (cents, orders, units) in bystoreday.items():
            if d <= OFFICIAL_ASOF.strftime("%Y%m%d"):
                ref = retail[(storekey, d)]
                reference = tuple(int(ref[k]) for k in ("net_sales_cents", "transactions", "units"))
                if reference[0] <= 0:
                    need(cents == orders == units == 0, "Nonpositive Retail had digital activity")
                else:
                    need(0 <= cents <= reference[0] and orders <= reference[1] and units <= reference[2],
                         "Digital attribution exceeds Retail matched values")
                matched += 1
            else:
                future += 1
        need(matched > 0 and future > 0, "Missing matched or newer Digital rows")
        return f"matched store-days={matched}, digital-ahead store-days={future}"

    def test_marketplace_asof():
        need(START <= OFFICIAL_ASOF < MARKETPLACE_ASOF <= END, "As-Of source relationship incorrect")
        a = max(r["date_key"] for r in parsed["official_sales_snapshot.csv"])
        b = max(r["date_key"] for r in parsed["marketplace_daily_snapshot.csv"])
        need(a == OFFICIAL_ASOF.strftime("%Y%m%d") and b == MARKETPLACE_ASOF.strftime("%Y%m%d"),
             "As-Of latest observed generated date mismatch")
        return f"Official={OFFICIAL_ASOF}; Marketplace={MARKETPLACE_ASOF}; matched={OFFICIAL_ASOF}"

    def test_financial_totals():
        off = parsed["official_sales_snapshot.csv"]
        dg = parsed["marketplace_daily_snapshot.csv"]
        retail = sum(int(r["net_sales_cents"]) for r in off if r["channel_key"] == "RETAIL")
        program = sum(int(r["net_sales_cents"]) for r in off if r["channel_key"] == "PROGRAM")
        digital = sum(int(r["attributed_retail_net_sales_cents"]) for r in dg)
        t = manif["totals_cents"]
        need(retail + program == t["official_net_cents"] ==
             sum(int(r["net_sales_cents"]) for r in off), "Official double-count or missing channel")
        need(retail == t["retail_net_cents"] and program == t["program_net_cents"] and
             digital == t["digital_net_cents"], "Manifest totals mismatch")
        need(sum(int(r["monthly_target_cents"]) for r in parsed["budget_monthly.csv"]) ==
             t["monthly_budget_master_cents"], "Budget manifest total incorrect")
        return "Official=Retail+Program; Marketplace excluded; all cents reconciled"

    def test_manifest():
        need(manif["settings_sha256"] == sha(canonical_json(manif["settings"])), "Settings hash wrong")
        for filename in CSV_NAMES:
            need(manif["sources"][filename]["sha256"] == sha(bodies[filename]), "Manifest hash mismatched")
            need(manif["sources"][filename]["rows"] == len(parsed[filename]), "Manifest row count wrong")
        need(manif["state"] == "CANDIDATE_ONLY_NOT_APPROVED", "Candidate falsely approved")
        return "7 CSV source hashes and canonical deterministic manifest"

    def test_fixture():
        # Independent non-generated miniature fixture for the KPI arithmetic guardrail.
        r, p, dig, budget = 9000, 1000, 2000, 12500
        need(r+p == 10000 and r+p-budget == -2500 and dig != r+p, "Sales/budget/digital fixture wrong")
        need(sum(distribute(10000, 31)) == 10000, "Cent fixture wrong")
        return "Official 100.00; Gap -25.00; digital nonadditive"

    for code, fn in (
        ("P2.2-01_P21_LINEAGE", test_source_lineage),
        ("P2.2-02_OFFICIAL_GRAIN_COVERAGE", test_official_keys_coverage),
        ("P2.2-03_OFFICIAL_ARITHMETIC", test_official_arithmetic),
        ("P2.2-04_LIFECYCLE_EXACT", test_official_lifecycle),
        ("P2.2-05_BUDGET_MONTHLY", test_budget_grain),
        ("P2.2-06_BUDGET_CENT_FIXTURE", test_budget_cent_policy),
        ("P2.2-07_ACCOUNT_HISTORY", test_account_mapping),
        ("P2.2-08_DIGITAL_GRAIN_COVERAGE", test_digital_grain_coverage),
        ("P2.2-09_DIGITAL_OWNER", test_digital_mapping),
        ("P2.2-10_MATCHED_DIGITAL_SUBSET", test_digital_subset),
        ("P2.2-11_SOURCE_ASOF", test_marketplace_asof),
        ("P2.2-12_FINANCIAL_RECONCILIATION", test_financial_totals),
        ("P2.2-13_MANIFEST", test_manifest),
        ("P2.2-14_KPI_FIXTURE", test_fixture),
    ):
        check(code, fn)
    return results


def report_write(report, workspace, lines):
    # Archive previous report OUTSIDE central output; temporary report also OUTSIDE
    # the central output folder (same volume on user's Windows project root).
    previous = report.read_bytes() if report.exists() else None
    history = workspace / "report_history"
    assert_safe_path(history, "report history")
    history.mkdir(parents=True, exist_ok=True)
    if previous is not None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        archive = history / f"OUTPUT_{stamp}_{sha(previous)[:12]}.txt"
        with archive.open("xb") as fd:
            fd.write(previous)
    tmpdir = workspace / "report_staging"
    assert_safe_path(tmpdir, "report staging")
    tmpdir.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="P2_2_", suffix=".tmp", dir=str(tmpdir))
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(("\n".join(lines) + "\n").encode("utf-8"))
            stream.flush(); os.fsync(stream.fileno())
        os.replace(tmp, report)
    finally:
        if tmp.exists():
            tmp.unlink()


def candidate_publish(candidate, bodies):
    """New-only atomic directory publish; identical rerun leaves old candidate intact."""
    assert_safe_path(candidate, "candidate")
    if candidate.exists():
        need(candidate.is_dir(), "Candidate exists but not a directory")
        actual = sorted(p.name for p in candidate.iterdir())
        need(actual == sorted(bodies), f"Existing candidate artifacts unexpected: {actual}")
        for name, content in bodies.items():
            dest = candidate / name
            assert_safe_path(dest, "existing candidate file")
            need(dest.is_file() and dest.read_bytes() == content,
                 f"Candidate conflict: {name} differs. NO files overwritten")
        return "IDENTICAL_CANDIDATE_UNCHANGED"
    candidate.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".P2_2_stage_", dir=str(candidate.parent)))
    did_move = False
    try:
        for name, content in bodies.items():
            (stage / name).write_bytes(content)
        need(all((stage / name).read_bytes() == data for name, data in bodies.items()),
             "Staged payload mismatch")
        need(not candidate.exists(), "Candidate appeared during staging; blocked")
        stage.rename(candidate)
        did_move = True
        need(all((candidate / name).read_bytes() == data for name, data in bodies.items()),
             "Post-candidate hash mismatch")
        return "CREATED_NEW_ATOMIC_CANDIDATE_DIRECTORY"
    except Exception:
        if did_move and candidate.is_dir():
            shutil.rmtree(candidate)
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def previous_gate(report):
    content = report.read_text(encoding="utf-8-sig")
    lines = set(content.splitlines())
    need("PROJECT | RetailPulse 360" in lines, "Central report is for another project")
    if "CHECKPOINT | P2.1-PROMOTION" in lines:
        need("STATUS=PASS_P2_1_LOCALLY_PROMOTED_PENDING_REPORT_REVIEW" in lines,
             "P2.1 was not successfully promoted")
        for name, fingerprint in APPROVED_P21.items():
            need(f"PUBLISHED_SHA256 | {name} | {fingerprint}" in lines,
                 f"Previous P2.1 promotion SHA missing: {name}")
    elif "CHECKPOINT | P2.2" in lines:
        need(any(s.startswith("STATUS=") for s in lines), "P2.2 report malformed")
    else:
        raise ValueError("Central report is not a P2.1 promotion or P2.2 run")


def main():
    parser = argparse.ArgumentParser(description="RetailPulse 360 P2.2 — candidate-only synthetic commercial sources")
    parser.add_argument("--root", required=True, help="Approved project root")
    parser.add_argument("--report", help="Central OUTPUT.txt; default <root.parent>/output/OUTPUT.txt")
    args = parser.parse_args()
    in_root = Path(args.root).expanduser()
    in_report = Path(args.report).expanduser() if args.report else in_root.parent / "output" / "OUTPUT.txt"
    # No root/report symlink. Prohibit output inside root before any work.
    for path, desc in ((in_root, "project root"), (in_report, "central OUTPUT")):
        assert_safe_path(path, desc)
    root = in_root.resolve()
    report = in_report.resolve()
    workspace = (root.parent / "retailpulse360_dev").resolve()
    if report.name != "OUTPUT.txt" or is_below(report, root) or is_below(workspace, root) or is_below(workspace, report.parent):
        print("STATUS=BLOCKED_UNSAFE_ROOT_OR_REPORT", file=sys.stderr)
        return 3
    if not root.is_dir() or not report.is_file():
        print("STATUS=BLOCKED_ROOT_OR_PREVIOUS_REPORT_MISSING", file=sys.stderr)
        return 3
    if workspace.is_symlink():
        print("STATUS=BLOCKED_UNSAFE_WORKSPACE", file=sys.stderr)
        return 3
    try:
        previous_gate(report)
    except Exception as exc:
        print(f"STATUS=BLOCKED_PREVIOUS_CHECKPOINT | {exc}", file=sys.stderr)
        return 3
    log = [
        f"PROJECT | {PROJECT}", f"CHECKPOINT | {CHECKPOINT}",
        "CONTRACT | Phase 1 v0.1 APPROVED DEC-01..DEC-10",
        f"RUN_UTC | {datetime.now(timezone.utc).isoformat()}",
        f"RUN_ID | P2_2_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}",
        "MODE | GENERATE_VALIDATE_CANDIDATE_ONLY", "SYNTHETIC | TRUE",
        f"PROJECT_ROOT | {root}", f"WORKSPACE | {workspace}",
        f"REPORT | {report}", f"GENERATOR_VERSION | {VERSION}", f"SEED | {SEED}",
        f"OFFICIAL_ASOF | {OFFICIAL_ASOF}", f"MARKETPLACE_ASOF | {MARKETPLACE_ASOF}",
        "APPROVED_PROJECT_WRITE | NONE",
    ]
    status = "FAIL_P2_2_CANDIDATE_BLOCKED"
    try:
        need(report.parent.is_dir(), "Report parent directory missing")
        need(sorted(p.name for p in report.parent.iterdir()) == ["OUTPUT.txt"],
             "Central output must contain ONLY OUTPUT.txt")
        for doc in DOCS:
            need((root / "docs" / doc).is_file(), f"Missing Phase1 contract: docs/{doc}")
        need((root / "data" / "synthetic" / "p2_1").is_dir(), "Missing approved P2.1")
        root_files_before = {str(p.relative_to(root)): sha(p.read_bytes()) for p in root.rglob("*") if p.is_file()}
        stores, lifecycle = load_p21(root)
        log.append("PASS | P2_1_APPROVED_SOURCE | 4 files pinned SHA256; 30 stores and 21,900 store-days")
        bodies, objects, totals = build(SEED, stores, lifecycle)
        checks = validate_payload(bodies, stores, lifecycle)
        for state, code, note in checks:
            log.append(f"{state} | {code} | {note}")
        failures = [r for r in checks if r[0] == "FAIL"]
        log.append(f"TESTS | total={len(checks)} passed={len(checks)-len(failures)} failed={len(failures)}")
        need(not failures, "At least one P2.2 independent validation test failed")
        second_bodies, _, _ = build(SEED, stores, lifecycle)
        need(second_bodies == bodies, "Same seed/config does not regenerate identical bytes")
        log.append("PASS | P2.2-15_SAME_SEED_BYTES | Exact canonical bytes including manifest")
        changed, _, _ = build(SEED + 1, stores, lifecycle)
        need(changed["official_sales_snapshot.csv"] != bodies["official_sales_snapshot.csv"] and
             changed[MANIFEST_NAME] != bodies[MANIFEST_NAME], "Different seed did not change output")
        log.append("PASS | P2.2-16_DIFFERENT_SEED | Generated data and manifest changed")
        candidate = workspace / "P2_2_CANDIDATE"
        result = candidate_publish(candidate, bodies)
        log.append(f"PASS | CANDIDATE | {result}")
        for name, data in bodies.items():
            log.append(f"CANDIDATE_SHA256 | {name} | {sha(data)}")
            if name in objects:
                log.append(f"ROWS | {name} | {len(objects[name])}")
        log.append(f"TOTALS_CENTS | {json.dumps(totals, sort_keys=True)}")
        root_files_after = {str(p.relative_to(root)): sha(p.read_bytes()) for p in root.rglob("*") if p.is_file()}
        need(root_files_after == root_files_before, "Approved root changed unexpectedly")
        log.append("PASS | P2.2-17_PROJECT_ROOT_UNCHANGED | Every existing project file SHA identical")
        log.append("PASS | OUTPUT_EXCLUSIVE | Only OUTPUT.txt in central output folder")
        log.append(f"TESTS | total=17 passed=17 failed=0")
        log.append("WARNING | P2.2 is baseline source generation ONLY: snapshot changes/protected history remain P2.3/Phase 3")
        log.append("WARNING | No SQL, DAX, Power BI runtime or Phase 3 ETL test was performed")
        log.append("WARNING | All 2026 future-dated records are FICTIONAL SIMULATION, not observed facts")
        status = "PASS_P2_2_CANDIDATE_VALIDATED_PENDING_REPORT_REVIEW"
    except Exception as exc:
        log.append(f"FAIL | {type(exc).__name__}: {exc}")
        log.append("TRACE | " + " | ".join(traceback.format_exception_only(type(exc), exc)).strip().replace("\n", " "))
        log.append("PUBLISH_POLICY | No modifications to approved root; never overwrite differing candidate")
    log.append(f"STATUS={status}")
    log.append(f"END_UTC | {datetime.now(timezone.utc).isoformat()}")
    try:
        report_write(report, workspace, log)
    except Exception as exc:
        print(f"STATUS=FAIL_REPORT_WRITE | {type(exc).__name__}: {exc}", file=sys.stderr)
        print("\n".join(log), file=sys.stderr)
        return 3
    print(f"STATUS={status}\nREPORT={report}")
    return 0 if status.startswith("PASS_") else 2


if __name__ == "__main__":
    sys.exit(main())

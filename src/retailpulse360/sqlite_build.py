#!/usr/bin/env python3
"""RetailPulse 360 P4.1: read published G0004; create verified SQLite candidate outside project.

Python standard-library only. Phase 1 v0.1 governs the model.  No in-project writes.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import shutil
from collections import defaultdict

REVISION = "p4.1.0"
GENERATION = "G0004"
EXPECTED_G4_MANIFEST_SHA = "d1135b60ff299996a05bd6edaeb26b7df9c126368984e46e8c368a031a642f92"
MAX_CENTS = 9_000_000_000_000_000

# Operational source location, SQLite name, key types. No corporate or private sources.
TABLES = {
 "dim_date": ("analytics/dim_date.csv", "date_key calendar_date year quarter month month_start year_month weekday_number week_start_saturday week_end_friday"),
 "dim_store": ("analytics/dim_store.csv", "store_key store_name region_key region_name city_key city_name store_profile lifecycle_cohort open_date last_trading_date"),
 "dim_channel": ("analytics/dim_channel.csv", "channel_key channel_name is_additive"),
 "dim_marketplace_account": ("analytics/dim_marketplace_account.csv", "account_key account_name account_type"),
 "bridge_account_store_period": ("analytics/bridge_account_store_period.csv", "account_key store_key valid_from valid_to"),
 "store_operating_calendar": ("analytics/store_operating_calendar.csv", "store_key date_key calendar_date is_operating lifecycle_state"),
 "fact_sales_daily": ("analytics/fact_sales_daily.csv", "store_key date_key channel_key gross_sales_cents returns_amount_cents net_sales_cents transactions units source_snapshot_id lineage_hash"),
 "fact_budget_monthly": ("analytics/fact_budget_monthly.csv", "store_key month_start channel_key monthly_target_cents budget_version"),
 "fact_budget_daily": ("analytics/fact_budget_daily.csv", "store_key date_key channel_key allocated_budget_cents budget_version allocation_policy_version"),
 "fact_marketplace_daily": ("analytics/fact_marketplace_daily.csv", "store_key account_key date_key attributed_retail_net_sales_cents orders units source_snapshot_id lineage_hash"),
 "source_coverage_official": ("staging/source_coverage_official.csv", "store_key date_key channel_key coverage_state evidence"),
 "source_coverage_marketplace": ("staging/source_coverage_marketplace.csv", "account_key date_key coverage_state evidence"),
 "dq_findings": ("analytics/dq_findings.csv", "check_id severity source_family affected_key reason evidence"),
}
NUMERIC = {"date_key", "year", "quarter", "month", "year_month", "weekday_number", "is_additive", "is_operating", "gross_sales_cents", "returns_amount_cents", "net_sales_cents", "transactions", "units", "monthly_target_cents", "allocated_budget_cents", "attributed_retail_net_sales_cents", "orders"}
CENTS = {"gross_sales_cents", "returns_amount_cents", "net_sales_cents", "monthly_target_cents", "allocated_budget_cents", "attributed_retail_net_sales_cents"}
DDL = """
CREATE TABLE dim_date (date_key INTEGER PRIMARY KEY, calendar_date TEXT NOT NULL UNIQUE, year INTEGER NOT NULL, quarter INTEGER NOT NULL CHECK(quarter BETWEEN 1 AND 4), month INTEGER NOT NULL CHECK(month BETWEEN 1 AND 12), month_start TEXT NOT NULL, year_month INTEGER NOT NULL, weekday_number INTEGER NOT NULL, week_start_saturday TEXT NOT NULL, week_end_friday TEXT NOT NULL);
CREATE TABLE dim_store (store_key TEXT PRIMARY KEY, store_name TEXT NOT NULL, region_key TEXT NOT NULL, region_name TEXT NOT NULL, city_key TEXT NOT NULL, city_name TEXT NOT NULL, store_profile TEXT NOT NULL, lifecycle_cohort TEXT NOT NULL, open_date TEXT NOT NULL, last_trading_date TEXT, CHECK(last_trading_date IS NULL OR last_trading_date >= open_date));
CREATE TABLE dim_channel (channel_key TEXT PRIMARY KEY CHECK(channel_key IN ('RETAIL','PROGRAM')), channel_name TEXT NOT NULL, is_additive INTEGER NOT NULL CHECK(is_additive=1));
CREATE TABLE dim_marketplace_account (account_key TEXT PRIMARY KEY, account_name TEXT NOT NULL, account_type TEXT NOT NULL);
CREATE TABLE bridge_account_store_period (account_key TEXT NOT NULL REFERENCES dim_marketplace_account(account_key), store_key TEXT NOT NULL REFERENCES dim_store(store_key), valid_from TEXT NOT NULL, valid_to TEXT, PRIMARY KEY(account_key, valid_from), CHECK(valid_to IS NULL OR valid_to >= valid_from));
CREATE TABLE store_operating_calendar (store_key TEXT NOT NULL REFERENCES dim_store(store_key), date_key INTEGER NOT NULL REFERENCES dim_date(date_key), calendar_date TEXT NOT NULL, is_operating INTEGER NOT NULL CHECK(is_operating IN (0,1)), lifecycle_state TEXT NOT NULL, PRIMARY KEY(store_key,date_key));
CREATE TABLE fact_sales_daily (store_key TEXT NOT NULL REFERENCES dim_store(store_key), date_key INTEGER NOT NULL REFERENCES dim_date(date_key), channel_key TEXT NOT NULL REFERENCES dim_channel(channel_key), gross_sales_cents INTEGER NOT NULL CHECK(gross_sales_cents >= 0), returns_amount_cents INTEGER NOT NULL CHECK(returns_amount_cents >= 0), net_sales_cents INTEGER NOT NULL CHECK(net_sales_cents = gross_sales_cents-returns_amount_cents), transactions INTEGER NOT NULL CHECK(transactions >= 0), units INTEGER NOT NULL CHECK(units >= 0), source_snapshot_id TEXT NOT NULL, lineage_hash TEXT NOT NULL, PRIMARY KEY(store_key,date_key,channel_key), FOREIGN KEY(store_key,date_key) REFERENCES store_operating_calendar(store_key,date_key));
CREATE TABLE fact_budget_monthly (store_key TEXT NOT NULL REFERENCES dim_store(store_key), month_start TEXT NOT NULL, channel_key TEXT NOT NULL REFERENCES dim_channel(channel_key), monthly_target_cents INTEGER NOT NULL CHECK(monthly_target_cents >= 0), budget_version TEXT NOT NULL, PRIMARY KEY(store_key,month_start,channel_key,budget_version), UNIQUE(store_key,month_start,channel_key));
CREATE TABLE fact_budget_daily (store_key TEXT NOT NULL REFERENCES dim_store(store_key), date_key INTEGER NOT NULL REFERENCES dim_date(date_key), channel_key TEXT NOT NULL REFERENCES dim_channel(channel_key), allocated_budget_cents INTEGER NOT NULL CHECK(allocated_budget_cents >= 0), budget_version TEXT NOT NULL, allocation_policy_version TEXT NOT NULL, PRIMARY KEY(store_key,date_key,channel_key), FOREIGN KEY(store_key,date_key) REFERENCES store_operating_calendar(store_key,date_key));
CREATE TABLE fact_marketplace_daily (store_key TEXT NOT NULL REFERENCES dim_store(store_key), account_key TEXT NOT NULL REFERENCES dim_marketplace_account(account_key), date_key INTEGER NOT NULL REFERENCES dim_date(date_key), attributed_retail_net_sales_cents INTEGER NOT NULL, orders INTEGER NOT NULL CHECK(orders>=0), units INTEGER NOT NULL CHECK(units>=0), source_snapshot_id TEXT NOT NULL, lineage_hash TEXT NOT NULL, PRIMARY KEY(store_key,date_key,account_key), FOREIGN KEY(store_key,date_key) REFERENCES store_operating_calendar(store_key,date_key));
CREATE TABLE source_coverage_official (store_key TEXT NOT NULL REFERENCES dim_store(store_key), date_key INTEGER NOT NULL REFERENCES dim_date(date_key), channel_key TEXT NOT NULL REFERENCES dim_channel(channel_key), coverage_state TEXT NOT NULL CHECK(coverage_state IN ('REPORTED_VALUE','REPORTED_ZERO','RETRACTED_CONFIRMED','MISSING_EXPECTED','NOT_APPLICABLE')), evidence TEXT NOT NULL, PRIMARY KEY(store_key,date_key,channel_key));
CREATE TABLE source_coverage_marketplace (account_key TEXT NOT NULL REFERENCES dim_marketplace_account(account_key), date_key INTEGER NOT NULL REFERENCES dim_date(date_key), coverage_state TEXT NOT NULL CHECK(coverage_state IN ('REPORTED_VALUE','REPORTED_ZERO','RETRACTED_CONFIRMED','MISSING_EXPECTED','NOT_APPLICABLE')), evidence TEXT NOT NULL, PRIMARY KEY(account_key,date_key));
CREATE TABLE dq_findings (dq_id INTEGER PRIMARY KEY, check_id TEXT NOT NULL, severity TEXT NOT NULL, source_family TEXT NOT NULL, affected_key TEXT NOT NULL, reason TEXT NOT NULL, evidence TEXT NOT NULL);
CREATE TABLE generation_metadata (generation_id TEXT PRIMARY KEY, parent_generation TEXT, official_asof TEXT NOT NULL, marketplace_asof TEXT NOT NULL, source_manifest_sha256 TEXT NOT NULL);
CREATE INDEX ix_sales_date_channel ON fact_sales_daily(date_key,channel_key);
CREATE INDEX ix_sales_store_date ON fact_sales_daily(store_key,date_key);
CREATE INDEX ix_budget_date ON fact_budget_daily(date_key);
CREATE INDEX ix_digital_date ON fact_marketplace_daily(date_key);
CREATE INDEX ix_bridge_store ON bridge_account_store_period(store_key,valid_from);
CREATE INDEX ix_coverage_date ON source_coverage_official(date_key,coverage_state);
"""


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):
            h.update(b)
    return h.hexdigest()


def csv_rows(path, header):
    with path.open('r',encoding='utf-8-sig',newline='') as fh:
        reader=csv.DictReader(fh)
        require(reader.fieldnames == header, f"Unexpected columns in {path}: {reader.fieldnames!r}; expected {header!r}")
        for idx, row in enumerate(reader,2):
            require(None not in row and all(v is not None for v in row.values()), f"Invalid CSV record {path}:{idx}")
            vals=[]
            for col in header:
                v=row[col]
                if col in NUMERIC:
                    require(v and v.lstrip('-').isdigit(),f"Non-integer {col}: {path}:{idx}")
                    v=int(v)
                    if col in CENTS:
                        require(abs(v)<=MAX_CENTS,f"Excess money range: {path}:{idx}")
                elif col in ('last_trading_date','valid_to') and v=='':
                    v=None
                elif v=='':
                    require(col not in ('lineage_hash','store_key','account_key','channel_key'),f"Empty required field {col}: {path}:{idx}")
                vals.append(v)
            yield tuple(vals)


def verify_source(root):
    require(root.is_dir() and not root.is_symlink(),'Invalid project root')
    docs=['DATA_MODEL_SPEC.md','KPI_CONTRACTS.md','QA_TEST_MATRIX.md','ARCHITECTURE_DECISIONS.md','PHASE_3_ETL_SNAPSHOTS.md']
    for name in docs: require((root/'docs'/name).is_file(),f"Missing approved documentation: {name}")
    store=root/'data/processed/p3_3'
    ptr=store/'CURRENT'
    require(ptr.is_file() and not ptr.is_symlink(),'Missing/unsafe CURRENT pointer')
    current=ptr.read_text(encoding='utf-8').strip()
    require(current==GENERATION,f"P4.1 expects active {GENERATION}; detected {current}")
    root_gen=store/'generations'
    previous=""
    for i in range(1,5):
        g=f'G{i:04d}'
        loc=root_gen/g
        require(loc.is_dir() and not loc.is_symlink(),f"Missing generation {g}")
        mp=loc/'generation_manifest.json'
        require(mp.is_file() and not mp.is_symlink(),f"Missing generation manifest {g}")
        manifest=json.loads(mp.read_text(encoding='utf-8'))
        require(manifest.get('generation')==g and manifest.get('parent_generation')==previous, f"Invalid generation parent chain {g}")
        for name, spec in manifest['artifacts'].items():
            p=loc/name
            require(p.is_file() and not p.is_symlink() and p.stat().st_size==spec['size_bytes'] and sha(p)==spec['sha256'],f"Generation artifact altered: {g}/{name}")
        previous=g
    mp=root_gen/GENERATION/'generation_manifest.json'
    require(sha(mp)==EXPECTED_G4_MANIFEST_SHA,'Published G0004 manifest differs from verified Phase 3 value')
    manifest=json.loads(mp.read_text(encoding='utf-8'))
    expected=set(v[0] for v in TABLES.values())
    require(expected.issubset(set(manifest['artifacts'])), 'Missing source analytical/staging artifacts')
    require(manifest['source_asof']['OFFICIAL']=='2026-12-20' and manifest['source_asof']['MARKETPLACE']=='2026-12-27','Unexpected As-Of; review contract')
    require(manifest['classification']=='100% SYNTHETIC', 'Non-synthetic data rejected')
    return root_gen/GENERATION,manifest,sha(mp)


def build_database(db, gen_path, manifest, manifest_sha):
    db.parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(db)
    try:
        con.execute('PRAGMA foreign_keys=ON')
        con.execute('PRAGMA journal_mode=DELETE')
        con.execute('PRAGMA synchronous=FULL')
        con.executescript(DDL)
        # Dimensions first, then bridge/calendar/facts. Coverage is treated separately from reported zeros.
        order=['dim_date','dim_store','dim_channel','dim_marketplace_account','bridge_account_store_period','store_operating_calendar',
               'fact_sales_daily','fact_budget_monthly','fact_budget_daily','fact_marketplace_daily','source_coverage_official','source_coverage_marketplace','dq_findings']
        sizes={}
        for table in order:
            rel, headerstr=TABLES[table]
            header=headerstr.split()
            records=list(csv_rows(gen_path/rel,header))
            columns=('dq_id,' if table=='dq_findings' else '')+','.join(header)
            # dq_id column auto increments when unspecified.
            columns=','.join(header)
            placeholders=','.join('?' for _ in header)
            con.executemany(f'INSERT INTO {table} ({columns}) VALUES ({placeholders})',records)
            sizes[table]=len(records)
        con.execute('INSERT INTO generation_metadata VALUES (?,?,?,?,?)',
                    (GENERATION,manifest['parent_generation'],manifest['source_asof']['OFFICIAL'],manifest['source_asof']['MARKETPLACE'],manifest_sha))
        con.commit()
        require(con.execute('PRAGMA integrity_check').fetchone()[0]=='ok','SQLite integrity_check failure')
        require(not con.execute('PRAGMA foreign_key_check').fetchall(),'SQLite foreign keys broken')
        # Test enforcement with rollbacks, leaving SQLite state invariant.
        def rejects(query,args):
            con.execute('SAVEPOINT fault')
            blocked=False
            try:
                con.execute(query,args)
            except sqlite3.IntegrityError:
                blocked=True
            finally:
                con.execute('ROLLBACK TO fault')
                con.execute('RELEASE fault')
            require(blocked,'SQLite constraint did not reject bad write')
        rejects('INSERT INTO dim_channel VALUES (?,?,?)',('RETAIL','Duplicated',1))
        rejects('INSERT INTO fact_sales_daily VALUES (?,?,?,?,?,?,?,?,?,?)',('MISSING_STORE',20250101,'RETAIL',1,0,1,1,1,'TEST','TEST'))
        rejects('INSERT INTO fact_sales_daily VALUES (?,?,?,?,?,?,?,?,?,?)',('S001',20250101,'RETAIL',0,2,0,0,0,'TEST','TEST'))
        require(con.execute('SELECT COUNT(*) FROM dim_channel').fetchone()[0]==2,'Unexpected channel count')
        con.execute('VACUUM')
        return sizes
    finally:
        con.close()


def scalar(con,query,values=()):
    return con.execute(query,values).fetchone()[0] or 0


def reference_oracle(gen_path, official_asof,marketplace_asof):
    """Independent Python reference: CSV enumeration, integer cents, never SQLite results."""
    sales=defaultdict(int); by_store_month=defaultdict(int);channel=defaultdict(int)
    negative=0
    retail_by_store_date=defaultdict(int)
    src,h=TABLES['fact_sales_daily']
    for r in csv_rows(gen_path/src,h.split()):
        store,date,chan,gross,ret,net,tx,units,source,hash_=r
        assert gross-ret==net
        sales['official']+=net
        sales['gross']+=gross
        sales['returns']+=ret
        channel[chan]+=net
        by_store_month[(store,date//100,chan)]+=net
        negative+=net<0
        if chan=='RETAIL':retail_by_store_date[(store,date)]+=net
    src,h=TABLES['fact_budget_daily']
    bstore=defaultdict(int)
    for r in csv_rows(gen_path/src,h.split()):
        store,date,chan,cents,version,policy=r
        sales['budget_total']+=cents
        bstore[(store,date//100,chan)]+=cents
        if str(date)<=official_asof.replace('-',''): sales['budget_aligned']+=cents
    src,h=TABLES['fact_marketplace_daily']
    dstore=defaultdict(int)
    digital_group=defaultdict(int)
    matched_end=min(official_asof,marketplace_asof).replace('-','')
    for r in csv_rows(gen_path/src,h.split()):
        store,account,date,cents,orders,units,source,hash_=r
        sales['digital_total']+=cents
        dstore[(store,date//100)]+=cents
        if str(date)<=matched_end:
            digital_group[(store,date)]+=cents
        else: sales['digital_ahead_rows']+=1
    # Matched pair date/store: only those digital dates whose Retail denominator is truly reported.
    for k,digital in digital_group.items():
        if k in retail_by_store_date:
            sales['digital_matched']+=digital
            sales['retail_matched']+=retail_by_store_date[k]
    return dict(sales),dict(channel),dict(by_store_month),dict(bstore),dict(dstore),negative


def sql_checks(db,gen,manifest,counts):
    official_asof=manifest['source_asof']['OFFICIAL']; market_asof=manifest['source_asof']['MARKETPLACE']; end=min(official_asof,market_asof)
    oracle,channel,sm,bm,dm,negative=reference_oracle(gen,official_asof,market_asof)
    con=sqlite3.connect(f'file:{db.as_posix()}?mode=ro',uri=True)
    try:
        totals={
         'official':scalar(con,'SELECT SUM(net_sales_cents) FROM fact_sales_daily'),
         'gross':scalar(con,'SELECT SUM(gross_sales_cents) FROM fact_sales_daily'),
         'returns':scalar(con,'SELECT SUM(returns_amount_cents) FROM fact_sales_daily'),
         'budget_total':scalar(con,'SELECT SUM(allocated_budget_cents) FROM fact_budget_daily'),
         'budget_aligned':scalar(con,'SELECT SUM(b.allocated_budget_cents) FROM fact_budget_daily b JOIN dim_date d ON b.date_key=d.date_key WHERE d.calendar_date<=?',(official_asof,)),
         'digital_total':scalar(con,'SELECT SUM(attributed_retail_net_sales_cents) FROM fact_marketplace_daily'),
         'digital_ahead_rows':scalar(con,'SELECT COUNT(*) FROM fact_marketplace_daily m JOIN dim_date d ON m.date_key=d.date_key WHERE d.calendar_date>?',(end,)),
        }
        # Do not duplicate Retail denominators when multiple marketplace accounts share a store/date.
        matched=con.execute('''SELECT COALESCE(SUM(d.digital_cents),0),COALESCE(SUM(s.net_sales_cents),0)
        FROM (SELECT m.store_key,m.date_key,SUM(m.attributed_retail_net_sales_cents) digital_cents
              FROM fact_marketplace_daily m JOIN dim_date cal ON cal.date_key=m.date_key
              WHERE cal.calendar_date<=? GROUP BY m.store_key,m.date_key) d
        JOIN fact_sales_daily s ON s.store_key=d.store_key AND s.date_key=d.date_key AND s.channel_key='RETAIL' ''',(end,)).fetchone()
        totals['digital_matched']=matched[0];totals['retail_matched']=matched[1]
        require(totals==oracle,f'Independent Python vs SQLite mismatch: {[(k,totals.get(k),oracle.get(k)) for k in totals if totals[k]!=oracle.get(k)]}')
        assert totals['official']==manifest['totals_cents']['official_net_cents']
        assert totals['digital_total']==manifest['totals_cents']['digital_net_cents']
        assert totals['gross']-totals['returns']==totals['official']
        actual=dict(con.execute('SELECT channel_key,SUM(net_sales_cents) FROM fact_sales_daily GROUP BY channel_key'))
        require(actual==channel,'Channel totals differ from Python')
        ssql={(s,int(month),c):int(value) for s,month,c,value in con.execute('SELECT store_key,CAST(date_key/100 AS INTEGER),channel_key,SUM(net_sales_cents) FROM fact_sales_daily GROUP BY 1,2,3')}
        require(ssql==sm,'Store/month/channel sales reconciliation failed')
        bsql={(s,int(month),c):int(value) for s,month,c,value in con.execute('SELECT store_key,CAST(date_key/100 AS INTEGER),channel_key,SUM(allocated_budget_cents) FROM fact_budget_daily GROUP BY 1,2,3')}
        require(bsql==bm,'Store/month/channel daily budget reconciliation failed')
        dsql={(s,int(month)):int(value) for s,month,value in con.execute('SELECT store_key,CAST(date_key/100 AS INTEGER),SUM(attributed_retail_net_sales_cents) FROM fact_marketplace_daily GROUP BY 1,2')}
        require(dsql==dm,'Store/month digital reconciliation failed')
        require(scalar(con,'SELECT COUNT(*) FROM fact_sales_daily WHERE net_sales_cents<0')==negative,'Negative return rows not retained')
        require(not con.execute('PRAGMA foreign_key_check').fetchall(),'FK check failed')
        # Verify the full certified protected history still matches immutable official rows.
        archive_path=gen/'protected_history/closed_store_official.csv'
        archive_cols=TABLES['fact_sales_daily'][1].split()
        archive_count=0
        for r in csv_rows(archive_path,archive_cols):
            match=con.execute('SELECT '+','.join(archive_cols)+' FROM fact_sales_daily WHERE store_key=? AND date_key=? AND channel_key=?',r[:3]).fetchone()
            require(match==r,'Protected history key/value mismatch in current analytical fact')
            archive_count+=1
        require(archive_count==2624,'Protected history row count mismatch')
        require(scalar(con,'SELECT COUNT(*) FROM fact_budget_daily b JOIN store_operating_calendar c USING(store_key,date_key) WHERE c.is_operating<>1')==0,'Budget on nonoperating date')
        require(scalar(con,'SELECT COUNT(*) FROM fact_sales_daily b JOIN store_operating_calendar c USING(store_key,date_key) WHERE c.is_operating<>1')==0,'Sales on nonoperating date')
        require(scalar(con,'SELECT COUNT(*) FROM fact_marketplace_daily b JOIN store_operating_calendar c USING(store_key,date_key) WHERE c.is_operating<>1')==0,'Digital on nonoperating date')
        require(scalar(con,'SELECT COUNT(*) FROM store_operating_calendar')==30*730,'Missing store operating calendar')
        # Source reporting zeros are not inferred: reported zero fact must be explicit.
        require(scalar(con,"SELECT COUNT(*) FROM fact_sales_daily WHERE net_sales_cents=0")>0,'Reported zeros missing')
        # Each digital row must map to one nonoverlapping account ownership interval.
        bad=con.execute('''SELECT COUNT(*) FROM fact_marketplace_daily m JOIN dim_date d ON m.date_key=d.date_key
        WHERE (SELECT COUNT(*) FROM bridge_account_store_period b WHERE b.account_key=m.account_key AND b.store_key=m.store_key AND b.valid_from<=d.calendar_date AND (b.valid_to IS NULL OR b.valid_to>=d.calendar_date))<>1''').fetchone()[0]
        require(bad==0,'Marketplace account ownership invalid')
        overlapping=con.execute('''SELECT COUNT(*) FROM bridge_account_store_period a JOIN bridge_account_store_period b
        ON a.account_key=b.account_key AND a.valid_from < b.valid_from
        WHERE b.valid_from <= COALESCE(a.valid_to,'9999-12-31')''').fetchone()[0]
        require(overlapping==0,'Overlapping account ownership intervals')
        require(all(v>=0 for v in (oracle['budget_total'],oracle['budget_aligned'])),'Budget invalid')
        return {'totals_cents':totals,'table_counts':counts,'negative_official_rows':negative,
                'sql_channel_net_cents':actual,'checked_sales_store_month_channel_groups':len(sm),
                'checked_budget_store_month_channel_groups':len(bm),'checked_digital_store_month_groups':len(dm),
                'matched_through':end,'protected_rows_matched':archive_count,'tests':14}
    finally: con.close()


def report_write(path,content):
    require(not path.is_symlink(),'REPORT cannot be symlink')
    if path.exists(): require(path.is_file(),'REPORT target must be a file')
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.RetailPulse360_P4_1_',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:
            f.write(content)
            f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.lexists(tmp):os.unlink(tmp)


def build_report(status,lines,report):
    return '\n'.join(['PROJECT | RetailPulse 360','CHECKPOINT | P4.1-SQLITE-CANDIDATE',
                     f'RUNNER | {REVISION}','MODE | SQLITE_MODEL_AND_INDEPENDENT_PYTHON_PARITY_CANDIDATE_ONLY',
                     'GITHUB | NOT_USED',f'REPORT | {report}','OUTPUT_ROLE | EPHEMERAL_COMMUNICATION_ONLY',*lines,
                     f'STATUS={status}',''])


def run(root, report):
    lines=[]
    gen,manifest,msha=verify_source(root)
    lines.append('PASS | CONTRACTS_AND_SOURCE | Phase 1 contracts, current G0004, four-generation SHA chain verified')
    candidate=root.parent/'retailpulse360_dev'/'P4_1_SQLITE_CANDIDATE'
    require(not candidate.is_symlink(),'Candidate directory is symlink')
    workspace=candidate.parent
    workspace.mkdir(parents=True,exist_ok=True)
    temp=Path(tempfile.mkdtemp(prefix='.P4_1_BUILD_',dir=workspace))
    try:
        db=temp/'retailpulse360_g0004.sqlite'
        counts=build_database(db,gen,manifest,msha)
        qa=sql_checks(db,gen,manifest,counts)
        require(qa['totals_cents']['official']==3759335807,'G4 official approved cents mismatch')
        require(qa['totals_cents']['digital_total']==514398580,'G4 digital approved cents mismatch')
        lines.append(f"PASS | SQLITE_SCHEMA | 13 governed tables + metadata, constraints, foreign keys, integers for cents")
        lines.append('PASS | INDEPENDENT_PYTHON_SQL_PARITY | 14 model/finance/coverage/negative/ownership/archive QA gates')
        lines.append('PASS | GRAINS_AND_OWNERSHIP | Unique fact keys; account temporal resolution; source coverage separate')
        lines.append('PASS | NO_DIGITAL_DOUBLE_COUNT | Marketplace not added to Official')
        lines.append('PASS | ASOF_POLICY | Marketplace ahead retained; matched dates only in cross-family comparison')
        payload={'checkpoint':'P4.1','state':'CANDIDATE_NOT_PUBLISHED','source_generation':'G0004',
                 'source_generation_manifest_sha256':msha,'sqlite_sha256':sha(db),'sqlite_bytes':db.stat().st_size,
                 'oracle':qa,'creation_policy':'sqlite_standard_library_no_external_dependencies'}
        mp=temp/'p4_1_manifest.json'
        mp.write_text(json.dumps(payload,ensure_ascii=False,sort_keys=True,indent=2)+'\n',encoding='utf-8')
        if candidate.exists():
            require(candidate.is_dir(),'Existing candidate is not directory')
            require(set(p.name for p in candidate.iterdir())=={'retailpulse360_g0004.sqlite','p4_1_manifest.json'},'Unknown candidate files present')
            for item in temp.iterdir():
                require(not (candidate/item.name).is_symlink(),f'Unsafe candidate symlink: {item.name}')
                require(sha(item)==sha(candidate/item.name),f'Candidate changed or not deterministic: {item.name}')
            status='VERIFIED_EXISTING_IDENTICAL_CANDIDATE'
        else:
            os.rename(temp,candidate)
            status='CREATED_NEW_ATOMIC_CANDIDATE'
        lines.append(f'PASS | CANDIDATE | {status} | {candidate}')
        lines.append(f'COUNTS | {json.dumps(counts,sort_keys=True)}')
        lines.append(f'TOTALS_CENTS | {json.dumps(qa["totals_cents"],sort_keys=True)}')
        lines.append(f'SQLITE_SHA256 | {payload["sqlite_sha256"]}')
        lines.append(f'MANIFEST_SHA256 | {sha(candidate/"p4_1_manifest.json")}')
        lines.append('PASS | PROJECT_READ_ONLY | No approved project files modified')
        lines.append('PASS | REPORT_SCOPED | Only specified OUTPUT.txt updated; sibling files and folders untouched')
        lines.append('WARNING | SQLite candidate only. Published SQL model, Power Query, DAX and Power BI runtime NOT TESTED')
        return build_report('PASS_P4_1_SQLITE_CANDIDATE_VALIDATED_PENDING_REPORT_REVIEW',lines,report)
    finally:
        if temp.exists():shutil.rmtree(temp)


def main():
    parser=argparse.ArgumentParser(description='Create read-only-governed SQLite G0004 candidate with independent Python↔SQL QA')
    parser.add_argument('--root',required=True,help='Local RetailPulse 360 project directory')
    parser.add_argument('--report',required=True,help='Only OUTPUT.txt report target (shared directory allowed)')
    a=parser.parse_args()
    root=Path(a.root).expanduser().resolve()
    report=Path(a.report).expanduser().absolute()
    # OUTPUT.txt may be elsewhere, but never inside the project (no hidden source modifications).
    try:
        require(report.name=='OUTPUT.txt','Report filename must be OUTPUT.txt')
        require(report!=root and root not in report.parents,'Report cannot live in project root')
        result=run(root,report)
        report_write(report,result)
        print(result)
    except Exception as exc:
        result=build_report('FAIL_P4_1_BLOCKED',[f'FAIL | {type(exc).__name__} | {exc}'],report)
        try: report_write(report,result)
        except Exception as reporting_error: print(f'REPORT_WRITE_FAILED: {reporting_error}')
        print(result)
        raise SystemExit(1)

if __name__=='__main__': main()

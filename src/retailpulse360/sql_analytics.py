#!/usr/bin/env python3
"""RetailPulse 360 P4.2: governed SQLite analytics candidate + independent CSV oracle.

Read-only project access; Python stdlib; no GitHub or approval logs.
Stage SQL and machine-verifiable KPI evidence outside the approved project.
"""
from __future__ import annotations
import argparse
import csv
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from collections import defaultdict
from fractions import Fraction

REVISION='p4.2.0'
GEN='G0004'
G4_MANIFEST_SHA='d1135b60ff299996a05bd6edaeb26b7df9c126368984e46e8c368a031a642f92'
P41_DB_SHA='3e5480af50f44f6718fcc48aa0a7ea859bd9b35259838c0b3abcc8bcaed5bb5b'
P41_MANIFEST_SHA='ee35f99526cc637d62da4384e0493781e317e3946804f018a6a50e0d06947a75'
OFFICIAL_ASOF=dt.date(2026,12,20)
DIGITAL_ASOF=dt.date(2026,12,27)
COVERED={'REPORTED_ZERO','REPORTED_VALUE'}
VIEWS_SQL='''-- RetailPulse 360 P4.2 / Portable SQLite read-only analytics views.
-- Official and Marketplace are NEVER added together.
CREATE TEMP VIEW v_rp_official_store_day AS
SELECT store_key,date_key,
 SUM(net_sales_cents) AS official_cents,
 SUM(CASE WHEN channel_key='RETAIL' THEN net_sales_cents ELSE 0 END) AS retail_cents,
 SUM(CASE WHEN channel_key='PROGRAM' THEN net_sales_cents ELSE 0 END) AS program_cents,
 SUM(gross_sales_cents) AS gross_cents,
 SUM(returns_amount_cents) AS returns_cents,
 SUM(transactions) AS transactions,
 SUM(units) AS units
FROM fact_sales_daily GROUP BY store_key,date_key;
CREATE TEMP VIEW v_rp_budget_store_day AS
SELECT store_key,date_key,SUM(allocated_budget_cents) AS effective_budget_cents
FROM fact_budget_daily GROUP BY store_key,date_key;
CREATE TEMP VIEW v_rp_marketplace_store_day AS
SELECT store_key,date_key,SUM(attributed_retail_net_sales_cents) AS attributed_cents
FROM fact_marketplace_daily GROUP BY store_key,date_key;
-- Aggregate accounts FIRST so one retail denominator is joined once per store/date.
CREATE TEMP VIEW v_rp_matched_digital_store_day AS
SELECT d.store_key,d.date_key,d.attributed_cents,r.net_sales_cents AS retail_cents
FROM v_rp_marketplace_store_day d
JOIN fact_sales_daily r ON r.store_key=d.store_key AND r.date_key=d.date_key AND r.channel_key='RETAIL'
JOIN generation_metadata m ON m.generation_id='G0004'
JOIN dim_date cal ON cal.date_key=d.date_key
WHERE cal.calendar_date<=m.official_asof AND cal.calendar_date<=m.marketplace_asof
AND EXISTS(SELECT 1 FROM source_coverage_official c
 WHERE c.store_key=r.store_key AND c.date_key=r.date_key AND c.channel_key='RETAIL'
 AND c.coverage_state IN ('REPORTED_ZERO','REPORTED_VALUE'));
'''
QUERIES_SQL='''-- RetailPulse 360 P4.2: parameterized reference queries (SQLite).
-- Money in integer CENTS; calculate ratios from SUMMED components in application.
-- Bind start_key, end_key and optional channel/store context consistently.
-- SQL-001: additive official sales, gross, returns, transaction and units.
SELECT COALESCE(SUM(net_sales_cents),0) official_cents,
 COALESCE(SUM(gross_sales_cents),0) gross_cents,
 COALESCE(SUM(returns_amount_cents),0) returns_cents,
 COALESCE(SUM(transactions),0) transactions,
 COALESCE(SUM(units),0) units
FROM fact_sales_daily WHERE date_key BETWEEN ? AND ?;
-- SQL-002: effective budget capped by official As-Of; zero sales do not remove budget.
SELECT COALESCE(SUM(b.allocated_budget_cents),0) budget_cents
FROM fact_budget_daily b JOIN dim_date d ON d.date_key=b.date_key
JOIN generation_metadata m ON m.generation_id='G0004'
WHERE b.date_key BETWEEN ? AND ? AND d.calendar_date<=m.official_asof;
-- SQL-003: raw Marketplace may extend beyond official source As-Of.
SELECT COALESCE(SUM(attributed_retail_net_sales_cents),0) digital_cents
FROM fact_marketplace_daily WHERE date_key BETWEEN ? AND ?;
-- SQL-004: paired marketplace/retail numerator and denominator.
SELECT COALESCE(SUM(attributed_cents),0) digital_cents,
 COALESCE(SUM(retail_cents),0) retail_cents
FROM v_rp_matched_digital_store_day WHERE date_key BETWEEN ? AND ?;
-- SQL-005: Strict LFL cohort: date-pair table is dynamically assembled from
-- same-day previous calendar year; WTD uses -364 days (Sat-Fri alignment).
-- Strict requires each chosen channel to be REPORTED and operating on every
-- TY and paired PY day. See executable SQL in P4.2 Python oracle runner.
-- SQL-006: Gap = Official - Budget, Achievement = Official / Budget;
-- Budget zero/missing => N/A, never 0%, never AVG(store achievements).
'''


def require(ok,msg):
    if not ok: raise ValueError(msg)

def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as fh:
        for b in iter(lambda:fh.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def key(day): return int(day.strftime('%Y%m%d'))

def daterange(start,end):
    n=(end-start).days
    return [start+dt.timedelta(days=i) for i in range(n+1)] if n>=0 else []

def prior(day,mode):
    if mode=='WTD':return day-dt.timedelta(days=364)
    try: return day.replace(year=day.year-1)
    except ValueError: return None  # leap-day omitted, flagged by caller

def safe_csv(p):
    with p.open('r',encoding='utf-8-sig',newline='') as f:
        return list(csv.DictReader(f))

def snapshot_project_files(root):
    # Only files that existed before this run; never modify project.
    return {str(p.relative_to(root)):digest(p) for p in root.rglob('*') if p.is_file() and not p.is_symlink()}

def verify_source(root):
    require(root.is_dir() and not root.is_symlink(),'Invalid project root')
    for name in ('DATA_MODEL_SPEC.md','KPI_CONTRACTS.md','ARCHITECTURE_DECISIONS.md','QA_TEST_MATRIX.md','PHASE_3_ETL_SNAPSHOTS.md'):
        require((root/'docs'/name).is_file(),'Missing approved contract '+name)
    base=root/'data/processed/p4_1'
    db=base/'retailpulse360_g0004.sqlite'
    pm=base/'p4_1_manifest.json'
    require(db.is_file() and not db.is_symlink() and pm.is_file() and not pm.is_symlink(),'Missing or unsafe P4.1 files')
    require(digest(db)==P41_DB_SHA,'P4.1 database SHA differs from certified local result')
    require(digest(pm)==P41_MANIFEST_SHA,'P4.1 manifest SHA differs from certified local result')
    meta=json.loads(pm.read_text(encoding='utf-8'))
    require(meta['source_generation']=='G0004' and meta['sqlite_sha256']==digest(db),'P4.1 manifest contents mismatch')
    genbase=root/'data/processed/p3_3'
    require((genbase/'CURRENT').read_text(encoding='utf-8').strip()=='G0004','Active generation changed; G0004 P4.2 baseline is stale')
    gen=genbase/'generations/G0004'
    gp=gen/'generation_manifest.json'
    require(digest(gp)==G4_MANIFEST_SHA,'G0004 manifest mismatch')
    manifest=json.loads(gp.read_text(encoding='utf-8'))
    require(manifest['source_asof']=={'OFFICIAL':'2026-12-20','MARKETPLACE':'2026-12-27'},'Unexpected As-Of')
    require(manifest['classification']=='100% SYNTHETIC','Non-synthetic project refused')
    # Pin selected CSV facts/coverage to independently re-run Python oracle.
    needed=['analytics/fact_sales_daily.csv','analytics/fact_budget_daily.csv',
            'analytics/fact_marketplace_daily.csv','analytics/dim_store.csv',
            'analytics/store_operating_calendar.csv','staging/source_coverage_official.csv',
            'staging/source_coverage_marketplace.csv','analytics/dim_date.csv']
    for rel in needed:
        p=gen/rel
        require(p.is_file() and not p.is_symlink() and digest(p)==manifest['artifacts'][rel]['sha256'],f'Source CSV tampered: {rel}')
    con=sqlite3.connect(f'file:{db.as_posix()}?mode=ro',uri=True)
    try:
        require(con.execute('PRAGMA integrity_check').fetchone()[0]=='ok','SQLite corruption')
        require(not con.execute('PRAGMA foreign_key_check').fetchall(),'Broken foreign key')
        metadata=con.execute('SELECT official_asof,marketplace_asof,source_manifest_sha256 FROM generation_metadata').fetchone()
        require(metadata==('2026-12-20','2026-12-27',G4_MANIFEST_SHA),'SQLite source metadata mismatch')
    finally:con.close()
    return db,gen,manifest

class Oracle:
    def __init__(self,gen):
        self.sales={};self.budgets={};self.market={};self.coverage={};self.op={};self.stores={}
        for x in safe_csv(gen/'analytics/fact_sales_daily.csv'):
            k=(x['store_key'],int(x['date_key']),x['channel_key'])
            require(k not in self.sales,'Duplicate Python oracle sales key')
            self.sales[k]=tuple(int(x[n]) for n in ('net_sales_cents','gross_sales_cents','returns_amount_cents','transactions','units'))
        for x in safe_csv(gen/'analytics/fact_budget_daily.csv'):
            k=(x['store_key'],int(x['date_key']),x['channel_key'])
            require(k not in self.budgets,'Duplicate Python oracle budget key')
            self.budgets[k]=int(x['allocated_budget_cents'])
        for x in safe_csv(gen/'analytics/fact_marketplace_daily.csv'):
            k=(x['store_key'],int(x['date_key']),x['account_key'])
            require(k not in self.market,'Duplicate Python oracle digital key')
            self.market[k]=int(x['attributed_retail_net_sales_cents'])
        for x in safe_csv(gen/'staging/source_coverage_official.csv'):
            self.coverage[(x['store_key'],int(x['date_key']),x['channel_key'])]=x['coverage_state']
        for x in safe_csv(gen/'analytics/store_operating_calendar.csv'):
            self.op[(x['store_key'],int(x['date_key']))]=int(x['is_operating'])
        for x in safe_csv(gen/'analytics/dim_store.csv'):
            self.stores[x['store_key']]=x
        self.digital_by_store_day=defaultdict(int)
        for (s,d,a),v in self.market.items(): self.digital_by_store_day[s,d]+=v

    def cohort(self,pairs,channels,subset):
        if not pairs:return set()
        return {s for s in subset if all(
            self.op.get((s,key(t)))==1 and self.op.get((s,key(p)))==1 and
            all(self.coverage.get((s,key(t),c)) in COVERED and self.coverage.get((s,key(p),c)) in COVERED for c in channels)
            for t,p in pairs)}

    def aggregate(self,days,channels,stores,asof=OFFICIAL_ASOF):
        allowed=set(key(d) for d in days if d<=asof)
        sums=[0,0,0,0,0,0]
        for (s,d,c),(n,g,r,tx,u) in self.sales.items():
            if d in allowed and s in stores and c in channels:
                for i,v in enumerate((n,g,r,tx,u)):sums[i]+=v
        for (s,d,c),v in self.budgets.items():
            if d in allowed and s in stores and c in channels:sums[5]+=v
        return tuple(sums)

    def digital(self,days,stores,allow_matched):
        raw_days={key(d) for d in days if d<=DIGITAL_ASOF}
        match_days={key(d) for d in days if d<=min(DIGITAL_ASOF,OFFICIAL_ASOF)}
        raw=sum(v for (s,d,a),v in self.market.items() if s in stores and d in raw_days)
        if not allow_matched:return (raw,None,None)
        dm=rm=0
        for (s,d),v in self.digital_by_store_day.items():
            if s in stores and d in match_days and self.coverage.get((s,d,'RETAIL')) in COVERED and (s,d,'RETAIL') in self.sales:
                dm+=v;rm+=self.sales[s,d,'RETAIL'][0]
        return (raw,dm,rm)


def filter_stores(oracle,flt):
    if not flt:return set(oracle.stores)
    typ,value=flt
    if typ=='store':require(value in oracle.stores,'Unknown store sample');return {value}
    if typ=='region':return {s for s,x in oracle.stores.items() if x['region_key']==value}
    if typ=='city':return {s for s,x in oracle.stores.items() if x['city_key']==value}
    raise ValueError('Unknown filter')

def sql_aggregate(con,days,channels,stores):
    active=[key(d) for d in days if d<=OFFICIAL_ASOF]
    if not active or not stores:return (0,0,0,0,0,0)
    require(bool(channels),'Empty SQL channel scope')
    placeholders=lambda n:','.join('?' for _ in range(n))
    pred=f'date_key IN ({placeholders(len(active))}) AND channel_key IN ({placeholders(len(channels))}) AND store_key IN ({placeholders(len(stores))})'
    params=(*active,*sorted(channels),*sorted(stores))
    row=con.execute(f'''SELECT COALESCE(SUM(net_sales_cents),0),COALESCE(SUM(gross_sales_cents),0),
    COALESCE(SUM(returns_amount_cents),0),COALESCE(SUM(transactions),0),COALESCE(SUM(units),0)
    FROM fact_sales_daily WHERE {pred}''',params).fetchone()
    bu=con.execute(f'SELECT COALESCE(SUM(allocated_budget_cents),0) FROM fact_budget_daily WHERE {pred}',params).fetchone()[0]
    return tuple(row)+(bu,)

def sql_cohort(con,pairs,channels,stores):
    if not pairs:return set()
    # SQLite parameterized date pairs: checks operation and source coverage both periods.
    v=','.join('(?,?)' for _ in pairs)
    ch=','.join('(?)' for _ in channels)
    st=','.join('?' for _ in stores)
    query=f'''WITH paired(ty,py) AS (VALUES {v}), channels(channel_key) AS (VALUES {ch})
    SELECT s.store_key FROM dim_store s WHERE s.store_key IN ({st}) AND NOT EXISTS (
      SELECT 1 FROM paired p CROSS JOIN channels ch WHERE
      NOT EXISTS (SELECT 1 FROM store_operating_calendar o WHERE o.store_key=s.store_key AND o.date_key=p.ty AND o.is_operating=1)
      OR NOT EXISTS (SELECT 1 FROM store_operating_calendar o WHERE o.store_key=s.store_key AND o.date_key=p.py AND o.is_operating=1)
      OR NOT EXISTS (SELECT 1 FROM source_coverage_official c WHERE c.store_key=s.store_key AND c.date_key=p.ty AND c.channel_key=ch.channel_key AND c.coverage_state IN ('REPORTED_ZERO','REPORTED_VALUE'))
      OR NOT EXISTS (SELECT 1 FROM source_coverage_official c WHERE c.store_key=s.store_key AND c.date_key=p.py AND c.channel_key=ch.channel_key AND c.coverage_state IN ('REPORTED_ZERO','REPORTED_VALUE'))
    ) ORDER BY s.store_key'''
    vals=[v for a,b in pairs for v in (key(a),key(b))]+list(sorted(channels))+list(sorted(stores))
    return {x[0] for x in con.execute(query,vals)}

def sql_digital(con,days,stores,allow_matched):
    raw_days=[key(d) for d in days if d<=DIGITAL_ASOF]
    match_days=[key(d) for d in days if d<=min(OFFICIAL_ASOF,DIGITAL_ASOF)]
    if not raw_days or not stores:return (0,0 if allow_matched else None,0 if allow_matched else None)
    place=lambda n:','.join('?' for _ in range(n))
    st=sorted(stores)
    raw=con.execute(f'''SELECT COALESCE(SUM(attributed_retail_net_sales_cents),0) FROM fact_marketplace_daily
      WHERE date_key IN ({place(len(raw_days))}) AND store_key IN ({place(len(st))})''',raw_days+st).fetchone()[0]
    if not allow_matched:return (raw,None,None)
    if not match_days:return (raw,0,0)
    matched=con.execute(f'''SELECT COALESCE(SUM(attributed_cents),0),COALESCE(SUM(retail_cents),0)
      FROM v_rp_matched_digital_store_day WHERE date_key IN ({place(len(match_days))})
      AND store_key IN ({place(len(st))})''',match_days+st).fetchone()
    return raw,*matched

def rat(a,b):return None if b is None or b<=0 else [a,b]   # exact rational, client can divide

def windows(start,end,mode):
    effective_end=min(end,OFFICIAL_ASOF)
    if effective_end<start:return [],[]
    if mode=='WTD': anchor=effective_end-dt.timedelta(days=(effective_end.weekday()+2)%7)
    elif mode=='MTD':anchor=effective_end.replace(day=1)
    elif mode=='QTD':anchor=effective_end.replace(month=3*((effective_end.month-1)//3)+1,day=1)
    elif mode=='YTD':anchor=effective_end.replace(month=1,day=1)
    elif mode=='CUSTOM':anchor=start
    else:raise ValueError('Unknown time mode')
    dates=daterange(max(anchor,start),effective_end)
    pairs=[(d,prior(d,mode)) for d in dates if prior(d,mode) is not None and prior(d,mode).year>=2025]
    return dates,pairs

def review_context(con,oracle,scenario):
    name,start,end,mode,channels,flt=scenario
    start=dt.date.fromisoformat(start);end=dt.date.fromisoformat(end)
    require(end>=start,'Bad test range')
    channels=set(channels)
    require(channels.issubset({'RETAIL','PROGRAM'}) and channels,'Illegal channel scope')
    stores=filter_stores(oracle,flt)
    require(stores,'Empty store scope not supported in test scenario')
    days,pairs=windows(start,end,mode)
    # Raw digital independent freshness uses selected start/end, not official truncated end.
    selected=daterange(start,end)
    a=oracle.aggregate(days,channels,stores);b=sql_aggregate(con,days,channels,stores)
    require(a==b,f'{name}: additive finance mismatch {a} != {b}')
    require(a[0]==a[1]-a[2],f'{name}: gross-returns mismatch')
    gap=a[0]-a[5]
    # WTD paired PY from 364d, all other modes paired calendar year.
    py_days=[p for _,p in pairs]
    a_py=oracle.aggregate(py_days,channels,stores);b_py=sql_aggregate(con,py_days,channels,stores)
    require(a_py==b_py,f'{name}: Total PY mismatch')
    py_available=bool(days) and all(d.year>=2026 for d in days) and len(pairs)==len(days)
    strict_a=oracle.cohort(pairs,channels,stores) if py_available else set()
    strict_b=sql_cohort(con,pairs,channels,stores) if py_available else set()
    require(strict_a==strict_b,f'{name}: Strict cohort mismatch ({strict_a ^ strict_b})')
    strict_ty_a=oracle.aggregate(days,channels,strict_a); strict_ty_b=sql_aggregate(con,days,channels,strict_b)
    strict_py_a=oracle.aggregate(py_days,channels,strict_a);strict_py_b=sql_aggregate(con,py_days,channels,strict_b)
    require(strict_ty_a==strict_ty_b and strict_py_a==strict_py_b,f'{name}: LFL amounts mismatch')
    dig_a=oracle.digital(selected,stores,'RETAIL' in channels)
    dig_b=sql_digital(con,selected,stores,'RETAIL' in channels)
    require(dig_a==dig_b,f'{name}: digital matched ratio mismatch {dig_a} != {dig_b}')
    # Cohort Budget must be based on operating dates, not sales existence.
    result={'window':name,'mode':mode,'start':start.isoformat(),'selected_end':end.isoformat(),
        'effective_official_end':min(end,OFFICIAL_ASOF).isoformat(),'channels':sorted(channels),
        'store_filter':flt,'store_population':len(stores),'period_days':len(days),
        'official_cents':a[0],'gross_cents':a[1],'returns_cents':a[2],
        'transactions':a[3],'units':a[4],'aligned_budget_cents':a[5],
        'budget_gap_cents':gap,'achievement_fraction':rat(a[0],a[5]),
        'basket_fraction_cents':rat(a[0],a[3]),'units_per_transaction_fraction':rat(a[4],a[3]),
        'total_py_cents':a_py[0] if py_available else None,
        'total_growth_fraction':rat(a[0]-a_py[0],a_py[0]) if py_available else None,
        'strict_eligible_stores':len(strict_a),'strict_ty_cents':strict_ty_a[0] if py_available else None,
        'strict_py_cents':strict_py_a[0] if py_available else None,
        'strict_growth_fraction':rat(strict_ty_a[0]-strict_py_a[0],strict_py_a[0]) if py_available and strict_a else None,
        'marketplace_raw_cents':dig_a[0], 'matched_digital_cents':dig_a[1],
        'matched_retail_cents':dig_a[2],
        'digital_share_fraction':rat(dig_a[1],dig_a[2]) if dig_a[1] is not None else None,
        'source_lag_days':(OFFICIAL_ASOF-DIGITAL_ASOF).days,
        'python_sql_parity':'PASS'}
    return result

def report_write(path,content):
    require(path.name=='OUTPUT.txt' and not path.is_symlink(),'Output must be OUTPUT.txt regular target')
    if path.exists():require(path.is_file(),'Output target is not regular file')
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.RetailPulse360_P4_2_',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:
            f.write(content);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.lexists(tmp):os.unlink(tmp)

def report(status,lines,root):
    return '\n'.join(['PROJECT | RetailPulse 360','CHECKPOINT | P4.2-SQL-ANALYTICS-CANDIDATE',
      f'REVISION | {REVISION}','MODE | READ_ONLY_SQL_AND_INDEPENDENT_PYTHON_ORACLE',
      'GITHUB | NOT_USED','OUTPUT_ROLE | TEMPORARY_COMMUNICATION_ONLY',f'ROOT_READ_ONLY | {root}',
      *lines,f'STATUS={status}',''])

def run(root):
    lines=[]
    db,gen,manifest=verify_source(root)
    before=snapshot_project_files(root)
    lines.append('PASS | BASELINES | Phase 1 KPI contracts, CURRENT=G0004, pinned G0004 CSVs and P4.1 SQLite verified')
    oracle=Oracle(gen)
    cases=[
      ('YTD_2026','2026-01-01','2026-12-31','YTD',['RETAIL','PROGRAM'],None),
      ('YTD_2025_NO_PY','2025-01-01','2025-12-31','YTD',['RETAIL','PROGRAM'],None),
      ('MTD_DEC_2026','2026-12-01','2026-12-31','MTD',['RETAIL','PROGRAM'],None),
      ('WTD_DEC20_2026','2026-12-01','2026-12-20','WTD',['RETAIL','PROGRAM'],None),
      ('QTD_DEC_2026','2026-10-01','2026-12-29','QTD',['RETAIL','PROGRAM'],None),
      ('MTD_NOV_2026','2026-11-01','2026-11-30','MTD',['RETAIL','PROGRAM'],None),
      ('CUSTOM_PARTIAL_2026','2026-05-11','2026-06-03','CUSTOM',['RETAIL','PROGRAM'],None),
      ('RETAIL_MTD_2026','2026-12-01','2026-12-31','MTD',['RETAIL'],None),
      ('PROGRAM_MTD_2026','2026-12-01','2026-12-31','MTD',['PROGRAM'],None),
      ('CLOSED_STORE','2026-01-01','2026-12-31','YTD',['RETAIL','PROGRAM'],('store','S019')),
      ('REGION_SCOPE','2026-09-01','2026-10-09','CUSTOM',['RETAIL','PROGRAM'],('region','R02')),
      ('FUTURE_DIGITAL_AHEAD','2026-12-21','2026-12-27','CUSTOM',['RETAIL','PROGRAM'],None),
      ('EARLY_2025_WTD','2025-01-01','2025-01-04','WTD',['RETAIL','PROGRAM'],None),
    ]
    con=sqlite3.connect(f'file:{db.as_posix()}?mode=ro',uri=True)
    con.execute('PRAGMA query_only=ON')
    try:
        # `query_only` prevents temp views too; TEMP view DDL is temporary and never touches db file.
        con.execute('PRAGMA query_only=OFF')
        con.executescript(VIEWS_SQL)
        con.execute('PRAGMA query_only=ON')
        results=[review_context(con,oracle,c) for c in cases]
        # Global safeguards: Official net does not include Marketplace, raw digital stays ahead.
        full=oracle.aggregate(daterange(dt.date(2025,1,1),OFFICIAL_ASOF),{'RETAIL','PROGRAM'},set(oracle.stores))
        require(full[0]==3759335807,'G0004 all-horizon official total mismatch')
        require(full[5]==3663645215,'All-horizon Official As-Of budget mismatch')
        require(results[1]['total_py_cents'] is None,'2025 should have no valid PY')
        require(results[-2]['marketplace_raw_cents']>0 and results[-2]['official_cents']==0,'Marketplace ahead not preserved separately')
        require(results[7]['official_cents']+results[8]['official_cents']==results[2]['official_cents'],'Official channel decomposition differs')
        require(all(r['python_sql_parity']=='PASS' for r in results),'SQL parity failed')
    finally:con.close()
    workspace=root.parent/'retailpulse360_dev'
    require(workspace.is_dir() and not workspace.is_symlink(),'Expected local dev workspace absent')
    target=workspace/'P4_2_SQL_ANALYTICS_CANDIDATE'
    require(not target.is_symlink(),'Unsafe P4.2 candidate symlink')
    temp=Path(tempfile.mkdtemp(prefix='.P4_2_',dir=workspace))
    try:
        (temp/'analytics_views.sql').write_text(VIEWS_SQL,encoding='utf-8',newline='\n')
        (temp/'kpi_queries.sql').write_text(QUERIES_SQL,encoding='utf-8',newline='\n')
        (temp/'python_sql_parity.json').write_text(json.dumps({'generation':'G0004','scenario_results':results,'checked':len(results),
           'financial_unit':'integer_cents','fraction_behavior':'[numerator,denominator] exact; null when denominator <=0'},sort_keys=True,indent=2)+'\n',encoding='utf-8',newline='\n')
        man={'checkpoint':'P4.2','state':'CANDIDATE_ONLY','source_generation':'G0004',
             'source_manifest_sha256':G4_MANIFEST_SHA,'sqlite_sha256':digest(db),
             'cases':len(results),'parity':'ALL_PASS',
             'artifact_sha256':{p.name:digest(p) for p in sorted(temp.iterdir())}}
        (temp/'p4_2_manifest.json').write_text(json.dumps(man,sort_keys=True,indent=2)+'\n',encoding='utf-8',newline='\n')
        if target.exists():
            require(target.is_dir(),'Candidate target not a directory')
            require({p.name for p in target.iterdir()}=={p.name for p in temp.iterdir()},'Candidate file inventory altered')
            for p in temp.iterdir():
                require((target/p.name).is_file() and not (target/p.name).is_symlink() and digest(target/p.name)==digest(p),'Candidate changed: '+p.name)
            creation='VERIFIED_EXISTING_IDENTICAL_CANDIDATE'
        else:
            os.rename(temp,target)
            creation='CREATED_NEW_ATOMIC_CANDIDATE'
        require(snapshot_project_files(root)==before,'Project root changed during read-only audit')
        lines.append('PASS | GOVERNED_KPIS | Official/Budget/Gap/Achievement, Transactions/Basket, Total and Strict LFL, WTD/MTD/QTD/YTD, Digital Matched')
        lines.append(f'PASS | PYTHON_SQL_PARITY | {len(results)}/{len(results)} independent CSV-versus-SQL contexts')
        lines.append(f"PASS | STRICT_LFL | Same eligible TY/PY store cohort; YTD_2026 eligible={results[0]['strict_eligible_stores']}")
        lines.append('PASS | SCOPE_AND_CLOCK | Sat-Fri WTD PY -364d, selected partial periods, no invented 2024, channel and region filters')
        lines.append('PASS | DIGITAL | Account aggregation before Retail join; independent ahead retention; matched store-date dates')
        lines.append(f'PASS | CANDIDATE | {creation} | {target}')
        lines.append('ARTIFACTS | 4 | 2 SQL files, Python-SQL comparison JSON, manifest')
        lines.append('P4_2_MANIFEST_SHA256 | '+digest(target/'p4_2_manifest.json'))
        lines.append('PASS | PROJECT_ROOT_UNCHANGED | All existing project bytes unchanged')
        lines.append('PASS | REPORT_SCOPED | Only OUTPUT.txt changed; shared siblings untouched')
        lines.append('WARNING | P4.2 covers selected validated scenarios, not all 37 KPI IDs; deeper edge fixtures and generalized SQL source integration pending')
        lines.append('WARNING | SQL files are SQLite dialect TEMP views; SQL Server, Power Query, DAX, Desktop not tested')
        return report('PASS_P4_2_SQL_CANDIDATE_VALIDATED_PENDING_REVIEW',lines,root)
    finally:
        if temp.exists():shutil.rmtree(temp)

def main():
    p=argparse.ArgumentParser(description='RetailPulse 360 P4.2 SQLite KPI reference + independent CSV oracle candidate')
    p.add_argument('--root',required=True);p.add_argument('--report',required=True)
    a=p.parse_args();root=Path(a.root).expanduser().resolve();out=Path(a.report).expanduser().absolute()
    try:
        require(out.name=='OUTPUT.txt' and root not in out.parents,'OUTPUT.txt must be outside project')
        content=run(root);report_write(out,content);print(content)
    except Exception as exc:
        content=report('FAIL_P4_2_BLOCKED',[f'FAIL | {type(exc).__name__} | {exc}'],root)
        try:report_write(out,content)
        except Exception as w:print('REPORT_WRITE_FAILED:',w)
        print(content);raise SystemExit(1)

if __name__=='__main__':main()

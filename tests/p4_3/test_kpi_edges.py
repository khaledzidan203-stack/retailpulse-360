#!/usr/bin/env python3
"""RetailPulse 360 / P4.3 - incremental KPI edge reconciliation candidate.

Scope: KPI-009/019/020/021/033/034/035/036/037 via independent CSV
arithmetic and SQLite SELECTs. No changes to approved project or SQLite.
No GitHub, no approval history; OUTPUT.txt is an ephemeral handoff.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from collections import defaultdict
from fractions import Fraction
from pathlib import Path

REVISION = 'p4.3.0'
GENERATION = 'G0004'
GEN_SHA = 'd1135b60ff299996a05bd6edaeb26b7df9c126368984e46e8c368a031a642f92'
DB_SHA = '3e5480af50f44f6718fcc48aa0a7ea859bd9b35259838c0b3abcc8bcaed5bb5b'
P42_SHA = '18ecf306af86fc98c9ee737170425eb2203bee33fcdb16ad20c14afbdf874a7e'
ASOF = dt.date(2026, 12, 20)
COVERED = {'REPORTED_VALUE', 'REPORTED_ZERO'}
NEW_IDS = [9,19,20,21,33,34,35,36,37]
SQL_REFERENCE = '''-- P4.3 / sqlite reference patterns, use parameterized dates, stores and channels.
-- Included in executable P4.3 Python tests; these templates are not standalone views.
-- KPI-009: selected official channel sales / ALL official sales, same store/date.
-- KPI-019: calculate gap at store/channel first; denominator sums NEGATIVE gaps only.
-- KPI-020: DISTINCT operating stores from store_operating_calendar.
-- KPI-021: DISTINCT stores from reported source coverage JOIN matching fact.
-- KPI-033: count explicit MISSING_EXPECTED keys; reported zeros are not missing.
-- KPI-034: period-specific SAME Strict eligible cohort for TY and paired PY.
-- KPI-035: gap per channel = channel sales - channel allocated budget.
-- KPI-036: YoY transactions as ratio of SUMS, Total and Strict cohorts.
-- KPI-037: YoY basket uses [TY sales / TY tx] / [PY sales / PY tx] - 1.
-- Zero/negative PY denominator => NULL/N/A, never 0% or infinity.
'''


def need(test, message):
    if not test:
        raise ValueError(message)


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as inp:
        for b in iter(lambda:inp.read(1024*1024),b''):
            h.update(b)
    return h.hexdigest()


def rows(path):
    with path.open('r',encoding='utf-8-sig',newline='') as f:
        return list(csv.DictReader(f))


def daykey(day):
    return int(day.strftime('%Y%m%d'))


def days_between(start,end):
    return [start+dt.timedelta(days=k) for k in range((end-start).days+1)] if start<=end else []


def sql_in(values):
    vals=sorted(values)
    need(vals,'SQL IN cannot be empty')
    return ','.join('?' for _ in vals), vals


def rational(num,den):
    if den is None or den<=0:
        return None
    f=Fraction(num,den)
    return [f.numerator, f.denominator]


def grow(a,b):
    return rational(a-b,b)


def basket_growth(ty,py):
    # Each tuple is (sales_cents, transactions); prior basket <=0 is not a growth base.
    a,at=ty; b,bt=py
    if at<=0 or bt<=0 or b<=0:
        return None
    ratio=Fraction(a*bt,at*b)-1
    return [ratio.numerator,ratio.denominator]


def selected_period(start,end,mode):
    start=dt.date.fromisoformat(start); end=dt.date.fromisoformat(end)
    need(start<=end,'Invalid scenario date range')
    effective=min(ASOF,end)
    if effective<start:
        return [],[]
    if mode=='WTD':
        anchor=effective-dt.timedelta(days=(effective.weekday()+2)%7)
    elif mode=='MTD':
        anchor=effective.replace(day=1)
    elif mode=='YTD':
        anchor=effective.replace(month=1,day=1)
    elif mode=='CUSTOM':
        anchor=start
    else:
        raise ValueError('Unsupported period mode '+mode)
    ds=days_between(max(start,anchor),effective)
    def prior(d):
        if mode=='WTD':
            return d-dt.timedelta(days=364)
        try:
            return d.replace(year=d.year-1)
        except ValueError:
            return None
    paired=[(daykey(d),daykey(prior(d))) for d in ds if prior(d) and prior(d).year>=2025]
    # Missing 2024 is never modeled as zero.
    return [daykey(d) for d in ds], paired


def verify(root):
    need(root.is_dir() and not root.is_symlink(),'Invalid project root')
    for f in ['KPI_CONTRACTS.md','DATA_MODEL_SPEC.md','QA_TEST_MATRIX.md','PHASE_3_ETL_SNAPSHOTS.md']:
        need((root/'docs'/f).is_file(),'Missing approved contract: '+f)
    text=(root/'docs/KPI_CONTRACTS.md').read_text(encoding='utf-8')
    found={int(x) for x in re.findall(r'\|\s*`KPI-(\d{3})`\s*\|',text)}
    need(found==set(range(1,38)),'KPI contract inventory does not contain exactly 001-037')
    need('Official' in text and 'Strict' in text and 'Marketplace' in text,'KPI contract semantics absent')
    g=root/'data/processed/p3_3'
    pointer=g/'CURRENT'
    need(pointer.is_file() and not pointer.is_symlink() and pointer.read_text(encoding='utf-8').strip()==GENERATION,'Active generation must be G0004; check later refresh')
    generation=g/'generations'/GENERATION
    m=generation/'generation_manifest.json'
    need(m.is_file() and not m.is_symlink() and sha(m)==GEN_SHA,'G0004 manifest SHA mismatch')
    manifest=json.loads(m.read_text(encoding='utf-8'))
    need(manifest['classification']=='100% SYNTHETIC','Only fully synthetic inputs supported')
    need(manifest['source_asof']['OFFICIAL']==ASOF.isoformat(),'Unexpected official As-Of')
    db=root/'data/processed/p4_1/retailpulse360_g0004.sqlite'
    need(db.is_file() and not db.is_symlink() and sha(db)==DB_SHA,'P4.1 SQLite source changed')
    p42=root/'sql/sqlite/p4_2/p4_2_manifest.json'
    need(p42.is_file() and not p42.is_symlink() and sha(p42)==P42_SHA,'P4.2 published manifest SHA mismatch')
    for rel in ('analytics/fact_sales_daily.csv','analytics/fact_budget_daily.csv',
                'analytics/dim_store.csv','analytics/store_operating_calendar.csv',
                'staging/source_coverage_official.csv'):
        f=generation/rel
        need(f.is_file() and not f.is_symlink() and sha(f)==manifest['artifacts'][rel]['sha256'],'G0004 source altered: '+rel)
    con=sqlite3.connect(f'file:{db.as_posix()}?mode=ro',uri=True)
    try:
        con.execute('PRAGMA query_only=ON')
        need(con.execute('PRAGMA integrity_check').fetchone()[0]=='ok','SQLite integrity_check failed')
        need(not con.execute('PRAGMA foreign_key_check').fetchall(),'Broken foreign key')
        need(con.execute('SELECT generation_id,source_manifest_sha256 FROM generation_metadata').fetchone()==(GENERATION,GEN_SHA),'SQLite metadata mismatch')
    finally:
        con.close()
    return generation, db


class CsvOracle:
    def __init__(self, generation):
        self.sales={}; self.budget={}; self.coverage={}; self.operation={}; self.stores={}
        for r in rows(generation/'analytics/fact_sales_daily.csv'):
            k=(r['store_key'],int(r['date_key']),r['channel_key'])
            need(k not in self.sales,'Duplicate CSV sales key')
            self.sales[k]=(int(r['net_sales_cents']),int(r['transactions']))
        for r in rows(generation/'analytics/fact_budget_daily.csv'):
            k=(r['store_key'],int(r['date_key']),r['channel_key'])
            need(k not in self.budget,'Duplicate CSV budget key')
            self.budget[k]=int(r['allocated_budget_cents'])
        for r in rows(generation/'staging/source_coverage_official.csv'):
            k=(r['store_key'],int(r['date_key']),r['channel_key'])
            need(k not in self.coverage,'Duplicate CSV official coverage')
            self.coverage[k]=r['coverage_state']
        for r in rows(generation/'analytics/store_operating_calendar.csv'):
            k=(r['store_key'],int(r['date_key']))
            need(k not in self.operation,'Duplicate CSV operating key')
            self.operation[k]=int(r['is_operating'])
        for r in rows(generation/'analytics/dim_store.csv'):
            self.stores[r['store_key']]=r

    def sub_stores(self, filt):
        if filt is None:
            return set(self.stores)
        typ,val=filt
        if typ=='store':
            need(val in self.stores,'Unknown store filter')
            return {val}
        need(typ in {'region','city'},'Invalid store filter')
        return {s for s,r in self.stores.items() if r[f'{typ}_key']==val}

    def groups(self, ds,stores,ch):
        ds=set(ds)
        r=defaultdict(lambda:[0,0])
        for (s,d,c),(sales,tx) in self.sales.items():
            if s in stores and d in ds and c in ch:
                r[(s,c)][0]+=sales; r[(s,c)][1]+=tx
        b=defaultdict(int)
        for (s,d,c),amount in self.budget.items():
            if s in stores and d in ds and c in ch:
                b[(s,c)]+=amount
        return dict(r),dict(b)

    def states(self,ds,stores,ch):
        ds=set(ds)
        operating={s for (s,d),v in self.operation.items() if s in stores and d in ds and v==1}
        reporting={s for (s,d,c),v in self.coverage.items() if s in stores and d in ds and c in ch and v in COVERED and (s,d,c) in self.sales}
        missing=sum(1 for (s,d,c),v in self.coverage.items() if s in stores and d in ds and c in ch and v=='MISSING_EXPECTED')
        return len(operating),len(reporting),missing

    def strict(self,pairs,stores,ch):
        return {s for s in stores if pairs and all(self.operation.get((s,ty))==1 and self.operation.get((s,py))==1 and
            all(self.coverage.get((s,ty,c)) in COVERED and self.coverage.get((s,py,c)) in COVERED for c in ch)
            for ty,py in pairs)}


def sql_groups(con,ds,stores,ch):
    if not ds or not stores:
        return {},{}
    dp,dv=sql_in(ds);sp,sv=sql_in(stores);cp,cv=sql_in(ch)
    def query(table,fields):
        sql=f'''SELECT store_key,channel_key,{fields} FROM {table}
                  WHERE date_key IN ({dp}) AND store_key IN ({sp}) AND channel_key IN ({cp})
                  GROUP BY store_key,channel_key'''
        return con.execute(sql,dv+sv+cv).fetchall()
    ss={(s,c):[int(n),int(t)] for s,c,n,t in query('fact_sales_daily','SUM(net_sales_cents),SUM(transactions)')}
    bb={(s,c):int(n) for s,c,n in query('fact_budget_daily','SUM(allocated_budget_cents)')}
    return ss,bb


def sql_states(con,ds,stores,ch):
    if not ds or not stores:
        return (0,0,0)
    dp,dv=sql_in(ds);sp,sv=sql_in(stores);cp,cv=sql_in(ch)
    op=con.execute(f'SELECT COUNT(DISTINCT store_key) FROM store_operating_calendar WHERE is_operating=1 AND date_key IN ({dp}) AND store_key IN ({sp})',dv+sv).fetchone()[0]
    rep=con.execute(f'''SELECT COUNT(DISTINCT c.store_key) FROM source_coverage_official c
       JOIN fact_sales_daily s ON s.store_key=c.store_key AND s.date_key=c.date_key AND s.channel_key=c.channel_key
       WHERE c.date_key IN ({dp}) AND c.store_key IN ({sp}) AND c.channel_key IN ({cp})
         AND c.coverage_state IN ('REPORTED_ZERO','REPORTED_VALUE')''',dv+sv+cv).fetchone()[0]
    missing=con.execute(f'''SELECT COUNT(*) FROM source_coverage_official
        WHERE date_key IN ({dp}) AND store_key IN ({sp}) AND channel_key IN ({cp})
          AND coverage_state='MISSING_EXPECTED' ''',dv+sv+cv).fetchone()[0]
    return (op,rep,missing)


def sql_strict(con,pairs,stores,ch):
    if not pairs or not stores:
        return set()
    # Candidate cohort: disqualify store if ANY paired channel/date is unreported or nonoperating.
    pv=','.join('(?,?)' for _ in pairs)
    cp=','.join('(?)' for _ in ch)
    sp=','.join('?' for _ in stores)
    query=f'''WITH pairs(ty,py) AS (VALUES {pv}), channels(channel_key) AS (VALUES {cp})
     SELECT s.store_key FROM dim_store s WHERE s.store_key IN ({sp}) AND NOT EXISTS (
      SELECT 1 FROM pairs p CROSS JOIN channels c WHERE
       NOT EXISTS (SELECT 1 FROM store_operating_calendar o WHERE o.store_key=s.store_key AND o.date_key=p.ty AND o.is_operating=1)
       OR NOT EXISTS (SELECT 1 FROM store_operating_calendar o WHERE o.store_key=s.store_key AND o.date_key=p.py AND o.is_operating=1)
       OR NOT EXISTS (SELECT 1 FROM source_coverage_official x WHERE x.store_key=s.store_key AND x.date_key=p.ty AND x.channel_key=c.channel_key AND x.coverage_state IN ('REPORTED_ZERO','REPORTED_VALUE'))
       OR NOT EXISTS (SELECT 1 FROM source_coverage_official x WHERE x.store_key=s.store_key AND x.date_key=p.py AND x.channel_key=c.channel_key AND x.coverage_state IN ('REPORTED_ZERO','REPORTED_VALUE'))
     )'''
    vals=[v for pair in pairs for v in pair]+sorted(ch)+sorted(stores)
    return {row[0] for row in con.execute(query,vals)}


def calculate(ds,pairs,stores,ch,sale_groups,budget_groups,cohort,py_groups,strict_ty_groups,strict_py_groups,states,full_mix):
    sums=lambda g: (sum(v[0] for v in g.values()),sum(v[1] for v in g.values()))
    total_cents,total_tx=sums(sale_groups)
    py_cents,py_tx=sums(py_groups)
    sy_cents,sy_tx=sums(strict_ty_groups)
    sp_cents,sp_tx=sums(strict_py_groups)
    group_keys=set(sale_groups)|set(budget_groups)
    all_gaps={(s,c):sale_groups.get((s,c),[0,0])[0]-budget_groups.get((s,c),0) for s,c in group_keys}
    negative={k:v for k,v in all_gaps.items() if v<0}
    min_key=min(negative,key=lambda k:(negative[k],k)) if negative else None
    total_negative=sum(negative.values())
    mix_denom=sum(x[0] for x in full_mix.values())
    mix_numerator=total_cents
    by_channel={c:sum(v for (s,channel),v in all_gaps.items() if channel==c) for c in sorted(ch)}
    return {
      'sales_cents':total_cents,'transactions':total_tx,
      'kpi009_channel_mix':rational(mix_numerator,mix_denom),
      'kpi019_negative_gap_count':len(negative),
      'kpi019_selected_key':list(min_key) if min_key else None,
      'kpi019_selected_gap_cents':negative[min_key] if min_key else None,
      'kpi019_negative_gap_sum_cents':total_negative,
      'kpi019_contribution':rational(-negative[min_key],-total_negative) if min_key else None,
      'kpi020_operating_stores':states[0],
      'kpi021_reporting_stores':states[1],
      'kpi033_missing_expected_keys':states[2],
      'kpi034_strict_stores':len(cohort),
      'kpi035_gap_by_channel_cents':by_channel,
      'kpi036_total_transactions_yoy':grow(total_tx,py_tx) if pairs else None,
      'kpi036_strict_transactions_yoy':grow(sy_tx,sp_tx) if pairs and cohort else None,
      'kpi037_total_basket_yoy':basket_growth((total_cents,total_tx),(py_cents,py_tx)) if pairs else None,
      'kpi037_strict_basket_yoy':basket_growth((sy_cents,sy_tx),(sp_cents,sp_tx)) if pairs and cohort else None,
      'strict_ty_cents':sy_cents, 'strict_py_cents':sp_cents,
      'strict_ty_transactions':sy_tx, 'strict_py_transactions':sp_tx,
    }


def run_case(con,oracle,case):
    name,start,end,mode,ch,flt=case
    ds,pairs=selected_period(start,end,mode)
    need(ds,f'Empty date context: {name}')
    ch=set(ch); stores=oracle.sub_stores(flt)
    py_dates=sorted({p for _,p in pairs})
    eligible_py=bool(pairs)
    cohort_py=oracle.strict(pairs,stores,ch) if eligible_py else set()
    cohort_sql=sql_strict(con,pairs,stores,ch) if eligible_py else set()
    need(cohort_py==cohort_sql,f'{name}: strict cohort mismatch: {cohort_py^cohort_sql}')

    def from_python():
        sale,budget=oracle.groups(ds,stores,ch)
        py,_=oracle.groups(py_dates,stores,ch)
        ty_strict,_=oracle.groups(ds,cohort_py,ch)
        py_strict,_=oracle.groups(py_dates,cohort_py,ch)
        states=oracle.states(ds,stores,ch)
        all_channels,_=oracle.groups(ds,stores,{'RETAIL','PROGRAM'})
        return calculate(ds,pairs,stores,ch,sale,budget,cohort_py,py,ty_strict,py_strict,states,all_channels)

    def from_sql():
        sale,budget=sql_groups(con,ds,stores,ch)
        py,_=sql_groups(con,py_dates,stores,ch)
        ty_strict,_=sql_groups(con,ds,cohort_sql,ch)
        py_strict,_=sql_groups(con,py_dates,cohort_sql,ch)
        states=sql_states(con,ds,stores,ch)
        full_mix,_=sql_groups(con,ds,stores,{'RETAIL','PROGRAM'})
        return calculate(ds,pairs,stores,ch,sale,budget,cohort_sql,py,ty_strict,py_strict,states,full_mix)
    py=from_python(); sql=from_sql()
    need(py==sql,f'{name}: Python/SQL mismatch {[(k,py[k],sql[k]) for k in py if py[k]!=sql[k]]}')
    if not pairs:
        need(py['kpi036_total_transactions_yoy'] is None and py['kpi037_total_basket_yoy'] is None,f'{name}: fabricated prior year')
    if name=='YTD_2026':
        need(py['kpi034_strict_stores']==18,'YTD2026 strict 18-store baseline changed')
    return {'scenario':name,'selected_period_days':len(ds),'pairs':len(pairs),
            'channels':sorted(ch),'store_filter':flt,'eligible_store_population':len(stores),
            'python_sql_parity':'PASS','results':py}


def microfixtures():
    # Independent edge contracts, not assertions that they occurred in production data.
    need(rational(0,0) is None,'Zero denominator must mean N/A')
    need(rational(100,-2) is None,'Negative denominator must mean N/A')
    need(rational(-5,10)==[-1,2],'Signed numerator must remain negative')
    need(basket_growth((100,0),(100,2)) is None,'Zero TY transactions must be N/A')
    need(basket_growth((90,3),(100,2))==[-2,5],'Basket growth must be ratio of aggregates')
    need(grow(105,0) is None and grow(90,100)==[-1,10],'Growth denominator semantics')
    fake_sales={('A','RETAIL'):[100,2],('B','RETAIL'):[200,4]}
    fake_budgets={('A','RETAIL'):125,('B','RETAIL'):150}
    x=calculate([],[],{'A','B'},{'RETAIL'},fake_sales,fake_budgets,set(),{},{},{},(2,2,0),fake_sales)
    need(x['kpi019_negative_gap_sum_cents']==-25,'Exclude positive gap from negative denominator')
    need(x['kpi019_contribution']==[1,1],'Contribution negative-subset math')
    need(x['kpi035_gap_by_channel_cents']=={'RETAIL':25},'Channel gap net')
    need(x['kpi009_channel_mix']==[1,1],'Full Official denominator matches fixture')
    # Validate SQL arithmetic independently on same miniature facts.
    c=sqlite3.connect(':memory:')
    try:
        c.executescript('CREATE TABLE sales(store TEXT,channel TEXT,cents INTEGER);CREATE TABLE budget(store TEXT,channel TEXT,cents INTEGER);')
        c.executemany('INSERT INTO sales VALUES (?,?,?)',[('A','RETAIL',100),('B','RETAIL',200)])
        c.executemany('INSERT INTO budget VALUES (?,?,?)',[('A','RETAIL',125),('B','RETAIL',150)])
        rr=c.execute('''WITH keys AS (SELECT store,channel FROM sales UNION SELECT store,channel FROM budget)
         SELECT k.store,COALESCE(s.cents,0)-COALESCE(b.cents,0) FROM keys k
         LEFT JOIN sales s ON s.store=k.store AND s.channel=k.channel
         LEFT JOIN budget b ON b.store=k.store AND b.channel=k.channel ORDER BY k.store''').fetchall()
        need(rr==[('A',-25),('B',50)],'SQLite negative gap microfixture')
    finally:
        c.close()
    return 11


def scan_project(root):
    return {str(p.relative_to(root)):sha(p) for p in root.rglob('*') if p.is_file() and not p.is_symlink()}


def write_atomic(report,text):
    need(report.name=='OUTPUT.txt' and not report.is_symlink(),'Report must be normal OUTPUT.txt')
    if report.exists():need(report.is_file(),'Report destination is not a regular file')
    report.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.RetailPulse360_P43_',suffix='.tmp',dir=report.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:
            f.write(text);f.flush();os.fsync(f.fileno())
        os.replace(tmp,report)
    finally:
        if os.path.lexists(tmp):os.unlink(tmp)


def display(status,details,root):
    return '\n'.join(['PROJECT | RetailPulse 360','CHECKPOINT | P4.3-ADVANCED-KPI-CANDIDATE',
        f'REVISION | {REVISION}','MODE | INCREMENTAL_CSV_SQL_KPI_QA_CANDIDATE_ONLY',
        'OUTPUT_ROLE | EPHEMERAL_COMMUNICATION_ONLY','GITHUB | NOT_USED',f'ROOT_READ_ONLY | {root}',
        *details,f'STATUS={status}',''])


def run(root):
    before=scan_project(root)
    gen,db=verify(root)
    oracle=CsvOracle(gen)
    cases=[
      ('YTD_2026','2026-01-01','2026-12-31','YTD',['RETAIL','PROGRAM'],None),
      ('MTD_DEC2026','2026-12-01','2026-12-31','MTD',['RETAIL','PROGRAM'],None),
      ('WTD_DEC20','2026-12-01','2026-12-20','WTD',['RETAIL','PROGRAM'],None),
      ('REGION_R02','2026-07-05','2026-08-06','CUSTOM',['RETAIL','PROGRAM'],('region','R02')),
      ('RETAIL_YTD','2026-01-01','2026-12-31','YTD',['RETAIL'],None),
      ('PROGRAM_YTD','2026-01-01','2026-12-31','YTD',['PROGRAM'],None),
      ('CLOSED_S019','2026-01-01','2026-12-31','YTD',['RETAIL','PROGRAM'],('store','S019')),
      ('YTD_2025_NO_PY','2025-01-01','2025-12-31','YTD',['RETAIL','PROGRAM'],None),
    ]
    con=sqlite3.connect(f'file:{db.as_posix()}?mode=ro',uri=True)
    con.execute('PRAGMA query_only=ON')
    try:
        results=[run_case(con,oracle,x) for x in cases]
        fixture_count=microfixtures()
    finally:
        con.close()
    need(scan_project(root)==before,'Approved project changed during P4.3 read-only QA')
    workspace=root.parent/'retailpulse360_dev'
    need(workspace.is_dir() and not workspace.is_symlink(),'Local dev workspace not available')
    target=workspace/'P4_3_KPI_EDGE_CANDIDATE'
    need(not target.is_symlink(),'Symlinked candidate not allowed')
    temp=Path(tempfile.mkdtemp(prefix='.P4_3_',dir=workspace))
    try:
        j={'checkpoint':'P4.3','source_generation':GENERATION,'input_database_sha256':DB_SHA,
           'tested_incremental_kpi_ids':[f'KPI-{i:03d}' for i in NEW_IDS],
           'scope':'incremental Python/SQLite parity, NOT full KPI approval or DAX runtime',
           'scenarios':results,'edge_microfixtures':fixture_count}
        (temp/'kpi_edge_parity.json').write_text(json.dumps(j,sort_keys=True,indent=2)+'\n',encoding='utf-8',newline='\n')
        (temp/'kpi_edge_queries.sql').write_text(SQL_REFERENCE,encoding='utf-8',newline='\n')
        matrix={'contract_ids':37,'previously_tested_contexts':13,
                'incremental_kpi_ids':[f'KPI-{i:03d}' for i in NEW_IDS],
                'incremental_results':'PYTHON_SQL_PARITY_ONLY',
                'not_yet_proven':'Full 37 KPI scenario/edge coverage, comprehensive KPI SQL API, DAX, Power BI Desktop',
                'phase4_status':'PARTIAL_SQLITE_VALIDATION_ONLY'}
        (temp/'kpi_coverage_scope.json').write_text(json.dumps(matrix,sort_keys=True,indent=2)+'\n',encoding='utf-8',newline='\n')
        manifest={'checkpoint':'P4.3','state':'CANDIDATE_ONLY','source_generation':GENERATION,
                  'sqlite_sha256':DB_SHA,'source_manifest_sha256':GEN_SHA,
                  'scenarios':len(results),'microfixtures':fixture_count,
                  'artifact_sha256':{p.name:sha(p) for p in sorted(temp.iterdir())}}
        (temp/'p4_3_manifest.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n',encoding='utf-8',newline='\n')
        if target.exists():
            need(target.is_dir(),'Candidate path is not a directory')
            need({p.name for p in target.iterdir()}=={p.name for p in temp.iterdir()},'Candidate inventory differs')
            for p in temp.iterdir():
                need((target/p.name).is_file() and not (target/p.name).is_symlink() and sha(p)==sha(target/p.name),'Candidate artifact changed: '+p.name)
            creation='VERIFIED_EXISTING_IDENTICAL_CANDIDATE'
        else:
            os.rename(temp,target)
            creation='CREATED_NEW_ATOMIC_CANDIDATE'
        need(scan_project(root)==before,'Approved project changed during candidate generation')
        lines=['PASS | INPUT_GATES | Phase 1 KPI 001..037, G0004 SHA, P4.1 SQLite, P4.2 manifest',
               'PASS | KPI_INCREMENTAL_PARITY | 9 KPI contracts: 009/019/020/021/033/034/035/036/037',
               f'PASS | SCENARIO_PARITY | {len(results)}/{len(results)} CSV versus SQLite contexts',
               f'PASS | EDGE_FIXTURES | {fixture_count} ratio, negative gap, zero denominator and SQL checks',
               'PASS | STRICT_COHORT | Identical TY/PY cohort and summed transaction/basket growth',
               f'PASS | CANDIDATE | {creation} | {target}',
               'ARTIFACTS | 4 | KPI results, SQL notes, coverage scope, manifest',
               f'MANIFEST_SHA256 | {sha(target/"p4_3_manifest.json")}',
               'PASS | PROJECT_ROOT_UNCHANGED | All existing approved bytes preserved',
               'PASS | REPORT_SCOPED | OUTPUT.txt only; siblings untouched',
               'WARNING | Full KPI-001..037 sign-off and DAX/Power BI runtime NOT TESTED',
               'WARNING | G0004-only SQLite; generic future-generation refresh NOT TESTED']
        return display('PASS_P4_3_INCREMENTAL_KPI_CANDIDATE_VALIDATED_PENDING_REVIEW',lines,root)
    finally:
        if temp.exists():shutil.rmtree(temp)


def main():
    p=argparse.ArgumentParser(description='RetailPulse 360 P4.3 incremental 9 KPI contract CSV/SQLite QA (read-only project)')
    p.add_argument('--root',required=True);p.add_argument('--report',required=True)
    args=p.parse_args();root=Path(args.root).expanduser().resolve();report=Path(args.report).expanduser().absolute()
    try:
        need(report.name=='OUTPUT.txt' and root not in report.parents,'Report must be external OUTPUT.txt')
        value=run(root);write_atomic(report,value);print(value)
    except Exception as e:
        value=display('FAIL_P4_3_BLOCKED',[f'FAIL | {type(e).__name__} | {e}'],root)
        try:write_atomic(report,value)
        except Exception as w:print('REPORT_WRITE_FAILED:',w)
        print(value)
        raise SystemExit(1)

if __name__=='__main__':main()

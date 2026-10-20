#!/usr/bin/env python3
"""RetailPulse 360 consolidated Phase 4: KPI 001..037 CSV/SQLite parity and
portable Power Query sources. Standard library, offline, no GitHub.

Run against approved locally published G0004. Validates before ONE scoped
atomic installation. Power Query/DAX/Desktop are explicitly NOT runtime-tested.
"""
from __future__ import annotations
import argparse
import csv
import datetime as D
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from collections import defaultdict
from fractions import Fraction
from pathlib import Path

sys.dont_write_bytecode=True
REV="phase4-consolidated.1"
GEN_SHA="d1135b60ff299996a05bd6edaeb26b7df9c126368984e46e8c368a031a642f92"
DB_SHA="3e5480af50f44f6718fcc48aa0a7ea859bd9b35259838c0b3abcc8bcaed5bb5b"
MAN_SHA="ee35f99526cc637d62da4384e0493781e317e3946804f018a6a50e0d06947a75"
OFFICIAL=D.date(2026,12,20)
DIGITAL=D.date(2026,12,27)
COVERED={'REPORTED_ZERO','REPORTED_VALUE'}
CH={'RETAIL','PROGRAM'}
KPI_IDS={f'KPI-{x:03}' for x in range(1,38)}

class GateError(Exception): pass

def need(test,message):
    if not test: raise GateError(message)

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''): h.update(b)
    return h.hexdigest()

def normal(path):
    need(path.is_file() and not path.is_symlink(),f'Missing or symlinked file: {path}')

def read_csv(path):
    normal(path)
    with path.open('r',encoding='utf-8-sig',newline='') as f:
        return list(csv.DictReader(f))

def days(a,b):
    return [a+D.timedelta(days=i) for i in range((b-a).days+1)] if a<=b else []

def date_key(d): return int(d.strftime('%Y%m%d'))

def prior(d,mode):
    if mode=='WTD':return d-D.timedelta(days=364)
    try:return d.replace(year=d.year-1)
    except ValueError:return None

def date_context(start,selected_end,mode):
    end=min(selected_end,OFFICIAL)
    if start>end: return [],[],False
    if mode=='WTD':anchor=end-D.timedelta(days=(end.weekday()+2)%7)
    elif mode=='MTD':anchor=end.replace(day=1)
    elif mode=='QTD':anchor=end.replace(month=((end.month-1)//3)*3+1,day=1)
    elif mode=='YTD':anchor=end.replace(month=1,day=1)
    elif mode=='CUSTOM':anchor=start
    else:raise GateError('Unsupported period '+mode)
    selected=days(max(anchor,start),end)
    paired=[(d,prior(d,mode)) for d in selected if prior(d,mode) is not None and prior(d,mode).year>=2025]
    valid_py=bool(selected) and all(d.year==2026 for d in selected) and len(paired)==len(selected)
    return selected,paired,valid_py

def ratio(a,b):return None if b is None or b<=0 else Fraction(a,b)

def growth(a,b):return None if b is None or b<=0 else Fraction(a-b,b)

def basket_growth(ty,py):
    tnet,ttx=ty; pnet,ptx=py
    if ttx<=0 or ptx<=0 or pnet<=0:return None
    return Fraction(tnet*ptx-pnet*ttx,ttx*pnet)

def fraction_repr(v):
    if isinstance(v,Fraction):return [v.numerator,v.denominator]
    if isinstance(v,dict):return {str(k):fraction_repr(x) for k,x in sorted(v.items(),key=lambda a:str(a[0]))}
    if isinstance(v,tuple):return [fraction_repr(x) for x in v]
    if isinstance(v,list):return [fraction_repr(x) for x in v]
    return v

def valid_source(root):
    need(root.is_dir() and not root.is_symlink(),'Project root missing or symlink')
    for d in ('KPI_CONTRACTS.md','DATA_MODEL_SPEC.md','QA_TEST_MATRIX.md','PHASE_3_ETL_SNAPSHOTS.md'):
        normal(root/'docs'/d)
    contract=(root/'docs/KPI_CONTRACTS.md').read_text(encoding='utf-8')
    found=set(re.findall(r'KPI-\d{3}',contract))
    need(KPI_IDS.issubset(found),'KPI-001..037 contract catalogue incomplete')
    current=root/'data/processed/p3_3/CURRENT';normal(current)
    need(current.read_text(encoding='utf-8').strip()=='G0004','CURRENT changed: consolidated baseline explicitly requires G0004')
    gen=root/'data/processed/p3_3/generations/G0004'
    manifest_file=gen/'generation_manifest.json';normal(manifest_file)
    need(sha(manifest_file)==GEN_SHA,'G0004 generation signature changed')
    manifest=json.loads(manifest_file.read_text(encoding='utf-8'))
    need(manifest.get('classification')=='100% SYNTHETIC','Non-synthetic input prohibited')
    need(manifest.get('source_asof')=={'OFFICIAL':str(OFFICIAL),'MARKETPLACE':str(DIGITAL)},'As-Of differs from approved baseline')
    for rel,metadata in manifest['artifacts'].items():
        path=gen/rel
        normal(path)
        need(sha(path)==metadata['sha256'],'G0004 artifact altered: '+rel)
    db=root/'data/processed/p4_1/retailpulse360_g0004.sqlite'
    m=root/'data/processed/p4_1/p4_1_manifest.json'
    normal(db);normal(m)
    need(sha(db)==DB_SHA and sha(m)==MAN_SHA,'P4.1 SQLite signed baseline changed')
    con=sqlite3.connect(f'file:{db.as_posix()}?mode=ro',uri=True)
    try:
        con.execute('PRAGMA query_only=ON')
        need(con.execute('PRAGMA integrity_check').fetchone()[0]=='ok','SQLite integrity failed')
        need(not con.execute('PRAGMA foreign_key_check').fetchall(),'SQLite FK failure')
        meta=con.execute('SELECT generation_id,official_asof,marketplace_asof,source_manifest_sha256 FROM generation_metadata').fetchone()
        need(meta==('G0004',str(OFFICIAL),str(DIGITAL),GEN_SHA),'SQLite source generation metadata differs')
    finally:con.close()
    return gen,db

class CSVOracle:
    def __init__(self,gen):
        self.stores={r['store_key']:r for r in read_csv(gen/'analytics/dim_store.csv')}
        self.sales={};self.budget={};self.coverage={};self.op={};self.digital={}
        for r in read_csv(gen/'analytics/fact_sales_daily.csv'):
            k=(r['store_key'],int(r['date_key']),r['channel_key'])
            need(k not in self.sales,'Duplicate sales grain')
            self.sales[k]=tuple(int(r[x]) for x in ('net_sales_cents','gross_sales_cents','returns_amount_cents','transactions','units'))
        for r in read_csv(gen/'analytics/fact_budget_daily.csv'):
            k=(r['store_key'],int(r['date_key']),r['channel_key'])
            need(k not in self.budget,'Duplicate budget grain')
            self.budget[k]=int(r['allocated_budget_cents'])
        for r in read_csv(gen/'staging/source_coverage_official.csv'):
            k=(r['store_key'],int(r['date_key']),r['channel_key'])
            need(k not in self.coverage,'Duplicate coverage grain')
            self.coverage[k]=r['coverage_state']
        for r in read_csv(gen/'analytics/store_operating_calendar.csv'):
            self.op[r['store_key'],int(r['date_key'])]=int(r['is_operating'])
        for r in read_csv(gen/'analytics/fact_marketplace_daily.csv'):
            k=(r['store_key'],int(r['date_key']),r['account_key'])
            need(k not in self.digital,'Duplicate marketplace grain')
            self.digital[k]=int(r['attributed_retail_net_sales_cents'])
    def scope(self,flt):
        if flt is None:return set(self.stores)
        t,x=flt
        if t=='store':return {x} if x in self.stores else set()
        need(t in {'city','region'},'Invalid store filter')
        return {s for s,r in self.stores.items() if r[f'{t}_key']==x}
    def group(self,day_set,stores,channels):
        out=defaultdict(lambda:[0]*6)
        d=set(date_key(x) for x in day_set)
        for (s,k,c),r in self.sales.items():
            if k in d and s in stores and c in channels:
                v=out[s,c]
                for i,x in enumerate(r):v[i]+=x
        for (s,k,c),n in self.budget.items():
            if k in d and s in stores and c in channels:out[s,c][5]+=n
        return dict(out)
    def state(self,day_set,stores,channels):
        d={date_key(x) for x in day_set}
        operating={s for (s,k),v in self.op.items() if s in stores and k in d and v==1}
        reported={s for (s,k,c),state in self.coverage.items() if s in stores and k in d and c in channels and state in COVERED and (s,k,c) in self.sales}
        missing=sum(1 for (s,k,c),v in self.coverage.items() if s in stores and k in d and c in channels and v=='MISSING_EXPECTED')
        return (len(operating),len(reported),missing)
    def strict(self,pairs,stores,channels):
        if not pairs:return set()
        return {s for s in stores if all(self.op.get((s,date_key(ty)))==1 and self.op.get((s,date_key(py)))==1 and
            all(self.coverage.get((s,date_key(ty),c)) in COVERED and self.coverage.get((s,date_key(py),c)) in COVERED for c in channels)
            for ty,py in pairs)}
    def digital_calc(self,selected,stores,has_retail):
        keys={date_key(x) for x in selected if x<=DIGITAL}
        match={k for k in keys if k<=date_key(OFFICIAL)}
        raw=sum(n for (s,k,a),n in self.digital.items() if s in stores and k in keys)
        if not has_retail:return raw,None,None
        byday=defaultdict(int)
        for (s,k,a),n in self.digital.items():
            if s in stores and k in match:byday[s,k]+=n
        dm=rm=0
        for (s,k),amount in byday.items():
            if self.coverage.get((s,k,'RETAIL')) in COVERED and (s,k,'RETAIL') in self.sales:
                dm+=amount;rm+=self.sales[s,k,'RETAIL'][0]
        return raw,dm,rm

# All SQL measurements below query SQLite independently, never the Python CSV arrays.
def sql_in(seq):
    vals=sorted(seq)
    return (','.join('?' for _ in vals) if vals else 'NULL'),vals

def sql_group(con,day_set,stores,channels):
    if not day_set or not stores or not channels:return {}
    dp,ds=sql_in({date_key(x) for x in day_set});sp,ss=sql_in(stores);cp,cc=sql_in(channels)
    clause=f'date_key IN ({dp}) AND store_key IN ({sp}) AND channel_key IN ({cp})'
    args=ds+ss+cc
    res=defaultdict(lambda:[0]*6)
    for s,c,net,gross,returns,tx,units in con.execute(
        f'''SELECT store_key,channel_key,SUM(net_sales_cents),SUM(gross_sales_cents),
         SUM(returns_amount_cents),SUM(transactions),SUM(units) FROM fact_sales_daily
         WHERE {clause} GROUP BY store_key,channel_key''',args):
        res[s,c][:5]=[net,gross,returns,tx,units]
    for s,c,n in con.execute(f'''SELECT store_key,channel_key,SUM(allocated_budget_cents) FROM fact_budget_daily
          WHERE {clause} GROUP BY store_key,channel_key''',args):
        res[s,c][5]=n
    return dict(res)

def sql_state(con,day_set,stores,channels):
    if not day_set or not stores:return (0,0,0)
    dp,ds=sql_in({date_key(x) for x in day_set});sp,ss=sql_in(stores);cp,cc=sql_in(channels)
    op=con.execute(f'SELECT COUNT(DISTINCT store_key) FROM store_operating_calendar WHERE is_operating=1 AND date_key IN ({dp}) AND store_key IN ({sp})',ds+ss).fetchone()[0]
    if not channels:return (op,0,0)
    reporting=con.execute(f'''SELECT COUNT(DISTINCT c.store_key) FROM source_coverage_official c
         INNER JOIN fact_sales_daily x ON x.store_key=c.store_key AND x.date_key=c.date_key AND x.channel_key=c.channel_key
         WHERE c.date_key IN ({dp}) AND c.store_key IN ({sp}) AND c.channel_key IN ({cp})
         AND c.coverage_state IN ('REPORTED_VALUE','REPORTED_ZERO')''',ds+ss+cc).fetchone()[0]
    missing=con.execute(f'''SELECT COUNT(*) FROM source_coverage_official WHERE coverage_state='MISSING_EXPECTED'
         AND date_key IN ({dp}) AND store_key IN ({sp}) AND channel_key IN ({cp})''',ds+ss+cc).fetchone()[0]
    return op,reporting,missing

def sql_strict(con,pairs,stores,channels):
    if not pairs or not stores:return set()
    pv=','.join('(?,?)' for _ in pairs);cp=','.join('(?)' for _ in channels);sp=','.join('?' for _ in stores)
    sql=f'''WITH pairs(ty,py) AS (VALUES {pv}), channels(channel_key) AS (VALUES {cp})
      SELECT s.store_key FROM dim_store s WHERE s.store_key IN ({sp}) AND NOT EXISTS (
       SELECT 1 FROM pairs p CROSS JOIN channels c WHERE
         NOT EXISTS(SELECT 1 FROM store_operating_calendar op WHERE op.store_key=s.store_key AND op.date_key=p.ty AND op.is_operating=1)
         OR NOT EXISTS(SELECT 1 FROM store_operating_calendar op WHERE op.store_key=s.store_key AND op.date_key=p.py AND op.is_operating=1)
         OR NOT EXISTS(SELECT 1 FROM source_coverage_official co WHERE co.store_key=s.store_key AND co.date_key=p.ty AND co.channel_key=c.channel_key AND co.coverage_state IN ('REPORTED_ZERO','REPORTED_VALUE'))
         OR NOT EXISTS(SELECT 1 FROM source_coverage_official co WHERE co.store_key=s.store_key AND co.date_key=p.py AND co.channel_key=c.channel_key AND co.coverage_state IN ('REPORTED_ZERO','REPORTED_VALUE'))
      )'''
    params=[v for ty,py in pairs for v in (date_key(ty),date_key(py))]+sorted(channels)+sorted(stores)
    return {s for (s,) in con.execute(sql,params)}

def sql_digital(con,selected,stores,has_retail):
    dates={date_key(x) for x in selected if x<=DIGITAL}
    if not dates or not stores:return 0, (0 if has_retail else None),(0 if has_retail else None)
    dp,ds=sql_in(dates);sp,ss=sql_in(stores)
    raw=con.execute(f'SELECT COALESCE(SUM(attributed_retail_net_sales_cents),0) FROM fact_marketplace_daily WHERE date_key IN ({dp}) AND store_key IN ({sp})',ds+ss).fetchone()[0]
    if not has_retail:return raw,None,None
    matched={k for k in dates if k<=date_key(OFFICIAL)}
    if not matched:return raw,0,0
    mp,mv=sql_in(matched)
    # Accounts must be aggregated before joining each single Retail denominator.
    row=con.execute(f'''WITH attributed AS (
        SELECT m.store_key,m.date_key,SUM(m.attributed_retail_net_sales_cents) AS digital
        FROM fact_marketplace_daily m WHERE m.date_key IN ({mp}) AND m.store_key IN ({sp})
        GROUP BY m.store_key,m.date_key)
      SELECT COALESCE(SUM(a.digital),0),COALESCE(SUM(r.net_sales_cents),0) FROM attributed a
        JOIN fact_sales_daily r ON r.store_key=a.store_key AND r.date_key=a.date_key AND r.channel_key='RETAIL'
        JOIN source_coverage_official c ON c.store_key=r.store_key AND c.date_key=r.date_key AND c.channel_key='RETAIL'
       WHERE c.coverage_state IN ('REPORTED_ZERO','REPORTED_VALUE')''',mv+ss).fetchone()
    return raw,row[0],row[1]

def sums(groups):
    v=[0]*6
    for row in groups.values():
        for i,x in enumerate(row):v[i]+=x
    return v

def measures(group,pgroup,strict_group,strict_prev,cohort,states,full_official,digital,valid_py,selected_start,selected_end,mode,channels):
    v=sums(group); p=sums(pgroup);st=sums(strict_group);sp=sums(strict_prev)
    channel_vals={c:sum(row[0] for (s,ch),row in group.items() if ch==c) for c in CH}
    gaps={(s,c):row[0]-row[5] for (s,c),row in group.items()}
    negatives={f'{s}/{c}':-g for (s,c),g in gaps.items() if g<0}
    sum_negative=sum(negatives.values())
    contribution={k:ratio(n,sum_negative) for k,n in negatives.items()}
    by_channel={c:sum(g for (s,ch),g in gaps.items() if c==ch) for c in sorted(channels)}
    raw,matched,retail_matched=digital
    match_through=min(selected_end,OFFICIAL,DIGITAL)
    comparable_window=(match_through>=selected_start)
    if not comparable_window:
        matched=None
        retail_matched=None
    values={
        'KPI-001':channel_vals['RETAIL'],'KPI-002':channel_vals['PROGRAM'],
        'KPI-003':v[0],'KPI-004':v[1],'KPI-005':v[2],
        'KPI-006':v[5],'KPI-007':v[0]-v[5],
        'KPI-008':ratio(v[0],v[5]),
        'KPI-009':ratio(v[0],sums(full_official)[0]),
        'KPI-010':v[3],'KPI-011':v[4],
        'KPI-012':ratio(v[0],v[3]),'KPI-013':ratio(v[4],v[3]),
        'KPI-014':p[0] if valid_py else None,
        'KPI-015':growth(v[0],p[0]) if valid_py else None,
        'KPI-016':st[0] if valid_py and cohort else None,
        'KPI-017':sp[0] if valid_py and cohort else None,
        'KPI-018':growth(st[0],sp[0]) if valid_py and cohort else None,
        'KPI-019':contribution if sum_negative>0 else None,
        'KPI-020':states[0],'KPI-021':states[1],
        'KPI-022':v[0] if mode=='WTD' else None,
        'KPI-023':v[0] if mode=='MTD' else None,
        'KPI-024':v[0] if mode=='QTD' else None,
        'KPI-025':v[0] if mode=='YTD' else None,
        'KPI-026':v[5] if mode in {'WTD','MTD','QTD','YTD'} else None,
        'KPI-027':raw,
        'KPI-028':match_through.isoformat() if comparable_window else None,
        'KPI-029':matched,
        'KPI-030':retail_matched,
        'KPI-031':ratio(matched,retail_matched) if matched is not None else None,
        'KPI-032':(OFFICIAL-DIGITAL).days,
        'KPI-033':states[2],
        'KPI-034':len(cohort),
        'KPI-035':by_channel,
        'KPI-036':{'total':growth(v[3],p[3]) if valid_py else None,
                   'strict':growth(st[3],sp[3]) if valid_py and cohort else None},
        'KPI-037':{'total':basket_growth((v[0],v[3]),(p[0],p[3])) if valid_py else None,
                   'strict':basket_growth((st[0],st[3]),(sp[0],sp[3])) if valid_py and cohort else None}
    }
    need(set(values)==KPI_IDS,'KPI catalogue missing calculations')
    return values

def run_case(con,oracle,scenario):
    name,start,end,mode,channels,flt=scenario
    start=D.date.fromisoformat(start);end=D.date.fromisoformat(end)
    need(end>=start,'Invalid selected dates')
    channels=set(channels)
    need(channels and channels.issubset(CH),'Invalid selected channel(s)')
    stores=oracle.scope(flt)
    need(stores,'Selected store filter has no stores')
    dd,pairs,valid_py=date_context(start,end,mode)
    if not valid_py:pairs=[]
    py_dates=[py for _,py in pairs]
    pycohort=oracle.strict(pairs,stores,channels) if valid_py else set()
    sqlcohort=sql_strict(con,pairs,stores,channels) if valid_py else set()
    need(pycohort==sqlcohort,f'{name}: Strict LFL eligible population differs')
    selected=days(start,end)
    def calculate(engine):
        if engine=='csv':
            g=oracle.group; state=oracle.state; digital=oracle.digital_calc
        else:
            g=lambda dates,s,c:sql_group(con,dates,s,c)
            state=lambda dates,s,c:sql_state(con,dates,s,c)
            digital=lambda dates,s,r:sql_digital(con,dates,s,r)
        group=g(dd,stores,channels)
        return measures(group,g(py_dates,stores,channels),g(dd,pycohort,channels),
            g(py_dates,pycohort,channels),pycohort,state(dd,stores,channels),
            g(dd,stores,CH),digital(selected,stores,'RETAIL' in channels),valid_py,start,end,mode,channels)
    a=calculate('csv');b=calculate('sql')
    for k in sorted(KPI_IDS):
        need(a[k]==b[k],f'{name} {k} mismatch: CSV={a[k]!r}; SQLite={b[k]!r}')
    need(a['KPI-003']==a['KPI-001']+a['KPI-002'],f'{name} sales identity invalid')
    need(a['KPI-003']==a['KPI-004']-a['KPI-005'],f'{name} returns reconciliation invalid')
    need(a['KPI-007']==a['KPI-003']-a['KPI-006'],f'{name} budget gap invalid')
    need(a['KPI-032']==-7,f'{name} source lag sign invalid')
    if 'RETAIL' not in channels:need(a['KPI-029'] is None and a['KPI-031'] is None,'Digital ratio leaked into non-retail channel')
    if end.year==2025:need(a['KPI-014'] is None and a['KPI-015'] is None,'Invented 2024 PY')
    if start>OFFICIAL:need(a['KPI-028'] is None and a['KPI-029'] is None and a['KPI-030'] is None,'Out-of-window digital comparison invalid')
    return {'case':name,'mode':mode,'valid_py':valid_py,'cohort':len(pycohort),'kpis_compared':len(KPI_IDS),
            'official_cents':a['KPI-003'],'budget_cents':a['KPI-006'],
            'marketplace_raw_cents':a['KPI-027'],'matched_marketplace_cents':a['KPI-029'],
            'kpi_ids':sorted(KPI_IDS)}

def independent_edges():
    # Edge fixtures deliberately run without any generation-dependent facts.
    need(ratio(0,0) is None,'0 denominator must be N/A')
    need(ratio(-2,5)==Fraction(-2,5),'Negative returns net should not be clamped')
    need(ratio(10,-1) is None,'Negative denominator must not yield ratio')
    need(growth(20,10)==Fraction(1,1),'Growth of totals')
    need(growth(0,0) is None,'No PY -> N/A')
    need(basket_growth((300,3),(200,4))==Fraction(1,1),'Basket growth ratio of aggregates')
    need(basket_growth((100,0),(50,1)) is None,'No transactions basket N/A')
    need(prior(D.date(2026,3,14),'WTD')==D.date(2025,3,15),'364 day week alignment')
    need(prior(D.date(2024,2,29),'MTD') is None,'Leap day should not be fabricated')
    need(date_context(D.date(2025,1,1),D.date(2025,12,31),'YTD')[2] is False,'No 2024 PY')
    need(date_context(D.date(2026,12,21),D.date(2026,12,27),'CUSTOM')[0]==[],'Source freshness official cap')
    need(measures({('s','RETAIL'):[900,1000,100,2,4,1100]}, {},{},{},set(),(1,1,0),
         {('s','RETAIL'):[900,1000,100,2,4,1100]},(300,150,900),False,D.date(2026,12,21),D.date(2026,12,27),'CUSTOM',{'RETAIL'})['KPI-007']==-200,'Gap fixture')
    return 12

# Dynamically parameterized Power Query loads governed CSVs without requiring a
# SQLite ODBC driver; semantic model must be validated separately in Desktop.
POWER_COLUMNS={
 'dim_date':[('date_key','Int64.Type'),('calendar_date','type date'),('year','Int64.Type'),('quarter','Int64.Type'),('month','Int64.Type'),('month_start','type date'),('year_month','Int64.Type'),('weekday_number','Int64.Type'),('week_start_saturday','type date'),('week_end_friday','type date')],
 'dim_store':[('store_key','type text'),('store_name','type text'),('region_key','type text'),('region_name','type text'),('city_key','type text'),('city_name','type text'),('store_profile','type text'),('lifecycle_cohort','type text'),('open_date','type date'),('last_trading_date','type date')],
 'dim_channel':[('channel_key','type text'),('channel_name','type text'),('is_additive','Int64.Type')],
 'dim_marketplace_account':[('account_key','type text'),('account_name','type text'),('account_type','type text')],
 'bridge_account_store_period':[('account_key','type text'),('store_key','type text'),('valid_from','type date'),('valid_to','type date')],
 'store_operating_calendar':[('store_key','type text'),('date_key','Int64.Type'),('calendar_date','type date'),('is_operating','Int64.Type'),('lifecycle_state','type text')],
 'fact_sales_daily':[('store_key','type text'),('date_key','Int64.Type'),('channel_key','type text'),('gross_sales_cents','Int64.Type'),('returns_amount_cents','Int64.Type'),('net_sales_cents','Int64.Type'),('transactions','Int64.Type'),('units','Int64.Type'),('source_snapshot_id','type text'),('lineage_hash','type text')],
 'fact_budget_monthly':[('store_key','type text'),('month_start','type date'),('channel_key','type text'),('monthly_target_cents','Int64.Type'),('budget_version','type text')],
 'fact_budget_daily':[('store_key','type text'),('date_key','Int64.Type'),('channel_key','type text'),('allocated_budget_cents','Int64.Type'),('budget_version','type text'),('allocation_policy_version','type text')],
 'fact_marketplace_daily':[('store_key','type text'),('account_key','type text'),('date_key','Int64.Type'),('attributed_retail_net_sales_cents','Int64.Type'),('orders','Int64.Type'),('units','Int64.Type'),('source_snapshot_id','type text'),('lineage_hash','type text')],
 'source_coverage_official':[('store_key','type text'),('date_key','Int64.Type'),('channel_key','type text'),('coverage_state','type text'),('evidence','type text')],
 'source_coverage_marketplace':[('account_key','type text'),('date_key','Int64.Type'),('coverage_state','type text'),('evidence','type text')],
 'dq_findings':[('check_id','type text'),('severity','type text'),('source_family','type text'),('affected_key','type text'),('reason','type text'),('evidence','type text')]
}

FN_M='''(relativeFile as text, columnTypes as list) as table =>
let
    Root = Text.TrimEnd(pProjectRoot, {"\\", "/"}),
    GenInput = Text.Upper(Text.Trim(pGeneration)),
    Generation = if GenInput = "CURRENT"
        then Text.Trim(Text.FromBinary(File.Contents(Root & "\\data\\processed\\p3_3\\CURRENT"), TextEncoding.Utf8))
        else GenInput,
    ValidGeneration = if Text.Length(Generation) = 5 and Text.Start(Generation, 1) = "G"
        and (try Number.FromText(Text.Range(Generation, 1, 4)) otherwise null) <> null
        then Generation else error "Invalid generation identifier",
    Path = Root & "\\data\\processed\\p3_3\\generations\\" & ValidGeneration & "\\" & Text.Replace(relativeFile, "/", "\\"),
    Csv = Csv.Document(File.Contents(Path), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),
    Head = Table.PromoteHeaders(Csv, [PromoteAllScalars=true]),
    ExactColumns = if Table.ColumnNames(Head) = List.Transform(columnTypes, each _{0}) then Head
        else error "CSV column contract differs",
    DateFields = List.Transform(List.Select(columnTypes, each _{1} = type date), each _{0}),
    CleanDates = Table.ReplaceValue(ExactColumns, "", null, Replacer.ReplaceValue, DateFields),
    Typed = Table.TransformColumnTypes(CleanDates, columnTypes, "en-US")
in
    Typed
'''

def power_files():
    files={
      '00_pProjectRoot.txt':'Power Query Text parameter, REQUIRED: choose this machine local project root (e.g. select folder) with no trailing slash. Do not hardcode any drive in shared artifact.\n',
      '01_pGeneration.txt':'Power Query Text parameter, default CURRENT. Fixed G0004 may be used for baseline snapshots.\n',
      '02_fnLoadCsv.m':FN_M,
    }
    for name,cols in POWER_COLUMNS.items():
        rel='staging/' if name.startswith('source_coverage') else 'analytics/'
        colstr=',\n        '.join('{"'+c+'", '+typ+'}' for c,typ in cols)
        files[f'q_{name}.m']='let\n    Source = fnLoadCsv("'+rel+name+'.csv", {\n        '+colstr+'\n    })\nin\n    Source\n'
    files['q_generation_metadata.m']='''let
    Root = Text.TrimEnd(pProjectRoot, {"\\", "/"}),
    Gen = if Text.Upper(Text.Trim(pGeneration)) = "CURRENT"
       then Text.Trim(Text.FromBinary(File.Contents(Root & "\\data\\processed\\p3_3\\CURRENT"), TextEncoding.Utf8))
       else Text.Trim(pGeneration),
    Manifest = Json.Document(File.Contents(Root & "\\data\\processed\\p3_3\\generations\\" & Gen & "\\generation_manifest.json")),
    Rows = #table({"generation_id", "official_asof", "marketplace_asof"}, {{
       Gen, Date.FromText(Manifest[source_asof][OFFICIAL]), Date.FromText(Manifest[source_asof][MARKETPLACE])}}),
    Typed = Table.TransformColumnTypes(Rows, {{"generation_id", type text}, {"official_asof", type date}, {"marketplace_asof", type date}})
in
    Typed
'''
    files['README_IMPORT.txt']='''RetailPulse 360 — Power Query source package, STATIC SOURCE ONLY

1. In Power BI Desktop create two TEXT parameters: pProjectRoot = your local RetailPulse 360 project root; pGeneration = CURRENT.
2. Create blank query fnLoadCsv by pasting 02_fnLoadCsv.m in Advanced Editor; disable load for function.
3. Create individual blank queries named for q_*.m files and paste each file; rename to filenames without q_ prefix if desired.
4. Use Import mode. All money columns are Int64 cents; divide by 100 in DAX display measures, never in raw facts.
5. Create active single-direction dimension-to-fact relationships: dim_date[date_key], dim_store[store_key], dim_channel[channel_key] to official sales/budget facts; dim_marketplace_account[account_key] to marketplace fact. Link date/store to marketplace too, with unambiguous one-to-many relationships. No fact-to-fact links or automatic ambiguous cross filtering.
6. bridge_account_store_period is HISTORY/QA: do not create a regular many-to-many active relationship that ignores validity dates.
7. Generation metadata enables explicit official/marketplace As-Of measures. Never add Marketplace to Official Sales.
8. Refresh in Desktop and validate row counts, money totals, relationships, period filters, Strict LFL, source freshness, and navigation BEFORE approval.
9. External connector / credentials / privacy levels / native Desktop runtime not tested by this package; local folder path is a parameter, not a mandatory D: dependency.

Expected G0004 counts (for Desktop comparison): fact_sales_daily=36438; fact_budget_daily=37054; fact_marketplace_daily=21377; dim_date=730; dim_store=30.
Expected G0004 Official net cents=3759335807; Marketplace attribution net cents=514398580 (nonadditive); entire allocated budget to official As-Of=3663645215.
'''
    return files

def write_atomic_report(path,content):
    need(path.name=='OUTPUT.txt','Report must be exactly OUTPUT.txt')
    need(not path.is_symlink(),'Symlinked output rejected')
    if path.exists():need(path.is_file(),'Output must be regular file')
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='.RP360_P4_',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:
            f.write(content);f.flush();os.fsync(f.fileno())
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)

def install_package(root,source_text,files):
    target=root/'src/retailpulse360/phase4_validation'
    need(not target.is_symlink(),'Unsafe target symlink')
    parent=target.parent
    need(parent.is_dir() and not parent.is_symlink(),'Source package parent is absent or unsafe')
    stage=Path(tempfile.mkdtemp(prefix='.rp360_phase4_',dir=parent))
    try:
        (stage/'kpi_sql_parity.py').write_text(source_text,encoding='utf-8',newline='\n')
        (stage/'powerquery').mkdir()
        for fn,value in files.items(): (stage/'powerquery'/fn).write_text(value,encoding='utf-8',newline='\n')
        artifacts={str(p.relative_to(stage)):sha(p) for p in stage.rglob('*') if p.is_file()}
        if target.exists():
            need(target.is_dir(),'Existing target is not directory')
            old={str(p.relative_to(target)):sha(p) for p in target.rglob('*') if p.is_file() and not p.is_symlink()}
            need(len(old)==len(artifacts) and old==artifacts,'Installed package differs: refusing overwrite')
            return 'VERIFIED_EXISTING_IDENTICAL_SOURCE',len(artifacts)
        os.rename(stage,target)
        return 'INSTALLED_NEW_ATOMIC_DIRECTORY',len(artifacts)
    finally:
        if stage.exists():shutil.rmtree(stage)

def run(root):
    gen,db=valid_source(root)
    oracle=CSVOracle(gen)
    city=next(iter(sorted({r['city_key'] for r in oracle.stores.values()})))
    cases=[
      ('YTD_2026','2026-01-01','2026-12-31','YTD',CH,None),
      ('YTD_2025_NO_PY','2025-01-01','2025-12-31','YTD',CH,None),
      ('WTD_DEC_2026','2026-12-01','2026-12-20','WTD',CH,None),
      ('MTD_DEC_2026','2026-12-01','2026-12-31','MTD',CH,None),
      ('QTD_2026','2026-10-01','2026-12-31','QTD',CH,None),
      ('CUSTOM_PARTIAL','2026-04-09','2026-05-12','CUSTOM',CH,None),
      ('RETAIL_ONLY','2026-01-01','2026-12-31','YTD',{'RETAIL'},None),
      ('PROGRAM_ONLY','2026-01-01','2026-12-31','YTD',{'PROGRAM'},None),
      ('CLOSED_STORE','2026-01-01','2026-12-31','YTD',CH,('store','S019')),
      ('REGION_R02','2026-09-01','2026-10-09','CUSTOM',CH,('region','R02')),
      ('CITY_FILTER','2026-06-01','2026-06-30','MTD',CH,('city',city)),
      ('MARKETPLACE_AHEAD','2026-12-21','2026-12-27','CUSTOM',CH,None),
      ('2025_WTD','2025-01-01','2025-01-04','WTD',CH,None)
    ]
    con=sqlite3.connect(f'file:{db.as_posix()}?mode=ro',uri=True)
    try:
        con.execute('PRAGMA query_only=ON')
        findings=[run_case(con,oracle,c) for c in cases]
        horizon=days(D.date(2025,1,1),OFFICIAL)
        total_csv=sums(oracle.group(horizon,set(oracle.stores),CH))
        total_sql=sums(sql_group(con,horizon,set(oracle.stores),CH))
        need(total_csv==total_sql,'Full 2025-2026 horizon Python/SQL mismatch')
        need(total_csv[0]==3759335807,'Certified full-horizon Official total mismatch')
        need(total_csv[5]==3663645215,'Certified full-horizon aligned budget mismatch')
    finally:con.close()
    need(findings[-2]['marketplace_raw_cents']>0 and findings[-2]['official_cents']==0,'Marketplace ahead retention failed')
    need(findings[6]['official_cents']+findings[7]['official_cents']==findings[0]['official_cents'],'Channel split mismatch')
    need(findings[0]['cohort']==18,'YTD Strict eligible store count changed')
    edge=independent_edges()
    files=power_files()
    # Ensure authored M is not silently missing a CSV table or a Date/Store channel key.
    need(len([x for x in files if x.startswith('q_')])==len(POWER_COLUMNS)+1,'Power Query table count mismatch')
    for fn,value in files.items():
        need(value.strip() and ('let\n' in value or fn.endswith('.txt') or fn=='02_fnLoadCsv.m'),'Power Query content missing '+fn)
    source=Path(__file__).read_text(encoding='utf-8')
    status,count=install_package(root,source,files)
    return [
      'PROJECT | RetailPulse 360','CHECKPOINT | PHASE4_CONSOLIDATED_KPI_AND_POWERQUERY',
      'REVISION | '+REV,'GITHUB | NOT_USED',
      'PASS | INPUT_GATES | Phase 1 contracts, G0004 all artifact hashes, published SQLite signed baseline',
      f'PASS | KPI_001_037_CSV_SQL_PARITY | {len(KPI_IDS)} IDs compared for each of {len(cases)} scenarios',
      'PASS | STRICT_LFL | Identical TY/PY eligible store cohort and ratio of sums',
      'PASS | CLOCK | Saturday WTD, period caps and 2025 PY unavailable',
      'PASS | MARKETPLACE | Ahead data independent, matched account aggregation no double count',
      f'PASS | INDEPENDENT_EDGE_FIXTURES | {edge}/{edge}',
      f'PASS | POWERQUERY_SOURCE | {len(POWER_COLUMNS)} tables + generation metadata, parameterized project root/current generation, static only',
      f'PASS | LOCAL_SOURCE_PACKAGE | {status} | files={count} | src/retailpulse360/phase4_validation',
      'PASS | PUBLISHED_SQLITE_UNCHANGED | All baseline checks read only',
      'NOT_TESTED | Power Query Desktop refresh, DAX and Power BI visuals/runtime; no Phase 4 closure yet',
      'NOT_TESTED | Actual G0005 SQLite refresh and GitHub clean clone',
      'STATUS=PASS_PHASE4_CONSOLIDATED_SQL_PARITY_AND_PQ_SOURCE_READY'
    ]

def main():
    parser=argparse.ArgumentParser(description='RetailPulse360 Phase4 bundled KPI SQL parity + portable Power Query static source')
    parser.add_argument('--root',required=True)
    parser.add_argument('--report',required=True)
    parser.add_argument('--selftest',action='store_true',help='run independent arithmetic fixtures without project')
    a=parser.parse_args()
    if a.selftest:
        print('SELFTEST | '+str(independent_edges())+'/12 arithmetic/date fixtures');return
    root=Path(a.root).expanduser().resolve()
    path=Path(a.report).expanduser().absolute()
    try:
        need(root not in path.parents and path.name=='OUTPUT.txt','Report must be external OUTPUT.txt')
        lines=run(root)
        write_atomic_report(path,'\n'.join(lines)+'\n')
        print('\n'.join(lines))
    except Exception as e:
        lines=['PROJECT | RetailPulse 360','CHECKPOINT | PHASE4_CONSOLIDATED_KPI_AND_POWERQUERY',
               f'FAIL | {type(e).__name__} | {e}', 'STATUS=FAIL_PHASE4_CONSOLIDATED_BLOCKED']
        try:write_atomic_report(path,'\n'.join(lines)+'\n')
        except Exception as report_error:print('REPORT_WRITE_FAILED',report_error)
        print('\n'.join(lines));raise SystemExit(1)

if __name__=='__main__':main()

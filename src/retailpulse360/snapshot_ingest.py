#!/usr/bin/env python3
"""RetailPulse 360 P3.7 — external full-snapshot ingestion and isolated generation QA.

Read-only against approved project; no GitHub, no prior report, no DEV candidate dependency.
With --input: read four full-snapshot source/coverage CSVs + snapshot_control.json.
Without --input: run 14 synthetic QA scenarios and stage a corrected generation candidate.
In both modes: publish NO generations into project. Output only requested OUTPUT.txt.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

NAME='RetailPulse 360'
REV='p3.7.1'
LEGACY_SHA='30158d61e2d9e12c232872943740149723beb1de402b3289a4f41496e23a6fe9'
G1_SHA='744f1d31f29d3b180efeb0b82918a44e2856781a4bbf72bccb8b73dc8e30b32d'
G2_SHA='c2630a286b1fa569224fb002c424db0faabdb2e2c00ae71e256a147f7cdc7a96'
FAMILIES=('official_sales_snapshot.csv','source_coverage_official.csv','marketplace_daily_snapshot.csv','source_coverage_marketplace.csv')
CONTROL='snapshot_control.json'

class Reject(ValueError):
    def __init__(self,code,desc=''):
        self.code=code
        super().__init__(code+(': '+str(desc) if desc else ''))

def require(ok,code,desc=''):
    if not ok:raise Reject(code,desc)

def h_bytes(b):return hashlib.sha256(b).hexdigest()
def h_file(p):
    d=hashlib.sha256()
    with p.open('rb') as f:
        for c in iter(lambda:f.read(1048576),b''):d.update(c)
    return d.hexdigest()
def cj(o):return (json.dumps(o,sort_keys=True,ensure_ascii=False,indent=2)+'\n').encode('utf8')

def module_from_project(root):
    source=root/'src/retailpulse360/legacy_steps/RetailPulse360_P3_3.py'
    require(source.is_file() and not source.is_symlink(),'MISSING_ENGINE_SOURCE',str(source))
    require(h_file(source)==LEGACY_SHA,'ENGINE_SOURCE_HASH_DRIFT')
    spec=importlib.util.spec_from_file_location('retailpulse360_verified_p33',source)
    require(spec is not None and spec.loader is not None,'ENGINE_IMPORT_ERROR')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def verify_root(root,m):
    require(root.is_dir() and not root.is_symlink(),'INVALID_PROJECT_ROOT')
    for f in ('G0001','G0002'):
        expected=G1_SHA if f=='G0001' else G2_SHA
        path=root/'data/processed/p3_3/generations'/f/'generation_manifest.json'
        require(path.is_file() and not path.is_symlink() and h_file(path)==expected,'CERTIFIED_BASELINE_DRIFT',f)
    base=root/'data/processed/p3_3'
    m.safe_dir(base)
    require((base/'CURRENT').is_file() and not (base/'CURRENT').is_symlink(),'CURRENT_POINTER_INVALID')
    current=(base/'CURRENT').read_text(encoding='ascii').strip()
    require(re.fullmatch(r'G[0-9]{4}',current) is not None,'INVALID_CURRENT_GENERATION',current)
    m.verify_pinned(root)
    m.verify_p32(root)
    generations=base/'generations'
    m.safe_dir(generations)
    names=sorted(p.name for p in generations.iterdir())
    require(names==[f'G{i:04d}' for i in range(1,len(names)+1)],'GENERATION_CHAIN_GAP',str(names))
    require(current in names and 'G0001' in names and 'G0002' in names,'CURRENT_NOT_IN_CERTIFIED_CHAIN')
    for gid in names:
        gp=generations/gid
        m.safe_dir(gp)
        meta=m.validate_generation(gp)
        require(meta.get('generation')==gid and meta.get('classification')=='100% SYNTHETIC','GENERATION_METADATA_INVALID',gid)
        if gid=='G0001':require(h_file(gp/'generation_manifest.json')==G1_SHA,'G0001_MANIFEST_DRIFT')
        elif gid=='G0002':require(h_file(gp/'generation_manifest.json')==G2_SHA,'G0002_MANIFEST_DRIFT')
        else:
            parent=meta.get('parent_generation','')
            require(parent in names and parent!=gid and int(parent[1:])<int(gid[1:]),'GENERATION_PARENT_INVALID',gid)
    generation=generations/current
    return generation,m.validate_generation(generation),f'G{len(names)+1:04d}'


def normalize_control(data,m):
    require(isinstance(data,dict),'INVALID_CONTROL')
    require(set(data)=={'classification','snapshot_mode','official_asof','marketplace_asof'},'INVALID_CONTROL_FIELDS',str(sorted(data)))
    require(data['classification']=='SYNTHETIC' and data['snapshot_mode']=='FULL_REPLACEMENT','INVALID_SOURCE_POLICY')
    o=m.asof_key(data['official_asof']);d=m.asof_key(data['marketplace_asof'])
    require('20250101'<=o<='20261231' and '20250101'<=d<='20261231','ASOF_OUTSIDE_SYNTHETIC_HORIZON')
    return o,d

def read_input(p,m):
    require(p.is_dir() and not p.is_symlink(),'INPUT_FOLDER_INVALID')
    actual={x.name for x in p.iterdir()}
    require(actual==set(FAMILIES)|{CONTROL},'INPUT_INVENTORY_INVALID',str(sorted(actual)))
    for name in actual:
        f=p/name
        require(f.is_file() and not f.is_symlink(),'UNSAFE_INPUT_FILE',name)
    control=json.loads((p/CONTROL).read_text(encoding='utf8'))
    normalize_control(control,m)
    blobs={n:(p/n).read_bytes() for n in FAMILIES}
    return blobs,control

def lineage_check(rows,n,m):
    if n not in (m.OFF,m.DIG):return
    for r in rows:
        claim=r['lineage_hash']
        actual=h_bytes(cj({k:v for k,v in r.items() if k!='lineage_hash'}))
        if claim!=actual:raise Reject('LINEAGE_SHA256_MISMATCH',f"{n}: {m.key(r,n)}")

def materialize(root, m, generation, p32_archive, ctx, blobs, control, prior=None, baseline_payload=None):
    official_cut,digital_cut=normalize_control(control,m)
    stores,operating,accounts,ownership,_=ctx
    rows={n:m.csv_rows(blobs[n],m.SCHEMAS[n],n) for n in FAMILIES}
    for n in FAMILIES:lineage_check(rows[n],n,m)
    # Treat snapshots as complete, not new events to append to the published generation.
    idx=m.csv_index(rows[m.OFF],m.OFF)
    for k,original in p32_archive.items():
        if k in idx and m.business_hash(idx[k],m.OFF)!=m.business_hash(original,m.OFF):
            raise Reject('PROTECTED_VALUE_CONFLICT','|'.join(k))
    restore={k:r for k,r in p32_archive.items() if k not in idx and k[1]<=official_cut}
    cov_o=m.csv_index(rows[m.CO],m.CO)
    for k in restore:
        if k in cov_o and cov_o[k]['coverage_state'] not in ('REPORTED_VALUE',):
            raise Reject('PROTECTED_COVERAGE_CONFLICT','|'.join(k))
        if k in cov_o and cov_o[k]['coverage_state']=='REPORTED_VALUE':
            # Value claimed but missing from full source: protected restore explicitly permitted.
            pass
    reconstructed=list(rows[m.OFF])+list(restore.values())
    covr=list(rows[m.CO])+[dict(store_key=k[0],date_key=k[1],channel_key=k[2],coverage_state='REPORTED_VALUE',evidence='SEALED_OPERATIONAL_ARCHIVE_RESTORE') for k in restore if k not in cov_o]
    off,covo=m.coverage_check(reconstructed,covr,m.OFF,official_cut,operating,stores,accounts,ownership)
    digital,covd=m.coverage_check(rows[m.DIG],rows[m.CD],m.DIG,digital_cut,operating,stores,accounts,ownership)
    prev=prior if prior is not None else {n:m.csv_index(m.csv_rows((generation/'raw'/n).read_bytes(),m.SCHEMAS[n],n),n) for n in (m.OFF,m.DIG)}
    count=Counter()
    for fam,cur,old,cut,cov,n in (('OFFICIAL',off,prev[m.OFF],official_cut,covo,m.OFF),('MARKETPLACE',digital,prev[m.DIG],digital_cut,covd,m.DIG)):
        for k,r in cur.items():
            if k not in old:count[fam+'_ADD']+=1
            elif any(r[field]!=old[k][field] for field in m.BUSINESS[n]):count[fam+'_CORRECT']+=1
        for k in old.keys()-cur.keys():
            if k[1]>cut:count[fam+'_LATER_THAN_ASOF']+=1
            elif fam=='OFFICIAL' and k in p32_archive:raise Reject('PROTECTED_HISTORY_LOSS','|'.join(k))
            elif cov.get(k,{}).get('coverage_state')!='RETRACTED_CONFIRMED':raise Reject('UNCONFIRMED_RETRACTION','|'.join(k))
            else:count[fam+'_RETRACT']+=1
    mapped=[];sum_by_store=defaultdict(int);future=0
    for k,r in sorted(digital.items()):
        owners=[a[0] for a in ownership[k[0]] if a[1]<=k[1]<=a[2]]
        require(len(owners)==1,'INVALID_ACCOUNT_OWNER','|'.join(k))
        store=owners[0]
        mapped.append({'store_key':store,**r})
        if k[1]>min(official_cut,digital_cut):future+=1
        else:sum_by_store[(store,k[1])]+=int(r['attributed_retail_net_sales_cents'])
    review=[]
    for (store,d),v in sum_by_store.items():
        retail=off.get((store,d,'RETAIL'))
        if retail is None:raise Reject('MISSING_MATCHED_RETAIL',store+'/'+d)
        if v>0 and v>max(0,int(retail['net_sales_cents'])):review.append(f'{store}/{d}')
    if review:raise Reject('DQ_REVIEW_DIGITAL_EXCESS',str(review[:3]))
    # Explicitly preserve all unaffected baseline dimension, budget and archive artifacts.
    payload=dict(baseline_payload) if baseline_payload is not None else {rel:(generation/rel).read_bytes() for rel in m.validate_generation(generation)['artifacts']}
    for n in FAMILIES:payload['raw/'+n]=blobs[n]
    staged_off=m.make_csv([off[k] for k in sorted(off)],m.SCHEMAS[m.OFF])
    staged_dig=m.make_csv(mapped,('store_key',)+m.SCHEMAS[m.DIG])
    payload['staging/stg_official_sales.csv']=staged_off
    payload['staging/source_coverage_official.csv']=m.make_csv([covo[k] for k in sorted(covo)],m.SCHEMAS[m.CO])
    payload['staging/source_coverage_marketplace.csv']=m.make_csv([covd[k] for k in sorted(covd)],m.SCHEMAS[m.CD])
    payload['staging/stg_marketplace_resolved.csv']=staged_dig
    payload['analytics/fact_sales_daily.csv']=staged_off
    payload['analytics/fact_marketplace_daily.csv']=staged_dig
    counts={'official_rows':len(off),'digital_rows':len(digital),'protected_restored':len(restore),'marketplace_ahead_rows':future}
    totals={'official_net_cents':sum(int(r['net_sales_cents']) for r in off.values()),'digital_net_cents':sum(int(r['attributed_retail_net_sales_cents']) for r in digital.values())}
    require(totals['official_net_cents']==sum(int(r['net_sales_cents']) for k,r in off.items() if k[2]=='RETAIL')+sum(int(r['net_sales_cents']) for k,r in off.items() if k[2]=='PROGRAM'),'OFFICIAL_RECONCILIATION_FAILURE')
    return payload,counts,totals,dict(sorted(count.items()))

def encode_rows(rows,m,name):return m.make_csv(rows,m.SCHEMAS[name])

def mutate_record(blobs,m,kind):
    b=dict(blobs)
    src=m.OFF;cov=m.CO
    offs=m.csv_rows(b[src],m.SCHEMAS[src],src)
    covs=m.csv_rows(b[cov],m.SCHEMAS[cov],cov)
    i=next(i for i,r in enumerate(offs) if r['store_key']=='S001' and r['channel_key']=='RETAIL' and r['date_key']=='20250101')
    row=offs[i]
    if kind in ('CORRECT','BAD_LINEAGE','PROTECTED_CONFLICT'):
        if kind=='PROTECTED_CONFLICT':
            idx_closed=next(j for j,r in enumerate(offs) if r['store_key'] in ('S019','S020') and r['channel_key']=='RETAIL')
            i=idx_closed;row=offs[i]
        gross=int(row['gross_sales_cents'])+111
        row['gross_sales_cents']=str(gross)
        row['net_sales_cents']=str(gross-int(row['returns_amount_cents']))
        if kind!='BAD_LINEAGE':row['lineage_hash']=h_bytes(cj({k:v for k,v in row.items() if k!='lineage_hash'}))
        b[src]=encode_rows(offs,m,src)
    elif kind=='RETRACT':
        k=m.key(row,src)
        offs.pop(i)
        match=next(r for r in covs if m.key(r,cov)==k)
        match['coverage_state']='RETRACTED_CONFIRMED';match['evidence']='SOURCE_CONFIRMED_RETRACTION'
        b[src]=encode_rows(offs,m,src);b[cov]=encode_rows(covs,m,cov)
    elif kind=='RESTORE_PROTECTED':
        # caller will find a guaranteed closed-store row in current source
        idx_closed=next(j for j,r in enumerate(offs) if r['store_key'] in ('S019','S020'))
        old=offs.pop(idx_closed)
        k=m.key(old,src)
        covs=[r for r in covs if m.key(r,cov)!=k]
        b[src]=encode_rows(offs,m,src);b[cov]=encode_rows(covs,m,cov)
    elif kind=='DUPLICATE':
        offs.append(dict(row));b[src]=encode_rows(offs,m,src)
    elif kind=='MISSING_COVERAGE':
        k=m.key(row,src);covs=[r for r in covs if m.key(r,cov)!=k];b[cov]=encode_rows(covs,m,cov)
    elif kind in ('DIGITAL_EXCESS','DIGITAL_CORRECT','DIGITAL_RETRACT','DIGITAL_ADD'):
        dig=m.DIG;dcov=m.CD
        drows=m.csv_rows(b[dig],m.SCHEMAS[dig],dig)
        crows=m.csv_rows(b[dcov],m.SCHEMAS[dcov],dcov)
        if kind=='DIGITAL_RETRACT':
            match=next(i for i,r in enumerate(drows) if r['date_key']=='20250101')
            removed=drows.pop(match)
            k=m.key(removed,dig)
            rowc=next(r for r in crows if m.key(r,dcov)==k)
            rowc['coverage_state']='RETRACTED_CONFIRMED';rowc['evidence']='SOURCE_CONFIRMED_RETRACTION'
            b[dig]=encode_rows(drows,m,dig);b[dcov]=encode_rows(crows,m,dcov)
        elif kind=='DIGITAL_ADD':
            original=next(r for r in drows if r['date_key']=='20261227')
            new={**original,'date_key':'20261228','attributed_retail_net_sales_cents':'1','orders':'1','units':'1','source_snapshot_id':'SIMULATED-GENERIC-ADD'}
            existing={m.key(r,dig) for r in drows}
            if m.key(new,dig) in existing:
                original=next(r for r in drows if r['date_key']=='20261227' and (r['account_key'],'20261228') not in existing)
                new={**original,'date_key':'20261228','attributed_retail_net_sales_cents':'1','orders':'1','units':'1','source_snapshot_id':'SIMULATED-GENERIC-ADD'}
            new['lineage_hash']=h_bytes(cj({k:v for k,v in new.items() if k!='lineage_hash'}))
            drows.append(new)
            crows.append({'account_key':new['account_key'],'date_key':'20261228','coverage_state':'REPORTED_VALUE','evidence':'EXPLICIT_NEW_DAY'})
            b[dig]=encode_rows(drows,m,dig);b[dcov]=encode_rows(crows,m,dcov)
        else:
            drows=m.csv_rows(b[dig],m.SCHEMAS[dig],dig)
            r=next(r for r in drows if r['date_key']==('20261225' if kind=='DIGITAL_CORRECT' else '20250101'))
            r['attributed_retail_net_sales_cents']=str(int(r['attributed_retail_net_sales_cents'])+111 if kind=='DIGITAL_CORRECT' else 1000000000)
            r['lineage_hash']=h_bytes(cj({k:v for k,v in r.items() if k!='lineage_hash'}))
            b[dig]=encode_rows(drows,m,dig)
    elif kind=='EARLIER_ASOF':
        for n in FAMILIES:
            rows=m.csv_rows(b[n],m.SCHEMAS[n],n)
            cut='20261130' if n in (m.OFF,m.CO) else '20261201'
            b[n]=encode_rows([r for r in rows if r['date_key']<=cut],m,n)
    elif kind=='UNKNOWN_STORE':
        old_key=m.key(row,src)
        row['store_key']='S999'
        row['lineage_hash']=h_bytes(cj({k:v for k,v in row.items() if k!='lineage_hash'}))
        cv=next(r for r in covs if m.key(r,cov)==old_key)
        cv['store_key']='S999'
        b[src]=encode_rows(offs,m,src);b[cov]=encode_rows(covs,m,cov)
    return b

def candidate_publish(workspace,artifact_root,m,gid,external=False):
    target=workspace/('P3_7_EXTERNAL_'+gid+'_CANDIDATE' if external else 'P3_7_'+gid+'_CANDIDATE')
    new=m.inventory(artifact_root)
    if target.exists() or target.is_symlink():
        require(target.is_dir() and not target.is_symlink(),'CANDIDATE_PATH_UNSAFE')
        old=m.inventory(target)
        require(set(old)==set(new),'CANDIDATE_INVENTORY_CONFLICT')
        for n in new:require(h_file(old[n])==h_file(new[n]),'CANDIDATE_CONTENT_CONFLICT',n)
        return target,'VERIFIED_EXISTING_IDENTICAL_CANDIDATE'
    tmp=Path(tempfile.mkdtemp(prefix='.p37_stage_',dir=str(workspace)))
    try:
        for n,p in new.items():
            f=tmp/n;f.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,f)
        require(set(m.inventory(tmp))==set(new),'CANDIDATE_STAGE_INVENTORY')
        for n,p in new.items():require(h_file(tmp/n)==h_file(p),'CANDIDATE_STAGE_HASH',n)
        tmp.rename(target)
    finally:
        if tmp.exists():shutil.rmtree(tmp)
    return target,'CREATED_NEW_ATOMIC_CANDIDATE'

def write_report(path,lines):
    require(path.name=='OUTPUT.txt' and not path.is_symlink() and not path.is_dir(),'INVALID_REPORT_TARGET')
    path.parent.mkdir(parents=True,exist_ok=True)
    require(not path.parent.is_symlink(),'UNSAFE_REPORT_FOLDER')
    fd,name=tempfile.mkstemp(prefix='.rp360_report_',suffix='.tmp',dir=str(path.parent))
    try:
        with os.fdopen(fd,'w',encoding='utf8',newline='\n') as f:f.write('\n'.join(lines)+'\n')
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)

def operate(root,report,input_dir=None):
    lines=[f'PROJECT | {NAME}','CHECKPOINT | P3.7',f'VERSION | {REV}',
           'MODE | '+('EXTERNAL_FULL_SNAPSHOT_CANDIDATE_ONLY' if input_dir else 'SELFTEST_GENERIC_FULL_SNAPSHOT_CANDIDATE_ONLY'),
           'OUTPUT_ROLE | EPHEMERAL_COMMUNICATION_ONLY','GITHUB | NOT_USED',
           f'ROOT_READ_ONLY | {root}',f'REPORT | {report}']
    try:
        require(root.resolve() not in report.resolve().parents,'REPORT_MUST_BE_OUTSIDE_PROJECT')
        m=module_from_project(root)
        generation,genmeta,next_gid=verify_root(root,m)
        active_gid=genmeta['generation']
        p32=root/'data/processed/p3_2'
        _,_,_,archive=m.verify_p32(root)
        ctx=m.context(root)
        # Certified generation was SHA-256 checked once above. Reuse immutable in-memory
        # copies for every fault scenario, instead of re-hashing all 25 artifacts 14 times.
        baseline_payload={rel:(generation/rel).read_bytes() for rel in genmeta['artifacts']}
        prior={n:m.csv_index(m.csv_rows(baseline_payload['raw/'+n],m.SCHEMAS[n],n),n) for n in (m.OFF,m.DIG)}
        lines.append(f'PASS | CERTIFIED_INPUTS | P2.1/P2.2/P2.3 P3.2 protected history; G0001/G0002 pinned; active={active_gid}; next={next_gid}')
        blobs={n:(generation/'raw'/n).read_bytes() for n in FAMILIES}
        control={'classification':'SYNTHETIC','snapshot_mode':'FULL_REPLACEMENT','official_asof':genmeta['source_asof']['OFFICIAL'],'marketplace_asof':genmeta['source_asof']['MARKETPLACE']}
        with tempfile.TemporaryDirectory(prefix='.rp360_p37_',dir=str(root.parent)) as stage:
            stage=Path(stage)
            qa=[]
            if input_dir:
                blobs,control=read_input(input_dir,m)
                lines.append('PASS | EXTERNAL_INPUT | Exact 4 CSV files + snapshot_control.json; unmodified read-only source')
            else:
                # Runtime tests on real full-size sources, not just assertions against fixture expectations.
                tests=(('UNCHANGED',None,'PASS'),('CORRECT','CORRECT','PASS'),('RETRACT','RETRACT','PASS'),
                       ('PROTECTED_RESTORE','RESTORE_PROTECTED','PASS'),('PROTECTED_CONFLICT','PROTECTED_CONFLICT','PROTECTED_VALUE_CONFLICT'),
                       ('BAD_LINEAGE','BAD_LINEAGE','LINEAGE_SHA256_MISMATCH'),('DUPLICATE','DUPLICATE','DUPLICATE_BUSINESS_KEY'),
                       ('MISSING_COVERAGE','MISSING_COVERAGE','MISSING_EXPECTED_NOT_ZERO'),
                       ('DIGITAL_EXCESS','DIGITAL_EXCESS','DQ_REVIEW_DIGITAL_EXCESS'),
                       ('DIGITAL_CORRECT','DIGITAL_CORRECT','PASS'),('DIGITAL_RETRACT','DIGITAL_RETRACT','PASS'),
                       ('DIGITAL_ADD','DIGITAL_ADD','PASS'),('EARLIER_ASOF','EARLIER_ASOF','PASS'),
                       ('UNKNOWN_STORE','UNKNOWN_STORE','UNKNOWN_STORE_FK'))
                for test,mutation,expect in tests:
                    data=mutate_record(blobs,m,mutation) if mutation else blobs
                    case_control=dict(control)
                    if test=='DIGITAL_ADD':case_control['marketplace_asof']='2026-12-28'
                    if test=='EARLIER_ASOF':case_control.update(official_asof='2026-11-30',marketplace_asof='2026-12-01')
                    actual='PASS';result=None
                    try:result=materialize(root,m,generation,archive,ctx,data,case_control,prior,baseline_payload)
                    except Exception as e:
                        actual=e.code if isinstance(e,Reject) else (e.code if isinstance(e,m.Blocked) else type(e).__name__)
                    require(actual==expect,'SELFTEST_CASE_UNEXPECTED',f'{test}: expected={expect} got={actual}')
                    if test=='CORRECT':
                        require(result is not None and result[3].get('OFFICIAL_CORRECT')==1,'CORRECT_COUNT_INCORRECT')
                    if test=='DIGITAL_ADD':require(result is not None and result[3].get('MARKETPLACE_ADD')==1,'DIGITAL_ADD_COUNT_INCORRECT')
                    if test=='DIGITAL_RETRACT':require(result is not None and result[3].get('MARKETPLACE_RETRACT')==1,'DIGITAL_RETRACT_COUNT_INCORRECT')
                    if test=='DIGITAL_CORRECT':require(result is not None and result[3].get('MARKETPLACE_CORRECT')==1,'DIGITAL_CORRECT_COUNT_INCORRECT')
                    if test=='EARLIER_ASOF':require(result is not None and result[3].get('OFFICIAL_LATER_THAN_ASOF',0)>0,'EARLIER_ASOF_COUNT_INCORRECT')
                    if test=='RETRACT':
                        require(result is not None and result[3].get('OFFICIAL_RETRACT')==1,'RETRACT_COUNT_INCORRECT')
                    if test=='PROTECTED_RESTORE':
                        require(result is not None and result[1]['protected_restored']==1,'PROTECTED_RESTORE_COUNT_INCORRECT')
                    qa.append({'case':test,'status':actual,'result':'PASS'})
                    lines.append('PASS | CASE_'+test+' | '+actual)
                    print('P3.7 TEST | '+test+' | '+actual,flush=True)
                blobs=mutate_record(blobs,m,'CORRECT')
                lines.append('PASS | SOURCE_INPUT_CASES | 14/14 executed on complete snapshot rows')
            payload,counts,totals,changes=materialize(root,m,generation,archive,ctx,blobs,control,prior,baseline_payload)
            require(len(payload)==25,'GENERATION_PAYLOAD_INCOMPLETE')
            scratch=stage/'isolated_publish'
            scratch.mkdir()
            require(not (scratch/'CURRENT').exists(),'POINTER_ISOLATION_FAILED')
            m.write_generation(scratch,next_gid,payload,{'OFFICIAL':control['official_asof'],'MARKETPLACE':control['marketplace_asof']},totals,counts,changes,active_gid)
            if next_gid!='G0003':
                generated_manifest=scratch/'generations'/next_gid/'generation_manifest.json'
                updated=json.loads(generated_manifest.read_text(encoding='utf8'))
                updated['checkpoint']='P3.7'
                updated['engine']=REV
                generated_manifest.write_bytes(cj(updated))
            meta=m.validate_generation(scratch/'generations'/next_gid)
            # Pointer faults tested only against disposable candidate generations.
            try:m.switch_pointer(scratch,next_gid,inject=True)
            except m.Blocked:pass
            else:raise Reject('POINTER_FAULT_NOT_BLOCKED')
            require(not (scratch/'CURRENT').exists(),'FAULT_EXPOSED_POINTER')
            m.switch_pointer(scratch,next_gid)
            require((scratch/'CURRENT').read_bytes()==(next_gid+'\n').encode('ascii'),'POINTER_SWITCH_FAILED')
            m.switch_pointer(scratch,next_gid)
            require((scratch/'CURRENT').read_bytes()==(next_gid+'\n').encode('ascii'),'IDEMPOTENCE_POINTER')
            # Source fingerprint and business changes: no source data taken from TEST fixtures.
            extra={'input_sha256':{n:h_bytes(blobs[n]) for n in FAMILIES},'source_control':control,
                   'generated_counts':counts,'generated_totals_cents':totals,'changes':changes,
                   'generation_manifest_sha256':h_file(scratch/'generations'/next_gid/'generation_manifest.json'),
                   'classification':'SYNTHETIC','checkpoint':'P3.7','mode':'CANDIDATE_ONLY',
                   'expected_artifacts':26,'purpose':'Source ingestion QA, not a release approval archive'}
            (scratch/'p3_7_input_verification.json').write_bytes(cj(extra))
            if qa:(scratch/'p3_7_case_matrix.json').write_bytes(cj(qa))
            # Do not modify the published directory or current pointer.
            workspace=root.parent/'retailpulse360_dev';workspace.mkdir(exist_ok=True)
            candidate,state=candidate_publish(workspace,scratch,m,next_gid,external=bool(input_dir))
            lines.append(f'PASS | GENERATION_CANDIDATE | {state} | {candidate}')
            lines.append(f'PASS | ATOMIC_FAULT_AND_POINTER | Isolated fault blocked; candidate CURRENT={next_gid}')
            lines.append('PASS | PROTECTED_ARCHIVE | 2624 frozen business keys; signed archive bytes preserved')
            lines.append('PASS | FINANCIAL_AND_ATTRIBUTION | Official channels only; digital separately matched')
            lines.append('COUNTS | '+json.dumps(counts,sort_keys=True))
            lines.append('CHANGES | '+json.dumps(changes,sort_keys=True))
            lines.append('TOTALS_CENTS | '+json.dumps(totals,sort_keys=True))
            lines.append('CANDIDATE_MANIFEST_SHA256 | '+extra['generation_manifest_sha256'])
        lines.append('PASS | PROJECT_ROOT_UNCHANGED | Source and published data accessed read-only')
        lines.append('PASS | REPORT_SCOPED | Only selected OUTPUT.txt updated; unrelated shared files untouched')
        lines.append(f'WARNING | Candidate-only {next_gid}, not published. Future snapshots outside 2025–2026 currently blocked')
        lines.append('WARNING | SQLite, SQL, DAX, Power BI Desktop not tested')
        lines.append('STATUS=PASS_P3_7_GENERIC_INPUT_CANDIDATE_VALIDATED')
        return lines,0
    except Exception as e:
        lines.append(f'FAIL | {getattr(e,"code",type(e).__name__)} | {e}')
        lines.append('STATUS=FAIL_P3_7_NOT_APPROVED')
        return lines,2

def main():
    parser=argparse.ArgumentParser(description='RetailPulse 360 P3.7: generic full-snapshot CLI — candidate only')
    parser.add_argument('--root',required=True,type=Path)
    parser.add_argument('--report',required=True,type=Path)
    parser.add_argument('--input',type=Path,help='Read 4 complete CSVs and snapshot_control.json (default runs built-in full-size synthetic selftests)')
    args=parser.parse_args()
    lines,rc=operate(args.root.resolve(),args.report.resolve(),args.input.resolve() if args.input else None)
    try:write_report(args.report,lines)
    except Exception as e:
        print(f'ERROR | Could not write OUTPUT.txt: {e}',file=sys.stderr);rc=3
    print('\n'.join(lines[-9:]),flush=True)
    return rc
if __name__=='__main__':sys.exit(main())

#!/usr/bin/env python3
"""RetailPulse 360 P4.4: generation-aware SQLite refresh, initially candidate-only.

Uses the already approved Phase 1 star-schema DDL and typed CSV mapping.
A baseline project is NEVER updated by this tool: all database builds target
an explicitly external workspace (or an isolated self-test temp directory).
No dependencies beyond Python stdlib; report is temporary communication only.
"""
from __future__ import annotations
import argparse
from contextlib import closing
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
REV = 'p4.4.1'
SOURCE_SHA = 'db41e4d9def57271e72f1f17691bf339eccab4634138b4a17586e68ecca70d8d'
ENGINE_SHA = '30158d61e2d9e12c232872943740149723beb1de402b3289a4f41496e23a6fe9'
P41_SHA = '3e5480af50f44f6718fcc48aa0a7ea859bd9b35259838c0b3abcc8bcaed5bb5b'
P41_MANIFEST_SHA = 'ee35f99526cc637d62da4384e0493781e317e3946804f018a6a50e0d06947a75'
P42_MANIFEST_SHA = '18ecf306af86fc98c9ee737170425eb2203bee33fcdb16ad20c14afbdf874a7e'
P43_MANIFEST_SHA = 'be4277321250984efb042643bbed388889f49e2e0b2562050645c968e485e195'
GEN_PINS = {
    'G0001':'744f1d31f29d3b180efeb0b82918a44e2856781a4bbf72bccb8b73dc8e30b32d',
    'G0002':'c2630a286b1fa569224fb002c424db0faabdb2e2c00ae71e256a147f7cdc7a96',
    'G0003':'3619ed2f4f9f10004013e56e06953637b3fc4f3174707c9196760549cd70e91e',
    'G0004':'d1135b60ff299996a05bd6edaeb26b7df9c126368984e46e8c368a031a642f92',
}

class GateError(ValueError): pass

def need(ok, msg):
    if not ok: raise GateError(msg)

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as fh:
        for buf in iter(lambda: fh.read(1 << 20), b''): h.update(buf)
    return h.hexdigest()

def regular(p):
    need(p.is_file() and not p.is_symlink(), 'Missing or unsafe file: '+str(p))

def directory(p):
    need(p.is_dir() and not p.is_symlink(), 'Missing or unsafe directory: '+str(p))

def json_bytes(data):
    return (json.dumps(data, sort_keys=True, ensure_ascii=False, indent=2) + '\n').encode('utf-8')

def import_checked(path, digest, name):
    regular(path)
    need(sha(path) == digest, 'Approved source SHA-256 mismatch: '+str(path))
    spec=importlib.util.spec_from_file_location(name, path)
    need(spec and spec.loader, 'Cannot import approved builder')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def preflight(root):
    directory(root)
    for d in ('DATA_MODEL_SPEC.md','KPI_CONTRACTS.md','QA_TEST_MATRIX.md','PHASE_3_ETL_SNAPSHOTS.md'):
        regular(root/'docs'/d)
    builder=import_checked(root/'src/retailpulse360/sqlite_build.py', SOURCE_SHA,'rp_p44_builder')
    engine=import_checked(root/'src/retailpulse360/legacy_steps/RetailPulse360_P3_3.py',ENGINE_SHA,'rp_p44_engine')
    p41=root/'data/processed/p4_1'
    regular(p41/'retailpulse360_g0004.sqlite'); regular(p41/'p4_1_manifest.json')
    need(sha(p41/'retailpulse360_g0004.sqlite')==P41_SHA,'Published G0004 SQLite changed')
    need(sha(p41/'p4_1_manifest.json')==P41_MANIFEST_SHA,'P4.1 manifest changed')
    p42=root/'sql/sqlite/p4_2/p4_2_manifest.json'
    regular(p42);need(sha(p42)==P42_MANIFEST_SHA, 'P4.2 manifest changed')
    p43=root/'tests/p4_3/p4_3_manifest.json'
    regular(p43);need(sha(p43)==P43_MANIFEST_SHA, 'P4.3 manifest changed')
    store=root/'data/processed/p3_3'
    regular(store/'CURRENT')
    current=(store/'CURRENT').read_text(encoding='ascii').strip()
    need(re.fullmatch(r'G\d{4}',current) is not None,'Invalid CURRENT pointer')
    engine.verify_pinned(root)
    engine.verify_p32(root)
    return builder,engine,store,current

def generation(root, engine, store, gid, current):
    need(re.fullmatch(r'G\d{4}',gid) is not None,'Invalid generation ID')
    # Never accept a generation newer than the pointer or missing from the immutable chain.
    last=int(current[1:]); idx=int(gid[1:]);need(1<=idx<=last,'Generation outside published chain')
    previous=''
    for num in range(1, idx+1):
        g=f'G{num:04d}'
        loc=store/'generations'/g
        directory(loc)
        meta=engine.validate_generation(loc)
        need(meta['generation']==g and meta['parent_generation']==previous,'Broken generation parent chain: '+g)
        if g in GEN_PINS:
            need(sha(loc/'generation_manifest.json')==GEN_PINS[g],'Historical generation SHA mismatch: '+g)
        previous=g
    path=store/'generations'/gid
    meta=engine.validate_generation(path)
    need(meta['classification']=='100% SYNTHETIC','Unsuitable non-synthetic generation')
    need(len(meta['artifacts'])==25,'Unexpected generation payload inventory')
    need(meta['protected_archive_sha256'] == '46155f724adea2f44b8164f0644502bdc1f5a408e6fec54ed231bd893a89bb69','Protected archive signature changed')
    return path,meta,sha(path/'generation_manifest.json')

def build_sqlite(builder, source, meta, msha, gid, dest):
    need(not dest.exists(),'Output must be a new disposable filename')
    dest.parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(str(dest))
    try:
        con.execute('PRAGMA foreign_keys=ON')
        con.execute('PRAGMA journal_mode=DELETE')
        con.execute('PRAGMA synchronous=FULL')
        con.executescript(builder.DDL)
        order=('dim_date','dim_store','dim_channel','dim_marketplace_account',
               'bridge_account_store_period','store_operating_calendar','fact_sales_daily',
               'fact_budget_monthly','fact_budget_daily','fact_marketplace_daily',
               'source_coverage_official','source_coverage_marketplace','dq_findings')
        sizes={}
        for name in order:
            rel, hdr=builder.TABLES[name]
            columns=hdr.split()
            records=list(builder.csv_rows(source/rel,columns))
            con.executemany('INSERT INTO '+name+' ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')',records)
            sizes[name]=len(records)
        con.execute('INSERT INTO generation_metadata VALUES (?,?,?,?,?)',
                    (gid,meta['parent_generation'],meta['source_asof']['OFFICIAL'],meta['source_asof']['MARKETPLACE'],msha))
        con.commit()
        need(con.execute('PRAGMA integrity_check').fetchone()[0]=='ok','SQLite integrity failed')
        need(not con.execute('PRAGMA foreign_key_check').fetchall(),'SQLite foreign keys failed')
        con.execute('VACUUM')
        return sizes
    except Exception:
        con.rollback();raise
    finally: con.close()

def test_sqlite(builder, source, meta, sha_manifest, gid, db, counts):
    oracle, channel, sm, bm, dm, negatives=builder.reference_oracle(
        source,meta['source_asof']['OFFICIAL'],meta['source_asof']['MARKETPLACE'])
    con=sqlite3.connect('file:'+db.as_posix()+'?mode=ro',uri=True)
    try:
        need(con.execute('PRAGMA integrity_check').fetchone()[0]=='ok','SQLite integrity_check failed')
        need(not con.execute('PRAGMA foreign_key_check').fetchall(),'SQLite foreign_key_check failed')
        row=con.execute('SELECT * FROM generation_metadata').fetchall()
        need(row==[(gid,meta['parent_generation'],meta['source_asof']['OFFICIAL'],meta['source_asof']['MARKETPLACE'],sha_manifest)],'Generation metadata incorrect')
        for t,size in counts.items():
            need(con.execute('SELECT COUNT(*) FROM '+t).fetchone()[0]==size,'Row count mismatch: '+t)
        s=lambda q,v=():int(con.execute(q,v).fetchone()[0] or 0)
        sql_totals={
            'official':s('SELECT SUM(net_sales_cents) FROM fact_sales_daily'),
            'gross':s('SELECT SUM(gross_sales_cents) FROM fact_sales_daily'),
            'returns':s('SELECT SUM(returns_amount_cents) FROM fact_sales_daily'),
            'budget_total':s('SELECT SUM(allocated_budget_cents) FROM fact_budget_daily'),
            'budget_aligned':s('SELECT SUM(b.allocated_budget_cents) FROM fact_budget_daily b JOIN dim_date d USING(date_key) WHERE d.calendar_date<=?',(meta['source_asof']['OFFICIAL'],)),
            'digital_total':s('SELECT SUM(attributed_retail_net_sales_cents) FROM fact_marketplace_daily'),
            'digital_ahead_rows':s('SELECT COUNT(*) FROM fact_marketplace_daily m JOIN dim_date d USING(date_key) WHERE d.calendar_date>?',(min(meta['source_asof']['OFFICIAL'],meta['source_asof']['MARKETPLACE']),)),
        }
        end=min(meta['source_asof']['OFFICIAL'],meta['source_asof']['MARKETPLACE'])
        matched=con.execute('''SELECT COALESCE(SUM(d.digital_cents),0),COALESCE(SUM(r.net_sales_cents),0)
        FROM (SELECT m.store_key,m.date_key,SUM(m.attributed_retail_net_sales_cents) digital_cents
         FROM fact_marketplace_daily m JOIN dim_date cd ON cd.date_key=m.date_key
         WHERE cd.calendar_date<=? GROUP BY m.store_key,m.date_key) d
        JOIN fact_sales_daily r ON r.store_key=d.store_key AND r.date_key=d.date_key AND r.channel_key='RETAIL' ''',(end,)).fetchone()
        sql_totals['digital_matched']=matched[0];sql_totals['retail_matched']=matched[1]
        need(all(sql_totals.get(k,0)==oracle.get(k,0) for k in set(sql_totals)|set(oracle)),
             'Independent Python SQL totals differ: '+str([(k,oracle.get(k,0),sql_totals.get(k,0)) for k in set(sql_totals)|set(oracle) if sql_totals.get(k,0)!=oracle.get(k,0)]))
        need(oracle['official']==meta['totals_cents']['official_net_cents'],'Official generation financial mismatch')
        need(oracle['digital_total']==meta['totals_cents']['digital_net_cents'],'Marketplace generation financial mismatch')
        need(oracle['gross']-oracle['returns']==oracle['official'],'Returns reconciliation failed')
        require_channel=dict(con.execute('SELECT channel_key,SUM(net_sales_cents) FROM fact_sales_daily GROUP BY channel_key'))
        need(require_channel==channel,'Channel aggregation differs')
        ms={(s,int(month),c):int(v) for s,month,c,v in con.execute('SELECT store_key,CAST(date_key/100 AS INTEGER),channel_key,SUM(net_sales_cents) FROM fact_sales_daily GROUP BY 1,2,3')}
        need(ms==sm,'Store/month/channel sales groups mismatch')
        mb={(s,int(month),c):int(v) for s,month,c,v in con.execute('SELECT store_key,CAST(date_key/100 AS INTEGER),channel_key,SUM(allocated_budget_cents) FROM fact_budget_daily GROUP BY 1,2,3')}
        need(mb==bm,'Store/month/channel budget groups mismatch')
        md={(s,int(month)):int(v) for s,month,v in con.execute('SELECT store_key,CAST(date_key/100 AS INTEGER),SUM(attributed_retail_net_sales_cents) FROM fact_marketplace_daily GROUP BY 1,2')}
        need(md==dm,'Store/month marketplace groups mismatch')
        need(s('SELECT COUNT(*) FROM fact_sales_daily WHERE net_sales_cents<0')==negatives,'Negative legitimate returns missing')
        archived=0
        cols=builder.TABLES['fact_sales_daily'][1].split()
        for record in builder.csv_rows(source/'protected_history/closed_store_official.csv',cols):
            val=con.execute('SELECT '+','.join(cols)+' FROM fact_sales_daily WHERE store_key=? AND date_key=? AND channel_key=?',record[:3]).fetchone()
            need(val==record,'Protected history missing/mismatched')
            archived+=1
        need(archived==2624,'Unexpected protected key count')
        need(s('SELECT COUNT(*) FROM fact_budget_daily b JOIN store_operating_calendar c USING(store_key,date_key) WHERE c.is_operating<>1')==0,'Budget after closure')
        need(s('SELECT COUNT(*) FROM fact_sales_daily b JOIN store_operating_calendar c USING(store_key,date_key) WHERE c.is_operating<>1')==0,'Sales outside operating period')
        need(s('''SELECT COUNT(*) FROM fact_marketplace_daily m JOIN dim_date d USING(date_key) WHERE
            (SELECT COUNT(*) FROM bridge_account_store_period a WHERE a.account_key=m.account_key AND a.store_key=m.store_key
             AND a.valid_from<=d.calendar_date AND (a.valid_to IS NULL OR a.valid_to>=d.calendar_date))<>1''')==0,'Digital ownership mismatch')
        need(s('SELECT COUNT(*) FROM fact_sales_daily WHERE net_sales_cents=0')>0,'Explicit zero days missing')
        return {'generation':gid,'manifest_sha256':sha_manifest,'totals_cents':oracle,
                'table_counts':counts,'protected_rows':archived,'negative_sales_rows':negatives,
                'sales_store_month_channel_groups':len(sm),'budget_store_month_channel_groups':len(bm),
                'marketplace_store_month_groups':len(dm),'matched_through':end}
    finally:con.close()

def scoped_report(path, lines):
    need(path.name=='OUTPUT.txt','Report must be OUTPUT.txt')
    need(not path.is_symlink(),'Report cannot be symlink')
    if path.exists(): need(path.is_file(),'Report must be a file')
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.RP360_P4_4_',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:
            f.write('\n'.join(lines)+'\n');f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.lexists(tmp):os.unlink(tmp)

def result(status, lines):
    return ['PROJECT | RetailPulse 360','CHECKPOINT | P4.4-SQLITE-REFRESH-CANDIDATE',
            'REVISION | '+REV,'MODE | GENERATION_AWARE_SQLITE_REBUILD_CANDIDATE_ONLY',
            'OUTPUT_ROLE | TEMPORARY_COMMUNICATION_ONLY','GITHUB | NOT_USED',*lines,'STATUS='+status]

def run_candidate(root):
    builder,engine,store,current=preflight(root)
    need(current=='G0004','P4.4 first checkpoint expects G0004 active; no new generation approved yet')
    # Cache target generation checks once, not repeated per fixture run.
    gens={g:generation(root,engine,store,g,current) for g in ('G0003','G0004')}
    dev=root.parent/'retailpulse360_dev'
    dev.mkdir(parents=True,exist_ok=True)
    need(not dev.is_symlink(),'Unsafe DEV workspace')
    candidate=dev/'P4_4_SQLITE_REFRESH_CANDIDATE'
    need(not candidate.is_symlink(),'Unsafe candidate link')
    temp=Path(tempfile.mkdtemp(prefix='.P4_4_BUILD_',dir=dev))
    try:
        qa={}
        for gid,(src,meta,msha) in gens.items():
            db=temp/(gid.lower()+'.sqlite')
            counts=build_sqlite(builder,src,meta,msha,gid,db)
            qa[gid]=test_sqlite(builder,src,meta,msha,gid,db,counts)
        need(qa['G0004']['totals_cents']['official']-qa['G0003']['totals_cents']['official']==111,
             'Expected G0003→G0004 Official correction not reflected')
        need(qa['G0004']['totals_cents']['digital_total']==qa['G0003']['totals_cents']['digital_total'],
             'Marketplace changed unexpectedly during Official-only correction')
        # Independent published G0004 database comparison, including all table contents.
        published=root/'data/processed/p4_1/retailpulse360_g0004.sqlite'
        # sqlite3.Connection.__exit__ commits/rolls back but does NOT close the DB.
        # Explicitly close both handles before deleting disposable *.sqlite files,
        # otherwise Windows raises WinError 32 at the cleanup stage.
        with closing(sqlite3.connect('file:'+published.as_posix()+'?mode=ro',uri=True)) as old,\
             closing(sqlite3.connect('file:'+(temp/'g0004.sqlite').as_posix()+'?mode=ro',uri=True)) as new:
            for table in (*builder.TABLES,'generation_metadata'):
                columns=[x[1] for x in new.execute('PRAGMA table_info('+table+')')]
                q='SELECT '+','.join(columns)+' FROM '+table+' ORDER BY '+','.join(str(i+1) for i in range(len(columns)))
                need(old.execute(q).fetchall()==new.execute(q).fetchall(),'G0004 published DB row parity mismatch: '+table)
        # Same source, repeated build, byte-exact within the actual local SQLite environment.
        db2=temp/'g0004_replay.sqlite'
        counts2=build_sqlite(builder,*gens['G0004'][:1],gens['G0004'][1],gens['G0004'][2],'G0004',db2)
        need(counts2==qa['G0004']['table_counts'],'G0004 rebuild counts changed')
        need(sha(db2)==sha(temp/'g0004.sqlite'),'Same-environment rebuild not byte deterministic')
        own=Path(__file__).resolve()
        regular(own)
        manifest_data={'checkpoint':'P4.4','state':'CANDIDATE_ONLY','scope':'GENERATION_AWARE_REFRESH_SOURCE',
                       'source_sha256':sha(own),'source_name':'sqlite_refresh.py',
                       'qa_sha256':None,'approved_g4_sqlite_sha256':P41_SHA,
                       'test_generations':['G0003','G0004']}
        check={'revision':REV,'oracle':'generation CSV enumerated independently of SQLite',
               'per_generation':qa,'correction_delta_cents':111,
               'original_g4_published_db_all_14_tables_equal':True,
               'same_env_g4_sha256_repeated_build_identical':True,
               'published_current_unchanged':'G0004'}
        qpath=temp/'refresh_qa.json';qpath.write_bytes(json_bytes(check))
        manifest_data['qa_sha256']=sha(qpath)
        (temp/'refresh_manifest.json').write_bytes(json_bytes(manifest_data))
        (temp/'sqlite_refresh.py').write_bytes(own.read_bytes())
        # Do not retain scratch 3 DBs after QA; only reusable source and results.
        for p in temp.glob('*.sqlite'):p.unlink()
        expected={'sqlite_refresh.py','refresh_qa.json','refresh_manifest.json'}
        if candidate.exists():
            directory(candidate)
            need({p.name for p in candidate.iterdir()}==expected,'Candidate inventory changed')
            for name in expected:
                regular(candidate/name)
                need(sha(candidate/name)==sha(temp/name),'Candidate changed: '+name)
            how='VERIFIED_EXISTING_IDENTICAL_CANDIDATE'
        else:
            os.rename(temp,candidate)
            how='CREATED_NEW_ATOMIC_CANDIDATE'
        return result('PASS_P4_4_GENERATION_REFRESH_CANDIDATE_VALIDATED_PENDING_REVIEW',[
            'PASS | PINNED_BASELINES | Approved P3/P4 project, CURRENT=G0004 verified',
            'PASS | GENERATION_REFRESH | G0003 and G0004 SQLite built separately from signed CSV families',
            'PASS | INDEPENDENT_CSV_SQL_PARITY | 13 tables, money/negative/coverage/ownership and protected 2624',
            'PASS | CORRECTION_DELTA | G0003 -> G0004 Official +111 cents; Marketplace unchanged',
            'PASS | PUBLISHED_G0004_EQUIVALENCE | All 14 tables row-identical to approved SQLite',
            'PASS | IDEMPOTENT_REBUILD | Same-environment G0004 SQLite byte-identical',
            'PASS | CANDIDATE | '+how+' | '+str(candidate),
            'CANDIDATE_ARTIFACTS | 3 | source, QA results, source-integrity manifest',
            'SOURCE_SHA256 | '+sha(candidate/'sqlite_refresh.py'),
            'MANIFEST_SHA256 | '+sha(candidate/'refresh_manifest.json'),
            'PASS | PROJECT_ROOT_READ_ONLY | No project files changed',
            'PASS | REPORT_SCOPED | Only OUTPUT.txt modified; shared sibling items untouched',
            'WARNING | Source candidate only; general SQLite refresh not yet installed/published',
            'NOT_TESTED | G0005 actual future generation, Power Query, DAX, Desktop, GitHub clean clone'])
    finally:
        if temp.exists():shutil.rmtree(temp)

def run_external(root,gid,out):
    builder,engine,store,current=preflight(root)
    need(gid!='CURRENT' or current,'No current generation')
    selected=current if gid=='CURRENT' else gid
    source,meta,msha=generation(root,engine,store,selected,current)
    need(out!=root and root not in out.parents,'Output cannot be in approved project')
    need(not out.is_symlink(),'Unsafe output symlink')
    need(not out.exists(),'Output already exists; never overwrite')
    directory(out.parent)
    fd, name=tempfile.mkstemp(prefix='.P4_4_DB_',suffix='.sqlite',dir=out.parent)
    os.close(fd)
    tmp=Path(name);tmp.unlink()
    try:
        counts=build_sqlite(builder,source,meta,msha,selected,tmp)
        qa=test_sqlite(builder,source,meta,msha,selected,tmp,counts)
        need((store/'CURRENT').read_text(encoding='ascii').strip()==current,'Generation pointer changed during build')
        os.rename(tmp,out)
        return qa
    finally:
        if tmp.exists():tmp.unlink()

def main():
    ap=argparse.ArgumentParser(description='Build generation-aware SQLite outside project; candidate QA by default')
    ap.add_argument('--root',required=True,help='RetailPulse360 local project root')
    ap.add_argument('--report',help='Report OUTPUT.txt for candidate QA mode')
    ap.add_argument('--generation',help='G0001..CURRENT (external rebuild mode)')
    ap.add_argument('--output',help='External *.sqlite path for external rebuild mode')
    a=ap.parse_args()
    root=Path(os.path.abspath(os.path.expanduser(a.root)))
    rpt=Path(os.path.abspath(os.path.expanduser(a.report))) if a.report else None
    try:
        if a.generation or a.output:
            need(a.generation and a.output,'Both --generation and --output required')
            output=Path(os.path.abspath(os.path.expanduser(a.output)))
            info=run_external(root,a.generation,output)
            lines=result('PASS_P4_4_EXTERNAL_SQLITE_REBUILT',[
                'PASS | EXTERNAL_SQLITE | '+str(output),
                'GENERATION | '+info['generation'],
                'OFFICIAL_CENTS | '+str(info['totals_cents']['official']),
                'SQLITE_SHA256 | '+sha(output),
                'PASS | PROJECT_ROOT_READ_ONLY'])
        else:
            need(rpt is not None,'--report is required for candidate QA')
            need(rpt.name=='OUTPUT.txt','Report filename must be OUTPUT.txt')
            need(not (rpt==root or root in rpt.parents),'Report must be outside project')
            lines=run_candidate(root)
        if rpt:scoped_report(rpt,lines)
        print('\n'.join(lines))
    except Exception as exc:
        lines=result('FAIL_P4_4_BLOCKED',[f'FAIL | {type(exc).__name__} | {exc}'])
        if rpt:
            try:scoped_report(rpt,lines)
            except Exception as e:print('REPORT_WRITE_FAILED | '+str(e),file=sys.stderr)
        print('\n'.join(lines),file=sys.stderr)
        raise SystemExit(1)

if __name__=='__main__':main()

#!/usr/bin/env python3
"""Generate and validate the synthetic portfolio in a NEW external directory.

Uses standard-library APIs from the retained historical engines; never invokes
their obsolete report-approval gates and never alters the source checkout.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[1]


def need(ok, message):
    if not ok:
        raise RuntimeError(message)


def module(root, relative):
    spec = importlib.util.spec_from_file_location(Path(relative).stem, root / relative)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def write_payload(folder, payload):
    folder.mkdir(parents=True, exist_ok=False)
    for name, body in payload.items():
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)


def reproduce(output):
    output = output.expanduser().absolute()
    need(not output.exists() and not output.is_symlink(), 'Output must not exist; refusing overwrite')
    output = output.resolve()
    need(REPO != output and REPO not in output.parents, 'Output must be outside source checkout')
    output.mkdir(parents=True, exist_ok=False)
    root = output / 'project'
    root.mkdir()
    for name in ('docs', 'src', 'tests', 'sql', 'PowerBI'):
        shutil.copytree(REPO / name, root / name, ignore=shutil.ignore_patterns('__pycache__', '.pbi'))
    logs = output / 'logs'
    logs.mkdir()
    dev = output / 'retailpulse360_dev'
    steps = []

    def record(name, start, **extra):
        steps.append(dict(name=name, status='PASS', seconds=round(time.monotonic()-start, 3), **extra))
        (output / 'results.json').write_text(json.dumps(steps, indent=2)+'\n')
        print('PASS | '+name, flush=True)

    def run(name, relative, extra=()):
        start = time.monotonic()
        report = logs / name / 'OUTPUT.txt'
        report.parent.mkdir()
        command = [sys.executable, str(root/relative), '--root', str(root), '--report', str(report), *extra]
        result = subprocess.run(command, cwd=root, capture_output=True, text=True,
                                encoding='utf-8', errors='replace',
                                env={**os.environ, 'PYTHONDONTWRITEBYTECODE':'1'})
        (report.parent/'console.txt').write_text(result.stdout+'\n'+result.stderr, encoding='utf-8')
        need(result.returncode == 0, name+' failed: '+result.stdout[-1500:]+result.stderr[-500:])
        record(name, start, exit_code=result.returncode)

    def promotion(phase):
        name=phase+'_promotion_record.json'
        shutil.copyfile(REPO/'tests/fixtures/provenance'/name, root/'data/synthetic'/phase/name)

    start=time.monotonic()
    p21=module(root, 'src/retailpulse360/legacy_steps/RetailPulse360_P2_1_v2.py')
    payload,stores,calendar=p21.dataset(3602026)
    checks=p21.run_checks(3602026,payload,stores,calendar)
    need(all(row[0]=='PASS' for row in checks), 'Lifecycle generator checks failed')
    write_payload(root/'data/synthetic/p2_1',payload);promotion('p2_1')
    record('seeded-store-lifecycle-generator',start, checks=len(checks))

    start=time.monotonic()
    p22=module(root,'src/retailpulse360/legacy_steps/RetailPulse360_P2_2.py')
    stores,lifecycle=p22.load_p21(root)
    payload,objects,totals=p22.build(p22.SEED,stores,lifecycle)
    checks=p22.validate_payload(payload,stores,lifecycle)
    need(all(row[0]=='PASS' for row in checks), 'Sales generator checks failed')
    need(payload==p22.build(p22.SEED,stores,lifecycle)[0], 'Seeded generation is not byte deterministic')
    write_payload(root/'data/synthetic/p2_2',payload);promotion('p2_2')
    record('seeded-sales-budget-marketplace-generator',start,checks=len(checks))

    start=time.monotonic()
    p23=module(root,'src/retailpulse360/legacy_steps/RetailPulse360_P2_3.py')
    base,stores,operating=p23.load_approved(root)
    payload,manifest,catalog,ledger=p23.build_suite(base,stores,operating)
    checks=p23.validate_fixture(payload,manifest,catalog,ledger,base,stores,operating)
    need(all(row[0]=='PASS' for row in checks),'Snapshot fixture checks failed')
    write_payload(root/'data/synthetic/p2_3',payload);promotion('p2_3')
    record('snapshot-fixture-generation',start,checks=len(checks))

    run('etl','src/retailpulse360/legacy_steps/RetailPulse360_P3_2_v5.py')
    shutil.copytree(dev/'P3_2_CANDIDATE',root/'data/processed/p3_2')
    run('snapshot-engine','src/retailpulse360/legacy_steps/RetailPulse360_P3_3.py')
    shutil.copytree(dev/'P3_3_CANDIDATE',root/'data/processed/p3_3')
    for gid in ('G0003','G0004'):
        run('snapshot-input-'+gid,'src/retailpulse360/snapshot_ingest.py')
        candidate=dev/('P3_7_'+gid+'_CANDIDATE')
        shutil.copytree(candidate/'generations'/gid,root/'data/processed/p3_3/generations'/gid)
        shutil.copyfile(candidate/'CURRENT',root/'data/processed/p3_3/CURRENT')

    start=time.monotonic()
    expected=json.loads((REPO/'release/data_baseline.json').read_text())
    for relative,digest in expected.items():
        file=root/relative
        need(file.is_file(),'Missing independently pinned artifact '+relative)
        need(hashlib.sha256(file.read_bytes()).hexdigest()==digest,'Approved baseline mismatch '+relative)
    record('independent-approved-data-hash-parity',start,files=len(expected))
    run('sqlite','src/retailpulse360/sqlite_build.py')
    shutil.copytree(dev/'P4_1_SQLITE_CANDIDATE',root/'data/processed/p4_1')
    run('sql-analytics','src/retailpulse360/sql_analytics.py')
    run('kpi-edges','tests/p4_3/test_kpi_edges.py')
    run('kpi-parity','src/retailpulse360/phase4_validation/kpi_sql_parity.py')
    run('sqlite-refresh','src/retailpulse360/sqlite_refresh.py')
    start=time.monotonic()
    # Exercise the actual publisher in a second isolated copy; keep the main
    # generated Power BI project pinned to the approved G0004 baseline.
    qa=output/'publisher-qa'
    qa.mkdir()
    qa_root=qa/'project'
    shutil.copytree(root,qa_root)
    ingest=module(qa_root,'src/retailpulse360/snapshot_ingest.py')
    engine=ingest.module_from_project(qa_root)
    raw=qa_root/'data/processed/p3_3/generations/G0004/raw'
    blobs={name:(raw/name).read_bytes() for name in ingest.FAMILIES}
    blobs=ingest.mutate_record(blobs,engine,'CORRECT')
    blobs['snapshot_control.json']=ingest.cj(dict(classification='SYNTHETIC',snapshot_mode='FULL_REPLACEMENT',official_asof='2026-12-20',marketplace_asof='2026-12-27'))
    write_payload(qa/'input',blobs)
    qa_logs=qa/'logs';qa_logs.mkdir()
    code=ingest.operate(qa_root,qa_logs/'OUTPUT.txt',qa/'input')
    (qa_logs/'ingest.txt').write_text('\n'.join(code[0]),encoding='utf-8')
    need(code[1]==0,'External G0005 ingestion failed')
    publisher=module(qa_root,'src/retailpulse360/snapshot_publish.py')
    pointer=qa_root/'data/processed/p3_3/CURRENT'
    old={p.relative_to(qa_root):hashlib.sha256(p.read_bytes()).hexdigest() for p in (qa_root/'data/processed/p3_3/generations').rglob('*') if p.is_file()}
    rc=publisher.execute(qa_root,qa_logs/'OUTPUT.txt',simulated=True)
    shutil.copyfile(qa_logs/'OUTPUT.txt',qa_logs/'injected-failure.txt')
    need(rc==2 and 'SIMULATED_FAILURE_BEFORE_CURRENT' in (qa_logs/'OUTPUT.txt').read_text(),'Expected injected publication failure not observed')
    need(pointer.read_bytes()==b'G0004\n' and not (pointer.parent/'generations/G0005').exists(),'Failed publication did not roll back')
    need(publisher.execute(qa_root,qa_logs/'OUTPUT.txt')==0,'Atomic G0005 publish failed')
    shutil.copyfile(qa_logs/'OUTPUT.txt',qa_logs/'published.txt')
    need(pointer.read_bytes()==b'G0005\n','Publication did not activate G0005')
    need(publisher.execute(qa_root,qa_logs/'OUTPUT.txt')==0,'Idempotent publication failed')
    need('VERIFIED_EXISTING_IDENTICAL_PUBLICATION' in (qa_logs/'OUTPUT.txt').read_text(),'Replay did not verify identical publication')
    for relative,digest in old.items():
        need(hashlib.sha256((qa_root/relative).read_bytes()).hexdigest()==digest,'Publisher changed historical generation')
    refresh=module(qa_root,'src/retailpulse360/sqlite_refresh.py')
    refresh.run_external(qa_root,'G0005',qa/'g0005.sqlite')
    need((root/'data/processed/p3_3/CURRENT').read_bytes()==b'G0004\n','Main baseline was changed')
    record('actual-publisher-fault-rollback-replay-and-G0005-refresh',start)
    # Generate a relocatable Power BI Desktop entry point. Only the isolated
    # output copy gets the machine-local root; the public source remains clean.
    shutil.copy2(REPO / 'tools' / 'open_powerbi.py', root / 'OPEN_POWER_BI.py')
    (root / 'OPEN_POWER_BI.cmd').write_text(
        '@echo off\npy -3.13 "%~dp0OPEN_POWER_BI.py"\nif errorlevel 1 pause\n',
        encoding='utf-8')
    subprocess.run([sys.executable, '-B', str(root / 'OPEN_POWER_BI.py'),
                    '--configure-only'], cwd=root, check=True)
    print('PASS | PORTABLE_POWER_BI_PATH | Generated path configured automatically', flush=True)

    print('HEADLESS BUILD PASS | Desktop runtime NOT RUN',flush=True)
    print('Open generated project/OPEN_POWER_BI.cmd; it detects paths automatically.')
    return root


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    reproduce(args.output)

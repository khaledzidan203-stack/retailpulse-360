#!/usr/bin/env python3
"""RetailPulse 360 — P3.9 safe, reusable local snapshot generation publisher.

Publish a complete, independently rebuilt P3.7 external full-snapshot candidate.
The generation is immutable; the sole live selector CURRENT changes by atomic
os.replace only AFTER all payload, archive and source-lineage checks pass.
A copy of this source is installed locally for future generations. No GitHub.

Expected candidate: sibling retailpulse360_dev/P3_7_EXTERNAL_GNNNN_CANDIDATE.
For later snapshots use the installed publisher together with snapshot_ingest.py.
OUTPUT.txt is ephemeral communication. No approval or execution-history logs.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True

NAME = 'RetailPulse 360'
CHECKPOINT = 'P3.9'
ENGINE_SHA = '30158d61e2d9e12c232872943740149723beb1de402b3289a4f41496e23a6fe9'
INGEST_SHA = '85908364fcdef6f28e0f19fb96eaff994fe85f1e5370eefec59caf3345e2cd16'
G1_SHA = '744f1d31f29d3b180efeb0b82918a44e2856781a4bbf72bccb8b73dc8e30b32d'
G2_SHA = 'c2630a286b1fa569224fb002c424db0faabdb2e2c00ae71e256a147f7cdc7a96'
G3_SHA = '3619ed2f4f9f10004013e56e06953637b3fc4f3174707c9196760549cd70e91e'
GID_RE = re.compile(r'G[0-9]{4}\Z')

class GateError(RuntimeError):
    pass


def need(condition, message):
    if not condition:
        raise GateError(message)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for part in iter(lambda: f.read(1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()


def ensure_regular(path, label='file'):
    need(path.is_file() and not path.is_symlink(), f'Unsafe/missing {label}: {path}')


def ensure_dir(path, label='folder'):
    need(path.is_dir() and not path.is_symlink(), f'Unsafe/missing {label}: {path}')


def module(path, label):
    ensure_regular(path, label)
    spec = importlib.util.spec_from_file_location(label, path)
    need(spec is not None and spec.loader is not None, f'Cannot import {label}')
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def safe_inventory(folder, engine):
    return engine.inventory(folder)  # verifies nested symlinks, regular files and safe paths


def reporter(path, lines):
    need(path.name == 'OUTPUT.txt' and not path.is_symlink() and not path.is_dir(), 'Unsafe OUTPUT.txt target')
    path.parent.mkdir(parents=True, exist_ok=True)
    need(not path.parent.is_symlink(), 'Unsafe OUTPUT.txt folder')
    fd, tmp = tempfile.mkstemp(prefix='.rp360_p39_report_', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
            f.write('\n'.join(lines) + '\n')
        os.replace(tmp, path)
    finally:
        if os.path.lexists(tmp):
            os.unlink(tmp)


def verify_project(root):
    ensure_dir(root, 'project root')
    src = root / 'src/retailpulse360'
    engine_path = src / 'legacy_steps/RetailPulse360_P3_3.py'
    ingest_path = src / 'snapshot_ingest.py'
    ensure_regular(engine_path, 'P3.3 engine')
    ensure_regular(ingest_path, 'P3.7 ingester')
    need(digest(engine_path) == ENGINE_SHA, 'Certified P3.3 engine modified')
    need(digest(ingest_path) == INGEST_SHA, 'Certified P3.7 ingester modified')
    m = module(engine_path, 'rp360_p39_engine')
    imp = module(ingest_path, 'rp360_p39_ingest')
    # Full baseline, P3.2 archive & the whole currently published chain are verified.
    active_path, active_meta, next_gid = imp.verify_root(root, m)
    base = root / 'data/processed/p3_3'
    generations = base / 'generations'
    current_file = base / 'CURRENT'
    ensure_regular(current_file, 'active pointer')
    current_bytes = current_file.read_bytes()
    current = active_meta['generation']
    need(current_bytes == (current + '\n').encode('ascii'), 'Unexpected CURRENT encoding')
    for gid, expected in (('G0001', G1_SHA), ('G0002', G2_SHA), ('G0003', G3_SHA)):
        f = generations / gid / 'generation_manifest.json'
        ensure_regular(f, gid + ' manifest')
        need(digest(f) == expected, f'{gid} baseline changed')
    need(current in [p.name for p in generations.iterdir()], 'CURRENT is not published')
    return m, imp, active_path, active_meta, base, current_bytes, current, next_gid


def candidate_path(root, current, next_gid, supplied):
    dev = root.parent / 'retailpulse360_dev'
    ensure_dir(dev, 'development workspace')
    if supplied is not None:
        candidate = Path(os.path.abspath(supplied))
        need(candidate.parent == dev, 'Candidate must be an immediate child of sibling DEV workspace')
    else:
        future = dev / f'P3_7_EXTERNAL_{next_gid}_CANDIDATE'
        replay = dev / f'P3_7_EXTERNAL_{current}_CANDIDATE'
        candidate = future if future.exists() else replay
    ensure_dir(candidate, 'snapshot candidate')
    match = re.fullmatch(r'P3_7_EXTERNAL_(G\d{4})_CANDIDATE', candidate.name)
    need(match is not None, 'Unsupported candidate naming scheme')
    gid = match.group(1)
    need(gid in {current, next_gid}, 'Candidate must be next generation or current replay')
    return candidate, gid


def verify_candidate(root, candidate, gid, current, next_gid, m, imp, base):
    inv = safe_inventory(candidate, m)
    gen = candidate / 'generations' / gid
    ensure_dir(gen, 'candidate generation')
    meta = m.validate_generation(gen)
    need(meta['generation'] == gid and meta['parent_generation'] == f'G{int(gid[1:])-1:04d}',
         'Candidate lineage/parent does not match adjacent generation')
    need(meta['classification'] == '100% SYNTHETIC' and meta['checkpoint'] == 'P3.7',
         'Candidate is not from synthetic P3.7 engine')
    need(meta['engine'] == 'p3.7.1', 'Unexpected candidate engine revision')
    need(len(meta['artifacts']) == 25 and len(inv) == 28, 'Candidate inventory/size mismatch')
    expected = {'CURRENT', 'p3_7_input_verification.json'} | {
        f'generations/{gid}/{rel}' for rel in set(meta['artifacts']) | {'generation_manifest.json'}
    }
    need(set(inv) == expected, 'Candidate has extra or missing files')
    need((candidate / 'CURRENT').read_bytes() == (gid + '\n').encode('ascii'),
         'Candidate CURRENT pointer conflicts with generation')
    proof_path = candidate / 'p3_7_input_verification.json'
    ensure_regular(proof_path, 'candidate input verification')
    proof = json.loads(proof_path.read_text(encoding='utf8'))
    need(proof.get('checkpoint') == 'P3.7' and proof.get('classification') == 'SYNTHETIC'
         and proof.get('mode') == 'CANDIDATE_ONLY' and proof.get('expected_artifacts') == 26,
         'Candidate source verification status invalid')
    need(proof.get('generation_manifest_sha256') == digest(gen/'generation_manifest.json'),
         'Candidate manifest fingerprint changed')
    for key, attr in [('changes', 'changes'), ('generated_counts', 'counts'),
                      ('generated_totals_cents', 'totals_cents')]:
        need(proof.get(key) == meta[attr], f'Candidate {key} disagrees with generation manifest')
    control = proof.get('source_control')
    need(isinstance(control, dict) and control.get('classification') == 'SYNTHETIC'
         and control.get('snapshot_mode') == 'FULL_REPLACEMENT',
         'Candidate is not a full synthetic snapshot')
    imp.normalize_control(control, m)
    need(meta['source_asof'] == {'OFFICIAL': control['official_asof'],
                                'MARKETPLACE': control['marketplace_asof']},
         'Candidate As-Of differs from input source control')
    hashes = proof.get('input_sha256')
    need(isinstance(hashes, dict) and set(hashes) == set(imp.FAMILIES),
         'Incomplete input family fingerprints')
    blobs = {}
    for family in imp.FAMILIES:
        f = gen / 'raw' / family
        ensure_regular(f, family)
        need(digest(f) == hashes[family], f'Raw full snapshot differs from verified input: {family}')
        blobs[family] = f.read_bytes()
    # Independently rebuild the entire candidate business payload against its published parent.
    parent_gid = meta['parent_generation']
    parent_path = base / 'generations' / parent_gid
    ensure_dir(parent_path, 'published parent generation')
    parent_meta = m.validate_generation(parent_path)
    need(parent_meta['generation'] == parent_gid, 'Parent generation manifest identity incorrect')
    parent_payload = {rel: (parent_path / rel).read_bytes() for rel in parent_meta['artifacts']}
    prev = {n: m.csv_index(m.csv_rows(parent_payload['raw/' + n], m.SCHEMAS[n], n), n)
            for n in (m.OFF, m.DIG)}
    _, _, _, protected_archive = m.verify_p32(root)
    need(len(protected_archive) == 2624, 'Protected history key count differs')
    context = m.context(root)
    payload, counts, totals, changes = imp.materialize(
        root, m, parent_path, protected_archive, context, blobs, control, prev, parent_payload)
    need(set(payload) == set(meta['artifacts']), 'Independently rebuilt payload inventory differs')
    need(counts == meta['counts'] and totals == meta['totals_cents'] and changes == meta['changes'],
         'Independent financial/coverage/change reconciliation mismatch')
    for rel, value in payload.items():
        need(hashlib.sha256(value).hexdigest() == meta['artifacts'][rel]['sha256'],
             f'Independent calculation differs: {rel}')
    if gid == next_gid:
        need(any(blobs[n] != parent_payload['raw/'+n] for n in imp.FAMILIES)
             or meta['source_asof'] != parent_meta['source_asof'],
             'No-change snapshot must not create a redundant published generation')
    else:
        need(gid == current, 'Replay is not active generation')
    # Avoid hardcoded hash for later generations, but pin current G0004 QA baseline when known.
    if gid == 'G0004':
        need(digest(gen/'generation_manifest.json') ==
             'd1135b60ff299996a05bd6edaeb26b7df9c126368984e46e8c368a031a642f92',
             'G0004 differs from the locally tested P3.8 payload')
    return meta, gen


def identical_directory(left, right, m):
    a = safe_inventory(left, m)
    b = safe_inventory(right, m)
    return set(a) == set(b) and all(digest(a[k]) == digest(b[k]) for k in a)


def safe_write_pointer(base, to_gid, expected_bytes, m):
    pointer = base / 'CURRENT'
    ensure_regular(pointer, 'live pointer')
    need(pointer.read_bytes() == expected_bytes, 'Concurrent CURRENT modification; refusing to publish')
    target = base / 'generations' / to_gid
    m.validate_generation(target)
    fd, tmp = tempfile.mkstemp(prefix='.rp360_CURRENT_', suffix='.tmp', dir=base)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write((to_gid + '\n').encode('ascii'))
            f.flush()
            os.fsync(f.fileno())
        need(pointer.read_bytes() == expected_bytes, 'CURRENT changed while staging')
        os.replace(tmp, pointer)
    finally:
        if os.path.lexists(tmp):
            os.unlink(tmp)
    need(pointer.read_bytes() == (to_gid + '\n').encode('ascii'), 'CURRENT switch verification failed')


def publish(root, candidate, gid, m, base, old_bytes, old_gid, gen, simulated):
    source = root / 'src/retailpulse360/snapshot_publish.py'
    source_bytes = Path(__file__).read_bytes()
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    dest = base / 'generations' / gid
    if source.exists() or source.is_symlink():
        ensure_regular(source, 'existing local publisher')
        need(digest(source) == source_hash, 'Existing publisher source differs; refusing overwrite')
    if dest.exists() or dest.is_symlink():
        ensure_dir(dest, 'existing generation')
        need(identical_directory(dest, gen, m), 'Published generation differs from checked candidate')
    if gid == old_gid:
        need(dest.exists() and source.exists(), 'Replay lacks generation or source')
        return 'VERIFIED_EXISTING_IDENTICAL_PUBLICATION', source_hash
    need(gid == f'G{int(old_gid[1:])+1:04d}', 'Only adjacent generation publication permitted')
    # Use exclusive, transient lock to reject competing publishers; no persistent logs.
    lock = base / '.snapshot_publish.lock'
    fd = None
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w', encoding='ascii') as f:
            f.write('P3.9 exclusive generation publication in progress\n')
        fd = None
    except FileExistsError as e:
        raise GateError('Another publisher is active, or a stale lock needs inspection') from e
    new_source = False
    new_generation = False
    pointer_switched = False
    stage_source = None
    stage_generation = None
    try:
        need((base/'CURRENT').read_bytes() == old_bytes, 'CURRENT changed after validation')
        if not source.exists():
            fd, name = tempfile.mkstemp(prefix='.rp360_source_', suffix='.tmp', dir=source.parent)
            stage_source = Path(name)
            with os.fdopen(fd, 'wb') as f:
                f.write(source_bytes)
                f.flush()
                os.fsync(f.fileno())
            need(digest(stage_source) == source_hash, 'Publisher stage source differs')
        if not dest.exists():
            stage_generation = Path(tempfile.mkdtemp(prefix='.rp360_gen_', dir=dest.parent))
            inventory = safe_inventory(gen, m)
            for rel, item in inventory.items():
                copy = stage_generation / rel
                copy.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(item, copy)
            need(identical_directory(stage_generation, gen, m), 'Staged payload differs from candidate')
            m.validate_generation(stage_generation)
        if stage_source is not None:
            need(not source.exists() and not source.is_symlink(), 'Concurrent source appeared')
            stage_source.rename(source)
            stage_source = None
            new_source = True
        if stage_generation is not None:
            need(not dest.exists() and not dest.is_symlink(), 'Concurrent generation appeared')
            stage_generation.rename(dest)
            stage_generation = None
            new_generation = True
        need(source.is_file() and digest(source) == source_hash, 'Publisher source verification failed')
        need(identical_directory(dest, gen, m), 'Generation content changed during staging')
        need((base/'CURRENT').read_bytes() == old_bytes, 'CURRENT changed before switch')
        if simulated:
            raise GateError('SIMULATED_FAILURE_BEFORE_CURRENT')
        safe_write_pointer(base, gid, old_bytes, m)
        pointer_switched = True
        need((base/'CURRENT').read_bytes() == (gid+'\n').encode('ascii'), 'Pointer content mismatch')
        return 'PUBLISHED_VERIFIED_GENERATION_AND_SWITCHED_CURRENT', source_hash
    except BaseException:
        if pointer_switched:
            try:
                safe_write_pointer(base, old_gid, (gid+'\n').encode('ascii'), m)
            except Exception as exc:
                raise RuntimeError('CRITICAL: pointer rollback failed; inspect CURRENT before further runs') from exc
        # Remove only the files introduced by this attempted publication.
        if (base/'CURRENT').read_bytes() == old_bytes:
            if new_generation and dest.is_dir():
                shutil.rmtree(dest)
            if new_source and source.is_file():
                source.unlink()
        raise
    finally:
        if stage_source is not None and stage_source.exists():
            stage_source.unlink()
        if stage_generation is not None and stage_generation.exists():
            shutil.rmtree(stage_generation)
        if lock.exists():
            lock.unlink()


def execute(root, report, supplied=None, simulated=False):
    lines = [f'PROJECT | {NAME}', f'CHECKPOINT | {CHECKPOINT}',
             'MODE | VERIFY_REBUILD_AND_ATOMICALLY_ACTIVATE_EXTERNAL_GENERATION',
             'OUTPUT_ROLE | EPHEMERAL_COMMUNICATION_ONLY', 'GITHUB | NOT_USED',
             'ROOT | ' + str(root), 'REPORT | ' + str(report)]
    try:
        need(report.name == 'OUTPUT.txt' and not report.is_symlink(), 'Only OUTPUT.txt is permitted')
        need(root not in report.parents and report != root, 'Report must be outside project')
        m, imp, active_path, active_meta, base, old_bytes, old_gid, next_gid = verify_project(root)
        lines.append('PASS | CERTIFIED_PROJECT | P2.1–P3.2 and G0001/G0002/G0003; protected archive and current chain')
        candidate, gid = candidate_path(root, old_gid, next_gid, supplied)
        meta, gen = verify_candidate(root, candidate, gid, old_gid, next_gid, m, imp, base)
        lines.append('PASS | EXTERNAL_CANDIDATE | ' + str(candidate))
        lines.append('PASS | SOURCE_AND_BUSINESS_PARITY | All 25 payload files re-materialized from 4 full source files')
        lines.append('PASS | PROTECTED_ARCHIVE | 2624 protected keys unchanged; official/digital independent reconciliation')
        lines.append('GENERATION | ' + gid + ' | parent=' + meta['parent_generation'])
        lines.append('GENERATION_MANIFEST_SHA256 | ' + digest(gen/'generation_manifest.json'))
        lines.append('CHANGES | ' + json.dumps(meta['changes'], sort_keys=True))
        lines.append('COUNTS | ' + json.dumps(meta['counts'], sort_keys=True))
        lines.append('TOTALS_CENTS | ' + json.dumps(meta['totals_cents'], sort_keys=True))
        state, source_sha = publish(root, candidate, gid, m, base, old_bytes, old_gid, gen, simulated)
        lines.append('PASS | SAFE_PUBLICATION | ' + state)
        lines.append('PASS | CURRENT | ' + gid + '; older generations preserved')
        lines.append('PASS | LOCAL_REUSABLE_SOURCE | src/retailpulse360/snapshot_publish.py SHA256=' + source_sha)
        lines.append('PASS | REPORT_SCOPED | OUTPUT.txt only; unrelated shared siblings left untouched')
        lines.append('WARNING | SQLite, DAX, Power BI Desktop and GitHub clone NOT TESTED')
        lines.append('STATUS=PASS_P3_9_LOCALLY_PUBLISHED')
        rc = 0
    except Exception as exc:
        lines.append(f'FAIL | {getattr(exc,"code",type(exc).__name__)} | {exc}')
        lines.append('STATUS=FAIL_P3_9_PUBLICATION_BLOCKED')
        rc = 2
    try:
        reporter(report, lines)
    except Exception as exc:
        print('REPORT_WRITE_FAILURE | '+str(exc), file=sys.stderr)
        print('\n'.join(lines[-5:]), file=sys.stderr)
        return 3
    print('\n'.join(lines[-9:]), flush=True)
    return rc


def main():
    parser = argparse.ArgumentParser(description='RetailPulse 360 P3.9 reusable, safe full-snapshot generation publisher')
    parser.add_argument('--root', type=Path, required=True, help='Local RetailPulse 360 project root')
    parser.add_argument('--report', type=Path, required=True, help='Ephemeral OUTPUT.txt report location')
    parser.add_argument('--candidate', type=Path, help='Explicit sibling DEV external P3.7 generation candidate (optional)')
    parser.add_argument('--simulate-failure-before-pointer', action='store_true',
                        help='QA fault-injection; never activate or retain newly staged files')
    args = parser.parse_args()
    root = Path(os.path.abspath(args.root))
    report = Path(os.path.abspath(args.report))
    return execute(root, report, args.candidate, args.simulate_failure_before_pointer)


if __name__ == '__main__':
    sys.exit(main())

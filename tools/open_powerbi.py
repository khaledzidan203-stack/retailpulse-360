#!/usr/bin/env python3
"""Open the generated RetailPulse 360 Power BI project from ANY Windows folder.

Derive project path from this script location. Never rely on current directory.
Regenerate only the Power Query pProjectRoot parameter in this generated copy.
Use --configure-only for automated builds and CI (no Desktop launch).
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import re
import sys
import tempfile
import time


def m_literal(value: str) -> str:
    # M: a # begins an escape sequence. Escape it even in otherwise valid paths.
    return value.replace('#', '#(#)').replace('"', '""')


def configure(root: Path) -> tuple[Path, bool]:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise RuntimeError('Generated project folder is missing')
    current = root / 'data' / 'processed' / 'p3_3' / 'CURRENT'
    if not current.is_file():
        raise RuntimeError('No generated data detected: run tools/reproduce.py first')
    gen = current.read_text(encoding='utf-8-sig').strip()
    if not re.fullmatch(r'G[0-9]{4}', gen):
        raise RuntimeError('Invalid CURRENT generation; refusing to bind the report')
    gd = root / 'data' / 'processed' / 'p3_3' / 'generations' / gen / 'analytics'
    for name in ('fact_sales_daily.csv', 'fact_budget_daily.csv', 'fact_marketplace_daily.csv'):
        if not (gd / name).is_file():
            raise RuntimeError('Missing generated analytics input: ' + name)
    model = root / 'PowerBI' / 'RetailPulse 360.SemanticModel' / 'definition' / 'expressions.tmdl'
    pbip = root / 'PowerBI' / 'RetailPulse 360.pbip'
    if not pbip.is_file() or not model.is_file():
        raise RuntimeError('Generated Power BI project is incomplete')
    with model.open('r', encoding='utf-8-sig', newline='') as f:
        old = f.read()
    lines = old.splitlines(keepends=True)
    indexes = [i for i, line in enumerate(lines) if line.startswith('expression pProjectRoot = ')]
    if len(indexes) != 1:
        raise RuntimeError('pProjectRoot expression missing/ambiguous; refusing update')
    index = indexes[0]
    original = lines[index]
    raw = original.rstrip('\r\n')
    ending = original[len(raw):]
    expected = r'expression pProjectRoot = "(?:[^"]|"")*" meta \[IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true\]'
    if not re.fullmatch(expected, raw):
        raise RuntimeError('Unexpected pProjectRoot schema: report change requires review')
    # Windows File.Contents requires an absolute local path; source repository
    # intentionally retains a placeholder. Only generated copies get a path.
    new = ('expression pProjectRoot = "' + m_literal(str(root))
           + '" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]')
    if raw == new:
        return pbip, False
    newtext = ''.join(lines[:index] + [new + ending] + lines[index+1:])
    # Keep a backup outside the PBIP directory; no caches or unsupported files
    # may be introduced into the model/report definition folders.
    backup = root.parent / 'logs' / 'portable_powerbi' / 'backups'
    backup.mkdir(parents=True, exist_ok=True)
    (backup / ('expressions_' + str(time.time_ns()) + '.tmdl')).write_bytes(model.read_bytes())
    fd, tmp = tempfile.mkstemp(prefix='.rp360_autopath_', suffix='.tmp', dir=model.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as f:
            f.write(newtext)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, model)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return pbip, True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--configure-only', action='store_true', help='Bind but do not open Desktop')
    opts = parser.parse_args()
    try:
        project = Path(__file__).resolve().parent
        pbip, changed = configure(project)
        print('STATUS=PASS_AUTO_PROJECT_PATH')
        print('PROJECT_ROOT=' + str(project))
        print('PARAMETER=pProjectRoot')
        print('PATH_BINDING=' + ('UPDATED' if changed else 'UNCHANGED'))
        print('PBIP=' + str(pbip))
        if not opts.configure_only:
            if sys.platform != 'win32':
                print('Power BI Desktop launch is Windows-only; file is configured.')
            else:
                os.startfile(str(pbip))
                print('DESKTOP_LAUNCH=REQUESTED_NOT_RUNTIME_VERIFIED')
        return 0
    except Exception as exc:
        print('STATUS=BLOCKED_AUTO_PROJECT_PATH')
        print('ERROR=' + str(exc))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

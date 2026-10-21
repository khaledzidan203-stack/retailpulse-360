#!/usr/bin/env python3
"""Zero-configuration first run: generate synthetic data and open Power BI Desktop.

Run from a clean GitHub clone using START_RETAILPULSE_360.cmd, regardless of
where the repository is stored or the terminal's current working directory.
"""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
import argparse
import subprocess
import sys
import uuid

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build-only', action='store_true', help='Do not request Desktop launch')
    args = p.parse_args()
    output_parent = Path.home() / 'RetailPulse360Runs'
    try:
        output_parent.mkdir(parents=True, exist_ok=True)
        output = output_parent / ('run_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:6])
        print('SOURCE_REPO=' + str(REPO), flush=True)
        print('NEW_BUILD=' + str(output), flush=True)
        cmd = [sys.executable, '-B', str(REPO / 'tools' / 'reproduce.py'), '--output', str(output)]
        build = subprocess.run(cmd, cwd=REPO)
        if build.returncode:
            print('STATUS=FAIL_PORTABLE_BOOTSTRAP', flush=True)
            return build.returncode
        launcher = output / 'project' / 'OPEN_POWER_BI.py'
        if not launcher.is_file():
            raise RuntimeError('Generated Power BI launcher is missing')
        launch_cmd = [sys.executable, '-B', str(launcher)]
        if args.build_only:
            launch_cmd.append('--configure-only')
        result = subprocess.run(launch_cmd, cwd=output / 'project')
        print('BUILD_ROOT=' + str(output), flush=True)
        print('STATUS=' + ('PASS_PORTABLE_FIRST_RUN' if result.returncode == 0 else 'FAIL_PORTABLE_FIRST_RUN'), flush=True)
        return result.returncode
    except Exception as exc:
        print('ERROR=' + str(exc), flush=True)
        print('STATUS=FAIL_PORTABLE_FIRST_RUN', flush=True)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

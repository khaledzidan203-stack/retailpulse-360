#!/usr/bin/env python3
"""Read-only source provenance, syntax and CLI smoke tests. No ETL execution.

Execute from repository root:
    python -m unittest discover -s tests -p 'test_*.py' -v
"""
from __future__ import annotations

import ast
import hashlib
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    "src/retailpulse360/legacy_steps/RetailPulse360_P2_1_v2.py": "da40e413ee6735138d36b4f67275114fce6c2f2659dc5b62b6bd8732a85874dd",
    "src/retailpulse360/legacy_steps/RetailPulse360_P2_2.py": "7d1d5f82653bfcca62b1a84cb3a23cfbd3fe5a407ce01acb5c985d1781d7c1fe",
    "src/retailpulse360/legacy_steps/RetailPulse360_P2_3.py": "805f1091b8a717deacccd052b65a607db7ea59508ced4f6b8f2f22f830895e7e",
    "src/retailpulse360/legacy_steps/RetailPulse360_P3_1.py": "b97c3a8accc134646b737ec5ef6a08a6567465e9d63e5073e7bdf540cb7f0b7f",
    "src/retailpulse360/legacy_steps/RetailPulse360_P3_2_v5.py": "37bacf7bf8e30946732923a11b2b80fbf8c93e7e79dd57a68e004f4488180827",
    "src/retailpulse360/legacy_steps/RetailPulse360_P3_3.py": "30158d61e2d9e12c232872943740149723beb1de402b3289a4f41496e23a6fe9"
}


class SourceIntegrityTests(unittest.TestCase):
    def test_exact_source_hashes(self):
        for rel, digest in EXPECTED.items():
            with self.subTest(source=rel):
                target = ROOT / rel
                self.assertTrue(target.is_file() and not target.is_symlink(), rel)
                self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), digest)

    def test_sources_parse(self):
        for rel in EXPECTED:
            with self.subTest(source=rel):
                ast.parse((ROOT / rel).read_text(encoding="utf-8-sig"), filename=rel)

    def test_cli_help_only(self):
        for rel in EXPECTED:
            with self.subTest(source=rel):
                result = subprocess.run(
                    [sys.executable, str(ROOT / rel), "--help"],
                    cwd=ROOT, text=True, capture_output=True, timeout=15,
                )
                self.assertEqual(result.returncode, 0, result.stderr[-500:])
                self.assertIn("--root", result.stdout)


if __name__ == "__main__":
    unittest.main()

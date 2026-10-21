"""Portable generated-project path binding: isolated, no Power BI Desktop required."""
from pathlib import Path
import importlib.util
import shutil
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('rp360_open_powerbi', REPO / 'tools' / 'open_powerbi.py')
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


class PortablePowerBITest(unittest.TestCase):
    def setup_project(self, root):
        model = root / 'PowerBI/RetailPulse 360.SemanticModel/definition/expressions.tmdl'
        model.parent.mkdir(parents=True)
        model.write_text('/// independent test\nexpression pProjectRoot = "SET_LOCAL_BUILD_PROJECT_ROOT" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]\nexpression pGeneration = "CURRENT"\n')
        (root / 'PowerBI/RetailPulse 360.pbip').write_text('{}')
        gen = root / 'data/processed/p3_3'
        (gen / 'CURRENT').parent.mkdir(parents=True)
        (gen / 'CURRENT').write_text('G0004\n')
        analytics = gen / 'generations/G0004/analytics'
        analytics.mkdir(parents=True)
        for name in ('fact_sales_daily.csv', 'fact_budget_daily.csv', 'fact_marketplace_daily.csv'):
            (analytics / name).write_text('a\n')
        return model

    def test_bind_idempotence_and_move(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            root = base/'project path #1'/'project'
            model = self.setup_project(root)
            pbip, changed = MOD.configure(root)
            self.assertTrue(changed)
            self.assertTrue(pbip.exists())
            self.assertIn(MOD.m_literal(str(root.resolve())), model.read_text())
            baseline = model.read_bytes()
            _, changed_again = MOD.configure(root)
            self.assertFalse(changed_again)
            self.assertEqual(baseline, model.read_bytes())
            moved = base/'other project folder'/'project'
            moved.parent.mkdir(parents=True)
            shutil.move(str(root), str(moved))
            moved_model = moved/'PowerBI/RetailPulse 360.SemanticModel/definition/expressions.tmdl'
            _, changed_moved = MOD.configure(moved)
            self.assertTrue(changed_moved)
            self.assertIn(MOD.m_literal(str(moved.resolve())), moved_model.read_text())
            self.assertNotIn(MOD.m_literal(str(root.resolve())), moved_model.read_text())

    def test_no_generated_data_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(RuntimeError):
                MOD.configure(Path(folder))

    def test_m_literal_hash(self):
        self.assertEqual(MOD.m_literal('alpha#beta'), 'alpha#(#)beta')


if __name__ == '__main__':
    unittest.main()

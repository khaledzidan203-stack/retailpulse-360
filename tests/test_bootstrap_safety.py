"""Guard the authoring checkout and existing output from accidental rebuilds."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('bootstrap',ROOT/'tools/reproduce.py')
bootstrap=importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


class BootstrapSafetyTests(unittest.TestCase):
    def test_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory(prefix='retailpulse safety ') as name:
            target=Path(name)
            sentinel=target/'approved.txt'
            sentinel.write_bytes(b'approved content')
            with self.assertRaisesRegex(RuntimeError,'refusing overwrite'):
                bootstrap.reproduce(target)
            self.assertEqual(sentinel.read_bytes(),b'approved content')
            self.assertEqual([p.name for p in target.iterdir()],['approved.txt'])

    def test_output_inside_checkout_is_rejected(self):
        target=ROOT/'must-not-be-created-by-test'
        self.assertFalse(target.exists())
        with self.assertRaisesRegex(RuntimeError,'outside source checkout'):
            bootstrap.reproduce(target)
        self.assertFalse(target.exists())

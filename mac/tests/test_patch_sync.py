"""An interrupted lift must not be mistaken for an unconfigured install."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'setup'))
import patch_sync


class InterruptedLift(unittest.TestCase):
    def test_empty_install(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(patch_sync, 'PORT', tmp):
            self.assertEqual(patch_sync.sync_lifted('inputs'), 'none')

    def test_incomplete_output(self):
        for name in ('out', 'recompiled', 'spu'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp, patch.object(patch_sync, 'PORT', tmp):
                (Path(tmp) / name).mkdir()
                self.assertEqual(patch_sync.sync_lifted('inputs'), 'relift')

    def test_completed_lift(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(patch_sync, 'PORT', tmp):
            patch_sync.save_lifted_state(patch_sync._read(patch_sync.LIFTED_PATCH), 'inputs')
            self.assertEqual(patch_sync.sync_lifted('inputs'), 'current')
            self.assertEqual(patch_sync.sync_lifted('changed inputs'), 'relift')


if __name__ == '__main__':
    unittest.main()

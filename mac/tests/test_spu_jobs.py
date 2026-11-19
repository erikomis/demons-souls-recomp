"""Dump validation and preservation of previously working generated jobs."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SDK = Path(sys.argv.pop(1)).resolve()
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
import lift_spurs_jobs as jobs


class JobImport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='SPU jobs ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.miss = self.root / 'miss'
        self.output = self.root / 'spu'
        self.miss.mkdir()
        self.output.mkdir()
        (self.output / 'jobmods_register.c').write_text('previous working registry')

    def dump(self, raw=b'\x00\x00\x20\x00', fp=None, size=None):
        path = self.miss / f'spujob_{fp or jobs.fingerprint(raw)}_{len(raw) if size is None else size}.bin'
        path.write_bytes(raw)
        return path

    def fake_lift(self, argv, **kwargs):
        output = Path(argv[argv.index('-o') + 1])
        tag = output.name
        (output / 'spu_recomp.h').write_text('#include "spu_context.h"\n')
        (output / 'spu_recomp.c').write_text(f'void {tag}_spu_func_00000000(spu_context* ctx) {{}}\n')
        return subprocess.CompletedProcess(argv, 0, '', '')

    def snapshot(self):
        return {str(p.relative_to(self.output)): p.read_bytes()
                for p in self.output.rglob('*') if p.is_file()}

    def test_invalid_dumps_leave_previous_output(self):
        for kwargs in ({'fp': '0000000000000000'}, {'size': 8}, {'size': 0},
                       {'raw': b'123'}, {'size': 262148}):
            with self.subTest(kwargs=kwargs):
                path = self.dump(**kwargs)
                before = self.snapshot()
                with patch.object(jobs.subprocess, 'run') as run, self.assertRaises(ValueError):
                    jobs.lift_jobs(SDK, self.miss, self.output)
                run.assert_not_called()
                self.assertEqual(self.snapshot(), before)
                path.unlink()

    def test_empty_directory_preserves_registry(self):
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'no SPU job dumps'):
            jobs.lift_jobs(SDK, self.miss, self.output)
        self.assertEqual(self.snapshot(), before)

    def test_reserved_image_ids_are_not_overwritten(self):
        for value in range(101):
            self.dump(value.to_bytes(4, 'big'))
        with self.assertRaisesRegex(ValueError, 'reserved 200'):
            jobs.read_jobs(self.miss)

    def test_second_lift_failure_preserves_every_old_file(self):
        self.dump()
        self.dump(b'\x40\x20\x00\x00')
        tags = [tag for tag, _, _ in jobs.read_jobs(self.miss)]
        for tag in tags:
            (self.output / tag).mkdir()
            (self.output / tag / 'spu_recomp.c').write_text('previous generated code')
        before = self.snapshot()
        def run(argv, **kwargs):
            if Path(argv[-1]).name == tags[1]:
                return subprocess.CompletedProcess(argv, 1, '', 'synthetic lifter failure')
            return self.fake_lift(argv, **kwargs)
        with patch.object(jobs.subprocess, 'run', side_effect=run), self.assertRaises(RuntimeError):
            jobs.lift_jobs(SDK, self.miss, self.output)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(list(self.output.glob('.job-lift-*')))

    def test_incomplete_success_is_rejected(self):
        self.dump()
        before = self.snapshot()
        with patch.object(jobs.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')):
            with self.assertRaisesRegex(RuntimeError, 'did not produce'):
                jobs.lift_jobs(SDK, self.miss, self.output)
        self.assertEqual(self.snapshot(), before)

    def test_publish_failure_rolls_back_files(self):
        self.dump()
        tag = jobs.read_jobs(self.miss)[0][0]
        (self.output / tag).mkdir()
        (self.output / tag / 'spu_recomp.c').write_text('previous code')
        before = self.snapshot()
        replace = jobs.os.replace
        def fail_registry(src, dst):
            if Path(dst).name == 'jobmods_register.c':
                raise OSError('synthetic publish failure')
            return replace(src, dst)
        with patch.object(jobs.subprocess, 'run', side_effect=self.fake_lift):
            with patch.object(jobs.os, 'replace', side_effect=fail_registry), self.assertRaises(OSError):
                jobs.lift_jobs(SDK, self.miss, self.output)
        self.assertEqual(self.snapshot(), before)

    def test_real_lifter_and_registry(self):
        self.assertEqual(jobs.fingerprint(b'\x00\x00\x20\x00'), '30E786A08645CC13')
        self.dump()
        jobs.lift_jobs(SDK, self.miss, self.output)
        tag, fp, _ = jobs.read_jobs(self.miss)[0]
        registry = (self.output / 'jobmods_register.c').read_text()
        self.assertIn(f'0x{fp}ULL', registry)
        self.assertIn('spu_begin_image(100)', registry)
        self.assertIn(f'{tag}_spu_func_00000000', registry)
        self.assertTrue((self.output / tag / 'spu_recomp.h').is_file())
        self.assertTrue((self.output / 'job_images' / (tag + '.elf')).is_file())


if __name__ == '__main__':
    unittest.main()

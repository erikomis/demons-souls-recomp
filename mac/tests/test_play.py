"""Launch-script integration using a fake host window, never a game or real save."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class Play(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='des play ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'mac').mkdir()
        shutil.copyfile(Path(__file__).parents[1] / 'play.sh', self.root / 'mac/play.sh')
        self.build = self.root / 'custom build'
        self.build.mkdir()
        (self.build / 'DemonsSoulsRecomp').write_text('#!/bin/sh\nexit 0\n')
        (self.build / 'DemonsSoulsRecomp_window').write_text('''#!/bin/sh
printf '%s\\n' "$PS3_HDD0_ROOT" "$PS3_HDD1_ROOT" "$PS3_DEV_FLASH" "$PS3_RES_SCALE" "$@" > "$CAPTURE"
''')
        for binary in self.build.iterdir():
            binary.chmod(0o755)
        elf = self.root / 'game/PS3_GAME/USRDIR/EBOOT.elf'
        elf.parent.mkdir(parents=True)
        elf.write_bytes(b'fixture')
        self.env = dict(os.environ, DES_BUILD=str(self.build), DES_GAME='game', DES_MOVIES='0', DES_FPS='30',
                        PS3RECOMP_FFMPEG_AVCODEC='/unused', CAPTURE=str(self.root / 'capture'),
                        PS3RECOMP_MSL_CACHE=str(self.root / 'cache'), DES_LOG_DIR=str(self.root / 'logs'),
                        PS3_HDD0_ROOT=str(self.root / 'test hdd0'), PS3_HDD1_ROOT=str(self.root / 'test hdd1'),
                        PS3_DEV_FLASH=str(self.root / 'test flash'), PS3_RES_SCALE='1.5')

    def run_play(self, size='1280x720'):
        return subprocess.run(['/bin/sh', str(self.root / 'mac/play.sh')],
                              env=dict(self.env, DES_SIZE=size), capture_output=True, text=True, timeout=10)

    def use_default_build(self):
        default = self.root / 'port/build_mac'
        shutil.copytree(self.build, default)
        self.env.pop('DES_BUILD')

    def test_default_build_and_valid_sizes(self):
        self.use_default_build()
        for size in ('1x1', '1280x720', '16384x16384', '005x009'):
            with self.subTest(size=size):
                result = self.run_play(size)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_custom_build_and_roots(self):
        result = self.run_play('1920x1080')
        self.assertEqual(result.returncode, 0, result.stderr)
        values = (self.root / 'capture').read_text().splitlines()
        self.assertEqual(values[:4], [self.env[k] for k in ('PS3_HDD0_ROOT', 'PS3_HDD1_ROOT', 'PS3_DEV_FLASH', 'PS3_RES_SCALE')])
        self.assertIn(str(self.build / 'DemonsSoulsRecomp'), values)
        self.assertIn('1920x1080', values)
        self.assertFalse((self.root / 'hdd0').exists())

    def test_relative_build_and_default_roots(self):
        self.env['DES_BUILD'] = 'custom build'
        for key in ('PS3_HDD0_ROOT', 'PS3_HDD1_ROOT', 'PS3_DEV_FLASH'):
            self.env.pop(key)
        result = self.run_play()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / 'capture').read_text().splitlines()[:3],
                         [str(self.root / name) for name in ('hdd0', 'hdd1', 'no_flash')])

    def test_invalid_size_preserves_logs(self):
        self.use_default_build()
        logs = self.root / 'logs'
        logs.mkdir()
        current = logs / 'last_run_err.txt'
        current.write_text('previous session')
        for size in ('0x720', '1280x0', '1280x720oops', '1280x720x3', '12xx3', 'x720', '-1x720', '999999999999999999999x720', '16385x720'):
            with self.subTest(size=size):
                self.assertNotEqual(self.run_play(size).returncode, 0)
                self.assertEqual(current.read_text(), 'previous session')
                self.assertFalse((self.root / 'capture').exists())


if __name__ == '__main__':
    unittest.main()

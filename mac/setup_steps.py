"""The Python half of mac/rebuild.sh: the steps that reuse the setup's own code (setup/setup.py).
Run with the repository's venv Python, from the repository folder. Nothing here asks a question:
whatever SETUP.bat would ask, this either decides the same way or stops with a message.

  python mac/setup_steps.py game <image.iso|image.zip|disc folder> [--key HEX|file.dkey]
      the game files -> game/ (tools/iso_extract.py --all, then tools/udf_rename.py's real names;
      a dumped disc folder is hard-linked or copied), game/.extracted last. Already there: nothing.
  python mac/setup_steps.py check-elf [--any]
      game/PS3_GAME/USRDIR/EBOOT.elf against setup.py's EBOOT_ELF_SHA256 (--any: a warning only)
  python mac/setup_steps.py toolkit     setup.step_ps3recomp(): deps/ps3recomp + this port's patch
  python mac/setup_steps.py lift        setup.step_lift(): port/recompiled, port/spu + lifted-code.patch
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'setup'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
os.chdir(ROOT)
import setup  # noqa: E402  (setup/setup.py; its main() is not run)
import iso_extract  # noqa: E402


def fail(msg, code=1):
    print('ERROR: ' + msg, flush=True)
    sys.exit(code)


def disc_key(image, given, check):
    """The key that decrypts this image: the one given, else a .dkey / .key / .txt next to it."""
    cands = [given] if given else []
    stem = os.path.splitext(image)[0]
    cands += [stem + e for e in ('.dkey', '.key', '.txt') if os.path.isfile(stem + e)]
    d = os.path.dirname(image)
    cands += [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.lower().endswith('.dkey')]
    for c in cands:
        try:
            k = iso_extract.parse_key(c)
        except (ValueError, OSError):
            continue
        if check(k):
            print(f'  disc key OK ({os.path.basename(c) if os.path.isfile(c) else "the one given"})', flush=True)
            return k
    if given:
        fail('that disc key does not decrypt this image. Check it (32 hex digits, or the .dkey that came with '
             f'your dump) against Redump\'s page for the disc: {setup.REDUMP_PAGE}', 4)
    fail('this image is encrypted (as Redump images are) and needs its disc key: the 32 hex digits that came '
         'with your dump (a .dkey file next to the .iso), or the "Disc Key" on Redump\'s page for the disc: '
         f'{setup.REDUMP_PAGE} (Demon\'s Souls USA, BLUS-30443). Give it and run the install again.', 3)


def step_game(src, key):
    usr = os.path.join(setup.USRDIR, 'EBOOT.BIN')
    mark = os.path.join(setup.GAME, '.extracted')
    if os.path.isfile(usr) and os.path.isfile(mark):
        print('  already extracted', flush=True)
        return
    if not src:
        fail('no disc image given (DES_ISO): choose your Demon\'s Souls (USA, BLUS-30443) image')
    src = os.path.abspath(src)
    if not os.path.exists(src):
        fail(f'{src}: not there')
    os.makedirs(setup.GAME, exist_ok=True)
    if os.path.isdir(src):
        setup.copy_folder_dump(src)
    else:
        try:
            needs_key, check = iso_extract.probe(src)
        except SystemExit as e:   # iso_extract exits with a message for a non-PS3 image
            fail(str(e))
        k = disc_key(src, key, check) if needs_key else None
        if not needs_key:
            print('  the image is already decrypted, no disc key needed', flush=True)
        print('  extracting all game files (about 8 GB, a few minutes)...', flush=True)
        iso_extract.extract(src, setup.GAME, ['--all'], k)
        print('  restoring the real file names from the disc\'s UDF file system...', flush=True)
        r = subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'udf_rename.py'), src, setup.GAME])
        if r.returncode:
            fail('tools/udf_rename.py failed')
    if not os.path.isfile(usr):
        fail('no PS3_GAME/USRDIR/EBOOT.BIN after extraction: is this Demon\'s Souls (BLUS-30443)?')
    with open(mark, 'w') as f:
        f.write(src + '\n')
    print(f'  game files in {setup.GAME}', flush=True)


def step_check_elf(any_ok):
    elf = setup.find_eboot_elf()
    if not elf:
        fail('no game/PS3_GAME/USRDIR/EBOOT.elf')
    with open(elf, 'rb') as f:
        if f.read(4) != b'\x7fELF':
            fail(f'{elf} is not an ELF')
    h = setup.sha256(elf)
    if h == setup.EBOOT_ELF_SHA256:
        print('  EBOOT.elf OK (matches the tested build)', flush=True)
        return
    bin_ = os.path.join(setup.USRDIR, 'EBOOT.BIN')
    other = os.path.isfile(bin_) and setup.sha256(bin_) != setup.EBOOT_BIN_SHA256
    msg = (f'EBOOT.elf is not the tested one (sha256 {h}). This port is made for Demon\'s Souls USA BLUS-30443 '
           'version 1.00 as on the disc' + ('; your EBOOT.BIN is a different one too (another region or an update)'
                                            if other else '') + '. The patches will most likely not apply.')
    if any_ok:
        print('WARNING: ' + msg, flush=True)
        return
    fail(msg + ' (DES_ANY_EBOOT=1 continues anyway.)')


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == 'game':
        key = None
        if '--key' in rest:
            i = rest.index('--key')
            key = rest[i + 1] if i + 1 < len(rest) else None
            del rest[i:i + 2]
        step_game(rest[0] if rest else None, key or None)
    elif cmd == 'check-elf':
        step_check_elf('--any' in rest)
    elif cmd == 'toolkit':
        setup.step_ps3recomp()
    elif cmd == 'lift':
        if not setup.find_eboot_elf():
            fail('no game/PS3_GAME/USRDIR/EBOOT.elf: run the decrypt step first')
        setup.step_lift()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

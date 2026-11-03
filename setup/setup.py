"""One-shot setup: your Demon's Souls disc image -> a native Windows build.

Run through SETUP.bat (which makes the Python environment). Every step is skipped when its
output is already there, so after a failure just fix the cause and run SETUP.bat again. After an
update of this repo, steps 3 and 5 re-apply the patches that changed (setup/patch_sync.py).

  1. extract the game files from the disc image          -> game/
  2. decrypt EBOOT.BIN with RPCS3 (SELF -> ELF)           -> game/PS3_GAME/USRDIR/EBOOT.elf
  3. fetch ps3recomp at the tested commit + our patches   -> deps/ps3recomp
  4. recompile the game's PPU and SPU code to C/C++       -> port/recompiled, port/spu
  5. apply this port's edits to the recompiled code       (patches/lifted-code.patch)
  6. build DemonsSoulsRecomp.exe                          -> port/build_opt (setup/build.py)

usage: SETUP.bat [image.iso | image.zip | dumped disc folder] [--key HEX | --key file.dkey]
                 [--rpcs3 path\\to\\rpcs3.exe] [--jobs N]
"""
import hashlib, json, os, shutil, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
sys.path.insert(0, os.path.join(ROOT, 'setup'))
import build                                                    # noqa: E402
import patch_sync                                               # noqa: E402

GAME = os.path.join(ROOT, 'game')
USRDIR = os.path.join(GAME, 'PS3_GAME', 'USRDIR')
PORT = os.path.join(ROOT, 'port')
PS3RECOMP = os.path.join(ROOT, 'deps', 'ps3recomp')
CONFIG = os.path.join(ROOT, 'setup', 'local_config.json')       # remembered paths (git-ignored)

PS3RECOMP_URL = 'https://github.com/sp00nznet/ps3recomp.git'
PS3RECOMP_COMMIT = '4e8f3ca87a3e1d87bb83b8b7e9348fe2685cd514'   # v0.18.0, what the patches are made against
EBOOT_BIN_SHA256 = '77375fbf5c654b5a92b870831862a9a09bdc9e6052956d5b84503bda5704f3ac'
EBOOT_ELF_SHA256 = '90eaa5e9e48b4874292badc311ccea253e6a622ff188bfbdbe76e6f6821269d8'
# SPURS job binaries the game hands to SPU at run time; they sit inside the EBOOT (file offsets)
SPURS_JOBS = [(0x176B480, 384, 'B1463A6F2DF960AC'), (0x176B600, 2064, 'BD46853E5ADE5098')]
LIFT_ARGS = ['--code-end', '0x16bb5e4', '--chunks', '128']


def say(msg=''):
    print(msg, flush=True)


def step(n, msg):
    say(f'\n=== [{n}/6] {msg}')


def fail(msg):
    say('\nERROR: ' + msg)
    sys.exit(1)


def ask(prompt):
    try:
        return input(prompt).strip().strip('"')
    except EOFError:
        fail('no answer (input closed) -- run SETUP.bat in a console window')


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def load_config():
    try:
        return json.load(open(CONFIG))
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    json.dump(cfg, open(CONFIG, 'w'), indent=2)


def run(cmd, cwd=None, log=None):
    say('  > ' + ' '.join(os.path.basename(c) if i == 0 else c for i, c in enumerate(cmd)))
    if log:
        with open(log, 'w') as f:
            r = subprocess.run(cmd, cwd=cwd, stdout=f, stderr=subprocess.STDOUT)
        if r.returncode:
            fail(f'{os.path.basename(cmd[1] if cmd[0] == sys.executable else cmd[0])} failed -- see {log}')
    elif subprocess.run(cmd, cwd=cwd).returncode:
        fail('command failed: ' + ' '.join(cmd))


def find_eboot_elf():
    for n in ('EBOOT.elf', 'EBOOT.ELF'):
        p = os.path.join(USRDIR, n)
        if os.path.isfile(p):
            return p
    return None


# --- 1. game files -----------------------------------------------------------------------------

def get_image(args, cfg):
    src = args.get('image') or cfg.get('image')
    while not src or not os.path.exists(src):
        if src:
            say(f'  not found: {src}')
        say('  Drag your Demon\'s Souls (USA, BLUS-30443) disc image -- .iso, a Redump .zip,')
        say('  or a dumped disc folder that has PS3_GAME in it -- into this window and press Enter:')
        src = ask('  > ')
    return os.path.abspath(src)


def copy_folder_dump(src):
    if os.path.isdir(os.path.join(src, 'PS3_GAME')):
        base = src
    else:
        fail(f'{src} has no PS3_GAME folder')
    say(f'  copying the game files from {base} (hard links where possible)')
    n = 0
    for d, _, fs in os.walk(base):
        rel = os.path.relpath(d, base)
        if rel.split(os.sep)[0] == 'PS3_UPDATE':
            continue
        os.makedirs(os.path.join(GAME, rel), exist_ok=True)
        for f in fs:
            s, t = os.path.join(d, f), os.path.join(GAME, rel, f)
            if os.path.exists(t):
                continue
            try:
                os.link(s, t)
            except OSError:
                shutil.copy2(s, t)
            n += 1
    say(f'  {n} files')


def disc_key(args, image, needs_key, check):
    if not needs_key:
        say('  image is already decrypted, no disc key needed')
        return None
    import iso_extract
    cands = []
    if args.get('key'):
        cands.append(args['key'])
    stem = os.path.splitext(image)[0]
    for ext in ('.dkey', '.key', '.txt'):
        if os.path.isfile(stem + ext):
            cands.append(stem + ext)
    d = os.path.dirname(image)
    cands += [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.lower().endswith('.dkey')]
    for c in cands:
        try:
            k = iso_extract.parse_key(c)
        except (ValueError, OSError):
            continue
        if check(k):
            say(f'  disc key OK ({os.path.basename(c) if os.path.isfile(c) else "from --key"})')
            return k
    say('  This image is encrypted (as Redump images are) and needs its disc key: the 32 hex digits')
    say('  that came with your dump (a .dkey file next to the .iso), or the "Disc Key" on the Redump')
    say('  page for your disc (redump.org, Demon\'s Souls USA, BLUS-30443).')
    while True:
        t = ask('  Disc key (or drag the .dkey file here): ')
        try:
            k = iso_extract.parse_key(t)
        except (ValueError, OSError) as e:
            say(f'  {e}'); continue
        if check(k):
            return k
        say('  That key does not decrypt this disc. Check it and try again.')


def step_game(args, cfg):
    step(1, 'game files')
    if os.path.isfile(os.path.join(USRDIR, 'EBOOT.BIN')) and os.path.isfile(os.path.join(GAME, '.extracted')):
        say('  already extracted'); return
    image = get_image(args, cfg)
    cfg['image'] = image; save_config(cfg)
    if os.path.isdir(image):
        copy_folder_dump(image)
    else:
        import iso_extract
        needs_key, check = iso_extract.probe(image)
        key = disc_key(args, image, needs_key, check)
        say('  extracting all game files (about 8 GB, a few minutes)...')
        iso_extract.extract(image, GAME, ['--all'], key)
        say('  restoring the real file names from the disc\'s UDF file system...')
        run([sys.executable, os.path.join(ROOT, 'tools', 'udf_rename.py'), image, GAME])
    if not os.path.isfile(os.path.join(USRDIR, 'EBOOT.BIN')):
        fail('no PS3_GAME/USRDIR/EBOOT.BIN after extraction')
    open(os.path.join(GAME, '.extracted'), 'w').write(image + '\n')


# --- 2. EBOOT.BIN -> EBOOT.elf -----------------------------------------------------------------

def find_rpcs3(args, cfg):
    cands = [args.get('rpcs3'), os.environ.get('RPCS3'), cfg.get('rpcs3'),
             os.path.join(ROOT, 'deps', 'rpcs3', 'rpcs3.exe'), shutil.which('rpcs3')]
    for c in cands:
        if c and os.path.isdir(c):
            c = os.path.join(c, 'rpcs3.exe')
        if c and os.path.isfile(c):
            return os.path.abspath(c)
    return None


def step_decrypt(args, cfg):
    step(2, 'decrypt EBOOT.BIN (RPCS3)')
    eboot = os.path.join(USRDIR, 'EBOOT.BIN')
    h = sha256(eboot)
    if h != EBOOT_BIN_SHA256:
        say(f'  WARNING: EBOOT.BIN is not the tested one (sha256 {h}).')
        say('  This port is made for Demon\'s Souls USA BLUS-30443 version 1.00 as on the disc; the')
        say('  patches will most likely not apply to another region or an updated EBOOT.')
        if ask('  Continue anyway? [y/N] ').lower() != 'y':
            sys.exit(1)
    elf = find_eboot_elf()
    if not elf:
        rpcs3 = find_rpcs3(args, cfg)
        while not rpcs3:
            say('  The game\'s EBOOT.BIN is a signed+encrypted PS3 executable (SELF); RPCS3 decrypts it.')
            say('  Get RPCS3 from https://rpcs3.net/download (unzip it anywhere), then drag rpcs3.exe')
            say('  here and press Enter. (Or decrypt it yourself: RPCS3 -> Utilities -> Decrypt PS3')
            say(f'  Binaries -> {eboot}, then just press Enter.)')
            t = ask('  rpcs3.exe: ')
            if not t and find_eboot_elf():
                break
            rpcs3 = find_rpcs3({'rpcs3': t}, {})
        if rpcs3:
            cfg['rpcs3'] = rpcs3; save_config(cfg)
            say('  running rpcs3 --decrypt (a window may flash up)')
            try:
                subprocess.run([rpcs3, '--decrypt', eboot], timeout=180)
            except subprocess.TimeoutExpired:
                pass
        elf = find_eboot_elf()
        while not elf:
            say('  RPCS3 did not write EBOOT.elf (is another RPCS3 window open? close it and run SETUP.bat')
            say('  again), or decrypt by hand: RPCS3 -> Utilities -> Decrypt PS3 Binaries ->')
            say(f'  {eboot}  -- it writes EBOOT.elf next to it.')
            if ask('  Press Enter when EBOOT.elf is there (or type q to quit): ').lower() == 'q':
                sys.exit(1)
            elf = find_eboot_elf()
    h = sha256(elf)
    if h != EBOOT_ELF_SHA256:
        say(f'  WARNING: EBOOT.elf differs from the tested one (sha256 {h}).')
        if ask('  Continue anyway? [y/N] ').lower() != 'y':
            sys.exit(1)
    else:
        say('  EBOOT.elf OK (matches the tested build)')


# --- 3. ps3recomp -------------------------------------------------------------------------------

def git(*a, cwd=None, check=True):
    r = subprocess.run(['git', *a], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode:
        fail(f'git {" ".join(a)} failed:\n{r.stdout}{r.stderr}')
    return r


def step_ps3recomp():
    step(3, 'ps3recomp (static recompiler + PS3 runtime) at the tested commit, with this port\'s patch')
    mark = os.path.join(PS3RECOMP, '.ds_patched')
    if os.path.isfile(mark):
        state = patch_sync.sync_runtime(PS3RECOMP_COMMIT)   # an update since: re-apply the patch
        if state == 'current':
            say('  already set up')
        if state in ('current', 'updated'):
            return
        say('  setting it up again')
    if not os.path.isdir(os.path.join(PS3RECOMP, '.git')):
        os.makedirs(os.path.dirname(PS3RECOMP), exist_ok=True)
        say(f'  cloning {PS3RECOMP_URL}')
        git('clone', '-q', PS3RECOMP_URL, PS3RECOMP)
    if git('cat-file', '-e', PS3RECOMP_COMMIT + '^{commit}', cwd=PS3RECOMP, check=False).returncode:
        git('fetch', '-q', 'origin', cwd=PS3RECOMP)
    git('-c', 'advice.detachedHead=false', 'checkout', '-q', '-f', PS3RECOMP_COMMIT, cwd=PS3RECOMP)
    git('reset', '-q', '--hard', cwd=PS3RECOMP)
    git('clean', '-q', '-fd', cwd=PS3RECOMP)
    git('apply', '--whitespace=nowarn', os.path.join(ROOT, 'patches', 'ps3recomp-local.patch'), cwd=PS3RECOMP)
    with open(os.path.join(ROOT, 'patches', 'ps3recomp-local.patch'), 'rb') as f:
        patch_sync.save_runtime_state(PS3RECOMP_COMMIT, f.read())
    say('  patched')


# --- 4 + 5. recompile ---------------------------------------------------------------------------

def lift_inputs():
    """What the recompiled code is made from besides the EBOOT; if this changes, an update needs a
    full recompile, not just lifted-code.patch again (setup/patch_sync.py)."""
    with open(os.path.join(ROOT, 'tools', 'lift_spurs_jobs.py'), 'rb') as f:
        tool = hashlib.sha256(f.read().replace(b'\r\n', b'\n')).hexdigest()[:16]
    return f'{PS3RECOMP_COMMIT} {" ".join(LIFT_ARGS)} {SPURS_JOBS} {tool}'


def step_lift():
    step(4, 'recompile the game code (PPU + SPU) -- a few minutes')
    mark = os.path.join(PORT, '.lifted')
    if os.path.isfile(mark):
        state = patch_sync.sync_lifted(lift_inputs())   # an update since: re-apply lifted-code.patch
        if state == 'current':
            say('  already done')
        if state in ('current', 'updated'):
            return
        os.remove(mark)   # 'relift': recompile from scratch below
    for d in ('out', 'recompiled', 'spu', 'spu_miss'):
        shutil.rmtree(os.path.join(PORT, d), ignore_errors=True)
    os.makedirs(os.path.join(PORT, 'game'), exist_ok=True)
    elf = os.path.join(PORT, 'game', 'EBOOT.ELF')
    shutil.copyfile(find_eboot_elf(), elf)
    T = os.path.join(PS3RECOMP, 'tools')
    py = sys.executable
    logs = os.path.join(PORT, 'logs'); os.makedirs(logs, exist_ok=True)
    run([py, os.path.join(T, 'ppu_loader.py'), 'game/EBOOT.ELF', '-o', 'out/'], PORT,
        os.path.join(logs, 'ppu_loader.log'))
    say('  lifting 94,000 PPU functions (about a minute or two)...')
    run([py, os.path.join(T, 'ppu_lifter.py'), 'game/EBOOT.ELF', '--functions', 'out/EBOOT.functions.json',
         '--hle-stubs', 'out/EBOOT.imports.json', *LIFT_ARGS, '--output', 'recompiled/'], PORT,
        os.path.join(logs, 'ppu_lifter.log'))
    run([py, os.path.join(T, 'extract_spu_images.py'), 'game/EBOOT.ELF', '--output', 'spu/images'], PORT,
        os.path.join(logs, 'spu_extract.log'))
    run([py, os.path.join(T, 'build_spu_workloads.py'), '--images', 'spu/images', '--lifted', 'spu',
         '--out', 'spu/spu_workloads.c', '--constructor'], PORT, os.path.join(logs, 'spu_lift.log'))
    raw = open(elf, 'rb').read()
    os.makedirs(os.path.join(PORT, 'spu_miss'), exist_ok=True)
    for off, size, fp in SPURS_JOBS:
        open(os.path.join(PORT, 'spu_miss', f'spujob_{fp}_{size}.bin'), 'wb').write(raw[off:off + size])
    run([py, os.path.join(ROOT, 'tools', 'lift_spurs_jobs.py'), PS3RECOMP, 'spu_miss', 'spu'], PORT,
        os.path.join(logs, 'spu_jobs.log'))

    step(5, 'apply this port\'s edits to the recompiled code')
    n = 0
    for sub in ('recompiled', 'spu'):
        for d, _, fs in os.walk(os.path.join(PORT, sub)):
            for f in fs:
                if f.endswith(('.c', '.cpp', '.h')):
                    p = os.path.join(d, f); b = open(p, 'rb').read()
                    if b'\r\n' in b:
                        open(p, 'wb').write(b.replace(b'\r\n', b'\n')); n += 1
    patch = os.path.join(ROOT, 'patches', 'lifted-code.patch')
    # port/ sits inside this repo's checkout: keep git from finding that repo, or it would take the
    # patch's paths as relative to the checkout's top instead of port/
    r = subprocess.run(['git', 'apply', '--whitespace=nowarn', '-p1', patch], cwd=PORT, capture_output=True,
                       text=True, env=dict(os.environ, GIT_CEILING_DIRECTORIES=ROOT))
    if r.returncode:
        fail(f'patches/lifted-code.patch did not apply:\n{r.stdout}{r.stderr}')
    with open(patch, 'rb') as f:
        patch_sync.save_lifted_state(f.read(), lift_inputs())
    say('  done')


def main():
    args, a = {}, sys.argv[1:]
    while a:
        x = a.pop(0)
        if x in ('--key', '--rpcs3', '--jobs') and a:
            args[x[2:]] = a.pop(0)
        elif x in ('-h', '--help'):
            say(__doc__); return
        else:
            args['image'] = x
    if shutil.which('git') is None:
        fail('git is not installed (SETUP.bat normally checks this)')
    cfg = load_config()
    say("Demon's Souls (BLUS-30443) -- ps3recomp PC port setup")
    step_game(args, cfg)
    step_decrypt(args, cfg)
    step_ps3recomp()
    step_lift()
    step(6, 'build DemonsSoulsRecomp.exe (the first build takes a while: 10-30 minutes)')
    for d in ('hdd0', 'hdd1', 'no_flash', 'logs'):
        os.makedirs(os.path.join(ROOT, d), exist_ok=True)
    if build.build(jobs=args.get('jobs')):
        fail('the build failed -- see the messages above')
    say('\nAll done. Double-click PLAY.bat to play.')


if __name__ == '__main__':
    main()

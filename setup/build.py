"""Build DemonsSoulsRecomp.exe (port/build_opt) with clang-cl, CMake and Ninja.

Finds the tools by itself: Visual Studio 2022 (or its Build Tools) with the C++ workload for the
Windows SDK and libraries, and clang-cl + lld-link from an LLVM install (LLVM_DIR, deps/llvm,
C:\\Program Files\\LLVM, Visual Studio's own Clang component, or PATH). CMake and Ninja come from
the Python environment SETUP.bat makes. Offers to install what is missing with winget.

The configuration is the tested one: build type "Fast" (no CMake flag preset, so the project's own
-O1 / -O2 apply) and the boot harness runner (DS_BOOT_HARNESS=ON).

The lifted SPU code uses AVX2 when this CPU has it (DS_AVX2). On an older CPU it is built without,
and port/build_opt/no_avx2.txt tells PLAY.bat not to ask for it. "set DS_AVX2=0" before BUILD.bat
builds without AVX2 on any CPU (for a copy meant for an older PC).

On Linux (docs/LINUX.md) the same exe is cross-compiled: clang-cl + lld-link from LLVM, with the
Microsoft C runtime and Windows SDK fetched on this PC by xwin (Microsoft's license is shown and
accepted by you, nothing of it is shipped with this repo) and the C runtime linked statically so
Wine/Proton needs no Visual C++ DLLs (setup/clang-cl-xwin.cmake). "set DS_XWIN=1" before BUILD.bat
takes that path on Windows too, without Visual Studio.

usage: BUILD.bat [--jobs N] [ninja targets...]
       build.py --runtime-only [--jobs N]   (cross toolchain: ps3recomp's runtime alone, no game needed)
"""
import glob, hashlib, os, re, shutil, subprocess, sys, tarfile, tempfile, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, 'port', 'build_opt')
# Copies of the patches the last successful full build was made from. PLAY.bat compares them with
# patches/: a folder updated (git pull, a new ZIP) but not rebuilt -- or whose rebuild failed or was
# stopped -- would run the old exe with the new files (GitHub #4: a black screen at the title).
BUILT = os.path.join(BUILD, 'built')
PATCHES = ('ps3recomp-local.patch', 'lifted-code.patch')
MIN_CLANG = 17
EXE = '.exe' if os.name == 'nt' else ''
XWIN_DIR = os.environ.get('DS_XWIN_DIR') or os.path.join(ROOT, 'deps', 'xwin')
XWIN_VERSION = '0.10.0'
XWIN_URL = 'https://github.com/Jake-Shadle/xwin/releases/download/{v}/xwin-{v}-{t}.tar.gz'
XWIN_LICENSE = 'https://go.microsoft.com/fwlink/?LinkId=2086102'


def say(msg=''):
    print(msg, flush=True)


def ask(prompt):
    try:
        return input(prompt).strip().lower()
    except EOFError:
        return ''


def fwd(p):
    return p.replace('\\', '/')


def find_vs():
    pf86 = os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')
    vswhere = os.path.join(pf86, 'Microsoft Visual Studio', 'Installer', 'vswhere.exe')
    if os.path.isfile(vswhere):
        r = subprocess.run([vswhere, '-latest', '-products', '*', '-requires',
                            'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-property', 'installationPath'],
                           capture_output=True, text=True)
        for line in r.stdout.splitlines():
            bat = os.path.join(line.strip(), 'VC', 'Auxiliary', 'Build', 'vcvars64.bat')
            if os.path.isfile(bat):
                return line.strip(), bat
    return None, None


def clang_version(bindir):
    try:
        out = subprocess.run([os.path.join(bindir, 'clang-cl' + EXE), '--version'], capture_output=True,
                             text=True).stdout
    except OSError:
        return 0, ''
    m = re.search(r'version (\d+)\.', out)
    return (int(m.group(1)) if m else 0), out.splitlines()[0] if out else ''


def find_llvm(vs_path):
    cands = []
    if os.environ.get('LLVM_DIR'):
        cands += [os.environ['LLVM_DIR'], os.path.join(os.environ['LLVM_DIR'], 'bin')]
    cands += glob.glob(os.path.join(ROOT, 'deps', 'llvm', '**', 'bin'), recursive=True)
    cands.append(os.path.join(os.environ.get('ProgramFiles', r'C:\Program Files'), 'LLVM', 'bin'))
    if vs_path:
        cands.append(os.path.join(vs_path, 'VC', 'Tools', 'Llvm', 'x64', 'bin'))
    w = shutil.which('clang-cl')
    if w:
        cands.append(os.path.dirname(w))
    best = None
    for c in cands:
        if os.path.isfile(os.path.join(c, 'clang-cl.exe')) and os.path.isfile(os.path.join(c, 'lld-link.exe')):
            v, text = clang_version(c)
            if best is None or v > best[0]:
                best = (v, c, text)
    return best


def winget(pkg, extra=()):
    if not shutil.which('winget'):
        say('  winget is not available; install it by hand (see README.md).')
        return False
    say(f'  > winget install {pkg}')
    return subprocess.run(['winget', 'install', '-e', '--id', pkg, '--accept-package-agreements',
                           '--accept-source-agreements', *extra]).returncode == 0


def tools():
    vs_path, vcvars = find_vs()
    if not vcvars:
        say('  Visual Studio 2022 with "Desktop development with C++" (or the free Build Tools) is needed')
        say('  for the Windows SDK and C++ libraries.')
        if ask('  Install the Visual Studio 2022 Build Tools now with winget (about 3 GB)? [Y/n] ') != 'n':
            winget('Microsoft.VisualStudio.2022.BuildTools',
                   ['--override', '--wait --passive --add Microsoft.VisualStudio.Workload.VCTools '
                                  '--includeRecommended'])
            vs_path, vcvars = find_vs()
        if not vcvars:
            return None
    llvm = find_llvm(vs_path)
    if not llvm or llvm[0] < MIN_CLANG:
        if llvm:
            say(f'  clang-cl in {llvm[1]} is too old ({llvm[2]}); LLVM {MIN_CLANG} or newer is needed.')
        else:
            say('  clang-cl (LLVM) is needed -- the recompiled code is built with it, not with MSVC.')
        if ask('  Install LLVM now with winget? [Y/n] ') != 'n':
            winget('LLVM.LLVM')
            llvm = find_llvm(vs_path)
        if not llvm or llvm[0] < MIN_CLANG:
            return None
    scripts = os.path.dirname(sys.executable)
    cmake = shutil.which('cmake', path=scripts) or shutil.which('cmake')
    ninja = shutil.which('ninja', path=scripts) or shutil.which('ninja')
    if not cmake or not ninja:
        say('  CMake / Ninja missing: run SETUP.bat (it installs them into .venv).')
        return None
    return vcvars, llvm, cmake, ninja


def want_avx2():
    e = os.environ.get('DS_AVX2', '').strip()
    if e in ('0', '1'):
        return e == '1'
    if os.name != 'nt':
        try:
            with open('/proc/cpuinfo') as f:
                return any(l.startswith('flags') and ' avx2' in l for l in f)
        except OSError:
            return True
    try:
        import ctypes
        return bool(ctypes.windll.kernel32.IsProcessorFeaturePresent(40))  # PF_AVX2_INSTRUCTIONS_AVAILABLE
    except Exception:
        return True


# --- cross toolchain: clang-cl + lld-link + xwin (Linux; Windows with DS_XWIN=1) -----------------

def use_xwin():
    return os.name != 'nt' or os.environ.get('DS_XWIN', '').strip() == '1'


def find_llvm_cross():
    """An LLVM bin folder with clang-cl, lld-link and llvm-lib (Linux packages put them in
    /usr/lib/llvm-N/bin). Returns (version, folder, version text) or None."""
    cands = []
    for e in ('DS_LLVM_DIR', 'LLVM_DIR'):
        if os.environ.get(e):
            cands += [os.environ[e], os.path.join(os.environ[e], 'bin')]
    cands += glob.glob(os.path.join(ROOT, 'deps', 'llvm', '**', 'bin'), recursive=True)
    if os.name != 'nt':
        cands += sorted(glob.glob('/usr/lib/llvm-*/bin'), reverse=True) + ['/usr/local/bin', '/usr/bin']
    w = shutil.which('clang-cl')
    if w:
        cands.append(os.path.dirname(os.path.realpath(w)))
        cands.append(os.path.dirname(w))
    best = None
    for c in cands:
        if all(os.path.isfile(os.path.join(c, t + EXE)) for t in ('clang-cl', 'lld-link', 'llvm-lib')):
            v, text = clang_version(c)
            if best is None or v > best[0]:
                best = (v, c, text)
    return best


def pip_tool(name):
    """cmake / ninja from their pip packages (the module knows where its binary is, which still holds
    when the Python environment was moved, as inside the Linux AppImage), else from PATH."""
    try:
        if name == 'cmake':
            import cmake
            p = os.path.join(cmake.CMAKE_BIN_DIR, 'cmake' + EXE)
        else:
            import ninja
            p = os.path.join(ninja.BIN_DIR, 'ninja' + EXE)
        if os.path.isfile(p):
            return p
    except (ImportError, AttributeError):
        pass
    return shutil.which(name, path=os.path.dirname(sys.executable)) or shutil.which(name)


def find_xwin():
    cands = [os.environ.get('XWIN'), shutil.which('xwin'), os.path.join(ROOT, 'deps', 'xwin-bin', 'xwin' + EXE)]
    return next((c for c in cands if c and os.path.isfile(c)), None)


def download_xwin():
    """The xwin release for this OS from its GitHub page, checked against the release's sha256."""
    target = 'x86_64-pc-windows-msvc' if os.name == 'nt' else 'x86_64-unknown-linux-musl'
    url = XWIN_URL.format(v=XWIN_VERSION, t=target)
    say(f'  downloading xwin {XWIN_VERSION} (open source, ~3 MB): {url}')
    try:
        data = urllib.request.urlopen(url, timeout=120).read()
        want = urllib.request.urlopen(url + '.sha256', timeout=60).read().decode().split()[0].lower()
    except OSError as e:
        say(f'  download failed: {e}')
        return None
    if hashlib.sha256(data).hexdigest() != want:
        say('  xwin download does not match its sha256; not using it')
        return None
    out = os.path.join(ROOT, 'deps', 'xwin-bin')
    os.makedirs(out, exist_ok=True)
    fd, tgz = tempfile.mkstemp(suffix='.tar.gz')
    with os.fdopen(fd, 'wb') as f:
        f.write(data)
    try:
        with tarfile.open(tgz) as t:
            m = next(m for m in t.getmembers() if m.isfile() and os.path.basename(m.name) == 'xwin' + EXE)
            with t.extractfile(m) as src, open(os.path.join(out, 'xwin' + EXE), 'wb') as dst:
                shutil.copyfileobj(src, dst)
    finally:
        os.remove(tgz)
    exe = os.path.join(out, 'xwin' + EXE)
    os.chmod(exe, 0o755)
    return exe


def xwin_paths(sdk):
    """Include and library folders of an "xwin splat --use-winsysroot-style --preserve-ms-arch-notation"
    folder (the Visual Studio layout: VC/Tools/MSVC/<ver>, Windows Kits/10/{Include,Lib}/<ver>), and the
    MSVC version clang-cl should imitate (CRT 14.44 -> 19.44)."""
    def newest(pattern):
        found = sorted(glob.glob(os.path.join(sdk, *pattern)),
                       key=lambda p: [int(x) for x in re.findall(r'\d+', os.path.basename(p))])
        return found[-1] if found else os.path.join(sdk, *pattern).replace('*', '?')
    vc = newest(('VC', 'Tools', 'MSVC', '*'))
    inc_kit = newest(('Windows Kits', '10', 'Include', '*'))
    lib_kit = newest(('Windows Kits', '10', 'Lib', '*'))
    inc = [os.path.join(vc, 'include')] + [os.path.join(inc_kit, d) for d in ('ucrt', 'um', 'shared', 'winrt')]
    lib = [os.path.join(vc, 'lib', 'x64')] + [os.path.join(lib_kit, d, 'x64') for d in ('um', 'ucrt')]
    m = re.match(r'14\.(\d+)', os.path.basename(vc))
    return inc, lib, f'19.{m.group(1)}' if m else '19.40'


def xwin_sdk():
    """The Microsoft CRT + Windows SDK in deps/xwin, fetched once by xwin (about 1 GB to download,
    700 MB on disk). xwin itself asks you to accept Microsoft's license."""
    mark = os.path.join(XWIN_DIR, '.ds_done')
    if os.path.isfile(mark):
        return XWIN_DIR
    if os.environ.get('DS_XWIN_DIR'):   # your own "xwin splat" output: used as it is
        inc, lib, _ = xwin_paths(XWIN_DIR)
        missing = [p for p in inc + lib if not os.path.isdir(p)]
        if missing:
            say('  DS_XWIN_DIR is not an xwin splat --use-winsysroot-style folder (no ' + ', '.join(missing) + ')')
            return None
        return XWIN_DIR
    say('  The exe is built against Microsoft\'s C runtime and Windows SDK. They are not part of this')
    say('  repo: xwin (an open-source tool) downloads them from Microsoft to this PC, once. Microsoft')
    say(f'  allows that under its license ({XWIN_LICENSE}); xwin asks you to accept it.')
    xwin = find_xwin() or download_xwin()
    if not xwin:
        say('  xwin is needed: get it from https://github.com/Jake-Shadle/xwin/releases and put it in')
        say(f'  {os.path.join(ROOT, "deps", "xwin-bin")} (or set XWIN=/path/to/xwin).')
        return None
    cache = os.path.join(ROOT, 'deps', 'xwin-cache')
    # the Visual Studio folder layout on every OS; xwin's symlinks fix the case of header names that
    # Microsoft's own headers spell differently (Linux), and need rights Windows does not give by default
    cmd = [xwin, '--cache-dir', cache, '--arch', 'x86_64', '--variant', 'desktop', '--http-retry', '3',
           'splat', '--output', XWIN_DIR, '--use-winsysroot-style', '--preserve-ms-arch-notation']
    if os.name == 'nt':
        cmd.append('--disable-symlinks')
    shutil.rmtree(XWIN_DIR, ignore_errors=True)
    say('  > xwin splat (downloading the Microsoft CRT + SDK, a few minutes)')
    if subprocess.run(cmd).returncode:
        say('  xwin failed (see above); run the setup again to retry.')
        return None
    shutil.rmtree(cache, ignore_errors=True)   # the downloaded packages, no longer needed
    inc, lib, _ = xwin_paths(XWIN_DIR)
    missing = [p for p in inc + lib if not os.path.isdir(p)]
    if missing:
        say('  xwin output is missing ' + ', '.join(missing))
        return None
    with open(mark, 'w') as f:
        f.write(f'xwin {XWIN_VERSION}\n')
    return XWIN_DIR


def default_jobs():
    """One compile per core, but on Linux no more than ~1 per 2.5 GB of free memory: the biggest
    lifted files need about that much, and a Steam Deck has 16 GB for 8 threads."""
    n = os.cpu_count() or 4
    if os.name != 'nt':
        try:
            with open('/proc/meminfo') as f:
                kb = next(int(l.split()[1]) for l in f if l.startswith('MemAvailable:'))
            n = max(1, min(n, int(kb / (2.5 * 1024 * 1024))))
        except (OSError, StopIteration, ValueError):
            pass
    return n


def build_xwin(jobs=None, targets=(), runtime_only=False):
    """runtime_only: just ps3recomp's runtime library (deps/ps3recomp on its own, port/build_runtime),
    no game code -- a quick check of the toolchain that needs no disc (the Linux CI job runs it)."""
    llvm = find_llvm_cross()
    if not llvm or llvm[0] < MIN_CLANG:
        say(f'  clang-cl + lld-link (LLVM {MIN_CLANG} or newer) are needed. The Linux AppImage brings them;')
        say('  from a git checkout install your distribution\'s clang and lld packages (Debian/Ubuntu:')
        say('  clang lld llvm, Fedora: clang lld llvm, Arch: clang lld llvm) or set DS_LLVM_DIR.')
        return 1
    ver, bindir, ver_text = llvm
    cmake, ninja = pip_tool('cmake'), pip_tool('ninja')
    if not cmake or not ninja:
        say('  CMake / Ninja missing: pip install cmake ninja (the setup normally does).')
        return 1
    sdk = xwin_sdk()
    if not sdk:
        return 1
    say(f'  compiler: {ver_text} ({bindir}), Microsoft CRT/SDK from xwin ({sdk})')
    inc, lib, msc = xwin_paths(sdk)
    env = dict(os.environ, INCLUDE=';'.join(inc), LIB=';'.join(lib))
    env.pop('EXTERNAL_INCLUDE', None)
    jobs = int(jobs or default_jobs())
    toolchain = fwd(os.path.join(ROOT, 'setup', 'clang-cl-xwin.cmake'))
    bdir = os.path.join(ROOT, 'port', 'build_runtime') if runtime_only else BUILD
    cache = os.path.join(bdir, 'CMakeCache.txt')
    if os.path.isfile(cache) and toolchain not in open(cache, errors='replace').read():
        say(f'  {bdir} was configured with another toolchain (Visual Studio?). Delete that folder')
        say('  (or set DS_XWIN=0) and build again.')
        return 1
    avx2 = want_avx2()
    flag = '-DDS_AVX2=' + ('ON' if avx2 else 'OFF')
    if not avx2 and not runtime_only:
        say('  CPU without AVX2 (or DS_AVX2=0): building the SPU code without it')
    ps3recomp = fwd(os.path.join(ROOT, 'deps', 'ps3recomp'))
    if not os.path.isfile(os.path.join(bdir, 'build.ninja')):
        cfg = [cmake, '-S', ps3recomp if runtime_only else fwd(os.path.join(ROOT, 'project')),
               '-B', fwd(bdir), '-G', 'Ninja',
               f'-DCMAKE_MAKE_PROGRAM={fwd(ninja)}', f'-DCMAKE_TOOLCHAIN_FILE={toolchain}',
               f'-DDS_LLVM_BIN={fwd(bindir)}', f'-DDS_MSVC_COMPAT={msc}',
               # static C runtime: Wine/Proton then needs none of the Visual C++ DLLs
               '-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded',
               '-DCMAKE_BUILD_TYPE=Fast', f'-DPython3_EXECUTABLE={fwd(sys.executable)}']
        if not runtime_only:
            cfg += ['-DDS_BOOT_HARNESS=ON', f'-DPS3RECOMP_DIR={ps3recomp}',
                    f'-DRECOMP_DIR={fwd(os.path.join(ROOT, "port", "recompiled"))}',
                    f'-DSPU_DIR={fwd(os.path.join(ROOT, "port", "spu"))}', flag]
    elif runtime_only:
        cfg = None
    else:   # existing build: a quick CMake re-run; the SPU code rebuilds only when the choice changed
        cfg = [cmake, flag, fwd(bdir)]
    if cfg and subprocess.run(cfg, env=env, stdout=subprocess.DEVNULL if len(cfg) == 3 else None).returncode:
        return 5
    if runtime_only:
        targets = targets or ['ps3recomp_runtime']
    rc = subprocess.run([ninja, '-C', bdir, '-j', str(jobs), *targets], env=env).returncode
    if runtime_only:
        say('\n  runtime library built' if rc == 0 else '\n  runtime library build FAILED')
        return rc
    return finish(rc, avx2)


def build(jobs=None, targets=()):
    if use_xwin():
        return build_xwin(jobs, targets)
    t = tools()
    if not t:
        say('  Missing build tools -- see README.md, "What you need".')
        return 1
    vcvars, (ver, llvm, ver_text), cmake, ninja = t
    say(f'  compiler: {ver_text} ({llvm})')
    jobs = int(jobs or os.cpu_count() or 8)
    L = fwd(llvm)
    lines = ['@echo off', f'call "{vcvars}" >nul || exit /b 4',
             f'set "PATH={os.path.dirname(cmake)};{os.path.dirname(ninja)};{llvm};%PATH%"']
    if not os.path.isfile(os.path.join(BUILD, 'build.ninja')):
        cfg = [f'"{cmake}"', '-S', f'"{fwd(os.path.join(ROOT, "project"))}"', '-B', f'"{fwd(BUILD)}"',
               '-G', 'Ninja', f'-DCMAKE_MAKE_PROGRAM="{fwd(ninja)}"',
               '-DCMAKE_BUILD_TYPE=Fast', '-DDS_BOOT_HARNESS=ON',
               f'-DPS3RECOMP_DIR="{fwd(os.path.join(ROOT, "deps", "ps3recomp"))}"',
               f'-DRECOMP_DIR="{fwd(os.path.join(ROOT, "port", "recompiled"))}"',
               f'-DSPU_DIR="{fwd(os.path.join(ROOT, "port", "spu"))}"',
               f'-DPython3_EXECUTABLE="{fwd(sys.executable)}"',
               f'-DCMAKE_C_COMPILER="{L}/clang-cl.exe"', f'-DCMAKE_CXX_COMPILER="{L}/clang-cl.exe"',
               f'-DCMAKE_LINKER="{L}/lld-link.exe"']
        if os.path.isfile(os.path.join(llvm, 'llvm-rc.exe')):
            cfg.append(f'-DCMAKE_RC_COMPILER="{L}/llvm-rc.exe"')
        if os.path.isfile(os.path.join(llvm, 'llvm-lib.exe')):
            cfg.append(f'-DCMAKE_AR="{L}/llvm-lib.exe"')
        lines.append(' '.join(cfg) + ' || exit /b 5')
    else:
        cfg = None
    avx2 = want_avx2()
    flag = '-DDS_AVX2=' + ('ON' if avx2 else 'OFF')
    if cfg:
        lines[-1] = lines[-1].replace(' || exit /b 5', f' {flag} || exit /b 5')
    else:   # existing build: a quick CMake re-run; the SPU code rebuilds only when the choice changed
        lines.append(f'"{cmake}" {flag} "{fwd(BUILD)}" >nul || exit /b 5')
    if not avx2:
        say('  CPU without AVX2 (or DS_AVX2=0): building the SPU code without it')
    lines.append(f'"{ninja}" -C "{BUILD}" -j {jobs} {" ".join(targets)}')
    lines.append('exit /b %errorlevel%')
    fd, bat = tempfile.mkstemp(suffix='.bat', prefix='ds_build_')
    with os.fdopen(fd, 'w') as f:
        f.write('\r\n'.join(lines) + '\r\n')
    try:
        rc = subprocess.run(['cmd', '/d', '/c', bat]).returncode
    finally:
        os.remove(bat)
    return finish(rc, avx2, full=not targets)


def finish(rc, avx2, full=True):
    if rc == 0 and full:   # only a whole build: "BUILD.bat <target>" may leave the exe as it was
        os.makedirs(BUILT, exist_ok=True)
        for n in PATCHES:
            shutil.copyfile(os.path.join(ROOT, 'patches', n), os.path.join(BUILT, n))
    if rc == 0:
        marker = os.path.join(BUILD, 'no_avx2.txt')
        if avx2:
            if os.path.isfile(marker):
                os.remove(marker)
        else:
            with open(marker, 'w') as f:
                f.write('Built without AVX2 (setup/build.py); PLAY.bat does not require it.\n')
        say(f'\n  built {os.path.join(BUILD, "DemonsSoulsRecomp.exe")}')
    return rc


def sync_patches():
    """An update of this repo since SETUP.bat: re-apply the patches that changed (setup/patch_sync.py).
    Returns False when that needs SETUP.bat."""
    import patch_sync
    from setup import PS3RECOMP_COMMIT, lift_inputs
    if patch_sync.sync_runtime(PS3RECOMP_COMMIT) == 'redo' or patch_sync.sync_lifted(lift_inputs()) == 'relift':
        say(f'  Run {os.environ.get("DS_SETUP_NAME") or "SETUP.bat"} to bring this setup up to date (it keeps the game files).')
        return False
    return True


if __name__ == '__main__':
    a = sys.argv[1:]
    jobs = None
    if '--jobs' in a:
        i = a.index('--jobs'); jobs = a[i + 1]; del a[i:i + 2]
    if '--runtime-only' in a:   # toolchain check without the game (cross toolchain only)
        a.remove('--runtime-only')
        sys.exit(build_xwin(jobs, a, runtime_only=True))
    if not sync_patches():
        sys.exit(1)
    sys.exit(build(jobs, a))

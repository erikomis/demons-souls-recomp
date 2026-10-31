"""Build DemonsSoulsRecomp.exe (port/build_opt) with clang-cl, CMake and Ninja.

Finds the tools by itself: Visual Studio 2022 (or its Build Tools) with the C++ workload for the
Windows SDK and libraries, and clang-cl + lld-link from an LLVM install (LLVM_DIR, deps/llvm,
C:\\Program Files\\LLVM, Visual Studio's own Clang component, or PATH). CMake and Ninja come from
the Python environment SETUP.bat makes. Offers to install what is missing with winget.

The configuration is the tested one: build type "Fast" (no CMake flag preset, so the project's own
-O1 / -O2 apply) and the boot harness runner (DS_BOOT_HARNESS=ON).

usage: BUILD.bat [--jobs N] [ninja targets...]
"""
import glob, os, re, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, 'port', 'build_opt')
MIN_CLANG = 17


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
        out = subprocess.run([os.path.join(bindir, 'clang-cl.exe'), '--version'], capture_output=True,
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


def build(jobs=None, targets=()):
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
    lines.append(f'"{ninja}" -C "{BUILD}" -j {jobs} {" ".join(targets)}')
    lines.append('exit /b %errorlevel%')
    fd, bat = tempfile.mkstemp(suffix='.bat', prefix='ds_build_')
    with os.fdopen(fd, 'w') as f:
        f.write('\r\n'.join(lines) + '\r\n')
    try:
        rc = subprocess.run(['cmd', '/d', '/c', bat]).returncode
    finally:
        os.remove(bat)
    if rc == 0:
        say(f'\n  built {os.path.join(BUILD, "DemonsSoulsRecomp.exe")}')
    return rc


if __name__ == '__main__':
    a = sys.argv[1:]
    jobs = None
    if '--jobs' in a:
        i = a.index('--jobs'); jobs = a[i + 1]; del a[i:i + 2]
    sys.exit(build(jobs, a))

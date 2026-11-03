"""Checks the tools of the Linux kit (the AppImage's "selftest", and the GitHub Actions job).

Needs no disc and downloads nothing by default:
  - Python, the cryptography module, CMake, Ninja
  - clang-cl + lld-link + llvm-lib: compiles a small C file for Windows and links it into a DLL
    (no Microsoft SDK needed for that)
  - xwin, git (git apply of a small patch)
  - every Python file of setup/, tools/ and linux/ compiles

--cross-runtime [folder]: also the real thing without a disc: ps3recomp at the tested commit with
patches/ps3recomp-local.patch, the Microsoft CRT/SDK from xwin (xwin asks to accept Microsoft's license
unless XWIN_ACCEPT_LICENSE=true is set), and ps3recomp's runtime library cross-compiled
(setup/build.py --runtime-only). In a copy of this kit in [folder] (default: a temporary one).

usage: selftest.py [--cross-runtime [folder]]
"""
import os, shutil, subprocess, sys, tempfile

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(KIT, 'setup'))
import build                                                    # noqa: E402

results = []


def check(name, fn):
    try:
        detail = fn()
        results.append((True, name, detail or ''))
    except Exception as e:                                       # noqa: BLE001 -- report every failure
        results.append((False, name, f'{type(e).__name__}: {e}'))
    ok, _, detail = results[-1]
    print(f'  [{"ok" if ok else "FAIL"}] {name}: {detail}', flush=True)


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode:
        raise RuntimeError(f'{" ".join(cmd)} -> {r.returncode}\n{r.stdout}{r.stderr}')
    return (r.stdout + r.stderr).strip()


def first_line(s):
    return s.splitlines()[0] if s else ''


def python():
    import cryptography
    if sys.version_info < (3, 10):
        raise RuntimeError(f'Python {sys.version.split()[0]} is too old')
    return f'Python {sys.version.split()[0]}, cryptography {cryptography.__version__}'


def tool(name):
    def fn():
        p = build.pip_tool(name)
        if not p:
            raise RuntimeError(f'{name} not found')
        return first_line(run([p, '--version']))
    return fn


def llvm():
    found = build.find_llvm_cross()
    if not found:
        raise RuntimeError('no LLVM folder with clang-cl, lld-link and llvm-lib (DS_LLVM_DIR)')
    ver, bindir, text = found
    if ver < build.MIN_CLANG:
        raise RuntimeError(f'{text} is older than LLVM {build.MIN_CLANG}')
    exe = build.EXE
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, 't.c')
        with open(src, 'w') as f:
            f.write('__declspec(dllexport) int ds_twice(int x) { return x * 2; }\n')
        run([os.path.join(bindir, 'clang-cl' + exe), '--target=x86_64-pc-windows-msvc', '/c', '/O2', '/Zl',
             '/GS-', src, '/Fo' + os.path.join(d, 't.obj')])
        run([os.path.join(bindir, 'lld-link' + exe), '/dll', '/noentry', '/nodefaultlib', '/machine:x64',
             os.path.join(d, 't.obj'), '/out:' + os.path.join(d, 't.dll')])
        run([os.path.join(bindir, 'llvm-lib' + exe), '/out:' + os.path.join(d, 't.lib'), os.path.join(d, 't.obj')])
        with open(os.path.join(d, 't.dll'), 'rb') as f:
            if f.read(2) != b'MZ':
                raise RuntimeError('lld-link wrote no PE file')
    return f'{text} ({bindir}); compiled + linked a Windows DLL'


def xwin():
    p = build.find_xwin()
    if not p:
        raise RuntimeError('xwin not found (XWIN, PATH or deps/xwin-bin)')
    return first_line(run([p, '--version']))


def git():
    v = first_line(run(['git', '--version']))
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, 'a.txt'), 'w', newline='\n') as f:
            f.write('one\ntwo\n')
        with open(os.path.join(d, 'p.patch'), 'w', newline='\n') as f:
            f.write('--- a/a.txt\n+++ b/a.txt\n@@ -1,2 +1,2 @@\n one\n-two\n+three\n')
        run(['git', 'apply', '-p1', 'p.patch'], cwd=d, env=dict(os.environ, GIT_CEILING_DIRECTORIES=d))
        if open(os.path.join(d, 'a.txt')).read() != 'one\nthree\n':
            raise RuntimeError('git apply gave the wrong result')
    return v + ', git apply works'


def scripts():
    n = 0
    for sub in ('setup', 'tools', 'linux'):
        for dp, _, fs in os.walk(os.path.join(KIT, sub)):
            for f in fs:
                if f.endswith('.py'):
                    p = os.path.join(dp, f)
                    with open(p, 'rb') as src:
                        compile(src.read(), p, 'exec')
                    n += 1
    return f'{n} Python files compile'


def cross_runtime(folder):
    def fn():
        work = folder or tempfile.mkdtemp(prefix='ds_selftest_')
        for sub in ('setup', 'tools', 'patches', 'project', 'linux'):
            shutil.copytree(os.path.join(KIT, sub), os.path.join(work, sub), dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns('__pycache__', 'local_config.json'))
        env = dict(os.environ, DS_SETUP_NAME='selftest')
        code = ('import sys; sys.path[:0] = ["setup", "tools"]; import setup; setup.step_ps3recomp()')
        r = subprocess.run([sys.executable, '-c', code], cwd=work, env=env)
        if r.returncode:
            raise RuntimeError('ps3recomp checkout / patch failed')
        r = subprocess.run([sys.executable, os.path.join(work, 'setup', 'build.py'), '--runtime-only'],
                           cwd=work, env=env)
        if r.returncode:
            raise RuntimeError(f'runtime cross-build failed (in {work})')
        return f'ps3recomp runtime cross-compiled in {work}'
    return fn


def main():
    a = sys.argv[1:]
    print("Demon's Souls PC port -- Linux kit self-test", flush=True)
    check('python', python)
    check('cmake', tool('cmake'))
    check('ninja', tool('ninja'))
    check('llvm', llvm)
    check('xwin', xwin)
    check('git', git)
    check('scripts', scripts)
    if '--cross-runtime' in a:
        i = a.index('--cross-runtime')
        folder = a[i + 1] if i + 1 < len(a) and not a[i + 1].startswith('-') else None
        check('cross-runtime', cross_runtime(os.path.abspath(folder) if folder else None))
    bad = [n for ok, n, _ in results if not ok]
    print('\nall good' if not bad else '\nFAILED: ' + ', '.join(bad), flush=True)
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()

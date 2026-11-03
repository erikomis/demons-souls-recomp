"""CI self-test: patches/ps3recomp-local.patch goes onto a fresh ps3recomp checkout (setup step 3), and an
update from the previous version of the patch works (patch_sync.sync_runtime, what BUILD.bat / SETUP.bat
run after a pull). No game files needed. Run from a full clone (the previous version comes from git
history); it makes deps/ps3recomp next to this folder, like SETUP.bat, and refuses to touch one that
is already there (a set-up copy) unless run in CI or with --force.

    python setup/selftest_patches.py
"""
import os, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patch_sync   # noqa: E402
import setup        # noqa: E402

REL = 'patches/ps3recomp-local.patch'


def git(*a, cwd):
    r = subprocess.run(['git', *a], cwd=cwd, capture_output=True)
    if r.returncode:
        sys.exit(f'FAIL: git {" ".join(a)}: {r.stderr.decode(errors="replace")}')
    return r.stdout


def main():
    if os.path.isdir(setup.PS3RECOMP) and not os.environ.get('GITHUB_ACTIONS') and '--force' not in sys.argv:
        sys.exit(f'{setup.PS3RECOMP} exists: this test resets it (checkout -f, clean -fd, older patches) and '
                 'the next build recompiles the runtime. Run it in a fresh clone, or pass --force.')
    commit = setup.PS3RECOMP_COMMIT
    new = patch_sync._read(patch_sync.RUNTIME_PATCH)
    print('1. fresh setup (step 3)')
    if os.path.isfile(os.path.join(setup.PS3RECOMP, '.ds_patched')):
        os.remove(os.path.join(setup.PS3RECOMP, '.ds_patched'))
    setup.step_ps3recomp()
    if patch_sync._apply(setup.PS3RECOMP, patch_sync.RUNTIME_PATCH, '-R', '--check', repo=True).returncode:
        sys.exit('FAIL: after step 3 the patch is not what is applied')

    # The last three older versions made for the same ps3recomp commit (an update can skip some). One
    # made for another commit never meets this checkout: sync_runtime sets that up from scratch.
    olds = []
    hist = git('log', '--format=%H', '--', REL, cwd=setup.ROOT).decode().split()
    if not hist:
        sys.exit('FAIL: no git history for the patch (clone with full history)')
    for h in hist:
        pin = subprocess.run(['git', 'show', f'{h}:setup/setup.py'], cwd=setup.ROOT, capture_output=True).stdout
        if commit.encode() not in pin:
            continue
        c = git('show', f'{h}:{REL}', cwd=setup.ROOT)
        if c != new and c not in olds:
            olds.append(c)
        if len(olds) == 3:
            break
    if not olds:
        print('no older version for this ps3recomp commit yet: update test skipped')
        print('ok')
        return
    p = setup.PS3RECOMP
    for n, old in enumerate(olds, 1):
        print(f'{n + 1}. update from the version {n} before this one')
        git('-c', 'advice.detachedHead=false', 'checkout', '-q', '-f', commit, cwd=p)
        git('clean', '-q', '-fd', cwd=p)
        tmp = os.path.join(p, '.ds_selftest_old.patch')
        patch_sync._write(tmp, old)
        r = patch_sync._apply(p, tmp, repo=True)
        os.remove(tmp)
        if r.returncode:
            sys.exit('FAIL: that version does not apply:\n' + r.stdout + r.stderr)
        patch_sync.save_runtime_state(commit, old)
        state = patch_sync.sync_runtime(commit)
        if state != 'updated':
            sys.exit(f'FAIL: sync_runtime returned {state!r}, expected updated')
        if patch_sync._apply(p, patch_sync.RUNTIME_PATCH, '-R', '--check', repo=True).returncode:
            sys.exit('FAIL: after the update the new patch is not what is applied')
    print('ok')


if __name__ == '__main__':
    main()

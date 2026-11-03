"""Bring an existing setup up to date with this checkout's patches (after a git pull or a new ZIP).

SETUP.bat applies patches/ps3recomp-local.patch (step 3) and patches/lifted-code.patch (step 5)
once. Before, a later SETUP.bat skipped both steps ("already done") and BUILD.bat only compiled, so
an update never reached the game. Now both re-apply a patch that changed since it was applied:
the old version is taken out (the saved copy of what was applied, or for older setups the version
from this checkout's git history that matches what is on disk) and the new one put in. Only files
the two patches name are touched; files whose content ends up the same get their old timestamps
back, so the build recompiles only what changed. When it cannot tell what is on disk it changes
nothing and SETUP.bat sets that part up from scratch.
"""
import hashlib, os, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = os.path.join(ROOT, 'port')
PS3RECOMP = os.path.join(ROOT, 'deps', 'ps3recomp')
LIFTED_PATCH = os.path.join(ROOT, 'patches', 'lifted-code.patch')
RUNTIME_PATCH = os.path.join(ROOT, 'patches', 'ps3recomp-local.patch')


def say(msg=''):
    print(msg, flush=True)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _read(p):
    with open(p, 'rb') as f:
        return f.read()


def _write(p, data):
    with open(p, 'wb') as f:
        f.write(data)


def _paths(patch):
    """Files a unified diff touches (from its ---/+++ lines), relative to -p1."""
    out = set()
    for line in patch.split(b'\n'):
        if line.startswith((b'--- ', b'+++ ')):
            p = line[4:].split(b'\t')[0].strip()
            if p != b'/dev/null' and p[:2] in (b'a/', b'b/'):
                out.add(p[2:].decode('utf-8', 'replace'))
    return out


def _changes(patch):
    """(file, changed line) pairs: the + and - lines, not the context, which shifts between versions."""
    out, path = set(), None
    for line in patch.replace(b'\r\n', b'\n').split(b'\n'):
        if line.startswith(b'+++ '):
            path = line[4:].split(b'\t')[0].strip()
        elif line.startswith(b'--- ') or line.startswith(b'diff '):
            continue
        elif line[:1] in (b'+', b'-'):
            out.add((path, line))
    return out


def _pick(cands, check):
    """The version on disk among candidate patches: every one whose reverse applies cleanly, and of
    those the one whose changes contain all the others' (a later version that dropped a change also
    reverses cleanly). None when nothing fits or it is ambiguous."""
    ok, seen = [], set()
    for c in cands:
        if _sha(c) not in seen:
            seen.add(_sha(c))
            if check(c):
                ok.append(c)
    if len(ok) <= 1:
        return ok[0] if ok else None
    hs = [_changes(c) for c in ok]
    for c, h in zip(ok, hs):
        if all(o <= h for o in hs):
            return c
    return None


def _snapshot(base, paths):
    snap = {}
    for p in paths:
        f = os.path.join(base, *p.split('/'))
        if os.path.isfile(f):
            st = os.stat(f)
            snap[p] = (_sha(_read(f)), st.st_atime_ns, st.st_mtime_ns)
    return snap


def _restore_times(base, snap, paths):
    """Old timestamps back on files whose content did not change; returns the changed ones."""
    changed = []
    for p in sorted(paths):
        f = os.path.join(base, *p.split('/'))
        now = _sha(_read(f)) if os.path.isfile(f) else None
        old = snap.get(p)
        if old and now == old[0]:
            os.utime(f, ns=(old[1], old[2]))
        elif old or now:
            changed.append(p)
    return changed


def _apply(cwd, patch_file, *flags, repo=False):
    """git apply in cwd. Outside a repository (port/) git must not find this checkout above it, or
    it would take the patch's paths as relative to the checkout's top."""
    env = dict(os.environ)
    if not repo:
        env['GIT_CEILING_DIRECTORIES'] = os.path.dirname(os.path.abspath(cwd))
    return subprocess.run(['git', 'apply', '--whitespace=nowarn', '-p1', *flags, patch_file], cwd=cwd,
                          capture_output=True, text=True, env=env)


def _history(rel):
    """Earlier versions of a file of this checkout, newest first ([] for a ZIP download)."""
    r = subprocess.run(['git', 'log', '--format=%H', '--', rel], cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        return []
    out = []
    for h in r.stdout.split()[:200]:
        s = subprocess.run(['git', 'show', f'{h}:{rel}'], cwd=ROOT, capture_output=True)
        if s.returncode == 0:
            out.append(s.stdout)
    return out


def _listing(changed):
    return ', '.join(os.path.basename(p) for p in changed[:8]) + (' ...' if len(changed) > 8 else '')


# --- recompiled code (port/) -------------------------------------------------------------------

def lifted_mark_text(patch, inputs):
    """inputs: what produced the recompiled code (setup.lift_inputs()); a change there needs a relift."""
    return 'inputs ' + inputs + '\nsha256 ' + _sha(patch) + '\n'


def save_lifted_state(patch, inputs):
    """After step 5 or an update: remember what was applied."""
    _write(os.path.join(PORT, '.lifted.patch'), patch)
    with open(os.path.join(PORT, '.lifted'), 'w') as f:
        f.write(lifted_mark_text(patch, inputs))


def sync_lifted(inputs):
    """Returns 'none' (not set up yet), 'current', 'updated' or 'relift' (the recompiler or its
    settings changed, or it could not tell what is on disk: the caller recompiles from scratch)."""
    mark = os.path.join(PORT, '.lifted')
    if not os.path.isfile(mark):
        return 'none'
    new = _read(LIFTED_PATCH)
    with open(mark) as f:
        text = f.read()
    if text.startswith('inputs ') and not text.startswith('inputs ' + inputs + '\n'):
        say('  the recompiler or its settings changed: recompiling the game code again (a few minutes)')
        return 'relift'
    if text == lifted_mark_text(new, inputs):
        return 'current'
    say('  patches/lifted-code.patch changed since it was applied: updating the recompiled code')
    saved = os.path.join(PORT, '.lifted.patch')
    tmp = os.path.join(PORT, '.lifted.old.patch')
    try:
        def reverses(c):
            _write(tmp, c)
            return _apply(PORT, tmp, '-R', '--check').returncode == 0
        old = _pick([_read(saved)], reverses) if os.path.isfile(saved) else None
        if old is None:
            old = _pick(_history('patches/lifted-code.patch'), reverses)
        if old is not None:
            _write(tmp, old)
            paths = _paths(old) | _paths(new)
            snap = _snapshot(PORT, paths)
            r = _apply(PORT, tmp, '-R')
            if r.returncode == 0:
                r = _apply(PORT, LIFTED_PATCH)
                if r.returncode == 0:
                    changed = _restore_times(PORT, snap, paths)
                    save_lifted_state(new, inputs)
                    say(f'  {len(changed)} recompiled file(s) changed: {_listing(changed)}')
                    return 'updated'
                _apply(PORT, tmp)   # put the old one back
                _restore_times(PORT, snap, paths)
            say('  the new patch does not fit the recompiled code on disk:\n' + r.stdout + r.stderr)
    finally:
        if os.path.isfile(tmp):
            os.remove(tmp)
    say('  could not update in place: recompiling the game code again (a few minutes)')
    return 'relift'


# --- ps3recomp runtime (deps/ps3recomp) -------------------------------------------------------

def runtime_mark_text(commit, patch):
    return commit + '\n' + 'sha256 ' + _sha(patch) + '\n'


def save_runtime_state(commit, patch):
    """After step 3 or an update: remember what was applied."""
    _write(os.path.join(PS3RECOMP, '.ds_patched.patch'), patch)
    with open(os.path.join(PS3RECOMP, '.ds_patched'), 'w') as f:
        f.write(runtime_mark_text(commit, patch))


def sync_runtime(commit):
    """Returns 'none' (not set up yet), 'current', 'updated' or 'redo' (the caller sets it up again)."""
    mark = os.path.join(PS3RECOMP, '.ds_patched')
    if not os.path.isfile(mark):
        return 'none'
    new = _read(RUNTIME_PATCH)
    with open(mark) as f:
        if f.read() == runtime_mark_text(commit, new):
            return 'current'
    say('  patches/ps3recomp-local.patch changed since it was applied: updating the runtime')

    def git(*a):
        return subprocess.run(['git', *a], cwd=PS3RECOMP, capture_output=True, text=True)
    head = git('rev-parse', 'HEAD')
    if head.returncode or head.stdout.strip() != commit:
        return 'redo'
    saved = os.path.join(PS3RECOMP, '.ds_patched.patch')
    tmp = os.path.join(PS3RECOMP, '.ds_patched.old.patch')
    try:
        def reverses(c):
            _write(tmp, c)
            return _apply(PS3RECOMP, tmp, '-R', '--check', repo=True).returncode == 0
        old = _pick([_read(saved)], reverses) if os.path.isfile(saved) else None
        if old is None:
            old = _pick(_history('patches/ps3recomp-local.patch'), reverses)
    finally:
        if os.path.isfile(tmp):
            os.remove(tmp)
    if old is None:
        say('  could not tell which version is applied')
        return 'redo'
    # Only what the two patches name goes back to the commit; anything else in the checkout stays.
    paths = _paths(old) | _paths(new)
    in_commit = set(git('ls-tree', '-r', '--name-only', '-z', commit).stdout.split('\0'))
    snap = _snapshot(PS3RECOMP, paths)
    back = sorted(p for p in paths if p in in_commit)
    for i in range(0, len(back), 100):
        if git('checkout', '-q', '-f', commit, '--', *back[i:i + 100]).returncode:
            return 'redo'
    for p in paths - in_commit:   # files the old patch created
        f = os.path.join(PS3RECOMP, *p.split('/'))
        if os.path.isfile(f):
            os.remove(f)
    r = _apply(PS3RECOMP, RUNTIME_PATCH, repo=True)
    if r.returncode:
        say('  the new patch did not apply:\n' + r.stdout + r.stderr)
        return 'redo'
    changed = _restore_times(PS3RECOMP, snap, paths)
    save_runtime_state(commit, new)
    say(f'  {len(changed)} runtime file(s) changed: {_listing(changed)}')
    return 'updated'

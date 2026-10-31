"""Install the "Demon's Souls PC Remaster" mod (fromsoftserve, Nexus Mods mod 106) into game_remaster/.

usage: python tools/install_remaster.py <mod.zip> [--apply]

game_remaster/ is made as a copy of game/ out of hard links (no extra disk space) the first time.
Without --apply only reports. Each mod file is matched to the game's existing path case-insensitively
(the mod uses lowercase folder names); an existing file is REMOVED first (it is a hard link shared with
game/, so writing into it would change the normal game too), then the mod's copy is written.
Replaced originals are listed in game_remaster/REMASTER_INSTALLED.txt. Play with PLAY_REMASTER.bat;
to remove the mod delete game_remaster/. Download the mod yourself from Nexus Mods."""
import os, shutil, sys, zipfile

zip_path = sys.argv[1]
apply = '--apply' in sys.argv
base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
root = os.path.join(base, 'game_remaster', 'PS3_GAME', 'USRDIR')
orig_root = os.path.join(base, 'game', 'PS3_GAME', 'USRDIR')
if not os.path.isdir(orig_root):
    sys.exit('no game/ yet -- run SETUP.bat first')
if apply and not os.path.isdir(root):
    print('making game_remaster/ (hard links to game/)')
    src = os.path.join(base, 'game')
    for d, _, fs in os.walk(src):
        t = os.path.join(base, 'game_remaster', os.path.relpath(d, src))
        os.makedirs(t, exist_ok=True)
        for f in fs:
            try:
                os.link(os.path.join(d, f), os.path.join(t, f))
            except OSError:
                shutil.copy2(os.path.join(d, f), os.path.join(t, f))
if not os.path.isdir(root):
    root = orig_root          # report-only run before the copy exists: same tree

idx = {}
for d, ds, fs in os.walk(root):
    for f in fs:
        p = os.path.relpath(os.path.join(d, f), root).replace(os.sep, '/')
        idx[p.lower()] = p
dir_idx = {}
for d, ds, fs in os.walk(root):
    for x in ds:
        p = os.path.relpath(os.path.join(d, x), root).replace(os.sep, '/')
        dir_idx[p.lower()] = p

z = zipfile.ZipFile(zip_path)
bad = [i.filename for i in z.infolist()
       if i.filename.startswith(('/', '\\')) or '..' in i.filename.replace('\\', '/').split('/') or ':' in i.filename]
if bad:
    sys.exit('unsafe paths in archive: %r' % bad[:5])
files = [i for i in z.infolist() if not i.is_dir()]


def target(name):
    """Existing path with the game's own capitalisation, else new path under existing dirs where possible."""
    key = name.lower()
    if key in idx:
        return idx[key], True
    parts = name.split('/')
    for n in range(len(parts) - 1, 0, -1):
        d = '/'.join(parts[:n]).lower()
        if d in dir_idx:
            return dir_idx[d] + '/' + '/'.join(parts[n:]), False
    return name, False


rep = []; new = []
for i in files:
    t, exists = target(i.filename)
    (rep if exists else new).append((i, t))
print('files %d: replace %d, new %d' % (len(files), len(rep), len(new)))
for i, t in new[:60]:
    print('  new', t, i.file_size)

if apply:
    log = []
    for i, t in rep + new:
        dest = os.path.join(root, t.replace('/', os.sep))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.exists(dest):
            os.remove(dest)          # break the hard link first
            log.append('replaced ' + t)
        else:
            log.append('added ' + t)
        with z.open(i) as src, open(dest, 'wb') as out:
            while True:
                buf = src.read(1 << 20)
                if not buf: break
                out.write(buf)
    with open(os.path.join(base, 'game_remaster', 'REMASTER_INSTALLED.txt'), 'w') as f:
        f.write('Demon\'s Souls PC Remaster (fromsoftserve, Nexus mod 106) installed from\n%s\n\n' % os.path.basename(zip_path))
        f.write('\n'.join(log) + '\n')
    # The normal game must be untouched: every replaced file there still differs from the mod copy.
    same = 0
    for i, t in rep:
        a = os.stat(os.path.join(root, t.replace('/', os.sep))); b = os.stat(os.path.join(orig_root, t.replace('/', os.sep)))
        same += (a.st_ino == b.st_ino)
    print('applied; replaced files still hard-linked to the normal game: %d (must be 0)' % same)

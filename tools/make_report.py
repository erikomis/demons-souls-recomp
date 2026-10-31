"""Pack a play session into one zip to attach to a GitHub issue (REPORT.bat runs this).

usage: python tools/make_report.py [perf\\<run> folder] [--no-open]   (default: the newest recording)

The zip (perf\\<run>\\report_<run>.zip) holds:
  report.txt    the summary tools/perf_report.py prints for the recording (hitches, F8 marks, causes)
  perf.txt      the recording itself (only the minutes around your F8 marks if the whole one is too big)
  system.txt    Windows version, CPU, RAM, GPU + driver, monitor refresh, this port's commit
  log_tail.txt  the last 400 lines of logs\\last_run_err.txt when that log is from the same run
Your Windows user name is replaced by %USERNAME% in everything, so the zip has no personal paths.
"""
import ctypes, glob, io, os, platform, re, subprocess, sys, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ISSUES = 'https://github.com/timboat/demons-souls-recomp/issues/new/choose'
LIMIT = 24 * 1024 * 1024          # GitHub takes attachments up to 25 MB
KEEP_AROUND_MARK_S = 90            # seconds of recording kept before / after each F8 mark when trimming


def scrub(text, names=True):
    home = os.path.expanduser('~')
    user = os.environ.get('USERNAME') or os.path.basename(home)
    for h in {home, home.replace('\\', '/')}:
        text = re.sub(re.escape(h), '%USERPROFILE%', text, flags=re.I)
    if names and user and len(user) > 2:
        text = re.sub(r'(?i)(?<![A-Za-z0-9])' + re.escape(user) + r'(?![A-Za-z0-9])', '%USERNAME%', text)
    return text


def ps(cmd):
    try:
        return subprocess.run(['powershell', '-NoProfile', '-Command', cmd], capture_output=True, text=True,
                              timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ''


def system_info(perf_text):
    L = []
    L.append('Windows: %s %s (%s)' % (platform.system(), platform.version(), platform.machine()))
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'HARDWARE\DESCRIPTION\System\CentralProcessor\0')
        L.append('CPU: %s, %d logical cores' % (winreg.QueryValueEx(k, 'ProcessorNameString')[0].strip(),
                                                os.cpu_count() or 0))
    except OSError:
        L.append('CPU: %s, %d logical cores' % (platform.processor(), os.cpu_count() or 0))

    class MS(ctypes.Structure):
        _fields_ = [('len', ctypes.c_ulong), ('load', ctypes.c_ulong), ('total', ctypes.c_ulonglong),
                    ('avail', ctypes.c_ulonglong), ('a', ctypes.c_ulonglong), ('b', ctypes.c_ulonglong),
                    ('c', ctypes.c_ulonglong), ('d', ctypes.c_ulonglong), ('e', ctypes.c_ulonglong)]
    m = MS(); m.len = ctypes.sizeof(MS)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
        L.append('RAM: %.1f GB' % (m.total / 2 ** 30))
    gpus = ps('Get-CimInstance Win32_VideoController | ForEach-Object { "$($_.Name) | driver $($_.DriverVersion)'
              ' | $($_.CurrentHorizontalResolution)x$($_.CurrentVerticalResolution) @ $($_.CurrentRefreshRate) Hz" }')
    for g in gpus.splitlines():
        L.append('GPU: ' + g.strip())
    try:
        c = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=ROOT, capture_output=True, text=True)
        L.append('port commit: ' + (c.stdout.strip() or 'unknown (not a git checkout)'))
    except OSError:
        L.append('port commit: unknown (git not found)')
    m = re.search(r'^# \d+ info (.*)$', perf_text, re.M)
    if m:
        L.append('settings: ' + m.group(1))
    return '\n'.join(L) + '\n'


def trim(perf_text):
    """Keep the lines within KEEP_AROUND_MARK_S of an F8 mark (plus the settings line)."""
    timed = []
    for ln in perf_text.splitlines(keepends=True):
        p = ln.split()
        try:
            timed.append((int(p[1]) if p[0] == '#' else int(p[0]), ln))
        except (ValueError, IndexError):
            pass
    marks = [t for t, ln in timed if ln.split()[2:3] == ['mark']]
    if marks:
        w = KEEP_AROUND_MARK_S * 10 ** 6
        win = [(t - w, t + w) for t in marks]
    else:                                          # no marks: keep the last 20 minutes
        last = max(t for t, _ in timed)
        win = [(last - 20 * 60 * 10 ** 6, last)]
    out = [ln for t, ln in timed if ln.split()[2:3] == ['info'] or any(a <= t <= b for a, b in win)]
    return ''.join(out), len(marks)


def main():
    args = [a for a in sys.argv[1:] if a != '--no-open']
    if args:
        run = os.path.abspath(args[0])
    else:
        runs = sorted(d for d in glob.glob(os.path.join(ROOT, 'perf', '*')) if os.path.isfile(os.path.join(d, 'perf.txt')))
        if not runs:
            sys.exit('No recordings yet: play with PLAY.bat (it records every run), press F8 at a stutter, then run this again.')
        run = runs[-1]
    perf = os.path.join(run, 'perf.txt')
    name = os.path.basename(run.rstrip('\\/'))
    print('Packing the recording from %s ...' % name)
    perf_text = scrub(open(perf, errors='replace').read(), names=False)

    r = subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'perf_report.py'), perf],
                       capture_output=True, text=True)
    report = scrub(r.stdout + (('\n' + r.stderr) if r.stderr.strip() else ''))

    log = os.path.join(ROOT, 'logs', 'last_run_err.txt')
    tail = ''
    if os.path.isfile(log) and os.path.getmtime(log) >= os.path.getmtime(run) - 5:
        with open(log, 'rb') as f:
            f.seek(0, 2); n = f.tell(); f.seek(max(0, n - 4 * 1024 * 1024))
            data = f.read().decode('utf-8', 'replace').splitlines()[-400:]
        tail = scrub('\n'.join(data) + '\n')

    out = os.path.join(run, 'report_%s.zip' % name)

    def write(perf_part, note):
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            z.writestr('report.txt', note + report)
            z.writestr('perf.txt', perf_part)
            z.writestr('system.txt', system_info(perf_text))
            if tail:
                z.writestr('log_tail.txt', tail)
    write(perf_text, '')
    if os.path.getsize(out) > LIMIT:
        part, nm = trim(perf_text)
        write(part, '(perf.txt trimmed to %s to fit GitHub\'s 25 MB limit)\n\n' % (
            '%d s around each of the %d F8 marks' % (KEEP_AROUND_MARK_S, nm) if nm else 'the last 20 minutes'))
    print()
    print(report.split('\n\n')[0] if report else '(no summary)')
    print()
    print('Made %s (%.1f MB).' % (out, os.path.getsize(out) / 2 ** 20))
    print('Open an issue at %s and drag that zip into it.' % ISSUES)
    print('Say where you were in the game and what you saw at each F8 press.')
    if '--no-open' in sys.argv:
        return
    try:
        subprocess.run(['explorer', '/select,', out])
        os.startfile(ISSUES)
    except OSError:
        pass


if __name__ == '__main__':
    main()

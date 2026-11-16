"""Pack a play session into one zip to attach to a GitHub issue (REPORT.bat runs this).

usage: python tools/make_report.py [perf\\<run> folder] [--no-open]   (default: the newest recording)

The zip (perf\\<run>\\report_<run>.zip) holds:
  report.txt    the summary tools/perf_report.py prints for the recording (hitches, F8 marks, causes)
  perf.txt      the recording itself (only the minutes around your F8 marks if the whole one is too big)
  system.txt    Windows version, CPU, RAM, GPU + driver, monitor refresh, this port's commit
  log_head.txt / log_tail.txt  the first / last 400 lines of logs\\last_run_err.txt, out_head.txt / out_tail.txt
                the same of logs\\last_run_out.txt (the console log: decoders, save data, start-up), when they
                are from the same run; log_notable.txt their error / failure / warning lines
  crash.txt     Windows' own record of a crash in this run (event log, Windows Error Reporting), if any
Your Windows user name is replaced by %USERNAME% in everything, so the zip has no personal paths.
"""
import ctypes, glob, io, os, platform, re, subprocess, sys, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ISSUES = 'https://github.com/timboat/demons-souls-recomp/issues/new/choose'
LIMIT = 24 * 1024 * 1024          # GitHub takes attachments up to 25 MB
KEEP_AROUND_MARK_S = 90            # seconds of recording kept before / after each F8 mark when trimming
# error-looking log lines for log_notable.txt; the routine per-wait / per-frame status lines (which carry counters
# such as "decodefail=0" and "timeout=0") are left out
NOTABLE = re.compile(r'\berror|\bfail(ed|ure|s)?\b|not found|missing|exception|crash|abort|null-read|exit-chain'
                     r'|\bwarn|refus|reject|cannot|could not|timed out|\bstall|unsupported(?!=)|unknown'
                     # sound and pad lines that settle GitHub #47 / #48 (NOTES fixes 204, 205)
                     r'|^\[cellAtrac\]|ran dry|^\[audio-rate\]|^\[cellSail\]|^\[cellPad\] port 0 <-'
                     r'|^\[live-draw\] texture colour flags', re.I)
NOT_NOTABLE = re.compile(r'^\[(WAIT|evt|live-draw\] frame)')


def short_path(p):
    """The 8.3 form of a path (C:\\Users\\JEANPI~1), which Windows' own records can use; '' if there is none."""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = ctypes.windll.kernel32.GetShortPathNameW(p, buf, 1024)
        return buf.value if 0 < n < 1024 and buf.value.lower() != p.lower() else ''
    except (AttributeError, OSError):
        return ''


def scrub(text, names=True):
    home = os.path.expanduser('~')
    user = os.environ.get('USERNAME') or os.path.basename(home)
    homes = {home, home.replace('\\', '/')}
    sh = short_path(home)
    if sh:
        homes |= {sh, sh.replace('\\', '/')}
    for h in sorted(homes, key=len, reverse=True):
        text = re.sub(re.escape(h), '%USERPROFILE%', text, flags=re.I)
    if names and user and len(user) > 2:
        text = re.sub(r'(?i)(?<![A-Za-z0-9])' + re.escape(user) + r'(?![A-Za-z0-9])', '%USERNAME%', text)
    return text


def ps(cmd):
    """PowerShell's output. It comes back base64-encoded UTF-8: Windows PowerShell writes a pipe in the console code
    page, which garbled (or, decoded strictly, crashed on) localised event text on non-English Windows."""
    import base64
    try:
        r = subprocess.run(['powershell', '-NoProfile', '-Command',
                            '[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes((& { %s } | Out-String -Width 4096)))'
                            % cmd], capture_output=True, timeout=30)
        return base64.b64decode((r.stdout or b'').strip() or b'').decode('utf-8', 'replace').strip()
    except (OSError, subprocess.SubprocessError, ValueError):
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


def run_start(run):
    """The run's start (local time) from its folder name (2026-11-16_08-42-04). The launcher writes that name in
    the user's calendar, which is not always Gregorian (Thai, Hijri), so a name more than two days away from the
    folder's creation time is not trusted and the creation time is used instead."""
    import datetime
    made = os.path.getctime(run)
    try:
        t = datetime.datetime.strptime(os.path.basename(run.rstrip('\\/'))[:19], '%Y-%m-%d_%H-%M-%S').timestamp()
    except (ValueError, OSError, OverflowError):
        return made
    return t if abs(t - made) < 2 * 86400 else made


WER_KEEP = re.compile(r'(EventTime|EventType|AppPath|FriendlyEventName|Sig\[\d+\]\.(Name|Value)'
                      r'|DynamicSig\[\d+\]\.(Name|Value))=')


def event_text(msg):
    """An event message without the WER file lists ('Attached files:' up to 'Analysis symbol:'): those paths can be
    in 8.3 form under the user's folder and say nothing about the crash."""
    out, skip = [], False
    for ln in msg.splitlines():
        if re.match(r'\s*(Attached files|These files may be available here)\s*:', ln):
            skip = True
            continue
        if skip and re.match(r'\s*Analysis symbol\s*:', ln):
            skip = False
        if not skip:
            out.append(ln)
    return '\n'.join(out)


def crash_records(start, end):
    """Windows' own record of how the game ended (GitHub #50). A crash Windows handles itself (heap corruption,
    a fast-fail) skips the game's crash filter, so the logs just stop; the Application event log (no admin
    needed) and the Windows Error Reporting folders keep the exception code and the faulting module. Only
    DemonsSoulsRecomp.exe entries between this run's start and a few minutes after its last log line."""
    import datetime

    def when(t):
        return datetime.datetime.fromtimestamp(t).strftime('%Y-%m-%dT%H:%M:%S')
    L = []
    # The exe name is matched in the event's insertion strings too: Message is empty when Windows cannot load
    # the provider's (localised) text.
    ev = ps("Get-WinEvent -FilterHashtable @{LogName='Application'; Id=1000,1001,1002; StartTime=[datetime]'%s';"
            " EndTime=[datetime]'%s'} -ErrorAction SilentlyContinue | Where-Object {"
            " ($_.Properties | ForEach-Object { [string]$_.Value }) -match 'DemonsSoulsRecomp'"
            " -or $_.Message -match 'DemonsSoulsRecomp' } | Select-Object -First 6 | ForEach-Object {"
            " '--- ' + $_.TimeCreated.ToString('s') + ' event ' + $_.Id + ' (' + $_.ProviderName + ')';"
            " if ($_.Message) { $_.Message } else { ($_.Properties | ForEach-Object { [string]$_.Value }) -join ' | ' }"
            " } | Out-String -Width 4096" % (when(start - 60), when(end)))
    if ev:
        L += ['Windows event log (Application):', event_text(ev)]
    found = []
    for base in (os.environ.get('ProgramData') or r'C:\ProgramData', os.environ.get('LOCALAPPDATA') or ''):
        if not base:
            continue
        for sub in ('ReportArchive', 'ReportQueue'):
            for d in glob.glob(os.path.join(base, 'Microsoft', 'Windows', 'WER', sub, '*DemonsSoulsRec*')):
                f = os.path.join(d, 'Report.wer')
                try:
                    if start - 60 <= os.path.getmtime(f) <= end:
                        found.append((os.path.getmtime(f), f))
                except OSError:
                    pass
    for _, f in sorted(found)[-3:]:
        try:
            raw = open(f, 'rb').read()
        except OSError:
            continue
        utf16 = raw[:2] in (b'\xff\xfe', b'\xfe\xff') or raw[1:2] == b'\x00'
        text = raw.decode('utf-16' if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else 'utf-16-le', 'replace') if utf16 \
            else raw.decode('utf-8', 'replace')
        L.append('--- Windows Error Reporting: ' + os.path.basename(os.path.dirname(f)))
        L += [ln for ln in text.splitlines() if WER_KEEP.match(ln)]
    if not L:
        L.append('No Windows crash record for DemonsSoulsRecomp.exe during this run.')
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

    logs = {}   # name in the zip -> text
    notable = []
    for src, tag in (('last_run_err.txt', 'log'), ('last_run_out.txt', 'out')):
        p = os.path.join(ROOT, 'logs', src)
        if not (os.path.isfile(p) and os.path.getmtime(p) >= os.path.getmtime(run) - 5):
            continue
        with open(p, 'rb') as f:
            head = f.read(4 * 1024 * 1024).decode('utf-8', 'replace').splitlines()
            f.seek(0, 2); n = f.tell(); f.seek(max(0, n - 4 * 1024 * 1024))
            tail_lines = f.read().decode('utf-8', 'replace').splitlines()
        logs[tag + '_head.txt'] = scrub('\n'.join(head[:400]) + '\n')
        logs[tag + '_tail.txt'] = scrub('\n'.join(tail_lines[-400:]) + '\n')
        # A black screen or an early stop is usually explained near the start; the error lines from both ends
        # (deduplicated, in order) say what went wrong without the full log.
        seen = set()
        for line in head + tail_lines:
            if NOTABLE.search(line) and not NOT_NOTABLE.match(line) and line not in seen:
                seen.add(line)
                notable.append('%s: %s' % (src, line))
    if notable:
        logs['log_notable.txt'] = scrub('\n'.join(notable[:500]) + '\n')

    crash = scrub(crash_records(run_start(run), os.path.getmtime(perf) + 300))
    out = os.path.join(run, 'report_%s.zip' % name)

    def write(perf_part, note):
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            z.writestr('report.txt', note + report)
            z.writestr('perf.txt', perf_part)
            z.writestr('system.txt', system_info(perf_text))
            z.writestr('crash.txt', crash)
            for k, v in logs.items():
                z.writestr(k, v)
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

"""Stutter report for a recorded run (PLAY.bat records every run) (NOTES fix 46).

usage: perf_report.py [perf.txt | run folder]   (default: the newest perf\\<run>)
       options: --from SEC --to SEC (seconds from the start of the log), --top N

The log (LD_PRESENT_LOG + DES_PERF) has two kinds of lines, all on one microsecond clock:
  <us> <frame> <pace us> <Present us> <gpu wait us> <last present> <stat present> <stat vblank> <sync vblank> <render cpu us> [<draws>]
  # <us> <kind> ...   kind = info | step <s> <rx> <ry> <pad src> <polls> <mdx> <mdy> <cpu us> | mark <n>
                              | pso <vs ms> <ps ms> <create ms> | read <sync|aio> <ms> <bytes> <path>
                              | psof <pipelines> <ms> <disk ms>  (pipeline builds on the drain thread in a frame; fix 62)
                              | psow <ms> <built here>  (a must-draw waited for a new shader; fix 62)
                              | psoa <vs> <ps> <create> <ms to ready> <draws skipped>  (built on a worker: no stall)
                              | texc <textures created> <ms>  (texture creation in a frame; fix 62)
                              | pos <area>,<block> <x> <y> <z>  (the player, once a second + with each mark;
                                fix 57. Two logs from 2026-11-01 01:00 have "<mcp AA,BB> x y z <block id>")
                              | thr <process %> <thread>=<%> ...  (busiest threads, % of a core, 1/s; fix 58)
What it prints: the display cadence (how many monitor refreshes each frame stayed up), every
hitch (a frame shown longer than the usual cadence, or a late present / step) with what happened
in that frame (shader compiles, slow reads, a late game step, a long Present), the F8 marks with
the hitches just before each, and how the camera stick was driven.
"""
import collections, glob, os, statistics, sys


# Map areas (map/mAA_*): the event scripts' world starts (NOTES fix 39) + the Nexus and the tutorial.
AREAS = {'1': ' (Nexus)', '2': ' (Boletarian Palace)', '3': ' (Shrine of Storms)', '4': ' (Tower of Latria)',
         '5': ' (Valley of Defilement)', '6': ' (Stonefang Tunnel)', '8': ' (tutorial)'}


def load(path):
    pres, steps, notes = [], [], []
    with open(path, errors='replace') as f:
        for line in f:
            p = line.split()
            if not p:
                continue
            if p[0] == '#':
                if len(p) < 3:
                    continue
                t, kind = int(p[1]), p[2]
                if kind == 'step' and len(p) >= 10:
                    steps.append((t, float(p[3]), int(p[4]), int(p[5]), int(p[6]), int(p[7]), int(p[8]), int(p[9]),
                                  int(p[10]) if len(p) > 10 else -1))
                else:
                    notes.append((t, kind, p[3:]))
            elif len(p) >= 9:
                try:
                    v = [int(x) for x in p[:11]]
                    pres.append(tuple(v + [-1] * (11 - len(v))))
                except ValueError:
                    pass
    return pres, steps, notes


def main():
    args = sys.argv[1:]
    opt = {'--from': None, '--to': None, '--top': '25'}
    rest = []
    i = 0
    while i < len(args):
        if args[i] in opt and i + 1 < len(args):
            opt[args[i]] = args[i + 1]; i += 2
        else:
            rest.append(args[i]); i += 1
    here = os.path.dirname(os.path.abspath(__file__))
    path = rest[0] if rest else None
    if not path:
        runs = sorted(glob.glob(os.path.join(here, '..', 'perf', '*', 'perf.txt')))
        if not runs:
            sys.exit('no recordings in perf\\ yet (PLAY.bat records every run)')
        path = runs[-1]
    if os.path.isdir(path):
        path = os.path.join(path, 'perf.txt')
    pres, steps, notes = load(path)
    if len(pres) < 10:
        sys.exit('%s: only %d frames logged' % (path, len(pres)))
    t0 = min([pres[0][0]] + [s[0] for s in steps[:1]] + [n[0] for n in notes[:1]])
    if opt['--from'] or opt['--to']:
        a = t0 + float(opt['--from'] or 0) * 1e6
        b = t0 + float(opt['--to']) * 1e6 if opt['--to'] else 1 << 62
        pres = [r for r in pres if a <= r[0] <= b]
        steps = [s for s in steps if a <= s[0] <= b]
        notes = [n for n in notes if a <= n[0] <= b]
    sec = lambda t: (t - t0) / 1e6
    top = int(opt['--top'])

    print('log %s' % path)
    for n in notes:
        if n[1] == 'info':
            print('settings:', ' '.join(n[2]))
            break
    span = (pres[-1][0] - pres[0][0]) / 1e6
    print('%.0f s logged (%.1f min), %d frames = %.1f fps average' % (span, span / 60, len(pres), len(pres) / span))

    # Display refresh from the vblank counter, then on-screen time of every present that the
    # frame statistics caught (present count -> vblank it first appeared on).
    sync = [r for r in pres if r[8]]
    hz = (sync[-1][8] - sync[0][8]) / ((sync[-1][0] - sync[0][0]) / 1e6) if len(sync) > 1 else 0
    shown = {}
    for r in pres:
        if r[6]:
            shown.setdefault(r[6], r[7])
    ks = sorted(shown)
    up = {}   # present count -> refreshes on screen
    for a, b in zip(ks, ks[1:]):
        if b == a + 1:
            up[a] = shown[b] - shown[a]
    cad = collections.Counter(up.values())
    n_up = sum(cad.values())
    usual = cad.most_common(1)[0][0] if cad else 0
    if n_up:
        print('display %.2f Hz; refreshes each frame stayed on screen: %s' % (
            hz, ', '.join('%d: %.2f%%' % (k, 100.0 * cad[k] / n_up) for k in sorted(cad))))
    else:
        print('display %.2f Hz; no frame statistics (windowed / not flip model?)' % hz)

    # Present / step intervals.
    piv = [b[0] - a[0] for a, b in zip(pres, pres[1:])]
    med_p = statistics.median(piv)
    print('present interval: median %.1f ms, 99th pct %.1f ms, worst %.1f ms' % (
        med_p / 1000, sorted(piv)[int(len(piv) * 0.99)] / 1000, max(piv) / 1000))
    med_s = 0
    if len(steps) > 10:
        siv = [b[0] - a[0] for a, b in zip(steps, steps[1:])]
        med_s = statistics.median(siv)
        sspan = (steps[-1][0] - steps[0][0]) / 1e6
        print('game steps: %.1f /s, game time %.3f s per real s; step interval median %.1f ms, 99th pct %.1f ms, worst %.1f ms' % (
            len(steps) / sspan, sum(s[1] for s in steps) / sspan, med_s / 1000,
            sorted(siv)[int(len(siv) * 0.99)] / 1000, max(siv) / 1000))

    # Repeated frames, by flip: each present shows the game's latest flip request before it. The same
    # flip request shown twice is the double present of NOTES fix 47 (~1.3 a second before it); a flip
    # request with no game step since the previous shown one is the game itself repeating a picture.
    # (Comparing presents with steps directly miscounts: a step can start just after a present while
    # its flip request is still one per step.)
    flips = [n[0] for n in notes if n[1] == 'flipreq']
    if steps and flips:
        import bisect as _b
        stt = [s[0] for s in steps]
        same = nostep = multi = 0
        prev = None
        for r in pres:
            i = _b.bisect_right(flips, r[0]) - 1
            if i < 0: continue
            f = flips[i]
            if prev is not None:
                if f == prev: same += 1
                else:
                    k = _b.bisect_right(stt, f) - _b.bisect_right(stt, prev)
                    if k == 0: nostep += 1
                    elif k > 1: multi += 1
            prev = f
        m = span / 60
        print('repeated frames: same flip shown twice %d (%.1f per minute); game flip with no new step %d (%.1f per minute); '
              'flip with 2+ steps %d (%.1f per minute)' % (same, same / m, nostep, nostep / m, multi, multi / m))
    elif steps:
        import bisect as _b
        stt = [s[0] for s in steps]
        rep = [y[0] for x, y in zip(pres, pres[1:]) if _b.bisect_right(stt, y[0]) == _b.bisect_right(stt, x[0])
               and stt[0] < x[0] and y[0] < stt[-1]]
        print('repeated frames (no game step since the previous frame; approximate): %d (%.1f per minute)' % (len(rep), len(rep) / (span / 60)))

    # Catch-up frames (NOTES fix 50): when a frame comes out late the game draws the next one without
    # its 3D scene (HUD / post only, ~150 draws instead of ~800) and flips it at once. Then two
    # presents land a few ms apart -- a full picture and a near-copy -- and nothing for ~38 ms, and
    # it can keep alternating like that for seconds: judder at ~25 real pictures a second. Counted
    # by draws when the log has them, else by render CPU (light frame right after a heavy one).
    dr = sorted(r[10] for r in pres if r[10] > 0)
    dr_med = dr[len(dr) // 2] if dr else 0
    def catchup(prev, r):
        if r[0] - prev[0] >= 17000: return False
        if r[10] >= 0 and dr_med > 100: return r[10] < 0.4 * dr_med
        return 0 <= r[9] < 3000 and prev[9] > 6000
    cu_t = [r[0] for x, r in zip(pres, pres[1:]) if catchup(x, r)]
    if cu_t:
        runs, best, last = 0, 0, None
        for t in cu_t:   # alternating stretches: catch-up frames ~40 ms apart
            runs = runs + 1 if last is not None and t - last < 60000 else 1
            best = max(best, runs); last = t
        print('game catch-up frames (3D scene skipped, shown right after a late frame): %d (%.1f per minute); '
              'longest alternating stretch %d in a row (%.1f s)' % (len(cu_t), len(cu_t) / (span / 60), best, best * 0.04))

    # Index notes by time for the per-hitch breakdown.
    ev = sorted((n for n in notes if n[1] in ('pso', 'read', 'psof', 'psow')), key=lambda n: n[0])
    tx = sorted((n for n in notes if n[1] == 'texc'), key=lambda n: n[0])
    tx_t = [n[0] for n in tx]
    ev_t = [n[0] for n in ev]
    import bisect

    def what(a, b):
        """Events in (a, b]: shader ms, read ms / count."""
        i, j = bisect.bisect_right(ev_t, a), bisect.bisect_right(ev_t, b)
        pso_ms = pso_n = rd_ms = rd_n = 0
        rd_files = collections.Counter()
        for n in ev[i:j]:
            if n[1] in ('psof', 'psow'):   # fix 62: all of a frame's builds / a must-draw's wait
                pso_n += int(float(n[2][0])) if n[1] == 'psof' else 1; pso_ms += float(n[2][1] if n[1] == 'psof' else n[2][0])
            elif n[1] == 'pso':
                if any(m[1] == 'psof' for m in ev[i:j]): continue   # counted in its frame's psof
                pso_n += 1; pso_ms += sum(float(x) for x in n[2][:3])
            else:
                rd_n += 1; rd_ms += float(n[2][1]); rd_files[os.path.basename(n[2][3]) if len(n[2]) > 3 else '?'] += 1
        return pso_n, pso_ms, rd_n, rd_ms, rd_files

    st_t = [s[0] for s in steps]

    def worst_step(a, b):
        """Longest game-step gap ending in (a, b], and the game thread's CPU time in it."""
        i, j = bisect.bisect_right(st_t, a), bisect.bisect_right(st_t, b)
        w, cpu = 0, -1
        for k in range(max(i, 1), j):
            if st_t[k] - st_t[k - 1] > w:
                w, cpu = st_t[k] - st_t[k - 1], steps[k][8]
        return w, cpu

    # Hitches: frames on screen longer than usual (from the stats) or presents late on the CPU side.
    hitches = []
    by_count = {}
    for idx, r in enumerate(pres):
        by_count.setdefault(r[5], idx)   # GetLastPresentCount after this Present = this present's number
    for idx in range(1, len(pres)):
        r, prev = pres[idx], pres[idx - 1]
        iv = r[0] - prev[0]
        refreshes = up.get(r[5] - 1) if r[5] else None   # how long the previous frame stayed up
        late = iv > 1.5 * med_p + 2000
        long_up = refreshes is not None and usual and refreshes > usual
        if not (late or long_up):
            continue
        pso_n, pso_ms, rd_n, rd_ms, rd_files = what(prev[0], r[0])
        ws, ws_cpu = worst_step(prev[0] - med_p, r[0])
        cause = []
        if pso_ms >= 4:
            cause.append('shader compile %d x %.0f ms' % (pso_n, pso_ms))
        tx_n = tx_ms = 0
        for n in tx[bisect.bisect_right(tx_t, prev[0]):bisect.bisect_right(tx_t, r[0])]:
            tx_n += int(n[2][0]); tx_ms += float(n[2][1])
        if tx_ms >= 4:
            cause.append('texture creation %d x %.0f ms' % (tx_n, tx_ms))
        if rd_ms >= 4:
            cause.append('file reads %d x %.0f ms (%s)' % (rd_n, rd_ms, ', '.join(k for k, _ in rd_files.most_common(2))))
        if med_s and ws > 1.5 * med_s + 2000:
            cause.append('game step late %.0f ms%s' % (ws / 1000, '' if ws_cpu < 0 else
                         ' (game thread %s: CPU %.0f ms)' % ('busy' if ws_cpu > 0.7 * ws else 'waiting', ws_cpu / 1000)))
        if r[3] > 8000:
            cause.append('Present blocked %.0f ms' % (r[3] / 1000))
        if r[4] > 8000:
            cause.append('GPU wait %.0f ms' % (r[4] / 1000))
        if r[2] > 8000:
            cause.append('pacing hold %.0f ms' % (r[2] / 1000))
        if not cause:
            cause.append('no CPU-side delay seen (missed vblank / OS / compositor)' if long_up and not late else
                         'renderer late' + ('' if r[9] < 0 else ' (render thread CPU %.0f ms of %.0f)' % (r[9] / 1000, iv / 1000)))
        hitches.append((r[0], iv, refreshes, '; '.join(cause)))

    print()
    big = [h for h in hitches if h[1] >= 2.5 * med_p or (h[2] and usual and h[2] >= usual + 2)]
    print('%d hitches (%.1f per minute); %d big ones (frame up >= %d refreshes or >= %.0f ms)' % (
        len(hitches), len(hitches) / (span / 60), len(big), usual + 2, 2.5 * med_p / 1000))
    kinds = collections.Counter()
    for h in hitches:
        for c in h[3].split('; '):
            k = c.split(' (')[0].split(' %')[0]
            for lab in ('shader compile', 'texture creation', 'file reads', 'Present blocked', 'GPU wait', 'pacing hold', 'no CPU-side', 'renderer late'):
                if c.startswith(lab): k = lab
            if c.startswith('game step late'):
                k = 'game step late (thread %s)' % ('busy' if 'busy' in c else 'waiting' if 'waiting' in c else '?')
            kinds[k] += 1
    print('causes:', ', '.join('%s %d' % kv for kv in kinds.most_common()))

    marks = [n for n in notes if n[1] == 'mark']
    print()
    print('%d F8 marks' % len(marks))
    # People press F8 a few seconds after they notice: look 10 s back. Besides hitches, show how even the
    # frames were (present interval spread) and the renderer's CPU per frame, since uneven frame pacing
    # (e.g. alternate frames 3 / 23 ms of render CPU) reads as judder with no single long frame.
    rcpu_all = sorted(r[9] for r in pres if r[9] >= 0)
    rcpu_med = rcpu_all[len(rcpu_all) // 2] / 1000 if rcpu_all else 0
    # Where the player was (fix 57): the newest "pos" line at or before the mark, and the one about 5 s
    # earlier (people press F8 after the stutter). To go there in a test run: DES_WARP_AT=<s>:<area>,<block>,999
    # (the world's archstone; later blocks need their own point) and, once loaded, DES_TELEPORT_AT=<s>:x,y,z.

    def where(v):
        a, b = (v[0].split(',') + ['?'])[:2]
        a = a.lstrip('0') or '0'
        if len(v) > 4:
            b = v[4]
        return 'area %s%s block %s at %s,%s,%s' % (a, AREAS.get(a, ''), b.lstrip('0') or '0', v[1], v[2], v[3])
    poss = [(n[0], n[2]) for n in notes if n[1] == 'pos' and len(n[2]) >= 4]

    def pos_at(t):
        best = None
        for pt, v in poss:
            if pt > t:
                break
            best = v
        return best
    # Thread CPU (fix 58): per thread name, the mean % of a core over the whole log and over the 10 s
    # before each mark; the threads that rose the most say what was saturated during the stutter.
    thr = []
    for n in notes:
        if n[1] == 'thr' and n[2]:
            d = {'(process)': float(n[2][0])}
            for kv in n[2][1:]:
                k, _, v = kv.rpartition('=')
                if k: d[k] = float(v)
            thr.append((n[0], d))

    def thr_mean(rows):
        acc = collections.Counter()
        for _, d in rows:
            for k, v in d.items(): acc[k] += v
        return {k: v / len(rows) for k, v in acc.items()} if rows else {}
    thr_all = thr_mean(thr)
    if thr_all:
        print('thread CPU, whole log (%% of one core): %s' % ', '.join(
            '%s %.0f' % kv for kv in sorted(thr_all.items(), key=lambda kv: -kv[1])[:9]))
    for m in marks:
        near = [h for h in hitches if m[0] - 10000000 <= h[0] <= m[0]]
        print('  mark %s at %.1f s: %s' % (m[2][0] if m[2] else '?', sec(m[0]),
              'no hitch in the 10 s before' if not near else ''))
        if poss:
            here, before = pos_at(m[0]), pos_at(m[0] - 5000000)
            if here:
                print('     player: %s%s' % (where(here), '' if not before or before == here else
                                                 ' (5 s before: %s)' % where(before)))
        win = [r for r in pres if m[0] - 10000000 <= r[0] <= m[0]]
        if len(win) > 2:
            iv = sorted((y[0] - x[0]) / 1000 for x, y in zip(win, win[1:]))
            rc = sorted(r[9] / 1000 for r in win if r[9] >= 0)
            print('     10 s before: present interval 5th-95th pct %.1f-%.1f ms; render CPU per frame median %.1f, '
                  '90th pct %.1f ms (whole log median %.1f)' % (iv[len(iv) // 20], iv[len(iv) * 19 // 20],
                  rc[len(rc) // 2] if rc else -1, rc[len(rc) * 9 // 10] if rc else -1, rcpu_med))
            ncu = sum(1 for t in cu_t if m[0] - 10000000 <= t <= m[0])
            if ncu:
                print('     %d game catch-up frames in those 10 s (full + scene-less frame pairs: judder)' % ncu)
        if thr:
            w = thr_mean([r for r in thr if m[0] - 10000000 <= r[0] <= m[0]])
            if w:
                up = sorted(((v - thr_all.get(k, 0), k, v) for k, v in w.items()), reverse=True)[:4]
                print('     thread CPU in those 10 s: %s' % ', '.join(
                    '%s %.0f%% (usual %.0f)' % (k, v, thr_all.get(k, 0)) for _, k, v in up))
        for h in near:
            print('     %.2f s before: frame %.1f ms, on screen %s refreshes -- %s' % (
                (m[0] - h[0]) / 1e6, h[1] / 1000, h[2] if h[2] is not None else '?', h[3]))

    print()
    print('worst %d hitches:' % min(top, len(hitches)))
    for h in sorted(hitches, key=lambda h: -h[1])[:top]:
        print('  %8.1f s  frame %6.1f ms  up %s  %s' % (sec(h[0]), h[1] / 1000, h[2] if h[2] is not None else '?', h[3]))

    # Hitches over time (per 10 s bucket), so bursts (loading, new areas) stand out.
    print()
    bucket = collections.Counter(int(sec(h[0]) // 10) for h in hitches)
    if bucket:
        print('hitches per 10 s (only buckets with >= 3):')
        print('  ' + ', '.join('%d-%ds: %d' % (k * 10, k * 10 + 10, v) for k, v in sorted(bucket.items()) if v >= 3) or '  none')

    # Camera input.
    if steps:
        print()
        src = collections.Counter(s[4] for s in steps)
        print('pad source per step: %s' % ', '.join('%s %.0f%%' % ({1: 'XInput pad', 2: 'keyboard+mouse', 0: 'none'}.get(k, k), 100.0 * v / len(steps)) for k, v in src.items()))
        polls = collections.Counter(min(s[5], 4) for s in steps)
        print('host pad polls per game step: %s' % ', '.join('%s%s: %.1f%%' % (k, '+' if k == 4 else '', 100.0 * v / len(steps)) for k, v in sorted(polls.items())))
        mouse = [s for s in steps if s[4] == 2 and (s[6] or s[7])]
        if mouse:
            sat = sum(1 for s in mouse if abs(s[2]) >= 127 or abs(s[3]) >= 127)
            print('mouse camera: %d steps with movement; stick pinned at full deflection on %.0f%% of them' % (len(mouse), 100.0 * sat / len(mouse)))
        turning = [s for s in steps if abs(s[2]) > 20 or abs(s[3]) > 20]
        print('steps with the camera stick pushed: %d (%.0f%%)' % (len(turning), 100.0 * len(turning) / len(steps)))


if __name__ == '__main__':
    main()

"""HTTPS downloads on a fresh Windows install (2026-11-03, Windows Sandbox: "CERTIFICATE_VERIFY_FAILED" for LLVM).

Windows does not ship every root certificate: it fetches a missing one the first time Windows' own TLS code (Edge,
PowerShell, .NET) meets a site that needs it. Python reads the certificate store but never triggers that fetch, so on a
new PC (or Windows Sandbox) its first download from a host whose root is not there yet fails, while the same download
in a browser works. install() wraps urllib.request.urlopen for this whole process: on a certificate failure it lets
Windows open the URL once (PowerShell, a HEAD request following redirects -- that fetches the missing roots into the
store) and tries again; if Python still cannot verify, Windows downloads the file itself and Python reads that copy.
The certificates are checked either way (by Windows instead of Python); nothing here turns verification off.
Downloaded files keep their own sha256 checks in the callers.
"""
import json, os, ssl, subprocess, sys, tempfile, urllib.error, urllib.request

_orig = urllib.request.urlopen
_PS = [os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'WindowsPowerShell', 'v1.0',
                    'powershell.exe'), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command']
_TLS = '[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072; '
_PRIME = _TLS + ("try { $q = [Net.WebRequest]::Create($env:DS_URL); $q.Method = 'HEAD'; $q.Timeout = 60000; "
                 "$q.UserAgent = 'DemonsSoulsRecomp-setup'; $q.GetResponse().Close() } catch [Net.WebException] { }")
_FETCH = _TLS + ("$ErrorActionPreference = 'Stop'; $w = New-Object Net.WebClient; "
                 "foreach ($p in (ConvertFrom-Json $env:DS_HDRS).psobject.Properties) { $w.Headers.Add($p.Name, [string]$p.Value) }; "
                 "$w.DownloadFile($env:DS_URL, $env:DS_OUT)")


def _rm(p):
    try:
        os.remove(p)
    except OSError:
        pass


def _cert_error(e):
    r = getattr(e, 'reason', e)
    return isinstance(r, ssl.SSLCertVerificationError) or 'CERTIFICATE_VERIFY_FAILED' in str(r)


def _ps(script, env, timeout):
    return subprocess.run(_PS + [script], env=dict(os.environ, **env), timeout=timeout, stdin=subprocess.DEVNULL,
                          stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                          errors='replace')


class _FileResponse:
    """What the callers use of a urlopen response (read, with, headers), backed by Windows' downloaded copy."""

    def __init__(self, path, url):
        self._path, self.url, self.status = path, url, 200
        self._f = open(path, 'rb')
        self.length = os.path.getsize(path)
        self.headers = {'Content-Length': str(self.length)}

    def read(self, n=-1):
        return self._f.read(n)

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def close(self):
        if self._f:
            self._f.close()
            self._f = None
            try:
                os.remove(self._path)
            except OSError:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def __del__(self):
        self.close()


def urlopen(url, *a, **k):
    try:
        return _orig(url, *a, **k)
    except urllib.error.URLError as e:
        if os.name != 'nt' or not _cert_error(e):
            raise
    req = url if isinstance(url, urllib.request.Request) else None
    full = req.full_url if req else url
    print('  (this PC is missing a root certificate for that site: letting Windows fetch it ...)',
          file=sys.stderr, flush=True)   # stderr: update.py --check's stdout is read by the launcher
    try:
        _ps(_PRIME, {'DS_URL': full}, 120)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        return _orig(url, *a, **k)
    except urllib.error.URLError as e:
        if not _cert_error(e):
            raise
    # still not verifiable by Python: Windows downloads it (and checks the certificate) into a temp file
    fd, out = tempfile.mkstemp(prefix='ds_dl_', suffix='.part')
    os.close(fd)
    hdrs = {k.title(): v for k, v in (req.header_items() if req else [])}   # urllib says 'User-agent'
    hdrs.setdefault('User-Agent', 'DemonsSoulsRecomp-setup')     # (PowerShell's JSON reader rejects case twins)
    try:
        r = _ps(_FETCH, {'DS_URL': full, 'DS_OUT': out, 'DS_HDRS': json.dumps(hdrs)}, 3 * 3600)
    except (OSError, subprocess.SubprocessError) as e:
        _rm(out)   # WebClient deletes it itself on a failed download
        raise urllib.error.URLError(f'Windows could not download it either: {e}')
    if r.returncode:
        _rm(out)   # WebClient deletes it itself on a failed download
        msg = (r.stderr or '').strip().splitlines()
        raise urllib.error.URLError('Windows could not download it either: ' + (msg[0] if msg else f'exit {r.returncode}'))
    return _FileResponse(out, full)


def install():
    if os.name == 'nt' and urllib.request.urlopen is _orig:
        urllib.request.urlopen = urlopen

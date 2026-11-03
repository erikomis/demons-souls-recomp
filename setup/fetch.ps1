# SETUP.bat / BUILD.bat: download a pinned file, check its SHA-256 and unzip it -- for what is needed
# before Python exists (the portable Python itself, and Git). Nothing is installed: it all stays in
# the folder given (under deps\).
#   powershell -NoProfile -ExecutionPolicy Bypass -File <kit>\setup\fetch.ps1 -Url <url> -Sha256 <hex> -Dest <abs dir> [-Name <text>]
# Paths are absolute and every file operation is literal (.NET, -LiteralPath): a folder named like
# "Demon's Souls [BLUS-30443]" is a wildcard pattern to PowerShell's own path cmdlets. The archive is
# unpacked into <Dest>.part and renamed to <Dest> only when complete, so an interrupted run never leaves
# a half folder that a later run would take as installed.
param([Parameter(Mandatory)][string]$Url, [Parameter(Mandatory)][string]$Sha256,
      [Parameter(Mandatory)][string]$Dest, [string]$Name = 'the download')
$ErrorActionPreference = 'Stop'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072 } catch {}   # TLS 1.2
Add-Type -AssemblyName System.IO.Compression.FileSystem
$file = "$Dest.download"
$part = "$Dest.part"
for ($try = 1; ; $try++) {
    try {
        Write-Host "  downloading $Name from $Url"
        $wc = New-Object System.Net.WebClient
        $wc.DownloadFile($Url, $file)
        break
    } catch {
        if ($try -ge 3) { Write-Host "  download failed: $($_.Exception.Message)"; exit 1 }
        Start-Sleep -Seconds (5 * $try)
    }
}
$got = (Get-FileHash -Algorithm SHA256 -LiteralPath $file).Hash
if ($got -ne $Sha256.ToUpper()) {
    [IO.File]::Delete($file)
    Write-Host "  $Name does not match its checksum (got $got): not using it"
    exit 1
}
try {
    if ([IO.Directory]::Exists($part)) { [IO.Directory]::Delete($part, $true) }
    [IO.Compression.ZipFile]::ExtractToDirectory($file, $part)
    if ([IO.Directory]::Exists($Dest)) { [IO.Directory]::Delete($Dest, $true) }
    [IO.Directory]::Move($part, $Dest)
} catch {
    Write-Host "  unpacking $Name failed: $($_.Exception.Message)"
    exit 1
} finally {
    if ([IO.File]::Exists($file)) { [IO.File]::Delete($file) }
}
exit 0

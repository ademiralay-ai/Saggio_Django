<#
.SYNOPSIS
    Saggio Robot Agent uninstaller.

.DESCRIPTION
    Servisi durdurur, kaldırır. İstenirse veriyi de siler.

.PARAMETER PurgeData
    Verilirse C:\SaggioRobotAgent klasörünü de siler (config, log dahil).
#>
[CmdletBinding()]
param(
    [string] $InstallDir  = "C:\SaggioRobotAgent",
    [string] $ServiceName = "SaggioRobotAgent",
    [switch] $PurgeData
)

$ErrorActionPreference = 'Continue'

$nssm = Join-Path $InstallDir 'nssm.exe'
if (Test-Path $nssm) {
    Write-Host "[*] Servis durduruluyor / kaldiriliyor..." -ForegroundColor Cyan
    & $nssm stop   $ServiceName confirm 2>$null | Out-Null
    & $nssm remove $ServiceName confirm 2>$null | Out-Null
} else {
    Write-Host "[!] nssm.exe bulunamadi, sc.exe ile deneniyor..." -ForegroundColor Yellow
    sc.exe stop   $ServiceName 2>$null | Out-Null
    sc.exe delete $ServiceName 2>$null | Out-Null
}

Start-Sleep -Seconds 2

if ($PurgeData) {
    Write-Host "[*] Veri klasoru siliniyor: $InstallDir" -ForegroundColor Cyan
    Remove-Item $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "[OK] Tamamlandi." -ForegroundColor Green

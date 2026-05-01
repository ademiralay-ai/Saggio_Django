<#
.SYNOPSIS
    Saggio Robot Agent kurulum paketini ZIP olarak uretir.

.EXAMPLE
    .\build_robot_agent_package.ps1
    .\build_robot_agent_package.ps1 -Version 1.3.1 -IncludeNssm
#>
[CmdletBinding()]
param(
    [string] $Version       = "1.3.0",
    [string] $OutDir        = "",
    [switch] $IncludeNssm
)

$ErrorActionPreference = 'Stop'
$rootDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
if ([string]::IsNullOrWhiteSpace($OutDir)) { $OutDir = Join-Path $rootDir 'dist' }
$srcDir = Join-Path $rootDir 'robot_agent'
if (-not (Test-Path $srcDir)) { throw "robot_agent klasoru bulunamadi: $srcDir" }

$pkgName  = "SaggioRobotAgentPackage_$Version"
$workDir  = Join-Path $env:TEMP $pkgName
if (Test-Path $workDir) { Remove-Item $workDir -Recurse -Force }
New-Item -ItemType Directory -Path $workDir | Out-Null

$filesToInclude = @(
    'agent_runtime.py',
    'agent_launcher.py',
    'install.ps1',
    'uninstall.ps1',
    'README.md',
    'config.example.json'
)

Write-Host "[*] Paket olusturuluyor: $pkgName" -ForegroundColor Cyan
foreach ($f in $filesToInclude) {
    $srcPath = Join-Path $srcDir $f
    if (-not (Test-Path $srcPath)) {
        Write-Warning "Dosya bulunamadi, atlaniyor: $f"
        continue
    }
    Copy-Item $srcPath (Join-Path $workDir $f) -Force
    Write-Host "    + $f"
}

# Opsiyonel: nssm.exe pakete goml (offline kurulum icin)
if ($IncludeNssm) {
    $nssmDest = Join-Path $workDir 'nssm.exe'
    $bundled  = Join-Path $srcDir 'nssm.exe'
    if (Test-Path $bundled) {
        Copy-Item $bundled $nssmDest -Force
        Write-Host "    + nssm.exe (bundled)"
    } else {
        Write-Host "[*] NSSM indiriliyor..." -ForegroundColor Cyan
        $tmpZip = Join-Path $env:TEMP 'nssm-build.zip'
        $tmpExt = Join-Path $env:TEMP 'nssm-build'
        Invoke-WebRequest 'https://nssm.cc/release/nssm-2.24.zip' -OutFile $tmpZip -UseBasicParsing
        if (Test-Path $tmpExt) { Remove-Item $tmpExt -Recurse -Force }
        Expand-Archive $tmpZip -DestinationPath $tmpExt -Force
        Copy-Item (Join-Path $tmpExt 'nssm-2.24\win64\nssm.exe') $nssmDest -Force
        Remove-Item $tmpZip -Force; Remove-Item $tmpExt -Recurse -Force
        Write-Host "    + nssm.exe (downloaded)"
    }
}

# VERSION.txt yaz
"$Version`r`nbuilt at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" | `
    Set-Content (Join-Path $workDir 'VERSION.txt') -Encoding UTF8

# ZIP'le
if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir | Out-Null }
$zipPath = Join-Path $OutDir "$pkgName.zip"
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }

Compress-Archive -Path "$workDir\*" -DestinationPath $zipPath -CompressionLevel Optimal
Remove-Item $workDir -Recurse -Force

$size = [math]::Round((Get-Item $zipPath).Length / 1KB, 1)
Write-Host ""
Write-Host "[OK] Paket hazir: $zipPath  ($size KB)" -ForegroundColor Green

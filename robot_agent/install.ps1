<#
.SYNOPSIS
    Saggio Robot Agent tek tıkla kurulum scripti (NSSM tabanlı).

.DESCRIPTION
    - C:\SaggioRobotAgent klasör iskeletini oluşturur
    - Python 3.11+ ile venv kurar
    - requests bağımlılığını yükler (pywin32 GEREKMİYOR - NSSM kullanıyoruz)
    - agent dosyalarını kopyalar
    - config.json'u parametrelere göre yazar
    - NSSM ile Windows servisi olarak kaydeder ve başlatır

.PARAMETER ServerUrl
    Merkez sunucu URL'si (örn: http://10.16.88.18:8000)

.PARAMETER AgentCode
    Bu robotun benzersiz kodu (örn: robot-06)

.PARAMETER Token
    Sunucudan alınan token

.PARAMETER Name
    Robot için görünür ad (örn: "Robot 06")

.PARAMETER PythonExe
    Kullanılacak Python exe yolu (varsayılan: 'py -3.11' ile bulunur)

.EXAMPLE
    .\install.ps1 -ServerUrl http://10.16.88.18:8000 -AgentCode robot-06 -Token abc123 -Name "Robot 06"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)] [string] $ServerUrl,
    [Parameter(Mandatory=$true)] [string] $AgentCode,
    [Parameter(Mandatory=$true)] [string] $Token,
    [Parameter(Mandatory=$false)][string] $Name = "",
    [Parameter(Mandatory=$false)][string] $InstallDir = "C:\SaggioRobotAgent",
    [Parameter(Mandatory=$false)][string] $ServiceName = "SaggioRobotAgent",
    [Parameter(Mandatory=$false)][string] $PythonExe = ""
)

$ErrorActionPreference = 'Stop'

function Write-Step($msg) { Write-Host "[*] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Warn2($msg){ Write-Host "[!] $msg" -ForegroundColor Yellow }

# 0) Yetki kontrolü
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Bu script Administrator olarak çalıştırılmalı (Sağ tık > Run as Administrator)."
}

if ([string]::IsNullOrWhiteSpace($Name)) { $Name = $AgentCode }
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$logsDir   = Join-Path $InstallDir 'logs'
$venvDir   = Join-Path $InstallDir '.venv'
$venvPy    = Join-Path $venvDir 'Scripts\python.exe'
$venvPip   = Join-Path $venvDir 'Scripts\pip.exe'
$nssmPath  = Join-Path $InstallDir 'nssm.exe'

Write-Step "Hedef klasor: $InstallDir"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
New-Item -ItemType Directory -Force -Path $logsDir   | Out-Null

# 1) Python tespiti
if (-not $PythonExe) {
    Write-Step "Python 3.11+ aranıyor..."
    try {
        $PythonExe = (& py -3.11 -c "import sys;print(sys.executable)").Trim()
    } catch {
        try { $PythonExe = (& py -3 -c "import sys;print(sys.executable)").Trim() }
        catch { throw "Python 3 bulunamadi. https://www.python.org/downloads/ adresinden 3.11 kurun." }
    }
}
Write-Ok "Python: $PythonExe"

# 2) venv kur
if (-not (Test-Path $venvPy)) {
    Write-Step "Sanal ortam olusturuluyor: $venvDir"
    & $PythonExe -m venv $venvDir
    if ($LASTEXITCODE -ne 0) { throw "venv olusturulamadi." }
} else {
    Write-Ok "venv zaten mevcut."
}

Write-Step "pip yukseltiliyor ve bagimliliklar kuruluyor (requests)..."
& $venvPy -m pip install --upgrade pip --quiet
& $venvPip install --quiet requests
if ($LASTEXITCODE -ne 0) { throw "requests kurulumu basarisiz." }
Write-Ok "Bagimliliklar kuruldu."

# 3) Agent dosyalarini kopyala
Write-Step "Agent dosyalari kopyalaniyor..."
$filesToCopy = @('agent_runtime.py', 'agent_launcher.py')
foreach ($f in $filesToCopy) {
    $srcPath = Join-Path $scriptDir $f
    if (-not (Test-Path $srcPath)) { throw "Eksik dosya: $srcPath" }
    Copy-Item $srcPath (Join-Path $InstallDir $f) -Force
}
Write-Ok "Dosyalar kopyalandi."

# 4) config.json olustur
$configPath = Join-Path $InstallDir 'config.json'
$config = [ordered]@{
    server_base_url               = $ServerUrl.TrimEnd('/')
    agent_code                    = $AgentCode
    token                         = $Token
    name                          = $Name
    agent_version                 = "1.3.0"
    log_level                     = "INFO"
    log_file                      = "C:/SaggioRobotAgent/agent.log"
    poll_interval_seconds         = 5
    idle_interval_seconds         = 3
    http_timeout_seconds          = 20
    update_check_interval_seconds = 300
    command_timeout_seconds       = 7200
    capabilities                  = @{ sap = $true; excel = $true; windows_automation = $true }
}
if (Test-Path $configPath) {
    Write-Warn2 "Mevcut config.json bulundu, $configPath.bak olarak yedeklendi."
    Copy-Item $configPath "$configPath.bak" -Force
}

# PowerShell 5.1 'UTF8' = BOM'lu yazar; Python json.load BOM kabul etmez.
# Bu yuzden BOM'suz UTF-8 olarak yaz.
$jsonText = $config | ConvertTo-Json -Depth 6
[System.IO.File]::WriteAllText($configPath, $jsonText, (New-Object System.Text.UTF8Encoding $false))
Write-Ok "config.json yazildi: $configPath"

# 5) NSSM tedarik
if (-not (Test-Path $nssmPath)) {
    $bundledNssm = Join-Path $scriptDir 'nssm.exe'
    if (Test-Path $bundledNssm) {
        Write-Step "Pakette gelen nssm.exe kopyalaniyor..."
        Copy-Item $bundledNssm $nssmPath -Force
    } else {
        Write-Step "nssm.exe indiriliyor (https://nssm.cc/release/nssm-2.24.zip)..."
        $tmpZip = Join-Path $env:TEMP 'nssm-saggio.zip'
        $tmpDir = Join-Path $env:TEMP 'nssm-saggio'
        Invoke-WebRequest -Uri 'https://nssm.cc/release/nssm-2.24.zip' -OutFile $tmpZip -UseBasicParsing
        if (Test-Path $tmpDir) { Remove-Item $tmpDir -Recurse -Force }
        Expand-Archive -Path $tmpZip -DestinationPath $tmpDir -Force
        Copy-Item (Join-Path $tmpDir 'nssm-2.24\win64\nssm.exe') $nssmPath -Force
        Remove-Item $tmpZip -Force -ErrorAction SilentlyContinue
        Remove-Item $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
Write-Ok "NSSM hazir: $nssmPath"

# 6) Eski servisi temizle (varsa)
$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Warn2 "Eski servis bulundu, kaldiriliyor..."
    & $nssmPath stop   $ServiceName confirm | Out-Null
    & $nssmPath remove $ServiceName confirm | Out-Null
    Start-Sleep -Seconds 2
}

# 7) Servisi NSSM ile kur
Write-Step "Servis kaydediliyor: $ServiceName"
$launcher = Join-Path $InstallDir 'agent_launcher.py'
& $nssmPath install $ServiceName $venvPy $launcher | Out-Null
& $nssmPath set $ServiceName AppDirectory  $InstallDir                       | Out-Null
& $nssmPath set $ServiceName AppStdout     (Join-Path $logsDir 'stdout.log') | Out-Null
& $nssmPath set $ServiceName AppStderr     (Join-Path $logsDir 'stderr.log') | Out-Null
& $nssmPath set $ServiceName AppRotateFiles 1                                | Out-Null
& $nssmPath set $ServiceName AppRotateBytes 5242880                          | Out-Null
& $nssmPath set $ServiceName Start          SERVICE_AUTO_START               | Out-Null
& $nssmPath set $ServiceName DisplayName   "Saggio Robot Agent ($AgentCode)" | Out-Null
& $nssmPath set $ServiceName Description   "Saggio merkezi sunucusundan is alip robot bilgisayarda calistirir." | Out-Null

Write-Step "Servis baslatiliyor..."
& $nssmPath start $ServiceName | Out-Null
Start-Sleep -Seconds 3

$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -eq 'Running') {
    Write-Ok "Servis calisiyor."
} else {
    Write-Warn2 "Servis baslamadi gibi gozukuyor. Loglara bakin: $logsDir"
}

Write-Host ""
Write-Host "=================================================" -ForegroundColor Green
Write-Host " KURULUM TAMAMLANDI" -ForegroundColor Green
Write-Host "=================================================" -ForegroundColor Green
Write-Host " Servis adi   : $ServiceName"
Write-Host " Install dir  : $InstallDir"
Write-Host " Log klasoru  : $logsDir"
Write-Host " Config       : $configPath"
Write-Host ""
Write-Host " Kontrol komutlari:"
Write-Host "   Get-Service $ServiceName"
Write-Host "   Get-Content $logsDir\launcher.log -Tail 30"
Write-Host "   Get-Content $logsDir\stdout.log   -Tail 30"
Write-Host ""
Write-Host " Sunucu tarafinda 'Robot Operasyon' ekraninda"
Write-Host " '$AgentCode' robotunun ONLINE oldugunu kontrol edin."
Write-Host "=================================================" -ForegroundColor Green

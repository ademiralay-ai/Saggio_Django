# React flow builder'i build edip Django static dizinine kopyalar
# Kullanim: cd frontend ; .\build_and_deploy.ps1

$ErrorActionPreference = "Stop"
$FrontendDir = $PSScriptRoot
$DjangoStatic = Join-Path $FrontendDir "..\core\static\core\flow_builder"

Write-Host "==> Bagimliliklar yukleniyor..." -ForegroundColor Cyan
npm install

Write-Host "==> Build aliniyor..." -ForegroundColor Cyan
npm run build

Write-Host "==> Static dizini hazirlaniyor: $DjangoStatic" -ForegroundColor Cyan
New-Item -ItemType Directory -Force $DjangoStatic | Out-Null

Write-Host "==> JS ve CSS dosyalari kopyalaniyor..." -ForegroundColor Cyan
Copy-Item "$FrontendDir\build\static\js\*"  $DjangoStatic -Force
Copy-Item "$FrontendDir\build\static\css\*" $DjangoStatic -Force

# Build edilen dosyaların isimlerini bul (hash'li)
$mainJs  = (Get-ChildItem "$DjangoStatic\main.*.js"  | Where-Object { $_.Name -notlike "*.map" } | Select-Object -First 1).Name
$mainCss = (Get-ChildItem "$DjangoStatic\main.*.css" | Select-Object -First 1).Name

if (-not $mainJs -or -not $mainCss) {
    Write-Host "HATA: Build dosyalari bulunamadi!" -ForegroundColor Red
    exit 1
}

Write-Host "==> Bulunan dosyalar: $mainJs, $mainCss" -ForegroundColor Green

# Chunk js'i de bul
$chunkJs = (Get-ChildItem "$DjangoStatic\*.chunk.js" | Where-Object { $_.Name -notlike "*.map" } | Select-Object -First 1).Name

# Django template'ini guncelle
$TemplatePath = Join-Path $FrontendDir "..\core\templates\core\sap_process_flow_builder_react.html"
$templateContent = @"
{%% load static %%}<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="process-id" content="{{ process.id }}">
    <meta name="csrf-token" content="{{ csrf_token }}">
    <title>Is Akisi Tasarimcisi - {{ process.name }}</title>
    <link rel="stylesheet" href="{%% static 'core/flow_builder/$mainCss' %%}">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        html, body, #root { width: 100%; height: 100%; overflow: hidden; }
    </style>
</head>
<body>
    <div id="root"></div>
$(if ($chunkJs) { "    <script src=""{%% static 'core/flow_builder/$chunkJs' %%}""></script>`n" })`    <script src="{%% static 'core/flow_builder/$mainJs' %%}"></script>
</body>
</html>
"@

Set-Content -Path $TemplatePath -Value $templateContent -Encoding UTF8
Write-Host "==> Template guncellendi: $TemplatePath" -ForegroundColor Green
Write-Host ""
Write-Host "TAMAM! Sunucuyu yeniden baslatmaniz yeterli." -ForegroundColor Green

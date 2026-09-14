#Requires -Version 5.1
<#
.SYNOPSIS
  Windows 用単一ファイル exe を PyInstaller でビルドし、指定パスへ出力する。

.PARAMETER SourceDir
  rkbdb2xml リポジトリのルート（Windows パス）。

.PARAMETER OutputPath
  出力先の exe フルパス。

.PARAMETER TempRoot
  作業用一時ディレクトリ。既定は $env:TEMP\rkbdb2xml_build。
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$SourceDir,

    [Parameter(Mandatory = $true)]
    [string]$OutputPath,

    [string]$TempRoot = "$env:TEMP\rkbdb2xml_build")

$ErrorActionPreference = "Stop"

$SourceDir = (Resolve-Path $SourceDir).ProviderPath
$OutputPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputPath)
$TempRoot = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($TempRoot)

$buildDir = Join-Path $TempRoot "src"
$venvDir = Join-Path $TempRoot ".venv"
$distDir = Join-Path $buildDir "dist"

Write-Output "Source : $SourceDir"
Write-Output "Output : $OutputPath"
Write-Output "Temp   : $TempRoot"

# クリーンアップ
if (Test-Path $TempRoot) {
    Remove-Item -Recurse -Force $TempRoot
}

New-Item -ItemType Directory -Force -Path $buildDir | Out-Null

# ソースをコピー（venv / git 履歴などは除外）
Write-Output "Copying source to $buildDir ..."
$excludedDirs = @(".git", ".venv", ".venv-win", "venv", "env", "dist", "build", "__pycache__", ".pytest_cache", ".serena", "graphify-out")
$robocopyArgs = @($SourceDir, $buildDir, "/E", "/MT:8") + ($excludedDirs | ForEach-Object { "/XD"; $_ })
& robocopy @robocopyArgs
if ($LASTEXITCODE -ge 8) {
    throw "robocopy failed with exit code $LASTEXITCODE"
}

# Python 確認
$py = (Get-Command python -ErrorAction Stop).Path
Write-Output "Using Python: $py"

# venv 作成
Write-Output "Creating venv at $venvDir ..."
& $py -m venv $venvDir
if ($LASTEXITCODE -ne 0) { throw "venv creation failed" }

$activate = Join-Path $venvDir "Scripts\Activate.ps1"

function Invoke-InVenv {
    param([scriptblock]$Block)
    & $activate
    & $Block
    if ($LASTEXITCODE -ne 0) { throw "command block failed" }
}

# 依存関係＋ PyInstaller をインストール
Write-Output "Installing dependencies ..."
Invoke-InVenv {
    python -m pip install --upgrade pip
    pip install -r (Join-Path $buildDir "requirements.txt")
    pip install -e $buildDir
    pip install pyinstaller
}

# ビルド
Write-Output "Building with PyInstaller ..."
Invoke-InVenv {
    Set-Location $buildDir
    pyinstaller --clean rkbdb2xml-gui.spec
}

$built = Join-Path $distDir "rkbdb2xml-gui.exe"
if (-not (Test-Path $built)) {
    throw "Built binary not found at $built"
}

# 出力先へコピー
$outDir = Split-Path $OutputPath -Parent
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
Write-Output "Copying to $OutputPath ..."
Copy-Item -Path $built -Destination $OutputPath -Force

Write-Output "Build complete: $OutputPath"

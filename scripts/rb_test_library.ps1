# Rekordbox 6/7 のライブラリをテスト用に切り替える（Issue #48）
#
#   .\scripts\rb_test_library.ps1 -SwapOut   # 本番ライブラリを退避し空にする
#   .\scripts\rb_test_library.ps1 -SwapIn    # 本番ライブラリを復帰する
#
# %APPDATA%\Pioneer\rekordbox（master.db + rekordbox3.settings + 解析
# キャッシュ）だけを退避する。rekordboxAgent（アカウント・復号鍵）は
# 触らないのでサインイン状態と pyrekordbox の鍵取得は維持される。
#
# 必ず Rekordbox を終了してから実行すること。

param(
    [switch]$SwapOut,
    [switch]$SwapIn
)

$ErrorActionPreference = "Stop"
$rbDir = "$env:APPDATA\Pioneer\rekordbox"
$backupDir = "$env:APPDATA\Pioneer\rekordbox.prod-backup"

if (Get-Process -Name "rekordbox*", "rekordboxAgent*" -ErrorAction SilentlyContinue) {
    Write-Error "Rekordbox 系プロセスが起動しています。終了してから再実行してください。"
}

if ($SwapOut) {
    if (Test-Path $backupDir) {
        Write-Error "$backupDir が既に存在します。前回の退避が残っています。中身を確認してから手動で処理してください。"
    }
    if (Test-Path $rbDir) {
        Rename-Item $rbDir $backupDir
        Write-Host "退避: $rbDir -> $backupDir"
    } else {
        Write-Host "$rbDir は存在しません（初回状態）。退避不要です。"
    }
    Write-Host "Rekordbox を起動すると空のテスト用ライブラリが作成されます。"
}
elseif ($SwapIn) {
    if (Test-Path $rbDir) {
        Remove-Item $rbDir -Recurse -Force
        Write-Host "削除: $rbDir（テスト用ライブラリ）"
    }
    if (Test-Path $backupDir) {
        Rename-Item $backupDir $rbDir
        Write-Host "復帰: $backupDir -> $rbDir"
    } else {
        Write-Host "バックアップがありません。何もしませんでした。"
    }
}
else {
    Write-Host "使い方: -SwapOut（退避）または -SwapIn（復帰）を指定してください。"
    Write-Host "現在: rbDir exists = $(Test-Path $rbDir), backup exists = $(Test-Path $backupDir)"
}

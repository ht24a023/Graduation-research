# 利用者が明示的に実行した場合だけ、この補助アプリを現在のユーザーへ登録します。
$ErrorActionPreference = 'Stop'
$bridgeRoot = $PSScriptRoot
$publishPath = Join-Path $bridgeRoot 'publish'
$manifestPath = Join-Path $bridgeRoot 'AppxManifest.xml'
Copy-Item -LiteralPath (Join-Path $bridgeRoot 'Package.appxmanifest') -Destination $manifestPath -Force
if (-not (Test-Path -LiteralPath (Join-Path $publishPath 'NotificationBridge.exe'))) {
    throw '先に Build.ps1 を実行してください。'
}
$developerMode = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock' -Name AllowDevelopmentWithoutDevLicense -ErrorAction SilentlyContinue).AllowDevelopmentWithoutDevLicense
if ($developerMode -ne 1) {
    throw '未署名の開発用アプリ登録には、Windows設定で開発者モードを有効にする必要があります。このスクリプトはWindows設定を自動変更しません。'
}
Copy-Item -LiteralPath (Join-Path $bridgeRoot 'Assets') -Destination $publishPath -Recurse -Force
Add-AppxPackage -Register $manifestPath -ExternalLocation $publishPath
$registered = Get-AppxPackage -Name 'Sotuken.NotificationBridge'
if (-not $registered) { throw 'アプリ登録を確認できませんでした。' }
@{ app_user_model_id = "$($registered.PackageFamilyName)!App" } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $bridgeRoot 'bridge-registration.json') -Encoding utf8
Write-Host '登録しました。Web UIのSETTINGSから通知アクセスを設定してください。'

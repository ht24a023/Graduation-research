$ErrorActionPreference = 'Stop'
Get-AppxPackage -Name 'Sotuken.NotificationBridge' | Remove-AppxPackage
$registrationPath = Join-Path $PSScriptRoot 'bridge-registration.json'
if (Test-Path -LiteralPath $registrationPath) { Remove-Item -LiteralPath $registrationPath }
$configPath = Join-Path $PSScriptRoot 'publish\bridge-config.json'
if (Test-Path -LiteralPath $configPath) { Remove-Item -LiteralPath $configPath }
Write-Host '補助アプリの登録と接続情報を削除しました。'

$ErrorActionPreference = 'Stop'
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
$env:DOTNET_SKIP_FIRST_TIME_EXPERIENCE = '1'
dotnet publish (Join-Path $PSScriptRoot 'NotificationBridge.csproj') -c Release -o (Join-Path $PSScriptRoot 'publish') --self-contained false
if ($LASTEXITCODE -ne 0) { throw 'ビルドに失敗しました。' }
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Assets') -Destination (Join-Path $PSScriptRoot 'publish') -Recurse -Force

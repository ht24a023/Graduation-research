param([string]$Url = 'http://127.0.0.1:8001/')
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path "$PSScriptRoot\..\..").Path
$endpoint = [Uri]$Url
if ($endpoint.Host -notin @('127.0.0.1','localhost','[::1]')) { throw 'Local URL required' }
$ready = $false
try { $ready = (Invoke-WebRequest "$($Url.TrimEnd('/'))/site/dashboard/chat_browser.js" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 } catch {}
if (-not $ready) {
 $env:LOCAL_AI_SERVER_PORT = [string]$endpoint.Port
 $env:LOCAL_AI_SERVER_HOST = '127.0.0.1'
 Start-Process -FilePath "$root\.venv\Scripts\python.exe" -ArgumentList 'local_ai_server.py' -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput "$root\work\chat-browser-server.log" -RedirectStandardError "$root\work\chat-browser-server-error.log"
 for ($attempt=0; $attempt -lt 60; $attempt++) {
  try { $ready = (Invoke-WebRequest "$($Url.TrimEnd('/'))/site/dashboard/chat_browser.js" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 } catch {}
  if ($ready) { break }
  Start-Sleep -Seconds 1
 }
 if (-not $ready) { throw 'AIサーバーを起動できませんでした。work/chat-browser-server-error.logを確認してください。' }
}
$env:SOTUKEN_URL = $Url
Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
& "$PSScriptRoot\node_modules\electron\dist\electron.exe" $PSScriptRoot

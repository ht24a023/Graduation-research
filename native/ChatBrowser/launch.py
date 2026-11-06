"""Start the local server and the desktop chat browser without PowerShell setup."""
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

folder = Path(__file__).resolve().parent
root = folder.parents[1]
url = 'http://127.0.0.1:8001/'
env = os.environ.copy()
env.pop('ELECTRON_RUN_AS_NODE', None)
env.update(SOTUKEN_URL=url, LOCAL_AI_SERVER_PORT='8001', LOCAL_AI_SERVER_HOST='127.0.0.1')

def ready():
    try:
        with urllib.request.urlopen(url+'site/dashboard/chat_browser.js', timeout=2) as response:
            return response.status == 200 and b'sotukenBrowser' in response.read()
    except OSError:
        return False

if not ready():
    (root/'work').mkdir(exist_ok=True)
    with (root/'work/chat-browser-server.log').open('ab') as log:
        subprocess.Popen([sys.executable, str(root/'local_ai_server.py')], cwd=root, env=env,
                         stdout=log, stderr=log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    for _ in range(60):
        if ready():
            break
        time.sleep(1)
    else:
        raise SystemExit('AI server startup failed. See work/chat-browser-server.log')

executable = folder/'node_modules/electron/dist/electron.exe'
if not executable.is_file():
    raise SystemExit('Install the browser first: npm install && node node_modules/electron/install.js')
result = subprocess.run([str(executable), str(folder)], cwd=folder, env=env)
if result.returncode:
    raise SystemExit(f'Browser exited with code {result.returncode}.')

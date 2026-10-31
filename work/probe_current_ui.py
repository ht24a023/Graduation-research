import sys,threading
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
import local_ai_server as server
from playwright.sync_api import sync_playwright
http=server.QuietThreadingHTTPServer(('127.0.0.1',0),server.LocalAIServerHandler)
threading.Thread(target=http.serve_forever,daemon=True).start()
try:
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        page.on('pageerror',lambda error:print('PAGE ERROR:',str(error),flush=True))
        page.on('response',lambda response:print('HTTP ERROR:',response.status,response.url,flush=True) if response.status>=400 and '/site/' in response.url else None)
        page.goto(f'http://127.0.0.1:{http.server_port}',wait_until='domcontentloaded')
        page.wait_for_timeout(1200)
        print('INITIALIZED:',page.evaluate('({dashboard:!!window.dashboardPanels,workbench:!!window.workbench,audio:!!document.getElementById("ai-signal"),systemButton:!!document.querySelector("[data-open-panel=system]")})'),flush=True)
        browser.close()
finally:http.shutdown();http.server_close()

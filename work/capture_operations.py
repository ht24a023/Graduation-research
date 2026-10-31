import sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from playwright.sync_api import sync_playwright
out=Path(r'C:\Users\ht24a023\Documents\Codex\2026-10-31\30-ai\outputs')
out.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(channel='chrome',headless=True)
    page=browser.new_page(viewport={'width':1920,'height':1080})
    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto('http://127.0.0.1:8001/',wait_until='domcontentloaded')
    page.wait_for_selector('#ops-open')
    page.wait_for_function("document.getElementById('hud-cpu').textContent!=='—'")
    page.wait_for_function("document.getElementById('hud-rx').textContent!=='計測中'",timeout=15000)
    assert page.locator('#ai-assist-box').count()==0
    assert page.locator('.composer .quick-grid').count()==0
    page.screenshot(path=str(out/'jarvis-permanent-left.png'))
    page.locator('#ops-open').click()
    page.screenshot(path=str(out/'jarvis-control.png'))
    assert not errors,errors
    print('Actual updated server UI and CONTROL screenshots saved; no browser errors',flush=True)
    browser.close()

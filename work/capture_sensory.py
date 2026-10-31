import sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from playwright.sync_api import sync_playwright
out=Path(r'C:\Users\ht24a023\Documents\Codex\2026-10-31\30-ai\outputs');out.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(channel='chrome',headless=True)
    page=browser.new_page(viewport={'width':1920,'height':1080})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto('http://127.0.0.1:8001/',wait_until='domcontentloaded')
    page.wait_for_selector('#ai-signal')
    page.wait_for_function("document.getElementById('ai-link-rtt').textContent.endsWith(' ms')")
    page.wait_for_function("document.getElementById('hud-rx').textContent!=='計測中'")
    page.screenshot(path=str(out/'ai-signal-dashboard.png'))
    page.locator('[data-open-panel="audio"]').click()
    page.screenshot(path=str(out/'ai-audio-controls.png'))
    assert page.locator('.dashboard-brand').inner_text().startswith('AI')
    assert page.locator('#ai-assist-box').count()==0
    assert not errors,errors
    print('Live updated UI captured, no browser errors',flush=True)
    browser.close()

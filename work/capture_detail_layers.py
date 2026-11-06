from pathlib import Path
from playwright.sync_api import sync_playwright
out=Path(r'C:\Users\ht24a023\Documents\Codex\2026-10-31\30-ai\outputs');out.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(channel='chrome',headless=True)
    page=browser.new_page(viewport={'width':1920,'height':1080})
    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto('http://127.0.0.1:8001/',wait_until='domcontentloaded')
    page.wait_for_selector('#dx-layer')
    page.wait_for_function("document.getElementById('hud-cpu').textContent!=='—'")
    cpu=page.locator('.hud-cell').filter(has=page.locator('#hud-cpu'));cpu.click()
    first=page.locator('.dx-window').first
    first.get_by_role('button',name='ピン留め',exact=True).click()
    first.get_by_role('button',name='さらに詳しく ›',exact=True).click()
    first.locator('.dx-field').filter(has=page.get_by_text('time_seconds',exact=True)).get_by_role('button').click()
    def move(win,x,y):
        head=win.locator('.dx-head').bounding_box()
        page.mouse.move(head['x']+40,head['y']+14);page.mouse.down();page.mouse.move(x+40,y+14,steps=6);page.mouse.up()
    move(first,490,230)
    page.locator('.hud-cell').filter(has=page.locator('#hud-ram')).click()
    second=page.locator('.dx-window').last
    second.get_by_role('button',name='ピン留め',exact=True).click()
    second.get_by_role('button',name='さらに詳しく ›',exact=True).click()
    second.locator('.dx-field').filter(has=page.get_by_text('memory',exact=True)).get_by_role('button').click()
    move(second,960,230)
    assert page.locator('.dx-window[data-pinned="true"]').count()==2
    assert page.locator('dialog[open]').count()==0
    assert page.locator('#message').is_visible()
    assert not errors,errors
    page.screenshot(path=str(out/'ai-detail-layers.png'))
    print('Live PC drilldown and two pinned non-modal windows captured',flush=True)
    browser.close()

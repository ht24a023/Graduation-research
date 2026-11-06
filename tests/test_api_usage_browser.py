import threading
from pathlib import Path
from types import SimpleNamespace as N
import pytest
from playwright.sync_api import sync_playwright
import local_ai_server as server
from models.api_usage import ApiUsage,usage_scope

@pytest.mark.e2e
def test_api_usage_dialog_settings_export_and_mobile(tmp_path,monkeypatch):
    ledger=ApiUsage(tmp_path/'api.jsonl',tmp_path/'settings.json',tmp_path/'official.json')
    with usage_scope('work_summary'):
        c=ledger.begin('gpt-4.1-mini')
    ledger.finish(c,N(model='gpt-4.1-mini',usage=N(prompt_tokens=1000,completion_tokens=100,prompt_tokens_details=N(cached_tokens=200))),'success',1)
    monkeypatch.setattr(server,'api_usage',ledger)
    http=server.QuietThreadingHTTPServer(('127.0.0.1',0),server.LocalAIServerHandler)
    threading.Thread(target=http.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1000},accept_downloads=True);errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            base=f'http://127.0.0.1:{http.server_port}'
            page.goto(base,wait_until='commit',timeout=60000)
            page.locator('#api-usage-open').click(timeout=60000)
            dialog=page.locator('#api-usage-dialog')
            page.wait_for_function("document.querySelector('#api-usage-dialog').textContent.includes('1,100')")
            assert 'バックグラウンド要約' in dialog.inner_text()
            page.get_by_label('月予算 USD',exact=True).fill('10')
            page.get_by_role('button',name='予算・為替を保存',exact=True).click()
            page.wait_for_function("document.querySelector('#api-usage-dialog').textContent.includes('$9.999500')")
            page.get_by_label('公式ページで確認した残高 USD',exact=True).fill('5')
            page.get_by_role('button',name='現在の参考残高として保存',exact=True).click()
            page.wait_for_function("document.querySelector('#api-usage-dialog').textContent.includes('$5.000000')")
            assert page.request.post(base+'/api-usage/settings',data={'action':'balance','balance_usd':99}).status==403
            with page.expect_download() as event:page.get_by_role('button',name='記録JSONを保存').click()
            assert event.value.suggested_filename=='sotuken-api-usage.json'
            page.screenshot(path=str(Path(server.__file__).parent/'work/api-usage-desktop.png'))
            page.set_viewport_size({'width':390,'height':844})
            assert dialog.evaluate('(e)=>e.getBoundingClientRect().width')<=390
            page.screenshot(path=str(Path(server.__file__).parent/'work/api-usage-mobile.png'))
            assert not errors,errors
            browser.close()
    finally:http.shutdown();http.server_close()

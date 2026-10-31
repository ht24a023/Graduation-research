"""実サーバーと実ブラウザーで固定入力・手動保護・実ツール連携を検証。"""
import os
import threading

import pytest
from playwright.sync_api import sync_playwright
import local_ai_server as server
from models.evaluation_metrics import EvaluationMetrics
from models import execution_trace


@pytest.mark.e2e
def test_workbench_real_tools_panel_policy_and_fixed_composer(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(server,'evaluation_metrics',EvaluationMetrics(str(tmp_path/'evaluation.jsonl')))
    monkeypatch.setattr(execution_trace,'LOG_PATH',tmp_path/'processing.jsonl')
    http=server.QuietThreadingHTTPServer(('127.0.0.1',0),server.LocalAIServerHandler)
    threading.Thread(target=http.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(channel=os.getenv('PLAYWRIGHT_CHANNEL','chrome'),headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1000})
            errors=[]; page.on('pageerror',lambda error:errors.append(str(error)))
            base=f'http://127.0.0.1:{http.server_port}'
            page.goto(base,wait_until='domcontentloaded')
            page.wait_for_function('window.dashboardPanels && window.workbench')
            page.locator('[data-open-panel="weather"]').click()

            def send(text):
                page.locator('#message').fill(text)
                page.locator('#send-btn').click()
                page.wait_for_function("!document.getElementById('send-btn').disabled")

            send('CPUの使用率を教えて')
            assert page.locator('[data-info-panel="system"]').is_visible()
            assert page.locator('[data-info-panel="weather"]').is_visible()
            send('https://example.comをQRコードにして')
            assert page.locator('[data-info-panel="qr"]').is_visible()
            assert page.locator('[data-info-panel="system"]').is_hidden()
            assert page.locator('[data-info-panel="weather"]').is_visible()
            assert page.locator('#qr-result img').count()==1
            page.locator('[data-info-panel="qr"] [data-pin]').click()
            send('CPUの使用率を教えて')
            assert page.locator('[data-info-panel="qr"]').is_visible()
            assert page.locator('[data-info-panel="weather"]').is_visible()
            # パネルを右に移動し、重なりなく再び左に戻せる。
            move=page.locator('[data-info-panel="system"] button[aria-label="パネルを左右に移動"]')
            move.click()
            assert page.locator('#info-panel-dock [data-info-panel="system"]').count()==1
            move.click()
            assert page.locator('#left-panel-dock [data-info-panel="system"]').count()==1
            page.locator('#close-all-panels').click()
            assert page.locator('[data-info-panel]:visible').count()==0
            before=page.locator('#message').bounding_box()
            page.evaluate("for(let i=0;i<200;i++) addBubble(i%2?'assistant':'user','長い会話の検証。'.repeat(20));")
            after=page.locator('#message').bounding_box()
            assert abs(before['y']-after['y'])<1
            for width,height in [(1920,1080),(1366,768),(1024,768),(390,844)]:
                page.set_viewport_size({'width':width,'height':height})
                box=page.locator('#message').bounding_box()
                assert box['y']>=0 and box['y']+box['height']<=height
                assert page.evaluate('document.documentElement.scrollHeight<=innerHeight'), (width,height,page.evaluate('({scroll:document.documentElement.scrollHeight,body:document.body.scrollHeight,shell:document.querySelector(".jarvis-shell").getBoundingClientRect().toJSON()})'))
            session=page.locator('#session-id').input_value()
            csv=page.request.get(base+'/processing/export.csv?session_id='+session)
            assert csv.status==200 and 'server_local_llm_sec' in csv.text()
            assert not errors,errors
            browser.close()
    finally:
        http.shutdown(); http.server_close()

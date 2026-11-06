import threading
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright
import local_ai_server as server
from models import execution_trace
from models.evaluation_metrics import EvaluationMetrics


@pytest.mark.e2e
def test_cloud_default_local_calculation_and_manual_delegation(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path);calls=[]
    monkeypatch.setattr(server,'evaluation_metrics',EvaluationMetrics(str(tmp_path/'evaluation.jsonl')))
    monkeypatch.setattr(execution_trace,'LOG_PATH',tmp_path/'processing.jsonl')
    def cloud(prompt):calls.append(prompt);return 'クラウドAIによる回答です。研究の目的、実装、評価を整理しましょう。'
    monkeypatch.setattr(server,'_ask_cloud_ai',cloud)
    def forbidden(*args,**kwargs):raise AssertionError('Default routing must not generate locally')
    monkeypatch.setattr(server,'_generate_llm_response',forbidden)
    monkeypatch.setattr(server,'ask_local_llm_json',forbidden)
    server._clear_all_sessions()
    http=server.QuietThreadingHTTPServer(('127.0.0.1',0),server.LocalAIServerHandler)
    threading.Thread(target=http.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1000});errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{http.server_port}',wait_until='commit',timeout=60000)
            page.wait_for_function("window.memoryNetwork && document.getElementById('runtime-model')?.textContent==='gpt-4.1-mini'",timeout=60000)
            assert 'クラウド対話が標準' in page.locator('#chat-log').inner_text()
            def send(text):
                page.locator('#message').fill(text);page.locator('#send-btn').click()
                page.wait_for_function("!document.getElementById('send-btn').disabled")
            send('卒業研究の構成を提案して')
            assert len(calls)==1
            answer=page.locator('#chat-log .bubble.assistant').last
            assert 'クラウドAIによる回答' in answer.inner_text()
            assert answer.locator('[data-cloud-delegate]').count()==0
            send('10+20を計算して')
            assert len(calls)==1
            local=page.locator('#chat-log .bubble.assistant').nth(1)
            assert '30' in local.inner_text() and 'ローカル機能' in local.inner_text()
            button=local.locator('[data-cloud-delegate]');assert button.count()==1
            assert local.get_by_role('button',name='クラウドで再生成',exact=True).count()==0
            page.screenshot(path=str(Path(server.__file__).parent/'work/cloud-first-local-routing.png'))
            page.on('dialog',lambda d:d.accept());button.click()
            page.wait_for_function("!document.getElementById('send-btn').disabled")
            assert len(calls)==2 and '10+20' in calls[1]
            assert button.is_disabled()
            assert 'クラウド（OpenAI API）で生成した追加回答' in page.locator('#chat-log').inner_text()
            page.screenshot(path=str(Path(server.__file__).parent/'work/cloud-first-manual-delegation.png'))
            page.locator('#research-open').click()
            page.wait_for_function("document.querySelector('.research-status').textContent.includes('対象 3件')")
            assert 'CLOUD_FIRST' in page.locator('.research-table-wrap').inner_text()
            page.locator('#research-dialog').get_by_role('button',name='閉じる',exact=True).click()
            page.set_viewport_size({'width':390,'height':844})
            box=page.locator('#message').bounding_box();assert box['y']>=0 and box['y']+box['height']<=844
            assert not errors,errors
            browser.close()
    finally:http.shutdown();http.server_close()

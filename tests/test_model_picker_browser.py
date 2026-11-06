import json,threading
from pathlib import Path
from types import SimpleNamespace as N
import pytest
from playwright.sync_api import sync_playwright
import local_ai_server as server
from cloud import model_catalog as catalog,free_pool
from models import execution_trace
from models.evaluation_metrics import EvaluationMetrics

@pytest.mark.e2e
def test_model_picker_free_selection_and_exhaustion(tmp_path,monkeypatch):
    monkeypatch.setattr(catalog,'DEFAULT_MODEL','free-auto')
    monkeypatch.setattr(server,'evaluation_metrics',EvaluationMetrics(str(tmp_path/'evaluation.jsonl')))
    monkeypatch.setattr(execution_trace,'LOG_PATH',tmp_path/'trace.jsonl')
    calls=[]
    def fake(prompt):
        calls.append(catalog.current()['id'])
        catalog.set_outcome({'free':True,'provider':'openrouter','model':'google/gemma-4-31b-it:free','cloud_attempted':True})
        return '無料のクラウドAIで卒業研究の進め方を整理しました。'
    monkeypatch.setattr(server,'_ask_cloud_ai',fake)
    http=server.QuietThreadingHTTPServer(('127.0.0.1',0),server.LocalAIServerHandler)
    threading.Thread(target=http.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1000});errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            base=f'http://127.0.0.1:{http.server_port}'
            page.goto(base,wait_until='commit',timeout=60000)
            page.locator('#cloud-model-open').click(timeout=60000)
            dialog=page.locator('#cloud-model-dialog')
            page.wait_for_function("document.querySelector('#cloud-model-dialog').textContent.includes('GPT-4.1 nano')")
            assert '無料枠を自動切替' in page.locator('#cloud-model-open').inner_text()
            assert '月固定' in dialog.inner_text() and '性能' in dialog.inner_text()
            page.get_by_label('APIキー',exact=True).fill('fake-secret-key')
            page.get_by_role('button',name='APIキーを保存',exact=True).click()
            page.wait_for_function("document.querySelector('#cloud-model-dialog [role=status]').textContent.includes('保存しました')")
            assert page.get_by_label('APIキー',exact=True).input_value()==''
            assert 'fake-secret-key' not in page.request.get(base+'/cloud-models').text()
            page.locator('[data-model-id="openai-mini"]').click()
            page.wait_for_function("document.querySelector('#cloud-model-open').textContent.includes('GPT-4.1 mini')")
            page.locator('[data-model-id="free-auto"]').click()
            page.wait_for_function("document.querySelector('#cloud-model-open').textContent.includes('無料枠を自動切替')")
            page.screenshot(path=str(Path(server.__file__).parent/'work/free-model-picker-desktop.png'))
            page.set_viewport_size({'width':390,'height':844})
            assert dialog.evaluate('(e)=>e.getBoundingClientRect().width')<=390
            page.screenshot(path=str(Path(server.__file__).parent/'work/free-model-picker-mobile.png'))
            page.set_viewport_size({'width':1440,'height':1000})
            dialog.get_by_role('button',name='閉じる',exact=True).click()
            page.locator('#message').fill('卒業研究の進め方を整理して')
            page.locator('#send-btn').click()
            page.wait_for_function("document.querySelector('#chat-log').textContent.includes('クラウド利用あり／API利用料金なし（無料枠）')")
            assert calls==['free-auto']
            def exhausted(prompt):
                catalog.set_outcome({'switch_required':True,'free':True,'cloud_attempted':False})
                raise free_pool.FreePoolExhausted([])
            monkeypatch.setattr(server,'_ask_cloud_ai',exhausted)
            page.locator('#message').fill('別の研究テーマも提案してください')
            page.locator('#send-btn').click()
            page.wait_for_function("document.querySelector('#cloud-model-open').textContent.includes('無料枠を利用できません')")
            assert page.request.post(base+'/cloud-models',data={'action':'select','model_id':'openai-full'}).status==403
            assert not errors,errors
            browser.close()
    finally:http.shutdown();http.server_close()

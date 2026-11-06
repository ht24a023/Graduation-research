import json
import threading
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright
import local_ai_server as server
from functions.work_memory import WorkMemory
from models import execution_trace
from models.evaluation_metrics import EvaluationMetrics


@pytest.mark.e2e
def test_background_summary_is_visible_editable_and_never_clobbers_input(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path);summary_calls=[];main_calls=[]
    def summary(prompt):
        summary_calls.append(prompt)
        return json.dumps({'purpose':'卒業研究のクラウド対話とローカル処理を実装する','decisions':['通常会話はクラウドを利用する'],'progress':['設計方針を会話で確認した。実機検証は未確認。'],'open_issues':['実験の実施は未確認'],'next_actions':['実験条件を整理する（未実施）']},ensure_ascii=False)
    service=WorkMemory(summary,debounce=.03,min_interval=.03)
    monkeypatch.setattr(server,'work_memory',service)
    monkeypatch.setattr(server,'evaluation_metrics',EvaluationMetrics(str(tmp_path/'evaluation.jsonl')))
    monkeypatch.setattr(execution_trace,'LOG_PATH',tmp_path/'processing.jsonl')
    def main(prompt):main_calls.append(prompt);return '通常会話をクラウドにし、計算と日時をローカルで処理する方針を提案します。実機の確認はこれからです。'
    monkeypatch.setattr(server,'_ask_cloud_ai',main)
    http=server.QuietThreadingHTTPServer(('127.0.0.1',0),server.LocalAIServerHandler)
    threading.Thread(target=http.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1100});errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{http.server_port}',wait_until='commit',timeout=60000)
            page.wait_for_function('window.memoryNetwork && window.dashboardRequest && window.workbench',timeout=60000)
            page.locator('#message').fill('卒業研究のクラウド対話とローカル処理の構成を考えたい')
            page.locator('#send-btn').click();page.wait_for_function("!document.getElementById('send-btn').disabled")
            page.locator('#neural-open').click()
            page.wait_for_function("document.getElementById('work-memory-status').textContent.includes('記憶に保存済み')")
            page.locator('#work-memory-open').click()
            page.wait_for_function("document.querySelector('.neural-editor textarea').value.includes('【目的】')")
            original_title=page.get_by_label('記憶のタイトル').input_value()
            assert 'AI生成' in page.locator('.neural-editor p').inner_text()
            draft='利用者が編集中の作業内容。勝手に変更しない。'
            page.get_by_label('記憶の内容').fill(draft)
            page.locator('#work-memory-retry').click()
            page.wait_for_function("document.getElementById('work-memory-status').textContent.includes('編集中の入力は保持')")
            assert page.get_by_label('記憶の内容').input_value()==draft
            page.locator('.neural-editor').get_by_role('button',name='保存',exact=True).click()
            page.wait_for_function("document.querySelector('.neural-editor p').textContent.includes('ユーザー編集済み')")
            page.locator('#neural-memory').get_by_role('button',name='閉じる',exact=True).click()
            page.locator('#message').fill('卒業研究の次の確認項目も整理してほしい')
            page.locator('#send-btn').click();page.wait_for_function("!document.getElementById('send-btn').disabled")
            page.locator('#neural-open').click()
            page.wait_for_function("document.getElementById('work-memory-status').textContent.includes('更新案を保存')")
            assert page.request.get(f'http://127.0.0.1:{http.server_port}/memory/graph').json()['nodes'][0]['content']==draft
            page.locator('#work-memory-open').click()
            page.wait_for_function("document.querySelector('.neural-editor input').value.includes('更新案')")
            page.screenshot(path=str(Path(server.__file__).parent/'work/cloud-work-summary-network.png'))
            page.locator('#work-memory-enabled').uncheck()
            page.wait_for_function("document.getElementById('work-memory-status').textContent==='作業要約：オフ'")
            assert len(main_calls)==2 and len(summary_calls)==3
            assert not errors,errors
            browser.close()
    finally:service.stop();http.shutdown();http.server_close()

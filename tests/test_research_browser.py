import json
import threading
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright
import local_ai_server as server
from models import execution_trace,user_profile_memory as memory
from models.evaluation_metrics import EvaluationMetrics


@pytest.mark.e2e
def test_research_report_and_memory_provenance(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    metrics=EvaluationMetrics(str(tmp_path/'evaluation.jsonl'))
    monkeypatch.setattr(server,'evaluation_metrics',metrics)
    monkeypatch.setattr(execution_trace,'LOG_PATH',tmp_path/'processing.jsonl')
    monkeypatch.setattr(server,'classify_intent',lambda _: 'chat')
    monkeypatch.setattr(server,'ask_local_llm',lambda *a,**k:'保存メモでは音声入力の停止操作を確認済みです。')
    monkeypatch.setattr(server,'stream_local_llm',lambda *a,**k:iter(['保存メモでは音声入力の停止操作を確認済みです。']))
    def forbidden(*a,**k):return '保存メモでは音声入力の停止操作を確認済みです。'
    monkeypatch.setattr(server,'ask_cloud_ai',forbidden)
    for i,(mode,seconds,ok,cloud,rating) in enumerate([('LOCAL_ONLY',1.,True,False,'good'),('FIXED_ROUTING',3.,False,True,'bad'),('DYNAMIC_ROUTING',2.,True,False,'')]):
        record=metrics.build_record(request_id=f'probe-{i}',experiment_mode=mode,test_case_id='case-one',entry_point='isolated-test',input_text='PRIVATE-PROMPT-NOT-FOR-EXPORT',response_text='テスト回答',route='test',response_time_sec=seconds,local_time_sec=seconds,cloud_time_sec=0,api_called=cloud,success=ok)
        metrics.save(record)
        if rating:metrics.set_user_feedback(f'probe-{i}',rating)
    memory.upsert_titled_note('音声入力の実験','停止操作を確認した。応答速度は未測定。')
    http=server.QuietThreadingHTTPServer(('127.0.0.1',0),server.LocalAIServerHandler)
    threading.Thread(target=http.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1000});errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{http.server_port}',wait_until='domcontentloaded')
            page.locator('#research-open').click()
            page.wait_for_function("document.querySelector('.research-status').textContent.includes('対象 3件')")
            assert '66.7%' in page.locator('.research-cards').inner_text()
            assert '3モード共通の実験ID：1件' in page.locator('.research-definitions').inner_text()
            assert 'PRIVATE-PROMPT' not in page.locator('#research-dialog').inner_text()
            page.screenshot(path=str(Path(server.__file__).parent/'work/research-report-desktop.png'))
            with page.expect_download() as download:page.get_by_role('button',name='集計JSONを保存').click()
            exported=Path(download.value.path()).read_text(encoding='utf-8')
            assert 'PRIVATE-PROMPT' not in exported and json.loads(exported)['overall']['count']==3
            page.get_by_label('集計する実験モード').select_option('LOCAL_ONLY')
            page.wait_for_function("document.querySelector('.research-status').textContent.includes('対象 1件')")
            page.get_by_label('実験ID付きのみ').check()
            page.wait_for_function("!document.querySelector('.research-tools button').disabled")
            page.set_viewport_size({'width':390,'height':844})
            assert page.locator('#research-dialog').evaluate('e=>e.scrollWidth<=e.clientWidth+1')
            page.screenshot(path=str(Path(server.__file__).parent/'work/research-report-mobile.png'))
            page.locator('#research-dialog').get_by_role('button',name='閉じる',exact=True).click()
            page.set_viewport_size({'width':1440,'height':1000})
            page.locator('#message').fill('音声入力の実験の続きを相談したい')
            page.locator('#send-btn').click()
            page.wait_for_function("!document.getElementById('send-btn').disabled")
            page.locator('#neural-open').click()
            page.wait_for_function("document.querySelector('.neural-status').textContent.startsWith('1件')")
            assert '音声入力の実験' in page.locator('#neural-context').inner_text()
            assert page.locator('.neural-list button[data-context="true"]').count()==1
            page.screenshot(path=str(Path(server.__file__).parent/'work/research-memory-context.png'))
            assert not errors,errors
            browser.close()
    finally:http.shutdown();http.server_close()

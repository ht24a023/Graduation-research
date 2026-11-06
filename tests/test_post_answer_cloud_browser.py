import json
import threading
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright
import local_ai_server as server
from models import execution_trace
from models.evaluation_metrics import EvaluationMetrics
from functions.system_monitor import SystemMonitor


@pytest.mark.e2e
def test_post_answer_button_confirms_then_generates_cloud_answer(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path);calls=[]
    monkeypatch.setattr(server,'ROUTING_MODE_DEFAULT','DYNAMIC_ROUTING')
    monkeypatch.setattr(server,'evaluation_metrics',EvaluationMetrics(str(tmp_path/'evaluation.jsonl')))
    monkeypatch.setattr(execution_trace,'LOG_PATH',tmp_path/'processing.jsonl')
    def cloud(prompt):calls.append(prompt);return 'クラウドに委託して生成した追加の回答です。'
    monkeypatch.setattr(server,'ask_cloud_ai',cloud)
    http=server.QuietThreadingHTTPServer(('127.0.0.1',0),server.LocalAIServerHandler)
    threading.Thread(target=http.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1000});errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{http.server_port}',wait_until='domcontentloaded')
            page.locator('#message').fill('こんにちは');page.locator('#send-btn').click()
            page.wait_for_function("!document.getElementById('send-btn').disabled")
            answer=page.locator('#chat-log .bubble.assistant').filter(has_text='こんにちは。ローカルで応答しています。')
            button=answer.locator('[data-cloud-delegate]')
            assert button.count()==1 and not calls
            assert page.locator('.cloud-check-btn').count()==0
            page.screenshot(path=str(Path(server.__file__).parent/'work/post-answer-cloud-button.png'))
            dismiss=lambda d:d.dismiss();page.on('dialog',dismiss);button.click()
            assert not calls
            page.remove_listener('dialog',dismiss);page.on('dialog',lambda d:d.accept())
            button.click();page.wait_for_function("!document.getElementById('send-btn').disabled")
            assert len(calls)==1 and 'こんにちは' in calls[0]
            assert 'クラウド（OpenAI API）で生成した追加回答' in page.locator('#chat-log').inner_text()
            assert 'こんにちは。ローカルで応答しています。' in answer.inner_text()
            assert button.is_disabled()
            page.screenshot(path=str(Path(server.__file__).parent/'work/post-answer-cloud-desktop.png'))
            monkeypatch.setattr(server,'ask_local_llm',lambda *a,**k:'（ローカルLLM応答は空でした）')
            page.locator('#message').fill('ローカルモデルで研究の説明をして')
            page.locator('#send-btn').click()
            page.wait_for_function("!document.getElementById('send-btn').disabled")
            assert page.locator('#chat-log .bubble.assistant').last.locator('[data-cloud-delegate]').count()==1
            assert len(calls)==1
            assert button.is_disabled()
            assert not errors,errors
            browser.close()
    finally:http.shutdown();http.server_close()


@pytest.mark.e2e
def test_telemetry_layout_shows_activity_separately_and_survives_failure(tmp_path,monkeypatch):
    monitor=SystemMonitor();sample=monitor.snapshot();monitor.stop()
    sample['sampled_at']=1000
    sample['cpu'].update(usage_percent=44,logical_cores=8)
    sample['disk'].update(usage_percent=95,active_percent=6)
    sample['process'].update(system_process_count=123,system_thread_count=4567,threads=3)
    monkeypatch.chdir(tmp_path)
    http=server.QuietThreadingHTTPServer(('127.0.0.1',0),server.LocalAIServerHandler)
    threading.Thread(target=http.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];broken=[False]
            page.on('pageerror',lambda e:errors.append(str(e)))
            def serve(route):
                data={'ok':False,'error':'test unavailable'} if broken[0] else sample
                route.fulfill(status=503 if broken[0] else 200,content_type='application/json',body=json.dumps(data))
            page.route('**/system/metrics',serve)
            page.goto(f'http://127.0.0.1:{http.server_port}',wait_until='domcontentloaded')
            page.wait_for_function("document.getElementById('hud-cpu')?.textContent==='44.0%'")
            assert page.locator('#hud-disk').inner_text()=='6.0%'
            assert page.locator('#hud-processes').inner_text()=='4567 / 123'
            page.evaluate("""sample=>{for(let i=0;i<2;i++){const data=structuredClone(sample);data.sampled_at+=i+1;data.process.server_uptime_sec=100+i;data.process.cpu_time_seconds={user:10+i*2,system:0};window.dispatchEvent(new CustomEvent('jarvis:system-metrics',{detail:data}));}}""",sample)
            assert abs(page.evaluate('window.leftMonitorAudit.inspect().backend_cpu_percent')-25)<.01
            page.screenshot(path=str(Path(server.__file__).parent/'work/task-manager-metrics-desktop.png'))
            broken[0]=True
            page.wait_for_function("document.getElementById('monitor-status').textContent==='取得停止'",timeout=12000)
            assert page.locator('#hud-cpu').inner_text()=='44.0%'
            assert page.locator('#system-monitor-content .metric').count()>=3
            page.set_viewport_size({'width':390,'height':844})
            box=page.locator('#message').bounding_box();assert box['y']>=0 and box['y']+box['height']<=844
            assert not errors,errors
            browser.close()
    finally:http.shutdown();http.server_close()

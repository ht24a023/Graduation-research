"""Real HTTP/browser regression for session-scoped measurement and history tools."""
import json
import threading

import pytest
from playwright.sync_api import sync_playwright
import local_ai_server as server
from models import execution_trace
from models.evaluation_metrics import EvaluationMetrics


@pytest.mark.e2e
def test_history_filters_statistics_export_and_session_reset(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(execution_trace, 'LOG_PATH', tmp_path/'processing.jsonl')
    monkeypatch.setattr(server, 'evaluation_metrics', EvaluationMetrics(str(tmp_path/'evaluation.jsonl')))
    for index, (duration, success) in enumerate([(1., True), (2., False), (5., True)]):
        execution_trace.append_log({'event':'server', 'request_id':f'probe{index}', 'session_id':'research-probe', 'created_at':index+1, 'message':f'QR request {index}', 'route':'qr', 'success':success, 'execution':{'server_elapsed_sec':duration,'stage_totals':{'tool':duration},'stages':[]}})
    http=server.QuietThreadingHTTPServer(('127.0.0.1',0),server.LocalAIServerHandler)
    threading.Thread(target=http.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1000})
            errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{http.server_port}',wait_until='domcontentloaded')
            page.wait_for_function('window.workbench && window.dashboardPanels')
            page.locator('#session-id').fill('research-probe')
            page.locator('#session-id').dispatch_event('change')
            page.locator('[data-open-panel="history"]').click()
            page.wait_for_function("document.getElementById('history-count').textContent==='3 / 3件'")
            assert '66.7%' in page.locator('#performance-result').inner_text()
            assert '2.000 秒' in page.locator('#performance-result').inner_text()
            page.locator('#history-status').select_option('failure')
            assert page.locator('.processing-item').count()==1
            page.locator('#history-query').fill('missing')
            assert page.locator('.processing-item').count()==0
            with page.expect_download() as download:
                page.locator('#export-processing-json').click()
            data=json.loads(download.value.path().read_text(encoding='utf-8'))
            assert data['session_id']=='research-probe' and len(data['records'])==3
            assert all('start' not in row for row in data['records'])
            page.locator('#session-id').fill('empty-session')
            page.locator('#session-id').dispatch_event('change')
            page.wait_for_function("document.getElementById('history-count').textContent==='0 / 0件'")
            assert page.locator('#performance-chart svg').count()==0
            assert page.locator('#hud-request-count').inner_text()=='0'
            assert not errors,errors
            browser.close()
    finally:
        http.shutdown();http.server_close()

"""Real HTTP/browser data routing, stable windows, limits and navigation retention."""
import threading
import pytest
from playwright.sync_api import sync_playwright
import local_ai_server as server
from functions import mission_control,apple_sync
from models import execution_trace
from models.evaluation_metrics import EvaluationMetrics

@pytest.fixture
def ui(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(apple_sync,'PATH',tmp_path/'apple.json');monkeypatch.setattr(apple_sync,'CREDS',None);monkeypatch.setattr(apple_sync,'COLLECTIONS',{})
    monkeypatch.setattr(mission_control,'STORE_PATH',tmp_path/'mission.json')
    monkeypatch.setattr(execution_trace,'LOG_PATH',tmp_path/'processing.jsonl')
    monkeypatch.setattr(server,'evaluation_metrics',EvaluationMetrics(str(tmp_path/'evaluation.jsonl')))
    http=server.QuietThreadingHTTPServer(('127.0.0.1',0),server.LocalAIServerHandler)
    threading.Thread(target=http.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1000})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.clock.install()
            page.goto(f'http://127.0.0.1:{http.server_port}',wait_until='domcontentloaded')
            page.wait_for_selector('#dx-layer')
            page.wait_for_function("document.getElementById('hud-cpu').textContent!=='—'")
            try:yield page
            finally:browser.close()
            assert not errors,errors
    finally:http.shutdown();http.server_close()

@pytest.mark.e2e
def test_counter_details_and_stable_metric_identity(ui):
    page=ui
    page.locator('[data-open-panel="system"]').click()
    metric=page.locator('#system-monitor-content .metric').first
    metric.click()
    win=page.locator('.dx-window');first_id=win.get_attribute('id')
    win.get_by_role('button',name='ピン留め',exact=True).click()
    page.evaluate("document.querySelector('#system-monitor-content .metric strong').textContent='42.0%' ")
    # A changing value must not change the identity of the selected field.
    page.evaluate("window.detailExplorer.openElement(document.querySelector('#system-monitor-content .metric'))")
    assert page.locator('.dx-window').count()==1 and win.get_attribute('id')==first_id
    assert win.get_attribute('data-level')=='2'
    assert 'time_seconds' in win.inner_text()
    win.locator('.dx-field').filter(has=page.get_by_text('time_seconds',exact=True)).get_by_role('button').click()
    win.locator('.dx-tree-item').filter(has_text='idle').first.click()
    assert '秒' in win.inner_text()
    assert page.locator('#message').is_visible()

@pytest.mark.e2e
def test_clock_audio_and_unfetched_panels_are_routed_without_side_effects(ui):
    page=ui
    page.wait_for_function("document.getElementById('clock-time').textContent!=='--:--:--'")
    page.locator('#header-clock').click()
    win=page.locator('.dx-window')
    win.get_by_role('button',name='さらに詳しく ›',exact=True).click()
    assert 'server_response' in win.inner_text() and 'display' in win.inner_text()
    page.evaluate('window.detailExplorer.closeUnpinned()')
    page.locator('[data-open-panel="audio"]').click()
    page.locator('[data-info-panel="audio"] > .panel-header .dx-open-section').click()
    win=page.locator('.dx-window');win.get_by_role('button',name='さらに詳しく ›',exact=True).click()
    assert 'preferences' in win.inner_text() and 'round_trip_samples' in win.inner_text()
    page.evaluate('window.detailExplorer.closeUnpinned()')
    calls=[]
    page.on('request',lambda request:calls.append(request.url) if '/mission/news' in request.url else None)
    page.evaluate("window.detailExplorer.open('news',{identity:'unfetched-news',data:{status:'未取得'}})")
    assert not calls
    assert page.locator('dialog[open]').count()==0

@pytest.mark.e2e
def test_session_change_keeps_pins_and_resets_only_global_inactivity(ui):
    page=ui
    page.locator('.hud-cell').filter(has=page.locator('#hud-cpu')).click()
    cpu=page.locator('.dx-window').first
    cpu.get_by_role('button',name='ピン留め',exact=True).click()
    page.locator('.hud-cell').filter(has=page.locator('#hud-ram')).click()
    page.clock.fast_forward(4100)
    page.locator('#message').fill('入力途中の内容')
    page.evaluate("window.dispatchEvent(new CustomEvent('jarvis:session-reset'))")
    page.clock.fast_forward(4900)
    assert page.locator('.dx-window').count()==2
    page.clock.fast_forward(300)
    assert page.locator('.dx-window').count()==1
    assert page.locator('.dx-window').get_attribute('data-pinned')=='true'
    assert page.locator('#message').input_value()=='入力途中の内容'

@pytest.mark.e2e
def test_capacity_never_evicts_a_window_before_idle_and_redacts_secrets(ui):
    page=ui
    page.evaluate("""() => {for(let i=0;i<16;i++)window.detailExplorer.open('proof',{identity:'proof-'+i,data:{actual_test_value:i}});} """)
    ids=page.locator('.dx-window').evaluate_all('(nodes)=>nodes.map(n=>n.id)')
    assert len(ids)==16
    page.evaluate("window.detailExplorer.open('proof',{identity:'overflow',data:{value:'new'}})")
    assert page.locator('.dx-window').evaluate_all('(nodes)=>nodes.map(n=>n.id)')==ids
    page.evaluate('window.detailExplorer.closeUnpinned()')
    page.evaluate("window.detailExplorer.open('proof',{identity:'secret-test',data:JSON.parse('{\"password\":\"do-not-display\",\"accessToken\":\"do-not-display\",\"__proto__\":{\"polluted\":true}}')})")
    win=page.locator('.dx-window')
    win.get_by_role('button',name='さらに詳しく ›',exact=True).click()
    win.get_by_role('button',name='さらに詳しく ›',exact=True).click()
    assert 'do-not-display' not in win.inner_text()
    assert page.evaluate('({}).polluted') is None

@pytest.mark.e2e
def test_zero_network_chart_reports_actual_zero(ui):
    page=ui
    page.evaluate("window.detailExplorer.open('network',{identity:'zero-chart',data:{samples:[{sampled_at:100,receive_bytes_sec:0,send_bytes_sec:0},{sampled_at:101,receive_bytes_sec:0,send_bytes_sec:0}]}})")
    win=page.locator('.dx-window')
    win.get_by_role('button',name='さらに詳しく ›',exact=True).click()
    assert '最大 0 bytes/s' in win.inner_text()
    assert '最大 1 bytes/s' not in win.inner_text()

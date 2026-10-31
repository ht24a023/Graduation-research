"""実HTTP/Chromeで常設HUD・入力欄・ローカル操作を検証する。"""
import json
import threading
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright
import local_ai_server as server
from functions.desktop_integration import NotificationHub
from models import execution_trace
from models.evaluation_metrics import EvaluationMetrics


@pytest.fixture
def browser_ui(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(execution_trace, 'LOG_PATH', tmp_path/'processing.jsonl')
    monkeypatch.setattr(server, 'evaluation_metrics', EvaluationMetrics(str(tmp_path/'evaluation.jsonl')))
    monkeypatch.setattr(server, 'notification_hub', NotificationHub())
    http = server.QuietThreadingHTTPServer(('127.0.0.1', 0), server.LocalAIServerHandler)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            page = browser.new_page(viewport={'width':1440,'height':1000})
            errors=[]
            page.on('pageerror',lambda err: errors.append(str(err)))
            base=f'http://127.0.0.1:{http.server_port}'
            yield page,base,errors
            assert not errors,errors
            browser.close()
    finally:
        http.shutdown();http.server_close()


@pytest.mark.e2e
def test_permanent_left_clean_composer_and_real_execution(browser_ui):
    page,base,errors=browser_ui
    page.add_init_script("localStorage.setItem('jarvis-hud-hidden-v1',JSON.stringify(['hardware','cores','trends','capacity','processes']));")
    assist=[]
    page.on('request',lambda request:assist.append(request.url) if '/chat/assist' in request.url else None)
    page.goto(base,wait_until='domcontentloaded')
    page.wait_for_selector('#ops-open')
    assert page.locator('#ai-assist-box').count()==0
    assert page.locator('.composer .quick-grid').count()==0
    for key in ['hardware','cores','trends','capacity','processes']:
        module=page.locator(f'[data-hud-module="{key}"]')
        assert not module.evaluate('(e)=>e.hidden')
        assert module.locator('.hud-module-head button').count()==0
    page.locator('[data-open-panel="system"]').click()
    assert page.locator('.hud-left-overview').is_visible()
    assert page.locator('#ai-core').is_visible()
    page.locator('#hud-mode-toggle').click()
    assert page.locator('.hud-left-overview').is_visible()
    page.locator('#hud-mode-toggle').click()
    page.locator('#close-all-panels').click()
    page.locator('#message').fill('今何時？')
    page.wait_for_timeout(350)
    assert not assist
    page.locator('#send-btn').click()
    page.wait_for_function("!document.getElementById('send-btn').disabled")
    page.locator('#ops-open').click()
    assert '応答完了' in page.locator('#ops-event-list').inner_text()
    page.locator('#ops-command-query').fill('qr')
    page.locator('#ops-command-query').press('Enter')
    assert not page.locator('#ops-console').evaluate('(e)=>e.open')
    assert page.locator('[data-info-panel="qr"]').is_visible()
    page.locator('#close-all-panels').click()
    before=page.locator('#message').bounding_box()
    page.evaluate("for(let i=0;i<200;i++)addBubble(i%2?'assistant':'user','固定入力欄の検証。'.repeat(15));")
    after=page.locator('#message').bounding_box()
    assert abs(before['y']-after['y'])<1
    for width,height in [(1920,1080),(1366,768),(1024,768),(390,844)]:
        page.set_viewport_size({'width':width,'height':height})
        box=page.locator('#message').bounding_box()
        assert 0<=box['y'] and box['y']+box['height']<=height
        assert page.evaluate('document.documentElement.scrollHeight<=innerHeight')


@pytest.mark.e2e
def test_timer_restore_completion_and_alert_transitions(browser_ui):
    page,base,errors=browser_ui
    page.clock.install()
    page.goto(base,wait_until='domcontentloaded')
    page.wait_for_selector('#ops-open')
    page.locator('#ops-open').click()
    page.locator('#ops-timer-minutes').fill('1')
    page.locator('#ops-timer-start').click()
    page.wait_for_timeout(1100)
    page.locator('#ops-timer-pause').click()
    paused=page.locator('#ops-timer-display').inner_text()
    assert paused!='00:00'
    page.reload(wait_until='domcontentloaded')
    page.wait_for_selector('#ops-open')
    page.keyboard.press('Alt+j')
    assert page.locator('#ops-console').evaluate('(e)=>e.open')
    assert page.locator('#ops-timer-display').inner_text()==paused
    page.locator('#ops-timer-start').click()
    page.clock.fast_forward(61000)
    assert page.locator('#ops-timer-state').inner_text()=='完了しました'
    assert '作業タイマーが完了' in page.locator('#ops-event-list').inner_text()
    # ここからは警告表示の試験データ。実PCの取得を証明するものではない。
    page.evaluate("""() => {
      for(let i=0;i<3;i++)window.dispatchEvent(new CustomEvent('jarvis:system-metrics',{detail:{ok:true,sampled_at:100+i,cpu:{usage_percent:98},memory:{usage_percent:40},disk:{usage_percent:50},network:{}}}));
    }""")
    assert 'CPUの高負荷' in page.locator('#ops-alert-list').inner_text()
    page.evaluate("window.dispatchEvent(new CustomEvent('jarvis:system-metrics',{detail:{ok:true,sampled_at:104,cpu:{usage_percent:10},memory:{usage_percent:40},disk:{usage_percent:50},network:{}}}))")
    assert 'CPUの高負荷' not in page.locator('#ops-alert-list').inner_text()
    assert '注意条件を解除' in page.locator('#ops-event-list').inner_text()
    page.locator('#ops-timer-reset').click()
    assert page.locator('#ops-timer-display').inner_text()=='00:00'
    page.keyboard.press('Escape')
    assert not page.locator('#ops-console').evaluate('(e)=>e.open')

"""Real browser coverage for keyboard commands, named layouts, and persistent time tools."""
import threading
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright
import local_ai_server as server
from models import execution_trace
from models.evaluation_metrics import EvaluationMetrics


@pytest.fixture
def app_url(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(server,'evaluation_metrics',EvaluationMetrics(str(tmp_path/'evaluation.jsonl')))
    monkeypatch.setattr(execution_trace,'LOG_PATH',tmp_path/'processing.jsonl')
    http=server.QuietThreadingHTTPServer(('127.0.0.1',0),server.LocalAIServerHandler)
    threading.Thread(target=http.serve_forever,daemon=True).start()
    yield f'http://127.0.0.1:{http.server_port}'
    http.shutdown();http.server_close()


@pytest.mark.e2e
def test_command_palette_and_persistent_timer_stopwatch(app_url):
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(app_url,wait_until='domcontentloaded')
        page.wait_for_selector('#task-command-open')
        page.locator('#message').fill('入力途中の文章')
        before=page.locator('#message').bounding_box()
        page.keyboard.press('Control+k')
        assert page.locator('#task-command-dialog').is_visible()
        page.locator('#task-command-query').fill('CPU');page.keyboard.press('Enter')
        assert page.locator('[data-info-panel="system"]').is_visible()
        assert page.locator('#message').input_value()=='入力途中の文章'
        assert abs(page.locator('#message').bounding_box()['y']-before['y'])<1
        page.keyboard.press('Control+k');page.locator('#task-command-query').fill('25分');page.keyboard.press('Enter')
        page.locator('#task-time-open').click()
        assert page.locator('#task-timer-list .task-timer-row').count()==1
        page.locator('#task-timer-name').fill('完了確認');page.locator('#task-timer-minutes').fill('0');page.locator('#task-timer-seconds').fill('1');page.locator('#task-timer-add').click()
        page.wait_for_selector('.task-timer-row.is-finished',timeout=4000)
        assert '完了' in page.locator('#task-time-open').inner_text()
        page.locator('#task-clear-finished').click();assert page.locator('#task-timer-list .task-timer-row').count()==1
        page.locator('#task-watch-toggle').click();page.wait_for_timeout(350);page.locator('#task-watch-lap').click();page.locator('#task-watch-toggle').click()
        assert page.locator('#task-laps li').count()==1
        page.keyboard.press('Escape');assert page.locator('#task-time-dialog').is_hidden()
        page.reload(wait_until='domcontentloaded');page.locator('#task-time-open').click()
        assert page.locator('#task-timer-list .task-timer-row').count()==1
        assert page.locator('#task-laps li').count()==1
        assert page.locator('#task-watch-value').inner_text()!='00:00:00.0'
        assert '一時停止' in page.locator('#task-watch-toggle').inner_text() or '計測開始' in page.locator('#task-watch-toggle').inner_text()
        page.keyboard.press('Escape');page.keyboard.press('Control+Shift+k')
        assert page.locator('#message').evaluate('el=>el===document.activeElement')
        assert not errors,errors
        browser.close()


@pytest.mark.e2e
def test_monitor_rows_expand_and_pin_without_blocking_other_ui(app_url):
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(app_url,wait_until='domcontentloaded')
        page.locator('[data-open-panel="system"]').click()
        page.wait_for_selector('#system-monitor-content .monitor-detail')
        first=page.locator('#system-monitor-content .monitor-detail').first
        assert first.evaluate('el => !el.classList.contains("is-expanded")')
        first.click()
        page.wait_for_timeout(100)
        assert first.evaluate('el => el.classList.contains("is-expanded")')
        assert page.locator('#message').is_visible()
        page.locator('#system-monitor-content .monitor-detail .monitor-pin').first.click()
        assert first.evaluate('el => el.classList.contains("is-pinned")')
        assert not errors,errors
        browser.close()


@pytest.mark.e2e
def test_named_layout_restores_modules_panel_side_pin_and_mode(app_url):
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(app_url,wait_until='domcontentloaded');page.wait_for_selector('#task-layout-open')
        page.locator('[data-hud-module="environment"] .hud-module-head button').click()
        page.locator('[data-open-panel="weather"]').click()
        weather=page.locator('[data-info-panel="weather"]');weather.locator('[data-pin]').click();weather.locator('button[aria-label="パネルを左右に移動"]').click()
        page.locator('#task-layout-open').click();page.locator('#task-layout-name').fill('研究用');page.locator('#task-layout-save').click()
        page.locator('[data-layout-built-in="focus"]').click();page.keyboard.press('Escape')
        assert not page.locator('body').evaluate("el=>el.classList.contains('max-hud')")
        page.locator('#task-layout-open').click();page.locator('.task-layout-row').filter(has_text='研究用').get_by_role('button',name='適用',exact=True).click();page.keyboard.press('Escape')
        assert page.locator('body').evaluate("el=>el.classList.contains('max-hud')")
        assert page.locator('[data-hud-module="environment"]').evaluate('el=>el.hidden')
        assert page.locator('#left-panel-dock [data-info-panel="weather"]').is_visible()
        assert weather.locator('[data-pin]').get_attribute('aria-pressed')=='true'
        page.reload(wait_until='domcontentloaded');page.locator('#task-layout-open').click()
        assert page.locator('.task-layout-row').filter(has_text='研究用').count()==1
        page.keyboard.press('Escape')
        page.locator('#task-time-open').click()
        page.locator('#task-timer-name').fill('RESEARCH SESSION');page.locator('#task-timer-minutes').fill('25');page.locator('#task-timer-add').click()
        page.screenshot(path='time-tools-test.png')
        page.keyboard.press('Escape')
        for width,height in [(1366,768),(390,844)]:
            page.set_viewport_size({'width':width,'height':height});box=page.locator('#message').bounding_box();assert box['y']>=0 and box['y']+box['height']<=height
        assert not errors,errors
        browser.close()

"""実HTTP/Chromeで通知UIを検証。注入データはOS通知の実取得とは区別する。"""
from contextlib import contextmanager
import json
from pathlib import Path
import threading
import time

import pytest
from playwright.sync_api import sync_playwright
import local_ai_server as server
from functions.desktop_integration import NotificationHub
from models import execution_trace
from models.evaluation_metrics import EvaluationMetrics


@pytest.fixture
def service(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    hub=NotificationHub()
    monkeypatch.setattr(server,'notification_hub',hub)
    monkeypatch.setattr(server,'evaluation_metrics',EvaluationMetrics(str(tmp_path/'evaluation.jsonl')))
    monkeypatch.setattr(execution_trace,'LOG_PATH',tmp_path/'processing.jsonl')
    http=server.QuietThreadingHTTPServer(('127.0.0.1',0),server.LocalAIServerHandler)
    threading.Thread(target=http.serve_forever,daemon=True).start()
    yield f'http://127.0.0.1:{http.server_port}',hub
    http.shutdown();http.server_close()


@pytest.mark.e2e
def test_notification_auth_and_same_origin_guards(service):
    base,hub=service
    with sync_playwright() as p:
        request=p.request.new_context()
        assert request.post(base+'/notifications/bridge',data={'state':'allowed'}).status==401
        assert request.post(base+'/notifications/settings',data={'enabled':True}).status==403
        assert request.post(base+'/notifications/settings',headers={'Origin':'https://external.example','X-Jarvis-Notifications':'1'},data={'enabled':True}).status==403
        assert not hub.settings()['enabled']
        assert request.get(base+'/notifications/events?cursor=no&mode=INFO').status==400
        request.dispose()


@pytest.mark.e2e
def test_notifications_queue_chat_suppression_close_disable_and_fixed_layout(service,tmp_path):
    base,hub=service
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(base,wait_until='domcontentloaded')
        page.wait_for_function("window.desktopIntegration && document.getElementById('header-clock')")
        page.wait_for_function("document.getElementById('clock-time').textContent !== '--:--:--'")
        assert page.locator('#header-clock #clock-date').is_visible()
        before=page.locator('#message').bounding_box()
        # 既定OFF。OSデータを読まず、認証済みブリッジの試験データを送る。
        def send(id,title='UI試験通知'):
            return page.request.post(base+'/notifications/bridge',headers={'Authorization':'Bearer '+hub._token},data={'state':'allowed','notifications':[{'id':id,'app':'Notification UI Test','title':title,'body':'これはポップアップ検証用の試験データです。','created_at':time.time()}]})
        assert send('off').json()['accepted']==0
        page.locator('#open-workspace').click()
        page.locator('#notifications-duration').fill('2')
        page.locator('#notifications-important-apps').fill('Notification UI Test')
        page.locator('#notifications-enabled').check()
        page.wait_for_function("document.getElementById('notifications-status').textContent.includes('ON')")
        page.locator('#close-workspace').click()
        page.locator('[data-right-mode="INFO"]').click()
        page.wait_for_timeout(100)
        assert send('one','通知1').json()['accepted']==1
        assert send('two','通知2').json()['accepted']==1
        page.wait_for_selector('.notification-toast',timeout=7000)
        assert page.locator('.notification-toast h3').inner_text()=='通知1'
        assert page.locator('.notification-toast').get_attribute('data-priority')=='important'
        page.wait_for_timeout(300)  # スライドイン終了後の領域を確認
        after=page.locator('#message').bounding_box()
        assert abs(before['y']-after['y'])<1
        toast=page.locator('.notification-toast').bounding_box();side=page.locator('.hud-right').bounding_box()
        assert toast['x']>=side['x'] and toast['x']+toast['width']<=side['x']+side['width']+1
        page.wait_for_function("document.querySelector('.notification-toast h3')?.textContent==='通知2'",timeout=6000)
        page.locator('.notification-close').click()
        page.wait_for_selector('.notification-toast',state='detached',timeout=1500)
        page.locator('[data-right-mode="CHAT"]').click()
        send('chat','CHAT中の通知')
        page.wait_for_timeout(1400)
        assert page.locator('.notification-toast').count()==0
        page.locator('[data-right-mode="INFO"]').click()
        page.wait_for_timeout(1300)
        assert page.locator('.notification-toast').count()==0
        page.locator('[data-right-mode="SEARCH"]').click();page.wait_for_timeout(100)
        send('search','SEARCH中の通知')
        page.wait_for_selector('.notification-toast',timeout=5000)
        page.locator('[data-right-mode="CHAT"]').click()
        assert page.locator('.notification-toast').count()==0
        page.locator('#open-workspace').click();page.locator('#notifications-enabled').uncheck()
        page.wait_for_function("document.getElementById('notifications-status').textContent.includes('OFF')")
        page.locator('#close-workspace').click()
        assert not hub.settings()['enabled']
        assert not errors,errors
        browser.close()


@pytest.mark.e2e
def test_header_clock_rollover_uses_server_offset_not_browser_timezone(service):
    from datetime import datetime,timezone,timedelta
    base,hub=service
    stamp=datetime(2026,10,30,23,59,59,tzinfo=timezone(timedelta(hours=5,minutes=30))).timestamp()*1000
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':900},timezone_id='America/Los_Angeles')
        page.route('**/system/clock',lambda route:route.fulfill(json={'ok':True,'source':'backend_pc','epoch_ms':stamp,'utc_offset_minutes':330,'timezone':'Clock fixture +0530'}))
        page.goto(base,wait_until='domcontentloaded')
        page.wait_for_function("document.getElementById('clock-time').textContent==='23:59:59'")
        rect=page.locator('#header-clock').bounding_box()
        page.wait_for_function("document.getElementById('clock-date').textContent==='2026.10.31 SAT'",timeout=4000)
        assert 'UTC+05:30' in page.locator('#clock-zone').inner_text()
        after=page.locator('#header-clock').bounding_box()
        assert abs(rect['width']-after['width'])<1
        assert page.locator('#clock-second-ring').get_attribute('style') is not None
        browser.close()

"""Real HTTP/Chrome CRUD on isolated uploaded calendars and iPhone file snapshots."""
import json
import threading
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright
import local_ai_server as server
from functions import apple_sync as a, mission_control as m
from models import execution_trace
from models.evaluation_metrics import EvaluationMetrics
from test_apple_sync import ICS,phone_snapshot

@pytest.fixture
def ui(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path);monkeypatch.setattr(a,'PATH',tmp_path/'apple.json');monkeypatch.setattr(a,'CREDS',None);monkeypatch.setattr(a,'COLLECTIONS',{})
    monkeypatch.setattr(m,'STORE_PATH',tmp_path/'mission.json');monkeypatch.setattr(execution_trace,'LOG_PATH',tmp_path/'trace.jsonl');monkeypatch.setattr(server,'evaluation_metrics',EvaluationMetrics(str(tmp_path/'evaluation.jsonl')))
    http=server.QuietThreadingHTTPServer(('127.0.0.1',0),server.LocalAIServerHandler);threading.Thread(target=http.serve_forever,daemon=True).start()
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True);page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];page.on('pageerror',lambda error:errors.append(str(error)));base=f'http://127.0.0.1:{http.server_port}'
        page.goto(base,wait_until='domcontentloaded');page.wait_for_selector('[data-open-panel="apple"]');page.locator('[data-open-panel="apple"]').click()
        yield page,base
        assert not errors,errors
        browser.close()
    http.shutdown();http.server_close()


def import_file(page,name,content):
    page.locator('#apple-setup').evaluate('el=>el.open=true')
    page.locator('#apple-upload').set_input_files({'name':name,'mimeType':'text/calendar' if name.endswith('.ics') else 'application/json','buffer':content.encode()})
    page.wait_for_function("document.getElementById('apple-import').disabled===false")
    page.locator('#apple-import').click();page.wait_for_function("document.getElementById('apple-status').textContent.includes('取り込みました')")


@pytest.mark.e2e
def test_uploaded_calendar_reminder_edit_delete_month_and_guard(ui):
    page,base=ui;import_file(page,'calendar.ics',ICS)
    page.wait_for_selector('#apple-list .mc-record')
    row=page.locator('#apple-list .mc-record').filter(has_text='終日テスト');assert row.count()==1
    row.get_by_role('button',name='編集',exact=True).click();page.locator('#apple-title').fill('更新した予定');page.locator('#apple-save').click()
    page.wait_for_selector('#apple-list .mc-record strong:text-is("更新した予定")')
    page.locator('#apple-view-kind').select_option('reminder');page.wait_for_selector('#apple-list .mc-record strong:text-is("提出")')
    page.locator('#apple-list .mc-record').filter(has_text='提出').get_by_role('button',name='完了',exact=True).click()
    page.wait_for_function("document.querySelectorAll('#apple-list .mc-record').length===0")
    page.locator('#apple-show-completed').check();row=page.locator('#apple-list .mc-record').filter(has_text='提出');row.get_by_role('button',name='削除',exact=True).click()
    assert page.locator('#apple-delete-dialog').is_visible();page.locator('#apple-delete-cancel').click();assert row.count()==1
    row.get_by_role('button',name='削除',exact=True).click();page.locator('#apple-delete-confirm').click();page.wait_for_function("document.querySelectorAll('#apple-list .mc-record').length===0")
    page.reload(wait_until='domcontentloaded');page.wait_for_selector('[data-open-panel="apple"]');page.evaluate("window.dashboardPanels.open('apple')")
    page.wait_for_selector('#apple-list .mc-record strong:text-is("更新した予定")')
    assert page.request.post(base+'/apple/mutate',data={'action':'delete'}).status==403
    assert page.request.post(base+'/apple/mutate',headers={'X-Jarvis-Mission':'1','Origin':'https://bad.example'},data={'action':'delete'}).status==403
    assert page.request.get(base+'/apple/bridge').status==400
    assert '更新した予定' in page.request.get(base+'/apple/export.ics').text()
    for width,height in [(1366,768),(390,844)]:
        page.set_viewport_size({'width':width,'height':height});box=page.locator('#message').bounding_box();assert box['y']>=0 and box['y']+box['height']<=height
    page.set_viewport_size({'width':1440,'height':1000});page.screenshot(path=r'C:\Users\ht24a023\Documents\Codex\2026-10-30\code\outputs\sotuken-apple-agenda.png')


@pytest.mark.e2e
def test_phone_snapshot_ui_queue_download_and_new_local_event(ui):
    page,base=ui;import_file(page,'iPhone.json',json.dumps(phone_snapshot(),ensure_ascii=False))
    page.locator('#apple-view-kind').select_option('reminder');row=page.locator('#apple-list .mc-record').filter(has_text='元の用件')
    row.get_by_role('button',name='編集',exact=True).click();page.locator('#apple-title').fill('iPhoneへ戻す用件');page.locator('#apple-save').click()
    page.wait_for_selector('#apple-list .mc-record strong:text-is("iPhoneへ戻す用件")')
    assert 'iPhone反映待ち' in page.locator('#apple-list').inner_text()
    assert page.locator('#apple-list .mc-record').get_by_role('button',name='編集',exact=True).is_disabled()
    page.locator('#apple-setup').evaluate('el=>el.open=true')
    with page.expect_download() as download:page.locator('#apple-export-jobs').click()
    result=json.loads(Path(download.value.path()).read_text(encoding='utf-8'));assert result['jobs'][0]['item']['title']=='iPhoneへ戻す用件'
    page.locator('#apple-kind').select_option('event');page.locator('#apple-target').select_option('local-events');page.locator('#apple-title').fill('追加した予定');page.locator('#apple-all-day').check();page.locator('#apple-start').fill('2026-11-15');page.locator('#apple-end').fill('2026-11-16');page.locator('#apple-save').click()
    page.wait_for_selector('#apple-list .mc-record strong:text-is("追加した予定")')
    assert page.locator('#apple-month button[data-date="2026-11-15"]').inner_text().endswith('1件')
    script=page.request.get(base+'/apple/iphone-script.js').text();assert 'new Request(' not in script and 'DocumentPicker.export(out)' in script

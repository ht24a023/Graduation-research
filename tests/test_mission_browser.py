"""Actual HTTP + Chrome tests; external accounts and physical devices are not exercised."""
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright
import local_ai_server as server
from functions import mission_control as mc
from models import execution_trace
from models.evaluation_metrics import EvaluationMetrics

@pytest.fixture
def ui(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(mc,'STORE_PATH',tmp_path/'mission.json')
    monkeypatch.setattr(execution_trace,'LOG_PATH',tmp_path/'processing.jsonl')
    monkeypatch.setattr(server,'evaluation_metrics',EvaluationMetrics(str(tmp_path/'evaluation.jsonl')))
    for key in ['JARVIS_HOME_URL','JARVIS_HOME_TOKEN','JARVIS_GRAPH_TOKEN']:monkeypatch.delenv(key,raising=False)
    http=server.QuietThreadingHTTPServer(('127.0.0.1',0),server.LocalAIServerHandler)
    threading.Thread(target=http.serve_forever,daemon=True).start()
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1000})
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        base=f'http://127.0.0.1:{http.server_port}'
        page.goto(base,wait_until='domcontentloaded');page.wait_for_selector('[data-open-panel="mission"]')
        yield page,base,errors
        assert not errors,errors
        browser.close()
    http.shutdown();http.server_close()


def open_panel(page,key):
    page.evaluate('(key)=>window.missionControl.open(key)',key)
    page.wait_for_selector(f'[data-info-panel="{key}"]:not([hidden])')


@pytest.mark.e2e
def test_board_edit_persist_reminder_suppression_and_guard(ui):
    page,base,errors=ui
    open_panel(page,'mission')
    page.locator('#message').fill('入力途中');before=page.locator('#message').bounding_box()
    page.locator('#mc-title').fill('研究タスク');page.locator('#mc-priority').select_option('high');page.locator('#mc-add').click()
    page.wait_for_selector('#mc-board .mc-record')
    row=page.locator('#mc-board .mc-record').filter(has_text='研究タスク')
    row.get_by_role('button',name='編集',exact=True).click();page.locator('#mc-title').fill('更新済みタスク');page.locator('#mc-add').click()
    page.wait_for_selector('#mc-board .mc-record strong:text-is("更新済みタスク")')
    assert page.locator('#mc-board .mc-record').count()==1
    assert page.locator('#message').input_value()=='入力途中'
    assert abs(page.locator('#message').bounding_box()['y']-before['y'])<1
    page.reload(wait_until='domcontentloaded');page.wait_for_selector('#mc-board .mc-record strong:text-is("更新済みタスク")',state='attached')
    page.evaluate("window.desktopIntegration.setMode('CHAT')")
    due=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
    response=page.request.post(base+'/mission/board',headers={'X-Jarvis-Mission':'1'},data={'action':'add','title':'抑制する通知','kind':'reminder','due':due})
    assert response.ok
    page.evaluate("window.missionControl.open('mission')")
    page.evaluate("window.desktopIntegration.setMode('CHAT')")
    page.locator('#mc-board-refresh').evaluate('el=>el.click()')
    page.wait_for_function("document.getElementById('mc-due-indicator').textContent.includes('1件')")
    assert page.locator('#mc-toast').is_hidden()
    page.evaluate("window.desktopIntegration.setMode('INFO')")
    page.wait_for_timeout(1200);assert page.locator('#mc-toast').is_hidden()
    assert page.request.post(base+'/mission/board',data={'action':'add','title':'blocked'}).status==403
    assert page.request.post(base+'/mission/device',headers={'X-Jarvis-Mission':'1','Origin':'https://bad.example'},data={'action':'notepad'}).status==403
    result=page.request.get(base+'/mission/board').json();assert len(result['items'])==2
    response=page.request.post(base+'/mission/device',headers={'X-Jarvis-Mission':'1'},data={'action':'shutdown'})
    assert response.status==400
    ics=page.request.get(base+'/mission/calendar.ics');assert 'BEGIN:VCALENDAR' in ics.text()
    for width,height in [(1366,768),(390,844)]:
        page.set_viewport_size({'width':width,'height':height});box=page.locator('#message').bounding_box();assert box['y']>=0 and box['y']+box['height']<=height


@pytest.mark.e2e
def test_knowledge_lab_capture_and_unconfigured_connectors(ui):
    page,base,errors=ui
    open_panel(page,'knowledge')
    page.locator('#mc-text-file').set_input_files({'name':'実験.txt','mimeType':'text/plain','buffer':'卒研の実測CPU記録。ローカル推論を評価する。'.encode()})
    page.wait_for_function("document.getElementById('mc-import-content').value.includes('実測CPU')")
    page.locator('#mc-import-text').click();page.wait_for_function("document.getElementById('mc-import-status').textContent.includes('保存しました')")
    page.locator('#mc-search-query').fill('実測CPU ローカル');page.locator('#mc-search-button').click()
    page.wait_for_selector('#mc-search-results .mc-record')
    assert '実験.txt' in page.locator('#mc-search-results').inner_text()
    open_panel(page,'lab');page.locator('#mc-expression').fill('(128+64)/3');page.locator('#mc-calc-button').click()
    page.wait_for_function("document.getElementById('mc-lab-result').textContent.includes('64')")
    page.locator('#mc-unit-value').fill('2');page.locator('#mc-unit-from').select_option('km');page.locator('#mc-unit-to').select_option('m');page.locator('#mc-convert').click()
    page.wait_for_function("document.getElementById('mc-lab-result').textContent.includes('2000')")
    open_panel(page,'connect');page.locator('#mc-home-read').click();page.wait_for_function("document.getElementById('mc-connect-status').textContent.includes('JARVIS_HOME_URL')")
    page.locator('#mc-mail-read').click();page.wait_for_function("document.getElementById('mc-connect-status').textContent.includes('JARVIS_GRAPH_TOKEN')")
    open_panel(page,'vision');page.locator('#mc-analyze').click();page.wait_for_function("document.getElementById('mc-vision-status').textContent.includes('静止画を用意')")
    png=page.screenshot(clip={'x':0,'y':0,'width':2,'height':2})
    page.locator('#mc-image-file').set_input_files({'name':'capture.png','mimeType':'image/png','buffer':png})
    page.wait_for_selector('#mc-image',state='visible');page.locator('#mc-analyze').click()
    page.wait_for_function("document.getElementById('mc-vision-status').textContent.includes('モデルを検出')")
    page.locator('#mc-clear-image').click();assert page.locator('#mc-image').is_hidden()
    open_panel(page,'systems');assert page.locator('#mc-capabilities .mc-record').count()>=30
    page.locator('#mc-capability-query').fill('家電');assert page.locator('#mc-capabilities .mc-record').count()==1
    open_panel(page,'briefing');assert '未完了' in page.locator('#mc-brief-content').inner_text()
    page.screenshot(path=r'C:\Users\ht24a023\Documents\Codex\2026-10-30\code\outputs\sotuken-mission-control.png')

@pytest.mark.e2e
def test_spatial_real_geometry_and_opt_in_voice_contract(ui):
    page,base,errors=ui
    open_panel(page,'spatial')
    empty=page.locator('#mc-spatial-canvas').screenshot()
    obj=b'v 0 0 0\nv 10 0 0\nv 0 20 0\nv 0 0 30\nf 1 2 3\nf 1 3 4\nf 1 2 4\nf 2 3 4\n'
    page.locator('#mc-model-file').set_input_files({'name':'tetra.obj','mimeType':'text/plain','buffer':obj})
    page.wait_for_function("document.getElementById('mc-spatial-info').textContent.includes('頂点 4')")
    assert '10.000' in page.locator('#mc-spatial-info').inner_text()
    assert page.locator('#mc-spatial-canvas').screenshot()!=empty
    page.screenshot(path='spatial-test.png')
    page.locator('#mc-spatial-canvas').focus();page.keyboard.press('ArrowRight')
    page.locator('#mc-spatial-clear').click();assert page.locator('#mc-spatial-info').inner_text()==''
    open_panel(page,'voicehub')
    assert page.locator('#mc-voice-start').is_enabled()
    assert page.locator('#mc-voice-autosend').is_checked() is False
    page.evaluate("""() => {window.__starts=0;window.__aborts=0;window.SpeechRecognition=class {start(){window.__starts++;window.__voice=this;this.onstart?.();}abort(){window.__aborts++;this.onend?.();}};}""")
    page.locator('#message').fill('')
    page.locator('#mc-wake-word').fill('AI')
    page.locator('#mc-voice-start').click();assert page.evaluate('window.__starts')==1
    page.evaluate("""() => {const results=[{isFinal:true,0:{transcript:'エーアイ、こんにちは'}}];window.__voice.onresult({resultIndex:0,results});}""")
    assert page.locator('#message').input_value()=='こんにちは'
    assert page.locator('#send-btn').is_enabled()
    page.locator('#mc-voice-stop').click();assert page.evaluate('window.__aborts')>=1
    assert page.locator('#voice-start').is_enabled()

"""Real browser drilldown, global inactivity, concurrent non-modal windows and pins."""
import threading
import pytest
from playwright.sync_api import sync_playwright
import local_ai_server as server
from functions import mission_control,apple_sync
from models import execution_trace
from models.evaluation_metrics import EvaluationMetrics

@pytest.fixture
def ui(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path);monkeypatch.setattr(mission_control,'STORE_PATH',tmp_path/'mission.json');monkeypatch.setattr(apple_sync,'PATH',tmp_path/'apple.json')
    monkeypatch.setattr(execution_trace,'LOG_PATH',tmp_path/'processing.jsonl');monkeypatch.setattr(server,'evaluation_metrics',EvaluationMetrics(str(tmp_path/'evaluation.jsonl')))
    http=server.QuietThreadingHTTPServer(('127.0.0.1',0),server.LocalAIServerHandler);threading.Thread(target=http.serve_forever,daemon=True).start()
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True);page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        page.clock.install();base=f'http://127.0.0.1:{http.server_port}';page.goto(base,wait_until='domcontentloaded');page.wait_for_selector('#dx-layer');page.wait_for_function("document.getElementById('hud-cpu').textContent!=='—'")
        yield page,base
        assert not errors,errors
        browser.close()
    http.shutdown();http.server_close()


def cell(page,key):return page.locator('.hud-cell').filter(has=page.locator('#'+key))
def move_to_right(page,win):
    box=win.locator('.dx-head').bounding_box();page.mouse.move(box['x']+50,box['y']+12);page.mouse.down();page.mouse.move(1050,280,steps=4);page.mouse.up()


@pytest.mark.e2e
def test_three_levels_data_tree_and_non_modal_input(ui):
    page,base=ui
    before=page.locator('#message').bounding_box();cell(page,'hud-cpu').click();win=page.locator('.dx-window');assert win.get_attribute('data-level')=='1'
    win.get_by_role('button',name='さらに詳しく ›',exact=True).click();assert win.get_attribute('data-level')=='2'
    assert 'usage_percent' in win.inner_text() and '論理プロセッサー数' in win.inner_text()
    win.locator('.dx-field').filter(has=page.get_by_text('per_core_percent',exact=True)).get_by_role('button',name='展開して見る',exact=True).click();assert win.get_attribute('data-level')=='3'
    assert win.locator('.dx-tree-item').count()>=1
    win.get_by_role('button',name='ピン留め',exact=True).click();page.clock.fast_forward(6500);assert win.count()==1
    page.locator('#message').fill('詳細を出したまま入力');assert page.locator('#message').input_value()=='詳細を出したまま入力'
    assert page.locator('#message').bounding_box()==before
    assert page.locator('dialog[open]').count()==0
    page.screenshot(path='detail-layers-test.png')


@pytest.mark.e2e
def test_global_idle_extends_across_panels_and_recent_click_raises(ui):
    page,base=ui
    cell(page,'hud-cpu').click();first=page.locator('.dx-window').first;first_id=first.get_attribute('id');move_to_right(page,first)
    cell(page,'hud-ram').click();assert page.locator('.dx-window').count()==2
    second=page.locator('.dx-window').last;assert int(second.evaluate('el=>el.style.zIndex'))>int(first.evaluate('el=>el.style.zIndex'))
    first.locator('.dx-head strong').click();assert int(first.evaluate('el=>el.style.zIndex'))>int(second.evaluate('el=>el.style.zIndex'))
    page.clock.fast_forward(3000);page.locator('[data-open-panel="weather"]').click();assert page.locator('.dx-window').count()==2
    page.clock.fast_forward(3000);page.locator('#message').fill('別画面の操作');assert page.locator('.dx-window').count()==2
    page.clock.fast_forward(4700);assert page.locator('.dx-window').count()==2
    page.clock.fast_forward(400);assert page.locator('.dx-window').count()==0
    assert page.locator('#message').input_value()=='別画面の操作'


@pytest.mark.e2e
def test_pin_unpin_and_auto_updates_do_not_extend_idle(ui):
    page,base=ui
    cell(page,'hud-cpu').click();cpu=page.locator('.dx-window');cpu.get_by_role('button',name='ピン留め',exact=True).click();move_to_right(page,cpu)
    cell(page,'hud-ram').click();page.clock.fast_forward(3500)
    page.evaluate("async()=>{const data=await (await fetch('/system/metrics')).json();window.dispatchEvent(new CustomEvent('jarvis:system-metrics',{detail:data}));}")
    page.clock.fast_forward(1700);assert page.locator('.dx-window').count()==1
    cpu=page.locator('.dx-window');assert cpu.get_attribute('data-pinned')=='true'
    cpu.get_by_role('button',name='固定中',exact=True).click();page.clock.fast_forward(4900);assert cpu.count()==1
    page.clock.fast_forward(300);assert cpu.count()==0


@pytest.mark.e2e
def test_dynamic_records_monitor_pin_and_sensitive_data(ui):
    page,base=ui
    response=page.request.post(base+'/mission/board',headers={'X-Jarvis-Mission':'1'},data={'action':'add','title':'RAMを購入する','details':'予定の詳細メモ','priority':'high'});assert response.ok
    page.locator('[data-open-panel="mission"]').click();page.locator('#mc-board-refresh').click();page.wait_for_selector('#mc-board .mc-record strong:text-is("RAMを購入する")')
    page.locator('#mc-board .mc-record>strong').click();win=page.locator('.dx-window');win.get_by_role('button',name='さらに詳しく ›',exact=True).click();assert '予定の詳細メモ' in win.inner_text() and 'priority' in win.inner_text()
    page.locator('#dx-manager').get_by_role('button',name='すべて閉じる',exact=True).click()
    page.evaluate("window.detailExplorer.open('test',{data:{title:'公開情報',password:'SECRET-NOT-VISIBLE',api_key:'PRIVATE-NOT-VISIBLE',first_token_sec:0.123},title:'検証データ',identity:'security'})")
    win=page.locator('.dx-window');win.get_by_role('button',name='さらに詳しく ›',exact=True).click();win.get_by_role('button',name='さらに詳しく ›',exact=True).click();assert 'SECRET-NOT-VISIBLE' not in win.inner_text() and 'PRIVATE-NOT-VISIBLE' not in win.inner_text();assert '0.123' in win.inner_text()
    page.locator('#dx-manager').get_by_role('button',name='すべて閉じる',exact=True).click()
    page.locator('[data-open-panel="system"]').click();row=page.locator('.monitor-detail').filter(has=page.locator('#network-speed'));row.locator('.monitor-pin').click();win=page.locator('.dx-window');assert win.get_attribute('data-pinned')=='true'
    page.clock.fast_forward(6500);assert win.count()==1
    for width,height in [(1366,768),(390,844)]:
        page.set_viewport_size({'width':width,'height':height});box=page.locator('#message').bounding_box();assert box['y']>=0 and box['y']+box['height']<=height
        rect=win.bounding_box();assert rect['x']>=0 and rect['x']+rect['width']<=width

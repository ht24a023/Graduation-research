"""名前：左. Left-column operation, real monitor integration, fault injection and bounded retention."""
import json,os,threading
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright
import local_ai_server as server
from models import execution_trace
from models.evaluation_metrics import EvaluationMetrics
from functions import mission_control,apple_sync

OUT=Path(r'C:\Users\ht24a023\Documents\Codex\2026-10-30\code\outputs')

@pytest.fixture
def ui(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path);monkeypatch.setattr(execution_trace,'LOG_PATH',tmp_path/'trace.jsonl');monkeypatch.setattr(server,'evaluation_metrics',EvaluationMetrics(str(tmp_path/'evaluation.jsonl')))
    monkeypatch.setattr(mission_control,'STORE_PATH',tmp_path/'mission.json');monkeypatch.setattr(apple_sync,'PATH',tmp_path/'apple.json')
    http=server.QuietThreadingHTTPServer(('127.0.0.1',0),server.LocalAIServerHandler);threading.Thread(target=http.serve_forever,daemon=True).start()
    with sync_playwright() as p:
        browser=p.chromium.launch(channel='chrome',headless=True,args=['--enable-precise-memory-info']);page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        page.clock.install();base=f'http://127.0.0.1:{http.server_port}'
        page.route('**/panel/location-weather*',lambda route:route.fulfill(status=503,content_type='application/json',body='{"ok":false,"error":"位置情報は今回の検証対象外"}'))
        page.goto(base,wait_until='domcontentloaded');page.wait_for_function("window.leftMonitorAudit?.inspect().last_success>0")
        yield page,base,browser
        assert not errors,errors
        browser.close()
    http.shutdown();http.server_close()


def reveal_left(page,selector):
    page.locator(selector).first.evaluate("node=>{const col=document.querySelector('.monitor-column'),sticky=col.querySelector('.ai-core-panel').getBoundingClientRect().height;col.scrollTop+=node.getBoundingClientRect().top-col.getBoundingClientRect().top-sticky-55;}")


@pytest.mark.e2e
def test_left_inventory_controls_detail_windows_and_layout(ui):
    page,base,browser=ui
    assert page.locator('#left-health').get_attribute('data-state')=='live'
    live=page.request.get(base+'/system/metrics').json();assert page.evaluate('window.leftMonitorAudit.inspect().backend_pid')==live['process']['pid']==os.getpid()
    assert '未取得' in page.locator('#left-gpu').inner_text() if not live['gpus'] else page.locator('#left-gpu').inner_text()
    if live['cpu']['temperature_c'] is None:assert '未取得' in page.locator('#left-temperature').inner_text()
    inventory=page.locator('.monitor-column .hud-module,.monitor-column .ai-core-panel,.monitor-column .live-timings').evaluate_all("nodes=>nodes.map(node=>({title:node.querySelector('.panel-header strong,.hud-module-head strong')?.textContent,visible:!node.hidden,detail_button:!!node.querySelector('.dx-open-section,.hud-expand,[aria-label=\"左側リソースの詳細\"]'),text:node.innerText.slice(0,2500)}))")
    OUT.joinpath('left-current-inventory.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2),encoding='utf-8')
    page.locator('#ai-link-rtt').click();assert page.locator('[data-info-panel="audio"]').is_visible();page.locator('#close-all-panels').click()
    page.locator('#speak-enabled').check();page.locator('#speak-enabled').uncheck()
    page.locator('#message').fill('今何時？');page.locator('#send-btn').click();page.wait_for_function("!document.getElementById('send-btn').disabled");assert page.locator('#chat-log .bubble.assistant').count()>=1
    assert page.locator('#live-elapsed').inner_text().strip()!=''
    before=page.locator('.hud-center').bounding_box();composer=page.locator('#message').bounding_box()
    resource=page.locator('[data-left-resource="memory"]').first;reveal_left(page,'[data-left-resource="memory"]');resource.click()
    win=page.locator('.dx-window').last;assert 'memory' in win.inner_text();win.get_by_role('button',name='ピン留め',exact=True).click()
    assert win.get_attribute('data-pinned')=='true'
    original=win.bounding_box();box=win.locator('.dx-head').bounding_box();page.mouse.move(box['x']+40,box['y']+12);page.mouse.down();page.mouse.move(800,300,steps=4);page.mouse.up();assert abs(win.bounding_box()['x']-original['x'])>5 or abs(win.bounding_box()['y']-original['y'])>5
    old=win.bounding_box();page.mouse.move(old['x']+old['width']-3,old['y']+old['height']-3);page.mouse.down();page.mouse.move(old['x']+old['width']-60,old['y']+old['height']-40,steps=3);page.mouse.up();assert win.bounding_box()['width']<old['width']
    page.clock.fast_forward(6000);assert page.locator('.dx-window').count()==1
    page.locator('#message').fill('左側を確認中');assert page.locator('.hud-center').bounding_box()==before and page.locator('#message').bounding_box()==composer
    page.locator('#dx-manager').get_by_role('button',name='すべて閉じる',exact=True).click()
    for module in ['cores','capacity','network']:
        selector=f'[data-hud-module="{module}"] .hud-expand';reveal_left(page,selector);page.locator(selector).click();assert page.locator('.dx-window').count()==1
        page.clock.fast_forward(5100);assert page.locator('.dx-window').count()==0
    # Pin a logical CPU, let its source button be re-created, then refresh the same detail.
    reveal_left(page,'#hud-logical-cpu-0');page.locator('#hud-logical-cpu-0').click();cpu_win=page.locator('.dx-window');cpu_win.get_by_role('button',name='ピン留め',exact=True).click()
    changed=page.request.get(base+'/system/metrics').json();changed['sampled_at']+=25;changed['cpu']['per_core_percent'][0]=37.5
    page.evaluate("data=>window.dispatchEvent(new CustomEvent('jarvis:system-metrics',{detail:data}))",changed)
    cpu_win.get_by_role('button',name='表示値を更新',exact=True).click();assert '37.5' in cpu_win.inner_text()
    page.locator('#dx-manager').get_by_role('button',name='すべて閉じる',exact=True).click()
    reveal_left(page,'#hud-volume-list .hud-volume');page.locator('#hud-volume-list .hud-volume').first.click();disk_win=page.locator('.dx-window');disk_win.get_by_role('button',name='ピン留め',exact=True).click()
    changed['sampled_at']+=25;changed['storage']['volumes'][0]['free_bytes']=12345678
    page.evaluate("data=>window.dispatchEvent(new CustomEvent('jarvis:system-metrics',{detail:data}))",changed)
    disk_win.get_by_role('button',name='表示値を更新',exact=True).click();disk_win.get_by_role('button',name='さらに詳しく ›',exact=True).click();assert '12345678' in disk_win.inner_text()
    page.locator('#dx-manager').get_by_role('button',name='すべて閉じる',exact=True).click()
    layouts=[]
    for width,height in [(1920,1080),(1366,768),(1024,768),(390,844)]:
        page.set_viewport_size({'width':width,'height':height});box=page.locator('#message').bounding_box();assert box['y']>=0 and box['y']+box['height']<=height
        if width>900:
            left=page.locator('.monitor-column').bounding_box();center=page.locator('.hud-center').bounding_box();assert left['x']+left['width']<=center['x']+1
            layouts.append({'viewport':[width,height],'left_width':left['width'],'center_width':center['width'],'input_bottom':box['y']+box['height']})
    OUT.joinpath('left-layout-validation.json').write_text(json.dumps(layouts,indent=2),encoding='utf-8')
    page.set_viewport_size({'width':1440,'height':1000});page.locator('.monitor-column').evaluate('el=>el.scrollTop=0');page.screenshot(path=str(OUT/'sotuken-left-layout-test.png'))
    preview=browser.new_page(viewport={'width':1440,'height':1000});preview.route('**/panel/location-weather*',lambda route:route.fulfill(status=503,content_type='application/json',body='{"ok":false,"error":"対象外"}'));preview.goto(base,wait_until='domcontentloaded');preview.wait_for_function("window.leftMonitorAudit?.inspect().status==='live'");preview.wait_for_timeout(2200);preview.evaluate("async()=>{const data=await (await fetch('/system/metrics')).json();window.dispatchEvent(new CustomEvent('jarvis:system-metrics',{detail:data}));}");preview.screenshot(path=str(OUT/'sotuken-left-audit.png'));reveal_left(preview,'[data-hud-module="network"] .hud-module-head');preview.screenshot(path=str(OUT/'sotuken-left-network-capacity.png'));preview.close()


@pytest.mark.e2e
def test_left_failure_stale_and_recovery_without_invented_values(ui):
    page,base,browser=ui
    previous=page.evaluate('window.leftMonitorAudit.inspect()')
    page.route('**/system/metrics',lambda route:route.fulfill(status=503,content_type='application/json',body='{"ok":false,"error":"fault injection"}'))
    page.clock.fast_forward(3000);page.wait_for_function("window.leftMonitorAudit.inspect().status==='error'")
    assert '取得失敗' in page.locator('#left-health').inner_text() and '前回取得分' in page.locator('#left-health').inner_text()
    assert page.evaluate('window.leftMonitorAudit.inspect().last_success')==previous['last_success']
    page.unroute('**/system/metrics');page.clock.fast_forward(3000);page.wait_for_function("window.leftMonitorAudit.inspect().status==='live'")
    data=page.request.get(base+'/system/metrics').json();page.route('**/system/metrics',lambda route:route.fulfill(content_type='application/json',body=json.dumps(data)))
    page.clock.fast_forward(13000);page.wait_for_function("window.leftMonitorAudit.inspect().status==='stale'")
    assert '更新停止' in page.locator('#left-health').inner_text()


@pytest.mark.e2e
def test_left_history_memory_plateau_and_process_cpu_formula(ui):
    page,base,browser=ui
    sample=page.request.get(base+'/system/metrics').json();cdp=page.context.new_cdp_session(page)
    cdp.send('HeapProfiler.enable')
    async_script="""({sample,count,offset})=>{for(let i=0;i<count;i++){const data={...sample,sampled_at:sample.sampled_at+(offset+i+1)*2.5,cpu:{...sample.cpu,usage_percent:20+(i%60)},network:{...sample.network,receive_bytes_sec:i%17===0?null:1000+i,send_bytes_sec:2000+i},process:{...sample.process,server_uptime_sec:100+(offset+i+1)*2.5,cpu_time_seconds:{user:10+(offset+i+1)*.5,system:5}}};window.dispatchEvent(new CustomEvent('jarvis:system-metrics',{detail:data}));}return Promise.resolve().then(()=>window.leftMonitorAudit.inspect());}"""
    first=page.evaluate(async_script,{'sample':sample,'count':400,'offset':0});cdp.send('HeapProfiler.collectGarbage');heap_first=cdp.send('Runtime.getHeapUsage')['usedSize']
    last=page.evaluate(async_script,{'sample':sample,'count':1200,'offset':400});cdp.send('HeapProfiler.collectGarbage');heap_last=cdp.send('Runtime.getHeapUsage')['usedSize']
    assert first['sample_count']==last['sample_count']==240
    assert max(last['plot_nodes'])<=3
    assert abs(last['backend_cpu_percent']-20/max(1,sample['cpu']['logical_cores']))<.001
    assert heap_last-heap_first<12*1024*1024
    # An unavailable volume must not show an invented 0% bar.
    page.evaluate("sample=>{sample.sampled_at+=10000;sample.storage={volumes:[{device:'X:',available:false,usage_percent:null,total_bytes:null,free_bytes:null}]};window.dispatchEvent(new CustomEvent('jarvis:system-metrics',{detail:sample}));}",sample)
    page.wait_for_function("document.querySelector('.monitor-column .hud-volume progress')?.hidden===true")
    report={'name':'左','method':'実測スナップショットを元に1600更新を注入した負荷試験。実時間の長期運転ではない。','retained_samples_before':first['sample_count'],'retained_samples_after':last['sample_count'],'plot_nodes':last['plot_nodes'],'heap_after_warmup':heap_first,'heap_after_more_updates':heap_last,'heap_growth_bytes':heap_last-heap_first,'simulated_backend_cpu_percent':last['backend_cpu_percent'],'limit':'OS・ブラウザー全体の長時間メモリー無増加を証明するものではない。'}
    OUT.joinpath('left-retention-validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

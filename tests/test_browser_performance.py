"""Regression checks for duplicate transfers and queued browser input."""
import json
import base64
import threading
import urllib.request
from types import SimpleNamespace
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright
import local_ai_server as server
from functions.embedded_browser import BrowserService


def test_unchanged_frame_has_no_body():
    http=BrowserService(('127.0.0.1',0))
    item=SimpleNamespace(frame=b'jpeg-test',sequence=8,last_use=0)
    http.sessions['test']=item
    threading.Thread(target=http.serve_forever,daemon=True).start()
    try:
        def get(after):
            req=urllib.request.Request(f'http://127.0.0.1:{http.server_port}/frame?after={after}',headers={'Origin':'http://localhost:8000','X-Sotuken-Browser':'1','Authorization':'Bearer test'})
            return urllib.request.urlopen(req,timeout=5)
        fresh=get(-1);assert fresh.read()==b'jpeg-test';assert fresh.headers['X-Frame-Sequence']=='8'
        same=get(8);assert same.status==204;assert same.read()==b''
        item.sequence=9;assert get(8).read()==b'jpeg-test'
    finally:http.shutdown();http.server_close()


@pytest.mark.e2e
def test_start_once_and_coalesce_scroll(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    http=server.QuietThreadingHTTPServer(('127.0.0.1',0),server.LocalAIServerHandler)
    threading.Thread(target=http.serve_forever,daemon=True).start()
    calls=[];frames=[];sessions=[];errors=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1000});page.on('pageerror',lambda e:errors.append(str(e)))
            def service(route):
                req=route.request;path=req.url.split(':8766')[-1]
                if path=='/session':sessions.append(1);data={'ok':True,'token':'test'}
                elif path=='/action':calls.append(req.post_data_json);data={'ok':True}
                elif path=='/state':data={'url':'about:blank','title':'','closed':False}
                elif path.startswith('/frame'):
                    frames.append(path)
                    if 'after=-1' in path:
                        route.fulfill(status=200,content_type='image/png',body=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='),headers={'Access-Control-Allow-Origin':'*','Access-Control-Expose-Headers':'X-Frame-Sequence','X-Frame-Sequence':'1'})
                    else:route.fulfill(status=204,headers={'Access-Control-Allow-Origin':'*'})
                    return
                else:data={'ok':True}
                route.fulfill(status=200,content_type='application/json',body=json.dumps(data),headers={'Access-Control-Allow-Origin':'*'})
            page.route('http://127.0.0.1:8766/**',service)
            page.goto(f'http://127.0.0.1:{http.server_port}',wait_until='domcontentloaded')
            page.wait_for_selector('#embedded-browser-screen',state='attached')
            page.evaluate("""()=>{document.getElementById('browser-pane').hidden=false;document.getElementById('browser-search').value='卒研';window.openSotukenBrowser();window.openSotukenBrowser();}""")
            page.wait_for_timeout(1000)
            assert len(sessions)==1
            assert sum('after=-1' in frame for frame in frames)==1
            assert any('after=1' in frame for frame in frames)
            assert not any('youtube.com' in c.get('url','') for c in calls)
            assert any('google.com/search' in c.get('url','') for c in calls)
            calls.clear()
            page.evaluate("""()=>{const el=document.getElementById('embedded-browser-screen');for(let i=0;i<100;i++)el.dispatchEvent(new WheelEvent('wheel',{deltaY:3,bubbles:true,cancelable:true}));}""")
            page.wait_for_timeout(300)
            wheels=[c for c in calls if c['action']=='wheel']
            assert len(wheels)==1 and wheels[0]['dy']==300
            calls.clear()
            page.evaluate("""()=>{const el=document.getElementById('browser-pane');for(let i=0;i<8;i++){el.hidden=true;el.hidden=false;}}""")
            page.wait_for_timeout(300);before=len(frames);page.wait_for_timeout(600)
            assert len(frames)-before<=9
            assert not any(c['action']=='resize' for c in calls)
            page.evaluate("document.getElementById('browser-pane').hidden=true")
            page.wait_for_timeout(200);before=len(frames);page.wait_for_timeout(400)
            assert len(frames)==before
            assert not errors,errors
            browser.close()
    finally:http.shutdown();http.server_close()

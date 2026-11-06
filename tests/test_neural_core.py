import threading
import pytest
from playwright.sync_api import sync_playwright
import local_ai_server as server
from models import user_profile_memory as memory
from functions.memory_graph import mutate, snapshot


def test_graph_persistence_and_context(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mutate({'action':'add','title':'卒研 音声入力','content':'音声入力を確認する'})
    mutate({'action':'add','title':'卒研 音声操作','content':'音声入力と停止操作を確認する'})
    assert len(snapshot()['edges']) == 1
    assert '音声入力' in memory.build_profile_context()
    with pytest.raises(ValueError):
        mutate({'action':'add','title':'卒研 音声入力','content':'上書き不可'})
    mutate({'action':'update','title':'卒研 音声入力','content':'停止を検証'})
    assert memory.load_notes()['notes'][0]['content'] == '停止を検証'
    mutate({'action':'delete','title':'卒研 音声操作'})
    assert len(snapshot()['nodes']) == 1


@pytest.mark.e2e
def test_neural_ui(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    http=server.QuietThreadingHTTPServer(('127.0.0.1',0),server.LocalAIServerHandler)
    threading.Thread(target=http.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1000}); errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(f'http://127.0.0.1:{http.server_port}',wait_until='domcontentloaded')
            page.wait_for_selector('#neural-open')
            # Read other agents' current explanation, then record our work.
            previous=page.locator('#work-description').input_value()
            page.locator('#work-description').fill(previous+'\n[AI Core / 記憶担当] 6配色・4パターン、保存メモ連動の関連図、検索・編集・削除を追加。関連線は共通語から算出。')
            page.locator('#work-description').dispatch_event('input')
            page.get_by_label('Coreの配色').select_option('violet')
            page.get_by_label('Coreの動き').select_option('helix')
            page.screenshot(path=str(__import__('pathlib').Path(server.__file__).parent/'work/neural-core-overview.png'))
            page.locator('#neural-open').click()
            page.get_by_label('記憶のタイトル').fill('卒研 音声入力')
            page.get_by_label('記憶の内容').fill('音声入力の停止機能を確認する')
            page.locator('.neural-editor').get_by_role('button',name='保存',exact=True).click()
            page.wait_for_function("document.querySelector('.neural-status').textContent.startsWith('1件')")
            page.get_by_role('button',name='新しい記憶',exact=True).click()
            page.get_by_label('記憶のタイトル').fill('卒研 音声操作')
            page.get_by_label('記憶の内容').fill('音声入力と停止機能を改善する')
            page.locator('.neural-editor').get_by_role('button',name='保存',exact=True).click()
            page.wait_for_function("document.querySelector('.neural-status').textContent.startsWith('2件の記憶 / 1本')")
            page.screenshot(path=str(__import__('pathlib').Path(server.__file__).parent/'work/neural-core-desktop.png'))
            page.reload();page.locator('#neural-open').click()
            page.wait_for_function("document.querySelector('.neural-status').textContent.startsWith('2件')")
            assert page.get_by_label('Coreの配色').input_value()=='violet'
            page.locator('.neural-list').get_by_role('button',name='卒研 音声入力',exact=True).click()
            page.get_by_label('記憶の内容').fill('音声入力の中断を検証済み')
            page.locator('.neural-editor').get_by_role('button',name='保存',exact=True).click()
            page.wait_for_function("document.querySelector('.neural-status').textContent.startsWith('2件')")
            page.get_by_label('記憶を検索').fill('中断を検証済み')
            assert page.locator('.neural-list button').count()==1
            page.set_viewport_size({'width':390,'height':844})
            page.screenshot(path=str(__import__('pathlib').Path(server.__file__).parent/'work/neural-core-mobile.png'))
            assert page.locator('.neural-dialog').evaluate('e=>e.scrollWidth<=e.clientWidth+1')
            page.on('dialog',lambda d:d.accept())
            page.locator('.neural-editor').get_by_role('button',name='削除',exact=True).click()
            page.wait_for_function("document.querySelector('.neural-status').textContent.startsWith('1件')")
            assert not errors,errors
            browser.close()
    finally:
        http.shutdown();http.server_close()

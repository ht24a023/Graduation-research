"""Actual HTTP/Chrome UI; microphone uses Chrome's synthetic capture device."""
import json
import threading
from pathlib import Path
import pytest
from playwright.sync_api import sync_playwright
import local_ai_server as server
from models import execution_trace
from models.evaluation_metrics import EvaluationMetrics
from functions import mission_control as mission

@pytest.fixture
def sensory(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(execution_trace,'LOG_PATH',tmp_path/'processing.jsonl')
    monkeypatch.setattr(mission,'STORE_PATH',tmp_path/'mission.json')
    monkeypatch.setattr(server,'evaluation_metrics',EvaluationMetrics(str(tmp_path/'evaluation.jsonl')))
    http=server.QuietThreadingHTTPServer(('127.0.0.1',0),server.LocalAIServerHandler)
    threading.Thread(target=http.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True,args=['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream'])
            page=browser.new_page(viewport={'width':1440,'height':1000})
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            base=f'http://127.0.0.1:{http.server_port}'
            try:yield page,base
            finally:
                browser.close()
            assert not errors,errors
    finally:http.shutdown();http.server_close()

@pytest.mark.e2e
def test_audio_controls_reply_style_and_real_rtt(sensory):
    page,base=sensory
    page.goto(base,wait_until='domcontentloaded')
    page.wait_for_selector('#ai-signal')
    assert page.locator('#ai-signal-label').inner_text()=='MIC / OFF'
    page.locator('[data-open-panel="audio"]').click()
    page.wait_for_function("document.getElementById('audio-rtt').textContent.endsWith(' ms')")
    assert page.locator('#audio-rtt-summary').inner_text()
    page.locator('#audio-auto-rtt').uncheck()
    page.locator('#audio-reply-style').select_option('concise')
    page.locator('#audio-rate').fill('1.3');page.locator('#audio-rate').dispatch_event('input')
    page.locator('#audio-pitch').fill('0.9');page.locator('#audio-pitch').dispatch_event('input')
    page.reload(wait_until='domcontentloaded')
    page.wait_for_selector('#ai-signal')
    if not page.locator('#audio-reply-style').is_visible():page.locator('[data-open-panel="audio"]').click()
    assert page.locator('#audio-reply-style').input_value()=='concise'
    assert page.locator('#audio-rate').input_value()=='1.3'
    assert not page.locator('#audio-auto-rtt').is_checked()
    page.locator('#close-all-panels').click()
    requests=[]
    page.on('request',lambda r:requests.append(r.post_data_json) if r.method=='POST' and r.url==base+'/chat' else None)
    page.locator('#message').fill('こんにちは');page.locator('#send-btn').click()
    page.wait_for_function("!document.getElementById('send-btn').disabled")
    assert requests[-1]['reply_style']=='concise'
    assert '文体設定：簡潔' in page.locator('.response-profile').last.inner_text()
    page.locator('[data-open-panel="audio"]').click()
    page.locator('#audio-panel details').click()
    assert '応答完了' in page.locator('#audio-process-log').inner_text()
    with page.expect_download() as download:page.locator('#audio-export-log').click()
    data=json.loads(download.value.path().read_text(encoding='utf-8'))
    assert data['events'] and 'こんにちは' not in json.dumps(data,ensure_ascii=False)
    page.route('**/system/clock',lambda route:route.abort())
    page.locator('#audio-measure').click()
    page.wait_for_function("document.getElementById('audio-rtt').textContent==='取得失敗'")
    with page.expect_download() as download:page.locator('#audio-export-rtt').click()
    data=json.loads(download.value.path().read_text(encoding='utf-8'))
    assert data['samples'][-1]['ok'] is False and data['samples'][-1]['ms'] is None
    assert page.locator('#ai-assist-box').count()==0
    assert page.locator('.composer .quick-grid').count()==0

@pytest.mark.e2e
def test_synthetic_capture_waveform_live_caption_and_track_release(sensory):
    page,base=sensory
    page.add_init_script("""() => {}""")
    page.add_init_script("""
      window.SpeechRecognition=class {
        constructor(){window.__recognition=this;}
        start(){this.onstart?.();}
        stop(){this.onend?.();}
        abort(){this.onend?.();}
      };
    """)
    page.goto(base,wait_until='domcontentloaded')
    page.wait_for_selector('#ai-signal')
    page.evaluate("""() => {const original=navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);navigator.mediaDevices.getUserMedia=async(...args)=>{const stream=await original(...args);window.__testCapture=stream;return stream;};}""")
    initial=page.locator('#ai-signal-canvas').evaluate('(canvas)=>canvas.toDataURL()')
    page.locator('#voice-start').click()
    page.wait_for_function("document.getElementById('ai-signal-label').textContent==='MIC / 実測'")
    page.wait_for_function("document.getElementById('audio-level').textContent.endsWith('dBFS')")
    assert page.locator('#ai-signal-canvas').evaluate('(canvas)=>canvas.toDataURL()')!=initial
    page.evaluate("window.__recognition.onresult({results:[{isFinal:false,0:{transcript:'音声入力を'}}]})")
    assert page.locator('#ai-live-caption').inner_text()=='音声入力を'
    assert page.locator('#message').input_value()=='音声入力を'
    page.evaluate("window.__recognition.onresult({results:[{isFinal:true,0:{transcript:'音声入力を検証します'}}]})")
    assert page.locator('#audio-transcript-state').inner_text()=='確定'
    page.locator('#voice-start').click()
    page.wait_for_function("window.__testCapture.getTracks().every(track=>track.readyState==='ended')")
    assert page.locator('#ai-signal-label').inner_text()=='MIC / OFF'
    page.locator('[data-open-panel="audio"]').click()
    page.locator('#audio-clear-transcript').click()
    assert page.locator('#ai-live-caption').is_hidden()
    assert page.locator('#message').input_value()=='音声入力を検証します'

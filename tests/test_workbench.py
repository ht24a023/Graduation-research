"""ツールに基づくカード、計測記録、文書の実読み込みを検証。"""
import base64
import csv
import io
from pathlib import Path
from unittest.mock import patch

import pytest
import local_ai_server as server
from models import execution_trace as trace
from models.evaluation_metrics import EvaluationMetrics
from functions import dashboard_tools


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(trace, 'LOG_PATH', tmp_path/'processing.jsonl')
    monkeypatch.setattr(server, 'evaluation_metrics', EvaluationMetrics(str(tmp_path/'evaluation.jsonl')))


def test_weather_card_is_actual_tool_return_not_answer_inference():
    with patch.object(server, 'get_weather', return_value='tool weather result') as tool:
        payload=server._build_chat_payload('weather request','one',tool_request={'kind':'weather','query':'大阪の天気'})
    tool.assert_called_once_with('大阪の天気')
    assert payload['cards'][0]['source']=='tool_result'
    assert payload['cards'][0]['data']['text']=='tool weather result'
    assert payload['execution']['stage_totals']['tool']>=0
    assert payload['execution']['text_generation_complete_sec'] is not None
    assert trace.processing_history('one')[0]['request_id']==payload['execution']['request_id']


def test_greeting_does_not_produce_irrelevant_cards():
    payload=server._build_chat_payload('こんにちは','one')
    assert payload['ok'] and payload['cards']==[]


def test_failed_tool_keeps_failed_card_and_failed_log():
    with patch.object(server,'search_google_web_structured',return_value={'ok':False,'results':[],'error_type':'timeout'}):
        payload=server._build_chat_payload('search','one',tool_request={'kind':'search','query':'test'})
    assert not payload['ok']
    assert not payload['cards'][0]['success']
    assert not trace.processing_history('one')[0]['success']
    assert not payload['execution']['stages'][0]['success']


def test_translation_suffix_is_not_misread_as_text_te():
    assert server._parse_dashboard_request('こんにちはを英語に翻訳して')['text']=='こんにちは'
    assert server._parse_dashboard_request('英語に翻訳して：こんにちは')['text']=='こんにちは'
    assert server._parse_dashboard_request('英語に翻訳して') is None


def test_translation_card_has_original_result_and_language():
    result={'ok':True,'translated_text':'Hello','source_language':'ja'}
    with patch.object(server,'translate_text_structured',return_value=result):
        payload=server._build_chat_payload('translate','one',tool_request={'kind':'translate','text':'こんにちは','source_lang':'ja','target_lang':'en'})
    data=payload['cards'][0]['data']
    assert data['original_text']=='こんにちは' and data['translated_text']=='Hello' and data['target_language']=='en'


def test_native_japanese_document_id_request_reads_actual_body():
    document=server.create_document_item('確認文書','実際の本文')['document']
    payload=server._build_chat_payload(document['doc_id']+'を表示して','one')
    assert payload['cards'][0]['data']['document']['content']=='実際の本文'
    assert '実際の本文' in payload['response']


def test_qr_is_local_svg_and_has_no_remote_image_url():
    payload=server._build_chat_payload('https://example.comをQRコードにして','one')
    image=payload['cards'][0]['data']['image_url']
    assert image.startswith('data:image/svg+xml;base64,')
    assert b'<svg' in base64.b64decode(image.split(',')[1])


def test_client_timings_validate_session_numbers_and_export():
    payload=server._build_chat_payload('こんにちは','one')
    request_id=payload['execution']['request_id']
    assert not trace.save_client_timings(request_id,'other',{'first_text_display_sec':1})
    assert trace.save_client_timings(request_id,'one',{'first_text_display_sec':.8,'audio_output_complete_sec':float('nan'),'speech_recognition_sec':-1,'arbitrary':7})
    assert trace.processing_history('one')[0]['client_timings']=={'first_text_display_sec':.8}
    row=list(csv.DictReader(io.StringIO(trace.processing_csv('one'))))[0]
    assert row['client_first_text_display_sec']=='0.8'
    assert row['server_first_token_sec']==''


def test_youtube_cards_come_from_real_video_renderer_structure():
    html='var ytInitialData = {"contents":[{"videoRenderer":{"videoId":"abcdefghijk","title":{"runs":[{"text":"actual provider title"}]}}}]};'
    with patch.object(dashboard_tools,'_http_get_text',return_value=html):
        result=dashboard_tools.youtube_results('query')
    assert result['ok']
    assert result['videos'][0]['title']=='actual provider title'
    assert result['videos'][0]['url']=='https://www.youtube.com/watch?v=abcdefghijk'


def test_sse_has_tool_stage_before_completed_card():
    events=list(server._chat_activity_events('CPUの使用率を教えて','one'))
    stage_index=next(i for i,e in enumerate(events) if e['event']=='stage' and e['data']['stage']=='tool')
    card_index=next(i for i,e in enumerate(events) if e['event']=='card')
    assert stage_index<card_index<len(events)-1
    assert events[-1]['event']=='done'


def test_unexpected_exception_is_logged_without_exposing_details():
    @trace.traced_request
    def fail(message,session_id):
        raise RuntimeError('private payload')
    payload=fail('test','one')
    assert not payload['ok'] and payload['error_type']=='RuntimeError'
    assert 'private payload' not in payload['error']
    assert not trace.processing_history('one')[0]['success']


def test_nested_llm_timing_is_not_double_counted_as_tool_time():
    import time
    @trace.traced_request
    def execute(message,session_id):
        def tool():
            return trace.run_stage('local_llm',lambda: time.sleep(.01))
        trace.run_stage('tool',tool,tool_name='test')
        return {'ok':True,'route':'local_function'}
    payload=execute('nested','one')
    stages=payload['execution']['stages']
    llm=next(stage for stage in stages if stage['stage']=='local_llm')
    tool=next(stage for stage in stages if stage['stage']=='tool')
    assert tool['duration_sec']>=llm['duration_sec']
    assert tool['exclusive_sec']<tool['duration_sec']
    assert payload['execution']['stage_totals']['tool']+payload['execution']['stage_totals']['local_llm']<=payload['execution']['server_elapsed_sec']

from unittest.mock import patch
import pytest
import local_ai_server as server
from models import execution_trace
from models.evaluation_metrics import EvaluationMetrics
from models import user_profile_memory as memory
from functions.routing_policy import decide
from functions.research_report import build_report


@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(server,'evaluation_metrics',EvaluationMetrics(str(tmp_path/'evaluation.jsonl')))
    monkeypatch.setattr(execution_trace,'LOG_PATH',tmp_path/'processing.jsonl')
    server._clear_all_sessions()


@pytest.mark.parametrize('question',['卒業研究の進め方を相談したい','今日のAIニュースについて説明して','CPU使用率の仕組みを説明して','Pythonとは何ですか','こんにちは。研究について相談したい'])
def test_normal_conversation_defaults_to_cloud_without_local_generation(question):
    assert server.ROUTING_MODE_DEFAULT=='CLOUD_FIRST'
    with patch.object(server,'ask_cloud_ai',return_value='クラウドによる通常の回答です。') as cloud,patch.object(server,'_generate_llm_response') as local,patch.object(server,'ask_local_llm_json') as probe,patch.object(server,'_run_search_with_fallback') as search:
        result=server._build_chat_payload(question,'cloud-first')
    assert result['ok'] and result['route']=='cloud_llm' and result['experiment_mode']=='CLOUD_FIRST'
    assert result['evaluation']['api_called']
    assert 'cloud_delegation' not in result
    cloud.assert_called_once();local.assert_not_called();probe.assert_not_called();search.assert_not_called()


@pytest.mark.parametrize('question',['今何時？','今日は何曜日？','10+20を計算して','こんにちは'])
def test_supported_programs_are_automatically_local_and_can_be_delegated(question):
    with patch.object(server,'ask_cloud_ai',return_value='クラウドで見直した回答です。') as cloud,patch.object(server,'_generate_llm_response') as local:
        result=server._build_chat_payload(question,'local-tool')
        assert result['ok'] and result['route']=='local_function' and not result['evaluation']['api_called']
        assert result['routing_reason'] and result['cloud_delegation']
        cloud.assert_not_called();local.assert_not_called()
        improved=server._build_chat_payload(result['cloud_delegation']['message'],'local-tool')
        assert improved['ok'] and improved['route']=='cloud_fallback'
        cloud.assert_called_once()


def test_memory_and_conversation_history_reach_normal_cloud_answer():
    memory.upsert_titled_note('卒研の音声入力','停止操作は確認済み。精度は未測定。')
    server._append_turn('context','user','前回は画面の構成を確認した')
    with patch.object(server,'ask_cloud_ai',return_value='メモと前回の話を踏まえた回答です。') as cloud:
        result=server._build_chat_payload('卒研の音声入力を改善したい','context')
    prompt=cloud.call_args.args[0]
    assert '精度は未測定' in prompt and '画面の構成' in prompt
    assert result['memory_context'][0]['title']=='卒研の音声入力'


def test_cloud_failure_is_visible_without_silent_local_fallback():
    with patch.object(server,'ask_cloud_ai',side_effect=RuntimeError('test unavailable')),patch.object(server,'_generate_llm_response') as local:
        result=server._build_chat_payload('研究内容を文章にして','cloud-error')
    assert not result['ok'] and 'test unavailable' in result['error']
    local.assert_not_called()


def test_streaming_endpoint_uses_the_same_cloud_first_policy():
    with patch.object(server,'ask_cloud_ai',return_value='クラウドの回答です。') as cloud,patch.object(server,'stream_local_llm') as local:
        events=list(server._chat_activity_events('研究計画を立てたい','stream-cloud',stream_body=True,operation_id='cloud-first-stream'))
    final=next(e['data'] for e in events if e['event']=='done')
    assert final['route']=='cloud_llm';cloud.assert_called_once();local.assert_not_called()


def test_regeneration_is_cloud_and_does_not_repeat_tools():
    with patch.object(server,'ask_cloud_ai',return_value='説明を修正した回答です。') as cloud,patch.object(server,'_dispatch_dashboard_tool') as tool,patch.object(server,'ask_local_llm') as local:
        result=server._build_chat_payload('CPUの使用率を教えて','regen-cloud',regenerate=True,regenerate_from='取得したCPU使用率は20%です。')
    assert result['ok'] and result['route']=='cloud_llm'
    assert '20%' in cloud.call_args.args[0]
    assert result['evaluation']['local_time_sec']==0
    tool.assert_not_called();local.assert_not_called()


def test_report_recognizes_cloud_first_mode():
    report=build_report([{'experiment_mode':'CLOUD_FIRST','api_called':True,'success':True,'response_time_sec':1}],mode='CLOUD_FIRST')
    assert report['overall']['count']==1 and report['unknown_mode_count']==0
    assert next(row for row in report['modes'] if row['mode']=='CLOUD_FIRST')['cloud_count']==1


def test_cloud_health_does_not_require_ollama_or_probe_paid_service():
    with patch.object(server,'_ollama_json_get') as ollama,patch.object(server,'ask_cloud_ai') as cloud:
        health=server._health_snapshot()
    assert health['routing_mode']=='CLOUD_FIRST'
    assert health['cloud']['connection']=='unverified' and health['ollama']['checked'] is False
    ollama.assert_not_called();cloud.assert_not_called()


def test_cloud_prompt_does_not_claim_to_be_local_and_avoids_duplicate_question():
    question='卒研の構成を提案して'
    with patch.object(server,'ask_cloud_ai',return_value='提案した構成です。') as cloud:
        server._build_chat_payload(question,'prompt-contract')
    prompt=cloud.call_args.args[0]
    assert '標準のクラウドAIアシスタント' in prompt
    assert 'あなたはローカルで動作する' not in prompt
    assert prompt.count(question)==1


@pytest.mark.parametrize(('text','intent'),[('大阪の天気','weather'),('今日は何日？','time'),('CPU使用率の目安を教えて','chat'),('メモリの空き容量を増やす対策を教えて','chat')])
def test_ambiguous_advice_is_not_a_machine_measurement(text,intent):
    assert decide(text,server._parse_dashboard_request(text))['intent']==intent


def test_program_routing_never_probes_local_model_for_clarification():
    with patch.object(server,'_should_probe_general_clarification',return_value=True),patch.object(server,'ask_local_llm_json') as probe,patch.object(server,'ask_cloud_ai') as cloud:
        result=server._build_chat_payload('10+20を計算して','no-probe')
    assert result['ok'] and result['route']=='local_function'
    probe.assert_not_called();cloud.assert_not_called()

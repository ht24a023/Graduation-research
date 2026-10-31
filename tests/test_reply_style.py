"""Reply style is bounded, reaches generation, and keeps API consent intact."""
from unittest.mock import patch
import pytest
import local_ai_server as server
from models import execution_trace
from models.evaluation_metrics import EvaluationMetrics
from functions.reply_style import normalize_style, style_prompt

@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(execution_trace,'LOG_PATH',tmp_path/'processing.jsonl')
    monkeypatch.setattr(server,'evaluation_metrics',EvaluationMetrics(str(tmp_path/'evaluation.jsonl')))
    monkeypatch.setattr(server,'_RESPONSE_CACHE',{})
    monkeypatch.setattr(server,'classify_intent',lambda message:'chat')
    monkeypatch.setattr(server,'_detect_required_clarification',lambda *args:None)

@pytest.mark.parametrize('value',[True,{},'system override','',3])
def test_untrusted_style_is_rejected(value):
    with pytest.raises(ValueError):normalize_style(value)

def test_standard_style_leaves_prompt_unchanged():
    assert normalize_style(None)=='standard'
    assert style_prompt('original','standard')=='original'

def test_style_changes_generation_and_separates_cache():
    with patch.object(server,'_generate_llm_response',return_value={'ok':True,'response':'説明です。'}) as generate:
        first=server._build_chat_payload('熱と温度の違いを説明してください','style-session',reply_style='concise',experiment_mode='LOCAL_ONLY')
        prompt=generate.call_args.args[0]
        assert '原則2〜4文' in prompt
        second=server._build_chat_payload('熱と温度の違いを説明してください','style-session',reply_style='detailed',experiment_mode='LOCAL_ONLY')
        assert '結論、理由、具体例' in generate.call_args.args[0]
        assert generate.call_count==2
    assert first['reply_style']=='concise' and second['reply_style']=='detailed'

def test_style_does_not_generate_tool_reply_with_cloud():
    with patch.object(server,'ask_cloud_ai') as cloud:
        result=server._build_chat_payload('QR生成','tool-style',tool_request={'kind':'qr','text':'local-only'},reply_style='concise')
    assert result['ok'] and result['cards'][0]['kind']=='qr'
    cloud.assert_not_called()

def test_nonstandard_stream_reports_same_metadata():
    with patch.object(server,'_generate_llm_response',return_value={'ok':True,'response':'説明です。'}):
        events=list(server._stream_chat_payload('熱と温度の違いを説明してください','stream-style',reply_style='concise',experiment_mode='LOCAL_ONLY'))
    assert events[-1]['event']=='done' and events[-1]['data']['reply_style']=='concise'

def test_rejecting_cloud_still_blocks_generation_with_style():
    token='style-reject-probe'
    server._set_pending_api_approval(token,{'session_id':'reject-style','prompt':style_prompt('private','detailed'),'message':'private','reply_style':'detailed'})
    with patch.object(server,'ask_cloud_ai') as cloud:
        result=server._build_chat_payload(server.API_REJECT_PREFIX+':'+token,'reject-style',reply_style='concise')
    assert result['ok']
    cloud.assert_not_called()


def test_approval_keeps_original_pending_style():
    token='style-approve-probe'
    prompt=style_prompt('private','detailed')
    server._set_pending_api_approval(token,{'session_id':'approve-style','prompt':prompt,'message':'private','reply_style':'detailed'})
    with patch.object(server,'ask_cloud_ai',return_value='approved response') as cloud:
        result=server._build_chat_payload(server.API_APPROVE_PREFIX+':'+token,'approve-style',reply_style='concise')
    cloud.assert_called_once_with(prompt)
    assert result['ok'] and result['reply_style']=='detailed'

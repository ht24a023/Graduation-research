import threading
import time
from collections import namedtuple
from types import SimpleNamespace
from unittest.mock import patch
import pytest
import local_ai_server as server
from models import execution_trace
from models.evaluation_metrics import EvaluationMetrics
from functions.system_monitor import SystemMonitor
from cloud import openai_client


@pytest.fixture
def isolated(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(server,'ROUTING_MODE_DEFAULT','DYNAMIC_ROUTING')
    monkeypatch.setattr(server,'evaluation_metrics',EvaluationMetrics(str(tmp_path/'evaluation.jsonl')))
    monkeypatch.setattr(execution_trace,'LOG_PATH',tmp_path/'processing.jsonl')
    server._RESPONSE_CACHE.clear();server._PENDING_API_APPROVAL.clear()
    monkeypatch.setattr(server,'classify_intent',lambda _: 'chat')


def test_post_answer_offer_does_not_call_cloud_until_selected(isolated):
    question='研究テーマの説明を改善したい'
    with patch.object(server,'ask_local_llm',return_value='ローカルで生成した説明です。'),patch.object(server,'ask_cloud_ai',return_value='クラウドによる改善した説明です。') as cloud:
        first=server._build_chat_payload(question,'answer-test')
        assert first['ok'] and first['cloud_delegation'];cloud.assert_not_called()
        with patch.object(server,'_dispatch_dashboard_tool') as tool:
            result=server._build_chat_payload(first['cloud_delegation']['message'],'answer-test')
            tool.assert_not_called()
        assert result['ok'] and result['route']=='cloud_fallback'
        prompt=cloud.call_args.args[0]
        assert question in prompt and first['response'] in prompt
        assert 'cloud_delegation' not in result
        assert not server._build_chat_payload(first['cloud_delegation']['message'],'answer-test')['ok']
        cloud.assert_called_once()


def test_local_failure_offers_cloud_and_local_only_remains_offline(isolated):
    with patch.object(server,'ask_local_llm',return_value='（ローカルLLM応答は空でした）'),patch.object(server,'_run_search_with_fallback',return_value=({'ok':False,'error_type':'test'},'')),patch.object(server,'ask_cloud_ai') as cloud:
        result=server._build_chat_payload('研究テーマについて詳しく説明したい','local-failed')
        assert 'cloud_delegation' in result
        local=server._build_chat_payload('研究テーマについて詳しく説明したい','local-only',experiment_mode='LOCAL_ONLY')
        assert not local['ok'] and 'cloud_delegation' not in local
        cloud.assert_not_called()


def test_stream_failure_also_offers_a_button(isolated):
    with patch.object(server,'stream_local_llm',return_value=iter([''])),patch.object(server,'ask_cloud_ai') as cloud:
        events=list(server._chat_activity_events('研究内容の改善を相談したい','stream-failed',stream_body=True,operation_id='post-answer-stream'))
        final=next(event for event in events if event['event']=='error')
        assert not final['data']['ok'] and final['data']['cloud_delegation']['message'].startswith(server.CLOUD_DELEGATE_PREFIX)
        cloud.assert_not_called()


def test_offer_scope_does_not_add_unseen_history(isolated):
    server._append_turn('private','user','SECRET-UNRELATED-HISTORY')
    payload={'ok':True,'response':'表示中の回答'}
    server._offer_cloud_delegation(payload,'選択した質問','private')
    token=payload['cloud_delegation']['message'].split(':',1)[1]
    pending=server._pop_pending_api_approval(token,'private','approve')
    assert 'SECRET-UNRELATED-HISTORY' not in pending['prompt']
    assert '表示中の回答' in pending['prompt']


def test_empty_cloud_answer_is_an_error():
    response=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='  '))])
    with pytest.raises(RuntimeError,match='空の回答'):openai_client._answer_text(response)


def test_process_percentage_matches_total_cpu_capacity():
    assert SystemMonitor._process_percent(12,(10,10),11,8)==25
    assert SystemMonitor._process_percent(9,(10,10),11,8) is None
    assert SystemMonitor._process_percent(12,None,11,8) is None
    assert SystemMonitor._process_percent(12,(10,10),10,8) is None


def test_cpu_time_percent_excludes_linux_guest_and_handles_counter_reset():
    Times=namedtuple('Times','user system idle guest guest_nice iowait')
    before=Times(100,20,100,10,0,5);after=Times(112,22,106,12,0,5)
    assert SystemMonitor._cpu_usage(after,before)==70.0
    assert SystemMonitor._cpu_usage(before,after) is None


def test_native_counter_is_preferred_and_disk_activity_is_not_capacity():
    monitor=SystemMonitor()
    monitor._native=SimpleNamespace(sample=lambda:{'cpu_utility':23.4,'core_0':40.2,'disk_idle':94.0},close=lambda:None)
    data=monitor.snapshot()
    assert data['cpu']['usage_percent']==23.4
    assert data['cpu']['per_core_percent'][0]==40.2
    assert data['disk']['active_percent']==6
    assert data['cpu']['usage_source']=='Windows Processor Utility / PDH'
    assert data['disk']['usage_percent'] is not None
    monitor.stop()


def test_slow_collection_does_not_block_readers_and_uses_one_sampler():
    monitor=SystemMonitor();entered=threading.Event();release=threading.Event();calls=[]
    def sample():
        calls.append(1);entered.set();release.wait(3)
        data={'ok':True,'source':'backend_pc','sampled_at':time.time()}
        monitor._cached=data;monitor._sampled=time.monotonic();return data
    monitor.snapshot=sample
    try:
        started=time.monotonic();first=monitor.latest()
        assert first['warming_up'] and time.monotonic()-started<.4
        assert entered.wait(1)
        monitor.latest();assert len(calls)==1
        release.set()
        limit=time.monotonic()+2
        while monitor._cached is None and time.monotonic()<limit:time.sleep(.01)
        assert monitor.latest()['ok']
        monitor._sampled=time.monotonic()-10
        assert monitor.latest()['telemetry']['stale']
    finally:release.set();monitor.stop()


def test_optional_disk_and_memory_failure_does_not_drop_cpu():
    monitor=SystemMonitor()
    with patch('functions.system_monitor.psutil.virtual_memory',side_effect=OSError('denied')),patch('functions.system_monitor.psutil.disk_usage',side_effect=OSError('denied')):
        data=monitor.snapshot()
    assert data['ok'] and data['memory']['total_bytes'] is None and data['disk']['total_bytes'] is None
    assert data['cpu']['logical_cores']>0
    monitor.stop()


def test_new_search_consent_does_not_revoke_other_answer_buttons(isolated):
    original={'ok':True,'response':'既存のローカル回答'}
    server._offer_cloud_delegation(original,'最初の質問','same-chat')
    token=original['cloud_delegation']['message'].split(':',1)[1]
    server._set_pending_api_approval('search-yes',{'session_id':'same-chat','decision':'approve','prompt':'search'})
    server._clear_pending_api_approval_for_session('same-chat',preserve_post_answers=True)
    assert 'search-yes' not in server._PENDING_API_APPROVAL
    assert server._pop_pending_api_approval(token,'same-chat','approve') is not None

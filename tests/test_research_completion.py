import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import pytest
import local_ai_server as server
from models import execution_trace, user_profile_memory as memory
from models.evaluation_metrics import EvaluationMetrics
from models.memory_retrieval import retrieve, memory_revision
from functions.research_report import build_report


@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(server,'ROUTING_MODE_DEFAULT','DYNAMIC_ROUTING')
    monkeypatch.setattr(server,'evaluation_metrics',EvaluationMetrics(str(tmp_path/'evaluation.jsonl')))
    monkeypatch.setattr(execution_trace,'LOG_PATH',tmp_path/'processing.jsonl')
    server._PENDING_API_APPROVAL.clear();server._RESPONSE_CACHE.clear()


def pair(session='consent'):
    for token,decision in [('yes','approve'),('no','reject')]:
        server._set_pending_api_approval(token,{'session_id':session,'prompt':'original private prompt','decision':decision,'approval_group':'one','memory_context':[{'id':'saved','title':'卒研'}]})


def test_approval_is_bound_to_session_and_button_and_single_use():
    pair()
    with patch.object(server,'ask_cloud_ai',return_value='クラウド回答') as cloud:
        wrong=server._build_chat_payload('__API_APPROVE__:yes','other')
        assert not wrong['ok'];assert 'yes' in server._PENDING_API_APPROVAL
        switched=server._build_chat_payload('__API_APPROVE__:no','consent')
        assert not switched['ok'];cloud.assert_not_called()
        approved=server._build_chat_payload('__API_APPROVE__:yes','consent')
        assert approved['ok'] and approved['memory_context'][0]['id']=='saved'
        cloud.assert_called_once_with('original private prompt')
        assert not server._PENDING_API_APPROVAL
        assert not server._build_chat_payload('__API_APPROVE__:yes','consent')['ok']
        assert cloud.call_count==1


def test_rejection_and_local_only_cannot_call_cloud():
    pair()
    with patch.object(server,'ask_cloud_ai') as cloud:
        assert not server._build_chat_payload('__API_APPROVE__:yes','consent',experiment_mode='LOCAL_ONLY')['ok']
        result=server._build_chat_payload('__API_REJECT__:no','consent')
        assert result['ok'];assert not server._PENDING_API_APPROVAL
        assert not server._build_chat_payload('__API_APPROVE__:yes','consent')['ok']
        cloud.assert_not_called()


def test_expiry_and_atomic_consumption():
    pair()
    created=server._PENDING_API_APPROVAL['yes']['created_at']
    with patch.object(server.time,'monotonic',return_value=created+601):
        assert server._pop_pending_api_approval('yes','consent','approve') is None
    pair();gate=threading.Barrier(2)
    def consume(token,decision):
        gate.wait();return server._pop_pending_api_approval(token,'consent',decision)
    with ThreadPoolExecutor(2) as executor:
        futures=[executor.submit(consume,'yes','approve'),executor.submit(consume,'no','reject')]
        assert sum(f.result() is not None for f in futures)==1


def test_retrieval_uses_old_relevant_notes_not_last_four():
    notes=[{'title':'卒研 音声入力','content':'呼びかけ機能の検証結果。'+'停止操作の確認。'*30}]
    notes.extend({'title':f'別のメモ{i}','content':'旅行の計画と食事'} for i in range(8))
    selected=retrieve('卒研の音声入力を改善したい',notes)
    assert len(selected)==1 and selected[0]['title']=='卒研 音声入力'
    assert len(selected[0]['content'])>40
    assert retrieve('GPU memory',notes)==[]
    memory.upsert_titled_note('卒研 音声入力',notes[0]['content'])
    context=memory.build_profile_context(query='卒研の音声入力',selected_notes=selected)
    assert selected[0]['id'] in context and '停止操作の確認' in context
    before=memory_revision();memory.upsert_titled_note('卒研 音声入力','更新された実験結果')
    assert memory_revision()!=before


def test_local_model_receives_selected_memory_and_returns_provenance():
    memory.upsert_titled_note('音声入力の実験','停止操作を確認した。応答速度は未測定。')
    with patch.object(server,'classify_intent',return_value='chat'),patch.object(server,'ask_local_llm',return_value='保存メモでは停止操作を確認済みです。') as llm,patch.object(server,'ask_cloud_ai') as cloud:
        result=server._build_chat_payload('音声入力の実験の続きについて相談したい','memory-probe')
    assert result['ok'] and result['memory_context'][0]['title']=='音声入力の実験'
    assert '応答速度は未測定' in llm.call_args.args[0]
    cloud.assert_not_called()


def rows():
    return [dict(experiment_mode='LOCAL_ONLY',test_case_id='one',response_time_sec=1,success=True,api_called=False,user_rating='good',input_text='SECRET'),
            dict(experiment_mode='FIXED_ROUTING',test_case_id='one',response_time_sec=3,success=False,api_called=True,user_rating='bad'),
            dict(experiment_mode='DYNAMIC_ROUTING',test_case_id='one',response_time_sec=2,success=True,api_called=False,user_rating=''),
            dict(experiment_mode='DYNAMIC_ROUTING',test_case_id='',response_time_sec=float('nan'),success=True,api_called=False,user_rating='partial')]


def test_research_metrics_filters_missing_values_and_privacy():
    data=build_report(rows());all=data['overall']
    assert all['count']==4 and all['measured']==3 and all['median_sec']==2 and all['p95_sec']==3
    assert all['rated']==3 and all['unrated']==1 and all['good']==1
    assert all['good_rate_among_rated']==33.3
    assert data['paired_case_count']==1
    assert 'SECRET' not in str(data) and 'input_text' not in str(data)
    assert build_report(rows(),experiments_only=True)['overall']['count']==3
    assert build_report(rows(),mode='LOCAL_ONLY')['overall']['count']==1
    empty=build_report([])['overall']
    assert empty['median_sec'] is None and empty['completion_rate'] is None
    with pytest.raises(ValueError):build_report([],mode='made-up')


def test_reset_revokes_pending_cloud_permission():
    pair()
    server._clear_session('consent')
    assert not server._PENDING_API_APPROVAL
    with patch.object(server,'ask_cloud_ai') as cloud:
        assert not server._build_chat_payload('__API_APPROVE__:yes','consent')['ok']
        cloud.assert_not_called()


def test_concurrent_feedback_preserves_all_log_records(tmp_path):
    metrics=EvaluationMetrics(str(tmp_path/'concurrent.jsonl'))
    def record(i):
        return metrics.build_record(request_id=f'record-{i}',entry_point='test',input_text='test',response_text='answer',route='local',response_time_sec=1,local_time_sec=1,cloud_time_sec=0,api_called=False,success=True)
    for i in range(12):metrics.save(record(i))
    def change(i):
        assert metrics.set_user_feedback(f'record-{i}','good')
        metrics.save(record(12+i))
    with ThreadPoolExecutor(6) as pool:list(pool.map(change,range(12)))
    all=metrics.load_all()
    assert len(all)==24
    assert sum(r.get('user_rating')=='good' for r in all)==12
    assert not metrics.set_user_feedback('record-0','not-a-rating')


def test_reset_discards_cached_answers_only_for_the_selected_session():
    server._set_cached_response('reset-me|DYNAMIC_ROUTING|balanced||question',{'route':'local_llm','response':'old private context'})
    server._set_cached_response('keep-me|DYNAMIC_ROUTING|balanced||question',{'route':'local_llm','response':'keep context'})
    server._clear_session('reset-me')
    assert server._get_cached_response('reset-me|DYNAMIC_ROUTING|balanced||question') is None
    assert server._get_cached_response('keep-me|DYNAMIC_ROUTING|balanced||question')['response']=='keep context'

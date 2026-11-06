from types import SimpleNamespace as N
from unittest.mock import Mock
import threading,time,json
import httpx,pytest
from cloud import model_catalog as catalog,free_pool,openai_client as sdk
from models.request_control import RequestCancelled

@pytest.fixture
def free_config(monkeypatch):
    monkeypatch.setattr(catalog,'DEFAULT_MODEL','free-auto')
    catalog.save_key('openrouter','fake-openrouter-key')
    catalog.save_key('groq','fake-groq-key',True)
    catalog.clear_outcome()

def error(code,retry='2'):
    response=httpx.Response(code,headers={'retry-after':retry},request=httpx.Request('POST','https://example.test'))
    from openai import APIStatusError
    return APIStatusError('simulated',response=response,body={})

def answer():return N(model='served-free-model',choices=[N(message=N(content='無料の回答'))],usage=N(prompt_tokens=100,completion_tokens=30,prompt_tokens_details=N(cached_tokens=0)))

def test_shared_quota_rotates_to_another_provider_and_never_paid(free_config,monkeypatch):
    calls=[]
    def create(**kw):
        calls.append(kw['model'])
        if kw['model']=='openrouter/free':raise error(429,'120')
        return answer()
    monkeypatch.setattr(sdk,'_get_provider_client',lambda *a:N(chat=N(completions=N(create=create))))
    assert sdk.ask_cloud_ai('test')=='無料の回答'
    assert calls==['openrouter/free','openai/gpt-oss-20b']
    result=catalog.outcome();assert result['free'] and result['automatic_free'] and result['provider']=='groq'
    assert result['rotation'][0]['status']==429
    assert all(not x['available'] for x in free_pool.status() if x['provider']=='openrouter')
    totals=sdk.api_usage.snapshot()['totals']
    assert totals['estimated_cost_usd']==0 and totals['unpriced_calls']==0
    assert totals['total_tokens']==130 and totals['calls']==2

def test_all_free_unavailable_stops_and_paid_is_never_called(free_config,monkeypatch):
    calls=[]
    def send(text):calls.append(catalog.current()['provider']);raise error(429)
    with pytest.raises(free_pool.FreePoolExhausted):free_pool.generate('test',send)
    assert calls==['openrouter','groq','groq','groq']
    assert catalog.outcome()['switch_required']
    assert all(p not in ('openai','ollama_local') for p in calls)
    assert free_pool.generate
    calls.clear()
    with pytest.raises(free_pool.FreePoolExhausted):free_pool.generate('test',send)
    assert calls==[] # persistent Retry-After respected, no sleeping or repeated network calls

def test_no_keys_does_not_attempt_cloud(monkeypatch):
    monkeypatch.setattr(catalog,'key',lambda p:'')
    call=Mock()
    with pytest.raises(free_pool.FreePoolExhausted):free_pool.generate('test',call)
    call.assert_not_called();assert catalog.outcome()['cloud_attempted'] is False

def test_cancel_does_not_rotate(free_config):
    send=Mock(side_effect=RequestCancelled())
    with pytest.raises(RequestCancelled):free_pool.generate('test',send)
    assert send.call_count==1

def test_invalid_prompt_does_not_rotate(free_config):
    send=Mock(side_effect=error(400))
    with pytest.raises(Exception) as caught:free_pool.generate('test',send)
    assert getattr(caught.value,'status_code',None)==400 and send.call_count==1

def test_model_unavailable_tries_next_model(free_config):
    seen=[]
    def send(text):
        seen.append(catalog.current()['id'])
        if len(seen)==1:raise error(404)
        catalog.set_outcome({'free':True,'provider':'openrouter'});return 'ok'
    assert free_pool.generate('test',send)=='ok'
    assert seen==['openrouter-free','or-google']

def test_groq_requires_free_plan_confirmation_and_keys_are_not_exposed():
    with pytest.raises(ValueError):catalog.save_key('groq','fake-private-key')
    catalog.save_key('groq','fake-private-key',True)
    data=catalog.snapshot('session')
    assert 'fake-private-key' not in json.dumps(data)
    assert next(r for r in data['models'] if r['provider']=='groq')['free_plan_confirmed']

def test_per_session_choice_persists_and_context_isolated():
    catalog.choose('a','openai-full');catalog.choose('b','openrouter-free')
    assert catalog.selected('a')=='openai-full' and catalog.selected('b')=='openrouter-free'
    with pytest.raises(ValueError):catalog.choose('a','https://untrusted')
    with catalog.model_scope('openai-full'):
        values=[]
        t=threading.Thread(target=lambda:values.append(catalog.current()['id']));t.start();t.join()
        assert catalog.current()['id']=='openai-full' and values==['openai-mini']

def test_official_free_quota_sync_redacts_other_account_data(free_config,monkeypatch):
    monkeypatch.setattr(httpx,'get',lambda *a,**kw:N(raise_for_status=lambda:None,json=lambda:{'data':{'label':'private','usage':100,'free_model_daily_requests':{'limit':50,'used':10,'remaining':40,'private':'secret'}}}))
    data=free_pool.sync_openrouter()
    assert data['daily']=={'limit':50,'used':10,'remaining':40}
    assert 'private' not in json.dumps(data)

def test_free_evaluation_and_exhaustion_payload(free_config,monkeypatch,tmp_path):
    import local_ai_server as server
    from models.evaluation_metrics import EvaluationMetrics
    from models import execution_trace
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(server,'evaluation_metrics',EvaluationMetrics('eval.jsonl'))
    monkeypatch.setattr(execution_trace,'LOG_PATH',tmp_path/'trace.jsonl')
    def fake(prompt):catalog.set_outcome({'free':True,'provider':'groq','model':'openai/gpt-oss-20b','cloud_attempted':True});return '回答です'
    monkeypatch.setattr(server,'_ask_cloud_ai',fake)
    data=server._build_chat_payload('卒業研究のテーマを提案して','free-eval')
    ev=data['evaluation'];assert data['ok'] and ev['api_called'] and ev['cloud_used']
    assert ev['api_fee_status']=='free' and ev['estimated_api_cost_yen']==0
    assert ev['usage_assessment']=='クラウド利用あり／API利用料金なし（無料枠）'
    row=server.evaluation_metrics.load_all()[0];assert row['api_fee_status']=='free' and row['cloud_provider']=='groq'
    def exhausted(prompt):catalog.set_outcome({'switch_required':True,'free':True,'cloud_attempted':False});raise free_pool.FreePoolExhausted([])
    monkeypatch.setattr(server,'_ask_cloud_ai',exhausted)
    data=server._build_chat_payload('違うテーマについても教えて','free-eval')
    assert data['model_switch_required'] and not data['ok'] and not data['evaluation']['api_called']

def test_paid_selection_only_calls_selected_model(monkeypatch):
    monkeypatch.setattr(sdk,'OPENAI_API_KEY','fake-openai')
    create=Mock(return_value=answer());monkeypatch.setattr(sdk,'_get_client',lambda key:N(chat=N(completions=N(create=create))))
    with catalog.model_scope('openai-full'):assert sdk.ask_cloud_ai('test')=='無料の回答'
    assert create.call_args.kwargs['model']=='gpt-4.1'
    assert catalog.outcome()['free'] is False

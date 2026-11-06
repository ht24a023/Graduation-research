from types import SimpleNamespace as N
import pytest
from models.api_usage import ApiUsage, usage_scope

@pytest.fixture
def ledger(tmp_path):return ApiUsage(tmp_path/'calls.jsonl',tmp_path/'settings.json',tmp_path/'official.json')

def response():return N(model='gpt-4.1-mini',id='fake',service_tier='default',usage=N(prompt_tokens=1000,completion_tokens=100,prompt_tokens_details=N(cached_tokens=200)))

def test_measured_cost_purposes_and_no_content(ledger):
    with usage_scope('work_summary',session_id='private-session'):
        call=ledger.begin('gpt-4.1-mini')
    ledger.finish(call,response(),'success',.1)
    snap=ledger.snapshot('all');assert snap['totals']['total_tokens']==1100
    assert snap['totals']['estimated_cost_usd']==pytest.approx(.0005)
    assert snap['by_purpose'][3]['calls']==1
    assert 'private-session' not in ledger.path.read_text()
    assert ledger.snapshot('all')['totals']['calls']==1

def test_missing_usage_and_restart_are_unknown(ledger):
    call=ledger.begin('gpt-4.1-mini');ledger.finish(call,None,'cancelled',.1)
    unfinished=ledger.begin('gpt-4.1-mini')
    assert ledger.snapshot()['totals']['unpriced_calls']==2
    restart=ApiUsage(ledger.path,ledger.settings_path)
    assert restart.records()[-1]['status']=='unconfirmed'
    ledger.update_settings({'action':'budget','monthly_budget_usd':10,'usd_jpy':None})
    assert ledger.snapshot()['budget_remaining_usd'] is None

@pytest.mark.parametrize('bad',[True,-1,float('nan'),float('inf'),'10'])
def test_bad_budget_rejected(ledger,bad):
    with pytest.raises(ValueError):ledger.update_settings({'action':'budget','monthly_budget_usd':bad})

def test_balance_anchor_and_budget_zero(ledger):
    ledger.update_settings({'action':'budget','monthly_budget_usd':0,'usd_jpy':150})
    assert ledger.snapshot()['budget_remaining_usd']==0
    ledger.update_settings({'action':'balance','balance_usd':5})
    c=ledger.begin('gpt-4.1-mini');ledger.finish(c,response(),'success',1)
    assert ledger.snapshot()['balance_reference_remaining_usd']==pytest.approx(4.9995)
    c=ledger.begin('gpt-4.1-mini');ledger.finish(c,None,'error',1)
    assert ledger.snapshot()['balance_reference_remaining_usd'] is None
    ledger.update_settings({'action':'balance','balance_usd':None})
    assert 'balance_reference' not in ledger.settings()

def test_sdk_records_returned_usage_and_survives_record_failure(monkeypatch):
    from cloud import openai_client as sdk
    r=response();r.choices=[N(message=N(content='answer'))]
    monkeypatch.setattr(sdk,'OPENAI_API_KEY','fake')
    monkeypatch.setattr(sdk,'_get_client',lambda _:N(chat=N(completions=N(create=lambda **kw:r))))
    assert sdk.ask_cloud_ai('secret prompt')=='answer'
    assert sdk.api_usage.snapshot()['totals']['total_tokens']==1100
    assert 'secret prompt' not in sdk.api_usage.path.read_text()
    monkeypatch.setattr(sdk.api_usage,'finish',lambda *a:(_ for _ in ()).throw(OSError()))
    assert sdk.ask_cloud_ai('another')=='answer'

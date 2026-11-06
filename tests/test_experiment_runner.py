import json
from pathlib import Path
import pytest
import run_experiment as runner


@pytest.fixture
def questions(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    path=tmp_path/'questions.json';path.write_text(json.dumps([{'test_case_id':'one','message':'検証の質問'},{'test_case_id':'two','message':'続きの質問'}]),encoding='utf-8')
    return path


def test_dry_run_and_cloud_guard_do_not_call_any_service(questions,monkeypatch):
    def forbidden(*a,**k):raise AssertionError('No service access expected')
    monkeypatch.setattr(runner,'post_json',forbidden);monkeypatch.setattr(runner,'get_json',forbidden)
    plan=runner.run_experiment('http://localhost:8000',questions,'exp',repetitions=3,dry_run=True)
    assert plan['protocol']['planned_requests']==12
    assert 'FIXED_ROUTING' not in plan['protocol']['modes']
    assert not Path('data').exists()
    with pytest.raises(ValueError,match='allow-cloud'):runner.run_experiment('http://localhost:8000',questions,'exp',modes=['FIXED_ROUTING'])


def test_run_isolation_current_results_only_and_partial_failures(questions,monkeypatch):
    sessions=[]
    def post(url,payload):
        sessions.append(payload['session_id'])
        if payload['test_case_id']=='two':raise TimeoutError('test timeout')
        return {'ok':True,'response':'テストの回答','evaluation':{'request_id':'probe','response_time_sec':1,'api_called':False}}
    monkeypatch.setattr(runner,'post_json',post)
    def get(url):
        assert url.endswith('/health');return {'ok':True,'api_key':'NEVER-EXPORT'}
    monkeypatch.setattr(runner,'get_json',get)
    first=runner.run_experiment('http://localhost:8000',questions,'exp',repetitions=2)
    assert first['total_requests']==8 and first['success_requests']==4 and first['missing_evaluation_count']==4
    assert first['summary']['overall']['count']==4
    assert len(set(sessions))==4
    assert 'NEVER-EXPORT' not in str(first)
    second=runner.run_experiment('http://localhost:8000',questions,'exp',modes=['LOCAL_ONLY'])
    assert second['run_id']!=first['run_id']
    assert first['summary']['overall']['count']==4 and second['summary']['overall']['count']==1
    csv=Path(first['evaluation_csv']).read_text(encoding='utf-8-sig')
    assert 'response_time_sec' in csv and '検証の質問' not in csv


def test_http_error_retains_server_evaluation(monkeypatch):
    import io
    from urllib.error import HTTPError
    error=HTTPError('http://localhost:8000/chat',400,'Bad Request',{},io.BytesIO(json.dumps({'ok':False,'error':'failed locally','evaluation':{'response_time_sec':2,'api_called':False}}).encode()))
    def fail(*a,**k):raise error
    monkeypatch.setattr(runner,'urlopen',fail)
    result=runner.post_json('http://localhost:8000/chat',{})
    assert not result['ok'] and result['evaluation']['response_time_sec']==2

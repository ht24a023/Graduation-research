import json
import threading
import time
from unittest.mock import patch
import pytest
from functions.work_memory import WorkMemory,parse_summary
from functions.memory_graph import mutate,snapshot
from models import user_profile_memory as memory

SUMMARY=json.dumps({'purpose':'卒業研究の作業内容を整理する','decisions':['クラウドを標準にする'],'progress':['計算機能の確認について会話した。実機検証は未確認。'],'open_issues':['回答品質の評価は未実施'],'next_actions':['実験を行う（未実施）']},ensure_ascii=False)


def wait(service,sid,state,timeout=4):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        data=service.status(sid)
        if data['state'] in state:return data
        time.sleep(.015)
    raise AssertionError(service.status(sid))


@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):monkeypatch.chdir(tmp_path)


def test_saved_summary_is_real_editable_note_and_events_exclude_content():
    prompts=[];service=WorkMemory(lambda p:(prompts.append(p) or SUMMARY),debounce=.01,min_interval=0)
    try:
        service.enqueue('one','卒業研究の目的を整理したい','研究目的を整理する提案です。')
        data=wait(service,'one',{'saved'})
        graph=snapshot();assert len(graph['nodes'])==1 and graph['nodes'][0]['id']==data['note']['id']
        assert '未確認' in graph['nodes'][0]['content'] and 'クラウド作業要約' in graph['nodes'][0]['source']
        assert '実行したと確認できないことを「完了した」と書いてはいけません' in prompts[0]
        mutate({'action':'update','title':graph['nodes'][0]['title'],'content':'ユーザーが確認して修正した内容'})
        assert snapshot()['nodes'][0]['user_edited']
        ledger=__import__('pathlib').Path('data/work_summary_events.jsonl').read_text()
        assert '研究目的を整理する提案' not in ledger
    finally:service.stop()


def test_burst_is_coalesced_without_losing_recent_context():
    prompts=[];service=WorkMemory(lambda p:(prompts.append(p) or SUMMARY),debounce=.08,min_interval=0)
    try:
        for i in range(3):service.enqueue('burst',f'質問{i}',f'回答{i}')
        wait(service,'burst',{'saved'})
        assert len(prompts)==1 and '質問0' in prompts[0] and '質問2' in prompts[0]
    finally:service.stop()


def test_user_edit_generates_proposal_instead_of_overwrite():
    service=WorkMemory(lambda _:SUMMARY,debounce=.01,min_interval=0)
    try:
        service.enqueue('edit','最初の質問','回答');data=wait(service,'edit',{'saved'})
        title=data['note']['title'];mutate({'action':'update','title':title,'content':'利用者の確定した修正'})
        service.enqueue('edit','次の質問','次の回答');wait(service,'edit',{'proposal'})
        notes=memory.load_notes()['notes']
        assert next(n for n in notes if n['title']==title)['content']=='利用者の確定した修正'
        assert len(notes)==2 and any(n.get('summary_proposal') for n in notes)
    finally:service.stop()


def test_edit_and_delete_during_generation_are_respected():
    entered=threading.Event();release=threading.Event()
    service=WorkMemory(lambda _:SUMMARY,debounce=.01,min_interval=0)
    try:
        service.enqueue('race','初回','回答');data=wait(service,'race',{'saved'});title=data['note']['title']
        def delayed(_):entered.set();release.wait(3);return SUMMARY
        service.generator=delayed;service.enqueue('race','更新','回答');assert entered.wait(2)
        mutate({'action':'update','title':title,'content':'生成中に編集した内容'})
        release.set();wait(service,'race',{'proposal'})
        assert next(n for n in memory.load_notes()['notes'] if n['title']==title)['content']=='生成中に編集した内容'
        entered.clear();release.clear();service.enqueue('race','削除確認','回答');assert entered.wait(2)
        mutate({'action':'delete','title':title});release.set();wait(service,'race',{'conflict'})
        assert all(n['title']!=title for n in memory.load_notes()['notes'])
    finally:release.set();service.stop()


def test_disabled_and_reset_do_not_save_inflight_summary():
    service=WorkMemory(lambda _:SUMMARY,debounce=.1,min_interval=0)
    try:
        service.enqueue('off','質問','回答');service.set_enabled(False)
        time.sleep(.15)
        assert service.status('off')['counts']['attempts']==0
        assert not WorkMemory().is_enabled()
        service.set_enabled(True)
        entered=threading.Event();release=threading.Event()
        def delayed(_):entered.set();release.wait(3);return SUMMARY
        service.generator=delayed;service.enqueue('reset','質問','回答');assert entered.wait(2)
        service.cancel_session('reset');release.set();wait(service,'reset',{'cancelled'})
        assert memory.load_notes()['notes']==[]
    finally:service.stop()


def test_malformed_response_is_not_saved_and_retry_is_explicit():
    service=WorkMemory(lambda _:'not valid JSON',debounce=.01,min_interval=0)
    try:
        service.enqueue('bad','質問','回答');wait(service,'bad',{'error'})
        assert memory.load_notes()['notes']==[] and service.status('bad')['counts']['attempts']==1
        service.generator=lambda _:SUMMARY;service.retry('bad');wait(service,'bad',{'saved'})
        assert service.status('bad')['counts']['attempts']==2
    finally:service.stop()


def test_capacity_does_not_evict_existing_memories():
    memory.save_notes({'notes':[{'title':f'既存{i}','content':'残すメモ'} for i in range(memory._MAX_NOTES)]})
    service=WorkMemory(lambda _:SUMMARY,debounce=.01,min_interval=0)
    try:
        service.enqueue('full','質問','回答');wait(service,'full',{'full'})
        notes=memory.load_notes()['notes'];assert len(notes)==memory._MAX_NOTES and all(n['title'].startswith('既存') for n in notes)
    finally:service.stop()


def test_chat_response_returns_before_background_generation(tmp_path,monkeypatch):
    import local_ai_server as server
    from models import execution_trace
    from models.evaluation_metrics import EvaluationMetrics
    entered=threading.Event();release=threading.Event()
    def delayed(_):entered.set();release.wait(3);return SUMMARY
    service=WorkMemory(delayed,debounce=.01,min_interval=0)
    monkeypatch.setattr(server,'work_memory',service)
    monkeypatch.setattr(server,'evaluation_metrics',EvaluationMetrics(str(tmp_path/'evaluation.jsonl')))
    monkeypatch.setattr(execution_trace,'LOG_PATH',tmp_path/'processing.jsonl')
    try:
        with patch.object(server,'ask_cloud_ai',return_value='クラウドの通常回答です。'):
            started=time.monotonic();result=server._build_chat_payload('卒業研究を進める計画を立てたい','response-before-summary')
        assert time.monotonic()-started<1 and result['ok'] and result['background_memory']['state']=='queued'
        assert entered.wait(2);release.set();wait(service,'response-before-summary',{'saved'})
    finally:release.set();service.stop()


def test_background_scheduling_failure_does_not_hide_main_answer(tmp_path,monkeypatch):
    import local_ai_server as server
    from models import execution_trace
    from models.evaluation_metrics import EvaluationMetrics
    monkeypatch.setattr(server,'evaluation_metrics',EvaluationMetrics(str(tmp_path/'evaluation.jsonl')))
    monkeypatch.setattr(execution_trace,'LOG_PATH',tmp_path/'processing.jsonl')
    with patch.object(server,'ask_cloud_ai',return_value='通常の回答は保持します。'),patch.object(server.work_memory,'enqueue',side_effect=RuntimeError('test scheduling failure')):
        result=server._build_chat_payload('卒業研究の考察をまとめたい','schedule-failed')
    assert result['ok'] and result['response']=='通常の回答は保持します。'
    assert result['background_memory']['state']=='error'


def test_conversations_keep_independent_work_summaries():
    service=WorkMemory(lambda _:SUMMARY,debounce=.01,min_interval=0)
    try:
        service.enqueue('first-conversation','質問1','回答1');service.enqueue('second-conversation','質問2','回答2')
        first=wait(service,'first-conversation',{'saved'});second=wait(service,'second-conversation',{'saved'})
        assert first['note']['id']!=second['note']['id']
        assert len(memory.load_notes()['notes'])==2
    finally:service.stop()


def test_saved_summary_can_be_opened_after_service_restart():
    service=WorkMemory(lambda _:SUMMARY,debounce=.01,min_interval=0)
    try:
        service.enqueue('restart','質問','回答');saved=wait(service,'restart',{'saved'})
    finally:service.stop()
    reopened=WorkMemory()
    data=reopened.status('restart')
    assert data['state']=='saved' and data['note']['id']==saved['note']['id']
    assert not data['can_retry']

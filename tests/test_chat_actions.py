"""中央chat担当: cancellation boundaries and answer-only regeneration."""
import threading
from unittest.mock import patch
import pytest
import local_ai_server as server


def test_cancel_request_is_scoped_and_stops_history_writes():
    signal = threading.Event()
    key = ('chat-cancel-test', 'unique-token')
    server._CHAT_CANCEL[key] = signal
    server._ACTIVITY.cancelled = signal
    try:
        assert not server._cancel_chat('another-session', key[1])
        assert not signal.is_set()
        assert server._cancel_chat(*key)
        with pytest.raises(server.ChatCancelled):
            server._append_turn(key[0], 'assistant', 'must not be saved')
    finally:
        del server._ACTIVITY.cancelled
        server._CHAT_CANCEL.pop(key, None)


def test_regeneration_never_dispatches_original_tool(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from models.evaluation_metrics import EvaluationMetrics
    from models import execution_trace
    monkeypatch.setattr(server, 'evaluation_metrics', EvaluationMetrics(str(tmp_path/'evaluation.jsonl')))
    monkeypatch.setattr(execution_trace, 'LOG_PATH', tmp_path/'processing.jsonl')
    with patch.object(server, 'ask_local_llm', return_value='取得済みの数値を使った別の回答です。') as llm, \
         patch.object(server, '_dispatch_dashboard_tool') as tool:
        result = server._build_chat_payload('CPUの使用率を教えて', 'regen-test',
                    regenerate=True, regenerate_from='CPU使用率は20%でした。')
    assert result['ok'] and result['regenerated']
    tool.assert_not_called()
    assert '20%' in llm.call_args.args[0]
    assert result['route'] == 'local_llm'

def test_worker_cancellation_blocks_followup_inference_and_cleans_registry():
    started, release = threading.Event(), threading.Event()
    key = ('cancel-worker-test', 'worker-token')
    def infer(*args, **kwargs):
        started.set()
        assert release.wait(3)
        return 'delayed answer'
    def build(*args, **kwargs):
        server.ask_local_llm('first')
        server.ask_local_llm('must never run')
        return {'ok': True}
    with patch.object(server, '_ask_local_llm', side_effect=infer) as llm, \
         patch.object(server, '_build_chat_payload', side_effect=build):
        events = server._chat_activity_events('question', key[0], request_token=key[1])
        assert next(events)['event'] == 'status'
        assert started.wait(3)
        assert server._cancel_chat(*key)
        release.set()
        remaining = list(events)
        assert remaining[-1]['data']['cancelled'] is True
        assert llm.call_count == 1
    assert key not in server._CHAT_CANCEL

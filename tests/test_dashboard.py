"""ダッシュボードの実測・状態通知を検証する。外部APIは呼び出さない。"""
from unittest.mock import patch

import local_ai_server as server
from functions.system_monitor import SystemMonitor


def test_system_monitor_returns_actual_backend_metrics():
    monitor = SystemMonitor()
    data = monitor.snapshot()
    assert data['ok']
    assert data['source'] == 'backend_pc'
    assert data['memory']['total_bytes'] > 0
    assert data['disk']['total_bytes'] > 0
    assert data['cpu']['logical_cores'] > 0
    assert data['network']['send_bytes_sec'] is None  # 初回に速度を捏造しない
    assert monitor.snapshot() is data  # 同時リクエストで採取間隔を壊さない


def test_monitor_missing_library_reports_failure():
    with patch('functions.system_monitor.psutil', None):
        assert not SystemMonitor().snapshot()['ok']


def test_activity_events_report_actual_cloud_call_before_answer():
    def build(*args, **kwargs):
        text = server.ask_cloud_ai('test')
        return {'ok': True, 'response': text}
    with patch.object(server, '_build_chat_payload', side_effect=build), patch.object(server, '_ask_cloud_ai', return_value='answer'):
        events = list(server._chat_activity_events('test', 'isolated'))
    assert [event['data'].get('state') for event in events[:-1]] == ['analyzing', 'cloud']
    assert events[-1] == {'event': 'done', 'data': {'ok': True, 'response': 'answer'}}
    assert not hasattr(server._ACTIVITY, 'callback')


def test_activity_exception_always_has_terminal_error():
    with patch.object(server, '_build_chat_payload', side_effect=RuntimeError('private detail')):
        events = list(server._chat_activity_events('test', 'isolated'))
    assert events[-1]['event'] == 'error'
    assert not events[-1]['data']['ok']
    assert 'private detail' not in events[-1]['data']['error']


def test_json_and_stream_keep_same_success_payload():
    payload = {'ok': True, 'response': 'hello', 'ui': {'type': 'cloud_api_consent'}, 'evaluation': {'api_called': False}}
    with patch.object(server, '_build_chat_payload', return_value=payload):
        events = list(server._chat_activity_events('hello', 'isolated'))
    assert events[-1]['data'] is payload

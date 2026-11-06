"""名前；真ん中: real TCP disconnects, scoped cancellation, and retry deduplication."""
import json
import select
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
import pytest
from openai import AsyncOpenAI as LoopbackAsyncOpenAI
from cloud import local_llm, openai_client
from models.request_control import RequestCancelled, request_scope
import local_ai_server as server


@pytest.fixture
def delayed_peer():
    started, disconnected = threading.Event(), threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length', 0)))
            # No headers yet: verify cancellation also interrupts time-to-first-byte.
            started.set()
            if select.select([self.connection], [], [], 6)[0]:
                if self.connection.recv(1) == b'':
                    disconnected.set()
    http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    try:
        yield f'http://127.0.0.1:{http.server_port}', started, disconnected
    finally:
        http.shutdown()
        http.server_close()


@pytest.mark.parametrize('kind', ['local', 'local_json', 'local_stream', 'cloud'])
def test_cancellation_closes_tcp_before_server_response(delayed_peer, kind):
    url, started, disconnected = delayed_peer
    signal, ended = threading.Event(), threading.Event()
    errors = []
    real_async_client = LoopbackAsyncOpenAI  # This test always sets base_url to its loopback peer.
    def invoke():
        try:
            with request_scope(signal):
                if kind == 'local':
                    local_llm.ask_local_llm('test', timeout=10)
                elif kind == 'local_json':
                    local_llm.ask_local_llm_json('test', timeout=10)
                elif kind == 'local_stream':
                    list(local_llm.stream_local_llm('test', timeout=10))
                else:
                    openai_client.ask_cloud_ai('test')
        except RequestCancelled:
            errors.append('cancelled')
        except Exception as error:
            errors.append(repr(error))
        finally:
            ended.set()
    with patch.object(local_llm, 'OLLAMA_HOST', url), \
         patch.object(openai_client, 'OPENAI_API_KEY', 'mock-key-not-real'), \
         patch.object(openai_client, 'AsyncOpenAI', side_effect=lambda **kw: real_async_client(base_url=url+'/v1', **kw)):
        worker = threading.Thread(target=invoke, daemon=True)
        worker.start()
        assert started.wait(5), 'transport never connected'
        begin = time.monotonic()
        signal.set()
        assert ended.wait(2), 'request waited for the delayed response'
        assert disconnected.wait(2), 'peer did not observe TCP close'
        assert errors == ['cancelled']
        assert time.monotonic()-begin < 2


def test_retry_replays_inflight_and_completed_operation_once():
    started, release = threading.Event(), threading.Event()
    def side_effect(*args, **kwargs):
        started.set()
        assert release.wait(3)
        return {'ok':True, 'response':'single execution'}
    operation = 'idempotence-'+str(time.monotonic_ns())
    with patch.object(server, '_build_chat_payload', side_effect=side_effect) as build:
        first = server._chat_activity_events('question', 'retry-session', operation_id=operation, request_token='first')
        assert next(first)['event'] == 'status'
        assert started.wait(2)
        second = server._chat_activity_events('question', 'retry-session', operation_id=operation, request_token='second')
        assert next(second)['event'] == 'status'
        release.set()
        assert list(first)[-1]['data']['response'] == 'single execution'
        assert list(second)[-1]['data']['response'] == 'single execution'
        assert list(server._chat_activity_events('question', 'retry-session', operation_id=operation))[-1]['data']['response']=='single execution'
        build.assert_called_once()
        conflict = list(server._chat_activity_events('different question', 'retry-session', operation_id=operation))
        assert conflict[-1]['data']['ok'] is False
        build.assert_called_once()


def test_cancelling_one_scope_does_not_cancel_another():
    first, second = threading.Event(), threading.Event()
    first.set()
    with request_scope(second):
        from models.request_control import run_cancellable
        import asyncio
        assert run_cancellable(lambda: asyncio.sleep(0, result='other chat intact')) == 'other chat intact'
    with pytest.raises(RequestCancelled), request_scope(first):
        pass

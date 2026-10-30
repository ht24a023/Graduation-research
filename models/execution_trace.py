"""実行した処理のみを記録する、リクエスト単位の計測とカード通知。"""
from __future__ import annotations
from collections import deque
from contextlib import contextmanager
from functools import wraps
import json
import math
import os
from pathlib import Path
import threading
import time
from uuid import uuid4

_context = threading.local()
_log_lock = threading.Lock()
LOG_PATH = Path(os.getenv('PROCESSING_LOG_PATH', 'data/processing_log.jsonl'))


@contextmanager
def event_sink(callback):
    previous = getattr(_context, 'sink', None)
    _context.sink = callback
    try:
        yield
    finally:
        _context.sink = previous


def emit(event, data):
    callback = getattr(_context, 'sink', None)
    if callback:
        callback({'event': event, 'data': data})


def append_log(record):
    with _log_lock:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open('a', encoding='utf-8') as file:
            file.write(json.dumps(record, ensure_ascii=False) + '\n')


def processing_history(session_id, limit=60):
    if not session_id or not LOG_PATH.exists():
        return []
    records = deque(maxlen=min(limit, 100))
    clients = {}
    with _log_lock:
        with LOG_PATH.open(encoding='utf-8') as file:
            for line in file:
                try:
                    item = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if item.get('session_id') != session_id:
                    continue
                if item.get('event') == 'client':
                    clients[item['request_id']] = item['timings']
                else:
                    records.append(item)
    return [{**row, 'client_timings': clients.get(row['request_id'], {})} for row in records]


def save_client_timings(request_id, session_id, timings):
    if not any(row['request_id'] == request_id for row in processing_history(session_id, 100)):
        return False
    allowed = {'first_text_display_sec', 'text_display_complete_sec', 'speech_recognition_sec',
               'speech_start_wait_sec', 'audio_output_complete_sec', 'audio_playback_sec'}
    clean = {key: round(value, 6) for key, value in timings.items() if key in allowed
             and isinstance(value, (int, float)) and not isinstance(value, bool)
             and math.isfinite(value) and 0 <= value <= 86400}
    append_log({'event': 'client', 'request_id': request_id, 'session_id': session_id, 'timings': clean})
    return True


def current_trace():
    return getattr(_context, 'trace', None)


class ExecutionTrace:
    def __init__(self):
        self.started = time.perf_counter()
        self.stages = []
        self.cards = []
        self.text_ready_sec = None
        self.stack = []

    def elapsed(self):
        return round(time.perf_counter() - self.started, 6)

    def snapshot(self):
        sums = {}
        for stage in self.stages:
            sums[stage['stage']] = round(sums.get(stage['stage'], 0) + stage.get('exclusive_sec', stage['duration_sec']), 6)
        return {'server_elapsed_sec': self.elapsed(), 'text_generation_complete_sec': self.text_ready_sec,
                'first_token_sec': None, 'stage_totals': sums, 'stages': list(self.stages)}


def run_stage(stage, function, *args, tool_name=None, success_check=None, **kwargs):
    trace = current_trace()
    if trace is None:
        return function(*args, **kwargs)
    started = time.perf_counter()
    frame = {'children_sec': 0.0}
    trace.stack.append(frame)
    emit('stage', {'stage': stage, 'tool_name': tool_name, 'status': 'running', 'elapsed_sec': trace.elapsed()})
    success = True
    try:
        result = function(*args, **kwargs)
        if success_check is not None:
            success = bool(success_check(result))
        elif isinstance(result, dict) and 'ok' in result:
            success = bool(result['ok'])
        return result
    except Exception:
        success = False
        raise
    finally:
        duration = time.perf_counter() - started
        trace.stack.pop()
        if trace.stack:
            trace.stack[-1]['children_sec'] += duration
        record = {'stage': stage, 'tool_name': tool_name, 'success': success,
                  'duration_sec': round(duration, 6), 'exclusive_sec': round(max(0, duration-frame['children_sec']), 6),
                  'completed_sec': trace.elapsed()}
        trace.stages.append(record)
        emit('stage', {**record, 'status': 'completed'})


def add_card(kind, data, *, success=True):
    trace = current_trace()
    card = {'kind': kind, 'data': data, 'success': bool(success), 'source': 'tool_result', 'event_id': uuid4().hex}
    if trace is not None:
        trace.cards.append(card)
        emit('card', card)
    return card


def mark_text_ready():
    trace = current_trace()
    if trace is not None:
        trace.text_ready_sec = trace.elapsed()


def traced_request(function):
    @wraps(function)
    def wrapped(message, session_id, **kwargs):
        if current_trace() is not None:
            return function(message, session_id, **kwargs)
        trace = ExecutionTrace()
        _context.trace = trace
        try:
            try:
                payload = function(message, session_id, **kwargs)
            except Exception as error:
                payload = {'ok': False, 'route': 'error', 'session_id': session_id,
                           'error': '処理中にエラーが発生しました。', 'error_type': type(error).__name__}
            if trace.text_ready_sec is None:
                trace.text_ready_sec = trace.elapsed()
            request_id = payload.get('evaluation', {}).get('request_id') or uuid4().hex
            execution = {**trace.snapshot(), 'request_id': request_id, 'session_id': session_id}
            payload['execution'] = execution
            payload['cards'] = trace.cards
            record = {'event': 'server', 'request_id': request_id, 'session_id': session_id,
                      'created_at': time.time(), 'message': message[:1000], 'route': payload.get('route'),
                      'success': bool(payload.get('ok')) and payload.get('route') != 'search_failed' and all(card['success'] for card in {card['kind']:card for card in trace.cards}.values()),
                      'execution': execution, 'cards': trace.cards}
            try:
                append_log(record)
            except OSError:
                payload['execution']['log_saved'] = False
            return payload
        finally:
            del _context.trace
    return wrapped

def processing_csv(session_id):
    import csv
    import io
    rows = processing_history(session_id, 100)
    columns = ['request_id','session_id','created_at','route','success','server_intent_sec','server_tool_sec',
               'server_local_llm_sec','server_cloud_llm_sec','server_text_generation_complete_sec',
               'server_first_token_sec','client_first_text_display_sec','client_text_display_complete_sec',
               'client_speech_recognition_sec','client_speech_start_wait_sec','client_audio_playback_sec',
               'client_audio_output_complete_sec']
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=columns); writer.writeheader()
    for row in rows:
        execution=row.get('execution',{}); totals=execution.get('stage_totals',{})
        record={key:row.get(key,'') for key in ['request_id','session_id','created_at','route','success']}
        for stage in ['intent','tool','local_llm','cloud_llm']:
            record['server_'+stage+'_sec']=totals.get(stage,'')
        record['server_text_generation_complete_sec']=execution.get('text_generation_complete_sec','')
        record['server_first_token_sec']=execution.get('first_token_sec','')
        for key,value in row.get('client_timings',{}).items():
            if 'client_'+key in columns: record['client_'+key]=value
        writer.writerow(record)
    return output.getvalue()


def traced_stage(stage):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            def successful(value):
                if value is None:
                    return False
                if isinstance(value, str) and value.startswith(('（Ollama', '（ローカルLLM', '(Ollama')):
                    return False
                return True
            return run_stage(stage, function, *args, success_check=successful, **kwargs)
        return wrapped
    return decorate

from pathlib import Path
p=Path('local_ai_server.py');s=p.read_text(encoding='utf-8');anchor='from models.execution_trace import';i=s.find(anchor);s=s[:i]+"from models.request_control import RequestCancelled as ChatCancelled, request_scope, check_cancelled\n"+s[i:]
start=s.index('class ChatCancelled(Exception):');end=s.index('_CHAT_CANCEL_LOCK',start);s=s[:start]+s[end:]
s=s.replace('_CHAT_CANCEL = {}', '_CHAT_CANCEL = {}\n_CHAT_FINISHED = {}\n_CHAT_OPERATIONS = {}',1)
s=s.replace('def _check_chat_cancelled():\n','def _check_chat_cancelled():\n    check_cancelled()\n',1)
start=s.index('def _chat_activity_events(');end=s.index('\n\n# サーバー全体',start)
new='''def _chat_activity_events(message, session_id, request_token='', operation_id='', stream_body=False, **kwargs):
    """Replay one logical operation across retries; cancel only its own HTTP transports."""
    operation_key = (session_id, operation_id or uuid4().hex)
    fingerprint = json.dumps([message, stream_body, kwargs], sort_keys=True, ensure_ascii=False)
    token_key = (session_id, request_token)
    with _CHAT_CANCEL_LOCK:
        now = time.monotonic()
        for key, value in list(_CHAT_OPERATIONS.items()):
            if value['finished'].is_set() and now-value['finished_at'] > 600:
                _CHAT_OPERATIONS.pop(key, None)
        record = _CHAT_OPERATIONS.get(operation_key)
        if record is not None and record['fingerprint'] != fingerprint:
            mismatch = True
        else:
            mismatch = False
        created = record is None
        if created:
            completed = [key for key, value in _CHAT_OPERATIONS.items() if value['finished'].is_set()]
            while len(_CHAT_OPERATIONS) >= 128 and completed:
                _CHAT_OPERATIONS.pop(completed.pop(0), None)
            if len(_CHAT_OPERATIONS) >= 128:
                record = None
            else:
                record = {'fingerprint': fingerprint, 'signal': threading.Event(),
                          'finished': threading.Event(), 'finished_at': now,
                          'condition': threading.Condition(), 'events': []}
                _CHAT_OPERATIONS[operation_key] = record
        if record is not None and not mismatch and request_token:
            _CHAT_CANCEL[token_key] = record['signal']
            _CHAT_FINISHED[token_key] = record['finished']
    if mismatch or record is None:
        yield {'event':'error', 'data':{'ok':False, 'error':'要求IDが重複しています。' if mismatch else '処理中の要求が多いため、しばらく待ってください。'}}
        return
    cancelled = record['signal']
    def publish(event):
        with record['condition']:
            record['events'].append(event)
            record['condition'].notify_all()
    def work():
        _ACTIVITY.cancelled = cancelled
        _ACTIVITY.callback = lambda data: publish({'event':'status', 'data':data})
        try:
            with request_scope(cancelled), event_sink(publish):
                _notify_activity('analyzing')
                if stream_body:
                    for event in _stream_chat_payload(message, session_id, **kwargs):
                        _check_chat_cancelled()
                        if event['event'] in {'done', 'error'}:
                            event['data'].setdefault('ok', event['event']=='done')
                        publish(event)
                else:
                    payload = _build_chat_payload(message, session_id, **kwargs)
                    _check_chat_cancelled()
                    publish({'event':'done' if payload.get('ok') else 'error', 'data':payload})
        except ChatCancelled:
            publish({'event':'error', 'data':{'ok':False, 'cancelled':True, 'error':'停止しました。'}})
        except Exception:
            publish({'event':'error', 'data':{'ok':False, 'error':'処理中にエラーが発生しました。'}})
        finally:
            del _ACTIVITY.callback
            del _ACTIVITY.cancelled
            record['finished_at'] = time.monotonic()
            record['finished'].set()
            with record['condition']:
                record['condition'].notify_all()
    if created:
        threading.Thread(target=work, daemon=True).start()
    cursor = 0
    try:
        while True:
            with record['condition']:
                if cursor >= len(record['events']) and not record['finished'].is_set():
                    record['condition'].wait(timeout=5)
                pending = record['events'][cursor:]
                cursor += len(pending)
                finished = record['finished'].is_set()
            for event in pending:
                yield event
                if event['event'] in {'done','error'}:
                    return
            if finished:
                return
            if not pending:
                yield {'event':'ping','data':{}}
    finally:
        if request_token:
            with _CHAT_CANCEL_LOCK:
                if _CHAT_CANCEL.get(token_key) is cancelled:
                    _CHAT_CANCEL.pop(token_key, None)
                    _CHAT_FINISHED.pop(token_key, None)
'''
s=s[:start]+new+s[end:]
old="      stopped = _cancel_chat(str(data.get('session_id', '')), str(data.get('request_token', '')))\n      self._send_json({'ok': True, 'cancellation_requested': stopped})"
new="      key = (str(data.get('session_id', '')), str(data.get('request_token', '')))\n      with _CHAT_CANCEL_LOCK:\n        finished = _CHAT_FINISHED.get(key)\n      stopped = _cancel_chat(*key)\n      ended = finished.wait(timeout=1.5) if stopped and finished is not None else False\n      self._send_json({'ok': True, 'cancellation_requested': stopped, 'worker_finished': ended})"
assert old in s;s=s.replace(old,new,1)
start=s.index('    if path == "/chat/stream":',s.index('  def do_POST'));end=s.index('    if "text/event-stream"',start)
s=s[:start]+'''    if path == "/chat/stream":
      self._send_sse_headers()
      try:
        for event in _chat_activity_events(message, session_id,
            request_token=str(data.get('request_token',''))[:128],
            operation_id=str(data.get('operation_id',''))[:128], stream_body=reply_style=='standard',
            current_location=current_location, experiment_mode=experiment_mode,
            test_case_id=test_case_id, turbo_mode=turbo_mode, reply_style=reply_style):
          self._send_sse_event(event['event'], event['data'])
      except (BrokenPipeError, ConnectionResetError):
        pass
      return

'''+s[end:]
s=s.replace("request_token=str(data.get('request_token', ''))[:128]):", "request_token=str(data.get('request_token', ''))[:128], operation_id=str(data.get('operation_id', ''))[:128]):",1)
# mark the version to inspect what a running server actually serves.
s=s.replace('<head>','<head>\n<meta name="central-chat-revision" content="20261101-cancel-v2">',1)
p.write_text(s,encoding='utf-8')
p=Path('cloud/local_llm.py');s=p.read_text(encoding='utf-8').replace('                values.put(error)','                try:\n                    values.put_nowait(error)\n                except queue.Full:\n                    pass',1);p.write_text(s,encoding='utf-8')

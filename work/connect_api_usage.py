from pathlib import Path
p=Path('cloud/openai_client.py');s=p.read_text(encoding='utf-8');s=s.replace('from functools import lru_cache','from functools import lru_cache\nimport time\nfrom models.api_usage import api_usage\nfrom models.request_control import RequestCancelled')
a=s.index('    if current_signal() is not None:');b=s.index('\n\ndef _answer_text',a)
s=s[:a]+'''    call = None
    response = None
    status = 'error'
    started = time.monotonic()
    try:
        try: call = api_usage.begin(CLOUD_MODEL)
        except Exception: pass
        if current_signal() is not None:
            async def request():
                nonlocal response
                async with AsyncOpenAI(api_key=api_key, timeout=60, max_retries=0) as client:
                    response = await client.chat.completions.create(
                        model=CLOUD_MODEL, messages=[{'role': 'user', 'content': text}])
                    return _answer_text(response)
            answer = run_cancellable(request)
        else:
            response = _get_client(api_key).chat.completions.create(
                model=CLOUD_MODEL, messages=[{'role': 'user', 'content': text}])
            answer = _answer_text(response)
        status = 'success'
        return answer
    except RequestCancelled:
        status = 'cancelled'
        raise
    except Exception:
        status = 'invalid_response' if response is not None else 'error'
        raise
    finally:
        if call:
            try: api_usage.finish(call, response, status, time.monotonic()-started)
            except Exception: pass
''' +s[b:];p.write_text(s,encoding='utf-8')
p=Path('functions/work_memory.py');s=p.read_text(encoding='utf-8').replace('from models.request_control import request_scope','from models.api_usage import usage_scope\nfrom models.request_control import request_scope').replace('with request_scope(self._cancel):text=self.generator(self._prompt(key,job,base))',"with request_scope(self._cancel), usage_scope('work_summary',session_key=key):text=self.generator(self._prompt(key,job,base))");p.write_text(s,encoding='utf-8')
p=Path('local_ai_server.py');s=p.read_text(encoding='utf-8');s='from models.api_usage import api_usage, usage_scope\n'+s if not s.startswith('from __future__') else s
# insert import after future import, if module has future
if 'from models.api_usage import' not in s:
 pos=s.index('\n',s.index('from __future__ import'));s=s[:pos+1]+'from models.api_usage import api_usage, usage_scope\n'+s[pos+1:]
pos=s.index('def ask_cloud_ai(');s=s[:pos]+'''def _cloud_answer(prompt, session_id, purpose):
    with usage_scope(purpose, session_id=session_id):
        return ask_cloud_ai(prompt)


'''+s[pos:]
s=s.replace('response=ask_cloud_ai(style_prompt(prompt, reply_style))',"response=_cloud_answer(style_prompt(prompt, reply_style), session_id, 'regeneration')").replace('cloud_response = ask_cloud_ai(str(pending.get("prompt", "")))',"cloud_response = _cloud_answer(str(pending.get(\"prompt\", \"\")), session_id, 'delegation')").replace('cloud_response = ask_cloud_ai(prompt)',"cloud_response = _cloud_answer(prompt, session_id, 'conversation')")
s=s.replace('  <script src="/site/dashboard/research.js"></script>','  <script src="/site/dashboard/research.js"></script>\n  <link rel="stylesheet" href="/site/dashboard/api_usage.css">\n  <script src="/site/dashboard/api_usage.js"></script>')
s=s.replace('if path in {"/site/dashboard/work_memory_ui.js",','if path in {"/site/dashboard/api_usage.js", "/site/dashboard/api_usage.css", "/site/dashboard/work_memory_ui.js",')
pos=s.index('    if path == "/research/summary":');s=s[:pos]+'''    if path == '/api-usage':
      if not self._notification_guard(): return
      try:
        self._send_json(api_usage.snapshot(str((query.get('period') or ['month'])[0])))
      except ValueError as exc:
        self._send_json({'ok': False, 'error': str(exc)}, status=400)
      return

'''+s[pos:]
pos=s.index("    if path == '/memory/work-summary':",s.index('  def do_POST'))
s=s[:pos]+'''    if path == '/api-usage/settings':
      if not self._notification_guard(write=True): return
      try:
        length=int(self.headers.get('Content-Length','0'))
        if not 0<length<=3000: raise ValueError('入力が不正です。')
        data=json.loads(self.rfile.read(length).decode('utf-8'))
        if not isinstance(data,dict): raise ValueError('入力が不正です。')
        api_usage.update_settings(data)
        self._send_json({'ok':True})
      except (OSError, ValueError, TypeError, UnicodeError) as exc:
        self._send_json({'ok':False,'error':'設定を保存できませんでした。数値を確認してください。'},status=400)
      return

'''+s[pos:];p.write_text(s,encoding='utf-8')
p=Path('conftest.py');s=p.read_text(encoding='utf-8').replace('def no_live_paid_api(monkeypatch):','def no_live_paid_api(monkeypatch, tmp_path):').replace('    from cloud import openai_client','    from cloud import openai_client\n    from models.api_usage import ApiUsage\n    monkeypatch.setattr(openai_client, "api_usage", ApiUsage(tmp_path/"usage.jsonl", tmp_path/"settings.json", tmp_path/"official.json"))');p.write_text(s,encoding='utf-8')

from pathlib import Path
p=Path('cloud/openai_client.py');s=p.read_text(encoding='utf-8');s=s.replace('from config import OPENAI_API_KEY','from config import OPENAI_API_KEY\nfrom cloud import model_catalog')
s=s.replace("@traced_stage('cloud_llm')",'''@lru_cache(maxsize=8)
def _get_provider_client(api_key, base_url):
    return OpenAI(api_key=api_key, base_url=base_url, timeout=60, max_retries=0)


@traced_stage('cloud_llm')''')
s=s.replace("    api_key = (OPENAI_API_KEY or '').strip()",'''    choice = model_catalog.current()
    provider = choice['provider']
    model = choice['model']
    api_key = ((OPENAI_API_KEY or model_catalog.key(provider)) if provider=='openai' else model_catalog.key(provider)).strip()
    base_url = {'openrouter':'https://openrouter.ai/api/v1', 'ollama_local':__import__('config').OLLAMA_HOST.rstrip('/')+'/v1'}.get(provider)
    client_options = {'api_key':api_key, 'timeout':60, 'max_retries':0}
    if base_url:client_options['base_url']=base_url''')
s=s.replace("'クラウドAIのAPIキーが未設定です。.env の OPENAI_API_KEY を設定して再起動してください。'", "('クラウドAIのAPIキーが未設定です。チャット右の「モデル変更」で'+('OpenRouter' if provider=='openrouter' else 'OpenAI')+'のAPIキーを設定してください。')")
s=s.replace('api_usage.begin(CLOUD_MODEL)',"api_usage.begin(model, provider=provider, free=choice['free'], model_choice=choice['id'])")
s=s.replace('AsyncOpenAI(api_key=api_key, timeout=60, max_retries=0)','AsyncOpenAI(**client_options)').replace('model=CLOUD_MODEL','model=model')
s=s.replace("response = _get_client(api_key).chat.completions.create(","client = _get_provider_client(api_key, base_url) if base_url else _get_client(api_key)\n            response = client.chat.completions.create(")
p.write_text(s,encoding='utf-8')
p=Path('models/api_usage.py');s=p.read_text(encoding='utf-8').replace("PRICES={'gpt-4.1-mini':", "PRICES={'gpt-4.1-nano':{'input':.10,'cached_input':.025,'output':.40,'as_of':'2026-11-06'},'gpt-4.1':{'input':2.,'cached_input':.50,'output':8.,'as_of':'2026-11-06'},'gpt-4.1-mini':")
# longest matching prefix avoids treating mini/nano snapshots as full GPT-4.1
s=s.replace('for key,rate in PRICES.items()', 'for key,rate in sorted(PRICES.items(),key=lambda item:-len(item[0]))')
s=s.replace('def begin(self,model):','def begin(self,model,provider="openai",free=False,model_choice=None):').replace("'model':model,**_SCOPE.get()","'model':model,'provider':provider,'free':free,'model_choice':model_choice,**_SCOPE.get()")
s=s.replace("response_id=field(response,'id')", "if started.get('free') and status=='success':cost,basis=0.0,'free_model'\n            response_id=field(response,'id')")
s=s.replace("'price_as_of':price_for(model)['as_of'] if price_for(model) else None", "'price_as_of':price_for(model)['as_of'] if price_for(model) and not started.get('free') else None")
p.write_text(s,encoding='utf-8')
p=Path('local_ai_server.py');s=p.read_text(encoding='utf-8');s=s.replace('from models.api_usage import api_usage, usage_scope','from models.api_usage import api_usage, usage_scope\nfrom cloud import model_catalog')
s=s.replace('def _cloud_answer(prompt, session_id, purpose):\n    with usage_scope(purpose, session_id=session_id):','def _cloud_answer(prompt, session_id, purpose, model_id=None):\n    with usage_scope(purpose, session_id=session_id), model_catalog.model_scope(model_id or model_catalog.selected(session_id)):')
s=s.replace('  _check_chat_cancelled()\n  reply_style = normalize_style(reply_style)','  _check_chat_cancelled()\n  selected_model = model_catalog.selected(session_id)\n  reply_style = normalize_style(reply_style)',1)
s=s.replace("session_id, 'regeneration')","session_id, 'regeneration', selected_model)").replace("session_id, 'delegation')","session_id, 'delegation', selected_model)").replace("session_id, 'conversation')","session_id, 'conversation', selected_model)")
s=s.replace('cache_key += "|reply-style=" + reply_style + "|memory=" + memory_revision()','cache_key += "|reply-style=" + reply_style + "|memory=" + memory_revision() + "|model=" + selected_model')
s=s.replace('      "reply_style": reply_style,\n      "routing_reason"','      "reply_style": reply_style,\n      "model_choice": selected_model,\n      "routing_reason"')
s=s.replace("str(payload.get('source_question') or message),response_text)","str(payload.get('source_question') or message),response_text, model_id=selected_model)")
s=s.replace('  <script src="/site/dashboard/api_usage.js"></script>','  <script src="/site/dashboard/api_usage.js"></script>\n  <link rel="stylesheet" href="/site/dashboard/model_picker.css">\n  <script src="/site/dashboard/model_picker.js"></script>')
s=s.replace('if path in {"/site/dashboard/api_usage.js",','if path in {"/site/dashboard/model_picker.js", "/site/dashboard/model_picker.css", "/site/dashboard/api_usage.js",')
pos=s.index("    if path == '/api-usage':")
s=s[:pos]+'''    if path == '/cloud-models':
      if not self._notification_guard(): return
      session_id=str((query.get('session_id') or [''])[0])[:128]
      self._send_json(model_catalog.snapshot(session_id))
      return

'''+s[pos:]
pos=s.index("    if path == '/api-usage/settings':")
s=s[:pos]+'''    if path == '/cloud-models':
      if not self._notification_guard(write=True): return
      try:
        length=int(self.headers.get('Content-Length','0'))
        if not 0<length<=3000:raise ValueError('入力が不正です。')
        data=json.loads(self.rfile.read(length).decode('utf-8'))
        if not isinstance(data,dict):raise ValueError('入力が不正です。')
        session_id=str(data.get('session_id',''))[:128]
        if data.get('action')=='key':model_catalog.save_key(data.get('provider'),data.get('key'))
        elif data.get('action')=='select':model_catalog.choose(session_id,data.get('model_id'))
        else:raise ValueError('操作が不正です。')
        self._send_json(model_catalog.snapshot(session_id))
      except (OSError,ValueError,TypeError,UnicodeError):
        self._send_json({'ok':False,'error':'モデル設定を保存できませんでした。入力を確認してください。'},status=400)
      return

'''+s[pos:]
p.write_text(s,encoding='utf-8')
p=Path('functions/work_memory.py');s=p.read_text(encoding='utf-8').replace('from models.api_usage import usage_scope','from models.api_usage import usage_scope\nfrom cloud import model_catalog')
s=s.replace('self._pending={};self._states={};self._contexts={};','self._models={};self._pending={};self._states={};self._contexts={};')
s=s.replace('def enqueue(self,session_id,question,answer):','def enqueue(self,session_id,question,answer,model_id=None):').replace('            contexts=self._contexts.setdefault(key,deque(maxlen=3))','            self._models[key]=model_id or model_catalog.selected(session_id)\n            contexts=self._contexts.setdefault(key,deque(maxlen=3))')
s=s.replace("'contexts':list(self._contexts[key])}","'contexts':list(self._contexts[key]),'model_id':self._models.get(key,model_catalog.DEFAULT_MODEL)}")
s=s.replace("with request_scope(self._cancel), usage_scope('work_summary',session_key=key):", "with request_scope(self._cancel), usage_scope('work_summary',session_key=key), model_catalog.model_scope(job['model_id']):")
p.write_text(s,encoding='utf-8')

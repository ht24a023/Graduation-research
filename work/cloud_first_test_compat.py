from pathlib import Path
p=Path('local_ai_server.py');s=p.read_text(encoding='utf-8');s=s.replace("policy = routing_decision(effective_message, requested_tool) if experiment_mode == 'CLOUD_FIRST' else None", "policy = ({'intent':'tool','tool':tool_request,'reason':'パネルで選択された専用機能を実行'} if tool_request else routing_decision(effective_message, requested_tool)) if experiment_mode == 'CLOUD_FIRST' else None",1)
s=s.replace("    else:\n      response = ask_local_llm(style_prompt(prompt, reply_style), timeout=REQUEST_TIMEOUT)\n    local_time_sec += time.perf_counter() - local_started", "    else:\n      response = ask_local_llm(style_prompt(prompt, reply_style), timeout=REQUEST_TIMEOUT)\n      local_time_sec += time.perf_counter() - local_started",1)
# The optional assist endpoint must predict the same deployed policy as the chat endpoint.
a=s.index('  confidence = 0.52',s.index('def _build_chat_assist_payload'));s=s[:a]+'''  if _resolve_routing_mode(None) == 'CLOUD_FIRST':
    decision=routing_decision(normalized,tool_request)
    tool_request=decision.get('tool')
    intent=decision['intent']
    route_hint='cloud_llm' if intent=='chat' else 'local_function'

'''+s[a:]
s=s.replace('    analysis = "自由対話としてローカルLLMへ渡す想定です。"', '    analysis = "一般対話としてクラウドAIへ渡します。" if route_hint=="cloud_llm" else "自由対話としてローカルLLMへ渡す想定です。"',1)
p.write_text(s,encoding='utf-8')
# These tests intentionally exercise the retained legacy local-first experiment mode.
for name,anchor in [('tests/test_post_answer_cloud.py','    monkeypatch.chdir(tmp_path)'),('tests/test_research_completion.py','    monkeypatch.chdir(tmp_path)')]:
 p=Path(name);s=p.read_text(encoding='utf-8');s=s.replace(anchor,anchor+'\n    monkeypatch.setattr(server,\'ROUTING_MODE_DEFAULT\',\'DYNAMIC_ROUTING\')',1);p.write_text(s,encoding='utf-8')
p=Path('tests/test_chat_actions.py');s=p.read_text(encoding='utf-8');s=s.replace('regenerate=True, regenerate_from=', "experiment_mode='LOCAL_ONLY', regenerate=True, regenerate_from=",1);p.write_text(s,encoding='utf-8')
p=Path('tests/test_research_browser.py');s=p.read_text(encoding='utf-8');s=s.replace("def forbidden(*a,**k):raise AssertionError('Cloud must not be called')", "def forbidden(*a,**k):return '保存メモでは音声入力の停止操作を確認済みです。'");p.write_text(s,encoding='utf-8')
p=Path('tests/test_post_answer_cloud_browser.py');s=p.read_text(encoding='utf-8');s=s.replace("    monkeypatch.chdir(tmp_path);calls=[]", "    monkeypatch.chdir(tmp_path);calls=[]\n    monkeypatch.setattr(server,'ROUTING_MODE_DEFAULT','DYNAMIC_ROUTING')",1);p.write_text(s,encoding='utf-8')

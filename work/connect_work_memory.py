from pathlib import Path
p=Path('functions/work_memory.py');s=p.read_text(encoding='utf-8');s=s.replace('        except (OSError,ValueError,AttributeError):return True', '        except FileNotFoundError:return True\n        except (OSError,ValueError,AttributeError):return False',1)
a=s.index('        path=self.settings_path();path.parent');b=s.index('\n    def _state',a);chunk=s[a:b];s=s[:a]+'        with self._condition:\n'+''.join('    '+line if line.strip() else line for line in chunk.splitlines(keepends=True))+s[b:];p.write_text(s,encoding='utf-8')
p=Path('local_ai_server.py');s=p.read_text(encoding='utf-8');s=s.replace('from functions.routing_policy import decide as routing_decision','from functions.work_memory import work_memory\nfrom functions.routing_policy import decide as routing_decision',1)
s=s.replace('    _clear_pending_api_approval_for_session(session_id)\n    for key', '    _clear_pending_api_approval_for_session(session_id)\n    work_memory.cancel_session(session_id)\n    for key',1)
s=s.replace('    _PENDING_API_APPROVAL.clear()\n    _RESPONSE_CACHE.clear()', '    _PENDING_API_APPROVAL.clear()\n    work_memory.cancel_all()\n    _RESPONSE_CACHE.clear()',1)
a=s.index('    return _attach_evaluation(',s.index('def _build_chat_payload('));b=s.index('\n  if regenerate:',a);chunk=s[a:b];chunk=chunk.replace('    return _attach_evaluation(', '    evaluated = _attach_evaluation(',1);chunk+='''
    if ok and api_called:
      evaluated['background_memory']=work_memory.enqueue(session_id,str(payload.get('source_question') or message),response_text)
    return evaluated
''';s=s[:a]+chunk+s[b:]
s=s.replace("'scope': 'この質問と表示中の回答（失敗時はエラー内容）をOpenAIへ送信します。料金が発生する場合があります。'", "'scope': 'この質問と表示中の回答（失敗時はエラー内容）をOpenAIへ送信します。自動記憶がオンの場合は、回答後に直近のクラウド対話と既存の作業要約から別のAPI呼び出しで要約します。料金が発生する場合があります。'",1)
s=s.replace('クラウドには質問・会話履歴・関連する保存情報を送信します。', 'クラウドには質問・会話履歴・関連する保存情報を送信します。回答後の作業要約も自動で生成します（追加API利用）。記憶ネットワークで停止・編集できます。',1)
a=s.index('    if path == "/memory/graph":',s.index('  def do_GET'))
s=s[:a]+'''    if path == '/memory/work-summary':
      if not self._notification_guard():
        return
      session_id=str((query.get('session_id') or [''])[0])[:128]
      self._send_json(work_memory.status(session_id))
      return

'''+s[a:]
a=s.index("    if path == '/memory/graph':",s.index('  def do_POST'))
s=s[:a]+'''    if path == '/memory/work-summary':
      if not self._notification_guard(write=True):
        return
      try:
        length=int(self.headers.get('Content-Length','0'))
        if not 0<length<=3000:raise ValueError('入力が不正です。')
        data=json.loads(self.rfile.read(length).decode('utf-8'))
        if not isinstance(data,dict):raise ValueError('入力が不正です。')
        session_id=str(data.get('session_id',''))[:128]
        if data.get('action')=='set_enabled':work_memory.set_enabled(data.get('enabled'))
        elif data.get('action')=='retry':work_memory.retry(session_id)
        else:raise ValueError('操作が不正です。')
        self._send_json(work_memory.status(session_id))
      except (OSError,ValueError,TypeError,UnicodeError):
        self._send_json({'ok':False,'error':'設定または要約を更新できませんでした。'},status=400)
      return

'''+s[a:]
p.write_text(s,encoding='utf-8')
p=Path('functions/memory_graph.py');s=p.read_text(encoding='utf-8');s=s.replace("'source': '保存メモ', 'kind': n.get('type', 'note')", "'source': ('クラウド作業要約・更新案' if n.get('summary_proposal') else 'クラウド作業要約（AI生成）') if n.get('source')=='cloud_work_summary' else '保存メモ', 'user_edited':bool(n.get('user_edited')), 'summary_revision':n.get('summary_revision'), 'kind':n.get('type','note')")
s=s.replace("            memory.upsert_titled_note(title, content.strip())", """            note=next((n for n in notes if n.get('title')==title),None)
            if note and note.get('source')=='cloud_work_summary':
                store=memory.load_notes()
                for saved in store['notes']:
                    if saved.get('title')==title:
                        saved.update(content=content.strip(),user_edited=True,updated_at=memory._now_iso())
                memory.save_notes(store)
            else:
                memory.upsert_titled_note(title, content.strip())""",1);p.write_text(s,encoding='utf-8')
p=Path('site/dashboard/workbench.js');s=p.read_text(encoding='utf-8');s=s.replace('routing_reason:data.routing_reason,', 'session_id:data.session_id,background_memory:data.background_memory,routing_reason:data.routing_reason,',1);p.write_text(s,encoding='utf-8')
p=Path('conftest.py');s=p.read_text(encoding='utf-8');s=s.replace('    from cloud import openai_client', "    from cloud import openai_client\n    from functions.work_memory import work_memory\n    monkeypatch.setattr(work_memory,'enqueue',lambda *args,**kwargs:{'state':'disabled','extra_cloud_request':False})",1);p.write_text(s,encoding='utf-8')

from pathlib import Path
p=Path('local_ai_server.py');s=p.read_text(encoding='utf-8');s=s.replace('def _clear_pending_api_approval_for_session(session_id: str) -> None:', 'def _clear_pending_api_approval_for_session(session_id: str, preserve_post_answers: bool = False) -> None:',1)
s=s.replace('      if (item.get("session_id") or "") == session_id\n    ]', '      if (item.get("session_id") or "") == session_id\n      and not (preserve_post_answers and item.get("kind") == "post_answer")\n    ]',1)
s=s.replace('return any((item.get("session_id") or "") == session_id for item in _PENDING_API_APPROVAL.values())', 'return any((item.get("session_id") or "") == session_id and item.get("kind") != "post_answer" for item in _PENDING_API_APPROVAL.values())',1)
# The reset path intentionally retains the default: revoke every offer.
a=s.index('  if reject_token:',s.index('def _build_chat_payload('));b=s.index('# SSEで',a)
chunk=s[a:b].replace('_clear_pending_api_approval_for_session(session_id)', '_clear_pending_api_approval_for_session(session_id, preserve_post_answers=True)');s=s[:a]+chunk+s[b:]
p.write_text(s,encoding='utf-8')
p=Path('site/dashboard/dashboard.js');s=p.read_text(encoding='utf-8');s=s.replace("detail('ディスク動作負荷', pct(data.disk.active_percent),", "detail('ディスク動作負荷', typeof data.disk.active_percent==='number'?pct(data.disk.active_percent):'未取得',",1);p.write_text(s,encoding='utf-8')

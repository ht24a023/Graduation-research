from pathlib import Path
p=Path('local_ai_server.py');s=p.read_text(encoding='utf-8')
a=s.index('def _set_pending_api_approval(');b=s.index('\n\ndef _build_google_then_api_prompt',a)
s=s[:a]+'''API_APPROVAL_TTL_SECONDS = 600


def _set_pending_api_approval(token: str, payload: dict[str, Any]) -> None:
  with _SESSION_LOCK:
    _PENDING_API_APPROVAL[token] = {**payload, "created_at": time.monotonic()}


def _pop_pending_api_approval(token: str, session_id: str, decision: str) -> dict[str, Any] | None:
  """Atomically consume only the selected request, including its opposite button."""
  with _SESSION_LOCK:
    pending = _PENDING_API_APPROVAL.get(token)
    if not pending or pending.get("session_id") != session_id:
      return None
    if time.monotonic() - pending.get("created_at", 0) > API_APPROVAL_TTL_SECONDS:
      _PENDING_API_APPROVAL.pop(token, None)
      return None
    if pending.get("decision", "approve") != decision:
      return None
    group = pending.get("approval_group", token)
    for key, item in list(_PENDING_API_APPROVAL.items()):
      if item.get("session_id") == session_id and item.get("approval_group", key) == group:
        _PENDING_API_APPROVAL.pop(key, None)
    return pending
'''+s[b:]
s=s.replace('_pop_pending_api_approval(approve_token)', '_pop_pending_api_approval(approve_token, session_id, "approve")').replace('_pop_pending_api_approval(reject_token)', '_pop_pending_api_approval(reject_token, session_id, "reject")')
s=s.replace('    approval_token = uuid4().hex\n    reject_token = uuid4().hex', '    _clear_pending_api_approval_for_session(session_id)\n    approval_token = uuid4().hex\n    reject_token = uuid4().hex\n    approval_group = uuid4().hex')
# Add bound decisions to the two production buttons only.
a=s.index('    _set_pending_api_approval(\n      approval_token,');b=s.index('\n    response_text = _format_structured_search_response',a)
chunk=s[a:b];chunk=chunk.replace('"session_id": session_id,', '"session_id": session_id,\n        "decision": "approve",\n        "approval_group": approval_group,',1)
i=chunk.index('      reject_token,');chunk=chunk[:i]+chunk[i:].replace('"session_id": session_id,', '"session_id": session_id,\n        "decision": "reject",\n        "approval_group": approval_group,',1);s=s[:a]+chunk+s[b:]
s=s.replace('"description": "料金が発生する可能性があります。実行する場合のみ選択してください。",','"description": "この質問・会話履歴・選択された保存情報をクラウドAIへ送信します。料金が発生する可能性があります。承認はこの回答の一回限り・10分間有効です。",')
p.write_text(s,encoding='utf-8')
p=Path('tests/test_reply_style.py');s=p.read_text(encoding='utf-8');s=s.replace("{'session_id':'reject-style',", "{'decision':'reject','session_id':'reject-style',");p.write_text(s,encoding='utf-8')

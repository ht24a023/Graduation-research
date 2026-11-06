from pathlib import Path
p=Path('local_ai_server.py');s=p.read_text(encoding='utf-8');s=s.replace('_PENDING_API_APPROVAL: dict[str, dict[str, str]]', '_PENDING_API_APPROVAL: dict[str, dict[str, Any]]')
s=s.replace('    _clear_pending_api_approval_for_session(session_id)\n    return cleared_history', '''    _clear_pending_api_approval_for_session(session_id)
    for key in list(_RESPONSE_CACHE):
      if key.startswith(session_id.strip() + '|'):
        _RESPONSE_CACHE.pop(key, None)
    return cleared_history''',1)
s=s.replace('    _PENDING_API_APPROVAL.clear()\n\n\ndef _list_sessions', '    _PENDING_API_APPROVAL.clear()\n    _RESPONSE_CACHE.clear()\n    _RESPONSE_CACHE_ORDER.clear()\n\n\ndef _list_sessions',1)
s=s.replace('  with _SESSION_LOCK:\n    return any((item.get("session_id") or "") == session_id for item in _PENDING_API_APPROVAL.values())', '''  with _SESSION_LOCK:
    now = time.monotonic()
    for token, item in list(_PENDING_API_APPROVAL.items()):
      if now - item.get("created_at", 0) > API_APPROVAL_TTL_SECONDS:
        _PENDING_API_APPROVAL.pop(token, None)
    return any((item.get("session_id") or "") == session_id for item in _PENDING_API_APPROVAL.values())''',1)
p.write_text(s,encoding='utf-8')

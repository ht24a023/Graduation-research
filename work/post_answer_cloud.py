from pathlib import Path
p=Path('local_ai_server.py');s=p.read_text(encoding='utf-8')
s=s.replace('API_APPROVE_PREFIX = "__API_APPROVE__"','API_APPROVE_PREFIX = "__API_APPROVE__"\nCLOUD_DELEGATE_PREFIX = "__CLOUD_DELEGATE__"')
s=s.replace('  approve_token = _approval_token(message, API_APPROVE_PREFIX)', '  approve_token = _approval_token(message, API_APPROVE_PREFIX) or _approval_token(message, CLOUD_DELEGATE_PREFIX)',1)
s=s.replace('    message.startswith(API_APPROVE_PREFIX)\n', '    message.startswith(API_APPROVE_PREFIX)\n    or message.startswith(CLOUD_DELEGATE_PREFIX)\n',1)
s=s.replace('  if message.startswith(API_APPROVE_PREFIX) and not approve_token:', '  if (message.startswith(API_APPROVE_PREFIX) or message.startswith(CLOUD_DELEGATE_PREFIX)) and not approve_token:',1)
a=s.index('\ndef _build_google_then_api_prompt(')
helper='''
def _offer_cloud_delegation(payload, message, session_id, experiment_mode=None, reply_style='standard'):
  """Issue an answer-bound consent token; issuing it never makes a cloud call."""
  if payload.get('cloud_delegation') or payload.get('cancelled'):
    return payload
  if _resolve_routing_mode(experiment_mode) == 'LOCAL_ONLY' or str(message).startswith('__'):
    return payload
  if payload.get('route') == 'cloud_fallback' or payload.get('evaluation', {}).get('api_called'):
    return payload
  question = str(message).strip()[:20000]
  answer = str(payload.get('response') or payload.get('error') or '').strip()[:30000]
  if not question or not answer:
    return payload
  token = uuid4().hex
  prompt = style_prompt(
    'あなたはローカルAIの回答を改善するアシスタントです。以下の質問と既存の回答を参考に、'
    '必要な修正を行い、日本語で分かりやすい最終回答を生成してください。'
    '既存の回答には誤りが含まれる可能性があります。外部ツールを実行したと主張しないでください。'
    '情報不足の場合は推測で埋めず確認点を示してください。\\n'
    + '[元の質問]\\n' + question + '\\n[既存の回答またはエラー]\\n' + answer,
    normalize_style(reply_style))
  with _SESSION_LOCK:
    # Expire old offers and bound retained prompt size per session.
    now = time.monotonic()
    for key, item in list(_PENDING_API_APPROVAL.items()):
      if now - item.get('created_at', 0) > API_APPROVAL_TTL_SECONDS:
        _PENDING_API_APPROVAL.pop(key, None)
    offers = [key for key, item in _PENDING_API_APPROVAL.items()
              if item.get('session_id') == session_id and item.get('kind') == 'post_answer']
    for key in offers[:-11]:
      _PENDING_API_APPROVAL.pop(key, None)
    _set_pending_api_approval(token, {'session_id': session_id, 'decision': 'approve',
        'kind': 'post_answer', 'prompt': prompt, 'message': question, 'reply_style': reply_style})
  payload['cloud_delegation'] = {'message': CLOUD_DELEGATE_PREFIX + ':' + token,
      'expires_in_sec': API_APPROVAL_TTL_SECONDS,
      'scope': 'この質問と表示中の回答（失敗時はエラー内容）をOpenAIへ送信します。料金が発生する場合があります。'}
  return payload

'''
s=s[:a]+helper+s[a:]
s=s.replace('    mark_text_ready()\n    elapsed =', '    if not api_called:\n      _offer_cloud_delegation(payload, message, session_id, experiment_mode, reply_style)\n    mark_text_ready()\n    elapsed =',1)
s=s.replace("                            event['data'].setdefault('ok', event['event']=='done')", "                            event['data'].setdefault('ok', event['event']=='done')\n                            _offer_cloud_delegation(event['data'], message, session_id, kwargs.get('experiment_mode'), kwargs.get('reply_style', 'standard'))",1)
s=s.replace('承認待ちのAPI呼び出しが見つかりませんでした。','承認が期限切れ・使用済み、または別の会話のため実行できません。元の質問をもう一度送信してください。')
s=s.replace("document.querySelectorAll('[data-chat-action]').forEach(button => button.disabled = value);", "document.querySelectorAll('[data-chat-action]').forEach(button => button.disabled = value || button.dataset.cloudConsumed === 'true');")
a=s.index('    function setChatBusy(')
ui='''    function addCloudDelegation(bubble, data, request) {
      const offer = data.cloud_delegation;
      if (!offer?.message) return;
      const button = chatAction(bubble, 'クラウドに委託して回答を改善', () => {
        if (button.dataset.cloudConsumed === 'true') return;
        if (!confirm(offer.scope + '\\nこの回答について一回だけ実行します。続けますか？')) return;
        button.dataset.cloudConsumed = 'true'; button.disabled = true; button.textContent = 'クラウドへ委託済み';
        sendMessage({message: offer.message, session_id: request.session_id,
          reply_style: request.reply_style, operation_id: crypto.randomUUID(),
          reuseQuestion: true, cloudDelegation: true});
      });
      button.dataset.cloudDelegate = 'true'; button.title = offer.scope;
      const note = document.createElement('small');note.className = 'cloud-delegate-note';note.textContent = offer.scope + ' 承認は10分・一回限りです。';bubble.append(note);
    }
'''
s=s[:a]+ui+s[a:]
s=s.replace("          if(options.regenerate){const version=", "          if(options.cloudDelegation){const badge=document.createElement('div');badge.className='chat-version-label';badge.textContent='クラウド（OpenAI API）で生成した追加回答';answer.prepend(badge);}\n          if(options.regenerate){const version=",1)
s=s.replace("          addFollowupPanel(data.followups);", "          addCloudDelegation(answer, data, request);\n          addFollowupPanel(data.followups);",1)
s=s.replace("          addBubble('assistant', data.error || 'error');", "          const failedAnswer = addBubble('assistant', data.error || 'error');\n          addCloudDelegation(failedAnswer, data, request);",1)
p.write_text(s,encoding='utf-8')
p=Path('site/dashboard/dashboard.css');s=p.read_text(encoding='utf-8');s+='\n.cloud-delegate-note{display:block;margin-top:7px;color:#a4bfce;font-size:10px;line-height:1.6;}\n';p.write_text(s,encoding='utf-8')
p=Path('cloud/openai_client.py');s=p.read_text(encoding='utf-8');s=s.replace('return OpenAI(api_key=api_key)', 'return OpenAI(api_key=api_key, timeout=60, max_retries=0)');s=s.replace('AsyncOpenAI(api_key=api_key, max_retries=0)', 'AsyncOpenAI(api_key=api_key, timeout=60, max_retries=0)');s=s.replace('                return response.choices[0].message.content', '                return _answer_text(response)');s=s.replace('    return response.choices[0].message.content', '    return _answer_text(response)');s+='''

def _answer_text(response):
    text = response.choices[0].message.content if response.choices else None
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError('クラウドAIが空の回答を返しました。')
    return text.strip()
''';p.write_text(s,encoding='utf-8')
p=Path('tests/test_cloud_startup.py');s=p.read_text(encoding='utf-8');s=s.replace("factory.assert_called_once_with(api_key='test-key')", "factory.assert_called_once_with(api_key='test-key', timeout=60, max_retries=0)");p.write_text(s,encoding='utf-8')

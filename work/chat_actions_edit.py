from pathlib import Path
root=Path(r'C:\Users\ht24a023\Documents\Codex\sotuken')
p=root/'local_ai_server.py';s=p.read_text(encoding='utf-8')
anchor='def _notify_activity(state):'
helpers='''class ChatCancelled(Exception):
    """Cooperative cancellation; completed external effects cannot be undone."""


_CHAT_CANCEL_LOCK = threading.Lock()
_CHAT_CANCEL = {}


def _check_chat_cancelled():
    signal = getattr(_ACTIVITY, 'cancelled', None)
    if signal is not None and signal.is_set():
        raise ChatCancelled('要求は停止されました')


def _cancel_chat(session_id, token):
    with _CHAT_CANCEL_LOCK:
        signal = _CHAT_CANCEL.get((session_id, token))
        if signal is not None:
            signal.set()
        return signal is not None


'''
s=s.replace(anchor,helpers+anchor).replace('def _notify_activity(state):\n','def _notify_activity(state):\n    _check_chat_cancelled()\n')
s=s.replace("    result = run_stage('tool',", "    _check_chat_cancelled()\n    result = run_stage('tool',",1)
s=s.replace('    return _ask_local_llm(*args, **kwargs)', '    result = _ask_local_llm(*args, **kwargs)\n    _check_chat_cancelled()\n    return result')
s=s.replace('    return _ask_cloud_ai(*args, **kwargs)', '    result = _ask_cloud_ai(*args, **kwargs)\n    _check_chat_cancelled()\n    return result')
s=s.replace('def _chat_activity_events(message, session_id, **kwargs):', "def _chat_activity_events(message, session_id, request_token='', **kwargs):")
s=s.replace('    events = queue.Queue()\n\n    def work():', "    events = queue.Queue()\n    cancelled = threading.Event()\n    key = (session_id, request_token)\n    if request_token:\n        with _CHAT_CANCEL_LOCK:\n            _CHAT_CANCEL[key] = cancelled\n\n    def work():\n        _ACTIVITY.cancelled = cancelled",1)
s=s.replace('            events.put({"event": "done" if payload.get("ok") else "error", "data": payload})','            _check_chat_cancelled()\n            events.put({"event": "done" if payload.get("ok") else "error", "data": payload})',1)
s=s.replace('        except Exception:\n            events.put({"event": "error",', '        except ChatCancelled:\n            events.put({"event": "error", "data": {"ok": False, "cancelled": True, "error": "停止しました。"}})\n        except Exception:\n            events.put({"event": "error",',1)
s=s.replace('            del _ACTIVITY.callback','            del _ACTIVITY.callback\n            del _ACTIVITY.cancelled\n            with _CHAT_CANCEL_LOCK:\n                _CHAT_CANCEL.pop(key, None)',1)
s=s.replace('def _append_turn(session_id: str, role: str, content: str) -> None:\n', 'def _append_turn(session_id: str, role: str, content: str) -> None:\n    _check_chat_cancelled()\n')
s=s.replace('  reply_style: str = "standard",\n) -> dict[str, Any]:\n  reply_style = normalize_style(reply_style)', '  reply_style: str = "standard",\n  regenerate: bool = False,\n) -> dict[str, Any]:\n  _check_chat_cancelled()\n  reply_style = normalize_style(reply_style)',1)
s=s.replace('  cacheable_request = _is_cacheable_message(effective_message)', '  cacheable_request = not regenerate and _is_cacheable_message(effective_message)',1)
s=s.replace('    response_text = (response or "").strip() if ok else (error or "").strip()', '    _check_chat_cancelled()\n    response_text = (response or "").strip() if ok else (error or "").strip()',1)
s=s.replace('    if path not in {"/chat",', '''    if path == '/chat/cancel':
      data = self._read_json()
      stopped = _cancel_chat(str(data.get('session_id', '')), str(data.get('request_token', '')))
      self._send_json({'ok': True, 'cancellation_requested': stopped})
      return

    if path not in {"/chat",''',1)
s=s.replace('tool_request=tool_request, turbo_mode=turbo_mode, reply_style=reply_style):', "tool_request=tool_request, turbo_mode=turbo_mode, reply_style=reply_style,\n                                         regenerate=bool(data.get('regenerate')), request_token=str(data.get('request_token', ''))[:128]):",1)
# UI controls. Keep changes to the existing central send path.
s=s.replace('<button id="send-btn" type="button">送信</button>', '<button id="send-btn" type="button">送信</button><button id="chat-stop" type="button" hidden>停止</button>',1)
s=s.replace("    let queuedMessage = '';", "    let queuedMessage = '';\n    const chatStop = document.getElementById('chat-stop');\n    chatStop.addEventListener('click', () => { queuedMessage = ''; window.chatTransport?.stop(); });\n    function chatAction(bubble, label, action) {\n      const button = document.createElement('button');button.type = 'button';button.className = 'chat-action';button.dataset.chatAction = 'true';button.textContent = label;button.disabled = isSending;button.addEventListener('click', () => { if (!isSending && !window.workbench?.busy()) action(); });\n      bubble.append(button);return button;\n    }\n    function setChatBusy(value) {\n      chatStop.hidden = !value;\n      document.querySelectorAll('[data-chat-action]').forEach(button => button.disabled = value);\n    }",1)
s=s.replace('    async function sendMessage() {\n      const text = messageInput.value.trim();\n      const sessionId = sessionInput.value.trim() || savedSessionId;\n      const currentLocation = locationInput.value.trim() || savedCurrentLocation;', "    async function sendMessage(options = {}) {\n      const text = String(options.message ?? messageInput.value).trim();\n      const sessionId = options.session_id || sessionInput.value.trim() || savedSessionId;\n      const currentLocation = options.current_location ?? (locationInput.value.trim() || savedCurrentLocation);\n      if (options.session_id && options.session_id !== sessionInput.value.trim()) return;",1)
s=s.replace('      isSending = true;\n      sendBtn.disabled = true;', '      isSending = true;\n      setChatBusy(true);\n      sendBtn.disabled = true;',1)
s=s.replace("      const turboMode = !!(turboModeInput && turboModeInput.checked);", "      const turboMode = options.turbo_mode ?? !!(turboModeInput && turboModeInput.checked);\n      const request = {message: text, session_id: sessionId, current_location: currentLocation, turbo_mode: turboMode, regenerate: !!options.regenerate};",1)
s=s.replace("      addBubble('user', text);\n      messageInput.value = '';", "      if (!options.reuseQuestion) {\n        const question = addBubble('user', text);\n        chatAction(question, '編集して再送信', () => { messageInput.value = text;messageInput.focus();messageInput.setSelectionRange(messageInput.value.length,messageInput.value.length); });\n      }\n      if (!options.reuseQuestion) messageInput.value = '';",1)
s=s.replace("await window.dashboardRequest({ message: text, session_id: sessionId, current_location: currentLocation, turbo_mode: turboMode });", 'await window.dashboardRequest(request);',1)
s=s.replace("          addBubble('assistant', data.response);", "          const answer = addBubble('assistant', data.response);\n          chatAction(answer, '再生成', () => sendMessage({...request, regenerate: true, reuseQuestion: true}));",1)
s=s.replace("        const detail = e && e.message ? ` (${e.message})` : '';\n        addBubble('assistant', `通信に失敗しました。${detail}`);\n        appendRuntimeLog(`network error${detail}`);", "        if (e.name === 'ChatStopped') {\n          window.aiCore.setState('idle');\n          addBubble('system', '回答の受信を停止しました。開始済みの外部処理は直ちに止まらない場合があります。');\n        } else {\n          const detail = e && e.message ? ` (${e.message})` : '';\n          const failure = addBubble('assistant', `通信に失敗しました。${detail}`);\n          chatAction(failure, '再試行', () => sendMessage({...request, reuseQuestion: true}));\n          appendRuntimeLog(`network error${detail}`);\n        }",1)
s=s.replace("        isSending = false;\n        runtimeProcessing.textContent", "        isSending = false;\n        setChatBusy(false);\n        runtimeProcessing.textContent",1)
p.write_text(s,encoding='utf-8')
p=root/'site/dashboard/dashboard.js';s=p.read_text(encoding='utf-8')
s=s.replace('    const controller = new AbortController();', "    const controller = new AbortController();\n    const requestToken = crypto.randomUUID();\n    payload.request_token = requestToken;\n    let userStopped = false;\n    const transport = {stop() {\n      if (controller.signal.aborted) return;\n      userStopped = true;controller.abort();\n      fetch('/chat/cancel', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({session_id:payload.session_id,request_token:requestToken})}).catch(()=>{});\n    }};\n    window.chatTransport = transport;",1)
s=s.replace("} catch (error) { window.workbench?.fail(); if (error.name === 'AbortError')", "} catch (error) { window.workbench?.fail(); if (userStopped) {const stopped = new Error('停止しました');stopped.name = 'ChatStopped';throw stopped;} if (error.name === 'AbortError')",1)
s=s.replace('finally { clearTimeout(timer); sessionControls.forEach', 'finally { if(window.chatTransport===transport)window.chatTransport=null;clearTimeout(timer); sessionControls.forEach',1)
p.write_text(s,encoding='utf-8')
p=root/'site/dashboard/dashboard.css';s=p.read_text(encoding='utf-8');s+='''
/* 移行chat担当: per-message actions and explicit stop. */
.chat-action{display:inline-block;margin:9px 6px 0 0;padding:5px 9px;font-size:11px;border:1px solid #477b91;background:#133242;color:#c5e8f0;border-radius:6px;cursor:pointer;}
.chat-action:disabled{opacity:.45;cursor:default;}
#chat-stop{background:#673038;border-color:#be6a70;color:#fff;}
#chat-stop[hidden]{display:none!important;}
''';p.write_text(s,encoding='utf-8')

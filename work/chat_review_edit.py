from pathlib import Path
p=Path('local_ai_server.py');s=p.read_text(encoding='utf-8').replace('// 移行chat担当:', '// 中央chat担当:')
s=s.replace("    let queuedMessage = '';\n",'',1).replace("chatStop.addEventListener('click', () => { queuedMessage = ''; window.chatTransport?.stop(); });", "chatStop.addEventListener('click', () => window.chatTransport?.stop());",1)
s=s.replace("      if (isSending) {\n        queuedMessage = text;\n        messageInput.value = text;\n        return;\n      }", "      if (isSending) return;",1)
start=s.index('        if (queuedMessage) {');end=s.index('        sendBtn.disabled = false;',start);s=s[:start]+s[end:]
s=s.replace("      followChatLatest(role === 'user');", "      followChatLatest();",1)
anchor="    const messageInput = document.getElementById('message');"
monitor='''    // Character updates include incremental/streaming answer text. One layout per frame.
    let chatScrollFrame = null;
    const chatContentObserver = new MutationObserver(() => {
      if (chatScrollFrame !== null) return;
      chatScrollFrame = requestAnimationFrame(() => {
        chatScrollFrame = null;
        followChatLatest();
      });
    });
    chatContentObserver.observe(chatLog, {childList:true, characterData:true, subtree:true});

'''
s=s.replace(anchor,monitor+anchor,1)
anchor='    function addBubble(role, text) {'
formatter='''    function renderChatContent(body, rawText) {
      const pattern = /```[^\\n`]*\\n([\\s\\S]*?)```/g;
      let offset = 0, match;
      const prose = text => {
        const span = document.createElement('span');
        span.innerHTML = linkifyText(text).split(String.fromCharCode(10)).join('<br>');
        body.append(span);
      };
      while ((match = pattern.exec(rawText)) !== null) {
        prose(rawText.slice(offset, match.index));
        const pre = document.createElement('pre');
        const code = document.createElement('code');
        code.textContent = match[1];pre.append(code);body.append(pre);
        offset = pattern.lastIndex;
      }
      prose(rawText.slice(offset));
    }

'''
s=s.replace(anchor,formatter+anchor,1)
s=s.replace("      body.innerHTML = linkifyText(rawText).split(String.fromCharCode(10)).join('<br>');", "      renderChatContent(body, rawText);",1)
p.write_text(s,encoding='utf-8')
p=Path('site/dashboard/dashboard.css');s=p.read_text(encoding='utf-8').replace('移行chat担当','中央chat担当');s+='''
/* 中央chat担当: contain long answers/code without widening the chat column. */
.chat-body #chat-log{overflow-anchor:none;}
#chat-log .bubble{min-width:0;}
#chat-log .bubble-content{min-width:0;max-width:100%;overflow-wrap:anywhere;}
#chat-log .bubble-content pre{max-width:100%;min-width:0;overflow-x:auto;white-space:pre;padding:12px;background:#061521;border:1px solid #345166;border-radius:7px;tab-size:4;}
#chat-log .bubble-content code{font:12px/1.7 Consolas,monospace;overflow-wrap:normal;word-break:normal;}
''';p.write_text(s,encoding='utf-8')
p=Path('site/dashboard/sensory.js');s=p.read_text(encoding='utf-8');old="`文体設定：${styles[event.detail.reply_style]||'標準'} / ${event.detail.route||'経路未記録'}`";new="`${event.detail.ok?'完了':'失敗'} / サーバー ${typeof event.detail.elapsed==='number'?event.detail.elapsed.toFixed(3)+'秒':'未計測'} / ${{local_llm:'ローカルAI',cloud_fallback:'クラウドAI',local_function:'ローカル機能',local_search:'検索'}[event.detail.route]||event.detail.route||'処理元未記録'} / 文体：${styles[event.detail.reply_style]||'標準'}`";assert old in s;s=s.replace(old,new,1);p.write_text(s,encoding='utf-8')
p=Path('tests/test_chat_actions.py');s=p.read_text(encoding='utf-8').replace('移行chat担当','中央chat担当');p.write_text(s,encoding='utf-8')

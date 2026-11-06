from pathlib import Path
p=Path('functions/embedded_browser.py');s=p.read_text(encoding='utf-8')
s=s.replace('from urllib.parse import urlparse', 'from urllib.parse import urlparse, parse_qs')
s=s.replace("                def receive_frame(event):\n                    self.frame = base64.b64decode(event['data'])\n                    self.sequence += 1\n                    cdp.send('Page.screencastFrameAck', {'sessionId':event['sessionId']})", """                last_frame = 0
                def receive_frame(event):
                    nonlocal last_frame
                    now = time.monotonic()
                    # Keep the latest display at <=15fps; always acknowledge Chrome.
                    if now - last_frame >= 1 / 15:
                        last_frame = now
                        self.frame = base64.b64decode(event['data'])
                        self.sequence += 1
                    cdp.send('Page.screencastFrameAck', {'sessionId':event['sessionId']})""")
s=s.replace("'format':'jpeg','quality':78,", "'format':'jpeg','quality':65,")
s=s.replace("'maxWidth':1920,'maxHeight':1080,'everyNthFrame':1", "'maxWidth':1600,'maxHeight':900,'everyNthFrame':2")
a=s.index('                try:\n                    page.goto(\'https://www.youtube.com/\'')
b=s.index('                last_state = 0',a)
s=s[:a]+"                # Start on the empty page: navigate only to what the user requests.\n"+s[b:]
s=s.replace("self.send_header('Access-Control-Allow-Private-Network','true')", "self.send_header('Access-Control-Allow-Private-Network','true')\n        self.send_header('Access-Control-Max-Age','600')")
s=s.replace("        if self.path=='/frame':self.reply(item.frame, mime='image/jpeg') if item.frame else self.reply(b'',204)\n        elif self.path=='/state':", """        parsed = urlparse(self.path)
        if parsed.path == '/frame':
            after = (parse_qs(parsed.query).get('after') or ['-1'])[0]
            if not item.frame or after == str(item.sequence):
                self.reply(b'', 204)
            else:
                self.reply(item.frame, mime='image/jpeg', sequence=item.sequence)
        elif self.path=='/state':""")
s=s.replace("def reply(self, data, status=200, mime='application/json'):", "def reply(self, data, status=200, mime='application/json', sequence=None):")
s=s.replace("        self.send_header('Vary','Origin')", "        self.send_header('Vary','Origin')\n        if sequence is not None:\n            self.send_header('X-Frame-Sequence', str(sequence))\n            self.send_header('Access-Control-Expose-Headers', 'X-Frame-Sequence')")
p.write_text(s,encoding='utf-8')
p=Path('site/dashboard/chat_browser.js');s=p.read_text(encoding='utf-8')
s=s.replace("let token='',starting=false,frameTimer,stateTimer,resizeTimer,active=false,currentBlob='',lastUrl='';", "let token='',startPromise=null,frameTimer,stateTimer,resizeTimer,active=false,currentBlob='',lastUrl='',lastSize='',sequence='-1',frameBusy=false,stateBusy=false,wheelTimer,wheelBusy=false,wheelPending=null;")
s=s.replace("if(!token)await start();", "if(!token)await start();")
a=s.index('  async function start()');b=s.index('  function point(event)',a)
s=s[:a]+"""  async function start(){
   if(token)return;if(startPromise)return startPromise;
   status.textContent='ブラウザを起動しています…';
   startPromise=(async()=>{try{const data=await(await request('/session',{})).json();token=data.token;sequence='-1';lastSize='';await resize();pollFrame();pollState();}catch(error){status.textContent='ブラウザに接続できません。'+error.message;}})();
   try{await startPromise;}finally{startPromise=null;}
  }
  async function resize(){if(!token||!active)return;const r=screen.getBoundingClientRect(),width=Math.round(r.width),height=Math.round(r.height),size=width+'x'+height;if(width>10&&height>10&&size!==lastSize){lastSize=size;await action({action:'resize',width,height});}}
  async function pollFrame(){
   clearTimeout(frameTimer);if(!token||!active||document.hidden||frameBusy)return;frameBusy=true;const session=token;
   try{const response=await request('/frame?after='+encodeURIComponent(sequence));if(response.status===200&&session===token&&active){const next=URL.createObjectURL(await response.blob());await new Promise(resolve=>{const done=()=>{image.onload=image.onerror=null;resolve();};image.onload=image.onerror=done;image.src=next;});if(currentBlob)URL.revokeObjectURL(currentBlob);currentBlob=next;sequence=response.headers.get('X-Frame-Sequence')||'-1';}}catch(error){status.textContent=error.message;}finally{frameBusy=false;}
   if(active&&token&&!document.hidden)frameTimer=setTimeout(pollFrame,80);
  }
  async function pollState(){
   clearTimeout(stateTimer);if(!token||!active||document.hidden||stateBusy)return;stateBusy=true;
   try{const data=await(await request('/state')).json();status.textContent=data.error||data.title||'検索またはURLを入力してください';if(data.url&&data.url!=='about:blank'&&data.url!==lastUrl){lastUrl=data.url;if(document.activeElement!==address)address.value=data.url;}if(data.closed){token='';status.textContent=data.error||'ブラウザは終了しました。';return;}}catch(error){status.textContent=error.message;}finally{stateBusy=false;}
   if(active&&token&&!document.hidden)stateTimer=setTimeout(pollState,1000);
  }
  function visibility(){const opened=!pane.hidden;active=opened;shell.classList.toggle('embedded-browser-open',opened);shell.classList.toggle('browser-wide',opened);workToggle.hidden=!opened;expand.textContent=opened?'左右を表示':'中央を最大化';if(!opened){shell.classList.remove('browser-work-visible');clearTimeout(frameTimer);clearTimeout(stateTimer);wheelPending=null;clearTimeout(wheelTimer);}else if(token){resize();pollFrame();pollState();}else start();}
  new MutationObserver(visibility).observe(pane,{attributes:true,attributeFilter:['hidden']});
  document.addEventListener('visibilitychange',()=>{if(document.hidden){clearTimeout(frameTimer);clearTimeout(stateTimer);}else if(active){pollFrame();pollState();}});
  new ResizeObserver(()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(resize,180);}).observe(screen);
"""+s[b:]
s=s.replace("  screen.addEventListener('wheel',event=>{event.preventDefault();action({action:'wheel',...point(event),dx:event.deltaX,dy:event.deltaY});},{passive:false});", """  async function flushWheel(){if(wheelBusy||!wheelPending||!active)return;const data=wheelPending;wheelPending=null;wheelBusy=true;try{await action(data);}finally{wheelBusy=false;if(wheelPending)wheelTimer=setTimeout(flushWheel,30);}}
  screen.addEventListener('wheel',event=>{event.preventDefault();const unit=event.deltaMode===1?16:event.deltaMode===2?screen.clientHeight:1;const pending=wheelPending;wheelPending={action:'wheel',...point(event),dx:(pending?.dx||0)+event.deltaX*unit,dy:(pending?.dy||0)+event.deltaY*unit};clearTimeout(wheelTimer);wheelTimer=setTimeout(flushWheel,30);},{passive:false});""")
s=s.replace("embedded-browser-v3", "embedded-browser-v4")
p.write_text(s,encoding='utf-8')

(() => {
 'use strict';
 function setup(){
  if(document.getElementById('embedded-browser-screen'))return;
  const pane=document.getElementById('browser-pane'),preview=pane?.querySelector('.browser-preview'),bar=pane?.querySelector('.browser-bar'),address=document.getElementById('browser-search'),shell=document.querySelector('.jarvis-shell');
  if(!pane||!preview||!bar)return;
  const service='http://127.0.0.1:8766';
  let token='',startPromise=null,frameTimer,stateTimer,resizeTimer,active=false,currentBlob='',lastUrl='',lastSize='',sequence='-1',frameBusy=false,stateBusy=false,wheelTimer,wheelBusy=false,wheelPending=null;
  const make=(tag,text)=>{const node=document.createElement(tag);if(text)node.textContent=text;return node;};
  const style=make('style');style.textContent=`
.embedded-browser-open .chat-body{grid-template-rows:56px minmax(0,1fr) auto!important;}
.embedded-browser-open .chat-body>.hud-mission-bar{display:none!important;}
.embedded-browser-open #chat-log{grid-row:1;}.embedded-browser-open #browser-pane{grid-row:2;}.embedded-browser-open .composer{grid-row:3;}
.embedded-browser-open .browser-pane{grid-template-rows:auto minmax(0,1fr) auto auto;gap:4px;padding:5px 7px 0;overflow:hidden;}
.embedded-browser-open .browser-preview{min-height:0;max-height:none;position:relative;border-radius:5px;}
#embedded-browser-screen{height:100%;width:100%;position:relative;overflow:hidden;min-height:0;background:#fff;outline:none;}
#embedded-browser-screen img{display:block;width:100%;height:100%;object-fit:contain;user-select:none;}
.embedded-browser-keys{position:absolute!important;bottom:4px;left:4px;width:2px!important;height:2px!important;min-height:0!important;padding:0!important;opacity:.02;pointer-events:none;}
.embedded-browser-open .browser-history{display:none!important;}
.embedded-browser-open .browser-bar{gap:4px;flex-wrap:wrap;}
.embedded-browser-open .browser-bar button{padding:5px 7px;font-size:10px;min-height:25px;}
.embedded-browser-open .browser-bar input{padding:6px 8px;}
.embedded-textbar{display:flex;gap:5px;min-width:0;}.embedded-textbar input{flex:1;min-width:0;font-size:11px;padding:5px;}.embedded-textbar button{width:auto;padding:5px;font-size:10px;}
.embedded-browser-open .work-description-wrap{display:none!important;}.embedded-browser-open.browser-work-visible .work-description-wrap{display:grid!important;}
.embedded-browser-open .composer{padding:5px 9px;gap:4px;}.embedded-browser-open .composer>label{display:none;}
.embedded-browser-open #message{height:42px!important;min-height:38px!important;max-height:80px;}.embedded-browser-open .chat-body #chat-log{padding:5px 12px;}
.embedded-browser-open .chat-actions-row{gap:5px;margin:0;}.embedded-browser-open .chat-actions-row button{font-size:10px;padding:4px 7px;}
@media(min-width:901px){.browser-wide .first-screen{grid-template-columns:84px minmax(0,1fr) 84px!important;gap:6px;}.browser-wide .hud-left,.browser-wide .hud-right{min-width:0!important;overflow-x:hidden;opacity:.75;}.browser-wide .hud-left .panel-header,.browser-wide .hud-right .panel-header,.browser-wide .hud-left .panel-body,.browser-wide .hud-right .panel-body{padding:5px;}.browser-wide #dx-manager{display:none!important;}}
@media(max-width:900px){.embedded-browser-open .first-screen{grid-template-columns:minmax(0,1fr)!important;}.embedded-browser-open .hud-left,.embedded-browser-open .hud-right{display:none!important;}.embedded-browser-open .browser-bar input{flex-basis:100%;}}
`;document.head.append(style);
  const status=make('div','この場所でWebサイトを操作できます。');status.className='chat-browser-status';status.setAttribute('role','status');
  const screen=make('div');screen.id='embedded-browser-screen';screen.tabIndex=0;screen.setAttribute('role','application');screen.setAttribute('aria-label','操作できるWebブラウザ');
  const image=make('img');image.alt='Webブラウザの画面';image.draggable=false;screen.append(image);
  const keys=make('textarea');keys.className='embedded-browser-keys';keys.setAttribute('aria-label','Webページへのキーボード入力');keys.autocomplete='off';screen.append(keys);
  preview.replaceChildren(screen);pane.append(status);
  const textbar=make('div');textbar.className='embedded-textbar';
  const text=make('input');text.placeholder='ページ内に文字を入力（日本語対応）';text.setAttribute('aria-label','ページ内へ入力する文字');textbar.append(text);pane.append(textbar);
  const textsend=make('button','文字を入力');textsend.type='button';textbar.append(textsend);
  async function request(path,data){
   const response=await fetch(service+path,{method:data===undefined?'GET':'POST',headers:{'X-Sotuken-Browser':'1',...(token?{Authorization:'Bearer '+token}:{}),...(data!==undefined?{'Content-Type':'application/json'}:{})},body:data===undefined?undefined:JSON.stringify(data)});
   if(!response.ok){let message;try{message=(await response.json()).error;}catch{}throw Error(message||'ブラウザとの接続に失敗しました');}return response;
  }
  async function action(data){try{if(!token)await start();if(!token)return;const result=await(await request('/action',data)).json();if(!result.ok)throw Error(result.error);return result;}catch(error){status.textContent=error.message;}}
  function url(value){value=value.trim();if(!value)return 'https://www.youtube.com/';try{const parsed=new URL(/^[\w.-]+\.[a-z]{2,}(\/|$)/i.test(value)?'https://'+value:value);if(['http:','https:'].includes(parsed.protocol))return parsed.href;}catch{}return 'https://www.google.com/search?q='+encodeURIComponent(value);}
  async function navigate(){status.textContent='ページを読み込んでいます…';await action({action:'navigate',url:url(address.value)});}
  window.openSotukenBrowser=navigate;window.openBrowserSearch=navigate;
  function button(label,fn){const b=make('button',label);b.type='button';b.addEventListener('click',fn);bar.append(b);return b;}
  button('戻る',()=>action({action:'back'}));button('進む',()=>action({action:'forward'}));button('再読み込み',()=>action({action:'reload'}));button('YouTube',()=>action({action:'navigate',url:'https://www.youtube.com/'}));
  const expand=button('左右を表示',()=>{shell.classList.toggle('browser-wide');expand.textContent=shell.classList.contains('browser-wide')?'左右を表示':'中央を最大化';resize();});
  button('ブラウザを終了',async()=>{if(token)await action({action:'close'});token='';document.getElementById('browser-close-btn').click();});
  const workToggle=make('button','作業説明を表示');workToggle.type='button';workToggle.id='browser-work-toggle';workToggle.hidden=true;document.querySelector('.chat-actions-row').append(workToggle);
  workToggle.addEventListener('click',()=>{shell.classList.toggle('browser-work-visible');workToggle.textContent=shell.classList.contains('browser-work-visible')?'作業説明を格納':'作業説明を表示';resize();});
  document.getElementById('chat-browser-launch')?.remove();
  async function start(){
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
  function point(event){const r=image.getBoundingClientRect(),w=image.naturalWidth||1280,h=image.naturalHeight||720,s=Math.min(r.width/w,r.height/h);return{x:Math.max(0,(event.clientX-r.left-(r.width-w*s)/2)/s),y:Math.max(0,(event.clientY-r.top-(r.height-h*s)/2)/s)};}
  screen.addEventListener('click',event=>{if(event.target===keys)return;action({action:'click',...point(event)});keys.focus({preventScroll:true});});
  async function flushWheel(){if(wheelBusy||!wheelPending||!active)return;const data=wheelPending;wheelPending=null;wheelBusy=true;try{await action(data);}finally{wheelBusy=false;if(wheelPending)wheelTimer=setTimeout(flushWheel,30);}}
  screen.addEventListener('wheel',event=>{event.preventDefault();const unit=event.deltaMode===1?16:event.deltaMode===2?screen.clientHeight:1;const pending=wheelPending;wheelPending={action:'wheel',...point(event),dx:(pending?.dx||0)+event.deltaX*unit,dy:(pending?.dy||0)+event.deltaY*unit};clearTimeout(wheelTimer);wheelTimer=setTimeout(flushWheel,30);},{passive:false});
  let composing=false;keys.addEventListener('compositionstart',()=>{composing=true;});keys.addEventListener('compositionend',event=>{composing=false;if(event.data)action({action:'text',text:event.data});keys.value='';});
  keys.addEventListener('beforeinput',event=>{if(composing||event.isComposing||event.inputType.includes('Composition'))return;if(event.inputType==='insertText'&&event.data){event.preventDefault();action({action:'text',text:event.data});}});
  keys.addEventListener('paste',event=>{event.preventDefault();action({action:'text',text:event.clipboardData.getData('text/plain')});});
  keys.addEventListener('keydown',event=>{if(composing||event.isComposing)return;const special={Enter:'Enter',Backspace:'Backspace',Delete:'Delete',Tab:'Tab',Escape:'Escape',ArrowUp:'ArrowUp',ArrowDown:'ArrowDown',ArrowLeft:'ArrowLeft',ArrowRight:'ArrowRight',Home:'Home',End:'End',PageUp:'PageUp',PageDown:'PageDown',' ':'Space'};if(event.ctrlKey||event.metaKey){if(['c','v','x'].includes(event.key.toLowerCase()))return;event.preventDefault();action({action:'key',key:'Control+'+event.key});}else if(special[event.key]){event.preventDefault();action({action:'key',key:(event.shiftKey?'Shift+':'')+special[event.key]});}});
  textsend.addEventListener('click',async()=>{if(text.value){await action({action:'text',text:text.value});text.value='';}});
  text.addEventListener('keydown',async event=>{if(event.key==='Enter'&&!event.isComposing){event.preventDefault();if(text.value){await action({action:'text',text:text.value});text.value='';}await action({action:'key',key:'Enter'});}});
  document.documentElement.dataset.browserFix='embedded-browser-v4';visibility();
  window.addEventListener('pagehide',()=>{if(token)fetch(service+'/action',{method:'POST',headers:{'X-Sotuken-Browser':'1',Authorization:'Bearer '+token,'Content-Type':'application/json'},body:JSON.stringify({action:'close'}),keepalive:true}).catch(()=>{});});
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',setup,{once:true});else setup();
})();

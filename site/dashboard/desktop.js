/* PC時計・表示モード・通知。通知内容をlocalStorageや会話ログへ保存しない。 */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const create = (tag,text,className) => {const el=document.createElement(tag);if(text!=null)el.textContent=text;if(className)el.className=className;return el;};
  let clockSample=null, clockSyncTimer=null, clockTickTimer=null;
  let settings={enabled:false,duration_sec:5,important_apps:[],bridge_state:'not_connected'};
  let mode='INFO',cursor=0,pollTimer=null,polling=false,disposed=false,activeNotification=null,queue=[];
  let dismissTimer=null,fadeTimer=null,visibleAfter=0,settingsRevision=0,previewFrame=null;
  let resizeObserver=null;
  const headers={'Content-Type':'application/json','X-Jarvis-Notifications':'1'};
  const bridgeLabels={not_connected:'補助アプリ未接続',allowed:'Windows許可済み',denied:'Windowsの通知アクセスが拒否されています',unspecified:'Windowsの通知アクセス許可が必要です',identity_required:'補助アプリの登録が必要です',error:'Windows通知APIの確認が必要です'};
  const weekdays=['SUN','MON','TUE','WED','THU','FRI','SAT'];
  const pad=value=>String(value).padStart(2,'0');
  function clockNow() {return clockSample?clockSample.epoch_ms+(performance.now()-clockSample.at):null;}
  function localParts(epoch) {
    const date=new Date(epoch+(clockSample?.utc_offset_minutes||0)*60000);
    return {date:`${date.getUTCFullYear()}.${pad(date.getUTCMonth()+1)}.${pad(date.getUTCDate())} ${weekdays[date.getUTCDay()]}`,
            time:`${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}:${pad(date.getUTCSeconds())}`,second:date.getUTCSeconds()};
  }
  function renderClock() {
    if (!$('header-clock')) return;
    const epoch=clockNow();
    if(epoch==null)return;
    const value=localParts(epoch);
    $('clock-time').textContent=value.time; $('clock-date').textContent=value.date;
    $('clock-time').dateTime=new Date(epoch).toISOString();
    const offset=clockSample.utc_offset_minutes;
    $('clock-zone').textContent=`PC / ${clockSample.timezone} · UTC${offset>=0?'+':'−'}${pad(Math.floor(Math.abs(offset)/60))}:${pad(Math.abs(offset)%60)}`;
    $('clock-second-ring').style.strokeDashoffset=String(150.8*(1-value.second/60));
    $('header-clock').style.setProperty('--second-angle',`${value.second*6}deg`);
    $('clock-seconds-value').textContent=pad(value.second);
    const stale=performance.now()-clockSample.at>45000;
    $('header-clock').classList.toggle('clock-stale',stale);
    $('clock-sync-status').textContent=stale?'同期停止':'PC SYNC';
  }
  function tick() {
    renderClock();
    clearTimeout(clockTickTimer);
    if(disposed||document.hidden)return;
    const now=clockNow(); clockTickTimer=setTimeout(tick,now==null?1000:Math.max(40,1000-now%1000));
  }
  async function syncClock() {
    const started=performance.now();
    try {
      const response=await fetch('/system/clock',{cache:'no-store',signal:AbortSignal.timeout(4000)});
      const data=await response.json();
      const ended=performance.now();
      if(disposed)return;
      if(!response.ok||!data.ok||!Number.isFinite(data.epoch_ms)||!Number.isFinite(data.utc_offset_minutes))throw new Error();
      clockSample={...data,epoch_ms:data.epoch_ms+(ended-started)/2,at:ended};
      tick();
    } catch {
      if(disposed)return;
      $('clock-sync-status').textContent='同期停止';
      $('header-clock').classList.add('clock-stale');
    } finally {
      clearTimeout(clockSyncTimer);
      if(!disposed)clockSyncTimer=setTimeout(syncClock,document.hidden?30000:15000);
    }
  }
  function installClock() {
    const header=document.querySelector('.dashboard-header');
    const clock=create('section',null,'header-clock');clock.id='header-clock';clock.setAttribute('aria-label','バックエンドPCの日時');
    clock.innerHTML='<div class="clock-orbit" aria-hidden="true"><svg viewBox="0 0 56 56"><circle class="clock-ring-track" cx="28" cy="28" r="24"/><circle id="clock-second-ring" cx="28" cy="28" r="24" pathLength="150.8"/></svg><span id="clock-seconds-value">--</span><i class="clock-orbit-dot"></i></div><div class="header-clock-values"><div id="header-date-slot"></div><div id="header-time-slot"></div><div id="clock-zone">PCの時計に接続中</div></div><span id="clock-sync-status">SYNC…</span>';
    header.insertBefore(clock,document.querySelector('.dashboard-nav'));
    const time=$('clock-time'),date=$('clock-date');
    // 既存IDを引き継ぎ、他の画面更新との互換性を維持する。
    const timeElement=create('time');timeElement.id='clock-time';timeElement.className='clock-time';timeElement.textContent='--:--:--';time.replaceWith(timeElement);
    $('header-time-slot').append(timeElement);$('header-date-slot').append(date);
    document.querySelector('.clock-panel')?.remove();
    syncClock();
  }
  function alignPopup() {
    const root=$('notification-overlay'),side=document.querySelector('.hud-right');if(!root||!side)return;
    const rect=side.getBoundingClientRect(),controls=$('right-mode-controls').getBoundingClientRect();
    root.style.left=`${rect.left+4}px`;root.style.top=`${Math.max(rect.top,controls.bottom)+8}px`;root.style.width=`${Math.max(0,rect.width-8)}px`;
  }
  function clearNotifications() {
    clearTimeout(dismissTimer);clearTimeout(fadeTimer);queue=[];activeNotification=null;
    $('notification-overlay')?.replaceChildren();
  }
  function setMode(value,{persist=true,openSearch=true}={}) {
    value=String(value||'').toUpperCase();if(!['CHAT','SEARCH','INFO'].includes(value))return;
    mode=value;const side=document.querySelector('.hud-right');side.dataset.mode=mode;
    document.querySelectorAll('[data-right-mode]').forEach(button=>{const current=button.dataset.rightMode===mode;button.setAttribute('aria-pressed',String(current));});
    $('right-chat-preview').hidden=mode!=='CHAT';
    $('info-panel-dock').inert=mode==='CHAT';
    clearNotifications();visibleAfter=(clockNow()??Date.now())/1000;
    if(persist)try{localStorage.setItem('jarvis-right-mode-v1',mode);}catch{}
    if(mode==='SEARCH'&&openSearch)window.dashboardPanels.open('search',{source:'manual'});
    updateChatPreview();alignPopup();
    window.dispatchEvent(new CustomEvent('jarvis:right-mode-change',{detail:{mode}}));
    pollNotifications();
  }
  function updateChatPreview() {
    if(mode!=='CHAT')return;
    if(previewFrame) return;
    previewFrame=requestAnimationFrame(() => {
      previewFrame=null;
      const box=$('right-chat-messages');
      if(!box)return;
      box.replaceChildren();
      [...$('chat-log').querySelectorAll('.bubble.user,.bubble.assistant')].slice(-12).forEach(bubble=>{
        const content=bubble.querySelector('.bubble-content')||bubble;
        const item=create('div',null,'right-chat-message');
        item.append(create('small',bubble.classList.contains('user')?'YOU':'AI'),create('p',(content.innerText||content.textContent).trim()));
        box.append(item);
      });
      if(!box.children.length)box.append(create('p','会話はまだありません。入力は中央のチャットから行えます。','measurement-note'));
      box.scrollTop=box.scrollHeight;
    });
  }
  function installModes() {
    const side=document.querySelector('.hud-right');
    const controls=create('div',null,'right-mode-controls');controls.id='right-mode-controls';controls.setAttribute('role','group');controls.setAttribute('aria-label','右側の表示モード');
    for(const label of ['CHAT','SEARCH','INFO']){const button=create('button',label);button.type='button';button.dataset.rightMode=label;button.setAttribute('aria-pressed','false');button.addEventListener('click',()=>setMode(label));controls.append(button);}
    side.prepend(controls);
    const preview=create('section',null,'panel right-chat-preview');preview.id='right-chat-preview';preview.hidden=true;preview.innerHTML='<div class="panel-header"><strong>CHAT / 会話の確認</strong></div><div id="right-chat-messages" class="panel-body"></div><p class="measurement-note">入力は中央のチャットから。CHATモード中の通知は表示しません。</p>';controls.after(preview);
    const observer=new MutationObserver(updateChatPreview);observer.observe($('chat-log'),{childList:true,subtree:true,characterData:true});
    // パネルの開閉と整合させる。CHAT中の自動結果は裏側で更新する。
    const open=window.dashboardPanels.open;
    window.dashboardPanels.open=(kind,options={})=>{
      const result=open(kind,options);
      const panel=document.querySelector(`[data-info-panel="${kind}"]`);
      if(panel?.parentElement===$('info-panel-dock')&&(options.source!=='auto'||mode!=='CHAT')){
        const next=kind==='search'?'SEARCH':'INFO';
        if(mode!==next)setMode(next,{openSearch:false});
      }
      return result;
    };
    document.querySelectorAll('[data-open-panel]').forEach(button=>button.addEventListener('click',()=>{
      const kind=button.dataset.openPanel;const panel=document.querySelector(`[data-info-panel="${kind}"]`);
      if(panel&&!panel.hidden&&panel.parentElement===$('info-panel-dock'))setMode(kind==='search'?'SEARCH':'INFO');
    }));
    $('close-all-panels').addEventListener('click',()=>setMode('INFO'));
    let saved='INFO';try{saved=localStorage.getItem('jarvis-right-mode-v1')||'INFO';}catch{}
    setMode(saved);
    const root=create('div');root.id='notification-overlay';root.setAttribute('aria-live','polite');root.setAttribute('aria-atomic','true');document.body.append(root);
    resizeObserver=new ResizeObserver(alignPopup);resizeObserver.observe(side);resizeObserver.observe(document.querySelector('.dashboard-header'));
    side.addEventListener('scroll',alignPopup,{passive:true});window.addEventListener('resize',alignPopup);alignPopup();
  }
  function closePopup(immediate=false) {
    clearTimeout(dismissTimer);clearTimeout(fadeTimer);
    if(!activeNotification)return;
    const popup=$('notification-overlay').firstElementChild;
    if(immediate||!popup){activeNotification=null;$('notification-overlay').replaceChildren();showNext();return;}
    popup.classList.add('leaving');
    fadeTimer=setTimeout(()=>{activeNotification=null;$('notification-overlay').replaceChildren();showNext();},220);
  }
  function showNext() {
    if(activeNotification||!settings.enabled||mode==='CHAT'||document.hidden)return;
    while(queue.length&&(clockNow()??Date.now())/1000-queue[0].received_at>60)queue.shift();
    const item=queue.shift();if(!item)return;
    activeNotification=item;const popup=create('article',null,'notification-toast');popup.dataset.priority=item.priority==='important'?'important':'normal';popup.setAttribute('role','status');
    const head=create('div',null,'notification-head');
    if(item.icon&&/^data:image\/(png|jpeg);base64,[A-Za-z0-9+/=]+$/.test(item.icon)){const image=create('img');image.src=item.icon;image.alt='';head.append(image);}
    head.append(create('strong',item.app||'通知'));
    const stamp=typeof item.created_at==='number'?item.created_at:item.received_at;
    head.append(create('time',clockSample?localParts(stamp*1000).time:'受信'));
    const exit=create('button','×','notification-close');exit.type='button';exit.setAttribute('aria-label','通知を閉じる');exit.addEventListener('click',()=>closePopup());head.append(exit);
    popup.append(head,create('h3',item.title||'新しい通知'),create('p',item.body||'','notification-body'),create('div',null,'notification-lifetime'));
    popup.style.setProperty('--notification-duration',`${settings.duration_sec}s`);$('notification-overlay').replaceChildren(popup);alignPopup();
    dismissTimer=setTimeout(()=>closePopup(),settings.duration_sec*1000);
  }
  function acceptEvents(data) {
    if(Number.isFinite(data.cursor))cursor=data.cursor;
    if(!settings.enabled||mode==='CHAT'||document.hidden){clearNotifications();return;}
    for(const item of data.notifications||[]){
      if(!item||typeof item.received_at!=='number'||item.received_at<visibleAfter)continue;
      if(queue.length<30)queue.push(item);
    }
    showNext();
  }
  async function pollNotifications() {
    clearTimeout(pollTimer);if(disposed||polling||!settings.enabled)return;
    polling=true;
    const revision=settingsRevision;
    try{
      const response=await fetch(`/notifications/events?cursor=${cursor}&mode=${document.hidden?'CHAT':mode}`,{cache:'no-store',signal:AbortSignal.timeout(4000)});
      if(!response.ok)throw new Error();const data=await response.json();
      if(disposed||revision!==settingsRevision)return;
      if(data.enabled===false){settings.enabled=false;$('notifications-enabled').checked=false;clearNotifications();return;}
      if(data.bridge_state){settings.bridge_state=data.bridge_state;$('notifications-status').textContent=statusLabel();}
      acceptEvents(data);
    }catch{if(!disposed&&revision===settingsRevision)$('notifications-status').textContent='通知の接続を確認しています。';}
    finally{polling=false;if(!disposed&&settings.enabled)pollTimer=setTimeout(pollNotifications,1000);}
  }
  function statusLabel() {return `${settings.enabled?'通知表示 ON':'通知表示 OFF'} / ${bridgeLabels[settings.bridge_state]||'未接続'}`;}
  function applySettings(data) {
    settings={...settings,...data};$('notifications-enabled').disabled=false;$('notifications-enabled').checked=!!settings.enabled;$('notifications-duration').value=settings.duration_sec;
    $('notifications-important-apps').value=(settings.important_apps||[]).join('\n');$('notifications-status').textContent=statusLabel();
    if(!settings.enabled){clearNotifications();clearTimeout(pollTimer);}else pollNotifications();
  }
  async function saveSettings() {
    const revision=++settingsRevision;
    const enabled=$('notifications-enabled').checked;
    if(!enabled){settings.enabled=false;clearNotifications();clearTimeout(pollTimer);}
    try{
      const response=await fetch('/notifications/settings',{method:'POST',headers,body:JSON.stringify({enabled,duration_sec:Number($('notifications-duration').value),important_apps:$('notifications-important-apps').value.split('\n').map(value=>value.trim()).filter(Boolean)})});
      const data=await response.json();if(!response.ok||!data.ok)throw new Error(data.error||'設定を保存できませんでした。');
      if(revision!==settingsRevision)return;
      cursor=data.cursor;visibleAfter=(clockNow()??Date.now())/1000;applySettings(data);
    }catch(error){if(revision===settingsRevision)$('notifications-status').textContent=error.message;}
  }
  async function refreshSettings() {
    const revision=settingsRevision;
    try{const response=await fetch('/notifications/settings',{cache:'no-store',signal:AbortSignal.timeout(5000)});const data=await response.json();if(!response.ok||!data.ok)throw new Error(data.error||'通知設定を取得できませんでした。');if(revision!==settingsRevision)return;cursor=data.cursor;applySettings(data);}
    catch(error){if(revision!==settingsRevision||disposed)return;$('notifications-status').textContent=error.message;$('notifications-enabled').disabled=true;}
  }
  function installSettings() {
    const settingsPanel=create('section',null,'panel desktop-settings');settingsPanel.innerHTML='<div class="panel-header"><strong>SETTINGS / 端末通知</strong></div><div class="panel-body tool-form"><label class="notification-toggle"><input type="checkbox" id="notifications-enabled" /> Windows通知をUIに表示する</label><label>表示秒数（2〜15秒）<input type="number" min="2" max="15" value="5" id="notifications-duration" /></label><label>重要扱いにするアプリ名（1行に1件）<textarea id="notifications-important-apps" rows="2" placeholder="Windowsに表示されるアプリ名"></textarea></label><button type="button" id="notifications-save">通知設定を適用</button><button type="button" id="notifications-connect">Windows通知アクセスを設定</button><div id="notifications-status" role="status">通知設定を確認中…</div><p class="measurement-note">初期状態はOFF。取得対象はこのPCのWindows通知センターにあるアプリ通知です。CHAT中・非表示タブではポップアップを出しません。本文はファイルへ保存せず、AIへ送りません。重要度は指定したアプリ名で区別します。</p><p id="notifications-setup-guide" class="measurement-note"></p></div>';
    $('workspace-drawer').append(settingsPanel);
    $('open-workspace').textContent='SETTINGS';
    $('notifications-enabled').addEventListener('change',saveSettings);$('notifications-save').addEventListener('click',saveSettings);
    $('notifications-connect').addEventListener('click',async()=>{
      try{const response=await fetch('/notifications/connect',{method:'POST',headers,body:'{}'});const data=await response.json();$('notifications-setup-guide').textContent=data.message||data.error||'接続を確認してください。';}
      catch{$('notifications-setup-guide').textContent='補助アプリを開けませんでした。サーバーと登録状態を確認してください。';}
    });
    refreshSettings();
    // 設定画面を開いたときに権限・接続状態だけを再確認する。
    $('open-workspace').addEventListener('click',refreshSettings);
  }
  window.desktopIntegration={renderClock,setMode,getMode:()=>mode};
  window.initDesktopIntegration=()=>{
    installClock();installSettings();installModes();
    document.addEventListener('visibilitychange',()=>{clearNotifications();visibleAfter=(clockNow()??Date.now())/1000;if(!document.hidden){syncClock();pollNotifications();}else clearTimeout(clockTickTimer);});
    window.addEventListener('online',()=>{if(!disposed){syncClock();refreshSettings();}});
    window.addEventListener('pageshow',event=>{
      if(!event.persisted)return;
      disposed=false;resizeObserver?.observe(document.querySelector('.hud-right'));
      resizeObserver?.observe(document.querySelector('.dashboard-header'));
      visibleAfter=Date.now()/1000;syncClock();refreshSettings();alignPopup();
    });
    window.addEventListener('pagehide',()=>{disposed=true;clearNotifications();clearTimeout(clockSyncTimer);clearTimeout(clockTickTimer);clearTimeout(pollTimer);resizeObserver?.disconnect();});
  };
})();

/* Command palette, named layouts, and persistent time tools. Browser-local only. */
(() => {
 'use strict';
 const $=id=>document.getElementById(id),T=window.JarvisTaskState;
 const STATE_KEY='jarvis-time-tools-v1',LAYOUT_KEY='jarvis-layout-presets-v1';
 let state=T.blank(),presets=[],returnFocus=null,restorePaletteFocus=true,selected=0,commands=[],shown=[];
 let originWall=Date.now(),originMono=performance.now(),timerId=null;
 const now=()=>originWall+performance.now()-originMono;
 function uid(){if(globalThis.crypto?.randomUUID)return globalThis.crypto.randomUUID();if(globalThis.crypto?.getRandomValues){const bytes=globalThis.crypto.getRandomValues(new Uint8Array(16));return [...bytes].map(value=>value.toString(16).padStart(2,'0')).join('');}return Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);}
 const make=(tag,text,cls)=>{const el=document.createElement(tag);if(text!=null)el.textContent=text;if(cls)el.className=cls;return el;};
 function setText(id,value){const el=$(id);if(el&&el.textContent!==String(value))el.textContent=String(value);}
 function read(key){try{return JSON.parse(localStorage.getItem(key)||'null');}catch{return null;}}
 function write(key,value){try{localStorage.setItem(key,JSON.stringify(value));return true;}catch{setText('task-storage-status','このブラウザーでは保存できません。画面を閉じるまで利用できます。');return false;}}
 function persist(){write(STATE_KEY,state);}
 function dialog(id,title,html){const el=make('dialog',null,'task-dialog');el.id=id;el.innerHTML=`<div class="task-dialog-head"><strong>${title}</strong><button type="button" data-dialog-close aria-label="閉じる">×</button></div><div class="task-dialog-body">${html}</div>`;el.querySelector('[data-dialog-close]').addEventListener('click',()=>el.close());el.addEventListener('keydown',event=>{if(event.key==='Escape'&&!event.isComposing){event.preventDefault();event.stopPropagation();el.close();}});el.addEventListener('click',event=>{if(event.target===el){const r=el.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)el.close();}});document.body.append(el);return el;}
 function show(id){document.querySelectorAll('.task-dialog[open]').forEach(other=>{if(other.id!==id)other.close();});const modal=$(id);if(!modal.open)modal.showModal();if(id==='task-time-dialog')updateTimes();}
 function focusInput(){const input=$('message');input.focus({preventScroll:true});}
 function timerRows(){
  const box=$('task-timer-list');box.replaceChildren();
  if(!state.timers.length)box.append(make('p','タイマーはまだありません。上で時間を指定するか、クイック追加を選んでください。','task-muted'));
  for(const item of state.timers){const row=make('article',null,'task-timer-row');row.dataset.timerId=item.id;
   const name=make('strong',item.label);const time=make('output');time.setAttribute('aria-live','off');time.dataset.timerValue=item.id;
   const status=make('span',null,'task-timer-state');status.dataset.timerState=item.id;
   const bar=make('progress');bar.max=item.duration;bar.setAttribute('aria-label',item.label+'の経過');bar.dataset.timerProgress=item.id;
   const controls=make('div',null,'task-button-row');
   const toggle=make('button');toggle.type='button';toggle.dataset.timerToggle=item.id;toggle.addEventListener('click',()=>{T.toggleTimer(item,now());persist();updateTimes();});
   const reset=make('button','リセット');reset.type='button';reset.addEventListener('click',()=>{T.resetTimer(item);persist();updateTimes();});
   const remove=make('button','削除','task-subtle');remove.type='button';remove.setAttribute('aria-label',item.label+'を削除');remove.addEventListener('click',()=>{state.timers=state.timers.filter(timer=>timer.id!==item.id);persist();timerRows();});
   controls.append(toggle,reset,remove);row.append(name,time,status,bar,controls);box.append(row);
  }
  updateTimes();
 }
 function alarmRows(){
  const box=$('task-alarm-list');if(!box)return;
  box.replaceChildren();
  if(!Array.isArray(state.alarms)||!state.alarms.length){box.append(make('p','設定したアラームはまだありません。時刻を指定して保存してください。','task-muted'));return;}
  for(const item of state.alarms){
   const row=make('article',null,'task-timer-row');
   const name=make('strong',item.label||'アラーム');
   const time=make('output',item.enabled?`${String(item.hour).padStart(2,'0')}:${String(item.minute).padStart(2,'0')}`:'停止中');
   const status=make('span',item.enabled?'待機中':'停止', 'task-timer-state');
   const controls=make('div',null,'task-button-row');
   const toggle=make('button',item.enabled?'停止':'有効');toggle.type='button';toggle.addEventListener('click',()=>{item.enabled=!item.enabled;item.triggerAt=item.enabled?new Date().setHours(item.hour,item.minute,0,0):0;persist();alarmRows();updateTimes();});
   const remove=make('button','削除','task-subtle');remove.type='button';remove.addEventListener('click',()=>{state.alarms=state.alarms.filter(alarm=>alarm.id!==item.id);persist();alarmRows();});
   controls.append(toggle,remove);row.append(name,time,status,controls);box.append(row);
  }
 }
 function addAlarm(hour,minute,label){
  if(!Array.isArray(state.alarms))state.alarms=[];
  const safeHour=Number(hour); const safeMinute=Number(minute);
  if(!Number.isInteger(safeHour)||!Number.isInteger(safeMinute)||safeHour<0||safeHour>23||safeMinute<0||safeMinute>59){throw new Error('時刻を正しく指定してください。');}
  const item={id:uid(),label:String(label||'アラーム').slice(0,60),hour:safeHour,minute:safeMinute,enabled:true,triggerAt:0};
  const allowTime=new Date();allowTime.setHours(safeHour,safeMinute,0,0);if(allowTime.getTime()<=Date.now())allowTime.setDate(allowTime.getDate()+1);item.triggerAt=allowTime.getTime();state.alarms.push(item);persist();alarmRows();setText('task-timer-message',`${item.label} を ${String(item.hour).padStart(2,'0')}:${String(item.minute).padStart(2,'0')} に設定しました。`);}
 function addTimer(duration,label){try{T.addTimer(state,{id:uid(),duration,label},now());persist();timerRows();setText('task-timer-message',`${label||'タイマー'}を開始しました。`);}catch(error){setText('task-timer-message',error.message);}}
 function watchRows(){const list=$('task-laps');list.replaceChildren();let last=0;state.stopwatch.laps.forEach((lap,index)=>{const row=make('li');row.append(make('span','LAP '+String(index+1).padStart(2,'0')),make('strong',T.format(lap,true)),make('small','＋'+T.format(lap-last,true)));last=lap;list.prepend(row);});updateTimes();}
 function ringAlarm(item){
  if(!item||item.ringing)return;
  item.ringing=true;
  const message=`${item.label || 'アラーム'} の時間です。`;
  setText('task-timer-live',message);
  try{
   const AudioCtor=window.AudioContext||window.webkitAudioContext;
   if(AudioCtor){const audio=new AudioCtor();const osc=audio.createOscillator();const gain=audio.createGain();osc.type='triangle';osc.frequency.value=880;gain.gain.value=0.08;osc.connect(gain);gain.connect(audio.destination);osc.start();osc.stop(audio.currentTime+0.8);setTimeout(()=>audio.close(),900);} 
  }catch(error){}
  setTimeout(()=>{item.ringing=false;item.enabled=false;persist();alarmRows();},1500);
 }
 function updateTimes(){
  const at=now(),finished=T.tick(state,at);
  if(finished.length){persist();setText('task-timer-live',state.timers.filter(item=>finished.includes(item.id)).map(item=>item.label).join('、')+' のタイマーが完了しました。');}
  const alarms=(Array.isArray(state.alarms)?state.alarms:[]).filter(item=>item.enabled===true);
  for(const item of alarms){if(Number(item.triggerAt || 0) <= at){ringAlarm(item);break;}}
  if($('task-time-dialog').open)for(const item of state.timers){const row=[...document.querySelectorAll('[data-timer-id]')].find(el=>el.dataset.timerId===item.id);if(!row)continue;
   const remaining=T.remaining(item,at);const value=T.format(Math.ceil(remaining/1000)*1000);if(row.querySelector('output').textContent!==value)row.querySelector('output').textContent=value;row.querySelector('progress').value=item.duration-remaining;row.querySelector('.task-timer-state').textContent=item.finished?'完了':item.deadline===null?'一時停止':'実行中';row.querySelector('[data-timer-toggle]').textContent=item.deadline!==null?'一時停止':item.finished?'もう一度':'開始';row.classList.toggle('is-finished',item.finished);
  }
  if($('task-time-dialog').open)setText('task-watch-value',T.format(T.elapsed(state,at),true));setText('task-watch-toggle',state.stopwatch.started===null?'計測開始':'一時停止');
  const running=state.timers.filter(item=>item.deadline!==null).sort((a,b)=>a.deadline-b.deadline);const done=state.timers.filter(item=>item.finished).length;
  setText('task-time-open',done?`TIME · 完了 ${done}`:running.length?`TIME ${T.format(Math.ceil(T.remaining(running[0],at)/1000)*1000)}`:state.stopwatch.started!==null?'TIME · 計測中':'TIME');$('task-time-open').classList.toggle('has-finished',done>0);
 }
 function installTime(){
  dialog('task-time-dialog','TIME / タイマー・ストップウォッチ・アラーム','<p class="task-muted">このブラウザーで計測・保存します。ページを閉じている間は通知せず、次に開いたときに期限を確認します。</p><div class="task-timer-form"><label>タイマー名<input id="task-timer-name" maxlength="60" placeholder="作業・休憩など" /></label><label>分<input id="task-timer-minutes" type="number" min="0" max="1440" value="5" /></label><label>秒<input id="task-timer-seconds" type="number" min="0" max="59" value="0" /></label><button type="button" id="task-timer-add">追加して開始</button></div><div class="task-button-row"><button type="button" data-timer-quick="300000">5分休憩</button><button type="button" data-timer-quick="1500000">25分作業</button><button type="button" data-timer-quick="3000000">50分作業</button><button type="button" id="task-clear-finished">完了分を片付ける</button></div><div class="task-timer-form"><label>アラーム名<input id="task-alarm-name" maxlength="60" placeholder="朝の準備" /></label><label>時<input id="task-alarm-hour" type="number" min="0" max="23" value="8" /></label><label>分<input id="task-alarm-minute" type="number" min="0" max="59" value="0" /></label><button type="button" id="task-alarm-add">アラームを設定</button></div><p id="task-timer-message" role="status"></p><div id="task-timer-list"></div><div id="task-alarm-list"></div><section class="task-watch"><h3>STOPWATCH</h3><output id="task-watch-value">00:00:00.0</output><div class="task-button-row"><button type="button" id="task-watch-toggle">計測開始</button><button type="button" id="task-watch-lap">ラップ</button><button type="button" id="task-watch-reset">リセット</button></div><ol id="task-laps"></ol></section><p id="task-storage-status" class="task-muted"></p>');
  const live=make('div');live.id='task-timer-live';live.className='task-sr-only';live.setAttribute('role','status');live.setAttribute('aria-live','polite');document.body.append(live);
  $('task-timer-add').addEventListener('click',()=>{const minutes=Number($('task-timer-minutes').value),seconds=Number($('task-timer-seconds').value);if(!Number.isFinite(minutes)||!Number.isFinite(seconds)||minutes<0||seconds<0||seconds>=60){setText('task-timer-message','分と秒を正しく指定してください。');return;}addTimer((minutes*60+seconds)*1000,$('task-timer-name').value.trim()||'タイマー');});
  $('task-alarm-add').addEventListener('click',()=>{const hour=Number($('task-alarm-hour').value),minute=Number($('task-alarm-minute').value);try{addAlarm(hour,minute,$('task-alarm-name').value.trim()||'アラーム');}catch(error){setText('task-timer-message',error.message);}});
  document.querySelectorAll('[data-timer-quick]').forEach(button=>button.addEventListener('click',()=>addTimer(Number(button.dataset.timerQuick),button.textContent)));
  $('task-clear-finished').addEventListener('click',()=>{state.timers=state.timers.filter(item=>!item.finished);persist();timerRows();});
  $('task-watch-toggle').addEventListener('click',()=>{T.toggleWatch(state,now());persist();updateTimes();});
  $('task-watch-lap').addEventListener('click',()=>{try{T.lap(state,now());persist();watchRows();}catch(error){setText('task-timer-message',error.message);}});
  $('task-watch-reset').addEventListener('click',()=>{state.stopwatch={elapsed:0,started:null,laps:[]};persist();watchRows();});
  $('task-watch-value').setAttribute('aria-live','off');state=T.restore(read(STATE_KEY));if(!Array.isArray(state.alarms))state.alarms=[];timerRows();alarmRows();watchRows();
 }
 function normalizePreset(value){if(!value||typeof value.name!=='string'||!value.layout||typeof value.layout!=='object')return null;return {id:typeof value.id==='string'?value.id.slice(0,80):uid(),name:value.name.slice(0,40),layout:{hud:{mode:value.layout.hud?.mode==='focus'?'focus':'max',hiddenModules:Array.isArray(value.layout.hud?.hiddenModules)?value.layout.hud.hiddenModules.filter(key=>typeof key==='string').slice(0,30):[]},panels:Array.isArray(value.layout.panels)?value.layout.panels.filter(item=>item&&typeof item.key==='string').slice(0,24):[],rightMode:['CHAT','SEARCH','INFO'].includes(value.layout.rightMode)?value.layout.rightMode:'INFO',autoPanels:value.layout.autoPanels!==false}};}
 function captureLayout(){return {hud:window.jarvisHud.capture(),panels:window.dashboardPanels.captureLayout(),rightMode:window.desktopIntegration.getMode(),autoPanels:$('auto-panels').checked};}
 function applyLayout(layout){window.jarvisHud.restore(layout.hud);window.dashboardPanels.restoreLayout(layout.panels);$('auto-panels').checked=layout.autoPanels!==false;$('auto-panels').dispatchEvent(new Event('change'));window.desktopIntegration.setMode(layout.rightMode||'INFO');}
 function layoutRows(){const box=$('task-layout-list');box.replaceChildren();if(!presets.length)box.append(make('p','まだ保存されていません。表示を整えて、名前を付けて保存できます。','task-muted'));for(const preset of presets){const row=make('div',null,'task-layout-row');const name=make('strong',preset.name);const apply=make('button','適用');apply.type='button';apply.addEventListener('click',()=>{applyLayout(preset.layout);setText('task-layout-status',preset.name+'を適用しました。');});const remove=make('button','削除','task-subtle');remove.type='button';remove.setAttribute('aria-label',preset.name+'を削除');remove.addEventListener('click',()=>{presets=presets.filter(item=>item.id!==preset.id);write(LAYOUT_KEY,presets);layoutRows();});row.append(name,apply,remove);box.append(row);}}
 function installLayouts(){
  dialog('task-layout-dialog','LAYOUT / 表示レイアウト','<p class="task-muted">HUDの表示枠、パネルの左右・開閉・ピン留め、右側モードを保存します。会話本文やAPIキーは保存しません。</p><div class="task-button-row"><button type="button" data-layout-built-in="all">全情報</button><button type="button" data-layout-built-in="focus">会話に集中</button><button type="button" data-layout-built-in="research">調べもの</button></div><div class="task-layout-save"><label>レイアウト名<input id="task-layout-name" maxlength="40" placeholder="研究用・発表用など" /></label><button type="button" id="task-layout-save">保存／同名を更新</button></div><p id="task-layout-status" role="status"></p><div id="task-layout-list"></div>');
  presets=(Array.isArray(read(LAYOUT_KEY))?read(LAYOUT_KEY):[]).map(normalizePreset).filter(Boolean).slice(0,12);layoutRows();
  $('task-layout-save').addEventListener('click',()=>{const name=$('task-layout-name').value.trim();if(!name){setText('task-layout-status','レイアウト名を入力してください。');return;}const existing=presets.find(item=>item.name===name);if(!existing&&presets.length>=12){setText('task-layout-status','レイアウトは12件までです。不要なものを削除してください。');return;}const saved={id:existing?.id||uid(),name,layout:captureLayout()};if(existing)Object.assign(existing,saved);else presets.push(saved);const stored=write(LAYOUT_KEY,presets);layoutRows();setText('task-layout-status',stored?name+'を保存しました。':'保存先を利用できないため、この画面内でのみ保持しています。再読込すると消えます。');});
  $('task-layout-name').addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.isComposing){event.preventDefault();$('task-layout-save').click();}});
  document.querySelectorAll('[data-layout-built-in]').forEach(button=>button.addEventListener('click',()=>{const kind=button.dataset.layoutBuiltIn;applyLayout({hud:{mode:kind==='focus'?'focus':'max',hiddenModules:[]},panels:[],rightMode:kind==='research'?'SEARCH':'INFO',autoPanels:kind!=='focus'});setText('task-layout-status',button.textContent+'を適用しました。');}));
 }
 function commandList(){const result=[];const aliases={weather:'weather 天気',map:'map route 地図 経路',translate:'translate 翻訳',document:'document 文書 メモ',system:'system CPU RAM GPU 使用率',search:'search 検索',youtube:'youtube 動画',qr:'qr コード',history:'history 履歴',performance:'performance 性能'};
  document.querySelectorAll('[data-open-panel]').forEach(button=>{const key=button.dataset.openPanel;result.push({label:button.textContent+'パネルを開く',group:'パネル',keywords:aliases[key]||key,run:()=>window.dashboardPanels.open(key,{source:'manual'})});});
  result.push({label:'チャットの入力欄へ移動',group:'会話',keywords:'chat 入力 focus',run:focusInput},{label:'すべての情報パネルを閉じる',group:'表示',keywords:'close 閉じる',run:()=>window.dashboardPanels.closeAll()},{label:'MAX HUD／FOCUSを切り替える',group:'表示',keywords:'max focus HUD 情報',run:()=>$('hud-mode-toggle').click()},{label:'レイアウトを保存・切り替える',group:'表示',keywords:'layout 保存 設定',run:()=>show('task-layout-dialog')},{label:'タイマー・ストップウォッチを開く',group:'時間',keywords:'timer stopwatch 時間 計測',run:()=>show('task-time-dialog')},{label:'5分の休憩タイマーを開始',group:'時間',keywords:'timer 5 休憩',run:()=>addTimer(300000,'5分休憩')},{label:'25分の作業タイマーを開始',group:'時間',keywords:'timer 25 ポモドーロ',run:()=>addTimer(1500000,'25分作業')});
  return result;
 }
 function renderCommands(){const terms=$('task-command-query').value.normalize('NFKC').toLocaleLowerCase().trim().split(/\s+/).filter(Boolean);shown=commands.filter(item=>terms.every(term=>(item.label+' '+item.group+' '+item.keywords).normalize('NFKC').toLocaleLowerCase().includes(term)));selected=Math.min(selected,Math.max(0,shown.length-1));const list=$('task-command-results');list.replaceChildren();shown.forEach((item,index)=>{const button=make('button',null,'task-command-result');button.type='button';button.id='task-command-'+index;button.setAttribute('role','option');button.setAttribute('aria-selected',String(selected===index));button.tabIndex=-1;button.append(make('span',item.label),make('small',item.group));button.addEventListener('click',()=>execute(index));list.append(button);});if(!shown.length)list.append(make('p','一致する操作がありません。','task-muted'));$('task-command-query').setAttribute('aria-activedescendant',shown.length?'task-command-'+selected:'');list.querySelector('[aria-selected="true"]')?.scrollIntoView({block:'nearest'});}
 function execute(index){const item=shown[index];if(!item)return;restorePaletteFocus=false;$('task-command-dialog').close();item.run();}
 function openPalette(){const modal=$('task-command-dialog');if(modal.open){modal.close();return;}returnFocus=document.activeElement;document.querySelectorAll('.task-dialog[open]').forEach(other=>other.close());restorePaletteFocus=true;commands=commandList();selected=0;$('task-command-query').value='';renderCommands();modal.showModal();$('task-command-query').focus();}
 function installPalette(){const modal=dialog('task-command-dialog','COMMAND / 操作を検索','<label class="task-command-label" for="task-command-query">パネル・操作を検索</label><input id="task-command-query" type="search" autocomplete="off" placeholder="例：CPU、翻訳、タイマー" role="combobox" aria-expanded="true" aria-controls="task-command-results" /><div id="task-command-results" role="listbox"></div><p class="task-muted">↑↓ 選択 / Enter 実行 / Esc 閉じる　・　Ctrl＋Shift＋Kで入力欄へ</p>');modal.addEventListener('close',()=>{if(restorePaletteFocus&&returnFocus?.isConnected&&!returnFocus.closest('[inert]'))returnFocus.focus({preventScroll:true});});$('task-command-query').addEventListener('input',()=>{selected=0;renderCommands();});modal.addEventListener('keydown',event=>{if(event.isComposing)return;if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();selected=shown.length?(selected+(event.key==='ArrowDown'?1:-1)+shown.length)%shown.length:0;renderCommands();}else if(event.key==='Enter'){event.preventDefault();execute(selected);}else if(event.key==='Escape'){event.stopPropagation();modal.close();}});
  window.addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k'&&!event.isComposing){event.preventDefault();event.stopImmediatePropagation();if(event.repeat)return;if(event.shiftKey){if(modal.open){restorePaletteFocus=false;modal.close();}focusInput();}else openPalette();}},true);
 }
 window.initTaskDeck=()=>{
  if($('task-command-open'))return;
  const nav=document.querySelector('.dashboard-nav');
  for(const[id,label,action]of[['task-command-open','COMMAND',openPalette],['task-layout-open','LAYOUT',()=>show('task-layout-dialog')],['task-time-open','TIME',()=>show('task-time-dialog')]]){const button=make('button',label,'task-nav-button');button.id=id;button.type='button';button.addEventListener('click',action);nav.append(button);}
  installPalette();installLayouts();installTime();$('message').title='Ctrl＋Kで操作検索 / Ctrl＋Shift＋Kで入力欄 / Shift＋Enterで改行';
  timerId=setInterval(()=>{if(!document.hidden)updateTimes();},100);
  document.addEventListener('visibilitychange',()=>{if(document.hidden)persist();else{originWall=Date.now();originMono=performance.now();updateTimes();}});
  window.addEventListener('pagehide',()=>{persist();clearInterval(timerId);});window.addEventListener('pageshow',event=>{if(event.persisted){originWall=Date.now();originMono=performance.now();clearInterval(timerId);timerId=setInterval(()=>{if(!document.hidden)updateTimes();},100);updateTimes();}});
  window.addEventListener('storage',event=>{if(event.key===STATE_KEY){state=T.restore(read(STATE_KEY));timerRows();watchRows();}else if(event.key===LAYOUT_KEY){presets=(Array.isArray(read(LAYOUT_KEY))?read(LAYOUT_KEY):[]).map(normalizePreset).filter(Boolean).slice(0,12);layoutRows();}});
 };
})();

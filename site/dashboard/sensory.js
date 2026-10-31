/* Real microphone frames, browser speech events and measured local HTTP latency. */
(() => {
  'use strict';
  const $=id=>document.getElementById(id), make=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
  const styles={standard:'標準',concise:'簡潔',detailed:'詳しく'};
  const key='ai-sensory-settings-v1';let prefs={voice:'',rate:1,pitch:1,reply_style:'standard',auto:true};
  try{const saved=JSON.parse(localStorage.getItem(key)||'null');if(saved&&typeof saved==='object')prefs={...prefs,...saved};}catch{}
  prefs.rate=Math.max(.5,Math.min(2,Number(prefs.rate)||1));prefs.pitch=Math.max(.5,Math.min(2,Number(prefs.pitch)||1));if(!(prefs.reply_style in styles))prefs.reply_style='standard';prefs.auto=prefs.auto!==false;
  let mic=false,currentSignal='idle',lastDraw=0,preview=null,poll=null,measuring=false,disposed=false,latencies=[],logs=[],lastTranscript='',measureVersion=0;
  const text=(id,value)=>{if($(id)&&$(id).textContent!==String(value))$(id).textContent=String(value);};
  const persist=()=>{try{localStorage.setItem(key,JSON.stringify(prefs));}catch{}};
  function download(name,data){const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=make('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  function signal(mode){
    currentSignal=mode;mic=mode==='microphone';const box=$('ai-signal');if(box)box.dataset.mode=mode;
    text('ai-signal-label',mic?'MIC / 実測':mode==='speaking'?'VOICE / 発話中':mode==='recognition'?'ASR / 待受中':mode==='recognition-wait'?'ASR / 再接続待ち':'MIC / OFF');
    if(!mic){draw(null,0,true);text('audio-level','未使用');}
  }
  function draw(samples,rms,force=false){
    const canvas=$('ai-signal-canvas');if(!canvas||document.hidden||(!force&&performance.now()-lastDraw<33))return;
    lastDraw=performance.now();const ctx=canvas.getContext('2d');if(!ctx)return;
    const w=canvas.width,h=canvas.height;ctx.clearRect(0,0,w,h);ctx.strokeStyle='#174252';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(0,h/2);ctx.lineTo(w,h/2);ctx.stroke();
    ctx.strokeStyle=samples?'#67e6ed':'#366878';ctx.lineWidth=2;ctx.beginPath();
    const count=128;for(let i=0;i<count;i++){const value=samples?(samples[Math.floor(i/(count-1)*(samples.length-1))]-128)/128:0;const x=i/(count-1)*w,y=h/2-value*h*.44;if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);}ctx.stroke();
    if(samples){const db=rms>0?20*Math.log10(rms):null;text('audio-level',db==null?'無音':`${db.toFixed(1)} dBFS`);}
  }
  function transcript(data){
    if(!data||typeof data.text!=='string')return;
    lastTranscript=data.text;text('audio-transcript',data.text);text('audio-transcript-state',data.final?'確定':'認識中');
    text('ai-live-caption',data.text);$('ai-live-caption').hidden=!data.text;
  }
  function voices(){
    const select=$('audio-voice');if(!select)return;select.replaceChildren();const auto=make('option','日本語の声を自動選択');auto.value='';select.append(auto);
    for(const voice of (window.speechSynthesis?.getVoices()||[]).slice(0,200)){const option=make('option',`${voice.name} / ${voice.lang}${voice.localService?' / 端末内':' / ブラウザー提供'}`);option.value=voice.voiceURI;select.append(option);}
    select.value=prefs.voice;if(select.selectedIndex<0)select.value='';
  }
  function configure(utterance){
    const list=window.speechSynthesis?.getVoices()||[];
    const voice=list.find(item=>item.voiceURI===prefs.voice)||list.find(item=>item.lang.startsWith('ja')&&item.localService)||list.find(item=>item.lang.startsWith('ja'));
    if(voice){utterance.voice=voice;utterance.lang=voice.lang;}else utterance.lang='ja-JP';utterance.rate=prefs.rate;utterance.pitch=prefs.pitch;
  }
  function speech(event,detail={}){
    if(event==='start'){signal('speaking');text('audio-speech-status','読み上げ中');}
    if(event==='end'||event==='error'||event==='stopped'){signal('idle');text('audio-speech-status',event==='end'?'読み上げ完了':event==='error'?'読み上げエラー':'読み上げ停止');}
    if(event==='boundary'&&Number.isFinite(detail.index)&&Number.isFinite(detail.total))text('audio-speech-progress',`発話位置 ${detail.index} / ${detail.total} 文字（ブラウザー通知値）`);
  }
  function addLog(kind,data={}){
    const labels={intent:'意図判定',tool:'ツール実行',local_llm:'ローカル推論',cloud_llm:'クラウド推論'};
    const duration=typeof data.duration_sec==='number'?` / ${data.duration_sec.toFixed(3)} s`:'';
    const label=kind==='start'?'要求受付':kind==='finish'?(data.ok?'応答完了':'応答失敗'):kind==='error'?'通信 / 実行エラー':`${data.tool_name||labels[data.stage]||data.stage} / ${data.status==='running'?'開始':data.success===false?'失敗':'完了'}${duration}`;
    logs.push({at:new Date().toISOString(),kind,label,...(kind==='stage'?{stage:data.stage,duration_sec:data.duration_sec,success:data.success}:{})});logs=logs.slice(-100);
    const box=$('audio-process-log');if(!box)return;const bottom=box.scrollHeight-box.scrollTop-box.clientHeight<30;box.replaceChildren();
    for(const item of logs){const row=make('div');row.append(make('time',new Date(item.at).toLocaleTimeString('ja-JP',{hour12:false})),make('span',item.label));box.append(row);}if(bottom)box.scrollTop=box.scrollHeight;
  }
  function renderLatency(){
    const svg=$('audio-rtt-chart');svg.replaceChildren();const ns='http://www.w3.org/2000/svg';const max=Math.max(1,...latencies.filter(s=>s.ok).map(s=>s.ms));
    for(let i=1;i<latencies.length;i++){const a=latencies[i-1],b=latencies[i];if(!a.ok||!b.ok)continue;const line=document.createElementNS(ns,'line');line.setAttribute('x1',String((i-1)/29*280+10));line.setAttribute('x2',String(i/29*280+10));line.setAttribute('y1',String(50-a.ms/max*40));line.setAttribute('y2',String(50-b.ms/max*40));line.setAttribute('stroke','#68d9ed');line.setAttribute('stroke-width','2');svg.append(line);}
    const valid=latencies.filter(s=>s.ok).map(s=>s.ms);text('audio-rtt-summary',valid.length?`${valid.length}回 / 平均 ${(valid.reduce((a,b)=>a+b,0)/valid.length).toFixed(1)} ms / 最大 ${Math.max(...valid).toFixed(1)} ms`:'成功した測定はありません');
  }
  async function measure(){
    clearTimeout(poll);if(disposed||measuring)return;measuring=true;const version=++measureVersion;const button=$('audio-measure');if(button)button.disabled=true;
    try{const start=performance.now(),r=await fetch('/system/clock',{cache:'no-store',signal:AbortSignal.timeout(5000)});const data=await r.json();if(!r.ok||!data.ok)throw new Error();const ms=performance.now()-start;if(disposed||version!==measureVersion)return;if(!Number.isFinite(ms)||ms<0)throw new Error();latencies.push({at:new Date().toISOString(),ok:true,ms});text('audio-rtt',ms.toFixed(1)+' ms');text('audio-rtt-status','AIサーバーとのHTTP往復時間 / '+new Date().toLocaleTimeString('ja-JP',{hour12:false}));text('ai-link-rtt','LINK / '+Math.round(ms)+' ms');}
    catch{if(disposed||version!==measureVersion)return;latencies.push({at:new Date().toISOString(),ok:false,ms:null});text('audio-rtt','取得失敗');text('audio-rtt-status','AIサーバーへ接続できません。');text('ai-link-rtt','LINK / OFFLINE');}
    finally{measuring=false;if(button)button.disabled=false;latencies=latencies.slice(-30);renderLatency();if(!disposed&&prefs.auto)poll=setTimeout(()=>{if(document.hidden){poll=setTimeout(measure,10000);return;}measure();},10000);}
  }
  window.prepareSensoryPanels=()=>{
    if($('audio-panel'))return;const panel=make('section',null,'panel');panel.dataset.infoPanel='audio';panel.id='audio-panel';panel.hidden=true;
    panel.innerHTML='<div class="panel-header"><strong>AUDIO / 音声・接続</strong></div><div class="panel-body signal-panel"><section><h3>VOICE INPUT / 音声認識</h3><p>左側の音声入力ボタンで開始します。認識中の言葉は字幕と入力欄へ反映します。</p><span id="audio-transcript-state">未使用</span><pre id="audio-transcript" aria-live="polite"></pre><button type="button" id="audio-clear-transcript">字幕を消す</button><p>入力レベル <strong id="audio-level">未使用</strong> / dBFSは端末内のデジタル音量です。</p></section><section><h3>SPEECH / 読み上げ設定</h3><label>声<select id="audio-voice"></select></label><label>速度 <output id="audio-rate-value">1.0</output><input type="range" id="audio-rate" min="0.5" max="2" step="0.1" value="1" /></label><label>高さ <output id="audio-pitch-value">1.0</output><input type="range" id="audio-pitch" min="0.5" max="2" step="0.1" value="1" /></label><div class="signal-actions"><button type="button" id="audio-preview">声を試す</button><button type="button" id="audio-stop">読み上げ停止</button></div><p id="audio-speech-status" role="status">未使用</p><p id="audio-speech-progress"></p><small>声によっては読み上げサービスへ文章が送信されます。出力波形は非公開のため発話イベントを表示します。</small></section><section><h3>REPLY STYLE / 回答文体</h3><label>通常のAI推論で使う文体<select id="audio-reply-style"><option value="standard">標準</option><option value="concise">簡潔</option><option value="detailed">詳しく</option></select></label><p>文体はAIへの生成指示に反映します。天気・計算などのツール結果の書式は対象外です。</p></section><section><h3>SERVER LINK / 接続計測</h3><strong id="audio-rtt">未計測</strong><p id="audio-rtt-status">AIサーバーとのHTTP往復時間です。インターネット全体のPingではありません。</p><label class="signal-check"><input id="audio-auto-rtt" type="checkbox" checked /> 10秒ごとに測定</label><div class="signal-actions"><button type="button" id="audio-measure">今すぐ測定</button><button type="button" id="audio-export-rtt">測定値を保存</button></div><svg id="audio-rtt-chart" viewBox="0 0 300 60" role="img" aria-label="HTTP往復時間の実測推移"></svg><p id="audio-rtt-summary"></p></section><details><summary>PROCESS LOG / 処理ログ</summary><p>実際の処理イベントだけを、この端末の時刻とともに表示します。</p><div id="audio-process-log" role="log"></div><div class="signal-actions"><button type="button" id="audio-export-log">ログを保存</button><button type="button" id="audio-clear-log">表示を消す</button></div></details></div>';
    $('info-panel-dock').append(panel);const button=make('button','AUDIO');button.type='button';button.dataset.openPanel='audio';button.setAttribute('aria-expanded','false');document.querySelector('.dashboard-nav').append(button);
  };
  window.aiSensory={configureUtterance:configure,signal,frame(samples,rms){draw(samples,rms);},transcript,speech,replyStyle:()=>prefs.reply_style};
  window.initSensoryUI=()=>{
    if($('ai-signal'))return;
    const signalBox=make('div',null,'ai-signal');signalBox.id='ai-signal';signalBox.innerHTML='<div><span id="ai-signal-label">MIC / OFF</span><button type="button" id="ai-link-rtt">LINK / 測定中</button></div><canvas id="ai-signal-canvas" width="600" height="64" aria-label="実測したマイク入力の波形"></canvas><div id="ai-live-caption" hidden></div>';
    $('core-state-label').after(signalBox);$('ai-link-rtt').addEventListener('click',()=>window.dashboardPanels.open('audio',{source:'manual'}));draw(null,0,true);
    $('audio-voice').addEventListener('change',()=>{prefs.voice=$('audio-voice').value;persist();});
    for(const type of ['rate','pitch']){$('audio-'+type).value=String(prefs[type]);text('audio-'+type+'-value',prefs[type].toFixed(1));$('audio-'+type).addEventListener('input',()=>{prefs[type]=Number($('audio-'+type).value);text('audio-'+type+'-value',prefs[type].toFixed(1));persist();});}
    $('audio-reply-style').value=prefs.reply_style;$('audio-reply-style').addEventListener('change',()=>{prefs.reply_style=$('audio-reply-style').value;persist();});
    const supported='speechSynthesis' in window&&'SpeechSynthesisUtterance' in window;
    for(const id of ['audio-voice','audio-rate','audio-pitch','audio-preview','audio-stop'])$(id).disabled=!supported;
    if(!supported)text('audio-speech-status','このブラウザーは読み上げに対応していません。');else{voices();window.speechSynthesis.addEventListener('voiceschanged',voices);}
    $('audio-preview').addEventListener('click',()=>{if(mic||currentSignal.startsWith('recognition')||window.workbench.busy()||window.speechSynthesis.speaking){text('audio-speech-status','音声入力・処理・読み上げが終わってから試してください。');return;}const u=new SpeechSynthesisUtterance('音声設定を確認します。');configure(u);preview=u;u.onstart=()=>text('audio-speech-status','試聴中');u.onend=()=>{preview=null;text('audio-speech-status','試聴完了');};u.onerror=()=>{preview=null;text('audio-speech-status','試聴を終了しました。');};window.speechSynthesis.speak(u);});
    $('audio-stop').addEventListener('click',()=>{$('speech-stop').click();window.speechSynthesis?.cancel();speech('stopped');});
    $('audio-clear-transcript').addEventListener('click',()=>{lastTranscript='';text('audio-transcript','');text('audio-transcript-state','消去済み');text('ai-live-caption','');$('ai-live-caption').hidden=true;});
    $('audio-measure').addEventListener('click',measure);$('audio-auto-rtt').checked=prefs.auto;$('audio-auto-rtt').addEventListener('change',()=>{prefs.auto=$('audio-auto-rtt').checked;persist();clearTimeout(poll);if(prefs.auto)measure();});
    $('audio-export-rtt').addEventListener('click',()=>download('ai-server-rtt.json',{source:'browser_http_round_trip',endpoint:'/system/clock',samples:latencies}));
    $('audio-export-log').addEventListener('click',()=>download('ai-process-events.json',{clock:'browser',events:logs}));$('audio-clear-log').addEventListener('click',()=>{logs=[];$('audio-process-log').replaceChildren();});
    window.addEventListener('jarvis:request-start',()=>addLog('start'));window.addEventListener('jarvis:execution-event',event=>{if(event.detail.kind==='stage')addLog('stage',event.detail.data);});window.addEventListener('jarvis:request-failed',()=>addLog('error'));
    window.addEventListener('jarvis:request-finished',event=>{addLog('finish',event.detail);const bubbles=$('chat-log').querySelectorAll('.bubble.assistant');const bubble=bubbles[bubbles.length-1];if(bubble&&!bubble.querySelector('.response-profile')){const chip=make('div',`文体設定：${styles[event.detail.reply_style]||'標準'} / ${event.detail.route||'経路未記録'}`,'response-profile');bubble.append(chip);}});
    window.addEventListener('jarvis:session-reset',()=>{logs=[];$('audio-process-log').replaceChildren();});
    window.addEventListener('pagehide',()=>{disposed=true;measureVersion++;clearTimeout(poll);preview=null;});window.addEventListener('pageshow',event=>{if(event.persisted){disposed=false;measure();}});
    document.addEventListener('visibilitychange',()=>{if(document.hidden){clearTimeout(poll);}else if(prefs.auto)measure();});measure();
  };
})();

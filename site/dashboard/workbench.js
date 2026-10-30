/* 実行結果カード、手動パネル保護、研究用の実測表示。 */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const titles = { weather:'天気', map:'地図', location:'現在地', translate:'翻訳', document:'文書', system:'システム', search:'検索', youtube:'YouTube', history:'処理履歴', performance:'性能', qr:'QRコード' };
  const stageNames = { intent:'意図判定', tool:'ツール実行', local_llm:'ローカルAI推論', cloud_llm:'クラウドAI推論' };
  let active = null, clock = null, recognitionStart = null, recognitionResult = null;
  const knownCards = new Set(), records = new Map(), suppressed = new Set();
  function successful(data) { const latest = new Map((data.cards || []).map(card => [card.kind,card])); return !!data.ok && data.route !== 'search_failed' && [...latest.values()].every(card => card.success); }
  function node(tag, text, className) { const el = document.createElement(tag); if (text != null) el.textContent = text; if (className) el.className = className; return el; }
  const seconds = value => typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(3)} 秒` : '—';
  function link(label, url) {
    try { const parsed = new URL(url); if (!['http:','https:'].includes(parsed.protocol)) return node('span',label); } catch { return node('span',label); }
    const a = node('a',label,'result-link'); a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer'; a.referrerPolicy = 'no-referrer'; return a;
  }
  function line(parent,label,value) { const row=node('div',null,'timing-line'); row.append(node('span',label),node('strong',value)); parent.append(row); }
  function panel(kind, bodyHtml) {
    const panel=node('section',null,'panel'); panel.dataset.infoPanel=kind; panel.hidden=true;
    const head=node('div',null,'panel-header'); head.append(node('strong',titles[kind]));
    const body=node('div',null,'panel-body'); body.innerHTML=bodyHtml; panel.append(head,body); return panel;
  }
  const languages='<option value="en">英語</option><option value="ja">日本語</option><option value="zh-CN">中国語</option><option value="ko">韓国語</option><option value="fr">フランス語</option><option value="de">ドイツ語</option><option value="es">スペイン語</option>';
  window.prepareWorkbenchPanels = () => {
    const dock=$('info-panel-dock');
    const left=node('div'); left.id='left-panel-dock'; document.querySelector('.monitor-column').append(left);
    const monitor=document.querySelector('.system-monitor'); monitor.dataset.infoPanel='system'; monitor.hidden=true; left.append(monitor);
    const docs=document.querySelector('#workspace-drawer > .panel'); docs.dataset.infoPanel='document'; docs.hidden=true; dock.append(docs);
    const oldDocManager=docs.querySelector('.panel-body');
    const viewer=node('div'); viewer.id='document-result'; oldDocManager.prepend(viewer);
    $('open-workspace').textContent='詳細設定';
    const translation=document.querySelector('[data-info-panel="translate"] .panel-body');
    translation.innerHTML=`<div class="tool-form"><label>翻訳元の文章<textarea id="translate-source" rows="3" placeholder="翻訳したい文章"></textarea></label><div class="language-row"><label>元の言語<select id="translate-from"><option value="auto">自動検出</option>${languages}</select></label><label>翻訳先<select id="translate-to">${languages}</select></label></div><button type="button" data-run="translate">翻訳する</button></div><div id="translate-result" class="tool-result">翻訳結果がここに表示されます。</div>`;
    const search=document.querySelector('[data-info-panel="search"] .panel-body');
    search.innerHTML='<div class="tool-form"><label>検索語<input id="search-query" placeholder="調べたい内容" /></label><div class="language-row"><button type="button" data-run="search">Web検索</button><button type="button" data-run="wikipedia">Wikipedia</button></div></div><div id="search-result" class="tool-result">実行した検索の結果と参照元を表示します。</div>';
    dock.append(
      panel('youtube','<div class="tool-form"><label>動画の検索語<input id="youtube-query" placeholder="検索する動画" /></label><button type="button" data-run="youtube">YouTube検索</button></div><div id="youtube-result" class="tool-result">取得した動画を表示します。</div>'),
      panel('qr','<div class="tool-form"><label>URL・文字列<textarea id="qr-text" rows="3" maxlength="2000"></textarea></label><button type="button" data-run="qr">QRコードを生成</button></div><div id="qr-result" class="tool-result">PC内で生成します。</div>'),
      panel('history','<button type="button" id="reload-processing">履歴を更新</button><div id="processing-history" class="tool-result">この会話の処理履歴を読み込みます。</div>'),
      panel('performance','<div id="performance-result"></div><div id="performance-chart" aria-label="実測した総応答時間の推移"></div><p class="measurement-note">グラフはこの会話の実測値。初回テキスト表示と音声出力完了はブラウザー時計、各内部処理はサーバー時計で測定します。</p>')
    );
    const runtime=document.querySelector('.runtime-panel'); document.querySelector('[data-info-panel="performance"] .panel-body').append(runtime);
    // 天気と地図の手動実行フォーム。既存の位置情報UIは維持。
    const weatherForm=node('div',null,'tool-form'); weatherForm.innerHTML='<label>地域・日付<input id="weather-query" placeholder="大阪の明日の天気" /></label><button type="button" data-run="weather">天気を取得</button>';
    $('weather-summary').before(weatherForm);
    const mapForm=node('div',null,'tool-form'); mapForm.innerHTML='<label>出発地・目的地<input id="map-query" placeholder="大阪駅から京都駅まで電車で" /></label><button type="button" data-run="map">経路を検索</button><div id="map-result" class="tool-result"></div>';
    $('map-panel-content').prepend(mapForm);
    // 起動時に見えるのはAIコアと短い計測情報だけ。
    const live=node('section',null,'panel live-timings'); live.innerHTML='<div class="panel-header"><strong>PROCESS / 実測</strong><span id="live-stage">待機中</span></div><div class="panel-body"><div id="live-elapsed">0.000 <small>秒</small></div><div id="live-stage-times"></div><p class="measurement-note">送信からの経過時間。詳しい記録は「性能」「処理履歴」へ。</p></div>';
    document.querySelector('.ai-core-panel').after(live);
    const nav=document.querySelector('.dashboard-nav');
    for (const kind of ['document','system','youtube','history','performance','qr']) {
      const button=node('button',titles[kind]); button.type='button'; button.dataset.openPanel=kind; button.setAttribute('aria-expanded','false'); nav.insertBefore(button,$('close-all-panels'));
    }
    const toggle=node('label',null,'auto-panels-control'); toggle.innerHTML='<input type="checkbox" id="auto-panels" checked /> 自動表示'; nav.insertBefore(toggle,$('close-all-panels'));
  };

  function rawResult(box,data,success) {
    box.replaceChildren(); box.classList.toggle('tool-error',!success);
    if (!success) box.append(node('p',data.error || data.text || '情報を取得できませんでした。'));
    else box.append(node('pre',data.text || data.response || data.summary_ja || '', 'result-text'));
    const urls=String(data.text || data.response || '').match(/https?:\/\/[^\s<>]+/g) || [];
    [...new Set(urls)].forEach(url=>box.append(link('参照元を開く',url)));
  }
  function applyCard(card) {
    if (!card || card.source!=='tool_result') return;
    if (card.event_id && knownCards.has(card.event_id)) return;
    if (card.event_id) knownCards.add(card.event_id);
    const kind=card.kind, data=card.data || {};
    if (kind==='weather') { $('weather-summary').dataset.toolResult='true'; rawResult($('weather-summary'),data,card.success); }
    else if (kind==='map') rawResult($('map-result'),data,card.success);
    else if (kind==='translate') {
      const box=$('translate-result'); box.replaceChildren();
      $('translate-source').value=data.original_text || '';
      $('translate-to').value=data.target_language || 'en'; $('translate-from').value=data.source_language || 'auto';
      box.append(node('span','翻訳結果','result-caption'),node('pre',data.translated_text || data.error || '翻訳結果なし','result-text'));
      if (data.external_url) box.append(link('外部翻訳ツールで開く',data.external_url));
      box.classList.toggle('tool-error',!card.success);
    } else if (kind==='document') {
      const box=$('document-result'); box.replaceChildren();
      if (data.document) { box.append(node('h3',data.document.title || '文書'),node('pre',data.document.content || data.document.text || '', 'result-text')); }
      else if (data.documents) {
        box.append(node('p',`保存文書 ${data.documents.length}件`));
        data.documents.forEach(doc=>{ const button=node('button',doc.title || doc.doc_id,'document-open-result'); button.type='button'; button.addEventListener('click',()=>runTool('document',{doc_id:doc.doc_id})); box.append(button); });
      } else box.append(node('p',data.error || '文書が見つかりませんでした。'));
    } else if (kind==='search') {
      const box=$('search-result'); box.replaceChildren();
      if (data.summary_ja) box.append(node('p',data.summary_ja));
      if (data.results?.length) data.results.forEach(item=>{ const row=node('article',null,'search-hit'); row.append(link(item.title || item.url,item.url),node('p',item.snippet || item.summary || '')); box.append(row); });
      else rawResult(box,data,card.success);
    } else if (kind==='youtube') {
      const box=$('youtube-result'); box.replaceChildren();
      if (!card.success) box.append(node('p',data.error || '動画の取得に失敗しました。'));
      (data.videos || []).forEach(video=>{
        const row=node('article',null,'video-hit');
        try { const url=new URL(video.thumbnail); if (url.protocol==='https:' && url.hostname==='i.ytimg.com') { const img=node('img'); img.src=url.href; img.alt=''; img.loading='lazy'; img.referrerPolicy='no-referrer'; row.append(img); } } catch {}
        row.append(link(video.title,video.url)); box.append(row);
      });
      if (data.search_url) box.append(link('YouTubeで検索を開く',data.search_url));
    } else if (kind==='qr') {
      const box=$('qr-result'); box.replaceChildren();
      if (card.success && /^data:image\/svg\+xml;base64,[A-Za-z0-9+/=]+$/.test(data.image_url)) {
        const image=node('img',null,'qr-image'); image.src=data.image_url; image.alt='生成したQRコード';
        const save=node('a','SVGで保存','result-link'); save.href=data.image_url; save.download='qrcode.svg';
        box.append(image,node('p',data.text),save);
      } else box.append(node('p',data.error || 'QRコードを生成できませんでした。'));
    }
    if ($('auto-panels')?.checked && !suppressed.has('*') && !suppressed.has(kind)) window.dashboardPanels.open(kind,{source:'auto'});
  }

  function drawLive() {
    if (!active) return;
    const elapsed=(performance.now()-active.start)/1000;
    $('live-elapsed').replaceChildren(document.createTextNode(elapsed.toFixed(3)+' '),node('small','秒'));
  }
  function stageTimes(box,execution) {
    box.replaceChildren();
    const totals=execution?.stage_totals || {};
    for (const kind of ['intent','tool','local_llm','cloud_llm']) line(box,stageNames[kind],kind in totals ? seconds(totals[kind]) : '未実行');
  }
  function logTimings(record) {
    if (!record?.request_id) return;
    fetch('/processing/client',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:record.request_id,session_id:record.session_id,timings:record.client_timings || {}})}).catch(()=>{});
  }
  function showRecord(record,box) {
    box.replaceChildren();
    stageTimes(box,record.execution);
    const t=record.client_timings || {};
    line(box,'音声認識（入力→確定）',t.speech_recognition_sec == null ? '未使用 / 未計測' : seconds(t.speech_recognition_sec));
    line(box,'テキスト生成完了（サーバー）',seconds(record.execution?.text_generation_complete_sec));
    line(box,'初回テキスト表示（送信→表示）',seconds(t.first_text_display_sec));
    line(box,'音声合成の内部時間','ブラウザー非公開');
    line(box,'音声開始待ち（合成依頼→発話）',seconds(t.speech_start_wait_sec));
    line(box,'音声再生時間',seconds(t.audio_playback_sec));
    line(box,'音声出力完了（送信→終了）',seconds(t.audio_output_complete_sec));
    line(box,'総応答（送信→テキスト表示）',seconds(t.text_display_complete_sec));
  }
  function conversationTiming(record) {
    let details=document.querySelector(`[data-execution-id="${record.request_id}"]`);
    if (!details) { details=node('details',null,'execution-details'); details.dataset.executionId=record.request_id; details.append(node('summary','実測した処理時間'),node('div',null,'execution-body')); $('chat-log').append(details); }
    showRecord(record,details.querySelector('.execution-body'));
  }
  function renderHistory() {
    const rows=[...records.values()].sort((a,b)=>(a.created_at||0)-(b.created_at||0)).slice(-60);
    const box=$('processing-history'); box.replaceChildren();
    if (!rows.length) box.append(node('p','この会話の記録はまだありません。'));
    rows.slice().reverse().forEach(record=>{
      const item=node('details',null,'processing-item');
      item.append(node('summary',`${record.success?'完了':'失敗'} · ${String(record.message||'').slice(0,60)}`));
      const stages=node('div');
      (record.execution?.stages || []).forEach(stage=>line(stages,`${stage.tool_name || stageNames[stage.stage] || stage.stage} / ${stage.success?'成功':'失敗'}`,seconds(stage.duration_sec)));
      item.append(stages); const timing=node('div'); showRecord(record,timing); item.append(timing); box.append(item);
    });
    const performanceBox=$('performance-result'); performanceBox.replaceChildren();
    if (!rows.length) { performanceBox.append(node('p','処理を実行すると実測結果を表示します。')); return; }
    showRecord(rows[rows.length-1],performanceBox);
    const sums=rows.reduce((acc,row)=>{ const t=row.execution?.stage_totals||{}; acc.local+=t.local_llm||0; acc.cloud+=t.cloud_llm||0; return acc; },{local:0,cloud:0});
    const total=sums.local+sums.cloud;
    line(performanceBox,'推論時間比率（この会話）',total>0?`ローカル ${(sums.local/total*100).toFixed(1)}% / クラウド ${(sums.cloud/total*100).toFixed(1)}%`:'AI推論の実行なし');
    const chart=$('performance-chart'); chart.replaceChildren();
    const download=node('a','この会話の計測CSVを保存','result-link'); download.href='/processing/export.csv?session_id='+encodeURIComponent($('session-id').value); download.download='processing_timings.csv'; chart.append(download);
    const values=rows.map(row=>row.client_timings?.text_display_complete_sec ?? row.execution?.server_elapsed_sec).filter(value=>typeof value==='number');
    if (!values.length) return;
    const ns='http://www.w3.org/2000/svg', svg=document.createElementNS(ns,'svg'); svg.setAttribute('viewBox','0 0 300 110'); svg.setAttribute('role','img'); svg.setAttribute('aria-label','応答時間の推移、単位は秒');
    const max=Math.max(...values,.001); const points=values.map((value,index)=>`${12+index/Math.max(1,values.length-1)*276},${95-value/max*75}`).join(' ');
    const polyline=document.createElementNS(ns,'polyline'); polyline.setAttribute('points',points); polyline.setAttribute('fill','none'); polyline.setAttribute('stroke','#64dced'); polyline.setAttribute('stroke-width','2'); svg.append(polyline);
    values.forEach((value,index)=>{const c=document.createElementNS(ns,'circle'); c.setAttribute('cx',String(12+index/Math.max(1,values.length-1)*276)); c.setAttribute('cy',String(95-value/max*75)); c.setAttribute('r','3'); c.setAttribute('fill','#64dced'); const title=document.createElementNS(ns,'title'); title.textContent=seconds(value); c.append(title); svg.append(c);});
    chart.append(node('p',`直近${values.length}件 · 最大${seconds(max)}`,'measurement-note'),svg);
  }
  async function loadHistory() {
    const session=$('session-id').value;
    try { const response=await fetch('/processing/history?session_id='+encodeURIComponent(session)); const data=await response.json(); if ($('session-id').value !== session) return; (data.records||[]).forEach(record=>records.set(record.request_id,record)); renderHistory(); }
    catch { $('processing-history').textContent='履歴を取得できませんでした。'; }
  }
  async function runTool(kind,params={}) {
    const send=$('send-btn'); if (send.disabled) return;
    const request={kind,...params};
    if (kind==='translate') Object.assign(request,{text:$('translate-source').value,source_lang:$('translate-from').value,target_lang:$('translate-to').value});
    if (['weather','map','search','wikipedia','youtube'].includes(kind)) request.query=$((kind==='wikipedia'?'search':kind)+'-query').value;
    if (kind==='qr') request.text=$('qr-text').value;
    const message=`${titles[kind] || kind}: ${request.text || request.query || request.doc_id || '情報取得'}`;
    send.disabled=true; window.addBubble('user',message);
    try {
      const data=await window.dashboardRequest({message,session_id:$('session-id').value,current_location:$('current-location').value,tool_request:request});
      window.addBubble('assistant',data.response || data.error || '処理が完了しました。');
      window.workbench.complete(data);
      if (data.ok) window.aiCore.answer(data.response,data.evaluation); else window.aiCore.setState('error');
      if (data.evaluation) window.showEvaluation(data.evaluation);
    } catch(error) { window.addBubble('assistant',`実行できませんでした: ${error.message}`); window.aiCore.setState('error'); window.workbench.fail(); }
    finally { send.disabled=false; }
  }
  window.workbench={
    succeeded: successful,
    busy() { return !!active && !active.completed; },
    suppress(kind) { suppressed.add(kind); },
    currentId() { return active?.request_id; },
    begin(payload) {
      suppressed.clear(); clearInterval(clock);
      active={start:performance.now(),session_id:payload.session_id,message:payload.message,stageTotals:{},client_timings:{}};
      if (recognitionResult?.text===payload.message) active.client_timings.speech_recognition_sec=recognitionResult.duration;
      recognitionResult=null;
      $('live-stage').textContent='処理開始'; $('live-stage-times').replaceChildren(); drawLive(); clock=setInterval(drawLive,100);
    },
    event(kind,data) {
      if (kind==='card') applyCard(data);
      if (kind==='stage') {
        const name=data.tool_name || stageNames[data.stage] || data.stage;
        $('live-stage').textContent=data.status==='running'?name:`${name} 完了`;
        if (data.status==='running') window.aiCore.setState(data.stage==='intent'?'analyzing':data.stage==='tool'?'tool':data.stage==='cloud_llm'?'cloud':'thinking');
        else if (active) { active.stageTotals[data.stage]=(active.stageTotals[data.stage]||0)+(data.exclusive_sec ?? data.duration_sec); stageTimes($('live-stage-times'),{stage_totals:active.stageTotals}); }
      }
    },
    complete(data) {
      if (!active || active.completed) return;
      active.completed=true; clearInterval(clock); drawLive(); $('live-stage').textContent=successful(data)?'完了':'失敗';
      active.request_id=data.execution?.request_id || data.evaluation?.request_id;
      active.execution=data.execution || {};
      active.client_timings.first_text_display_sec=(performance.now()-active.start)/1000;
      active.client_timings.text_display_complete_sec=active.client_timings.first_text_display_sec;
      (data.cards||[]).forEach(applyCard);
      if (!active.request_id) return;
      const record={request_id:active.request_id,session_id:active.session_id,message:active.message,created_at:Date.now()/1000,execution:active.execution,client_timings:active.client_timings,success:successful(data),route:data.route,start:active.start};
      records.set(record.request_id,record); conversationTiming(record); logTimings(record); renderHistory();
    },
    fail() { clearInterval(clock); drawLive(); if (active) active.completed=true; $('live-stage').textContent='通信 / 実行エラー'; },
    recognition(event) { if (event==='start') recognitionStart=performance.now(); else if (event==='end' && recognitionStart!=null) recognitionResult={duration:(performance.now()-recognitionStart)/1000,text:$('message').value}; else if(event==='error') recognitionResult=null; },
    speech(event,id) {
      const record=records.get(id); if (!record) return;
      const now=performance.now();
      if (event==='queued') record.speechQueued=now;
      if (event==='start') { record.speechStarted=now; record.client_timings.speech_start_wait_sec=(now-record.speechQueued)/1000; }
      if (event==='end' && record.speechStarted) { record.client_timings.audio_playback_sec=(now-record.speechStarted)/1000; record.client_timings.audio_output_complete_sec=(now-record.start)/1000; logTimings(record); conversationTiming(record); renderHistory(); }
    }
  };
  window.initWorkbench=()=>{
    document.querySelectorAll('[data-run]').forEach(button=>button.addEventListener('click',()=>runTool(button.dataset.run)));
    $('reload-processing').addEventListener('click',loadHistory);
    $('reset-btn').addEventListener('click',()=>{records.clear();clearInterval(clock);active=null;renderHistory();});
    $('session-id').addEventListener('change',()=>{records.clear();loadHistory();});
    loadHistory();
    // 形状は固定した少数のDOM要素。フレームごとの粒子生成は行わない。
    const core=$('ai-core');
    for (const className of ['core-ticks','core-segments','core-tilt','core-scan','core-particles']) core.append(node('div',null,className));
    document.addEventListener('visibilitychange',()=>core.classList.toggle('animation-paused',document.hidden));
  };
})();

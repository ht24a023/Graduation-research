/* 常設の監視状態、実行イベント、端末内で動く操作コンソール。 */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const el = (tag, text, cls) => { const n = document.createElement(tag); if (text != null) n.textContent = text; if (cls) n.className = cls; return n; };
  const numeric = value => typeof value === 'number' && Number.isFinite(value);
  const percent = value => numeric(value) ? value.toFixed(1) + '%' : '未取得';
  const gigabytes = value => numeric(value) ? (value / 1073741824).toFixed(1) + ' GB' : '未取得';
  const seconds = value => numeric(value) ? value.toFixed(3) + ' 秒' : '未計測';
  const stageLabels = { intent:'意図判定', tool:'ツール', local_llm:'ローカル推論', cloud_llm:'クラウド推論' };
  let latest = null, sampledAt = 0, cpuStreak = 0, alerts = [], transitions = new Map(), feed = [], watchSignature = null;
  let timer = { state:'idle', remaining:0, deadline:null }, interval = null, returnFocus = null, commands = [], disposed = false;
  function text(id, value) { const n = $(id); if (n && n.textContent !== value) n.textContent = value; }
  function log(label, kind = 'info') {
    feed.unshift({ label, kind, at:new Date() }); feed = feed.slice(0, 30);
    if (!$('ops-event-list')) return;
    $('ops-event-list').replaceChildren();
    for (const item of feed) {
      const row = el('div', null, 'ops-event'); row.dataset.kind = item.kind;
      row.append(el('time', item.at.toLocaleTimeString('ja-JP', { hour12:false })), el('span', item.label));
      $('ops-event-list').append(row);
    }
  }
  function renderWatch() {
    if (!$('ops-alert-list')) return;
    const stale = sampledAt && performance.now() - sampledAt > 12000;
    let label = !latest ? 'PC情報に接続中' : stale ? 'PC情報の更新停止' : alerts.length ? `${alerts.length}件の注意` : '監視中';
    text('ops-watch-label', label); text('ops-watch-mini', label);
    $('ops-watch-mini').dataset.level = stale || alerts.length ? 'warning' : latest ? 'normal' : 'unknown';
    if (latest) text('ops-snapshot', `CPU ${percent(latest.cpu?.usage_percent)} / RAM ${percent(latest.memory?.usage_percent)} / DISK ${percent(latest.disk?.usage_percent)}`);
    const signature = label + '|' + stale + '|' + alerts.map(a => a.label).join('|');
    if (signature === watchSignature) return; watchSignature = signature;
    $('ops-alert-list').replaceChildren();
    if (!latest) $('ops-alert-list').append(el('p', '実測データの到着を待っています。'));
    if (stale) $('ops-alert-list').append(el('p', '表示値は最新ではありません。接続を確認してください。', 'ops-warning'));
    for (const alert of alerts) $('ops-alert-list').append(el('p', alert.label, 'ops-warning'));
    if (latest && !alerts.length && !stale) $('ops-alert-list').append(el('p', '取得できた項目に、設定した注意条件はありません。'));
  }
  function metrics(data) {
    if (!data?.ok || !numeric(data.sampled_at)) return;
    const fresh = !latest || latest.sampled_at !== data.sampled_at;
    latest = data; sampledAt = performance.now();
    if (fresh) cpuStreak = numeric(data.cpu?.usage_percent) && data.cpu.usage_percent >= 95 ? cpuStreak + 1 : 0;
    const next = [];
    if (cpuStreak >= 3) next.push({ key:'cpu', label:`CPUの高負荷が3回以上継続：${percent(data.cpu.usage_percent)}` });
    if (numeric(data.memory?.usage_percent) && data.memory.usage_percent >= 90) next.push({ key:'ram', label:`メモリ使用量が高い状態：${percent(data.memory.usage_percent)}` });
    if (numeric(data.disk?.usage_percent) && data.disk.usage_percent >= 95) next.push({ key:'disk', label:`ディスク空き容量が少ない状態：${gigabytes(data.disk.free_bytes)}` });
    if (numeric(data.battery?.percent) && !data.battery.plugged && data.battery.percent <= 20) next.push({ key:'battery', label:`バッテリー残量：${data.battery.percent}%` });
    const keys = new Set(next.map(a => a.key));
    for (const item of next) if (!transitions.has(item.key)) log(item.label, 'warning');
    for (const [key, label] of transitions) if (!keys.has(key)) log(`注意条件を解除：${label}`, 'success');
    transitions = new Map(next.map(a => [a.key, a.label])); alerts = next; renderWatch();
  }
  function saveTimer() { try { localStorage.setItem('jarvis-task-timer-v1', JSON.stringify(timer)); } catch {} }
  function restoreTimer() {
    try {
      const value = JSON.parse(localStorage.getItem('jarvis-task-timer-v1') || 'null');
      if (value && ['running','paused','done','idle'].includes(value.state) && numeric(value.remaining) && value.remaining >= 0 && value.remaining <= 10800000 && (value.state !== 'running' || numeric(value.deadline))) timer = value;
    } catch {}
  }
  function duration() { return timer.state === 'running' ? Math.max(0, timer.deadline - Date.now()) : timer.remaining; }
  function renderTimer() {
    const left = duration();
    if (timer.state === 'running' && left <= 0) { timer = { state:'done', remaining:0, deadline:null }; saveTimer(); log('作業タイマーが完了しました', 'success'); }
    const total = Math.ceil(left / 1000), value = `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`;
    text('ops-timer-display', value); text('ops-timer-mini', timer.state === 'idle' ? 'TIMER / OFF' : `${timer.state === 'done' ? '完了' : timer.state === 'paused' ? '一時停止' : 'TIMER'} / ${value}`);
    if ($('ops-timer-mini')) $('ops-timer-mini').dataset.state = timer.state;
    if ($('ops-timer-pause')) $('ops-timer-pause').disabled = timer.state !== 'running';
    if ($('ops-timer-start')) $('ops-timer-start').textContent = timer.state === 'paused' ? '再開' : timer.state === 'running' ? '実行中' : '開始';
    if ($('ops-timer-start')) $('ops-timer-start').disabled = timer.state === 'running';
    text('ops-timer-state', { idle:'停止中', running:'実行中', paused:'一時停止', done:'完了しました' }[timer.state]);
  }
  function startTimer() {
    if (timer.state === 'running') return;
    const minutes = Number($('ops-timer-minutes').value);
    if (timer.state !== 'paused' && (!Number.isFinite(minutes) || minutes < 1 || minutes > 180)) { text('ops-command-status','時間は1〜180分で指定してください。'); return; }
    const remaining = timer.state === 'paused' ? timer.remaining : minutes * 60000;
    timer = { state:'running', remaining, deadline:Date.now() + remaining }; saveTimer(); renderTimer(); log('作業タイマーを開始', 'info');
  }
  function pauseTimer() { if (timer.state !== 'running') return; timer = { state:'paused', remaining:duration(), deadline:null }; saveTimer(); renderTimer(); }
  function resetTimer() { timer = { state:'idle', remaining:0, deadline:null }; saveTimer(); renderTimer(); }
  function downloadReport() {
    if (!latest) throw new Error('PC情報を取得してから保存できます。');
    const rows = [ 'AI / PC診断スナップショット', `採取時刻：${new Date(latest.sampled_at * 1000).toISOString()}`, `PC：${latest.hostname || '未取得'}`, `CPU：${percent(latest.cpu?.usage_percent)}`, `RAM：${percent(latest.memory?.usage_percent)} / 空き ${gigabytes(latest.memory?.available_bytes)}`, `DISK：${percent(latest.disk?.usage_percent)} / 空き ${gigabytes(latest.disk?.free_bytes)}`, ...alerts.map(a => '注意：' + a.label), 'このファイルは採取時点の実測スナップショットです。' ];
    const url = URL.createObjectURL(new Blob([rows.join('\n')], { type:'text/plain;charset=utf-8' }));
    const a = el('a'); a.href = url; a.download = 'ai-pc-report.txt'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    text('ops-command-status','PC診断レポートのダウンロードを開始しました。');
  }
  async function run(command) {
    try { await command.action(); if (command.close) close(); else if (!command.keepStatus) text('ops-command-status', command.label + '：完了'); }
    catch (error) { text('ops-command-status', error.message || '実行できませんでした。'); }
  }
  function renderCommands() {
    const query = $('ops-command-query').value.trim().toLocaleLowerCase();
    const matched = commands.filter(c => (c.label + ' ' + c.search).toLocaleLowerCase().includes(query));
    $('ops-command-list').replaceChildren();
    for (const command of matched) { const b = el('button', command.label); b.type = 'button'; b.addEventListener('click', () => run(command)); $('ops-command-list').append(b); }
    if (!matched.length) $('ops-command-list').append(el('p','一致する操作はありません。'));
  }
  function open() { if ($('ops-console').open) return; returnFocus = document.activeElement; $('ops-console').showModal(); $('ops-command-query').focus(); renderWatch(); }
  function close() { $('ops-console').close(); }
  function install() {
    const trigger = el('button','CONTROL'); trigger.type = 'button'; trigger.id = 'ops-open'; trigger.title = '操作コンソール / Alt + J'; trigger.addEventListener('click',open); document.querySelector('.dashboard-nav').append(trigger);
    const mini = el('div',null,'ops-core-status'); mini.append(el('button','PC情報に接続中'),el('button','TIMER / OFF')); mini.children[0].id = 'ops-watch-mini'; mini.children[1].id = 'ops-timer-mini';
    for (const button of mini.children) { button.type = 'button'; button.addEventListener('click',open); }
    document.querySelector('.ai-core-panel').append(mini);
    const dialog = el('dialog'); dialog.id = 'ops-console'; dialog.setAttribute('aria-labelledby','ops-title');
    dialog.innerHTML = '<header class="ops-dialog-head"><div><small>LOCAL OPERATIONS</small><h2 id="ops-title">COMMAND CONSOLE</h2></div><button type="button" id="ops-close" aria-label="操作コンソールを閉じる">×</button></header><div class="ops-dialog-body"><section class="ops-watch"><h3>SYSTEM WATCH <span id="ops-watch-label"></span></h3><p id="ops-snapshot">実測待機中</p><div id="ops-alert-list" role="status"></div><small>注意条件：CPU 95%以上を3回継続／RAM 90%以上／ディスク95%以上／電池20%以下。取得した値だけを監視します。</small></section><section class="ops-timer"><h3>TASK TIMER <span id="ops-timer-state"></span></h3><div id="ops-timer-display" role="timer">00:00</div><label>時間（分）<input type="number" id="ops-timer-minutes" min="1" max="180" value="25" /></label><div class="ops-timer-buttons"><button id="ops-timer-start" type="button">開始</button><button id="ops-timer-pause" type="button">一時停止</button><button id="ops-timer-reset" type="button">リセット</button></div></section><section class="ops-commands"><label for="ops-command-query">操作を検索</label><input id="ops-command-query" placeholder="地図・履歴・レポート…" autocomplete="off" /><div id="ops-command-list"></div><p id="ops-command-status" role="status"></p></section><section class="ops-events"><h3>ACTIVITY / 実際の処理イベント</h3><div id="ops-event-list"><p>処理を実行すると表示します。</p></div></section></div>';
    document.body.append(dialog); $('ops-close').addEventListener('click',close); dialog.addEventListener('close', () => returnFocus?.focus({ preventScroll:true }));
    dialog.addEventListener('click',event=>{if(event.target === dialog){const rect=dialog.getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)close();}});
    $('ops-timer-start').addEventListener('click',startTimer); $('ops-timer-pause').addEventListener('click',pauseTimer); $('ops-timer-reset').addEventListener('click',resetTimer);
    $('ops-command-query').addEventListener('input',renderCommands);
    $('ops-command-query').addEventListener('keydown',event=>{if(event.key==='ArrowDown'){event.preventDefault();$('ops-command-list').querySelector('button')?.focus();}if(event.key==='Enter'){event.preventDefault();$('ops-command-list').querySelector('button')?.click();}});
    document.addEventListener('keydown',event=>{if(event.altKey && event.key.toLowerCase()==='j'){event.preventDefault();if($('workspace-drawer').hidden)dialog.open?close():open();}});
    for (const button of document.querySelectorAll('[data-open-panel]')) { const key=button.dataset.openPanel;commands.push({ label:button.textContent+'を開く', search:key, close:true, action:()=>window.dashboardPanels.open(key,{source:'manual'}) }); }
    commands.push({ label:'PC診断レポートを保存', search:'report system snapshot', keepStatus:true, action:downloadReport },{ label:'すべての情報パネルを閉じる', search:'close', close:true, action:()=>window.dashboardPanels.closeAll() },{ label:'画面を全画面表示／解除', search:'fullscreen', action:async()=>{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen();} },{ label:'最後の回答をコピー', search:'copy answer', action:async()=>{const answer=$('chat-log').querySelector('.bubble.assistant:last-of-type');const answers=$('chat-log').querySelectorAll('.bubble.assistant');const last=answers[answers.length-1]||answer;if(!last)throw new Error('コピーできる回答がありません。');if(!navigator.clipboard?.writeText)throw new Error('このブラウザーではクリップボードを利用できません。');await navigator.clipboard.writeText((last.querySelector('.bubble-content')||last).textContent);} },{ label:'読み上げを停止', search:'speech stop', action:()=>$('speech-stop').click() });
    renderCommands(); restoreTimer(); renderTimer(); renderWatch();
  }
  window.initJarvisOperations = () => {
    if ($('ops-console')) return; install();
    window.addEventListener('jarvis:system-metrics',event=>metrics(event.detail));
    window.addEventListener('jarvis:request-start',()=>log('要求を受付 / 処理開始'));
    window.addEventListener('jarvis:execution-event',event=>{const {kind,data}=event.detail;if(kind!=='stage')return;const label=data.tool_name||stageLabels[data.stage]||data.stage;log(`${label} / ${data.status==='running'?'開始':data.success===false?'失敗':'完了'}${numeric(data.duration_sec)?' / '+seconds(data.duration_sec):''}`,data.success===false?'error':'info');});
    window.addEventListener('jarvis:request-finished',event=>{const d=event.detail;log(`${d.ok?'応答完了':'応答失敗'} / ${d.route||'経路未記録'} / ${seconds(d.elapsed)}`,d.ok?'success':'error');});
    window.addEventListener('jarvis:request-failed',()=>log('通信 / 実行エラー','error'));
    window.addEventListener('jarvis:session-reset',()=>{feed=[];$('ops-event-list').replaceChildren(el('p','処理を実行すると表示します。'));});
    window.addEventListener('storage',event=>{if(event.key==='jarvis-task-timer-v1'){restoreTimer();renderTimer();}});
    const tick=()=>{renderTimer();renderWatch();}; interval=setInterval(tick,1000);
    window.addEventListener('pagehide',()=>{disposed=true;clearInterval(interval);});
    window.addEventListener('pageshow',event=>{if(event.persisted&&disposed){disposed=false;restoreTimer();tick();interval=setInterval(tick,1000);}});
  };
})();

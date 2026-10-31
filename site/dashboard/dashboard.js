/* 実際の処理状態、音声、手動パネル配置を管理する。 */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const labels = { idle: '待機中', listening: '音声検出中', recognizing: '音声認識中', thinking: 'AI推論中', cloud: 'クラウド委譲中', responding: '回答中', analyzing: '意図判定中', tool: 'ツール実行中', error: 'エラー' };
  let resetTimer;
  let activityVersion = 0;
  let recognition = null;
  let micStream = null;
  let audioContext = null;
  let meterFrame = null;
  let listening = false;
  let currentUtterance = null;
  function savePreference(key, value) { try { localStorage.setItem(key, value); } catch {} }
  function readPreference(key) { try { return localStorage.getItem(key); } catch { return null; } }
  function stopSpeech() {
    window.speechSynthesis?.cancel(); currentUtterance = null; window.aiSensory?.speech('stopped');
    if ($('speech-stop')) $('speech-stop').disabled = true;
    if (!listening && !$('send-btn').disabled) state('idle');
  }
  function state(value) {
    if (!(value in labels)) return;
    clearTimeout(resetTimer);
    const core = $('ai-core');
    core.dataset.state = value;
    core.setAttribute('aria-label', `AIの状態: ${labels[value]}`);
    $('core-state-label').textContent = labels[value];
  }
  function laterIdle(delay = 900) {
    const version = activityVersion;
    resetTimer = setTimeout(() => { if (version === activityVersion && !listening) state('idle'); }, delay);
  }
  function begin() {
    activityVersion++;
    if (recognition && listening) recognition.stop();
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
    currentUtterance = null;
    if ($('speech-stop')) $('speech-stop').disabled = true;
    state('analyzing');
  }
  window.aiCore = {
    setState: state,
    setAudioLevel(value) { $('ai-core').style.setProperty('--level', String(Math.max(0, Math.min(1, Number(value) || 0)))); },
    answer(text, evaluation) {
      state('responding');
      const speechRequest = window.workbench?.currentId();
      const local = evaluation && evaluation.local_time_sec;
      const cloud = evaluation && evaluation.cloud_time_sec;
      $('local-time-value').textContent = typeof local === 'number' ? `${local.toFixed(2)} 秒` : '未計測';
      $('cloud-time-value').textContent = evaluation && evaluation.api_called && typeof cloud === 'number' ? `${cloud.toFixed(2)} 秒` : '未使用';
      if ($('speak-enabled').checked && 'speechSynthesis' in window && text) {
        const version = activityVersion;
        const utterance = new SpeechSynthesisUtterance(String(text));
        utterance.lang = 'ja-JP'; window.aiSensory?.configureUtterance(utterance);
        utterance.onstart = () => { if(version === activityVersion)window.aiSensory?.speech('start'); window.workbench?.speech('start', speechRequest); if (version === activityVersion) state('responding'); };
        utterance.onend = () => { if(version === activityVersion)window.aiSensory?.speech('end'); if ($('speech-stop') && version === activityVersion) $('speech-stop').disabled = true; window.workbench?.speech('end', speechRequest); if (version === activityVersion) { currentUtterance = null; state('idle'); } };
        utterance.onboundary = event => { if(version === activityVersion)window.aiSensory?.speech('boundary',{index:event.charIndex,total:String(text).length}); };
        utterance.onerror = event => { if(version === activityVersion)window.aiSensory?.speech(event.error==='canceled'||event.error==='interrupted'?'stopped':'error'); if ($('speech-stop') && version === activityVersion) $('speech-stop').disabled = true; if (version === activityVersion && event.error !== 'canceled' && event.error !== 'interrupted') state('error'); };
        window.workbench?.speech('queued', speechRequest);
        currentUtterance = utterance;
        if ($('speech-stop')) $('speech-stop').disabled = false;
        window.speechSynthesis.speak(utterance);
      } else laterIdle(1100);
    }
  };

  window.dashboardRequest = async payload => {
    payload={...payload,reply_style:payload.reply_style||window.aiSensory?.replyStyle()||'standard'};
    begin();
    window.workbench?.begin(payload);
    const sessionControls = [$('session-id'), $('reset-btn'), $('turbo-mode')].filter(Boolean).map(element => ({ element, disabled: element.disabled }));
    sessionControls.forEach(({ element }) => { element.disabled = true; });
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 240000);
    try {
      const response = await fetch('/chat', {
        method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
        body: JSON.stringify(payload), signal: controller.signal
      });
      if (!response.headers.get('content-type')?.includes('text/event-stream')) {
        let data;
        try { data = await response.json(); } catch { throw new Error(`サーバーが応答を返せませんでした（HTTP ${response.status}）`); }
        if (!response.ok) throw new Error(data.error || `サーバーエラー（HTTP ${response.status}）`);
        return data;
      }
      if (!response.ok || !response.body) throw new Error(`応答ストリームを開始できませんでした（HTTP ${response.status}）`);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let result = null;
      function receive(frame) {
        let kind = 'message';
        const lines = [];
        for (const line of frame.split('\n')) {
          if (line.startsWith('event:')) kind = line.slice(6).trim();
          if (line.startsWith('data:')) lines.push(line.slice(5).trimStart());
        }
        if (!lines.length) return;
        const data = JSON.parse(lines.join('\n'));
        if (kind === 'status' && data.state in labels) state(data.state);
        window.workbench?.event(kind, data);
        if (kind === 'done' || kind === 'error') result = data;
      }
      while (true) {
        const chunk = await reader.read();
        buffer += decoder.decode(chunk.value || new Uint8Array(), { stream: !chunk.done }).replace(/\r/g, '');
        let position;
        while ((position = buffer.indexOf('\n\n')) >= 0) {
          receive(buffer.slice(0, position)); buffer = buffer.slice(position + 2);
        }
        if (chunk.done) { if (buffer.trim()) receive(buffer); break; }
      }
      if (!result) throw new Error('サーバーから最終結果を受信できませんでした');
      return result;
    } catch (error) { window.workbench?.fail(); if (error.name === 'AbortError') throw new Error('応答が4分以内に完了しませんでした。接続状態を確認して再送してください。'); throw error; } finally { clearTimeout(timer); sessionControls.forEach(({ element, disabled }) => { element.disabled = disabled; }); }
  };

  function metric(label, value, note, percent) {
    const block = document.createElement('div'); block.className = 'metric';
    const head = document.createElement('div'); head.className = 'metric-head';
    const name = document.createElement('span'); name.textContent = label;
    const amount = document.createElement('strong'); amount.textContent = value;
    head.append(name, amount); block.append(head);
    if (typeof percent === 'number') {
      const bar = document.createElement('progress'); bar.max = 100; bar.value = percent; bar.setAttribute('aria-label', label); block.append(bar);
    }
    const detail = document.createElement('div'); detail.className = 'metric-note'; detail.textContent = note; block.append(detail);
    return block;
  }
  let monitorAutoCollapseTimer = null;
  const monitorPinned = new Set();
  function bindMonitorRows() {
    const content = $('system-monitor-content');
    if (!content) return;
    content.querySelectorAll('.monitor-detail').forEach(row => {
      if (row.dataset.bound === 'true') return;
      row.dataset.bound = 'true';
      row.tabIndex = 0; row.setAttribute('role', 'button');
      const pin = document.createElement('button');
      pin.type = 'button';
      pin.className = 'monitor-pin';
      pin.textContent = 'ピン';
      pin.setAttribute('aria-label', `${row.dataset.monitorLabel || '項目'} を固定`);
      pin.addEventListener('click', event => {
        event.preventDefault(); event.stopPropagation();
        const key = row.dataset.monitorKey || row.dataset.monitorLabel || 'detail';
        if (monitorPinned.has(key)) {
          monitorPinned.delete(key); row.classList.remove('is-pinned');
        } else {
          monitorPinned.add(key); row.classList.add('is-pinned');
        }
        pin.setAttribute('aria-pressed', String(monitorPinned.has(key)));
      });
      row.append(pin);
      row.addEventListener('click', event => {
        if (event.target.closest('.monitor-pin')) return;
        const contentNode = row.closest('#system-monitor-content');
        const rows = contentNode ? [...contentNode.querySelectorAll('.monitor-detail')] : [];
        rows.forEach(item => {
          if (item !== row && !monitorPinned.has(item.dataset.monitorKey || item.dataset.monitorLabel || 'detail')) {
            item.classList.remove('is-expanded');
          }
        });
        const key = row.dataset.monitorKey || row.dataset.monitorLabel || 'detail';
        const shouldExpand = !row.classList.contains('is-expanded');
        row.classList.toggle('is-expanded', shouldExpand);
        if (shouldExpand) {
          updateMonitorAutoCollapse();
        } else {
          clearMonitorAutoCollapse();
        }
      });
      row.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault(); row.click();
        }
      });
    });
  }
  function updateMonitorAutoCollapse() {
    clearMonitorAutoCollapse();
    const content = $('system-monitor-content');
    if (!content) return;
    const expanded = [...content.querySelectorAll('.monitor-detail.is-expanded')].filter(row => !monitorPinned.has(row.dataset.monitorKey || row.dataset.monitorLabel || 'detail'));
    if (!expanded.length) return;
    monitorAutoCollapseTimer = setTimeout(() => {
      expanded.forEach(row => row.classList.remove('is-expanded'));
      clearMonitorAutoCollapse();
    }, 5000);
  }
  function clearMonitorAutoCollapse() {
    if (monitorAutoCollapseTimer) {
      clearTimeout(monitorAutoCollapseTimer);
      monitorAutoCollapseTimer = null;
    }
  }
  function detail(label, value, id, extraDetail = '') {
    const row = document.createElement('div'); row.className = 'monitor-detail';
    row.dataset.monitorKey = String(id || label).toLowerCase();
    row.dataset.monitorLabel = label;
    const main = document.createElement('div'); main.className = 'monitor-main';
    const name = document.createElement('span'); name.textContent = label;
    const content = document.createElement('strong'); content.textContent = value; if (id) content.id = id;
    main.append(name, content);
    row.append(main);
    if (extraDetail) {
      const extra = document.createElement('div'); extra.className = 'monitor-extra'; extra.textContent = extraDetail;
      row.append(extra);
    }
    return row;
  }
  const gb = value => typeof value === 'number' ? `${(value / 1024 ** 3).toFixed(1)} GB` : '取得不可';
  const pct = value => typeof value === 'number' ? `${value.toFixed(1)}%` : '計測中';
  const speed = value => typeof value === 'number' ? value >= 1024 ** 2 ? `${(value / 1024 ** 2).toFixed(1)} MB/s` : `${(value / 1024).toFixed(1)} KB/s` : '計測中';
  let monitorTimer;
  let monitorDisposed = false;
  async function refreshMonitor() {
    if (monitorDisposed) return;
    try {
      const response = await fetch('/system/metrics', { cache: 'no-store', signal: AbortSignal.timeout(7000) });
      const data = await response.json();
      if (monitorDisposed) return;
      if (!response.ok || !data.ok) throw new Error(data.error || 'PC情報の取得に失敗しました');
      window.dispatchEvent(new CustomEvent('jarvis:system-metrics',{detail:data}));
      const oldLocal = $('local-time-value')?.textContent || '未計測';
      const oldCloud = $('cloud-time-value')?.textContent || '未使用';
      const content = $('system-monitor-content'); const scrollPosition = content.scrollTop; content.replaceChildren();
      content.append(
        metric('CPU', pct(data.cpu.usage_percent), `${data.cpu.physical_cores ?? '—'} コア / ${data.cpu.logical_cores ?? '—'} スレッド`, data.cpu.usage_percent),
        metric('RAM', pct(data.memory.usage_percent), `${gb(data.memory.used_bytes)} / ${gb(data.memory.total_bytes)}`, data.memory.usage_percent),
        metric('DISK', pct(data.disk.usage_percent), `${data.disk.path} 空き ${gb(data.disk.free_bytes)} / ${gb(data.disk.total_bytes)}`, data.disk.usage_percent),
        detail('通信速度', `↑ ${speed(data.network.send_bytes_sec)} / ↓ ${speed(data.network.receive_bytes_sec)}`, 'network-speed', `送信 ${speed(data.network.send_bytes_sec)} / 受信 ${speed(data.network.receive_bytes_sec)} · 合計 ${gb(data.network.sent_bytes)} / ${gb(data.network.received_bytes)}`),
        detail('累計送受信', `↑ ${gb(data.network.sent_bytes)} / ↓ ${gb(data.network.received_bytes)}`, 'network-total', `送信累計 ${gb(data.network.sent_bytes)} · 受信累計 ${gb(data.network.received_bytes)} · 実測は現在の回線負荷で表示`),
        detail('PC稼働時間', `${Math.floor(data.uptime_sec / 86400)}日 ${Math.floor(data.uptime_sec / 3600) % 24}時間 ${Math.floor(data.uptime_sec / 60) % 60}分`, 'uptime', `稼働時間 ${Math.floor(data.uptime_sec / 86400)}日 ${Math.floor(data.uptime_sec / 3600) % 24}時間 ${Math.floor(data.uptime_sec / 60) % 60}分 · バックエンドPC`),
        detail('CPU温度', data.cpu.temperature_c == null ? '取得非対応' : `${data.cpu.temperature_c} ℃`, 'cpu-temp', `負荷 ${pct(data.cpu.usage_percent)} / 電源状態 ${data.battery?.plugged ? '接続' : 'バッテリー'} / コア数 ${data.cpu.physical_cores ?? '—'}`),
        detail('バッテリー', data.battery ? `${data.battery.percent}%${data.battery.plugged ? ' / 電源接続' : ''}` : '非搭載 / 取得非対応', 'battery', data.battery ? `残量 ${data.battery.percent}% / 充電状態 ${data.battery.plugged ? '接続中' : '電池使用中'}` : 'この環境ではバッテリー情報を取得できません。'),
        detail('ローカル処理', oldLocal, 'local-time-value', `直近のローカル応答時間 ${oldLocal}`), detail('クラウドAPI', oldCloud, 'cloud-time-value', `直近のクラウド応答時間 ${oldCloud}`)
      );
      if (data.gpus?.length) {
        data.gpus.forEach(gpu => {
          content.append(
            detail('GPU', gpu.name, `gpu-${gpu.name}`.replace(/[^a-z0-9-_]/gi, '-').toLowerCase(), `GPU情報 ${gpu.name} / 使用率 ${gpu.usage_percent == null ? '取得非対応' : `${gpu.usage_percent}%`} / 温度 ${gpu.temperature_c == null ? '取得非対応' : `${gpu.temperature_c} ℃`}`),
            detail('GPU使用率', gpu.usage_percent == null ? '取得非対応' : `${gpu.usage_percent}%`, 'gpu-usage', gpu.usage_percent == null ? 'GPU利用率はこの環境で取得できません。' : `GPU使用率 ${gpu.usage_percent}% / VRAM ${gpu.vram_used_mb == null || gpu.vram_total_mb == null ? '取得非対応' : `${gpu.vram_used_mb} / ${gpu.vram_total_mb} MB`}`),
            detail('VRAM', gpu.vram_used_mb == null || gpu.vram_total_mb == null ? '取得非対応' : `${gpu.vram_used_mb} / ${gpu.vram_total_mb} MB`, 'gpu-vram', gpu.vram_used_mb == null || gpu.vram_total_mb == null ? 'VRAM情報は非対応です。' : `使用中 ${gpu.vram_used_mb} MB / 合計 ${gpu.vram_total_mb} MB`),
            detail('GPU温度', gpu.temperature_c == null ? '取得非対応' : `${gpu.temperature_c} ℃`, 'gpu-temp', gpu.temperature_c == null ? '温度情報は取得できません。' : `GPU温度 ${gpu.temperature_c} ℃`)
          );
        });
      } else content.append(detail('GPU / VRAM / 温度', '取得非対応', 'gpu-none', 'この PC では GPU の詳細情報が取得できません。'));
      const foot = document.createElement('p'); foot.className = 'monitor-footnote';
      foot.textContent = `実測 · ${data.hostname}（バックエンドPC）\n2.5秒ごと更新 · 温度/GPUは対応機のみ`;
      content.append(foot);
      content.scrollTop = scrollPosition;
      bindMonitorRows();
      $('monitor-status').textContent = 'LIVE'; $('monitor-status').classList.add('live');
    } catch (error) {
      if (monitorDisposed) return;
      $('monitor-status').textContent = '取得停止'; $('monitor-status').classList.remove('live');
      const content = $('system-monitor-content');
      content.textContent = `現在のPC情報を取得できません。${error.message}`;
      // 応答時間の更新先は、モニター障害時にも残す。
      content.append(detail('ローカル処理', '未計測', 'local-time-value'), detail('クラウドAPI', '未使用', 'cloud-time-value'));
      bindMonitorRows();
    } finally {
      if (!monitorDisposed) {
        const delay = document.hidden ? 15000 : 6000;
        monitorTimer = setTimeout(refreshMonitor, delay);
      }
    }
  }

  function setupPanels() {
    window.prepareWorkbenchPanels?.();
    const dock = $('info-panel-dock');
    const location = document.querySelector('[data-info-panel="location"]');
    dock.append(location);
    const mapBody = $('map-panel-content');
    document.querySelectorAll('.geo-maps-wrap, .geo-map-nav').forEach(node => mapBody.append(node));
    const panels = [...document.querySelectorAll('[data-info-panel]')];
    const pinned = new Set();
    const manual = new Set();
    const leftDock = $('left-panel-dock');
    // 結果本文は保存せず、ユーザーが選んだ配置だけを記憶する。
    function remember() {
      savePreference('jarvis-panel-layout-v1', JSON.stringify(panels.map(panel => ({
        key: panel.dataset.infoPanel, side: panel.parentElement === leftDock ? 'left' : 'right',
        open: !panel.hidden && (manual.has(panel.dataset.infoPanel) || pinned.has(panel.dataset.infoPanel)),
        pinned: pinned.has(panel.dataset.infoPanel)
      }))));
    }
    function render() {
      const anyOpen = panels.some(panel => !panel.hidden && panel.parentElement === dock);
      $('panels-empty').hidden = anyOpen;
      document.querySelector('.hud-right').classList.toggle('has-panels', anyOpen);
      panels.forEach(panel => {
        const key = panel.dataset.infoPanel;
        document.querySelector(`[data-open-panel="${key}"]`).setAttribute('aria-expanded', String(!panel.hidden));
        panel.querySelector('[data-pin]').setAttribute('aria-pressed', String(pinned.has(key)));
      });
    }
    function close(key, restoreFocus = false) {
      const panel = panels.find(item => item.dataset.infoPanel === key);
      if (!panel) return;
      pinned.delete(key); manual.delete(key); panel.hidden = true; window.workbench?.suppress(key); render();
      remember();
      if (restoreFocus) document.querySelector(`[data-open-panel="${key}"]`).focus({ preventScroll: true });
    }
    function open(key, options = {}) {
      const target = panels.find(item => item.dataset.infoPanel === key);
      if (!target) return;
      if (innerWidth <= 900 && target.parentElement === leftDock) dock.append(target);
      if (options.source !== 'auto') manual.add(key);
      panels.forEach(panel => { if (panel !== target && !pinned.has(panel.dataset.infoPanel) && !manual.has(panel.dataset.infoPanel)) panel.hidden = true; });
      target.hidden = false; render(); if (options.source !== 'auto') remember();
      // サイドパネル内だけをスクロール。ページや入力欄を動かさない。
      const isLeft = target.parentElement === leftDock;
      const side = isLeft ? document.querySelector('.monitor-column') : document.querySelector('.hud-right');
      if (options.source !== 'auto') {
        const offset = isLeft ? target.getBoundingClientRect().top - side.getBoundingClientRect().top + side.scrollTop - (document.querySelector('.ai-core-panel')?.offsetHeight || 0) - 8 : target.offsetTop - target.parentElement.offsetTop;
        side.scrollTop = Math.max(0, offset);
      }
    }
    panels.forEach(panel => {
      const tools = document.createElement('div'); tools.className = 'panel-tools';
      const pin = document.createElement('button'); pin.type = 'button'; pin.dataset.pin = ''; pin.textContent = 'ピン'; pin.setAttribute('aria-pressed', 'false');
      pin.setAttribute('aria-label', `${panel.querySelector('strong').textContent}をピン留め`);
      pin.addEventListener('click', () => { const key = panel.dataset.infoPanel; pinned.has(key) ? pinned.delete(key) : pinned.add(key); render(); remember(); });
      const exit = document.createElement('button'); exit.type = 'button'; exit.textContent = '×';
      exit.setAttribute('aria-label', `${panel.querySelector('strong').textContent}パネルを閉じる`);
      exit.addEventListener('click', () => close(panel.dataset.infoPanel, true));
      const side = document.createElement('button'); side.type = 'button'; side.textContent = '⇄';
      side.setAttribute('aria-label', 'パネルを左右に移動');
      side.addEventListener('click', () => { manual.add(panel.dataset.infoPanel); (panel.parentElement === leftDock ? dock : leftDock).append(panel); render(); remember(); });
      tools.append(side, pin, exit); panel.querySelector('.panel-header').append(tools);
    });
    document.querySelectorAll('[data-open-panel]').forEach(button => button.addEventListener('click', () => {
      const panel = panels.find(item => item.dataset.infoPanel === button.dataset.openPanel);
      if (!panel.hidden) close(button.dataset.openPanel); else open(button.dataset.openPanel);
    }));
    $('close-all-panels').addEventListener('click', () => { pinned.clear(); manual.clear(); window.workbench?.suppress('*'); panels.forEach(panel => { panel.hidden = true; }); render(); remember(); });
    document.querySelectorAll('[data-panel-prompt]').forEach(button => button.addEventListener('click', () => {
      $('message').value = button.dataset.panelPrompt; $('message').focus({ preventScroll: true });
    }));
    window.dashboardPanels = {
      open, close, isManual: key => manual.has(key), closeAll: () => $('close-all-panels').click(),
      captureLayout: () => panels.map(panel => ({key:panel.dataset.infoPanel, side:panel.parentElement===leftDock?'left':'right',open:!panel.hidden,pinned:pinned.has(panel.dataset.infoPanel)})),
      restoreLayout: saved => {
        if (!Array.isArray(saved)) return;
        manual.clear(); pinned.clear(); panels.forEach(panel => {panel.hidden=true;});
        for (const item of saved.slice(0,panels.length)) {
          const panel=panels.find(panel=>panel.dataset.infoPanel===item?.key); if(!panel)continue;
          (item.side==='left'&&innerWidth>900?leftDock:dock).append(panel);
          panel.hidden=item.open!==true;
          if(item.open===true)manual.add(item.key);
          if(item.open===true&&item.pinned===true)pinned.add(item.key);
        }
        render();remember();
      }
    };
    window.addEventListener('resize', () => { if (innerWidth <= 900) panels.filter(panel => !panel.hidden && panel.parentElement === leftDock).forEach(panel => dock.append(panel)); render(); });
    try {
      const saved = JSON.parse(readPreference('jarvis-panel-layout-v1') || 'null');
      if (Array.isArray(saved)) for (const item of saved.slice(0, panels.length)) {
        const panel = panels.find(panel => panel.dataset.infoPanel === item?.key);
        if (!panel) continue;
        if (item.side === 'left' && innerWidth > 900) leftDock.append(panel);
        else if (item.side === 'right' || innerWidth <= 900) dock.append(panel);
        panel.hidden = item.open !== true;
        if (item.open === true) manual.add(item.key);
        if (item.pinned === true && item.open === true) pinned.add(item.key);
      }
    } catch {}
    render();
    // 天気は既存の実データ表示と同期。チャット文の推測やサンプル値は使わない。
    const sources = ['geo-location-label', 'geo-weather', 'geo-temp', 'geo-humidity', 'geo-wind', 'geo-hi-lo', 'geo-rain', 'geo-observed-at', 'geo-provider'];
    function weather() {
      const box = $('weather-summary'); if (box.dataset.toolResult) return; box.replaceChildren();
      const place = document.createElement('div'); place.className = 'weather-place'; place.textContent = $('geo-location-label').textContent;
      const temp = document.createElement('div'); temp.className = 'weather-temp'; temp.textContent = $('geo-temp').textContent;
      const extra = document.createElement('div'); extra.className = 'weather-extra';
      extra.textContent = `${$('geo-weather').textContent}\n最高 / 最低 ${$('geo-hi-lo').textContent}\n降水確率 ${$('geo-rain').textContent}\n湿度 ${$('geo-humidity').textContent}\n風 ${$('geo-wind').textContent}\n更新 ${$('geo-observed-at').textContent}\n${$('geo-provider').textContent}`;
      const hint = document.createElement('p'); hint.className = 'core-caption'; hint.textContent = '地域や取得方法は「現在地」パネルで変更できます。';
      box.append(place, temp, extra, hint);
    }
    const observer = new MutationObserver(weather);
    sources.forEach(id => observer.observe($(id), { childList: true, subtree: true, characterData: true }));
    weather();
  }

  function setupWorkspace() {
    const drawer = $('workspace-drawer'); let returnFocus;
    const behind = () => [...document.querySelector('.jarvis-shell').children].filter(node => node !== drawer);
    function close() { drawer.hidden = true; behind().forEach(node => { node.inert = false; }); $('open-workspace').setAttribute('aria-expanded', 'false'); returnFocus?.focus({ preventScroll: true }); }
    $('open-workspace').addEventListener('click', () => {
      returnFocus = document.activeElement; drawer.hidden = false; behind().forEach(node => { node.inert = true; });
      $('open-workspace').setAttribute('aria-expanded', 'true'); $('close-workspace').focus({ preventScroll: true });
    });
    $('close-workspace').addEventListener('click', close);
    drawer.addEventListener('keydown', event => {
      if (event.key === 'Escape') close();
      if (event.key !== 'Tab') return;
      const focusable = [...drawer.querySelectorAll('button,input,textarea,select,a[href]')].filter(node => !node.disabled && node.getClientRects().length);
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    });
  }

  async function releaseMic() {
    if (meterFrame) cancelAnimationFrame(meterFrame);
    meterFrame = null;
    micStream?.getTracks().forEach(track => track.stop()); micStream = null;
    if (audioContext) { await audioContext.close().catch(() => {}); audioContext = null; }
    window.aiCore.setAudioLevel(0); window.aiSensory?.signal('idle');
  }
  function setupVoice() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const button = $('voice-start');
    const support = $('voice-support');
    const speak = $('speak-enabled');
    speak.checked = readPreference('jarvis-speech-enabled-v1') === 'true';
    const stop = document.createElement('button'); stop.type = 'button'; stop.id = 'speech-stop';
    stop.textContent = '読み上げ停止'; stop.disabled = true; stop.title = 'Escapeキーでも停止';
    button.parentElement.append(stop); stop.addEventListener('click', stopSpeech);
    document.addEventListener('keydown', event => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        if (!$('workspace-drawer').hidden) return;
        event.preventDefault(); $('message').focus({ preventScroll: true });
      }
      if (event.key === 'Escape' && currentUtterance) { event.preventDefault(); stopSpeech(); }
    });
    $('message').title = 'Ctrl + Kで入力欄へ移動 / Shift + Enterで改行';
    speak.addEventListener('change', () => savePreference('jarvis-speech-enabled-v1', String(speak.checked)));
    if (!('speechSynthesis' in window)) { $('speak-enabled').disabled = true; $('speak-enabled').title = 'このブラウザーは読み上げに非対応です'; }
    $('speak-enabled').addEventListener('change', () => { if (!$('speak-enabled').checked) stopSpeech(); });
    if (!SpeechRecognition || !navigator.mediaDevices?.getUserMedia || !window.isSecureContext) {
      button.disabled = true; support.textContent = '音声入力は対応ブラウザーのHTTPS / localhostで利用できます。'; return;
    }
    support.textContent = 'ブラウザー音声認識（音声が外部送信される場合があります）。入力欄へ反映後に送信。';
    let voiceVersion = 0;
    button.addEventListener('click', async () => {
      if (listening) { recognition?.stop(); await releaseMic(); return; }
      if ($('send-btn').disabled) return;
      activityVersion++; const version = ++voiceVersion;
      stopSpeech();
      button.disabled = true;
      window.workbench?.recognition('start');
      try {
        micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        if (version !== voiceVersion) { await releaseMic(); return; }
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const analyser = audioContext.createAnalyser(); analyser.fftSize = 512;
        audioContext.createMediaStreamSource(micStream).connect(analyser);
        const samples = new Uint8Array(analyser.fftSize);
        function meter() {
          analyser.getByteTimeDomainData(samples);
          const rms = Math.sqrt(samples.reduce((sum, value) => sum + ((value - 128) / 128) ** 2, 0) / samples.length);
          window.aiCore.setAudioLevel(Math.min(1, rms * 7)); window.aiSensory?.frame(samples,rms);
          meterFrame = requestAnimationFrame(meter);
        }
        recognition = new SpeechRecognition(); recognition.lang = 'ja-JP'; recognition.interimResults = true;
        const prefix = $('message').value;
        recognition.onstart = () => { listening = true; window.aiSensory?.signal('microphone'); window.aiSensory?.transcript({text:'',final:false}); state('listening'); button.textContent = '音声入力を停止'; button.disabled = false; meter(); };
        recognition.onspeechend = () => { if (listening) state('recognizing'); };
        recognition.onresult = event => {
          if ($('send-btn').disabled) return;
          let text = ''; for (let i = 0; i < event.results.length; i++) text += event.results[i][0].transcript;
          $('message').value = prefix + text; $('message').dispatchEvent(new Event('input',{bubbles:true}));
          window.aiSensory?.transcript({text,final:!!event.results[event.results.length-1].isFinal});
          if (event.results[event.results.length - 1].isFinal) { window.workbench?.recognition('end'); state('recognizing'); }
        };
        let failed = false;
        recognition.onerror = event => { window.workbench?.recognition('error'); failed = true; state('error'); support.textContent = `音声入力を利用できません: ${event.error}`; };
        recognition.onend = async () => {
          listening = false; button.textContent = '音声入力'; button.disabled = false; await releaseMic();
          if (!failed && !$('send-btn').disabled) state('idle');
        };
        recognition.start();
      } catch (error) {
        listening = false; button.disabled = false; await releaseMic(); state('error');
        support.textContent = `マイクを利用できません: ${error.message}`;
      }
    });
    window.addEventListener('pagehide', () => { voiceVersion++; recognition?.abort(); releaseMic(); window.speechSynthesis?.cancel(); });
  }

  window.initDashboard = () => {
    // 最初の応答までにも処理時間の表示先を確保する。
    const content = $('system-monitor-content');
    content.append(detail('ローカル処理', '未計測', 'local-time-value'), detail('クラウドAPI', '未使用', 'cloud-time-value'));
    bindMonitorRows();
    setupPanels(); setupWorkspace(); setupVoice(); refreshMonitor();
  };
})();

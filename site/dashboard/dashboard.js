/* UIの状態とパネルを管理。ツール実行結果からのカード自動連携は後で接続する。 */
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
        utterance.lang = 'ja-JP';
        utterance.onstart = () => { window.workbench?.speech('start', speechRequest); if (version === activityVersion) state('responding'); };
        utterance.onend = () => { window.workbench?.speech('end', speechRequest); if (version === activityVersion) { currentUtterance = null; state('idle'); } };
        utterance.onerror = event => { if (version === activityVersion && event.error !== 'canceled' && event.error !== 'interrupted') state('error'); };
        window.workbench?.speech('queued', speechRequest);
        currentUtterance = utterance;
        window.speechSynthesis.speak(utterance);
      } else laterIdle(1100);
    }
  };

  window.dashboardRequest = async payload => {
    begin();
    window.workbench?.begin(payload);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 240000);
    try {
      const response = await fetch('/chat', {
        method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
        body: JSON.stringify(payload), signal: controller.signal
      });
      if (!response.headers.get('content-type')?.includes('text/event-stream')) return await response.json();
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
        if (chunk.done) break;
      }
      if (!result) throw new Error('サーバーから最終結果を受信できませんでした');
      return result;
    } catch (error) { window.workbench?.fail(); throw error; } finally { clearTimeout(timer); }
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
  function detail(label, value, id) {
    const row = document.createElement('div'); row.className = 'monitor-detail';
    const name = document.createElement('span'); name.textContent = label;
    const content = document.createElement('strong'); content.textContent = value; if (id) content.id = id;
    row.append(name, content); return row;
  }
  const gb = value => typeof value === 'number' ? `${(value / 1024 ** 3).toFixed(1)} GB` : '取得不可';
  const pct = value => typeof value === 'number' ? `${value.toFixed(1)}%` : '計測中';
  const speed = value => typeof value === 'number' ? value >= 1024 ** 2 ? `${(value / 1024 ** 2).toFixed(1)} MB/s` : `${(value / 1024).toFixed(1)} KB/s` : '計測中';
  let monitorTimer;
  async function refreshMonitor() {
    if (document.hidden) { monitorTimer = setTimeout(refreshMonitor, 2500); return; }
    try {
      const response = await fetch('/system/metrics', { cache: 'no-store', signal: AbortSignal.timeout(7000) });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || 'PC情報の取得に失敗しました');
      const oldLocal = $('local-time-value')?.textContent || '未計測';
      const oldCloud = $('cloud-time-value')?.textContent || '未使用';
      const content = $('system-monitor-content'); const scrollPosition = content.scrollTop; content.replaceChildren();
      content.append(
        metric('CPU', pct(data.cpu.usage_percent), `${data.cpu.physical_cores ?? '—'} コア / ${data.cpu.logical_cores ?? '—'} スレッド`, data.cpu.usage_percent),
        metric('RAM', pct(data.memory.usage_percent), `${gb(data.memory.used_bytes)} / ${gb(data.memory.total_bytes)}`, data.memory.usage_percent),
        metric('DISK', pct(data.disk.usage_percent), `${data.disk.path} 空き ${gb(data.disk.free_bytes)} / ${gb(data.disk.total_bytes)}`, data.disk.usage_percent),
        detail('通信速度', `↑ ${speed(data.network.send_bytes_sec)} / ↓ ${speed(data.network.receive_bytes_sec)}`),
        detail('累計送受信', `↑ ${gb(data.network.sent_bytes)} / ↓ ${gb(data.network.received_bytes)}`),
        detail('PC稼働時間', `${Math.floor(data.uptime_sec / 86400)}日 ${Math.floor(data.uptime_sec / 3600) % 24}時間 ${Math.floor(data.uptime_sec / 60) % 60}分`),
        detail('CPU温度', data.cpu.temperature_c == null ? '取得非対応' : `${data.cpu.temperature_c} ℃`),
        detail('バッテリー', data.battery ? `${data.battery.percent}%${data.battery.plugged ? ' / 電源接続' : ''}` : '非搭載 / 取得非対応'),
        detail('ローカル処理', oldLocal, 'local-time-value'), detail('クラウドAPI', oldCloud, 'cloud-time-value')
      );
      if (data.gpus?.length) {
        data.gpus.forEach(gpu => {
          content.append(detail('GPU', gpu.name), detail('GPU使用率', gpu.usage_percent == null ? '取得非対応' : `${gpu.usage_percent}%`),
            detail('VRAM', gpu.vram_used_mb == null || gpu.vram_total_mb == null ? '取得非対応' : `${gpu.vram_used_mb} / ${gpu.vram_total_mb} MB`),
            detail('GPU温度', gpu.temperature_c == null ? '取得非対応' : `${gpu.temperature_c} ℃`));
        });
      } else content.append(detail('GPU / VRAM / 温度', '取得非対応'));
      const foot = document.createElement('p'); foot.className = 'monitor-footnote';
      foot.textContent = `実測 · ${data.hostname}（バックエンドPC）\n2.5秒ごと更新 · 温度/GPUは対応機のみ`;
      content.append(foot);
      content.scrollTop = scrollPosition;
      $('monitor-status').textContent = 'LIVE'; $('monitor-status').classList.add('live');
    } catch (error) {
      $('monitor-status').textContent = '取得停止'; $('monitor-status').classList.remove('live');
      $('system-monitor-content').textContent = `現在のPC情報を取得できません。${error.message}`;
      // 応答時間の更新先は、モニター障害時にも残す。
      $('system-monitor-content').append(detail('ローカル処理', '未計測', 'local-time-value'), detail('クラウドAPI', '未使用', 'cloud-time-value'));
    } finally { monitorTimer = setTimeout(refreshMonitor, 2500); }
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
      if (restoreFocus) document.querySelector(`[data-open-panel="${key}"]`).focus({ preventScroll: true });
    }
    function open(key, options = {}) {
      const target = panels.find(item => item.dataset.infoPanel === key);
      if (!target) return;
      if (innerWidth <= 900 && target.parentElement === leftDock) dock.append(target);
      if (options.source !== 'auto') manual.add(key);
      panels.forEach(panel => { if (panel !== target && !pinned.has(panel.dataset.infoPanel) && !manual.has(panel.dataset.infoPanel)) panel.hidden = true; });
      target.hidden = false; render();
      // サイドパネル内だけをスクロール。ページや入力欄を動かさない。
      const side = target.parentElement === leftDock ? leftDock : document.querySelector('.hud-right');
      if (options.source !== 'auto') side.scrollTop = Math.max(0, target.offsetTop - target.parentElement.offsetTop);
    }
    panels.forEach(panel => {
      const tools = document.createElement('div'); tools.className = 'panel-tools';
      const pin = document.createElement('button'); pin.type = 'button'; pin.dataset.pin = ''; pin.textContent = 'ピン'; pin.setAttribute('aria-pressed', 'false');
      pin.setAttribute('aria-label', `${panel.querySelector('strong').textContent}をピン留め`);
      pin.addEventListener('click', () => { const key = panel.dataset.infoPanel; pinned.has(key) ? pinned.delete(key) : pinned.add(key); render(); });
      const exit = document.createElement('button'); exit.type = 'button'; exit.textContent = '×';
      exit.setAttribute('aria-label', `${panel.querySelector('strong').textContent}パネルを閉じる`);
      exit.addEventListener('click', () => close(panel.dataset.infoPanel, true));
      const side = document.createElement('button'); side.type = 'button'; side.textContent = '⇄';
      side.setAttribute('aria-label', 'パネルを左右に移動');
      side.addEventListener('click', () => { manual.add(panel.dataset.infoPanel); (panel.parentElement === leftDock ? dock : leftDock).append(panel); render(); });
      tools.append(side, pin, exit); panel.querySelector('.panel-header').append(tools);
    });
    document.querySelectorAll('[data-open-panel]').forEach(button => button.addEventListener('click', () => {
      const panel = panels.find(item => item.dataset.infoPanel === button.dataset.openPanel);
      if (!panel.hidden) close(button.dataset.openPanel); else open(button.dataset.openPanel);
    }));
    $('close-all-panels').addEventListener('click', () => { pinned.clear(); manual.clear(); window.workbench?.suppress('*'); panels.forEach(panel => { panel.hidden = true; }); render(); });
    document.querySelectorAll('[data-panel-prompt]').forEach(button => button.addEventListener('click', () => {
      $('message').value = button.dataset.panelPrompt; $('message').focus({ preventScroll: true });
    }));
    window.dashboardPanels = { open, close, isManual: key => manual.has(key), closeAll: () => $('close-all-panels').click() };
    window.addEventListener('resize', () => { if (innerWidth <= 900) panels.filter(panel => !panel.hidden && panel.parentElement === leftDock).forEach(panel => dock.append(panel)); render(); });
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
    const behind = [...document.querySelector('.jarvis-shell').children].filter(node => node !== drawer);
    function close() { drawer.hidden = true; behind.forEach(node => { node.inert = false; }); $('open-workspace').setAttribute('aria-expanded', 'false'); returnFocus?.focus({ preventScroll: true }); }
    $('open-workspace').addEventListener('click', () => {
      returnFocus = document.activeElement; drawer.hidden = false; behind.forEach(node => { node.inert = true; });
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
    window.aiCore.setAudioLevel(0);
  }
  function setupVoice() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const button = $('voice-start');
    const support = $('voice-support');
    if (!('speechSynthesis' in window)) { $('speak-enabled').disabled = true; $('speak-enabled').title = 'このブラウザーは読み上げに非対応です'; }
    $('speak-enabled').addEventListener('change', () => { if (!$('speak-enabled').checked) { window.speechSynthesis?.cancel(); currentUtterance = null; if (!listening) state('idle'); } });
    if (!SpeechRecognition || !navigator.mediaDevices?.getUserMedia || !window.isSecureContext) {
      button.disabled = true; support.textContent = '音声入力は対応ブラウザーのHTTPS / localhostで利用できます。'; return;
    }
    support.textContent = 'ブラウザー音声認識（音声が外部送信される場合があります）。入力欄へ反映後に送信。';
    let voiceVersion = 0;
    button.addEventListener('click', async () => {
      if (listening) { recognition?.stop(); await releaseMic(); return; }
      if ($('send-btn').disabled) return;
      activityVersion++; const version = ++voiceVersion;
      window.speechSynthesis?.cancel();
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
          window.aiCore.setAudioLevel(Math.min(1, rms * 7));
          meterFrame = requestAnimationFrame(meter);
        }
        recognition = new SpeechRecognition(); recognition.lang = 'ja-JP'; recognition.interimResults = true;
        const prefix = $('message').value;
        recognition.onstart = () => { listening = true; state('listening'); button.textContent = '音声入力を停止'; button.disabled = false; meter(); };
        recognition.onspeechend = () => { if (listening) state('recognizing'); };
        recognition.onresult = event => {
          if ($('send-btn').disabled) return;
          let text = ''; for (let i = 0; i < event.results.length; i++) text += event.results[i][0].transcript;
          $('message').value = prefix + text;
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
    $('system-monitor-content').append(detail('ローカル処理', '未計測', 'local-time-value'), detail('クラウドAPI', '未使用', 'cloud-time-value'));
    setupPanels(); setupWorkspace(); setupVoice(); refreshMonitor();
  };
})();

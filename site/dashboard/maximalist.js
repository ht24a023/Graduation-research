/* 情報を選んで削るためのMAX HUD。数値とグラフは実際の取得結果だけを使う。 */
(() => {
 'use strict';
 const $=id=>document.getElementById(id);
 const make=(tag,text,cls)=>{const el=document.createElement(tag);if(text!=null)el.textContent=text;if(cls)el.className=cls;return el;};
 const modules={telemetry:'上部テレメトリー',hardware:'PC・プロセス情報',cores:'CPUコア別負荷',trends:'実測トレンド',environment:'現在地・天気・地図',pipeline:'AI処理パイプライン',tools:'機能マトリクス',session:'会話・文書・音声',worldtime:'世界時計',processes:'メモリ使用量上位プロセス',capacity:'容量・通信状況',activity:'最近の処理',footer:'システムステータスバー'};
 const permanent=new Set(['hardware','cores','processes','capacity','trends']);
 let mode='max',hidden=new Set(),samples=[],latest=null,seen=new Set(),recent=[],counts={requests:0,local:0,cloud:0,tools:0,unknown:0,failed:0},latencies=[],metricsReceivedAt=0,sessionVersion=0;
 function store(){try{localStorage.setItem('jarvis-hud-mode-v1',mode);localStorage.setItem('jarvis-hud-hidden-v1',JSON.stringify([...hidden]));}catch{}}
 const seconds=v=>num(v)?v.toFixed(3)+' s':'未計測';
 const num=v=>typeof v==='number'&&Number.isFinite(v);
 const pct=v=>num(v)?v.toFixed(1)+'%':'—';
 const gb=v=>num(v)?(v/1073741824).toFixed(1)+' GB':'—';
 const mb=v=>num(v)?(v/1048576).toFixed(1)+' MB':'—';
 const rate=v=>num(v)?v>=1048576?(v/1048576).toFixed(1)+' MB/s':(v/1024).toFixed(1)+' KB/s':'計測中';
 function text(id,value){const el=$(id);if(!el)return;const next=String(value??'—');if(el.textContent!==next)el.textContent=next;if(el.matches('.hud-cell strong'))el.title=next;}
 function cell(label,id){const el=make('div',null,'hud-cell');el.append(make('span',label));const strong=make('strong','—');strong.id=id;el.append(strong);return el;}
 function block(key,title,subtitle=''){
  const el=make('section',null,'hud-module');el.dataset.hudModule=key;
  const head=make('div',null,'hud-module-head');head.append(make('strong',title),make('small',subtitle));
  const close=make('button','×');close.type='button';close.setAttribute('aria-label',modules[key]+'を非表示');close.addEventListener('click',()=>{hidden.add(key);apply();});if(permanent.has(key)){el.dataset.permanent='true';head.append(make('small','常時監視','hud-permanent-label'));}else head.append(close);el.append(head);return el;
 }
 function apply(){
  document.body.classList.toggle('max-hud',mode==='max');
  document.querySelectorAll('[data-hud-module]').forEach(el=>el.hidden=!permanent.has(el.dataset.hudModule)&&hidden.has(el.dataset.hudModule));
  document.querySelectorAll('[data-hud-option]').forEach(el=>{el.checked=permanent.has(el.dataset.hudOption)||!hidden.has(el.dataset.hudOption);el.disabled=permanent.has(el.dataset.hudOption);});
  $('hud-mode-toggle').textContent=mode==='max'?'MAX HUD':'FOCUS';$('hud-mode-toggle').setAttribute('aria-pressed',String(mode==='max'));
  $('hud-density-select').value=mode;store();
 }
 function miniPlot(id,values,color='#70e0ed',ceiling=100){
  const box=$(id);if(!box)return;box.replaceChildren();
  if(!values.length){box.append(make('span','実測データを待機中','hud-empty'));return;}
  const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 260 48');svg.setAttribute('aria-label','取得した実測値の推移');
  const max=ceiling||Math.max(...values,1),points=values.map((value,i)=>`${i/Math.max(1,values.length-1)*258},${44-Math.min(value/max,1)*39}`);
  const area=document.createElementNS(ns,'polygon');area.setAttribute('points','0,48 '+points.join(' ')+' 258,48');area.setAttribute('fill',color);area.setAttribute('opacity','.08');svg.append(area);
  const line=document.createElementNS(ns,'polyline');line.setAttribute('points',points.join(' '));line.setAttribute('fill','none');line.setAttribute('stroke',color);line.setAttribute('stroke-width','1.6');svg.append(line);
  const end=document.createElementNS(ns,'circle');const xy=points[points.length-1].split(',');end.setAttribute('cx',xy[0]);end.setAttribute('cy',xy[1]);end.setAttribute('r','2');end.setAttribute('fill',color);svg.append(end);box.append(svg);
 }
 function panelButton(key,label){const button=make('button',label,'hud-tool-button');button.type='button';button.addEventListener('click',()=>{const original=document.querySelector(`[data-open-panel="${key}"]`);original?.click();});return button;}
 function build(){
  const toggle=make('button','MAX HUD');toggle.title='情報量を切替：MAX HUD / FOCUS';toggle.id='hud-mode-toggle';toggle.type='button';toggle.addEventListener('click',()=>{mode=mode==='max'?'focus':'max';apply();});document.querySelector('.dashboard-nav').prepend(toggle);
  const top=block('telemetry','LIVE TELEMETRY','BACKEND PC / REAL DATA');top.classList.add('hud-telemetry');
  const cells=make('div',null,'hud-telemetry-values');for(const [label,id]of[['CPU LOAD','hud-cpu'],['MEMORY','hud-ram'],['DISK','hud-disk'],['NETWORK ↓','hud-rx'],['NETWORK ↑','hud-tx'],['GPU / VRAM','hud-gpu'],['POWER','hud-power']])cells.append(cell(label,id));top.append(cells);document.querySelector('.first-screen').before(top);
  const left=make('div',null,'hud-left-overview');document.querySelector('.monitor-column').append(left);
  const hardware=block('hardware','HOST / MACHINE','SYSTEM IDENTITY');const hardwareGrid=make('div',null,'hud-info-grid');
  for(const [label,id]of[['HOST','hud-host'],['OS','hud-os'],['CPU','hud-cpu-spec'],['REPORTED CLOCK','hud-frequency'],['SERVER RSS','hud-server-rss'],['THREADS / PROCESSES','hud-processes'],['UPTIME','hud-uptime'],['I/O READ · WRITE','hud-disk-io'],['ADAPTERS / LINK','hud-link-info'],['CPU / GPU TEMP','hud-thermals']])hardwareGrid.append(cell(label,id));hardware.append(hardwareGrid);left.append(hardware);
  const cores=block('cores','CPU CORE MATRIX','LOGICAL PROCESSORS');const coregrid=make('div',null,'hud-core-grid');coregrid.id='hud-core-grid';cores.append(coregrid);left.append(cores);
  const processes=block('processes','MEMORY / PROCESSES','TOP RSS · READ ONLY');const processList=make('div','実測データを待機中','hud-process-list');processList.id='hud-process-list';processes.append(processList);left.append(processes);
  const capacity=block('capacity','CAPACITY / NETWORK','AVAILABLE RESOURCES');const capacityGrid=make('div',null,'hud-info-grid');for(const[label,id]of[['RAM AVAILABLE','hud-ram-free'],['DISK FREE','hud-disk-free'],['SWAP','hud-swap'],['NETWORK ERRORS','hud-net-errors'],['DROPPED PACKETS','hud-net-drops'],['SERVER UPTIME','hud-server-uptime']])capacityGrid.append(cell(label,id));capacity.append(capacityGrid);const alerts=make('div','容量と通信の状態を確認中','hud-health-summary');alerts.id='hud-health';alerts.setAttribute('role','status');capacity.append(alerts);left.append(capacity);
  const trends=block('trends','RESOURCE TIMELINE','LIVE SAMPLES');for(const [label,id]of[['CPU','hud-cpu-plot'],['RAM','hud-ram-plot'],['TRAFFIC','hud-net-plot']]){const row=make('div',null,'hud-plot-row');row.append(make('span',label));const graph=make('div');graph.id=id;row.append(graph);trends.append(row);}left.append(trends);
  const right=make('div',null,'hud-right-overview');right.id='hud-right-overview';$('info-panel-dock').before(right);
  const environment=block('environment','GEO / ENVIRONMENT','LOCATION SOURCE SHOWN');
  environment.innerHTML+='<div class="hud-map"><svg id="hud-world-map" viewBox="0 0 960 460" aria-label="既存の地図データ"></svg><span class="hud-map-caption">WORLD / POSITION CONTEXT</span></div><div id="hud-place" class="hud-place">位置情報を取得中</div><div id="hud-location-source" class="hud-sub">—</div><div class="hud-environment-values"><strong id="hud-weather-temp">—</strong><span id="hud-weather-summary">—</span></div><div id="hud-weather-extra" class="hud-sub">—</div>';
  // innerHTMLで作ったヘッダーのイベントを張り直す。
  environment.querySelector('.hud-module-head button').addEventListener('click',()=>{hidden.add('environment');apply();});right.append(environment);
  const pipeline=block('pipeline','NEURAL ROUTING','ACTUAL EXECUTION STATE');const nodes=make('div',null,'hud-pipeline');
  for(const [key,label]of[['intent','INTENT'],['tool','TOOLS'],['local_llm','LOCAL'],['cloud_llm','CLOUD'],['output','OUTPUT']]){const n=make('div',label);n.dataset.stage=key;nodes.append(n);}pipeline.append(nodes);const stage=make('p','待機中','hud-stage-label');stage.id='hud-active-stage';pipeline.append(stage);right.append(pipeline);
  const tools=block('tools','FUNCTION MATRIX','SELECT TO EXPAND');const toolgrid=make('div',null,'hud-tool-grid');
  for(const [key,label]of[['weather','01 WEATHER'],['map','02 MAP / ROUTE'],['translate','03 TRANSLATE'],['document','04 DOCUMENTS'],['search','05 WEB SEARCH'],['youtube','06 YOUTUBE'],['qr','07 QR CODE'],['performance','08 PERFORMANCE']])toolgrid.append(panelButton(key,label));tools.append(toolgrid);right.append(tools);
  const session=block('session','SESSION / WORKSPACE','LIVE CONTEXT');const sessiongrid=make('div',null,'hud-info-grid');for(const [label,id]of[['REQUESTS','hud-request-count'],['LOCAL / CLOUD / TOOL','hud-route-count'],['DOCUMENTS','hud-document-count'],['MODEL','hud-model'],['MIC / AUDIO','hud-audio'],['CONNECTION','hud-connection']])sessiongrid.append(cell(label,id));session.append(sessiongrid);const responseStats=make('div',null,'hud-response-stats');responseStats.append(cell('SERVER LAST','hud-latency-last'),cell('SERVER MEDIAN','hud-latency-median'),cell('FAILED','hud-failed-count'));session.append(responseStats);const latencyPlot=make('div',null,'hud-latency-plot');latencyPlot.id='hud-latency-plot';session.append(latencyPlot);right.append(session);
  const world=block('worldtime','CHRONOMETRY','BACKEND CLOCK DERIVED');const worldgrid=make('div',null,'hud-world-clocks');for(const [key,label]of[['utc','UTC'],['tokyo','TOKYO'],['london','LONDON'],['newyork','NEW YORK']])worldgrid.append(cell(label,'hud-clock-'+key));world.append(worldgrid);right.append(world);
  const activity=block('activity','EXECUTION FEED','CURRENT SESSION');const feed=make('div','処理を実行すると、実際の履歴が表示されます。','hud-feed');feed.id='hud-feed';activity.append(feed);right.append(activity);
  const mission=make('div',null,'hud-mission-bar');mission.innerHTML='<span><i></i> CONVERSATION / PRIMARY CHANNEL</span><strong id="hud-message-info">READY FOR INPUT</strong>';document.querySelector('.chat-body').prepend(mission);
  const footer=block('footer','SYSTEM BUS','');footer.classList.add('hud-footer');footer.innerHTML='<span id="hud-sample-state">TELEMETRY / WAITING</span><span id="hud-bridge">NOTIFICATIONS / OFF</span><span id="hud-viewport"></span><span id="hud-clock-footer">PC CLOCK / SYNCING</span><span>AI / LOCAL FIRST</span>';document.querySelector('.jarvis-shell').append(footer);
  const settings=make('section',null,'panel hud-settings');settings.innerHTML='<div class="panel-header"><strong>SETTINGS / HUD表示情報</strong></div><div class="panel-body"><label>情報量 <select id="hud-density-select"><option value="max">MAX HUD：情報を多めに表示</option><option value="focus">FOCUS：チャット中心</option></select></label><div id="hud-module-options"></div><div class="hud-settings-actions"><button type="button" id="hud-restore-all">全情報を表示</button><button type="button" id="hud-export-telemetry">実測スナップショットを保存</button></div><p id="hud-export-status" role="status">保存ファイルにはPC名・プロセス名・実測値を含みます。</p><p class="measurement-note">チェックを外すと、その枠を隠せます。数値とグラフは取得できた実データだけを表示します。</p></div>';$('workspace-drawer').append(settings);
  for(const [key,label]of Object.entries(modules)){const option=make('label');const input=make('input');input.type='checkbox';input.dataset.hudOption=key;input.checked=true;input.addEventListener('change',()=>{input.checked?hidden.delete(key):hidden.add(key);apply();});option.append(input,make('span',label+(permanent.has(key)?'（常時表示）':'')));$('hud-module-options').append(option);}
  $('hud-export-telemetry').addEventListener('click',()=>{if(!latest){text('hud-export-status','実測値の取得後に保存できます。');return;}const blob=new Blob([JSON.stringify({exported_at:new Date().toISOString(),source:'backend_pc',metrics:latest,samples,session:{...counts,server_latency_seconds:latencies}},null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const link=make('a');link.href=url;link.download='ai-telemetry-'+new Date().toISOString().replace(/[:.]/g,'-')+'.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);text('hud-export-status','実測スナップショットのダウンロードを開始しました。');});
  $('hud-restore-all').addEventListener('click',()=>{hidden.clear();mode='max';apply();});$('hud-density-select').addEventListener('change',()=>{mode=$('hud-density-select').value;apply();});
 }
 function renderMetrics(data){
  if(!data?.ok||!data.cpu||!data.memory||!data.network||!data.disk)return;
  latest=data;metricsReceivedAt=performance.now();document.body.classList.remove('hud-telemetry-stale');
  if(!samples.length||samples[samples.length-1].sampled_at!==data.sampled_at){samples.push(data);if(samples.length>32)samples.shift();}
  text('hud-cpu',pct(data.cpu.usage_percent));text('hud-ram',pct(data.memory.usage_percent));text('hud-disk',pct(data.disk.usage_percent));text('hud-rx',rate(data.network.receive_bytes_sec));text('hud-tx',rate(data.network.send_bytes_sec));
  const gpu=data.gpus?.[0];text('hud-gpu',gpu?`${pct(gpu.usage_percent)} / ${num(gpu.vram_used_mb)?Math.round(gpu.vram_used_mb)+' MB':'—'}`:'取得非対応');text('hud-power',data.battery?`${data.battery.percent}% / ${data.battery.plugged?'AC':'BATTERY'}`:'電源情報 取得不可');
  const h=data.hardware||{},p=data.process||{};text('hud-host',data.hostname);text('hud-os',[h.os,h.os_release,h.architecture].filter(Boolean).join(' / '));text('hud-cpu-spec',`${data.cpu.physical_cores??'—'} CORES / ${data.cpu.logical_cores??'—'} THREADS`);text('hud-frequency',num(h.cpu_frequency_mhz)?(h.cpu_frequency_mhz/1000).toFixed(2)+' GHz':'取得非対応');text('hud-server-rss',mb(p.rss_bytes));text('hud-processes',`${p.threads??'—'} / ${p.system_process_count??'—'}`);text('hud-uptime',`${Math.floor(data.uptime_sec/86400)}d ${Math.floor(data.uptime_sec/3600)%24}h ${Math.floor(data.uptime_sec/60)%60}m`);text('hud-disk-io',`${rate(data.disk_io?.read_bytes_sec)} / ${rate(data.disk_io?.write_bytes_sec)}`);
  text('hud-ram-free',gb(data.memory.available_bytes));text('hud-disk-free',gb(data.disk.free_bytes));text('hud-swap',num(data.swap?.usage_percent)?pct(data.swap.usage_percent):'未取得');text('hud-server-uptime',num(p.server_uptime_sec)?Math.floor(p.server_uptime_sec/60)+' min':'未取得');
  text('hud-net-errors',num(data.network.errors_in)?`${data.network.errors_in} IN / ${data.network.errors_out??'—'} OUT`:'未取得');text('hud-net-drops',num(data.network.drops_in)?`${data.network.drops_in} IN / ${data.network.drops_out??'—'} OUT`:'未取得');
  const processList=$('hud-process-list');processList.replaceChildren();for(const entry of (p.top_memory||[]).slice(0,5)){const row=make('div',null,'hud-process-row');row.append(make('span',entry.name||'名称未取得'),make('small','PID '+entry.pid),make('strong',mb(entry.rss_bytes)));processList.append(row);}if(!processList.children.length)processList.append(make('span','プロセス情報 取得不可','hud-empty'));
  const warnings=[];if(data.memory.usage_percent>=90)warnings.push('メモリ残量が少なくなっています');if(data.disk.usage_percent>=90)warnings.push('ディスク残量が少なくなっています');if(data.battery&&!data.battery.plugged&&data.battery.percent<=20)warnings.push('バッテリー残量 '+data.battery.percent+'%');text('hud-health',warnings.join(' / ')||'容量・電源にしきい値超過なし');$('hud-health').classList.toggle('has-warning',warnings.length>0);
  text('hud-link-info',`${h.active_adapters??'—'} / ${num(h.reported_link_mbps)?h.reported_link_mbps+' Mbps':'—'}`);text('hud-thermals',`${num(data.cpu.temperature_c)?data.cpu.temperature_c+'°C':'非対応'} / ${num(gpu?.temperature_c)?gpu.temperature_c+'°C':'非対応'}`);
  const grid=$('hud-core-grid');grid.replaceChildren();(data.cpu.per_core_percent||[]).forEach((value,index)=>{const core=make('div',null,'hud-core');core.style.setProperty('--load',num(value)?value/100:0);core.classList.toggle('hot',num(value)&&value>=85);core.append(make('small','C'+pad(index)),make('strong',num(value)?Math.round(value)+'%':'—'));grid.append(core);});
  miniPlot('hud-cpu-plot',samples.map(v=>v.cpu.usage_percent).filter(num));miniPlot('hud-ram-plot',samples.map(v=>v.memory.usage_percent).filter(num),'#bea8ff');miniPlot('hud-net-plot',samples.map(v=>num(v.network.receive_bytes_sec)?v.network.receive_bytes_sec+(num(v.network.send_bytes_sec)?v.network.send_bytes_sec:0):null).filter(num),'#efa96b',null);
  text('hud-sample-state',`TELEMETRY / LIVE · ${samples.length} SAMPLES · ${h.active_adapters??'—'} LINKS`);
  document.body.classList.add('hud-data-received');setTimeout(()=>document.body.classList.remove('hud-data-received'),250);
 }
 function pad(v){return String(v).padStart(2,'0');}
 function mirror(){
  if(metricsReceivedAt&&performance.now()-metricsReceivedAt>12000){document.body.classList.add('hud-telemetry-stale');text('hud-sample-state','TELEMETRY / STALE · '+Math.floor((performance.now()-metricsReceivedAt)/1000)+'s SINCE UPDATE');}
  text('hud-model',$('runtime-model')?.textContent||'—');text('hud-connection',$('runtime-connection')?.textContent||'—');
  text('hud-place',$('geo-location-label')?.textContent||'未取得');text('hud-location-source',[$('geo-provider')?.textContent,$('geo-accuracy')?.textContent].filter(Boolean).join(' · '));text('hud-weather-temp',$('geo-temp')?.textContent||'—');text('hud-weather-summary',$('geo-weather')?.textContent||'—');text('hud-weather-extra',`降水 ${$('geo-rain')?.textContent||'—'} / 湿度 ${$('geo-humidity')?.textContent||'—'} / 風 ${$('geo-wind')?.textContent||'—'}`);
  const original=$('world-map-svg');if(original?.innerHTML&&$('hud-world-map').innerHTML!==original.innerHTML)$('hud-world-map').innerHTML=original.innerHTML;
  const state=$('ai-core').dataset.state;const listening=['listening','recognizing'].includes(state);text('hud-audio',`${listening?'MIC LIVE':'MIC 待機'} / ${$('speak-enabled').checked?'READ ON':'READ OFF'}`);text('hud-active-stage',$('core-state-label').textContent);
  document.querySelectorAll('.hud-pipeline [data-stage]').forEach(el=>el.classList.toggle('is-active',({analyzing:'intent',tool:'tool',thinking:'local_llm',cloud:'cloud_llm',responding:'output'})[state]===el.dataset.stage));
  const status=$('notifications-status')?.textContent||'OFF';text('hud-bridge',status.includes('通知表示 ON')?'NOTIFICATIONS / '+status.split('/').slice(1).join('/'):'NOTIFICATIONS / OFF');
  const stamp=$('clock-time')?.getAttribute('datetime');if(stamp){const date=new Date(stamp);for(const[key,zone]of[['utc','UTC'],['tokyo','Asia/Tokyo'],['london','Europe/London'],['newyork','America/New_York']])text('hud-clock-'+key,new Intl.DateTimeFormat('en-GB',{timeZone:zone,hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(date));text('hud-clock-footer',`${$('clock-date').textContent} / ${$('clock-time').textContent}`);}
  text('hud-viewport',`VIEWPORT ${innerWidth} × ${innerHeight}`);
 }
 function record(data){
  const id=data.execution?.request_id||data.evaluation?.request_id;if(!id||seen.has(id))return;seen.add(id);counts.requests++;
  const totals=data.execution?.stage_totals||{};const cloud=data.evaluation?.api_called||totals.cloud_llm>0;const local=totals.local_llm>0;
  if(cloud)counts.cloud++;if(local)counts.local++;if(!cloud&&!local){if(totals.tool>0||Object.prototype.hasOwnProperty.call(totals,'intent'))counts.tools++;else counts.unknown++;}
  const success=window.workbench.succeeded(data);if(!success)counts.failed++;
  const elapsed=data.execution?.server_elapsed_sec;if(num(elapsed)){latencies.push(elapsed);if(latencies.length>64)latencies.shift();}
  text('hud-request-count',counts.requests);text('hud-route-count',`${counts.local} / ${counts.cloud} / ${counts.tools}${counts.unknown?' / ?'+counts.unknown:''}`);text('hud-failed-count',counts.failed);
  text('hud-latency-last',seconds(elapsed));$('hud-route-count').title='LOCALとCLOUDは実際の推論回数（併用は両方に計上）。TOOLは推論なし。?は経路未記録。';const sorted=[...latencies].sort((a,b)=>a-b);const middle=Math.floor(sorted.length/2);text('hud-latency-median',seconds(sorted.length?(sorted.length%2?sorted[middle]:(sorted[middle-1]+sorted[middle])/2):null));miniPlot('hud-latency-plot',latencies,'#70ddc7',null);
  if(!window.workbench.busy())text('hud-message-info',success?'COMPLETE / '+seconds(elapsed):'FAILED / 実行履歴を確認');
  recent.unshift({route:data.evaluation?.route||data.route||'処理',ok:success,time:elapsed});recent=recent.slice(0,5);
  const feed=$('hud-feed');feed.replaceChildren();for(const entry of recent){const row=make('div');row.classList.toggle('is-failed',!entry.ok);row.append(make('i',entry.ok?'✓':'!'),make('span',entry.route),make('strong',seconds(entry.time)));feed.append(row);}
 }
 function resetSession(){
  sessionVersion++;seen.clear();recent=[];latencies=[];counts={requests:0,local:0,cloud:0,tools:0,unknown:0,failed:0};
  text('hud-request-count',0);text('hud-route-count','0 / 0 / 0');text('hud-failed-count',0);text('hud-latency-last','未計測');text('hud-latency-median','未計測');miniPlot('hud-latency-plot',[]);text('hud-feed','処理を実行すると、実際の履歴が表示されます。');
 }
 function restoreHistory(rows){
  resetSession();for(const row of [...rows].sort((a,b)=>(a.created_at||0)-(b.created_at||0)))record({ok:row.success,route:row.route,execution:{...row.execution,request_id:row.request_id},evaluation:{api_called:(row.execution?.stage_totals?.cloud_llm||0)>0,route:row.route}});
 }
 function loadSession(){
  resetSession();const version=sessionVersion,session=$('session-id').value;
  fetch('/processing/history?session_id='+encodeURIComponent(session)).then(r=>{if(!r.ok)throw new Error('履歴取得失敗');return r.json();}).then(data=>{if(version!==sessionVersion||$('session-id').value!==session)return;restoreHistory(data.records||[]);}).catch(()=>{});
 }
 window.jarvisHud = {
  capture:()=>({mode,hiddenModules:[...hidden]}),
  restore:value=>{if(!value)return;mode=value.mode==='focus'?'focus':'max';hidden=new Set((Array.isArray(value.hiddenModules)?value.hiddenModules:[]).filter(key=>Object.prototype.hasOwnProperty.call(modules,key)));apply();}
 };
 window.initMaximalistDashboard=()=>{
  if($('hud-mode-toggle'))return;
  try{mode=localStorage.getItem('jarvis-hud-mode-v1')||(innerWidth>=1100?'max':'focus');hidden=new Set(JSON.parse(localStorage.getItem('jarvis-hud-hidden-v1')||'[]'));}catch{}
  if(!['max','focus'].includes(mode))mode='max';build();apply();
  window.addEventListener('jarvis:system-metrics',event=>renderMetrics(event.detail));window.addEventListener('jarvis:storage-status',event=>text('hud-document-count',event.detail.counts?.document_items??'—'));
  const complete=window.workbench.complete.bind(window.workbench);window.workbench.complete=data=>{complete(data);record(data);};
  const begin=window.workbench.begin.bind(window.workbench);window.workbench.begin=payload=>{begin(payload);text('hud-message-info','PROCESSING / '+($('clock-time')?.textContent||'PC CLOCK'));};
  const fail=window.workbench.fail.bind(window.workbench);window.workbench.fail=()=>{fail();text('hud-message-info','CONNECTION / EXECUTION ERROR');};
  $('session-id').addEventListener('change',resetSession);
  $('message').addEventListener('input',()=>text('hud-message-info',`${$('message').value.length} CHARACTERS / ENTER TO SEND`));
  const observer=new MutationObserver(mirror);for(const id of ['core-state-label','runtime-model','runtime-connection','geo-location-label','geo-provider','geo-accuracy','geo-temp','geo-weather','geo-rain','geo-humidity','geo-wind','clock-time','notifications-status'])if($(id))observer.observe($(id),{childList:true,characterData:true,subtree:true});
  const mapObserver=new MutationObserver(mirror);mapObserver.observe($('world-map-svg'),{childList:true,subtree:true});$('speak-enabled').addEventListener('change',mirror);window.addEventListener('resize',mirror);mirror();
  window.addEventListener('jarvis:processing-history',event=>{if(event.detail?.session_id===$('session-id').value)restoreHistory(event.detail.records||[]);});
  window.addEventListener('jarvis:session-reset',resetSession);
  loadSession();setInterval(()=>{if(!document.hidden)mirror();},3000);
 };
})();

/* 名前：左 — left column only. Reuses existing metrics and detailExplorer; no extra requests. */
(() => {
 'use strict';
 const MAX=240,STALE=12000,history=[];
 const $=id=>document.getElementById(id),make=(tag,text,cls)=>{const node=document.createElement(tag);if(text!=null)node.textContent=String(text);if(cls)node.className=cls;return node;};
 const finite=n=>typeof n==='number'&&Number.isFinite(n),pct=n=>finite(n)?n.toFixed(1)+'%':'未取得',gib=n=>finite(n)?(n/1073741824).toFixed(2)+' GiB':'未取得';
 const rate=n=>finite(n)?(n/1048576).toFixed(3)+' MiB/s':'未取得 / 差分なし';
 let latest=null,previous=null,processCPU=null,receivedAt=0,lastSuccess=null,failed=false,errorText='',booted=false,queued=false,interval=null,lastLinkSuccess=null;
 function text(id,value){const node=$(id);if(node&&node.textContent!==String(value))node.textContent=String(value);}
 function clock(value){return value?new Date(value).toLocaleTimeString('ja-JP',{hour12:false}):'未取得';}
 function ingest(data){
  if(!data?.ok||!data.cpu||!data.memory||!data.network||!data.disk){failed=true;errorText=data?.error||'PC情報を取得できませんでした。';if(booted)health();return;}
  const changed=!latest||latest.sampled_at!==data.sampled_at;latest=data;if(changed){receivedAt=performance.now();lastSuccess=finite(data.sampled_at)?data.sampled_at*1000:Date.now();}failed=false;errorText='';
  const p=data.process||{};const counters=p.cpu_time_seconds;const current=finite(counters?.user)&&finite(counters?.system)?counters.user+counters.system:null;
  if(!previous||previous.stamp!==data.sampled_at){
   const elapsed=previous&&finite(p.server_uptime_sec)&&finite(previous.uptime)?p.server_uptime_sec-previous.uptime:null;
   processCPU=previous&&p.pid===previous.pid&&finite(current)&&finite(previous.total)&&current>=previous.total&&finite(elapsed)&&elapsed>0?Math.max(0,Math.min(100,(current-previous.total)/elapsed/Math.max(1,data.cpu.logical_cores||1)*100)):null;
   previous={pid:p.pid,uptime:p.server_uptime_sec,total:current,stamp:data.sampled_at,interval:elapsed};
   history.push({sampled_at:data.sampled_at,cpu:data.cpu.usage_percent,rx:data.network.receive_bytes_sec,tx:data.network.send_bytes_sec,backend_cpu:processCPU,per_core:Array.isArray(data.cpu.per_core_percent)?data.cpu.per_core_percent.slice(0,512):[]});
   if(history.length>MAX)history.splice(0,history.length-MAX);
  }
  if(booted&&!queued){queued=true;queueMicrotask(()=>{queued=false;render();});}
 }
 function getDetail(ctx){
  const key=ctx.element?.closest('[data-left-resource]')?.dataset.leftResource;
  const p=latest?.process||{};const cpu={usage_percent_one_core_basis:processCPU,usage_percent_pc_capacity:finite(processCPU)&&latest?.cpu?.logical_cores?processCPU/latest.cpu.logical_cores:null,
   interval_sec:previous?.interval??null,pid:p.pid??null,cpu_time_seconds:p.cpu_time_seconds??null,rss_bytes:p.rss_bytes??null,
   scope:'Pythonバックエンド自身のCPU時間差分。Ollamaやクラウドの負荷は含みません。1論理CPU=100%の基準なので100%を超える場合があります。'};
  const groups={memory:{memory:latest?.memory??null,swap:latest?.swap??null},gpu:{gpus:latest?.gpus??[],availability:'対応GPU・ドライバーで取得できた値だけです。空配列は使用率0%ではありません。'},temperature:{temperature_c:latest?.cpu?.temperature_c??null},disk_io:latest?.disk_io??null,backend_cpu:cpu};
  return {source:'backend_pc',sampled_at:latest?.sampled_at??null,received_at:lastSuccess?new Date(lastSuccess).toISOString():null,
   status:failed?'error':!lastSuccess?'not_received':performance.now()-receivedAt>STALE?'stale':'live',error:failed?errorText:null,
   selection:key||'all',...(key?groups[key]||{status:'未取得'}:{...groups,logical_processors:latest?.cpu??null,samples:history.slice()}),max_samples:MAX};
 }
 function field(parent,key,label,id){const cell=make('div',null,'hud-cell left-resource-cell');cell.dataset.leftResource=key;cell.dataset.detailTopic='leftresources';cell.append(make('span',label));const value=make('strong','未取得');value.id=id;cell.append(value);cell.tabIndex=0;cell.setAttribute('role','button');cell.setAttribute('aria-label',label+'の詳細');const open=()=>window.detailExplorer?.openElement(cell);cell.addEventListener('click',event=>{event.stopPropagation();open();});cell.addEventListener('keydown',event=>{if(!event.isComposing&&['Enter',' '].includes(event.key)){event.preventDefault();event.stopPropagation();open();}});parent.append(cell);return cell;}
 function build(){
  const column=document.querySelector('.monitor-column');if(!column)return false;column.classList.add('left-audited');
  const status=make('div',null,'left-health');status.id='left-health';status.setAttribute('role','status');status.append(make('strong','OS TELEMETRY'),make('span','未取得'));column.querySelector('.ai-core-panel').after(status);
  const panel=make('section',null,'hud-module left-resource-panel');panel.dataset.leftOwned='resources';panel.dataset.detailTopic='leftresources';
  const head=make('div',null,'hud-module-head');head.append(make('strong','RESOURCES / 実測'),make('small','BACKEND PC'));const detail=make('button','詳細');detail.type='button';detail.setAttribute('aria-label','左側リソースの詳細');detail.addEventListener('click',()=>window.detailExplorer?.openElement(panel));head.append(detail);panel.append(head);
  const grid=make('div',null,'hud-info-grid');field(grid,'memory','RAM / 使用率','left-ram-usage');field(grid,'memory','RAM / 使用・総容量','left-ram-capacity');field(grid,'gpu','GPU / 使用率・VRAM','left-gpu');field(grid,'temperature','CPU / 温度','left-temperature');field(grid,'disk_io','DISK / 読込・書込','left-disk-io');field(grid,'backend_cpu','SERVER CPU / 1コア基準','left-process-cpu');panel.append(grid);
  const note=make('p','バックエンドPCの実測。SERVER CPUはPython自身で、LLM全体の負荷ではありません。','left-caption');panel.append(note);const plot=make('div');plot.id='left-cpu-history';plot.setAttribute('aria-label','CPU使用率の実測履歴');panel.append(make('small','CPU HISTORY / 最大240サンプル','left-chart-title'),plot);
  const processPanel=column.querySelector('.live-timings');if(processPanel){processPanel.after(panel);processPanel.querySelector('.panel-body')?.append(make('small','経過時間の表示。CPU使用率は下のSERVER CPUを参照。','left-caption'));}else document.querySelector('.hud-left-overview')?.prepend(panel);
  for(const key of ['hardware','cores','network','capacity']){const module=column.querySelector(`[data-hud-module="${key}"]`);if(module){const stamp=make('small','未取得','left-sample-note');stamp.dataset.leftStamp=key;module.querySelector('.hud-module-head')?.after(stamp);}}
  const network=column.querySelector('[data-hud-module="network"]');if(network){const scale=make('small','実通信量・グラフは自動スケール','left-caption');scale.id='left-network-scale';network.append(scale);}
  window.detailExplorer?.register('leftresources',getDetail);
  window.detailExplorer?.register('leftcpu',ctx=>{const index=Number(ctx.recordId);return {source:'backend_pc',logical_processor:index,usage_percent:latest?.cpu?.per_core_percent?.[index]??null,time_seconds:latest?.cpu?.per_core_time_seconds?.[index]??null,reported_frequency_mhz:latest?.hardware?.cpu_frequency_mhz??null,frequency_scope:'CPU全体の報告クロック。コア単体の実測クロックではありません。',sampled_at:latest?.sampled_at??null,samples:history.map(s=>({sampled_at:s.sampled_at,usage_percent:s.per_core?.[index]??null})),max_samples:MAX};});
  window.detailExplorer?.register('leftstorage',ctx=>({source:'backend_pc',volume:latest?.storage?.volumes?.find(v=>(v.mountpoint||v.device)===ctx.recordId)??null,refresh_interval_sec:latest?.storage?.refresh_interval_sec??15,snapshot_at:latest?.sampled_at??null,note:'スナップショット時刻です。個別ドライブの取得時刻はAPIで未提供、最大約15秒のキャッシュがあります。'}));
  // Own only left core/volume entry points. Stable containers survive periodic child replacement.
  document.addEventListener('click',event=>{if(!(event.target instanceof Element)||!window.detailExplorer)return;const node=event.target.closest('.monitor-column .hud-core,.monitor-column .hud-volume');if(!node)return;
   let ctx,anchor;
   if(node.matches('.hud-core')){const index=Number(node.id.match(/(\d+)$/)?.[1]??[...node.parentElement.children].indexOf(node));anchor=$('hud-core-grid');ctx={element:anchor,host:anchor,topic:'leftcpu',key:'leftcpu:'+index,label:'論理CPU '+index+' / 左詳細',recordId:String(index)};}
   else{const index=[...node.parentElement.children].indexOf(node),volume=latest?.storage?.volumes?.[index];if(!volume)return;anchor=$('hud-volume-list');const id=volume.mountpoint||volume.device;ctx={element:anchor,host:anchor,topic:'leftstorage',key:'leftstorage:'+id,label:(volume.device||id)+' / 左詳細',recordId:id};}
   event.preventDefault();event.stopPropagation();window.detailExplorer.openElement(anchor,{providedContext:ctx,expanded:true,advance:false});
  },true);

  const monitor=$('monitor-status');if(monitor)new MutationObserver(()=>{if(monitor.textContent.includes('停止')){failed=true;errorText='PC情報の取得が失敗しました。';health();}}).observe(monitor,{childList:true,characterData:true,subtree:true});
  const link=$('audio-rtt-status');if(link)new MutationObserver(()=>linkHealth()).observe(link,{childList:true,characterData:true,subtree:true});
  const linkText=make('small','接続計測：未取得','left-link-note');linkText.id='left-link-note';$('ai-signal')?.append(linkText);
  return true;
 }
 function plot(id,key,color,percent=false){const node=$(id);if(!node)return;const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 260 48');svg.setAttribute('role','img');svg.setAttribute('aria-label',`${key}の実測値。欠測は線を途切れさせます。`);
  const values=history.map(item=>item[key]),valid=values.filter(finite);if(!valid.length){node.replaceChildren(make('span','未取得 / 差分計測待ち','left-caption'));return;}
  const max=percent?100:Math.max(...valid,1);let path='',joined=false;values.forEach((v,i)=>{if(!finite(v)){joined=false;return;}const x=i/Math.max(1,values.length-1)*258,y=44-Math.max(0,Math.min(v/max,1))*39;path+=(joined?' L':' M')+x.toFixed(2)+','+y.toFixed(2);joined=true;});
  const line=document.createElementNS(ns,'path');line.setAttribute('d',path);line.setAttribute('fill','none');line.setAttribute('stroke',color);line.setAttribute('stroke-width','1.6');svg.append(line);const lastIndex=values.findLastIndex(finite);const dot=document.createElementNS(ns,'circle');dot.setAttribute('cx',String(lastIndex/Math.max(1,values.length-1)*258));dot.setAttribute('cy',String(44-Math.max(0,Math.min(values[lastIndex]/max,1))*39));dot.setAttribute('r','2');dot.setAttribute('fill',color);svg.append(dot);node.replaceChildren(svg);
 }
 function health(){if(!booted)return;const stale=lastSuccess&&performance.now()-receivedAt>STALE;const state=failed?'error':!lastSuccess?'missing':stale?'stale':'live';const label=failed?'取得失敗':!lastSuccess?'未取得':stale?'更新停止':'実測取得中';
  $('left-health').dataset.state=state;$('left-health').querySelector('span').textContent=label+' / 最終 '+clock(lastSuccess)+(failed||stale?' / 表示値は前回取得分':'');$('left-health').title=(errorText||'バックエンドPCの取得状態')+' / 最終取得 '+(lastSuccess?new Date(lastSuccess).toLocaleString('ja-JP',{hour12:false}):'未取得');
  document.querySelector('.monitor-column').dataset.leftFreshness=state;document.querySelectorAll('.monitor-column [data-left-stamp]').forEach(n=>{n.textContent=label+' / 最終 '+clock(lastSuccess);n.dataset.state=state;});
 }
 function linkHealth(){const message=$('audio-rtt-status')?.textContent||'',value=$('ai-link-rtt')?.textContent||'';if(value.includes('OFFLINE'))text('left-link-note','接続取得失敗 / 最終成功 '+clock(lastLinkSuccess));else if(/LINK \/ \d/.test(value)){lastLinkSuccess=Date.now();text('left-link-note','HTTP往復実測 / 最終成功 '+clock(lastLinkSuccess));}else text('left-link-note','接続計測：未取得');}
 function render(){if(!booted)return;const data=latest;if(!data){health();return;}
  text('left-ram-usage',pct(data.memory.usage_percent));text('left-ram-capacity',gib(data.memory.used_bytes)+' / '+gib(data.memory.total_bytes));
  const gpu=data.gpus?.[0];text('left-gpu',gpu?`${pct(gpu.usage_percent)} / ${finite(gpu.vram_used_mb)?gpu.vram_used_mb.toFixed(0)+' MiB':'未取得'} / ${finite(gpu.vram_total_mb)?gpu.vram_total_mb.toFixed(0)+' MiB':'未取得'}`:'未取得 / 対応GPU情報なし');
  text('left-temperature',finite(data.cpu.temperature_c)?data.cpu.temperature_c.toFixed(1)+' ℃':'未取得 / センサー情報なし');text('left-disk-io',(finite(data.disk_io?.read_bytes)?rate(data.disk_io?.read_bytes_sec):'未取得 / OS情報なし')+' / '+(finite(data.disk_io?.write_bytes)?rate(data.disk_io?.write_bytes_sec):'未取得 / OS情報なし'));text('left-process-cpu',finite(processCPU)?pct(processCPU):'未取得 / 差分計測待ち');
  text('hud-core-temp',finite(data.cpu.temperature_c)?data.cpu.temperature_c.toFixed(1)+' ℃':'未取得 / センサー情報なし');text('hud-thermals',`${finite(data.cpu.temperature_c)?data.cpu.temperature_c+' ℃':'未取得'} / ${finite(gpu?.temperature_c)?gpu.temperature_c+' ℃':'未取得'}`);
  const traffic=n=>finite(n)?(n/1024).toFixed(1)+' KiB/s':'未取得 / 差分なし';text('hud-net-rx',traffic(data.network.receive_bytes_sec));text('hud-net-tx',traffic(data.network.send_bytes_sec));const rx=history.map(s=>s.rx).filter(finite),tx=history.map(s=>s.tx).filter(finite);text('left-network-scale',`グラフ自動スケール / 直近最大 RX ${rx.length?traffic(Math.max(...rx)):'未取得'} / TX ${tx.length?traffic(Math.max(...tx)):'未取得'} / 欠測は線を切断`);
  plot('left-cpu-history','cpu','#70e0ed',true);plot('hud-network-plot','rx','#70e0ed');plot('hud-network-tx-plot','tx','#f4b267');
  // Do not turn an unavailable drive into a zero-filled progress bar.
  document.querySelectorAll('.monitor-column .hud-volume').forEach((row,index)=>{const volume=data.storage?.volumes?.[index],bar=row.querySelector('progress');if(bar&&!finite(volume?.usage_percent)){bar.hidden=true;row.dataset.leftUnavailable='true';row.title='OSから使用率を取得できませんでした。';}else if(bar){bar.hidden=false;delete row.dataset.leftUnavailable;}});
  health();
 }
 function init(){if(booted||!build())return;booted=true;render();interval=setInterval(()=>{if(!document.hidden)health();},1000);window.addEventListener('pagehide',()=>clearInterval(interval));window.addEventListener('pageshow',event=>{if(event.persisted){clearInterval(interval);health();interval=setInterval(()=>{if(!document.hidden)health();},1000);}});}
 window.addEventListener('jarvis:system-metrics',event=>ingest(event.detail));
 window.addEventListener('jarvis:telemetry-error',event=>{failed=true;errorText=event.detail?.error||'取得失敗';health();});
 window.leftMonitorAudit={inspect:()=>({sample_count:history.length,max_samples:MAX,last_success:lastSuccess,status:failed?'error':!lastSuccess?'missing':performance.now()-receivedAt>STALE?'stale':'live',backend_cpu_percent:processCPU,backend_cpu_interval_sec:previous?.interval??null,backend_pid:latest?.process?.pid??null,plot_nodes:['left-cpu-history','hud-network-plot','hud-network-tx-plot'].map(id=>$(id)?.querySelectorAll('*').length||0)}),details:()=>getDetail({})};
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();

/* Non-modal three-level detail windows. One global inactivity clock; pins are session-only. */
(() => {
 'use strict';
 const IDLE=5000,MAX_WINDOWS=16,providers=new Map(),windows=new Map(),cards=new Map();
 let latest=null,history=[],samples=[],lastActivity=performance.now(),z=420,sequence=0,root=null,tickTimer=null;
 const $=id=>document.getElementById(id),el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=String(text);if(cls)n.className=cls;return n;};
 const titles={system:'PC全体の実測情報',connections:'PCの接続一覧',session:'会話・モデル・処理件数',thermals:'CPU・GPUの温度',uptime:'PC・サーバーの稼働時間',cpu:'CPU / 論理コア・使用率',memory:'メモリー / 容量・使用量',disk:'ディスク / 容量・入出力',network:'ネットワーク / 通信量・エラー',gpus:'GPU / 使用率・VRAM・温度',battery:'電源 / バッテリー',hardware:'PC / ハードウェア',process:'プロセス / メモリー・スレッド',clock:'日時 / 時計同期',core:'AI Core / 実行状態',history:'処理履歴',performance:'応答性能',weather:'天気',map:'地図・位置情報',location:'位置情報',apple:'Apple予定・リマインダー',mission:'予定・タスク',audio:'音声・応答',spatial:'3Dモデル',connect:'外部接続',vision:'画像認識',news:'ニュース',lab:'計算・変換',document:'保存文書',search:'検索結果',translate:'翻訳',youtube:'動画',qr:'QRコード'};
 const glossary={usage_percent:['使用率','%'],physical_cores:['物理コア数','コア'],logical_cores:['論理プロセッサー数','スレッド'],per_core_percent:['論理コア別の使用率','%'],temperature_c:['温度','℃'],total_bytes:['総容量','bytes'],used_bytes:['使用量','bytes'],available_bytes:['利用可能容量','bytes'],free_bytes:['空き容量','bytes'],sent_bytes:['送信累積量','bytes'],received_bytes:['受信累積量','bytes'],send_bytes_sec:['送信速度','bytes/s'],receive_bytes_sec:['受信速度','bytes/s'],errors_in:['受信エラー数','件'],errors_out:['送信エラー数','件'],drops_in:['受信破棄数','件'],drops_out:['送信破棄数','件'],uptime_sec:['PC稼働時間','秒'],rss_bytes:['プロセスの物理メモリー使用量','bytes'],vram_used_mb:['VRAM使用量','MB'],vram_total_mb:['VRAM総容量','MB'],cpu_frequency_mhz:['報告クロック','MHz'],plugged:['外部電源への接続','真偽値'],remaining_sec:['バッテリー残り時間','秒'],per_core_time_seconds:['論理CPU別の累積稼働時間','秒'],percent:['バッテリー残量','%'],threads:['スレッド数','本'],system_process_count:['PC全体のプロセス数','件'],sampled_at:['実測サンプルの時刻','Unix秒'],read_bytes_sec:['ディスク読込速度','bytes/s'],write_bytes_sec:['ディスク書込速度','bytes/s'],read_bytes:['読込累積量','bytes'],write_bytes:['書込累積量','bytes'],server_elapsed_sec:['サーバー経過時間','秒'],duration_sec:['この処理の所要時間','秒'],local_llm:['ローカル推論','秒'],cloud_llm:['クラウド推論','秒'],intent:['意図判定','秒'],tool:['ツール実行','秒'],first_token_sec:['最初のトークンまで','秒'],text_generation_complete_sec:['テキスト生成完了まで','秒'],title:['件名','文字列'],notes:['メモ','文字列'],start:['開始日時','日時'],end:['終了日時','日時'],due:['期限','日時'],all_day:['終日','真偽値'],completed:['完了','真偽値'],priority:['優先度','数値'],sync_status:['反映状態','状態'],revision:['データの更新番号','版'],latitude:['緯度','度'],longitude:['経度','度'],accuracy:['位置精度','m'],accuracy_m:['推定位置精度','m'],hostname:['バックエンドPC名','文字列'],source:['取得元','識別子'],source_id:['保存先ID','識別子'],remote_id:['外部の項目ID','識別子'],request_id:['要求ID','識別子'],session_id:['会話ID','識別子'],route:['処理経路','識別子'],success:['成功・失敗','真偽値'],ok:['取得成功・失敗','真偽値'],name:['名称','文字列'],model:['モデル','文字列'],state:['状態','文字列'],url:['参照URL','URL']};
 Object.assign(glossary,{time_seconds:['OS累積CPU時間','秒'],cpu_time_seconds:['サーバー累積CPU時間','秒'],os_reported:['OSが報告するメモリ内訳','bytes / %'],os_counters:['OSのI/O累積内訳',''],sample_interval_sec:['速度の差分を取った間隔','秒'],network_adapters:['通信アダプターの内訳',''],cpu_frequency_detail_mhz:['OSが報告する周波数の内訳','MHz'],frequency_detail_mhz:['OSが報告する周波数の内訳','MHz'],speed_mbps:['報告リンク速度','Mbps'],mtu_bytes:['MTU','bytes'],is_up:['有効状態','真偽値'],logical_processor:['論理プロセッサー番号（0始まり）',''],epoch_ms:['PCのシステム時刻','Unix ms']});
 const notes={cpu:'バックエンドPC全体のCPU使用率です。論理コアは物理コアと同じ意味ではありません。センサー非対応の温度は未取得です。',memory:'容量はバックエンドPCの実測です。bytesの換算値は1024基準のGiB/MiBを併記します。',disk:'監視対象ドライブの容量とPCのディスクI/Oです。ディスクの空き容量とI/O速度は異なる指標です。',network:'PC全体のカウンターとサンプル間の差分速度です。初回など差分がない場合のnullは0ではありません。',gpus:'対応GPU・ドライバーで取得できた項目だけを表示します。空の配列はGPU負荷0%を意味しません。',battery:'バッテリー非搭載・OS非対応・残時間不明は未取得です。残り時間はOSの推定値です。',process:'プロセス名・PID・RSSなど取得済みの情報です。コマンドラインや環境変数は読みません。',hardware:'バックエンドPCのOSとハードウェア情報です。ブラウザーを開いた端末の情報とは区別します。',clock:'PCから同期した日時をブラウザーの単調時計で進めます。表示値は時計同期の遅延・更新停止の影響を受けます。',core:'実行イベントに連動したAIの状態です。内部の思考内容を表示したものではありません。',weather:'取得できた観測情報・ツールの戻り値だけを表示します。予報と現在の観測値を混同しないでください。',map:'地図・位置の取得方法と精度は別項目です。IP推定をGPS位置と同じ精度として扱いません。',location:'IP・手動・端末位置など取得方法を確認してください。未取得の精度や高度は補いません。',apple:'PC内・ファイル内・iCloud反映済み・iPhone反映待ちを区別します。詳細を見る操作では予定を変更しません。',mission:'予定・期限・優先度・完了状態の保存値です。詳細を見る操作では更新・削除しません。',performance:'サーバー計測とブラウザー計測は別の時計です。未計測はnull・欠落であり、0秒ではありません。',history:'実際に記録された処理と時間です。要求文や結果には個人情報を含む場合があります。',audio:'マイク入力、認識、音声合成、通信往復時間はそれぞれ別の指標です。未取得の音量や合成内部時間は推測しません。',connect:'取得した外部情報です。ここでの閲覧は家電操作・メール送信などを実行しません。',vision:'認識結果・モデル・計測時間を表示します。画像データそのものは詳細ウィンドウに複製しません。',spatial:'読込済みモデルの表示情報です。寸法の単位や物理解析の結果は保証しません。'};
 const selectors='.hud-cell,.metric,.monitor-detail,.hud-core,.hud-volume,.hud-module,.hud-tool-button,.hud-core-cell,.hud-process-row,.hud-plot-row,.timing-line,.mc-record,.processing-item,.execution-details,.geo-stat,.geo-metric,.meta-line,.bubble.assistant,#ai-core,#header-clock';
 function clean(value,depth=0,seen=new WeakSet(),budget={remaining:18000}){
  if(--budget.remaining<0)return '（表示項目数の上限に達しました）';
  if(depth>14)return '（深い階層は省略）';if(value===null||value===undefined)return null;
  if(typeof value==='string')return /^data:image\//i.test(value)?'（画像データは複製しません）':value.slice(0,120000);
  if(typeof value!=='object')return typeof value==='function'?null:value;
  if(seen.has(value))return '（循環参照）';seen.add(value);
  if(Array.isArray(value))return value.slice(0,3000).map(v=>clean(v,depth+1,seen,budget));
  const result=Object.create(null);for(const [key,entry]of Object.entries(value).slice(0,3000)){
   if(/password|passwd|authorization|credential|secret|cookie|^(?:token|access_?token|refresh_?token|id_?token|bearer_?token|session_?token)$|api[_-]?key$|^ics$|^image$|image_url/i.test(key)||(/token/i.test(key)&&typeof entry==='string'&&!/^(?:first_token_sec|token_count|prompt_tokens|completion_tokens|total_tokens)$/i.test(key))){result[key]='（機密・画像データは表示対象外）';continue;}
   result[key]=clean(entry,depth+1,seen,budget);
  }return result;
 }
 function visibleText(node){if(!node)return '';const clone=node.cloneNode(true);clone.querySelectorAll('input,textarea,select,button,script,style,[hidden],[data-dx-omit]').forEach(n=>n.remove());return (clone.textContent||'').replace(/\s+/g,' ').trim().slice(0,12000);}
 function hash(text){let n=2166136261;for(const c of text)n=Math.imul(n^c.charCodeAt(0),16777619);return (n>>>0).toString(36);}
 function context(element){
  const host=element.closest('[data-info-panel],[data-hud-module],.panel')||element;const panel=element.closest('[data-info-panel]')?.dataset.infoPanel,module=element.closest('[data-hud-module]')?.dataset.hudModule;
  const id=element.id||element.querySelector('[id]')?.id||'';const label=element.dataset.monitorLabel||element.querySelector('.metric-head span,.monitor-main span,.hud-cell>span,:scope>span,strong,summary')?.textContent?.trim()||host.querySelector('.panel-header>strong,.hud-module-head>strong')?.textContent?.trim()||element.getAttribute('aria-label')||'画面の情報';
  let topic=element.dataset.detailTopic||panel||module||'screen';
  const telemetry=!!element.closest('#system-monitor-content')||panel==='system'||['telemetry','hardware','cores','processes','capacity','trends'].includes(module);
  if(id==='header-clock'||id.startsWith('clock-')||id.startsWith('hud-clock-'))topic='clock';
  else if(id==='ai-core')topic='core';
  else if(panel==='network')topic='connections';
  else if(module==='session')topic='session';
  else if(telemetry&&!element.dataset.detailTopic){
   if(/thermals/.test(id))topic='thermals';
   else if(/uptime/.test(id))topic='uptime';
   else if(module==='cores'||element.matches('.hud-core')||/cpu|frequency|core-/i.test(id)||/CPU|コア|クロック/i.test(label))topic='cpu';
   else if(/ram|memory|swap/i.test(id)||/RAM|メモリ|SWAP/i.test(label))topic='memory';
   else if(/disk|drive/i.test(id)||/ディスク|DISK|I\/O/i.test(label))topic='disk';
   else if(/net|hud-rx|hud-tx|link-info/i.test(id)||/NETWORK|通信|送受信/i.test(label))topic='network';
   else if(/gpu|vram|thermals/i.test(id)||/GPU|VRAM/i.test(label))topic='gpus';
   else if(/power|battery/i.test(id)||/バッテリー|電源|POWER/i.test(label))topic='battery';
   else if(/server-rss|process/i.test(id)||module==='processes')topic='process';
   else if(/local-time|cloud-time/.test(id))topic='performance';
   else topic='hardware';
  }
  if(element.matches('.hud-volume'))topic='storage';
  if(['cores'].includes(topic))topic='cpu';if(topic==='environment')topic='location';if(topic==='trends')topic=/RAM/i.test(label)?'memory':/TRAFFIC/i.test(label)?'network':'cpu';
  if(element.matches('.bubble'))topic='conversation';
  if(element.matches('[data-hud-module="telemetry"]'))topic='system';
  const recordId=element.dataset.appleId||element.dataset.missionId||element.dataset.executionId||element.dataset.requestId||'';
  const stableLabel=element.matches('.mc-record,.processing-item,.execution-details,.bubble')?label+visibleText(element).slice(0,200):label;
  const coreIndex=element.matches('.hud-core')?'core-'+[...element.parentElement.children].indexOf(element):'';
  const key=topic+':'+(id||recordId||element.dataset.monitorKey||coreIndex||(element.matches('.hud-process-row')?element.querySelector('small')?.textContent:'')||hash(stableLabel));
  return {element,host,panel,module,id,topic,key,label:label.slice(0,140),recordId};
 }
 function metricData(topic){if(!latest)return null;switch(topic){case 'system':return latest;case 'storage':return latest.storage;case 'thermals':return {cpu_temperature_c:latest.cpu.temperature_c,gpus:latest.gpus};case 'uptime':return {uptime_sec:latest.uptime_sec,server_uptime_sec:latest.process?.server_uptime_sec};case 'hardware':return {hostname:latest.hostname,...latest.hardware};case 'disk':return {disk:latest.disk,disk_io:latest.disk_io,volumes:latest.storage?.volumes};case 'network':return { ...latest.network,adapters:latest.hardware?.network_adapters,samples:samples.map(s=>({sampled_at:s.sampled_at,send_bytes_sec:s.network?.send_bytes_sec,receive_bytes_sec:s.network?.receive_bytes_sec}))};case 'memory':return {memory:latest.memory,swap:latest.swap};case 'cpu':return {...latest.cpu,reported_frequency_mhz:latest.hardware?.cpu_frequency_mhz,frequency_detail_mhz:latest.hardware?.cpu_frequency_detail_mhz};case 'process':return latest.process;default:return latest[topic];}}
 function sampleStats(topic){const key={cpu:['cpu','usage_percent'],memory:['memory','usage_percent'],disk:['disk','usage_percent'],network:['network','receive_bytes_sec']}[topic];if(!key)return null;const points=samples.map(s=>s[key[0]]?.[key[1]]).filter(v=>typeof v==='number'&&Number.isFinite(v));if(!points.length)return null;return {sample_count:points.length,minimum:Math.min(...points),maximum:Math.max(...points),average:points.reduce((a,b)=>a+b,0)/points.length,unit:topic==='network'?'bytes/s':'%',note:'この画面が保持している直近サンプルから計算。研究ログ全体の統計ではありません。'};}
 function displayData(element){
  const data={visible_content:visibleText(element),links:[],displayed_times:[],indicators:[]};
  for(const a of element.querySelectorAll('a[href]')){try{const url=new URL(a.href);if(!['http:','https:'].includes(url.protocol))continue;for(const key of [...url.searchParams.keys()])if(/key|token|secret|auth|password/i.test(key))url.searchParams.set(key,'REDACTED');data.links.push({title:a.textContent.trim(),url:url.href});}catch{}}
  for(const time of element.querySelectorAll('time'))data.displayed_times.push({text:time.textContent,date_time:time.dateTime||null});
  for(const bar of element.querySelectorAll('progress'))data.indicators.push({label:bar.getAttribute('aria-label'),value:bar.value,max:bar.max});
  const pre=element.querySelector('pre');if(pre){try{data.displayed_json=JSON.parse(pre.textContent);}catch{data.displayed_text=pre.textContent.slice(0,40000);}}
  data.note='画面に表示された内容から取り出した情報です。APIの生データではありません。';return data;
 }
 function snapshot(ctx){
  if(ctx.explicitPath&&latest){let selected=latest;for(const key of ctx.explicitPath)selected=selected?.[key];return {data:clean({selected_path:ctx.explicitPath,selected_value:selected,related_data:latest[ctx.explicitPath[0]]}),origin:'バックエンドPCの実測',sampleAt:latest.sampled_at*1000,openedAt:Date.now(),visible:ctx.label+' / '+valueText(selected),stats:sampleStats(ctx.topic)};}
  let raw=null,origin='画面に表示されている内容',sampleAt=null;
  const metric=metricData(ctx.topic);
  if(metric!==undefined&&metric!==null){raw=metric;if(ctx.element.matches('.hud-core')){const index=[...ctx.element.parentElement.children].indexOf(ctx.element);raw={logical_processor:index,usage_percent:latest.cpu?.per_core_percent?.[index]??null,pc_cpu:metric};}if(ctx.element.matches('.hud-process-row')){const pid=Number(ctx.element.querySelector('small')?.textContent.match(/\d+/)?.[0]);raw=metric.top_memory?.find(row=>row.pid===pid)||metric;}origin='バックエンドPCのシステム監視';sampleAt=latest.sampled_at?latest.sampled_at*1000:null;}
  else if(cards.has(ctx.topic)&&['weather','map','translate','search','youtube','document','qr','knowledge','lab','vision'].includes(ctx.topic)){const card=cards.get(ctx.topic);raw=card.data;origin='実行したツールの戻り値';sampleAt=card.receivedAt;}
  else if(providers.has(ctx.topic)){try{raw=providers.get(ctx.topic)(ctx);origin='対応機能の取得済みデータ';}catch{raw={status:'機能のデータを取得できませんでした。'};}}
  else if(cards.has(ctx.topic)){const card=cards.get(ctx.topic);raw=card.data;origin='実行したツールの戻り値';sampleAt=card.receivedAt;}
  else if(['history','performance','pipeline','activity'].includes(ctx.topic)){raw={records:history};origin='実際の処理記録';}
  if(ctx.topic==='core'){raw={runtime:providers.get('runtime')?.(ctx)||null,state:$('ai-core')?.dataset.state,label:$('core-state-label')?.textContent,current_stage:$('live-stage')?.textContent,elapsed:$('live-elapsed')?.textContent};origin='AI実行イベント';}
  if(raw==null){raw={...displayData(ctx.element),section:visibleText(ctx.host)};}
  return {data:clean(raw),origin,sampleAt,openedAt:Date.now(),visible:visibleText(ctx.element),stats:sampleStats(ctx.topic)};
 }
 function unit(key){return glossary[key]?.[1]||'';}
 function valueText(value,key=''){
  if(value===null||value===undefined)return '未取得 / 未計測';
  if(Array.isArray(value))return `${value.length}件の内訳`;
  if(typeof value==='object')return `${Object.keys(value).length}項目の内訳`;
  if(typeof value==='boolean')return value?'はい / true':'いいえ / false';
  if(typeof value==='number'){
   if(key==='sampled_at')return new Date(value*1000).toLocaleString('ja-JP',{hour12:false});
   const u=unit(key);let text=Number.isInteger(value)?value.toLocaleString('ja-JP'):value.toLocaleString('ja-JP',{maximumFractionDigits:6});
   if(u)text+=' '+u;
   if(u==='bytes'||u==='bytes/s'){const suffix=u==='bytes/s'?'/s':'';text+=` / ${(value/1073741824).toFixed(6)} GiB${suffix} / ${(value/1048576).toFixed(3)} MiB${suffix}`;}
   return text;
  }return String(value);
 }
 function line(parent,label,value){const row=el('div',null,'dx-line');row.append(el('span',label),el('strong',value));parent.append(row);return row;}
 function action(parent,label,fn,cls=''){const b=el('button',label,cls);b.type='button';b.addEventListener('click',fn);parent.append(b);return b;}
 function focusWindow(win){win.order=++z;win.element.style.zIndex=String(win.order);windows.forEach(w=>w.element.classList.toggle('dx-front',w===win));}
 function clamp(win){const rect=win.element.getBoundingClientRect();win.element.style.left=Math.max(8,Math.min(rect.left,innerWidth-rect.width-8))+'px';win.element.style.top=Math.max(8,Math.min(rect.top,innerHeight-rect.height-100))+'px';}
 function close(win,automatic=false){if(!windows.has(win.key))return;const focus=win.element.contains(document.activeElement);windows.delete(win.key);win.element.remove();win.resize?.disconnect();if(!automatic&&focus&&win.ctx.element.isConnected)win.ctx.element.focus({preventScroll:true});updateManager();}
 function currentNode(win){let value=win.snapshot.data;for(const key of win.path){if(value==null)return null;value=value[key];}return value;}
 function back(win){if(win.level===3&&win.path.length){win.path.pop();render(win);}else if(win.level>1){win.level--;win.path=[];render(win);}}
 function detailChart(body,points,key,label,color){
  const valid=points.filter(p=>typeof p[key]==='number'&&Number.isFinite(p[key]));
  body.append(el('h3',label));if(!valid.length){body.append(el('p','差分計測待ち'));return;}
  const actualPeak=Math.max(...valid.map(p=>p[key])),peak=Math.max(actualPeak,1),ns='http://www.w3.org/2000/svg';
  const svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 800 160');svg.setAttribute('role','img');svg.setAttribute('aria-label',label);svg.style.width='100%';
  const first=points[0].sampled_at,last=points.at(-1).sampled_at;const line=document.createElementNS(ns,'polyline');line.setAttribute('points',valid.map((p,i)=>`${10+(last>first?(p.sampled_at-first)/(last-first):0)*780},${145-p[key]/peak*130}`).join(' '));line.setAttribute('fill','none');line.setAttribute('stroke',color);line.setAttribute('stroke-width','2');svg.append(line);for(const point of valid){const dot=document.createElementNS(ns,'circle');dot.setAttribute('cx',String(10+(last>first?(point.sampled_at-first)/(last-first):0)*780));dot.setAttribute('cy',String(145-point[key]/peak*130));dot.setAttribute('r','3');dot.setAttribute('fill',color);svg.append(dot);}body.append(svg);
  body.append(el('p',`最大 ${actualPeak.toLocaleString('ja-JP',{maximumFractionDigits:2})} ${key==='usage_percent'?'%':'bytes/s'} · ${valid.length}サンプル · ${new Date(first*1000).toLocaleTimeString()} ～ ${new Date(last*1000).toLocaleTimeString()}`,'dx-note'));
 }
 function render(win){
  const body=win.body,scroll=body.scrollTop;body.replaceChildren();win.levelText.textContent=`LEVEL ${win.level} / 3`;win.back.disabled=win.level===1;win.more.disabled=win.level===3;win.pin.setAttribute('aria-pressed',String(win.pinned));win.pin.textContent=win.pinned?'固定中':'ピン留め';win.element.dataset.level=String(win.level);win.element.dataset.pinned=String(win.pinned);
  const stamp=win.snapshot;const source=el('p',stamp.origin,'dx-source');body.append(source);
  if(win.level===1){body.append(el('p',stamp.visible||'選択項目の現在の内容','dx-summary'));line(body,'取得・表示時点',new Date(stamp.sampleAt||stamp.openedAt).toLocaleString('ja-JP',{hour12:false}));line(body,'元の画面',titles[win.ctx.topic]||win.ctx.label);body.append(el('p',notes[win.ctx.topic]||'取得済みの内容を段階的に表示します。表示だけで元データを変更することはありません。','dx-note'));action(body,'内訳を詳しく見る →',()=>{win.level=2;render(win);},'dx-primary');}
  else if(win.level===2){
   if(win.ctx.topic==='network'){detailChart(body,stamp.data.samples||[],'receive_bytes_sec','↓ 下り / DOWNLOAD','#70e0ed');detailChart(body,stamp.data.samples||[],'send_bytes_sec','↑ 上り / UPLOAD','#f4b267');}if(stamp.data?.samples&&win.ctx.topic==='cpu')detailChart(body,stamp.data.samples,'usage_percent','論理CPU使用率の推移','#70e0ed');body.append(el('h3','取得値の内訳'));const value=stamp.data,entries=Array.isArray(value)?value.map((v,i)=>[String(i),v]):value&&typeof value==='object'?Object.entries(value):[['value',value]];
   if(!entries.length)body.append(el('p','取得された内訳はありません。未取得を0と扱っていません。','dx-note'));
   for(const[key,value]of entries.slice(0,200)){const row=el('div',null,'dx-field');row.append(el('span',glossary[key]?.[0]||key),el('small',key),el('strong',valueText(value,key)));action(row,value&&typeof value==='object'?'展開して見る':'値の詳細',()=>{win.level=3;win.path=[key];render(win);});body.append(row);}
   if(entries.length>200)body.append(el('p','内訳一覧は先頭200件。取得データからさらに確認できます。','dx-note'));
   if(stamp.stats){body.append(el('h3','直近の実測サンプル'));for(const[key,value]of Object.entries(stamp.stats))line(body,({sample_count:'サンプル数',minimum:'最小値',maximum:'最大値',average:'平均値',unit:'単位',note:'集計範囲'})[key]||key,typeof value==='number'?value.toLocaleString('ja-JP',{maximumFractionDigits:6}):value);}
   body.append(el('p',notes[win.ctx.topic]||'項目名と単位が提供されている範囲を表示しています。','dx-note'));action(body,'取得データをすべて見る →',()=>{win.level=3;win.path=[];render(win);},'dx-primary');
  }else{
   const value=currentNode(win),path=win.path.length?win.path.join(' / '):'取得データ全体';body.append(el('h3',path));
   const crumb=el('div',null,'dx-path');action(crumb,'全体',()=>{win.path=[];render(win);});win.path.forEach((key,index)=>action(crumb,String(key),()=>{win.path=win.path.slice(0,index+1);render(win);}));body.append(crumb);
   if(value&&typeof value==='object'){
    const fields=Array.isArray(value)?value.map((v,i)=>[String(i),v]):Object.entries(value);const controls=el('div',null,'dx-tree');for(const[key,entry]of fields.slice(0,200))action(controls,`${Array.isArray(value)&&win.path.at(-1)==='per_core_percent'?'論理CPU '+key:glossary[key]?.[0]||key} · ${valueText(entry,Array.isArray(value)&&win.path.at(-1)==='per_core_percent'?'usage_percent':key).slice(0,85)}`,()=>{win.path.push(key);render(win);},'dx-tree-item');body.append(controls);if(fields.length>200)body.append(el('p','先頭200項目を表示。JSON保存でこの階層の取得データを確認できます。','dx-note'));
   }
   const key=win.path.at(-1)||'';line(body,'データ型',value===null?'null / 未取得':Array.isArray(value)?'配列':typeof value);const measuredUnit=win.path.some(k=>k==='time_seconds'||k==='cpu_time_seconds')?'秒':win.path.includes('os_reported')?(key==='percent'?'%':'bytes'):win.path.includes('os_counters')?(/bytes/.test(key)?'bytes':/count/.test(key)?'件':/time/.test(key)?'ms（累積）':unit(key)):win.path.some(k=>/frequency.*mhz/.test(k))?'MHz':unit(key);if(measuredUnit)line(body,'単位',measuredUnit);if(typeof value==='number'&&measuredUnit==='bytes'){line(body,'MiB（1024基準）',(value/1048576).toFixed(4));line(body,'GiB（1024基準）',(value/1073741824).toFixed(6));}if(value===null)body.append(el('p','未取得・非対応・未計測のいずれかです。0や正常状態を意味しません。','dx-note'));
   const pre=el('pre',JSON.stringify(value,null,2)??'null');body.append(pre);action(body,'この取得データをJSON保存',()=>{const url=URL.createObjectURL(new Blob([JSON.stringify({selected_at:new Date(stamp.openedAt).toISOString(),source:stamp.origin,path:win.path,data:value},null,2)],{type:'application/json'}));const a=el('a');a.href=url;a.download='ai-detail-'+Date.now()+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});body.append(el('p','選択時点の取得データです。更新したい場合は「表示値を更新」。保存内容には表示中の個人情報を含む場合があります。','dx-note'));
  }
  body.scrollTop=win.lastLevel===win.level?scroll:0;win.lastLevel=win.level;clamp(win);
 }
 function drag(win,head){let start=null;head.addEventListener('pointerdown',event=>{if(event.button!==0||event.target.closest('button'))return;const r=win.element.getBoundingClientRect();start={x:event.clientX,y:event.clientY,left:r.left,top:r.top};head.setPointerCapture(event.pointerId);});head.addEventListener('pointermove',event=>{if(!start)return;activity();win.element.style.left=start.left+event.clientX-start.x+'px';win.element.style.top=start.top+event.clientY-start.y+'px';clamp(win);});for(const event of ['pointerup','pointercancel','lostpointercapture'])head.addEventListener(event,()=>start=null);}
 function openElement(element,{advance=true,pinned=false,expanded=false,data,title:customTitle,providedContext,providedSnapshot}={}){
  if(!root||!(element instanceof Element))return null;expanded=expanded||!!element.closest('[data-detail-topic]');const ctx=providedContext||context(element);if(customTitle)ctx.label=customTitle;let win=windows.get(ctx.key);
  if(win){if(expanded){win.level=2;win.element.classList.add('dx-expanded');}if(data!==undefined)win.snapshot={...win.snapshot,data:clean(data)};if(advance&&win.level<3){win.level++;win.path=[];render(win);}if(pinned){win.pinned=true;render(win);}focusWindow(win);activity();return win;}
  if(windows.size>=MAX_WINDOWS){$('dx-manager-status').textContent=`詳細を${MAX_WINDOWS}件表示中です。新しい詳細を開くには、どれかを閉じてください。既存の詳細は入れ替えません。`;return null;}
  const node=el('section',null,'dx-window');node.id='dx-window-'+(++sequence);node.setAttribute('role','region');node.setAttribute('aria-label',ctx.label+'の詳細');node.tabIndex=-1;
  const head=el('div',null,'dx-head'),title=el('strong',ctx.label),buttons=el('div',null,'dx-head-actions');head.append(title,buttons);const body=el('div',null,'dx-body');const nav=el('div',null,'dx-nav'),level=el('span','LEVEL 1 / 3');const footer=el('div',null,'dx-footer'),ttl=el('span'),progress=el('progress');progress.max=IDLE;progress.value=IDLE;progress.setAttribute('aria-label','画面全体の操作がない場合に戻るまで');footer.append(ttl,progress);
  win={key:ctx.key,ctx,element:node,customData:data,body,level:expanded?2:1,path:[],pinned,snapshot:providedSnapshot||snapshot(ctx),order:0,levelText:level,ttl,progress};win.pin=action(buttons,'ピン留め',()=>{win.pinned=!win.pinned;activity();render(win);updateManager();});action(buttons,'×',()=>close(win)).setAttribute('aria-label',ctx.label+'の詳細を閉じる');win.back=action(nav,'‹ 戻る',()=>back(win));nav.append(level);win.more=action(nav,'さらに詳しく ›',()=>{if(win.level<3){win.level++;win.path=[];render(win);}});action(nav,'表示値を更新',()=>{win.snapshot=snapshot(win.ctx);if(win.customData!==undefined)win.snapshot.data=clean(win.customData);render(win);});node.append(head,nav,body,footer);root.append(node);windows.set(win.key,win);
  if(data!==undefined)win.snapshot.data=clean(data);if(expanded)node.classList.add('dx-expanded');
  const center=document.querySelector('.hud-center').getBoundingClientRect(),startTop=document.querySelector('.first-screen').getBoundingClientRect().top+12;
  const bottom=Math.min(innerHeight-100,document.querySelector('.composer').getBoundingClientRect().top-10),offset=(windows.size-1)%4*14;
  const width=Math.min(expanded ? 920 : 430, innerWidth - 24, Math.max(320, center.width - 24)),height=Math.max(260, Math.min(expanded ? 760 : 510, bottom - startTop));
  node.style.width=width+'px';node.style.height=height+'px';node.style.left=Math.max(8,Math.min(innerWidth-width-12,center.left+(center.width-width)/2+offset))+'px';node.style.top=Math.max(8,Math.min(startTop+offset,bottom-height))+'px';node.addEventListener('pointerdown',()=>focusWindow(win),true);node.addEventListener('focusin',()=>focusWindow(win));node.addEventListener('keydown',event=>{if(event.key==='Escape'&&!event.isComposing){event.stopPropagation();event.preventDefault();close(win);}});drag(win,head);win.resize=new ResizeObserver(()=>clamp(win));win.resize.observe(node);focusWindow(win);render(win);activity();updateManager();return win;
 }
 function pinElement(element){const ctx=context(element),existing=windows.get(ctx.key);const win=existing||openElement(element,{advance:false});if(win){win.pinned=!win.pinned;activity();render(win);updateManager();return win.pinned;}return false;}
 function activity(){lastActivity=performance.now();}
 function updateManager(){if(!root)return;document.querySelectorAll('.monitor-detail').forEach(row=>{const pinned=windows.get(context(row).key)?.pinned===true;row.classList.toggle('is-pinned',pinned);const pin=row.querySelector('.monitor-pin');if(pin)pin.setAttribute('aria-pressed',String(pinned));});const manager=$('dx-manager');manager.hidden=windows.size===0;$('dx-manager-count').textContent=`詳細 ${windows.size}件 / 固定 ${[...windows.values()].filter(w=>w.pinned).length}件`;}
 function tick(){const remaining=Math.max(0,IDLE-(performance.now()-lastActivity));for(const win of [...windows.values()]){if(!win.pinned&&remaining<=0){close(win,true);continue;}win.ttl.textContent=win.pinned?'ピン留め中 / 時間で閉じません':`画面全体で操作がない場合 ${Math.ceil(remaining/1000)}秒で戻る`;win.progress.hidden=win.pinned;win.progress.value=remaining;}}
 function addPanelEntrances(){
  document.querySelectorAll('[data-info-panel]>.panel-header,[data-hud-module]>.hud-module-head,.ai-core-panel>.panel-header,.runtime-panel>.panel-header').forEach(head=>{if(head.querySelector('.dx-open-section'))return;const b=el('button','詳細','dx-open-section');b.type='button';b.setAttribute('aria-label',(head.querySelector('strong')?.textContent||'項目')+'の詳細を見る');b.addEventListener('click',()=>openElement(head.parentElement));head.append(b);});
  document.querySelectorAll(selectors).forEach(target=>{if(target.closest('#dx-layer')||target.dataset.dxTrigger)return;target.dataset.dxTrigger='true';if(!target.matches('.monitor-detail')&&!target.matches('button,a,summary,details')&&!target.querySelector('button,input,textarea,select,a,summary')){target.tabIndex=target.tabIndex<0?0:target.tabIndex;target.setAttribute('role','button');target.setAttribute('aria-haspopup','false');target.setAttribute('aria-description','クリックで3段階の詳細表示。ピン留めしない詳細は画面全体の操作が5秒止まると閉じます。');}});
 }
 function openData(topic,options={}){
  const element=el('div',options.title||titles[topic]||topic);const path=Array.isArray(options.path)?options.path:[];let selected=options.data;for(const key of path)selected=selected?.[key];
  const ctx={element,host:element,panel:null,module:null,id:'',recordId:'',topic:path[0]||topic,key:'direct:'+(options.identity||topic),explicitPath:path,label:options.title||titles[topic]||topic};
  const data=path.length?{selected_path:path,selected_value:selected,related_data:options.data?.[path[0]]}:options.data;
  const snap={data:clean(data),origin:'取得済みの実測データ',sampleAt:options.data?.sampled_at?options.data.sampled_at*1000:null,openedAt:Date.now(),visible:ctx.label+' / '+valueText(selected),stats:null};
  return openElement(element,{providedContext:ctx,providedSnapshot:snap});
 }
 window.detailExplorer={register:(key,provider)=>providers.set(key,provider),open:openData,openElement,pinElement,isPinned:element=>windows.get(context(element).key)?.pinned===true,closeTopic:key=>{for(const win of [...windows.values()])if(win.ctx.topic===key)close(win,true);},closeUnpinned:()=>{for(const win of [...windows.values()])if(!win.pinned)close(win,true);}};
 window.initDetailExplorer=()=>{
  if(root)return;root=el('div');root.id='dx-layer';document.body.append(root);const manager=el('div',null,'dx-manager');manager.id='dx-manager';manager.hidden=true;manager.append(el('strong','',null));manager.firstChild.id='dx-manager-count';action(manager,'固定以外を戻す',()=>window.detailExplorer.closeUnpinned());action(manager,'すべて閉じる',()=>{for(const win of [...windows.values()])close(win);});const status=el('span');status.id='dx-manager-status';status.setAttribute('role','status');manager.append(status);document.body.append(manager);
  for(const event of ['pointerdown','click','keydown','input','wheel','touchstart','touchmove'])document.addEventListener(event,activity,{capture:true,passive:true});document.addEventListener('pointermove',event=>{if(event.buttons)activity();},{capture:true,passive:true});
  // Capture monitor actions before its legacy inline expand/collapse handlers.
  document.addEventListener('click',event=>{if(!(event.target instanceof Element))return;const row=event.target.closest('.monitor-detail');if(!row||row.closest('#dx-layer'))return;const pin=event.target.closest('.monitor-pin');if(!pin&&event.target.closest('button,input,textarea,select,a'))return;event.preventDefault();event.stopPropagation();if(pin)pinElement(row);else openElement(row);},true);
  document.addEventListener('keydown',event=>{if(event.isComposing||!['Enter',' '].includes(event.key)||!(event.target instanceof Element))return;const row=event.target.closest('.monitor-detail');if(!row)return;const pin=event.target.closest('.monitor-pin');if(!pin&&event.target!==row)return;event.preventDefault();event.stopPropagation();if(pin)pinElement(row);else openElement(row);},true);
  document.addEventListener('click',event=>{if(event.defaultPrevented||!(event.target instanceof Element)||event.target.closest('#dx-layer,#dx-manager,button,input,textarea,select,a,summary,label,.panel-tools,.monitor-pin'))return;const target=event.target.closest('[data-dx-trigger]');if(!target||target.matches('.monitor-detail')||getSelection()?.toString())return;openElement(target,{expanded:true});});
  document.addEventListener('keydown',event=>{const target=event.target;if(event.defaultPrevented||event.isComposing||!(target instanceof Element)||!target.matches('[data-dx-trigger]')||target.matches('.monitor-detail,details')||event.key!=='Enter'&&event.key!==' ')return;event.preventDefault();openElement(target,{expanded:true});});
  let pending=false;const observer=new MutationObserver(changes=>{if(pending||!changes.some(c=>[...c.addedNodes].some(n=>n.nodeType===1&&!n.closest?.('#dx-layer,#dx-manager'))))return;pending=true;queueMicrotask(()=>{pending=false;addPanelEntrances();});});observer.observe(document.querySelector('.jarvis-shell'),{subtree:true,childList:true});addPanelEntrances();
  tickTimer=setInterval(tick,100);window.addEventListener('resize',()=>windows.forEach(clamp));document.addEventListener('visibilitychange',()=>{if(!document.hidden)tick();});window.addEventListener('pagehide',()=>clearInterval(tickTimer));window.addEventListener('pageshow',event=>{if(event.persisted){clearInterval(tickTimer);tick();tickTimer=setInterval(tick,100);}});
 };
 window.addEventListener('jarvis:system-metrics',event=>{latest=event.detail;if(latest?.ok&&samples.at(-1)?.sampled_at!==latest.sampled_at){samples.push(clean(latest));if(samples.length>120)samples.shift();}});
 window.addEventListener('jarvis:tool-card',event=>{const card=event.detail;if(card?.kind)cards.set(card.kind,{data:clean(card.data),receivedAt:Date.now()});});
 window.addEventListener('jarvis:processing-history',event=>{history=clean(event.detail.records||[]);});
 window.addEventListener('jarvis:session-reset',()=>{history=[];cards.clear();});
})();

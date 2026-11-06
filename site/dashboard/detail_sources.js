/* Observes only already-requested, same-origin read results. It never fetches extra data. */
(() => {
 'use strict';
 const api=window.detailExplorer;if(!api)return;
 const received=new Map(),versions=new Map();
 const endpoints=new Map([
  ['/panel/location-weather','geo'],['/system/clock','clock'],['/health','health'],['/meta','runtime_meta'],['/storage','storage'],['/capabilities','capabilities'],
  ['/documents','documents'],['/mission/news','news'],['/mission/network','connections'],['/mission/lab','lab'],['/mission/knowledge','knowledge'],['/mission/vision','vision'],['/mission/models','vision_models'],['/mission/device','device']
 ]);
 const original=window.fetch;
 window.fetch=async function(...args){
  let url,key,version;try{url=new URL(args[0] instanceof Request?args[0].url:String(args[0]),location.href);if(url.origin===location.origin){key=endpoints.get(url.pathname);if(!key&&/^\/documents\/[^/]+$/.test(url.pathname))key='document';if(key){version=(versions.get(key)||0)+1;versions.set(key,version);}}}catch{}
  const response=await original.apply(this,args);
  if(key&&response.headers.get('content-type')?.includes('application/json')&&Number(response.headers.get('content-length')||0)<3000000){
   response.clone().json().then(value=>{if(versions.get(key)!==version)return;received.set(key,{value,at:new Date().toISOString(),endpoint:url.pathname});}).catch(()=>{});
  }
  return response;
 };
 const entry=key=>received.get(key)?.value;
 const source=key=>received.has(key)?{endpoint:received.get(key).endpoint,received_at:received.get(key).at,data:entry(key)}:null;
 const shown=id=>document.getElementById(id)?.textContent||null;
 api.register('clock',()=>({display:{date:shown('clock-date'),time:shown('clock-time'),timezone:shown('clock-zone'),sync:shown('clock-sync-status'),utc:shown('hud-clock-utc'),tokyo:shown('hud-clock-tokyo'),london:shown('hud-clock-london'),new_york:shown('hud-clock-newyork')},server_response:source('clock')}));
 api.register('runtime',()=>({health:source('health'),model:source('runtime_meta'),capabilities:source('capabilities')}));
 for(const key of ['weather','location'])api.register(key,()=>source('geo')||{status:'構造化された位置・天気データは未取得です',display:{place:shown('geo-location-label'),weather:shown('geo-weather'),temperature:shown('geo-temp'),provider:shown('geo-provider')}});
 for(const key of ['news','connections','lab','knowledge','vision','device'])api.register(key,()=>source(key)||{status:'この機能ではまだ結果を取得していません。元のパネルで実行してください。'});
 api.register('document',()=>({selected_document:source('document'),saved_documents:source('documents'),storage_summary:source('storage')}));
 api.register('session',()=>({session_id:document.getElementById('session-id')?.value,requests:shown('hud-request-count'),local_cloud_tool:shown('hud-route-count'),failures:shown('hud-failed-count'),last_seconds:shown('hud-latency-last'),median_seconds:shown('hud-latency-median'),documents:source('storage'),runtime:{health:source('health'),model:source('runtime_meta')}}));
})();

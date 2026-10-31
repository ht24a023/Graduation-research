/* Persistent timer math; no network, audio, or OS notification permission required. */
(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.JarvisTaskState=factory();})(globalThis,function(){
 'use strict';
 const finite=value=>typeof value==='number'&&Number.isFinite(value);
 const clamp=(value,min,max)=>Math.min(max,Math.max(min,value));
 const blank=()=>({version:1,timers:[],alarms:[],stopwatch:{elapsed:0,started:null,laps:[]}});
 function restore(value){
  const state=blank();if(!value||value.version!==1)return state;
  if(Array.isArray(value.timers))for(const item of value.timers.slice(0,12)){
   if(!item||typeof item.id!=='string'||!finite(item.duration)||item.duration<1000||item.duration>86400000||!finite(item.remaining)||item.remaining<0||item.remaining>item.duration)continue;
   if(state.timers.some(row=>row.id===item.id))continue;
   state.timers.push({id:item.id.slice(0,80),label:String(item.label||'タイマー').slice(0,60),duration:item.duration,remaining:item.remaining,deadline:finite(item.deadline)?item.deadline:null,finished:item.finished===true});
  }
  if(Array.isArray(value.alarms))for(const item of value.alarms.slice(0,12)){
   if(!item||typeof item.id!=='string'||typeof item.label!=='string')continue;
   const hour=clamp(Number(item.hour)||0,0,23);const minute=clamp(Number(item.minute)||0,0,59);const enabled=item.enabled!==false;
   state.alarms.push({id:item.id.slice(0,80),label:String(item.label||'アラーム').slice(0,60),hour,minute,enabled,triggerAt:finite(item.triggerAt)?item.triggerAt:0,ringing:false});
  }
  const watch=value.stopwatch;
  if(watch&&finite(watch.elapsed)&&watch.elapsed>=0){state.stopwatch.elapsed=Math.min(watch.elapsed,31536000000);state.stopwatch.started=finite(watch.started)?watch.started:null;let previous=-1;for(const lap of (Array.isArray(watch.laps)?watch.laps:[]).slice(0,32)){if(finite(lap)&&lap>=previous&&lap>=0){state.stopwatch.laps.push(lap);previous=lap;}}}
  return state;
 }
 function addTimer(state,{id,label,duration},now){
  if(state.timers.length>=12)throw new Error('タイマーは12件までです。');
  if(!finite(duration)||duration<1000||duration>86400000)throw new Error('1秒〜24時間で指定してください。');
  const item={id:String(id),label:String(label||'タイマー').slice(0,60),duration:Math.round(duration),remaining:Math.round(duration),deadline:now+Math.round(duration),finished:false};state.timers.push(item);return item;
 }
 function remaining(item,now){return item.deadline===null?item.remaining:Math.min(item.duration,Math.max(0,item.deadline-now));}
 function tick(state,now){const completed=[];for(const item of state.timers)if(item.deadline!==null&&now>=item.deadline){item.deadline=null;item.remaining=0;item.finished=true;completed.push(item.id);}return completed;}
 function toggleTimer(item,now){if(item.deadline!==null){item.remaining=remaining(item,now);item.deadline=null;if(item.remaining<=0)item.finished=true;}else{if(item.finished||item.remaining<=0){item.remaining=item.duration;item.finished=false;}item.deadline=now+item.remaining;}}
 function resetTimer(item){item.remaining=item.duration;item.deadline=null;item.finished=false;}
 function elapsed(state,now){const w=state.stopwatch;return Math.max(0,w.elapsed+(w.started===null?0:Math.max(0,now-w.started)));}
 function toggleWatch(state,now){const w=state.stopwatch;if(w.started===null)w.started=now;else{w.elapsed=elapsed(state,now);w.started=null;}}
 function lap(state,now){if(state.stopwatch.laps.length>=32)throw new Error('ラップは32件までです。');if(state.stopwatch.started===null)throw new Error('計測を開始してください。');const value=elapsed(state,now);state.stopwatch.laps.push(value);return value;}
 function format(ms,tenths=false){ms=Math.max(0,ms);const sec=Math.floor(ms/1000);return `${String(Math.floor(sec/3600)).padStart(2,'0')}:${String(Math.floor(sec/60)%60).padStart(2,'0')}:${String(sec%60).padStart(2,'0')}${tenths?'.'+Math.floor(ms%1000/100):''}`;}
 return {blank,restore,addTimer,remaining,tick,toggleTimer,resetTimer,elapsed,toggleWatch,lap,format};
});

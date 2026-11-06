/* Background work summaries: visible status, explicit controls, safe editor refresh. */
(()=>{'use strict';const boot=()=>{
const dialog=document.getElementById('neural-memory');if(!dialog)return;
const make=(tag,text,cls)=>{const e=document.createElement(tag);if(text)e.textContent=text;if(cls)e.className=cls;return e;};
const panel=make('section',null,'work-memory-panel');panel.id='work-memory-panel';const label=make('label','クラウド回答から作業要約を自動記憶'),toggle=make('input');toggle.type='checkbox';toggle.id='work-memory-enabled';label.htmlFor=toggle.id;label.prepend(toggle);
const status=make('p','作業要約：確認中');status.id='work-memory-status';status.setAttribute('role','status');const latest=make('button','最新の作業要約を開く'),retry=make('button','作業要約を再試行');latest.type=retry.type='button';latest.id='work-memory-open';retry.id='work-memory-retry';latest.disabled=retry.disabled=true;
const actions=make('div',null,'work-memory-actions');actions.append(latest,retry);panel.append(label,status,actions,make('small','目的・決定事項・進捗・未解決事項・次の作業をまとめます。直近のクラウド対話と既存の作業要約を追加のAPI呼び出しで送信します。AI生成の要約は内容を確認・編集できます。'));
dialog.querySelector('.neural-toolbar').after(panel);
const indicator=make('button','作業要約：待機');indicator.type='button';indicator.id='work-memory-indicator';document.querySelector('.neural-controls')?.append(indicator);
let timer=null,busy=false,currentSession='',lastNote='',current=null,pending=false;
const names={idle:'待機',queued:'要約待ち',running:'バックグラウンドで要約中',saved:'記憶に保存済み',proposal:'編集内容を保持して更新案を保存',error:'生成失敗。再試行できます',conflict:'編集内容を保持しました。更新案を整理してから再試行してください',full:'記憶が上限です。不要な記憶を整理してください',cancelled:'停止済み',disabled:'オフ'};
function session(){return document.getElementById('session-id')?.value||'';}
async function refresh(action){if(busy&&!action)return;busy=true;const sid=session();try{const response=await fetch('/memory/work-summary'+(action?'':'?session_id='+encodeURIComponent(sid)),action?{method:'POST',headers:{'Content-Type':'application/json','X-Jarvis-Notifications':'1'},body:JSON.stringify({session_id:sid,...action})}:{});const data=await response.json();if(sid!==session())return;if(!response.ok||!data.ok)throw Error(data.error||'取得失敗');current=data;toggle.checked=data.enabled;pending=data.state==='queued'||data.state==='running';const text=data.enabled?(names[data.state]||data.state):'オフ';status.textContent='作業要約：'+text;indicator.textContent='作業要約：'+text;latest.disabled=!data.note;retry.disabled=!data.enabled||!data.can_retry||pending;
const stamp=data.note?data.note.id+':'+data.note.revision:'';if(stamp&&stamp!==lastNote){lastNote=stamp;await window.memoryNetwork?.refresh();if(window.memoryNetwork?.isDirty())status.textContent+='（編集中の入力は保持しています）';}
}catch(error){status.textContent='作業要約を取得できません：'+error.message;}finally{busy=false;clearTimeout(timer);if(dialog.open||pending)timer=setTimeout(refresh,2000);}}
indicator.onclick=async()=>{await window.memoryNetwork?.open();refresh();};latest.onclick=()=>current?.note&&window.memoryNetwork?.open(current.note.id);retry.onclick=()=>refresh({action:'retry'});toggle.onchange=()=>refresh({action:'set_enabled',enabled:toggle.checked});
document.getElementById('neural-open')?.addEventListener('click',()=>refresh());
window.addEventListener('jarvis:request-finished',event=>{if(event.detail?.session_id&&event.detail.session_id!==session())return;const info=event.detail?.background_memory;if(info&&info.state!=='disabled'){pending=true;refresh();}});
window.addEventListener('jarvis:session-reset',()=>{clearTimeout(timer);current=null;lastNote='';pending=false;indicator.textContent='作業要約：待機';if(dialog.open)refresh();});
window.addEventListener('pagehide',()=>clearTimeout(timer));refresh();
};if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();})();

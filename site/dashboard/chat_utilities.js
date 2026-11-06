/* 名前；真ん中: search and export only the conversation loaded in this browser. */
(() => {
 'use strict';
 function setup(){
  const log=document.getElementById('chat-log'),head=document.querySelector('.hud-center>.panel-header');
  if(!log||!head||document.getElementById('chat-search-toggle'))return;
  const make=(tag,text)=>{const node=document.createElement(tag);if(text)node.textContent=text;return node;};
  const controls=make('div');controls.className='chat-utilities';
  const toggle=make('button','会話検索'),save=make('button','会話を保存');toggle.id='chat-search-toggle';save.id='chat-export';
  for(const button of [toggle,save])button.type='button';
  save.title='このブラウザーに表示中の会話をJSONで保存';toggle.setAttribute('aria-expanded','false');toggle.setAttribute('aria-controls','chat-search-bar');controls.append(toggle,save);head.append(controls);
  const bar=make('div');bar.id='chat-search-bar';bar.hidden=true;
  const input=make('input');input.type='search';input.placeholder='会話内のキーワード';input.setAttribute('aria-label','会話内のキーワード');input.id='chat-search-query';
  const previous=make('button','前へ'),next=make('button','次へ'),status=make('span','キーワードを入力');previous.type=next.type='button';status.id='chat-search-count';status.setAttribute('role','status');bar.append(input,previous,next,status);head.append(bar);
  const index=new Map();let matches=[],selected=null,timer;
  const add=node=>{if(node.nodeType===1&&node.matches('.bubble')&&!node.classList.contains('chat-pending'))index.set(node,node.chatRawText??node.querySelector('.bubble-content')?.textContent??'');};
  [...log.children].forEach(add);
  function refresh(){
   const query=input.value.trim().toLocaleLowerCase();
   for(const node of matches)node.classList.remove('chat-search-hit','chat-search-current');
   matches=query?[...index].filter(([node,text])=>node.isConnected&&text.toLocaleLowerCase().includes(query)).map(([node])=>node):[];
   if(!matches.includes(selected))selected=null;
   for(const node of matches)node.classList.add('chat-search-hit');
   previous.disabled=next.disabled=!matches.length;
   status.textContent=query?`${selected?matches.indexOf(selected)+1:0} / ${matches.length}件`:'キーワードを入力';
  }
  function go(direction){if(!matches.length)return;selected=matches[(matches.indexOf(selected)+direction+matches.length)%matches.length];for(const node of matches)node.classList.toggle('chat-search-current',node===selected);selected.scrollIntoView({block:'center',behavior:'instant'});status.textContent=`${matches.indexOf(selected)+1} / ${matches.length}件`;}
  input.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(refresh,120);});
  input.addEventListener('keydown',event=>{if(event.isComposing||event.keyCode===229)return;if(event.key==='Enter'){event.preventDefault();clearTimeout(timer);refresh();go(event.shiftKey?-1:1);}if(event.key==='Escape'){bar.hidden=true;toggle.setAttribute('aria-expanded','false');toggle.focus();}});
  previous.addEventListener('click',()=>go(-1));next.addEventListener('click',()=>go(1));
  toggle.addEventListener('click',()=>{bar.hidden=!bar.hidden;toggle.setAttribute('aria-expanded',String(!bar.hidden));if(!bar.hidden)input.focus();});
  const observer=new MutationObserver(records=>{for(const record of records){record.removedNodes.forEach(node=>index.delete(node));record.addedNodes.forEach(add);}if(input.value.trim()){clearTimeout(timer);timer=setTimeout(refresh,120);}});observer.observe(log,{childList:true});
  save.addEventListener('click',()=>{
   const messages=[...index].filter(([node])=>node.isConnected&&!node.classList.contains('chat-pending')).map(([node,text])=>({role:['user','assistant','system'].find(role=>node.classList.contains(role))||'system',text,regenerated:!!node.querySelector('.chat-version-label')}));
   const blob=new Blob([JSON.stringify({schema_version:1,exported_at:new Date().toISOString(),session_id:document.getElementById('session-id')?.value,scope:'messages_loaded_in_this_browser',messages},null,2)],{type:'application/json;charset=utf-8'});
   const url=URL.createObjectURL(blob),link=make('a');link.href=url;link.download='conversation-'+new Date().toISOString().replace(/[:.]/g,'-')+'.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
  refresh();
 }
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',setup,{once:true});else setup();
})();

from pathlib import Path
p=Path('site/dashboard/neural_core.js');s=p.read_text(encoding='utf-8')
s=s.replace("let theme='aurora',", "let contextRefs=[],contextCached=false;\nlet theme='aurora',",1)
s=s.replace("const status=make('p','読み込み中','neural-status');", "const contextPanel=make('div',null,'neural-context');contextPanel.id='neural-context';\nconst status=make('p','読み込み中','neural-status');")
s=s.replace("dialog.append(head,toolbar,status,body,", "dialog.append(head,toolbar,status,contextPanel,body,")
s=s.replace("b.setAttribute('aria-pressed',String(n.id===selected?.id));", "b.setAttribute('aria-pressed',String(n.id===selected?.id));b.dataset.context=String(contextRefs.some(r=>r.id===n.id));")
s=s.replace("open.onclick=async()=>{dialog.showModal();expanded=true;dirty=true;await load();};", """async function showMemory(id){if(!dialog.open)dialog.showModal();expanded=true;dirty=true;await load();if(id)select(graph.nodes.find(n=>n.id===id)||null);}
open.onclick=()=>showMemory();
function renderContext(){contextPanel.replaceChildren();contextPanel.append(make('span',contextRefs.length?(contextCached?'再利用した回答の元のモデル入力に含めた記憶：':'直近のモデル入力に含めた記憶：'):'直近の完了した処理で、入力に含めた保存メモはありません。'));for(const r of contextRefs){const b=make('button',r.title+(r.truncated?'（一部）':''));b.type='button';b.onclick=()=>showMemory(r.id);contextPanel.append(b);}contextPanel.append(make('small','入力に含めたことを示します。回答での利用・正しさを保証するものではありません。'));renderList();}
window.addEventListener('jarvis:request-finished',event=>{contextRefs=event.detail?.memory_context||[];contextCached=!!event.detail?.cached;renderContext();});
window.addEventListener('jarvis:session-reset',()=>{contextRefs=[];contextCached=false;renderContext();});
renderContext();""")
s=s.replace("x.fillStyle=p.n.id===selected?.id?b:a;", "x.fillStyle=p.n.id===selected?.id?b:(isMap&&contextRefs.some(r=>r.id===p.n.id)?'#a5ffd1':a);")
s=s.replace("図の光は演出で、回答で参照した記憶を示すものではありません。", "流れる光は演出です。モデル入力に含めた記憶は緑色で表示します。")
p.write_text(s,encoding='utf-8')

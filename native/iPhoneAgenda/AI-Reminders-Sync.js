// Scriptable for iPhone. OFFLINE file exchange only: no HTTP requests, tokens or login.
(async()=>{
 const fm=FileManager.local(),journalPath=fm.joinPath(fm.libraryDirectory(),'ai-reminders-operations.json');
 const info=async(title,message)=>{const a=new Alert();a.title=title;a.message=message;a.addAction('OK');await a.presentAlert();};
 let journal={};if(fm.fileExists(journalPath)){try{journal=JSON.parse(fm.readString(journalPath));}catch{throw new Error('操作記録が読めません。重複実行を避けるため停止しました。');}}
 const persist=()=>fm.writeString(journalPath,JSON.stringify(journal));
 const a=new Alert();a.title='AI・iPhoneリマインダー連携';a.message='①PCへ送るJSONを作成、または②PCからの変更JSONを読み込んで適用します。ファイルは「ファイル」アプリやiCloud Driveで受け渡します。';a.addAction('PCへ送るJSONを作る');a.addAction('PCの変更JSONを適用');a.addCancelAction('キャンセル');const mode=await a.presentSheet();if(mode<0)return;
 const available=await Calendar.forReminders();if(!available.length)throw new Error('リマインダーのアクセス権限とリストを確認してください。');
 const picker=new Alert();picker.title='PCへ送るリスト';picker.message='選択したリストを出力します。最大3000件。iOSのAPIには取得期間の制限があります。';for(const c of available)picker.addAction(c.title);picker.addAction('すべてのリスト');picker.addCancelAction('キャンセル');const chosen=await picker.presentSheet();if(chosen<0)return;const calendars=chosen===available.length?available:[available[chosen]];
 const values=r=>({kind:'reminder',calendar_id:r.calendar.identifier,title:r.title||'(件名なし)',notes:r.notes||'',location:'',start:'',end:'',due:r.dueDate?r.dueDate.toISOString():'',all_day:false,completed:r.isCompleted,priority:r.priority||0,due_has_time:r.dueDateIncludesTime!==false});
 const acknowledgments=[];
 if(mode===1){
  const files=await DocumentPicker.open(['public.json']);if(!files.length)return;
  const path=files[0];const cloud=FileManager.iCloud();const reader=cloud.isFileStoredIniCloud(path)?cloud:fm;
  if(reader.isFileStoredIniCloud(path))await reader.downloadFileFromiCloud(path);
  const changes=JSON.parse(reader.readString(path));if(changes.version!==1||changes.type!=='ai-iphone-changes'||!Array.isArray(changes.jobs)||changes.jobs.length>200)throw new Error('PCのAPPLE画面で保存した変更JSONを選択してください。');
  const confirm=new Alert();confirm.title=`iPhoneに変更 ${changes.jobs.length}件`;confirm.message=changes.jobs.slice(0,15).map(j=>`${{create:'追加',update:'編集',delete:'削除'}[j.action]||'不明'}：${j.title}`).join('\n')+'\n\n繰り返し項目では系列に影響する場合があります。取り消した古い変更ファイルは適用しないでください。';confirm.addAction('上の変更を適用');confirm.addCancelAction('中止');if(await confirm.presentAlert()<0)return;
  for(const job of changes.jobs){try{
   if(journal[job.id]?.status==='done'){acknowledgments.push({id:job.id,...journal[job.id].result});continue;}
   if(journal[job.id]?.status==='started')throw new Error('前回の結果が未確認です。リマインダー本体を確認してください。二重追加を避けるため再実行しません。');
   if(!['create','update','delete'].includes(job.action)||job.item?.kind!=='reminder')throw new Error('このスクリプトはリマインダーだけに対応しています。');
   const cal=calendars.find(c=>c.identifier===job.item.calendar_id);if(!cal||!cal.allowsContentModifications)throw new Error('対象のリストを選択していないか、編集権限がありません。');
   const all=await Reminder.all([cal]);const target=job.action==='create'?new Reminder():all.find(r=>r.identifier===job.remote_id);if(!target)throw new Error('対象がiPhoneに見つかりません。再取得してください。');
   if(job.base){const actual=values(target);for(const k of Object.keys(job.base))if(actual[k]!==job.base[k])throw new Error('iPhone側が変更されています。PCの反映待ちを取り消し、新しいJSONを取り込んでください。');}
   if(typeof job.item.title!=='string'||!job.item.title.trim()||job.item.title.length>300||String(job.item.notes||'').length>10000||!Number.isInteger(job.item.priority)||job.item.priority<0||job.item.priority>9)throw new Error('変更データの形式が不正です。');
   journal[job.id]={status:'started'};persist();let result;
   if(job.action==='delete'){target.remove();result={ok:true};}
   else{target.calendar=cal;target.title=job.item.title;target.notes=job.item.notes;target.priority=job.item.priority;target.dueDateIncludesTime=job.item.due_has_time!==false;target.dueDate=job.item.due?new Date(job.item.due):null;target.isCompleted=job.item.completed;await target.save();result={ok:true,remote_id:target.identifier,item:values(target)};}
   journal[job.id]={status:'done',result};persist();acknowledgments.push({id:job.id,...result});
  }catch(error){acknowledgments.push({id:job.id,ok:false,error:String(error.message||error)});}}
 }
 const reminders=await Reminder.all(calendars);if(reminders.length>3000)throw new Error('3000件を超えています。リストを分けて出力してください。変更済みの場合は同じ変更ファイルを再度選ぶと結果を回収できます。');
 const snapshot={version:1,type:'ai-iphone-snapshot',created_at:new Date().toISOString(),calendars:calendars.map(c=>({id:c.identifier,name:c.title,kind:'reminder',writable:c.allowsContentModifications})),items:reminders.map(r=>({...values(r),remote_id:r.identifier})),acknowledgments};
 const out=fm.joinPath(fm.documentsDirectory(),'iPhone-reminders-'+Date.now()+'.json');fm.writeString(out,JSON.stringify(snapshot,null,2));await DocumentPicker.export(out);await info('JSONを作成しました','ファイルをPCのAPPLE画面に取り込むと、一覧と反映結果が更新されます。');Script.complete();
})().catch(async error=>{const a=new Alert();a.title='連携を完了できませんでした';a.message=String(error.message||error);a.addAction('OK');await a.presentAlert();});

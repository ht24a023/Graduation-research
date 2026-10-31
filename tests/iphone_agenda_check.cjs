/* Execute the actual offline iPhone script against an in-memory Scriptable contract. */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const code=fs.readFileSync('native/iPhoneAgenda/AI-Reminders-Sync.js','utf8');
const files=new Map(),cal={identifier:'list-1',title:'Test Reminders',allowsContentModifications:true};
let records=[],counter=0,exportPath='',queue=[];
class Reminder{constructor(){this.identifier='';this.calendar=cal;this.title='';this.notes='';this.priority=0;this.isCompleted=false;this.dueDate=null;this.dueDateIncludesTime=true;}static async all(){return records;}save(){if(!this.identifier){this.identifier='native-'+(++counter);records.push(this);}}remove(){records=records.filter(r=>r!==this);}}
const fm={libraryDirectory:()=>'/lib',documentsDirectory:()=>'/docs',joinPath:(a,b)=>a+'/'+b,fileExists:p=>files.has(p),readString:p=>files.get(p),writeString:(p,s)=>files.set(p,s),isFileStoredIniCloud:()=>false,downloadFileFromiCloud:async()=>{}};
class Alert{addAction(){}addCancelAction(){}async presentSheet(){return queue.shift()??0;}async presentAlert(){return queue.shift()??0;}}
const context={console,Date,JSON,Error,Number,String,Array,FileManager:{local:()=>fm,iCloud:()=>fm},Calendar:{forReminders:async()=>[cal]},Reminder,Alert,DocumentPicker:{open:async()=>['/changes.json'],export:async path=>{exportPath=path;}},Script:{complete(){}}};
const value={kind:'reminder',calendar_id:'list-1',title:'Create once',notes:'note',location:'',start:'',end:'',due:'',all_day:false,completed:false,priority:0,due_has_time:true};
async function run(jobs){queue=[1,0,0,0];exportPath='';files.set('/changes.json',JSON.stringify({version:1,type:'ai-iphone-changes',jobs}));await vm.runInNewContext(code,context);assert.ok(exportPath,'must export result');return JSON.parse(files.get(exportPath));}
(async()=>{
 const add={id:'op-add',action:'create',title:'Create once',item:value,base:null,remote_id:''};
 let result=await run([add]);assert.equal(records.length,1);assert.equal(result.acknowledgments[0].ok,true);assert.equal(result.items[0].title,'Create once');
 result=await run([add]);assert.equal(records.length,1,'same operation cannot create twice');assert.equal(result.acknowledgments[0].ok,true);
 const update={id:'op-edit',action:'update',title:'Updated',item:{...value,title:'Updated'},base:value,remote_id:records[0].identifier};
 result=await run([update]);assert.equal(records[0].title,'Updated');assert.equal(result.acknowledgments[0].ok,true);
 records[0].title='Changed on phone';result=await run([{...update,id:'op-conflict'}]);assert.equal(result.acknowledgments[0].ok,false);assert.equal(records[0].title,'Changed on phone');
 const remove={id:'op-delete',action:'delete',title:'Changed on phone',item:{...value,title:'Changed on phone'},base:{...value,title:'Changed on phone'},remote_id:records[0].identifier};
 result=await run([remove]);assert.equal(records.length,0);assert.equal(result.acknowledgments[0].ok,true);
 assert.ok(!code.includes('new Request('),'no LAN HTTP interface');console.log('Offline iPhone contract passed: create, idempotent retry, update, conflict, delete, export.');
})().catch(error=>{console.error(error);process.exitCode=1;});

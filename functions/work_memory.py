"""Debounced cloud work summaries saved as editable, provenance-labelled notes."""
from collections import deque
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import threading
import time
from models import user_profile_memory as memory
from models.memory_retrieval import note_id
from models.api_usage import usage_scope
from cloud import model_catalog
from models.request_control import request_scope

TEMPLATE=Path(__file__).resolve().parents[1]/'prompts/work_summary.txt'
_FIELDS={'decisions':'決まったこと','progress':'進捗（会話での報告）','open_issues':'未解決・未確認','next_actions':'次の作業（未実施）'}


def parse_summary(text):
    if not isinstance(text,str) or len(text)>16000:raise ValueError('Invalid summary')
    text=re.sub(r'^```(?:json)?\s*|\s*```$','',text.strip())
    data=json.loads(text)
    if not isinstance(data,dict) or not isinstance(data.get('purpose'),str) or not data['purpose'].strip():raise ValueError('Missing purpose')
    normalized={'purpose':data['purpose'].strip()[:240]}
    for key in _FIELDS:
        values=data.get(key)
        if not isinstance(values,list) or any(not isinstance(v,str) for v in values):raise ValueError('Invalid fields')
        normalized[key]=[v.strip()[:240] for v in values[:5] if v.strip()]
    return normalized


def render_summary(data):
    lines=['【目的】',data['purpose']]
    for key,label in _FIELDS.items():lines.extend(['',f'【{label}】',*(['・'+v for v in data[key]] or ['記載なし'])])
    return '\n'.join(lines)


def fingerprint(note):
    if note is None:return None
    return hashlib.sha256(json.dumps({k:note.get(k) for k in ('title','content','updated_at','user_edited')},ensure_ascii=False,sort_keys=True).encode()).hexdigest()


class WorkMemory:
    def __init__(self,generator=None,debounce=1.5,min_interval=20):
        self.generator=generator or self._generate
        self.debounce=debounce;self.min_interval=min_interval
        self._condition=threading.Condition(threading.RLock())
        self._models={};self._pending={};self._states={};self._contexts={};self._epochs={};self._versions={};self._last_started={}
        self._thread=None;self._stop=False;self._active=None;self._cancel=None
        self._counts={'attempts':0,'saved':0,'errors':0,'conflicts':0}

    @staticmethod
    def _generate(prompt):
        from cloud.openai_client import ask_cloud_ai
        return ask_cloud_ai(prompt)

    @staticmethod
    def key(session_id):return hashlib.sha256(session_id.encode()).hexdigest()[:12]

    @staticmethod
    def settings_path():return Path(memory._NOTES_PATH).parent/'work_summary_settings.json'

    def is_enabled(self):
        try:return json.loads(self.settings_path().read_text(encoding='utf-8')).get('enabled',True) is True
        except FileNotFoundError:return True
        except (OSError,ValueError,AttributeError):return False

    def set_enabled(self,enabled):
        if not isinstance(enabled,bool):raise ValueError('enabled must be boolean')
        with self._condition:
            path=self.settings_path();path.parent.mkdir(parents=True,exist_ok=True)
            temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps({'enabled':enabled}),encoding='utf-8');temporary.replace(path)
            if not enabled:self.cancel_all()

    def _state(self,key,state,**values):
        self._states[key]={**self._states.get(key,{}),'state':state,'updated_at':datetime.now().astimezone().isoformat(timespec='seconds'),**values}

    def status(self,session_id):
        key=self.key(session_id)
        with self._condition:
            state=dict(self._states.get(key,{'state':'idle'}))
            if not state.get('note'):
                candidates=[note for note in self._base(key).values() if note is not None]
                if candidates:
                    latest=max(candidates,key=lambda n:n.get('updated_at',''))
                    state['note']={'id':note_id(latest['title']),'title':latest['title'],'revision':latest.get('summary_revision',1)}
                    if state['state']=='idle':state['state']='saved'
            return {'ok':True,'enabled':self.is_enabled(),'session_key':key,
                    **state,'counts':dict(self._counts),
                    'can_retry':bool(self._contexts.get(key)),'extra_cloud_request':True}

    def enqueue(self,session_id,question,answer,model_id=None):
        if not self.is_enabled():return {'state':'disabled','extra_cloud_request':False}
        key=self.key(session_id)
        with self._condition:
            self._models[key]=model_id or model_catalog.selected(session_id)
            contexts=self._contexts.setdefault(key,deque(maxlen=3))
            pair={'question':str(question)[:6000],'answer':str(answer)[:6000]}
            if not contexts or contexts[-1]!=pair:contexts.append(pair)
            return self._queue(key)

    def retry(self,session_id):
        if not self.is_enabled():raise ValueError('自動要約がオフです。')
        key=self.key(session_id)
        with self._condition:
            if not self._contexts.get(key):raise ValueError('この起動中の会話に再試行できる内容がありません。')
            self._queue(key)
        return self.status(session_id)

    def _queue(self,key):
        if key not in self._pending and len(self._pending)>=8:
            self._state(key,'error',error='要約待ちが多いため、後で再試行してください。');return {'state':'error'}
        self._versions[key]=self._versions.get(key,0)+1
        due=max(time.monotonic()+self.debounce,self._last_started.get(key,-1e9)+self.min_interval)
        self._pending[key]={'version':self._versions[key],'epoch':self._epochs.get(key,0),'due':due,'contexts':list(self._contexts[key]),'model_id':self._models.get(key,model_catalog.DEFAULT_MODEL)}
        self._state(key,'queued',error=None)
        if self._thread is None or not self._thread.is_alive():
            self._stop=False;self._thread=threading.Thread(target=self._run,daemon=True,name='cloud-work-summary');self._thread.start()
        self._condition.notify_all()
        return {'state':'queued','session_key':key,'extra_cloud_request':True}

    def cancel_session(self,session_id):
        key=self.key(session_id)
        with self._condition:
            self._epochs[key]=self._epochs.get(key,0)+1;self._pending.pop(key,None);self._contexts.pop(key,None)
            if self._active==key and self._cancel:self._cancel.set()
            self._state(key,'cancelled');self._condition.notify_all()

    def cancel_all(self):
        with self._condition:
            for key in set(self._pending)|set(self._states)|set(self._contexts):
                self._epochs[key]=self._epochs.get(key,0)+1;self._state(key,'cancelled')
            self._pending.clear();self._contexts.clear()
            if self._cancel:self._cancel.set()
            self._condition.notify_all()

    def stop(self):
        with self._condition:
            self._stop=True
            if self._cancel:self._cancel.set()
            self._condition.notify_all()
        if self._thread:self._thread.join(timeout=2)

    @staticmethod
    def titles(key):return f'作業要約 [{key}]',f'作業要約の更新案 [{key}]'

    def _base(self,key):
        main,proposal=self.titles(key)
        with memory._LOCK:
            notes=memory.load_notes().get('notes',[])
            return {title:next((dict(n) for n in notes if n.get('title')==title and n.get('source')=='cloud_work_summary' and n.get('work_session_key')==key),None) for title in (main,proposal)}

    def _prompt(self,key,job,base):
        main,proposal=self.titles(key)
        source={'previous_summary':base[main].get('content','') if base[main] else '',
                'previous_user_edited':bool(base[main] and base[main].get('user_edited')),
                'previous_update_proposal':base[proposal].get('content','') if base[proposal] else '',
                'recent_cloud_dialogue':job['contexts']}
        return TEMPLATE.read_text(encoding='utf-8-sig')+'\n[会話データ: JSON]\n'+json.dumps(source,ensure_ascii=False)

    def _commit(self,key,job,base,summary):
        main,proposal=self.titles(key)
        with memory._LOCK:
            store=memory.load_notes();notes=store.get('notes',[])
            current={title:next((n for n in notes if n.get('title')==title),None) for title in (main,proposal)}
            if base[main] is not None and current[main] is None:return 'conflict',None
            changed=fingerprint(current[main])!=fingerprint(base[main])
            preserve=changed or bool(current[main] and current[main].get('user_edited'))
            target=proposal if preserve else main
            if preserve and (fingerprint(current[proposal])!=fingerprint(base[proposal]) or (current[proposal] and current[proposal].get('user_edited'))):return 'conflict',None
            if current[target] is None and len(notes)>=memory._MAX_NOTES:return 'full',None
            if current[target] is not None and (current[target].get('source')!='cloud_work_summary' or current[target].get('work_session_key')!=key):return 'conflict',None
            revision=int((current[target] or {}).get('summary_revision',0))+1
            note={'title':target,'content':render_summary(summary),'type':'note','source':'cloud_work_summary',
                  'work_session_key':key,'summary_revision':revision,'user_edited':False,
                  'updated_at':memory._now_iso(),'summary_proposal':preserve}
            if current[target] is None:notes.append(note)
            else:notes[notes.index(current[target])]=note
            store['notes']=notes;memory.save_notes(store)
            return 'proposal' if preserve else 'saved',{'id':note_id(target),'title':target,'revision':revision}

    def _log(self,key,state,elapsed):
        # Separate auxiliary-call ledger: never store prompts or note bodies here.
        try:
            path=Path(memory._NOTES_PATH).parent/'work_summary_events.jsonl';path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('a',encoding='utf-8') as file:file.write(json.dumps({'timestamp':datetime.now().astimezone().isoformat(),'session_key':key,'state':state,'elapsed_sec':round(elapsed,3),'auxiliary_cloud_attempt':True})+'\n')
        except OSError:pass

    def _run(self):
        while True:
            with self._condition:
                if self._stop:return
                if not self._pending:self._condition.wait(.5);continue
                key=min(self._pending,key=lambda k:self._pending[k]['due']);job=self._pending[key]
                wait=job['due']-time.monotonic()
                if wait>0:self._condition.wait(min(wait,.5));continue
                self._pending.pop(key);self._active=key;self._cancel=threading.Event()
                self._last_started[key]=time.monotonic();self._counts['attempts']+=1;self._state(key,'running')
            begin=time.monotonic();state='error';note=None
            try:
                base=self._base(key)
                with request_scope(self._cancel), usage_scope('work_summary',session_key=key), model_catalog.model_scope(job['model_id']):text=self.generator(self._prompt(key,job,base))
                summary=parse_summary(text)
                with self._condition:
                    if self._stop or self._epochs.get(key,0)!=job['epoch'] or not self.is_enabled():state='cancelled'
                    else:state,note=self._commit(key,job,base,summary)
            except Exception:
                state='cancelled' if self._cancel.is_set() else 'error'
            with self._condition:
                self._active=None;self._cancel=None
                if state in ('saved','proposal'):self._counts['saved']+=1
                elif state in ('conflict','full'):self._counts['conflicts']+=1
                elif state=='error':self._counts['errors']+=1
                values={'last_result':state}
                if note:values['note']=note
                self._state(key,'queued' if key in self._pending else state,**values)
            self._log(key,state,time.monotonic()-begin)


work_memory=WorkMemory()

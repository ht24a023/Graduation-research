"""Measured OpenAI response usage; no prompts, answers or credentials in the ledger."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime,timezone,timedelta
import hashlib
import json
import math
from pathlib import Path
import threading
import time
from uuid import uuid4

_SCOPE=ContextVar('api_usage_scope',default={'purpose':'other','session_key':None})
JST=timezone(timedelta(hours=9))
PURPOSES={'conversation','delegation','regeneration','work_summary','other'}
# Published standard text-token prices checked 2026-11-06; estimates, not invoices.
PRICES={'gpt-4.1-nano':{'input':.10,'cached_input':.025,'output':.40,'as_of':'2026-11-06'},'gpt-4.1':{'input':2.,'cached_input':.50,'output':8.,'as_of':'2026-11-06'},'gpt-4.1-mini':{'input':.40,'cached_input':.10,'output':1.60,'as_of':'2026-11-06'}}


@contextmanager
def usage_scope(purpose,session_id='',session_key=None):
    key=session_key or (hashlib.sha256(session_id.encode()).hexdigest()[:12] if session_id else None)
    token=_SCOPE.set({'purpose':purpose if purpose in PURPOSES else 'other','session_key':key})
    try:yield
    finally:_SCOPE.reset(token)


def field(obj,key,default=None):
    return obj.get(key,default) if isinstance(obj,dict) else getattr(obj,key,default)


def integer(value):
    return value if isinstance(value,int) and not isinstance(value,bool) and value>=0 else None


def measured_usage(response):
    usage=field(response,'usage')
    prompt=integer(field(usage,'prompt_tokens'));output=integer(field(usage,'completion_tokens'))
    cached=integer(field(field(usage,'prompt_tokens_details'),'cached_tokens'))
    if cached is not None and (prompt is None or cached>prompt):cached=None
    return {'input_tokens':prompt,'output_tokens':output,'cached_input_tokens':cached,
            'total_tokens':prompt+output if prompt is not None and output is not None else None}


def price_for(model):
    return next((rate for key,rate in sorted(PRICES.items(),key=lambda item:-len(item[0])) if model==key or model.startswith(key+'-')),None)


def cost_estimate(model,usage,tier=None):
    rate=price_for(model)
    if not rate or usage['input_tokens'] is None or usage['output_tokens'] is None or (isinstance(tier,str) and tier not in ('default','auto')):return None,None
    cached=usage['cached_input_tokens']
    value=((usage['input_tokens']-(cached or 0))*rate['input']+(cached or 0)*rate['cached_input']+usage['output_tokens']*rate['output'])/1000000
    return round(value,9),'published_standard_rates' if cached is not None else 'uncached_upper_estimate'


class ApiUsage:
    def __init__(self,path='data/api_usage.jsonl',settings_path='data/api_usage_settings.json',official_path='data/api_official_usage.json'):
        self.path=Path(path);self.settings_path=Path(settings_path);self.official_path=Path(official_path)
        self._lock=threading.RLock();self._active={};self.last_error=None
        self._rows={};self._offset=0;self._file_id=None;self._mtime=None

    def _append(self,row):
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            with self.path.open('a',encoding='utf-8') as file:file.write(json.dumps(row,ensure_ascii=False)+'\n')
            self.last_error=None
        except OSError:self.last_error='利用記録を書き込めませんでした。公式使用量も確認してください。'

    def begin(self,model,provider="openai",free=False,model_choice=None):
        with self._lock:
            call=uuid4().hex;row={'event':'start','id':call,'started_at':time.time(),'model':model,'provider':provider,'free':free,'model_choice':model_choice,**_SCOPE.get()}
            self._active[call]=row;self._append(row);return call

    def finish(self,call,response,status,elapsed):
        with self._lock:
            started=self._active.pop(call,{'id':call,'model':'unknown','purpose':'other'})
            reported=field(response,'model');model=reported if isinstance(reported,str) else started['model']
            tier=field(response,'service_tier');tier=tier if isinstance(tier,str) else None
            usage=measured_usage(response);cost,basis=cost_estimate(model,usage,tier)
            if started.get('free'):cost,basis=0.0,'free_model'
            response_id=field(response,'id')
            row={**started,'event':'finish','finished_at':time.time(),'model':model,'status':status,
                 'elapsed_sec':round(elapsed,3),**usage,'estimated_cost_usd':cost,'cost_basis':basis,
                 'price_as_of':price_for(model)['as_of'] if price_for(model) and not started.get('free') else None,
                 'service_tier':tier,'provider_response_id':response_id[:160] if isinstance(response_id,str) else None}
            self._append(row)

    def records(self):
        with self._lock:
            try:stat=self.path.stat()
            except FileNotFoundError:return []
            ident=(stat.st_dev,stat.st_ino)
            if ident!=self._file_id or stat.st_size<self._offset or (stat.st_size==self._offset and self._mtime!=stat.st_mtime_ns):
                self._rows={};self._offset=0
            self._file_id=ident;self._mtime=stat.st_mtime_ns
            with self.path.open('rb') as file:
                file.seek(self._offset)
                while True:
                    position=file.tell();line=file.readline()
                    if not line:break
                    if not line.endswith(b'\n'):file.seek(position);break
                    try:
                        row=json.loads(line)
                        if isinstance(row,dict) and isinstance(row.get('id'),str) and row.get('event') in ('start','finish'):
                            self._rows[row['id']]={**self._rows.get(row['id'],{}),**row}
                    except (ValueError,UnicodeError):pass
                self._offset=file.tell()
            rows=[]
            for key,value in self._rows.items():
                row=dict(value)
                if row.get('event')!='finish':row.update(status='running' if key in self._active else 'unconfirmed',input_tokens=None,output_tokens=None,cached_input_tokens=None,total_tokens=None,estimated_cost_usd=None)
                rows.append(row)
            return sorted(rows,key=lambda r:r.get('started_at',0))

    def settings(self):
        try:
            value=json.loads(self.settings_path.read_text(encoding='utf-8'))
            return value if isinstance(value,dict) else {}
        except (OSError,ValueError):return {}

    def _write_settings(self,settings):
        self.settings_path.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.settings_path.with_name(self.settings_path.name+'.'+uuid4().hex+'.tmp')
        try:
            temporary.write_text(json.dumps(settings,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(self.settings_path)
        finally:temporary.unlink(missing_ok=True)

    @staticmethod
    def _number(value,allow_none=True,positive=False):
        if value is None and allow_none:return None
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0 or value>1000000000 or (positive and value==0):raise ValueError('0以上の有効な金額・換算値を入力してください。')
        return float(value)

    def update_settings(self,data):
        if not isinstance(data,dict):raise ValueError('入力形式が不正です。')
        with self._lock:
            settings=self.settings()
            if data.get('action')=='budget':
                settings.update(monthly_budget_usd=self._number(data.get('monthly_budget_usd')),usd_jpy=self._number(data.get('usd_jpy'),positive=True))
            elif data.get('action')=='balance':
                amount=self._number(data.get('balance_usd'))
                rows=self.records()
                if amount is None:settings.pop('balance_reference',None)
                else:settings['balance_reference']={'amount_usd':amount,'recorded_at':time.time(),'baseline_cost_usd':sum(r.get('estimated_cost_usd') or 0 for r in rows)}
            else:raise ValueError('操作が不正です。')
            self._write_settings(settings)
            return settings

    @staticmethod
    def aggregate(rows):
        known=[r for r in rows if r.get('estimated_cost_usd') is not None]
        measured=[r for r in rows if r.get('total_tokens') is not None]
        return {'calls':len(rows),'successes':sum(r.get('status')=='success' for r in rows),
                'errors':sum(r.get('status') in ('error','invalid_response') for r in rows),
                'cancelled':sum(r.get('status')=='cancelled' for r in rows),
                'unconfirmed':sum(r.get('status')=='unconfirmed' for r in rows),
                'running':sum(r.get('status')=='running' for r in rows),
                'measured_calls':len(measured),'unmeasured_calls':len(rows)-len(measured),
                'input_tokens':sum(r.get('input_tokens') or 0 for r in measured),
                'output_tokens':sum(r.get('output_tokens') or 0 for r in measured),
                'cached_input_tokens':sum(r.get('cached_input_tokens') or 0 for r in measured),
                'cache_unknown_calls':sum(r.get('cached_input_tokens') is None for r in measured),
                'total_tokens':sum(r.get('total_tokens') or 0 for r in measured),
                'priced_calls':len(known),'unpriced_calls':len(rows)-len(known),
                'estimated_cost_usd':round(sum(r['estimated_cost_usd'] for r in known),9)}

    def snapshot(self,period='month',now=None):
        if period not in ('today','month','all'):raise ValueError('集計期間が不正です。')
        now=time.time() if now is None else now;date=datetime.fromtimestamp(now,JST)
        today=date.replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
        month=date.replace(day=1,hour=0,minute=0,second=0,microsecond=0).timestamp()
        rows=self.records();selected=[r for r in rows if period=='all' or r.get('started_at',0)>=(today if period=='today' else month)]
        monthly=[r for r in rows if r.get('started_at',0)>=month]
        total=self.aggregate(selected);month_total=self.aggregate(monthly);settings=self.settings()
        budget=settings.get('monthly_budget_usd');budget_left=max(0,budget-month_total['estimated_cost_usd']) if budget is not None and month_total['unpriced_calls']==0 else None
        reference=settings.get('balance_reference');balance_left=None;balance_uncertain=False
        if reference:
            later=[r for r in rows if r.get('finished_at',r.get('started_at',0))>=reference['recorded_at']]
            balance_uncertain=any(r.get('estimated_cost_usd') is None for r in later)
            if not balance_uncertain:balance_left=max(0,reference['amount_usd']-(self.aggregate(rows)['estimated_cost_usd']-reference['baseline_cost_usd']))
        main_count=sum(r.get('purpose') in ('conversation','delegation','regeneration') and r.get('status')=='success' for r in monthly)
        average=month_total['estimated_cost_usd']/main_count if main_count and not month_total['unpriced_calls'] else None
        remaining=[v for v in (budget_left,balance_left) if v is not None]
        turns=int(min(remaining)/average) if remaining and average and average>0 else None
        try:official=json.loads(self.official_path.read_text(encoding='utf-8'))
        except (OSError,ValueError):official=None
        return {'ok':True,'period':period,'generated_at':now,'period_start':None if period=='all' else today if period=='today' else month,
                'totals':total,'month':month_total,'by_purpose':[{'purpose':p,**self.aggregate([r for r in selected if r.get('purpose')==p])} for p in ('conversation','delegation','regeneration','work_summary','other')],
                'by_model':[{'model':m,**self.aggregate([r for r in selected if r.get('model')==m])} for m in sorted({r.get('model','unknown') for r in selected})],
                'recent':list(reversed(selected[-50:])),'settings':settings,'budget_remaining_usd':budget_left,
                'budget_over_usd':max(0,month_total['estimated_cost_usd']-budget) if budget is not None else None,
                'balance_reference_remaining_usd':balance_left,'balance_reference_uncertain':balance_uncertain,
                'estimated_dialogue_turns_remaining':turns,'recording_started_at':rows[0].get('started_at') if rows else None,
                'official':official,'official_balance_usd':None,'prices':PRICES,'log_error':self.last_error,
                'notes':['sotukenでこの記録を導入した後の呼び出しが対象です。導入前・他アプリの利用は含みません。',
                         'トークン数はAPI応答のusageから取得します。応答が途切れた場合やusageがない場合は未計測です。',
                         '金額は公開された標準料金からの目安で、公式の請求額ではありません。キャッシュ情報がない場合はキャッシュ割引前の上限寄りの目安です。',
                         '月予算と残高の手入力は表示用です。自動停止・購入・自動チャージの設定は変更しません。',
                         '手入力からの参考残額は、このアプリ以外の利用、クレジットの有効期限、調整額を反映しません。',
                         'API残高は金額で管理されます。残りトークン数や残り会話回数は固定ではありません。']}


api_usage=ApiUsage()

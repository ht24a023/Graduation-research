"""Bounded free-tier rotation, persistent cooldowns, no paid fallback or sleeps."""
import json,threading,time
from pathlib import Path
from email.utils import parsedate_to_datetime
from cloud import model_catalog as catalog
from models.request_control import RequestCancelled,check_cancelled
STATE=Path('data/free_cloud_state.json')
_lock=threading.RLock()

class FreePoolExhausted(RuntimeError):
    def __init__(self,attempts):
        self.attempts=attempts
        super().__init__('設定済みの無料クラウドは現在すべて利用できません。モデル変更で接続設定・無料枠の回復を確認するか、端末内Ollama／有料モデルを選択してください。有料への自動切替は行っていません。')

def reset():
    with _lock:catalog.write(STATE,{})

def status():
    with _lock:
        state=catalog.read(STATE);now=time.time()
        return [{'id':r['id'],'name':r['name'],'provider':r['provider'],'configured':bool(catalog.key(r['provider'])),'eligible':catalog.free_confirmed(r['provider']),
                 'blocked_until':state.get(r['id'],{}).get('until'),'reason':state.get(r['id'],{}).get('reason'),
                 'available':state.get(r['id'],{}).get('until',0)<=now} for r in candidates()]

def candidates():return [r for r in catalog.CATALOG if r['free'] and r['provider'] not in ('free_auto','ollama_local')]

def _cooldown(error):
    headers=getattr(getattr(error,'response',None),'headers',{}) or {}
    value=headers.get('retry-after')
    try:return max(1,min(float(value),31*86400))
    except (TypeError,ValueError):
        try:return max(1,min(parsedate_to_datetime(value).timestamp()-time.time(),31*86400))
        except (TypeError,ValueError,OverflowError):return 60

def generate(text,send,preferred=None):
    attempts=[]
    ordered=candidates()
    if preferred:ordered.sort(key=lambda r:r["id"]!=preferred)
    for row in ordered:
        check_cancelled()
        if not catalog.key(row['provider']) or not catalog.free_confirmed(row['provider']):
            attempts.append({'id':row['id'],'state':'unconfigured'});continue
        with _lock:blocked=catalog.read(STATE).get(row['id'],{})
        if blocked.get('until',0)>time.time():
            attempts.append({'id':row['id'],'state':'cooldown','until':blocked['until']});continue
        try:
            with catalog.model_scope(row['id']):answer=send(text)
            result=catalog.outcome() or {'choice':row['id'],'provider':row['provider'],'model':row['model'],'free':True}
            catalog.set_outcome({**result,'rotation':attempts,'automatic_free':True})
            with _lock:
                state=catalog.read(STATE);state.pop(row['id'],None);catalog.write(STATE,state)
            return answer
        except RequestCancelled:raise
        except Exception as error:
            code=getattr(error,'status_code',None)
            if code==400:
                # Invalid prompts, context overflow, and moderation must not be replayed across providers.
                raise
            from openai import APIConnectionError
            network_failure=isinstance(error,APIConnectionError)
            reason='上限・混雑' if code==429 else '認証・利用権限' if code in (401,402,403) else 'モデル利用不可・通信エラー'
            delay=_cooldown(error) if code==429 else 300 if code in (401,402,403,404) else 30
            until=time.time()+delay
            with _lock:
                state=catalog.read(STATE)
                affected=[r for r in candidates() if r['provider']==row['provider']] if network_failure or code in (401,402,403) or (code==429 and row['provider']=='openrouter') else [row]
                for affected_row in affected:state[affected_row['id']]={'until':until,'reason':reason,'status':code}
                catalog.write(STATE,state)
            attempts.append({'id':row['id'],'state':'unavailable','status':code,'until':until})
    catalog.set_outcome({'switch_required':True,'rotation':attempts,'free':True,'provider':'free_auto','cloud_attempted':any(a.get('state')=='unavailable' for a in attempts)})
    raise FreePoolExhausted(attempts)

QUOTA=Path('data/free_cloud_quota.json')
def sync_openrouter():
    import httpx
    key=catalog.key('openrouter')
    if not key:raise ValueError('OpenRouterのAPIキーが未設定です。')
    try:
        response=httpx.get('https://openrouter.ai/api/v1/key',headers={'Authorization':'Bearer '+key},timeout=10)
        response.raise_for_status();data=response.json().get('data',{})
        counter=data.get('free_model_daily_requests')
        if not isinstance(counter,dict):counter=None
        allowed={k:v for k,v in (counter or {}).items() if k in ('limit','used','remaining','reset_at','resets_at') and isinstance(v,(str,int,float,type(None)))}
        result={'provider':'openrouter','fetched_at':time.time(),'daily':allowed or None,'note':'同じアカウントの無料モデル間で共有する日次枠です。自動要約や再試行も消費します。月の残量ではありません。'}
        catalog.write(QUOTA,result);return result
    except (httpx.HTTPError,ValueError,AttributeError):raise ValueError('公式の無料枠を取得できませんでした。公式ページで確認してください。') from None

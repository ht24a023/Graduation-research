"""Server-side model choices. Free cloud is the default; never fall back to paid."""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib,json,os,threading
from pathlib import Path
from uuid import uuid4
import config

DEFAULT_MODEL='free-auto'
_context=ContextVar('cloud_model',default=None)
_lock=threading.RLock()
SETTINGS=Path('data/cloud_model_settings.json')
CREDENTIALS=Path('data/cloud_credentials.json')
CATALOG=[
 dict(id='openrouter-free',name='無料クラウド（自動選択）',provider='openrouter',model='openrouter/free',usage='小',performance='モデルにより変動',traits='無料モデルから自動選択。日常会話・試作向け。混雑・回数上限があり、回答ごとにモデルが変わる場合があります。',billing='無料モデル専用',free=True),
 dict(id='openai-nano',name='GPT-4.1 nano',provider='openai',model='gpt-4.1-nano',usage='小',performance='軽い処理向け',traits='短い質問・要約・分類向け。複雑な検討は上位モデルを推奨。',billing='有料：入力 $0.10 / 出力 $0.40',free=False),
 dict(id='openai-mini',name='GPT-4.1 mini',provider='openai',model='gpt-4.1-mini',usage='中',performance='バランス型',traits='日常対話・文章作成・コードの相談向け。速度と費用のバランスを重視。',billing='有料：入力 $0.40 / 出力 $1.60',free=False),
 dict(id='openai-full',name='GPT-4.1',provider='openai',model='gpt-4.1',usage='大',performance='複雑な指示・コード向け',traits='細かな指示、長文の整理、複雑なコードの相談向け。miniより費用が高い。',billing='有料：入力 $2.00 / 出力 $8.00',free=False),
 dict(id='ollama-local',name='Ollama（端末内）',provider='ollama_local',model=config.OLLAMA_MODEL,usage='小',performance='端末・導入モデルによる',traits='既存の端末内モデル。クラウドへ送信しません。Ollamaの起動とモデルの導入が必要です。電力・端末負荷は発生します。',billing='API料金なし（ローカル）',free=True),
]

FREE_LIMITS={
 'openrouter':{'period':'日・分（モデル間で共有する枠あり）','limit_text':'正確な日上限・残り回数は「無料枠を確認」で取得。月固定の無料量ではありません。','url':'https://openrouter.ai/settings/keys'},
 'groq':{'period':'日・分（組織・モデルごと）','limit_text':'参考：各モデル 30回/分・1,000回/日・8,000トークン/分・200,000トークン/日。実際の組織上限を公式画面で確認。月固定枠なし。','url':'https://console.groq.com/settings/limits'},
}
CATALOG.insert(0,dict(id='free-auto',name='無料枠を自動切替（標準）',provider='free_auto',model='free-auto',usage='小',performance='使用中のモデルによる',traits='設定済みの無料クラウドを順に利用。上限・障害時は次へ切替。すべて使えないときは停止して切替を求めます。',billing='無料枠のみ・有料へ自動切替なし',free=True))
for mid,name,size,traits in [
 ('google/gemma-4-31b-it:free','Gemma 4 31B（無料）','中','文章・会話向け。無料提供の有無・混雑により使えない場合があります。'),
 ('nvidia/nemotron-3.5-lightning:free','Nemotron 3.5 Lightning（無料）','中','推論・会話向け。提供元の無料枠を使います。'),
 ('liquid/lfm-2.5-2.6b:free','LFM2.5 2.6B（無料）','小','小型モデル。短い会話・軽い処理向け。複雑な内容の品質は要確認。')]:
 CATALOG.insert(-1,dict(id='or-'+mid.split('/')[0],name=name,provider='openrouter',model=mid,usage=size,performance='用途・入力により変動',traits=traits,billing='無料専用モデル',free=True))
for mid,name in [('openai/gpt-oss-20b','GPT OSS 20B / Groq'),('openai/gpt-oss-120b','GPT OSS 120B / Groq'),('qwen/qwen3.8-27b','Qwen 3.8 27B / Groq')]:
 CATALOG.insert(-1,dict(id='groq-'+mid.split('/')[-1],name=name,provider='groq',model=mid,usage='中',performance='高速推論・コード相談向け',traits='Groqの無料プラン専用アカウントを確認して登録した場合だけ自動切替対象にします。無料枠内でも回数・トークン上限があります。',billing='無料プラン確認が必要',free=True))


def read(path):
    try:
        value=json.loads(path.read_text(encoding='utf-8'));return value if isinstance(value,dict) else {}
    except (OSError,ValueError):return {}

def write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_name(path.name+'.'+uuid4().hex+'.tmp')
    try:temp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8');temp.replace(path)
    finally:temp.unlink(missing_ok=True)

def get(model_id):
    row=next((r for r in CATALOG if r['id']==model_id),None)
    if row is None:raise ValueError('選択できないモデルです。')
    return dict(row)

def session_key(session_id):return hashlib.sha256(str(session_id).encode()).hexdigest()

def selected(session_id=''):
    choice=read(SETTINGS).get(session_key(session_id),DEFAULT_MODEL)
    return choice if any(r['id']==choice for r in CATALOG) else DEFAULT_MODEL

def choose(session_id,model_id):
    get(model_id)
    with _lock:
        settings=read(SETTINGS);settings[session_key(session_id)]=model_id;write(SETTINGS,settings)

@contextmanager
def model_scope(model_id):
    get(model_id);token=_context.set(model_id)
    try:yield
    finally:_context.reset(token)

def current():return get(_context.get() or DEFAULT_MODEL)

def key(provider):
    if provider=='free_auto':return 'configured' if any(key(p) and free_confirmed(p) for p in ('openrouter','groq')) else ''
    if provider=='ollama_local':return 'ollama'
    env={'openrouter':'OPENROUTER_API_KEY','groq':'GROQ_API_KEY','openai':'OPENAI_API_KEY'}[provider]
    existing=config.OPENAI_API_KEY if provider=='openai' else os.getenv(env)
    return (read(CREDENTIALS).get(provider) or existing or '').strip()

def save_key(provider,value,free_plan_confirmed=False):
    if provider not in ('openrouter','openai','groq') or not isinstance(value,str) or not 10<=len(value.strip())<=512 or any(c.isspace() for c in value.strip()):raise ValueError('APIキーを確認してください。')
    with _lock:
        if provider=='groq' and free_plan_confirmed is not True:raise ValueError('Groq無料プラン専用アカウントの確認が必要です。')
        keys=read(CREDENTIALS);keys[provider]=value.strip()
        if provider=='groq':keys['groq_free_confirmed']=True
        write(CREDENTIALS,keys)

def snapshot(session_id):
    from cloud.free_pool import status, QUOTA
    return {'ok':True,'selected':selected(session_id),'default':DEFAULT_MODEL,'free_pool':status(),'quota':read(QUOTA),'models':[{**row,'configured':bool(key(row['provider'])),'connection':'未確認','free_plan_confirmed':free_confirmed(row['provider']),'limits':FREE_LIMITS.get(row['provider'])} for row in CATALOG],
    'note':'使用量の大・中・小は同じ入力・出力を有料モデルに送った場合の相対的な費用目安です。実際のトークン数や性能を保証する評価ではありません。料金は100万トークンあたりのUSD（2026-11-06確認）。無料クラウドにも回数・混雑制限があります。無料が使えなくても有料へ自動切替しません。'}


def free_confirmed(provider):
    if provider in ('openrouter','free_auto','ollama_local'):return True
    return provider=='groq' and read(CREDENTIALS).get('groq_free_confirmed') is True

_outcome=ContextVar('cloud_outcome',default=None)
def clear_outcome():_outcome.set(None)
def set_outcome(value):_outcome.set(value)
def outcome():return _outcome.get()

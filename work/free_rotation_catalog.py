from pathlib import Path
p=Path('cloud/model_catalog.py');s=p.read_text(encoding='utf-8').replace("DEFAULT_MODEL='openrouter-free'","DEFAULT_MODEL='free-auto'")
pos=s.index('\ndef read(path):')
s=s[:pos]+'''
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

'''+s[pos:]
s=s.replace("    if provider=='ollama_local':return 'ollama'", "    if provider=='free_auto':return 'configured' if any(key(p) and free_confirmed(p) for p in ('openrouter','groq')) else ''\n    if provider=='ollama_local':return 'ollama'")
s=s.replace("env='OPENROUTER_API_KEY' if provider=='openrouter' else 'OPENAI_API_KEY'","env={'openrouter':'OPENROUTER_API_KEY','groq':'GROQ_API_KEY','openai':'OPENAI_API_KEY'}[provider]")
s=s.replace('def save_key(provider,value):','def save_key(provider,value,free_plan_confirmed=False):').replace("provider not in ('openrouter','openai')", "provider not in ('openrouter','openai','groq')")
s=s.replace("        keys=read(CREDENTIALS);keys[provider]=value.strip();write(CREDENTIALS,keys)","        if provider=='groq' and free_plan_confirmed is not True:raise ValueError('Groq無料プラン専用アカウントの確認が必要です。')\n        keys=read(CREDENTIALS);keys[provider]=value.strip()\n        if provider=='groq':keys['groq_free_confirmed']=True\n        write(CREDENTIALS,keys)")
s=s.replace("'connection':'未確認'} for row in CATALOG]", "'connection':'未確認','free_plan_confirmed':free_confirmed(row['provider']),'limits':FREE_LIMITS.get(row['provider'])} for row in CATALOG]")
s+='''

def free_confirmed(provider):
    if provider in ('openrouter','free_auto','ollama_local'):return True
    return provider=='groq' and read(CREDENTIALS).get('groq_free_confirmed') is True

_outcome=ContextVar('cloud_outcome',default=None)
def clear_outcome():_outcome.set(None)
def set_outcome(value):_outcome.set(value)
def outcome():return _outcome.get()
'''
p.write_text(s,encoding='utf-8')

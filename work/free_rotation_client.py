from pathlib import Path
p=Path('cloud/openai_client.py');s=p.read_text(encoding='utf-8').replace("@traced_stage('cloud_llm')\ndef ask_cloud_ai(text):","def _ask_one(text):")
s=s.replace("'ollama_local':__import__('config').OLLAMA_HOST.rstrip('/')+'/v1'", "'groq':'https://api.groq.com/openai/v1', 'ollama_local':__import__('config').OLLAMA_HOST.rstrip('/')+'/v1'")
s=s.replace("    if not api_key:","    if provider=='groq' and not model_catalog.free_confirmed(provider):\n        raise RuntimeError('Groq無料プラン専用アカウントの確認が必要です。モデル変更から設定してください。')\n    if not api_key:")
s=s.replace("('OpenRouter' if provider=='openrouter' else 'OpenAI')", "({'openrouter':'OpenRouter','groq':'Groq'}.get(provider,'OpenAI'))")
s=s.replace("        status = 'success'\n        return answer", "        status = 'success'\n        model_catalog.set_outcome({'choice':choice['id'],'provider':provider,'model':getattr(response,'model',model) if isinstance(getattr(response,'model',None),str) else model,'free':choice['free'],'local':provider=='ollama_local'})\n        return answer")
s+='''

@traced_stage('cloud_llm')
def ask_cloud_ai(text):
    model_catalog.clear_outcome()
    if model_catalog.current()['provider']=='free_auto':
        from cloud.free_pool import generate
        return generate(text,_ask_one)
    return _ask_one(text)
''';p.write_text(s,encoding='utf-8')

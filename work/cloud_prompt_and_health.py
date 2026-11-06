from pathlib import Path
p=Path('cloud/openai_client.py');s=p.read_text(encoding='utf-8');s=s.replace('from config import OPENAI_API_KEY','from config import OPENAI_API_KEY\n\nCLOUD_MODEL = \'gpt-4.1-mini\'',1);s=s.replace("model='gpt-4.1-mini'",'model=CLOUD_MODEL');p.write_text(s,encoding='utf-8')
p=Path('local_ai_server.py');s=p.read_text(encoding='utf-8');s=s.replace('from cloud.local_prompt import build_local_prompt','from cloud.local_prompt import build_local_prompt, build_cloud_prompt',1);s=s.replace('from cloud.openai_client import ask_cloud_ai as _ask_cloud_ai', 'from cloud import openai_client as cloud_client\nfrom cloud.openai_client import ask_cloud_ai as _ask_cloud_ai',1)
s=s.replace('    prompt = build_local_prompt(\n      \'次の質問への回答を再生成してください。', "    prompt_builder = build_cloud_prompt if experiment_mode=='CLOUD_FIRST' else build_local_prompt\n    prompt = prompt_builder(\n      '次の質問への回答を再生成してください。",1)
s=s.replace('  prompt = build_local_prompt(\n    llm_message,', "  prompt_builder = build_cloud_prompt if experiment_mode=='CLOUD_FIRST' else build_local_prompt\n  prompt = prompt_builder(\n    llm_message,",1)
s=s.replace('    "local_llm": {\n      "model": config.OLLAMA_MODEL,', '    "cloud": {"model":cloud_client.CLOUD_MODEL, "configured":bool((cloud_client.OPENAI_API_KEY or "").strip())},\n    "local_llm": {\n      "model": config.OLLAMA_MODEL,',1)
a=s.index('  try:\n    version = _ollama_json_get(',s.index('def _health_snapshot'))
s=s[:a]+'''  result['routing_mode']=_resolve_routing_mode(None)
  result['cloud']={'model':cloud_client.CLOUD_MODEL,'configured':bool((cloud_client.OPENAI_API_KEY or '').strip()),'connection':'unverified'}
  if result['routing_mode']=='CLOUD_FIRST':
    result['status']='configured_unverified' if result['cloud']['configured'] else 'configuration_required'
    result['ollama']['checked']=False
    result['latency_ms']=round((time.perf_counter()-started)*1000,1)
    return result

'''+s[a:]
s=s.replace("const modelName = getPathValue(meta, ['local_llm', 'model'], 'unknown');", "const modelName = getPathValue(meta,['routing','default_mode'],'')==='CLOUD_FIRST'?getPathValue(meta,['cloud','model'],'unknown'):getPathValue(meta,['local_llm','model'],'unknown');",1)
s=s.replace('`Ollama: ${modelName}`', '`標準モデル: ${modelName}`',1)
s=s.replace("        const modelName = getPathValue(data, ['ollama', 'model_configured'], data.model || 'unknown');", "        const modelName = data.routing_mode==='CLOUD_FIRST'?data.cloud?.model:getPathValue(data, ['ollama', 'model_configured'], data.model || 'unknown');",1)
s=s.replace('        setStatus(`health: ${data.status} | model: ${modelName}`);', "        setStatus(data.routing_mode==='CLOUD_FIRST'?`クラウド標準 / APIキー${data.cloud?.configured?'設定済み（疎通未確認）':'未設定'} / ${modelName}`:`health: ${data.status} | model: ${modelName}`);",1)
p.write_text(s,encoding='utf-8')

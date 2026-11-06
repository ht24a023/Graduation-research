from pathlib import Path
p=Path('models/evaluation_metrics.py');s=p.read_text(encoding='utf-8');s=s.replace('    notes: str = ""','    notes: str = ""\n    cloud_used: bool | None = None\n    api_fee_status: str = "unknown"\n    cloud_provider: str = ""\n    cloud_model: str = ""')
s=s.replace('        success: bool,\n    ) -> EvaluationRecord:', '        success: bool,\n        api_fee_status: str = "unknown",\n        cloud_provider: str = "",\n        cloud_model: str = "",\n    ) -> EvaluationRecord:')
s=s.replace('        if api_called:\n            actual_cost', '        if api_called and api_fee_status != "free":\n            actual_cost')
s=s.replace('            success=success,\n        )','            success=success,\n            cloud_used=api_called,\n            api_fee_status=api_fee_status if api_called else "none",\n            cloud_provider=cloud_provider, cloud_model=cloud_model,\n        )')
s=s.replace('        "cloud_api_call": cloud_api_call,','        "cloud_api_call": cloud_api_call,\n        "cloud_used": record.cloud_used if record.cloud_used is not None else record.api_called,\n        "api_fee_status": record.api_fee_status,\n        "cloud_provider": record.cloud_provider, "cloud_model": record.cloud_model,\n        "usage_assessment": ("クラウド利用あり／API利用料金なし（無料枠）" if record.api_fee_status=="free" else "クラウド利用あり／API利用料金あり（従量課金）" if record.api_fee_status=="paid" else "クラウド利用あり／API利用料金未確認" if record.api_called else "クラウド利用なし／API利用料金なし"),')
p.write_text(s,encoding='utf-8')
p=Path('local_ai_server.py');s=p.read_text(encoding='utf-8');s=s.replace('  selected_model = model_catalog.selected(session_id)','  selected_model = model_catalog.selected(session_id)\n  model_catalog.clear_outcome()',1)
pos=s.index('  record = evaluation_metrics.build_record(',s.index('def _attach_evaluation('));s=s[:pos]+'''  execution = model_catalog.outcome() if api_called else None
  fee_status = ('free' if execution.get('free') else 'paid') if execution and success and not execution.get('switch_required') else 'unknown'
'''+s[pos:]
pos=s.index('    success=success,',s.index('def _attach_evaluation('));s=s[:pos]+s[pos:].replace('    success=success,','    success=success,\n    api_fee_status=fee_status, cloud_provider=(execution or {}).get("provider", ""), cloud_model=(execution or {}).get("model", ""),',1)
pos=s.index('    _check_chat_cancelled()',s.index('  def finalize(',s.index('def _build_chat_payload(')));s=s[:pos]+'''    nonlocal api_called, cloud_time_sec, local_time_sec
'''+s[pos:]
pos=s.index('    response_text = ',pos);s=s[:pos]+'''    execution = model_catalog.outcome()
    if api_called and execution and execution.get('local'):
      api_called=False
      local_time_sec+=cloud_time_sec;cloud_time_sec=0
      if route in ('cloud_llm','cloud_fallback'):route='local_llm'
'''+s[pos:]
pos=s.index('    if memory_context:',pos);s=s[:pos]+'''    if execution:
      payload['cloud_execution']=execution
      if execution.get('switch_required'):payload['model_switch_required']=True
'''+s[pos:]
s=s.replace("model_catalog.save_key(data.get('provider'),data.get('key'))", "model_catalog.save_key(data.get('provider'),data.get('key'),data.get('free_plan_confirmed',False))")
# Endpoint explicit quota sync and cooldown reset does not generate completions.
s=s.replace("        elif data.get('action')=='select':model_catalog.choose(session_id,data.get('model_id'))", "        elif data.get('action')=='select':model_catalog.choose(session_id,data.get('model_id'))\n        elif data.get('action')=='quota':\n          from cloud.free_pool import sync_openrouter\n          sync_openrouter()")
s=s.replace("      const apiLabel = evaluation.api_called ? 'あり' : 'なし';", "      const apiLabel = evaluation.api_called ? 'あり' : 'なし';")
s=s.replace('runtimeCloud.textContent = evaluation.api_called ? \'使用あり\' : \'未使用\';',"runtimeCloud.textContent = evaluation.api_fee_status==='free'?'クラウド利用あり・料金なし':evaluation.api_called?'使用あり':'未使用';")
s=s.replace('        `API使用：${apiLabel}`,','        evaluation.usage_assessment || `API使用：${apiLabel}`,\n        evaluation.cloud_model ? `使用モデル：${evaluation.cloud_provider} / ${evaluation.cloud_model}` : \'\',')
s=s.replace("          const answer = addBubble('assistant', data.response);", "          const answer = addBubble('assistant', data.response);\n          if(data.evaluation?.usage_assessment){const badge=document.createElement('div');badge.className='chat-version-label';badge.textContent=data.evaluation.usage_assessment+(data.evaluation.cloud_model?' / '+data.evaluation.cloud_model:'');answer.prepend(badge);}")
# Add explicit model switch action in error UI.
s=s.replace("        typing.remove();\n        if (data.ok)","        typing.remove();\n        if(data.model_switch_required)window.dispatchEvent(new CustomEvent('jarvis:free-models-exhausted',{detail:data}));\n        if (data.ok)")
p.write_text(s,encoding='utf-8')
p=Path('cloud/model_catalog.py');s=p.read_text(encoding='utf-8').replace("def snapshot(session_id):\n    return", "def snapshot(session_id):\n    from cloud.free_pool import status, QUOTA\n    return")
s=s.replace("'selected':selected(session_id),'default':DEFAULT_MODEL", "'selected':selected(session_id),'default':DEFAULT_MODEL,'free_pool':status(),'quota':read(QUOTA)")
p.write_text(s,encoding='utf-8')
p=Path('cloud/free_pool.py');s=p.read_text(encoding='utf-8');s=s.replace("state=catalog.read(STATE);state[row['id']]={'until':until,'reason':reason,'status':code};catalog.write(STATE,state)","state=catalog.read(STATE)\n                affected=[r for r in candidates() if r['provider']==row['provider']] if code in (401,402,403) or (code==429 and row['provider']=='openrouter') else [row]\n                for affected_row in affected:state[affected_row['id']]={'until':until,'reason':reason,'status':code}\n                catalog.write(STATE,state)")
p.write_text(s,encoding='utf-8')
p=Path('functions/research_report.py');s=p.read_text(encoding='utf-8').replace("'cloud_count':cloud,'api_known':len(known_api)","'cloud_count':cloud,'free_cloud_count':sum(r.get('api_fee_status')=='free' and r.get('api_called') is True for r in rows),'paid_cloud_count':sum(r.get('api_fee_status')=='paid' and r.get('api_called') is True for r in rows),'api_known':len(known_api)")
s=s.replace("'cloud':'クラウドLLMの利用。検索・天気などの外部通信は含みません。'", "'cloud':'クラウドLLMの利用。無料クラウドも利用ありとして計上し、API料金なしの件数を別集計します。検索・天気などの外部通信は含みません。'");p.write_text(s,encoding='utf-8')
p=Path('site/dashboard/research.js');s=p.read_text(encoding='utf-8').replace("['記録件数',all.count+'件']", "['記録件数',all.count+'件'],['無料クラウド利用',all.free_cloud_count+'件'],['有料クラウド利用',all.paid_cloud_count+'件']");p.write_text(s,encoding='utf-8')
p=Path('conftest.py');s=p.read_text(encoding='utf-8').replace('    from models.api_usage import ApiUsage','    from cloud import free_pool\n    monkeypatch.setattr(free_pool, "STATE", tmp_path/"free-state.json")\n    monkeypatch.setattr(free_pool, "QUOTA", tmp_path/"free-quota.json")\n    from models.api_usage import ApiUsage');p.write_text(s,encoding='utf-8')

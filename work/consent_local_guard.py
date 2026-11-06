from pathlib import Path
p=Path('local_ai_server.py');s=p.read_text(encoding='utf-8');s=s.replace('  if approve_token:\n    pending =', '  if approve_token:\n    if experiment_mode == "LOCAL_ONLY":\n      return finalize(ok=False, route="error", error="LOCAL_ONLYモードではクラウドAPIを呼び出しません。")\n    pending =',1);p.write_text(s,encoding='utf-8')

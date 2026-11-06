from pathlib import Path
p=Path('local_ai_server.py');s=p.read_text(encoding='utf-8')
s=s.replace('  <script src="/site/dashboard/neural_core.js"></script>', '  <script src="/site/dashboard/neural_core.js"></script>\n  <link rel="stylesheet" href="/site/dashboard/research.css" />\n  <script src="/site/dashboard/research.js"></script>')
s=s.replace('if path in {"/site/dashboard/neural_core.js",', 'if path in {"/site/dashboard/research.js", "/site/dashboard/research.css", "/site/dashboard/neural_core.js",')
s=s.replace('    if path == "/memory/graph":', '''    if path == "/research/summary":
      if not self._notification_guard():
        return
      from functions.research_report import build_report
      try:
        mode = str((query.get('mode') or [''])[0])
        experiments_only = (query.get('experiments_only') or ['0'])[0] == '1'
        self._send_json(build_report(evaluation_metrics.load_all(), mode, experiments_only))
      except ValueError as exc:
        self._send_json({'ok': False, 'error': str(exc)}, status=400)
      return

    if path == "/memory/graph":''',1)
# Preserve memory references through approved cloud and cached answers.
s=s.replace('"age_sec": max(0.0,', '"memory_context": cached.get("memory_context", []),\n      "age_sec": max(0.0,',1)
s=s.replace('"cached_at": now,', '"memory_context": payload.get("memory_context", []),\n      "cached_at": now,',1)
s=s.replace('    if cached and cached.get("response"):\n      update_profile', '    if cached and cached.get("response"):\n      memory_context = cached.get("memory_context", [])\n      update_profile',1)
s=s.replace('    cloud_started = time.perf_counter()\n    try:\n      reply_style = normalize_style(pending', '    memory_context = pending.get("memory_context", [])\n    cloud_started = time.perf_counter()\n    try:\n      reply_style = normalize_style(pending',1)
s=s.replace('"approval_group": approval_group,', '"approval_group": approval_group,\n        "memory_context": memory_context,')
p.write_text(s,encoding='utf-8')
p=Path('site/dashboard/workbench.js');s=p.read_text(encoding='utf-8');s=s.replace('reply_style:data.reply_style}}));','reply_style:data.reply_style,memory_context:data.memory_context||[],cached:!!data.cache?.hit}}));',1);p.write_text(s,encoding='utf-8')

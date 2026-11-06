from pathlib import Path
p=Path('local_ai_server.py')
s=p.read_text(encoding='utf-8')
s=s.replace('  <script src="/site/dashboard/spatial.js"></script>', '  <script src="/site/dashboard/spatial.js"></script>\n  <link rel="stylesheet" href="/site/dashboard/neural_core.css" />\n  <script src="/site/dashboard/neural_core.js"></script>')
s=s.replace('if path in {"/site/dashboard/dashboard.css",', 'if path in {"/site/dashboard/neural_core.js", "/site/dashboard/neural_core.css", "/site/dashboard/dashboard.css",')
s=s.replace('    if path == "/storage":', '''    if path == "/memory/graph":
      from functions.memory_graph import snapshot
      self._send_json(snapshot())
      return

    if path == "/storage":''')
s=s.replace('    if path == \'/browser/launch\':', '''    if path == '/memory/graph':
      if not self._notification_guard(write=True):
        return
      try:
        length = int(self.headers.get('Content-Length', '0'))
        if not 0 < length <= 40000:
          raise ValueError('送信内容が長すぎます。')
        data = json.loads(self.rfile.read(length).decode('utf-8'))
        from functions.memory_graph import mutate
        self._send_json(mutate(data))
      except (ValueError, TypeError, UnicodeError) as exc:
        self._send_json({'ok': False, 'error': str(exc)}, status=400)
      return

    if path == '/browser/launch\':''')
p.write_text(s,encoding='utf-8')

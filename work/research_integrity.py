from pathlib import Path
p=Path('local_ai_server.py');s=p.read_text(encoding='utf-8');s=s.replace('    _SESSION_LOCATION_CONTEXT.pop(session_id, None)\n    return cleared_history', '    _SESSION_LOCATION_CONTEXT.pop(session_id, None)\n    _clear_pending_api_approval_for_session(session_id)\n    return cleared_history',1);s=s.replace('    _SESSION_LOCATION_CONTEXT.clear()\n\n\ndef _list_sessions', '    _SESSION_LOCATION_CONTEXT.clear()\n    _PENDING_API_APPROVAL.clear()\n\n\ndef _list_sessions',1);p.write_text(s,encoding='utf-8')
p=Path('models/evaluation_metrics.py');s=p.read_text(encoding='utf-8');s=s.replace('self._lock = threading.Lock()', 'self._lock = threading.RLock()')
s=s.replace('                        records.append(json.loads(line))', '                        row = json.loads(line)\n                        if isinstance(row, dict):\n                            records.append(row)')
a=s.index('        records = self._normalize_records(self.load_all())\n        updated = False',s.index('    def set_user_feedback'));b=s.index('\n    def export_csv',a)
chunk=s[a:b];s=s[:a]+'        with self._lock:\n'+''.join('    '+line if line.strip() else line for line in chunk.splitlines(keepends=True))+s[b:]
s=s.replace('        quality_passed = rating in {"good", "partial"}', '        if rating not in {"good", "partial", "bad"}:\n            return False\n        quality_passed = rating in {"good", "partial"}',1)
p.write_text(s,encoding='utf-8')
p=Path('site/dashboard/neural_core.js');s=p.read_text(encoding='utf-8');s=s.replace("let contextRefs=[],contextCached=false;", "let contextRefs=[],contextCached=false,coreVisible=true;")
s=s.replace('if(document.hidden||now-last<40)return;', 'if(document.hidden||now-last<66)return;')
s=s.replace('draw(canvas,false,phase);if(expanded)', "if(coreVisible&&!expanded&&!document.querySelector('.jarvis-shell')?.classList.contains('embedded-browser-open'))draw(canvas,false,phase);if(expanded)")
s=s.replace('new ResizeObserver(()=>dirty=true).observe(core);', 'new IntersectionObserver(entries=>{coreVisible=entries[0].isIntersecting;dirty=true;}).observe(core);new ResizeObserver(()=>dirty=true).observe(core);')
p.write_text(s,encoding='utf-8')

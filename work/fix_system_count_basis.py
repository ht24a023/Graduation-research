from pathlib import Path
p=Path('functions/system_monitor.py');s=p.read_text(encoding='utf-8')
s=s.replace('            native=self._native.sample()', "            try:native=self._native.sample()\n            except (OSError,RuntimeError):native={}",1)
s=s.replace('            process_ids = optional(psutil.pids)', "            process_ids = optional(psutil.pids)\n            from functions.windows_performance import system_counts\n            counts=system_counts()",1)
s=s.replace("'system_process_count':len(process_ids) if process_ids is not None else None,", "'system_process_count':counts.get('processes',len(process_ids) if process_ids is not None else None),\n                            'system_thread_count':counts.get('threads'),\n                            'visible_process_count':len(process_ids) if process_ids is not None else None,",1)
p.write_text(s,encoding='utf-8')
p=Path('site/dashboard/maximalist.js');s=p.read_text(encoding='utf-8');s=s.replace("${p.threads??'—'} / ${p.system_process_count??'—'}", "${p.system_thread_count??'—'} / ${p.system_process_count??'—'}",1);p.write_text(s,encoding='utf-8')
p=Path('tests/test_system_monitor_extended.py');s=p.read_text(encoding='utf-8');s=s.replace("with patch('functions.system_monitor.psutil.pids', side_effect=OSError('unavailable')):", "with patch('functions.windows_performance.system_counts', return_value={}), patch('functions.system_monitor.psutil.pids', side_effect=OSError('unavailable')):");p.write_text(s,encoding='utf-8')

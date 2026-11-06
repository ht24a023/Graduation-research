from pathlib import Path
p=Path('functions/work_memory.py');s=p.read_text(encoding='utf-8');s=s.replace("return f'作業要約 [{key[:6]}]',f'作業要約の更新案 [{key[:6]}]'", "return f'作業要約 [{key}]',f'作業要約の更新案 [{key}]'",1)
s=s.replace("if n.get('title')==title),None) for title in (main,proposal)}", "if n.get('title')==title and n.get('source')=='cloud_work_summary' and n.get('work_session_key')==key),None) for title in (main,proposal)}",1)
s=s.replace("if current[target] is not None and current[target].get('source')!='cloud_work_summary':", "if current[target] is not None and (current[target].get('source')!='cloud_work_summary' or current[target].get('work_session_key')!=key):",1)
p.write_text(s,encoding='utf-8')
# Make the cloud-first browser check wait for actual app readiness, not unrelated load timing.
p=Path('tests/test_cloud_first_browser.py');s=p.read_text(encoding='utf-8');s=s.replace("page.goto(f'http://127.0.0.1:{http.server_port}',wait_until='domcontentloaded')", "page.goto(f'http://127.0.0.1:{http.server_port}',wait_until='commit',timeout=60000)");s=s.replace("page.wait_for_function(\"document.getElementById('runtime-model').textContent==='gpt-4.1-mini'\")", "page.wait_for_function(\"window.memoryNetwork && document.getElementById('runtime-model')?.textContent==='gpt-4.1-mini'\",timeout=60000)");p.write_text(s,encoding='utf-8')

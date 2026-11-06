from pathlib import Path
p=Path('tests/test_post_answer_cloud_browser.py');s=p.read_text(encoding='utf-8');s=s.replace("document.getElementById('hud-cpu').textContent==='44.0%'", "document.getElementById('hud-cpu')?.textContent==='44.0%'");p.write_text(s,encoding='utf-8')

from pathlib import Path
p=Path('site/dashboard/left_monitor.js');s=p.read_text(encoding='utf-8');s=s.replace('(current-previous.total)/elapsed/Math.max(1,data.cpu.logical_cores||1)*100:null;', 'Math.max(0,Math.min(100,(current-previous.total)/elapsed/Math.max(1,data.cpu.logical_cores||1)*100)):null;',1);p.write_text(s,encoding='utf-8')
p=Path('site/dashboard/maximalist.js');s=p.read_text(encoding='utf-8');s=s.replace("text('hud-cpu',pct(data.cpu.usage_percent));", "text('hud-cpu',pct(data.cpu.usage_percent));$('hud-cpu')?.setAttribute('title',data.cpu.usage_source||'OS CPU実測値');",1);p.write_text(s,encoding='utf-8')
p=Path('functions/system_monitor.py');s=p.read_text(encoding='utf-8');s=s.replace("'sample_interval_sec': elapsed,", "'sample_interval_sec': elapsed, 'source':'OS all interfaces combined',",1);p.write_text(s,encoding='utf-8')
# Keep the unavailable-network contract: an absent source stays unknown too.
s=p.read_text(encoding='utf-8');s=s.replace("'source':'OS all interfaces combined',", "'source':'OS all interfaces combined' if network else None,",1);p.write_text(s,encoding='utf-8')

from pathlib import Path
p=Path('site/dashboard/neural_core.js');s=p.read_text(encoding='utf-8');s=s.replace("x.fillText(p.n.title.slice(0,18),p.x+9,p.y+4);", "const label=p.n.title.slice(0,18),tw=x.measureText(label).width;x.fillText(label,Math.max(8,Math.min(w-tw-8,p.x+9)),p.y+17);")
p.write_text(s,encoding='utf-8')
p=Path('tests/test_neural_core.py');s=p.read_text(encoding='utf-8');s=s.replace("page.locator('#neural-open').click()\n            page.get_by_label", "page.screenshot(path=str(__import__('pathlib').Path(server.__file__).parent/'work/neural-core-overview.png'))\n            page.locator('#neural-open').click()\n            page.get_by_label",1);p.write_text(s,encoding='utf-8')

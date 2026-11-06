from pathlib import Path
p=Path('functions/research_report.py');s=p.read_text(encoding='utf-8');s=s.replace("'cost':'料金とトークンの実測値", "'background_memory':'作業要約は追加のAPI利用です。ここでの会話応答の件数・時間には含みません。自動要約の状態と別記録で確認できます。',\n                'cost':'料金とトークンの実測値",1);p.write_text(s,encoding='utf-8')

"""A local, inspectable graph over the same notes used by conversation context."""
import hashlib
import re
from models import user_profile_memory as memory


def _terms(text):
    # Japanese bigrams allow shared subjects without a cloud model/tokenizer.
    chunks = re.findall(r'[a-z0-9]{2,}|[一-龯ぁ-んァ-ヶー]{2,}', text.lower())
    return {part for chunk in chunks for part in ([chunk] if chunk.isascii() else [chunk[i:i+2] for i in range(len(chunk)-1)])}


def snapshot():
    with memory._LOCK:
        notes = memory.load_notes().get('notes', [])
        nodes = [{'id': hashlib.sha256(n['title'].encode()).hexdigest()[:16], 'title': n['title'], 'content': n.get('content', ''), 'updated_at': n.get('updated_at', ''), 'source': ('クラウド作業要約・更新案' if n.get('summary_proposal') else 'クラウド作業要約（AI生成）') if n.get('source')=='cloud_work_summary' else '保存メモ', 'user_edited':bool(n.get('user_edited')), 'summary_revision':n.get('summary_revision'), 'kind':n.get('type','note')} for n in notes if n.get('title')]
    terms = {n['id']: _terms(n['title'] + ' ' + n['content']) for n in nodes}
    edges = []
    for i, a in enumerate(nodes):
        for b in nodes[i+1:]:
            common = sorted(terms[a['id']] & terms[b['id']])
            if len(common) >= 2:
                edges.append({'source': a['id'], 'target': b['id'], 'terms': common[:8], 'weight': len(common)})
    return {'ok': True, 'nodes': nodes, 'edges': edges, 'relation': '共通語による関連（AIの思考経路ではありません）', 'context_note': '保存メモは既存の会話用記憶に接続されます。毎回すべてのメモが参照されるわけではありません。'}


def mutate(data):
    if not isinstance(data, dict):
        raise ValueError('入力形式が不正です。')
    action, title = data.get('action'), data.get('title', '')
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 100:
        raise ValueError('タイトルは1〜100文字で入力してください。')
    title = title.strip()
    with memory._LOCK:
        notes = memory.load_notes().get('notes', [])
        exists = any(n.get('title') == title for n in notes)
        if action == 'delete':
            if not exists:
                raise ValueError('記憶が見つかりません。更新してください。')
            memory.delete_titled_note(title)
        elif action in ('add', 'update'):
            content = data.get('content', '')
            if not isinstance(content, str) or not 1 <= len(content.strip()) <= 8000:
                raise ValueError('内容は1〜8000文字で入力してください。')
            if (action == 'add' and exists) or (action == 'update' and not exists):
                raise ValueError('同名の記憶があるか、編集対象が削除されています。更新してください。')
            if action == 'add' and len(notes) >= memory._MAX_NOTES:
                raise ValueError('記憶が上限に達しました。不要な記憶を整理してください。')
            note=next((n for n in notes if n.get('title')==title),None)
            if note and note.get('source')=='cloud_work_summary':
                store=memory.load_notes()
                for saved in store['notes']:
                    if saved.get('title')==title:
                        saved.update(content=content.strip(),user_edited=True,updated_at=memory._now_iso())
                memory.save_notes(store)
            else:
                memory.upsert_titled_note(title, content.strip())
        else:
            raise ValueError('操作が不正です。')
        return snapshot()

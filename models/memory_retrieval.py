"""Deterministic, local retrieval of saved notes with inspectable matches."""
import hashlib
import re
import os


def terms(text):
    chunks = re.findall(r'[a-z0-9]{2,}|[一-龯ぁ-んァ-ヶー]{2,}', text.lower())
    return {part for chunk in chunks for part in ([chunk] if chunk.isascii() else [chunk[i:i+2] for i in range(len(chunk)-1)])}


def note_id(title):
    return hashlib.sha256(title.encode()).hexdigest()[:16]


def retrieve(query, notes, limit=4):
    query_terms = terms(query)
    ranked = []
    for i, note in enumerate(notes):
        title, content = str(note.get('title', '')), str(note.get('content', ''))
        if not title or not content:
            continue
        title_matches = query_terms & terms(title)
        common = query_terms & terms(title + ' ' + content)
        # Avoid claiming a relation from a single generic Japanese bigram.
        exact = title.lower() in query.lower()
        latin = any(part.isascii() for part in common)
        if not exact and len(common) < 2 and not latin:
            continue
        score = len(common) + 3 * len(title_matches) + (12 if exact else 0)
        ranked.append((score, i, {'id':note_id(title), 'title':title,
                       'content':content[:1400], 'updated_at':note.get('updated_at',''),
                       'matched_terms':sorted(common)[:12], 'selection':'共通語による選択',
                       'score':score, 'truncated':len(content)>1400}))
    ranked.sort(key=lambda row:(row[0],row[1]),reverse=True)
    return [row[2] for row in ranked[:limit]]


def memory_revision():
    from models import user_profile_memory as memory
    stamps=[]
    for path in (memory._PROFILE_PATH,memory._NOTES_PATH,memory._KEEP_REQUESTS_PATH):
        try:
            stat=os.stat(path);stamps.append((str(path),stat.st_mtime_ns,stat.st_size))
        except FileNotFoundError:stamps.append((str(path),None))
    return hashlib.sha256(repr(stamps).encode()).hexdigest()[:20]

from __future__ import annotations

import json
import os
import re
import threading
import hashlib
from datetime import datetime
from typing import Any

_PROFILE_PATH = os.path.join("data", "user_profile.json")
_NOTES_PATH = os.path.join("data", "user_notes.json")
_KEEP_REQUESTS_PATH = os.path.join("data", "user_keep_requests.json")
_TEXT_DOCS_DIR = os.path.join("data", "documents")
_TEXT_DOCS_DB_PATH = os.path.join("data", "documents_db.txt")
_DOC_SESSION_PATH = os.path.join("data", "document_session.json")
_VIEW_PATH = os.path.join("data", "user_memory_view.json")
_LOCK = threading.RLock()

_MAX_FACTS = 24
_MAX_PREFERENCES = 24
_MAX_NOTES = 40
_MAX_KEEP_REQUESTS = 120
_MAX_KEEP_CONTENT = 20000
_MAX_DOC_LIST = 12
_LONG_TEXT_TO_DOC_THRESHOLD = 320
_PRIORITY_DEFAULT = "medium"

_ACTION_VERB_PATTERN = re.compile(r"(する|提出|比較|決める|準備|調べる|応募|連絡|実施|作成|改善|練習|確認|買う|増やす)")

_AUTO_TEMPLATE_TASKS = {
    "自己分析を進める",
    "応募企業を10社リスト化",
    "ESを作成して提出",
    "面接対策を実施",
    "予算上限を決める",
    "候補車種を比較",
    "維持費を試算",
    "購入時期を決める",
    "出会いの場を増やす",
    "週1回は新しい行動をする",
    "会話力を磨く",
    "清潔感のある身だしなみを整える",
}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _default_profile() -> dict[str, Any]:
    return {
        "name": "",
        "location": "",
        "likes": [],
        "dislikes": [],
        "facts": [],
        "updated_at": _now_iso(),
    }


def _ensure_profile_file() -> None:
    os.makedirs(os.path.dirname(_PROFILE_PATH), exist_ok=True)
    if not os.path.exists(_PROFILE_PATH):
        with open(_PROFILE_PATH, "w", encoding="utf-8") as f:
            json.dump(_default_profile(), f, ensure_ascii=False, indent=2)


def _default_notes() -> dict[str, Any]:
    return {
        "notes": [],
        "updated_at": _now_iso(),
    }


def _default_keep_requests() -> dict[str, Any]:
    return {
        "items": [],
        "updated_at": _now_iso(),
    }


def _default_document_session() -> dict[str, Any]:
    return {
        "current_doc_id": "",
        "current_title": "",
        "current_file_path": "",
        "pending_choices": [],
        "pending_keyword": "",
        "updated_at": _now_iso(),
    }


def _ensure_text_documents_store() -> None:
    os.makedirs(_TEXT_DOCS_DIR, exist_ok=True)
    if not os.path.exists(_TEXT_DOCS_DB_PATH):
        with open(_TEXT_DOCS_DB_PATH, "w", encoding="utf-8") as f:
            f.write("# documents_db (tab-separated)\n")
            f.write("# doc_id\tcreated_at\tupdated_at\tstatus\ttitle\tfile_path\tchars\tchecksum\n")


def _ensure_document_session_file() -> None:
    os.makedirs(os.path.dirname(_DOC_SESSION_PATH), exist_ok=True)
    if not os.path.exists(_DOC_SESSION_PATH):
        with open(_DOC_SESSION_PATH, "w", encoding="utf-8") as f:
            json.dump(_default_document_session(), f, ensure_ascii=False, indent=2)


def _iter_documents_db_rows() -> list[list[str]]:
    _ensure_text_documents_store()
    rows: list[list[str]] = []
    try:
        with open(_TEXT_DOCS_DB_PATH, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.rstrip("\n")
                if not line or line.startswith("#"):
                    continue
                cols = line.split("\t")
                if len(cols) < 8:
                    continue
                rows.append(cols)
    except Exception:
        return []
    return rows


def _write_documents_db_rows(rows: list[list[str]]) -> None:
    _ensure_text_documents_store()
    with open(_TEXT_DOCS_DB_PATH, "w", encoding="utf-8") as f:
        f.write("# documents_db (tab-separated)\n")
        f.write("# doc_id\tcreated_at\tupdated_at\tstatus\ttitle\tfile_path\tchars\tchecksum\n")
        for cols in rows:
            if len(cols) < 8:
                continue
            f.write("\t".join(cols[:8]) + "\n")


def _next_document_id() -> str:
    rows = _iter_documents_db_rows()
    max_num = 0
    for cols in rows:
        doc_id = (cols[0] or "").strip()
        m = re.match(r"^DOC(\d+)$", doc_id)
        if not m:
            continue
        try:
            num = int(m.group(1))
            if num > max_num:
                max_num = num
        except Exception:
            continue
    return f"DOC{max_num + 1:06d}"


def _clean_title_for_db(title: str) -> str:
    return (title or "").replace("\t", " ").replace("\n", " ").strip()


def _build_document_file_path(doc_id: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(_TEXT_DOCS_DIR, f"{doc_id}_{stamp}.txt")


def _write_document_text_file(doc_id: str, title: str, content: str, checksum: str, saved_at: str) -> str:
    _ensure_text_documents_store()
    abs_path = _build_document_file_path(doc_id)
    body = (content or "").replace("\r\n", "\n")
    with open(abs_path, "w", encoding="utf-8") as f:
        f.write(f"# Document ID: {doc_id}\n")
        f.write(f"# Title: {title}\n")
        f.write(f"# Created At: {saved_at}\n")
        f.write(f"# Updated At: {saved_at}\n")
        f.write("# Status: active\n")
        f.write(f"# Checksum: {checksum}\n")
        f.write("\n")
        f.write("----- BODY -----\n")
        f.write(body)
        if not body.endswith("\n"):
            f.write("\n")
    return abs_path


def _append_document_db_row(
    doc_id: str,
    created_at: str,
    updated_at: str,
    status: str,
    title: str,
    file_path: str,
    char_count: int,
    checksum: str,
) -> None:
    _ensure_text_documents_store()
    title_col = _clean_title_for_db(title)
    rel_path = file_path.replace("\\", "/")
    row = "\t".join(
        [
            doc_id,
            created_at,
            updated_at,
            status,
            title_col,
            rel_path,
            str(char_count),
            checksum,
        ]
    )
    with open(_TEXT_DOCS_DB_PATH, "a", encoding="utf-8") as f:
        f.write(row + "\n")


def _is_document_list_request(text: str) -> bool:
    return bool(re.search(r"(?:文書|文章|ドキュメント).*(?:一覧|見せて|表示)", text))


def build_document_list_text(max_items: int = _MAX_DOC_LIST) -> str:
    rows = _iter_documents_db_rows()
    if not rows:
        return "保存文書はまだありません。"

    lines = ["保存文書一覧:"]
    target = rows[-max_items:]
    for cols in target:
        doc_id, _created, _updated, status, title, file_path, chars, _checksum = cols[:8]
        lines.append(f"- {doc_id} [{status}] {title} ({chars}文字) -> {file_path}")
    return "\n".join(lines)


def _load_document_session() -> dict[str, Any]:
    _ensure_document_session_file()
    try:
        with open(_DOC_SESSION_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _default_document_session()
        base = _default_document_session()
        base.update(data)
        return base
    except Exception:
        return _default_document_session()


def _save_document_session(session: dict[str, Any]) -> None:
    _ensure_document_session_file()
    payload = dict(session)
    payload["updated_at"] = _now_iso()
    with open(_DOC_SESSION_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _set_current_document(item: dict[str, Any]) -> None:
    current = _load_document_session()
    _save_document_session(
        {
            "current_doc_id": (item.get("doc_id") or "").strip(),
            "current_title": (item.get("title") or "").strip(),
            "current_file_path": (item.get("file_path") or "").strip(),
            "pending_choices": current.get("pending_choices", []),
            "pending_keyword": current.get("pending_keyword", ""),
        }
    )


def _set_pending_document_choices(keyword: str, docs: list[dict[str, Any]]) -> None:
    current = _load_document_session()
    choices: list[dict[str, Any]] = []
    for idx, doc in enumerate(docs, start=1):
        choices.append(
            {
                "index": idx,
                "doc_id": (doc.get("doc_id") or "").strip(),
                "title": (doc.get("title") or "").strip(),
                "file_path": (doc.get("file_path") or "").strip(),
            }
        )
    _save_document_session(
        {
            "current_doc_id": current.get("current_doc_id", ""),
            "current_title": current.get("current_title", ""),
            "current_file_path": current.get("current_file_path", ""),
            "pending_choices": choices,
            "pending_keyword": (keyword or "").strip(),
        }
    )


def _clear_pending_document_choices() -> None:
    current = _load_document_session()
    _save_document_session(
        {
            "current_doc_id": current.get("current_doc_id", ""),
            "current_title": current.get("current_title", ""),
            "current_file_path": current.get("current_file_path", ""),
            "pending_choices": [],
            "pending_keyword": "",
        }
    )


def _clear_current_document_selection() -> None:
    current = _load_document_session()
    _save_document_session(
        {
            "current_doc_id": "",
            "current_title": "",
            "current_file_path": "",
            "pending_choices": current.get("pending_choices", []),
            "pending_keyword": current.get("pending_keyword", ""),
        }
    )


def _read_document_body(file_path: str) -> str:
    path = (file_path or "").strip()
    if not path:
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except Exception:
        return ""

    marker = "----- BODY -----"
    if marker in raw:
        return raw.split(marker, 1)[1].lstrip("\r\n").rstrip("\r\n")
    return raw.strip()


def _resolve_document_content(item: dict[str, Any]) -> str:
    if not isinstance(item, dict):
        return ""
    file_path = (item.get("file_path") or "").strip()
    content = _read_document_body(file_path)
    if content:
        return content
    return (item.get("content") or "").strip()


def _document_items() -> list[dict[str, Any]]:
    data = load_keep_requests()
    items = data.get("items", [])
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if (item.get("type") or "") != "document":
            continue
        out.append(item)
    return out


def _document_sort_key(item: dict[str, Any]) -> str:
    if not isinstance(item, dict):
        return ""
    return (
        (item.get("saved_at") or "").strip()
        or (item.get("updated_at") or "").strip()
        or (item.get("doc_id") or "").strip()
    )


def _serialize_document_item(item: dict[str, Any], include_content: bool = False) -> dict[str, Any]:
    title = (item.get("title") or "").strip()
    content = _resolve_document_content(item)
    file_path = (item.get("file_path") or "").strip()
    doc_id = (item.get("doc_id") or "").strip()
    payload = {
        "doc_id": doc_id,
        "title": title,
        "file_path": file_path,
        "chars": int(item.get("chars") or len(content) or 0),
        "checksum": (item.get("checksum") or "").strip(),
        "preview": (item.get("preview") or _truncate(content.replace("\n", " "), 120)).strip(),
        "source": (item.get("source") or "").strip(),
        "saved_at": (item.get("saved_at") or "").strip(),
        "updated_at": (item.get("updated_at") or "").strip(),
        "is_current": False,
    }
    if include_content:
        payload["content"] = content
    return payload


def get_document_session() -> dict[str, Any]:
    with _LOCK:
        session = _load_document_session()
        return {
            "current_doc_id": (session.get("current_doc_id") or "").strip(),
            "current_title": (session.get("current_title") or "").strip(),
            "current_file_path": (session.get("current_file_path") or "").strip(),
            "pending_choices": session.get("pending_choices", []),
            "pending_keyword": (session.get("pending_keyword") or "").strip(),
            "updated_at": (session.get("updated_at") or "").strip(),
        }


def list_document_items(max_items: int | None = None) -> list[dict[str, Any]]:
    with _LOCK:
        docs = sorted(_document_items(), key=_document_sort_key, reverse=True)
        if max_items is not None:
            docs = docs[:max_items]
        session = _load_document_session()
        current_doc_id = (session.get("current_doc_id") or "").strip()
        current_path = (session.get("current_file_path") or "").strip()
        current_title = (session.get("current_title") or "").strip()

        out: list[dict[str, Any]] = []
        for item in docs:
            payload = _serialize_document_item(item)
            payload["is_current"] = bool(
                (current_doc_id and payload["doc_id"] == current_doc_id)
                or (current_path and payload["file_path"] == current_path)
                or (current_title and payload["title"] == current_title)
            )
            out.append(payload)
        return out


def get_document_item(doc_id: str = "", file_path: str = "", title: str = "") -> dict[str, Any] | None:
    with _LOCK:
        item = _find_document_exact(doc_id=doc_id, file_path=file_path, title=title)
        if not item:
            return None
        payload = _serialize_document_item(item, include_content=True)
        session = _load_document_session()
        payload["is_current"] = bool(
            (session.get("current_doc_id") or "").strip() == payload["doc_id"]
            or (session.get("current_file_path") or "").strip() == payload["file_path"]
            or (session.get("current_title") or "").strip() == payload["title"]
        )
        return payload


def get_current_document_item() -> dict[str, Any] | None:
    with _LOCK:
        item = _find_document_by_session()
        if not item:
            return None
        payload = _serialize_document_item(item, include_content=True)
        payload["is_current"] = True
        return payload


def _remove_document_db_entry(doc_id: str = "", file_path: str = "") -> None:
    rows = _iter_documents_db_rows()
    if not rows:
        return
    target_doc_id = (doc_id or "").strip()
    target_file_path = (file_path or "").replace("\\", "/").strip()
    filtered: list[list[str]] = []
    for cols in rows:
        if len(cols) < 8:
            continue
        row_doc_id = (cols[0] or "").strip()
        row_file_path = (cols[5] or "").replace("\\", "/").strip()
        if (target_doc_id and row_doc_id == target_doc_id) or (target_file_path and row_file_path == target_file_path):
            continue
        filtered.append(cols)
    _write_documents_db_rows(filtered)


def _delete_document_file(file_path: str) -> None:
    path = (file_path or "").strip()
    if not path:
        return
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        return


def update_document_item(doc_id: str, title: str | None = None, content: str | None = None) -> dict[str, Any]:
    with _LOCK:
        item = _find_document_exact(doc_id=doc_id)
        if not item:
            return {"ok": False, "error": f"指定された文書が見つかりませんでした。doc_id: {doc_id}"}

        current_content = _resolve_document_content(item)
        new_title = (title if title is not None else item.get("title") or "").strip()
        new_content = current_content if content is None else (content or "").strip()
        if not new_title:
            new_title = "無題"
        if not new_content:
            return {"ok": False, "error": "本文が空のため更新できません。"}

        if not _update_document_text_file(item, new_content, new_title=new_title):
            return {"ok": False, "error": "文書更新に失敗しました。"}

        _set_current_document(item)
        return {"ok": True, "document": _serialize_document_item(item, include_content=True)}


def delete_document_item(doc_id: str) -> dict[str, Any]:
    with _LOCK:
        item = _find_document_exact(doc_id=doc_id)
        if not item:
            return {"ok": False, "error": f"指定された文書が見つかりませんでした。doc_id: {doc_id}"}

        file_path = (item.get("file_path") or "").strip()
        title = (item.get("title") or "").strip()
        serialized = _serialize_document_item(item, include_content=True)

        data = load_keep_requests()
        items = data.get("items", []) if isinstance(data.get("items"), list) else []
        next_items = []
        removed = False
        for target in items:
            if not isinstance(target, dict):
                continue
            if (target.get("type") or "") != "document":
                next_items.append(target)
                continue
            same_doc = bool(doc_id and (target.get("doc_id") or "").strip() == doc_id.strip())
            same_path = bool(file_path and (target.get("file_path") or "").strip() == file_path)
            same_title = bool(title and (target.get("title") or "").strip() == title)
            if same_doc or same_path or same_title:
                removed = True
                continue
            next_items.append(target)

        if not removed:
            return {"ok": False, "error": "文書の削除対象が見つかりませんでした。"}

        data["items"] = next_items
        save_keep_requests(data)
        _remove_document_db_entry(doc_id=doc_id, file_path=file_path)
        _delete_document_file(file_path)

        session = _load_document_session()
        current_id = (session.get("current_doc_id") or "").strip()
        current_path = (session.get("current_file_path") or "").strip()
        current_title = (session.get("current_title") or "").strip()
        if current_id == doc_id.strip() or current_path == file_path or current_title == title:
            _clear_current_document_selection()

        return {"ok": True, "deleted": serialized}


def _find_document_by_keyword(keyword: str) -> dict[str, Any] | None:
    docs = _document_items()
    if not docs:
        return None

    key = (keyword or "").strip().lower()
    if not key:
        return docs[-1]

    best = None
    best_score = -1
    for item in docs:
        title = (item.get("title") or "")
        preview = (item.get("preview") or "")
        score = 0
        if key in title.lower():
            score += 3
        if key in preview.lower():
            score += 1
        if score > best_score:
            best = item
            best_score = score
    if best_score <= 0:
        return docs[-1]
    return best


def _find_documents_by_keyword(keyword: str) -> list[dict[str, Any]]:
    docs = _document_items()
    if not docs:
        return []

    key = (keyword or "").strip().lower()
    if not key:
        return docs[-6:]

    tokens = [tok for tok in re.split(r"[\s　、,。]+", key) if tok]
    if not tokens:
        tokens = [key]

    scored: list[tuple[int, dict[str, Any]]] = []
    for item in docs:
        title = (item.get("title") or "").lower()
        preview = (item.get("preview") or "").lower()
        score = 0
        if key in title:
            score += 3
        if key in preview:
            score += 1
        for tok in tokens:
            if tok in title:
                score += 2
            elif tok in preview:
                score += 1
        if score > 0:
            scored.append((score, item))

    if not scored:
        return []

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:6]]


def _find_document_by_session() -> dict[str, Any] | None:
    session = _load_document_session()
    target_id = (session.get("current_doc_id") or "").strip()
    target_title = (session.get("current_title") or "").strip()
    target_path = (session.get("current_file_path") or "").strip()
    docs = _document_items()

    if target_id:
        for item in docs:
            if (item.get("doc_id") or "").strip() == target_id:
                return item

    if target_path:
        for item in docs:
            if (item.get("file_path") or "").strip() == target_path:
                return item

    if target_title:
        for item in reversed(docs):
            if (item.get("title") or "").strip() == target_title:
                return item
    return None


def _is_document_show_request(text: str) -> bool:
    if not re.search(r"(出して|見せて|表示して|表示|見たい)", text):
        return False
    return bool(re.search(r"(文書|文章|自己PR|ES|ガクチカ|志望動機|200字|400字|1000字)", text))


def _extract_document_show_keyword(text: str) -> str:
    keyword = (text or "").strip()
    keyword = re.sub(r"(?:を)?(?:出して|見せて|表示して|表示|見たい)$", "", keyword)
    keyword = re.sub(r"(?:の)?(?:文書|文章)$", "", keyword)
    keyword = re.sub(r"(?:だけ)?(?:取り出して|抽出して|出力して)", "", keyword)
    keyword = re.sub(r"(?:を)?(?:選んで|選択して)", "", keyword)
    keyword = keyword.replace("版", "")
    keyword = re.sub(r"\s+", " ", keyword)
    return keyword.strip()


def _extract_variant_key(text: str) -> str:
    normalized = (text or "")
    m = re.search(r"(200|400|1000)\s*字", normalized)
    if m:
        return f"{m.group(1)}字"
    return ""


def _split_variant_sections(content: str) -> dict[str, str]:
    body = (content or "").replace("\r\n", "\n")
    lines = body.split("\n")
    headers: list[tuple[str, int]] = []
    for idx, line in enumerate(lines):
        m = re.match(r"^\s*(200|400|1000)\s*字", line.strip())
        if m:
            headers.append((f"{m.group(1)}字", idx))

    if not headers:
        return {}

    sections: dict[str, str] = {}
    for i, (name, start_idx) in enumerate(headers):
        end_idx = headers[i + 1][1] if i + 1 < len(headers) else len(lines)
        section_lines = lines[start_idx:end_idx]
        sections[name] = "\n".join(section_lines).strip()
    return sections


def _render_variant_section(content: str, variant_key: str) -> str:
    sections = _split_variant_sections(content)
    if not sections:
        return content
    if variant_key and variant_key in sections:
        return sections[variant_key]
    return content


def _replace_variant_section(content: str, variant_key: str, replacement: str) -> str:
    body = (content or "").replace("\r\n", "\n")
    lines = body.split("\n")
    headers: list[tuple[str, int]] = []
    for idx, line in enumerate(lines):
        m = re.match(r"^\s*(200|400|1000)\s*字", line.strip())
        if m:
            headers.append((f"{m.group(1)}字", idx))

    if not headers or not variant_key:
        return replacement

    target_idx = -1
    for i, (name, _) in enumerate(headers):
        if name == variant_key:
            target_idx = i
            break

    if target_idx < 0:
        return body

    start = headers[target_idx][1]
    end = headers[target_idx + 1][1] if target_idx + 1 < len(headers) else len(lines)
    before = lines[:start]
    after = lines[end:]

    replacement_lines = (replacement or "").replace("\r\n", "\n").strip().split("\n")
    merged = before + replacement_lines + after
    return "\n".join(merged).strip()


def _resolve_pending_document_choice(text: str) -> dict[str, Any] | None:
    session = _load_document_session()
    pending = session.get("pending_choices", [])
    if not isinstance(pending, list) or not pending:
        return None

    normalized = (text or "").strip()
    m = re.search(r"(\d+)\s*(?:番|つ目)?", normalized)
    if m:
        idx = int(m.group(1))
        for choice in pending:
            if not isinstance(choice, dict):
                continue
            if int(choice.get("index", -1)) == idx:
                return choice

    for choice in pending:
        if not isinstance(choice, dict):
            continue
        title = (choice.get("title") or "")
        if title and title in normalized:
            return choice

    return None


def _find_document_exact(doc_id: str = "", file_path: str = "", title: str = "") -> dict[str, Any] | None:
    docs = _document_items()
    if doc_id:
        for item in docs:
            if (item.get("doc_id") or "").strip() == doc_id.strip():
                return item
    if file_path:
        for item in docs:
            if (item.get("file_path") or "").strip() == file_path.strip():
                return item
    if title:
        for item in reversed(docs):
            if (item.get("title") or "").strip() == title.strip():
                return item
    return None


def _build_document_output_from_item(item: dict[str, Any], variant_key: str = "") -> dict[str, Any]:
    content = _resolve_document_content(item)
    title = (item.get("title") or "").strip() or "無題"
    doc_id = (item.get("doc_id") or "").strip()
    rendered = _render_variant_section(content, variant_key)
    _set_current_document(item)
    _clear_pending_document_choices()

    lines = [f"文書タイトル: {title}"]
    if doc_id:
        lines.append(f"文書ID: {doc_id}")
    if variant_key:
        lines.append(f"抽出: {variant_key}版")
    lines.append("本文:")
    lines.append(rendered or "(本文なし)")
    return {"response": "\n".join(lines)}


def _build_document_output_with_meta(keyword: str) -> dict[str, Any]:
    matches = _find_documents_by_keyword(keyword)
    if not matches:
        return {"response": "保存文書が見つかりませんでした。"}

    # 自己PR系で複数候補がある場合は選択UIを返す
    normalized_key = (keyword or "").strip().lower().replace(" ", "")
    if len(matches) > 1 and normalized_key in {"", "自己pr", "自己ｐｒ"}:
        _set_pending_document_choices(keyword, matches)
        lines = ["候補が複数あります。選んでください:"]
        ui_options = []
        for idx, item in enumerate(matches, start=1):
            title = (item.get("title") or "無題").strip()
            lines.append(f"{idx}. {title}")
            ui_options.append({"label": title, "message": f"{idx}番"})
        return {
            "response": "\n".join(lines),
            "ui": {
                "type": "document_choice",
                "title": "自己PR文書を選択",
                "options": ui_options,
            },
        }

    variant_key = _extract_variant_key(keyword)
    return _build_document_output_from_item(matches[0], variant_key=variant_key)


def _build_document_output(keyword: str) -> str:
    return _build_document_output_with_meta(keyword).get("response", "保存文書が見つかりませんでした。")


def _extract_document_update_target_hint(text: str) -> str:
    m = re.search(r"(.+?)(?:の)?(?:文書|文章|自己PR|ES).*(?:変更|修正|更新)して", text)
    if m:
        return (m.group(1) or "").strip(" 。、")
    return ""


def _extract_document_update_content(text: str) -> str:
    normalized = (text or "").strip()
    if not normalized:
        return ""
    if not re.search(r"(?:変更|修正|更新)(?:して)?", normalized):
        return ""

    m = re.search(r"(?:本文|内容)[：:\s]*(.+)$", normalized, flags=re.DOTALL)
    if m:
        return (m.group(1) or "").strip()

    m = re.search(r"(.+?)(?:\s*)(?:に|へ)?(?:変更|修正|更新)(?:して)?(?:ください|ほしい)?$", normalized, flags=re.DOTALL)
    if not m:
        return ""
    value = (m.group(1) or "").strip()
    if value in {"これ", "それ", "この内容", "こちら", "上記"}:
        return ""
    return value


def _update_document_text_file(item: dict[str, Any], new_content: str, new_title: str | None = None) -> bool:
    file_path = (item.get("file_path") or "").strip()
    doc_id = (item.get("doc_id") or "").strip()
    title = (new_title if new_title is not None else item.get("title") or "").strip()
    checksum = _document_checksum(title, new_content)
    now = _now_iso()
    created_at = (item.get("saved_at") or "").strip() or now

    # 旧形式(contentのみ)の文書は、更新時にTXT+DB形式へ昇格させる
    if not file_path:
        if not doc_id:
            doc_id = _next_document_id()
        abs_file_path = _write_document_text_file(doc_id, title or "無題", new_content, checksum, now)
        file_path = abs_file_path.replace("\\", "/")
        _append_document_db_row(
            doc_id=doc_id,
            created_at=created_at,
            updated_at=now,
            status="active",
            title=title or "無題",
            file_path=file_path,
            char_count=len(new_content),
            checksum=checksum,
        )
        item["doc_id"] = doc_id
        item["file_path"] = file_path

    with open(file_path, "w", encoding="utf-8") as f:
        if doc_id:
            f.write(f"# Document ID: {doc_id}\n")
        f.write(f"# Title: {title}\n")
        f.write(f"# Created At: {created_at}\n")
        f.write(f"# Updated At: {now}\n")
        f.write("# Status: active\n")
        f.write(f"# Checksum: {checksum}\n")
        f.write("\n")
        f.write("----- BODY -----\n")
        body = (new_content or "").replace("\r\n", "\n")
        f.write(body)
        if not body.endswith("\n"):
            f.write("\n")

    item["doc_id"] = doc_id
    item["title"] = title or "無題"
    item["file_path"] = file_path
    item["chars"] = len(new_content)
    item["checksum"] = checksum
    item["preview"] = _truncate(new_content.replace("\n", " "), 120)
    item["saved_at"] = created_at
    item["updated_at"] = now

    rows = _iter_documents_db_rows()
    if doc_id and rows:
        for cols in rows:
            if (cols[0] or "").strip() != doc_id:
                continue
            cols[2] = now
            cols[4] = title or "無題"
            cols[5] = file_path
            cols[6] = str(len(new_content))
            cols[7] = checksum
            break
        _write_documents_db_rows(rows)

    data = load_keep_requests()
    items = data.get("items", []) if isinstance(data.get("items"), list) else []
    for target in items:
        if not isinstance(target, dict):
            continue
        if (target.get("type") or "") != "document":
            continue
        same_doc = bool(doc_id and (target.get("doc_id") or "") == doc_id)
        same_legacy = (target is item) or (
            (target.get("title") or "") == (item.get("title") or "")
            and (target.get("saved_at") or "") == (item.get("saved_at") or "")
        )
        if same_doc or same_legacy:
            target["doc_id"] = doc_id
            target["title"] = title or "無題"
            target["file_path"] = file_path
            target["chars"] = len(new_content)
            target["checksum"] = checksum
            target["preview"] = _truncate(new_content.replace("\n", " "), 120)
            target["saved_at"] = now
            if "content" in target:
                target.pop("content", None)
            break
    data["items"] = items
    save_keep_requests(data)
    return True


def _update_document_from_text(text: str) -> str | None:
    new_content = _extract_document_update_content(text)
    if not new_content:
        return None

    hint = _extract_document_update_target_hint(text)
    variant_key = _extract_variant_key(text)
    target = _find_document_by_keyword(hint) if hint else _find_document_by_session()
    if not target:
        return "更新対象の文書が特定できませんでした。先に『自己PR出して』のように文書を表示してください。"

    if variant_key:
        current_content = _resolve_document_content(target)
        new_content = _replace_variant_section(current_content, variant_key, new_content)

    if _update_document_text_file(target, new_content):
        _set_current_document(target)
        title = (target.get("title") or "").strip() or "無題"
        if variant_key:
            return f"文書を更新しました。タイトル: {title}（{variant_key}版）"
        return f"文書を更新しました。タイトル: {title}"
    return "文書更新に失敗しました。"


def _parse_date_ymd(value: str):
    text = (value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except Exception:
            continue
    return None


def _is_goal_like_title(title: str) -> bool:
    t = (title or "").strip()
    if not t:
        return False
    goal_keywords = ["就職", "内定", "転職", "車", "彼女", "彼氏", "結婚", "資格", "英語", "貯金", "起業", "研究", "卒業"]
    return any(k in t for k in goal_keywords) or len(t) <= 12


def _default_tasks_for_goal(title: str) -> list[dict[str, str]]:
    # 要件変更: タスクは会話の文脈から抽出して構成するため、初期状態は空
    return []


def _goal_keywords(title: str) -> list[str]:
    t = (title or "").strip()
    keywords = [t]
    if "就職" in t:
        keywords.extend(["就職", "ES", "面接", "企業", "インターン", "自己分析", "応募"])
    if "車" in t:
        keywords.extend(["車", "車種", "予算", "維持費", "購入", "見積", "中古", "新車"])
    if "彼女" in t or "彼氏" in t:
        keywords.extend(["出会い", "恋愛", "デート", "会話", "身だしなみ", "マッチング"])
    return [k for k in keywords if k]


def _infer_priority(text: str) -> str:
    normalized = (text or "")
    if any(k in normalized for k in ["至急", "急ぎ", "今日中", "今週中", "優先"]):
        return "high"
    if any(k in normalized for k in ["余裕", "あとで", "時間ある時"]):
        return "low"
    return _PRIORITY_DEFAULT


def _extract_task_candidates(text: str) -> list[str]:
    normalized = (text or "").strip()
    if not normalized:
        return []

    segments = re.split(r"[。！？\n;；]", normalized)
    out: list[str] = []
    for seg in segments:
        s = seg.strip(" 、")
        if not s:
            continue
        if "?" in s or "？" in s:
            continue
        if not _ACTION_VERB_PATTERN.search(s):
            continue
        if len(s) < 4 or len(s) > 60:
            continue
        out.append(s)

    seen = set()
    deduped = []
    for item in out:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _find_related_goal(notes: list[dict[str, Any]], text: str) -> dict[str, Any] | None:
    normalized = (text or "")
    best = None
    best_score = 0
    for note in notes:
        if not isinstance(note, dict):
            continue
        if (note.get("type") or "") != "goal":
            continue
        score = 0
        for kw in _goal_keywords(note.get("title", "")):
            if kw and kw in normalized:
                score += 1
        if score > best_score:
            best_score = score
            best = note
    return best if best_score > 0 else None


def _append_task_if_new(goal: dict[str, Any], task_title: str, priority: str) -> bool:
    tasks = goal.get("tasks", [])
    if not isinstance(tasks, list):
        tasks = []

    for task in tasks:
        if not isinstance(task, dict):
            continue
        if (task.get("title") or "").strip() == task_title.strip():
            return False

    tasks.append(
        {
            "title": task_title.strip(),
            "priority": priority,
            "status": "pending",
            "due_date": "",
        }
    )
    goal["tasks"] = tasks
    goal["status"] = "active"
    return True


def _cleanup_placeholder_goal_tasks(notes_data: dict[str, Any]) -> dict[str, Any]:
    notes = notes_data.get("notes", [])
    if not isinstance(notes, list):
        return notes_data

    for note in notes:
        if not isinstance(note, dict):
            continue
        if (note.get("type") or "") != "goal":
            continue
        if (note.get("content") or "") != "ユーザー指定の予定タスク":
            continue

        tasks = note.get("tasks", [])
        if not isinstance(tasks, list) or not tasks:
            continue

        titles = [str(t.get("title", "")).strip() for t in tasks if isinstance(t, dict)]
        if titles and all(title in _AUTO_TEMPLATE_TASKS for title in titles):
            note["tasks"] = []
            note["status"] = "active"

    notes_data["notes"] = notes
    return notes_data


def _prune_notes_data(notes_data: dict[str, Any]) -> dict[str, Any]:
    """期限切れscheduleと完了タスクを削除する。"""
    notes = notes_data.get("notes", [])
    if not isinstance(notes, list):
        notes_data["notes"] = []
        return notes_data

    today = datetime.now().date()
    kept_notes: list[dict[str, Any]] = []

    for note in notes:
        if not isinstance(note, dict):
            continue

        note_type = (note.get("type") or "note").strip()
        status = (note.get("status") or "pending").strip()
        due_date = _parse_date_ymd(note.get("due_date", ""))

        # scheduleは「完了」または「期限切れ」で削除
        if note_type == "schedule":
            if status == "done":
                continue
            if due_date and due_date < today:
                continue
            kept_notes.append(note)
            continue

        # goalは配下タスクを掃除（done/期限切れを削除）
        if note_type == "goal":
            tasks = note.get("tasks", [])
            if not isinstance(tasks, list):
                tasks = []

            filtered_tasks = []
            for task in tasks:
                if not isinstance(task, dict):
                    continue
                task_status = (task.get("status") or "pending").strip()
                task_due = _parse_date_ymd(task.get("due_date", ""))
                if task_status == "done":
                    continue
                if task_due and task_due < today:
                    continue
                filtered_tasks.append(task)

            note["tasks"] = filtered_tasks
            # 会話からタスクを構成する方式なので、目標は常に active とする
            note["status"] = "active"
            kept_notes.append(note)
            continue

        kept_notes.append(note)

    notes_data["notes"] = kept_notes
    return notes_data


def _migrate_goal_like_schedules(notes_data: dict[str, Any]) -> dict[str, Any]:
    notes = notes_data.get("notes", [])
    if not isinstance(notes, list):
        notes_data["notes"] = []
        return notes_data

    migrated: list[dict[str, Any]] = []
    for note in notes:
        if not isinstance(note, dict):
            continue
        note_type = (note.get("type") or "").strip()
        title = (note.get("title") or "").strip()

        if note_type == "schedule" and _is_goal_like_title(title):
            migrated.append(
                {
                    "title": title,
                    "content": note.get("content") or "目標",
                    "type": "goal",
                    "priority": note.get("priority") or _PRIORITY_DEFAULT,
                    "status": "active",
                    "due_date": note.get("due_date") or "",
                    "tasks": _default_tasks_for_goal(title),
                }
            )
        else:
            migrated.append(note)

    notes_data["notes"] = migrated
    return notes_data


def _ensure_notes_file() -> None:
    os.makedirs(os.path.dirname(_NOTES_PATH), exist_ok=True)
    if not os.path.exists(_NOTES_PATH):
        with open(_NOTES_PATH, "w", encoding="utf-8") as f:
            json.dump(_default_notes(), f, ensure_ascii=False, indent=2)


def _ensure_keep_requests_file() -> None:
    os.makedirs(os.path.dirname(_KEEP_REQUESTS_PATH), exist_ok=True)
    if not os.path.exists(_KEEP_REQUESTS_PATH):
        with open(_KEEP_REQUESTS_PATH, "w", encoding="utf-8") as f:
            json.dump(_default_keep_requests(), f, ensure_ascii=False, indent=2)


def _sync_view_file(profile_data: dict[str, Any] | None = None, notes_data: dict[str, Any] | None = None) -> None:
    """Keep a single consolidated file for quick inspection in VS Code."""
    os.makedirs(os.path.dirname(_VIEW_PATH), exist_ok=True)

    if profile_data is None:
        try:
            with open(_PROFILE_PATH, "r", encoding="utf-8") as f:
                profile_data = json.load(f)
        except Exception:
            profile_data = _default_profile()

    if notes_data is None:
        try:
            with open(_NOTES_PATH, "r", encoding="utf-8") as f:
                notes_data = json.load(f)
        except Exception:
            notes_data = _default_notes()

    try:
        with open(_KEEP_REQUESTS_PATH, "r", encoding="utf-8") as f:
            keep_requests_data = json.load(f)
    except Exception:
        keep_requests_data = _default_keep_requests()

    view = {
        "profile": profile_data,
        "notes": notes_data.get("notes", []),
        "keep_requests": keep_requests_data.get("items", []),
        "profile_updated_at": profile_data.get("updated_at", ""),
        "notes_updated_at": notes_data.get("updated_at", ""),
        "keep_requests_updated_at": keep_requests_data.get("updated_at", ""),
        "synced_at": _now_iso(),
    }

    with open(_VIEW_PATH, "w", encoding="utf-8") as f:
        json.dump(view, f, ensure_ascii=False, indent=2)


def load_profile() -> dict[str, Any]:
    with _LOCK:
        _ensure_profile_file()
        try:
            with open(_PROFILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return _default_profile()
            base = _default_profile()
            base.update(data)
            return base
        except Exception:
            return _default_profile()


def save_profile(profile: dict[str, Any]) -> None:
    with _LOCK:
        _ensure_profile_file()
        profile = dict(profile)
        profile["updated_at"] = _now_iso()
        with open(_PROFILE_PATH, "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)
        _sync_view_file(profile_data=profile)


def load_notes() -> dict[str, Any]:
    with _LOCK:
        _ensure_notes_file()
        try:
            with open(_NOTES_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return _default_notes()
            base = _default_notes()
            base.update(data)
            if not isinstance(base.get("notes"), list):
                base["notes"] = []
            base = _migrate_goal_like_schedules(base)
            base = _cleanup_placeholder_goal_tasks(base)
            base = _prune_notes_data(base)
            return base
        except Exception:
            return _default_notes()


def load_keep_requests() -> dict[str, Any]:
    with _LOCK:
        _ensure_keep_requests_file()
        try:
            with open(_KEEP_REQUESTS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return _default_keep_requests()
            base = _default_keep_requests()
            base.update(data)
            if not isinstance(base.get("items"), list):
                base["items"] = []
            return base
        except Exception:
            return _default_keep_requests()


def save_notes(notes_data: dict[str, Any]) -> None:
    with _LOCK:
        _ensure_notes_file()
        notes_data = dict(notes_data)
        notes_data = _migrate_goal_like_schedules(notes_data)
        notes_data = _cleanup_placeholder_goal_tasks(notes_data)
        notes_data = _prune_notes_data(notes_data)
        notes_data["updated_at"] = _now_iso()
        with open(_NOTES_PATH, "w", encoding="utf-8") as f:
            json.dump(notes_data, f, ensure_ascii=False, indent=2)
        _sync_view_file(notes_data=notes_data)


def save_keep_requests(keep_requests_data: dict[str, Any]) -> None:
    with _LOCK:
        _ensure_keep_requests_file()
        keep_requests_data = dict(keep_requests_data)
        items = keep_requests_data.get("items", [])
        if not isinstance(items, list):
            items = []
        if len(items) > _MAX_KEEP_REQUESTS:
            items = items[-_MAX_KEEP_REQUESTS:]
        keep_requests_data["items"] = items
        keep_requests_data["updated_at"] = _now_iso()
        with open(_KEEP_REQUESTS_PATH, "w", encoding="utf-8") as f:
            json.dump(keep_requests_data, f, ensure_ascii=False, indent=2)
        _sync_view_file()


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        normalized = (item or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def _append_limited(items: list[str], value: str, max_len: int) -> list[str]:
    arr = _dedupe_keep_order(items + [value])
    if len(arr) > max_len:
        arr = arr[-max_len:]
    return arr


def _extract_name(text: str) -> str:
    patterns = [
        r"(?:私|僕|俺)の名前は(.+?)(?:です|だよ|だ)",
        r"(.+?)って呼んで",
        r"(.+?)と呼んで",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(1).strip(" 。、")
    return ""


def _extract_location(text: str) -> str:
    patterns = [
        r"(.+?)に住んで(?:ます|います|る)",
        r"(.+?)在住",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(1).strip(" 。、")
    return ""


def _extract_like(text: str) -> str:
    m = re.search(r"(.+?)が好き", text)
    if m:
        return m.group(1).strip(" 。、")
    return ""


def _extract_dislike(text: str) -> str:
    m = re.search(r"(.+?)が(?:嫌い|苦手)", text)
    if m:
        return m.group(1).strip(" 。、")
    return ""


def _extract_fact(text: str) -> str:
    patterns = [
        r"(?:私は|僕は|俺は)(.+?)(?:です|だ)",
        r"(?:仕事は|職業は)(.+?)(?:です|だ)",
        r"(?:趣味は)(.+?)(?:です|だ)",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(0).strip(" 。、")
    return ""


def _forget_targets(text: str) -> list[str]:
    # 例: 「ラーメンの好みは忘れて」「大阪の情報消して」
    m = re.search(r"(.+?)(?:は|を)(?:忘れて|削除して|消して|取り消して)", text)
    if m:
        return [m.group(1).strip(" 。、")]
    return []


def _is_forget_all(text: str) -> bool:
    return bool(re.search(r"(?:全部|全て|ぜんぶ).*(?:忘れて|削除|消して)", text))


def _extract_explicit_note_title_data(text: str) -> tuple[str, str] | None:
    patterns = [
        # 覚えて: タイトル: xxx 内容: yyy
        r"(?:覚えて|メモして|保存して|記録して|記憶して)[：:\s]*タイトル[：:\s]*(.+?)[,、\s]+(?:内容|データ)[：:\s]*(.+)",
        # タイトル: xxx 内容: yyy
        r"タイトル[：:\s]*(.+?)[,、\s]+(?:内容|データ)[：:\s]*(.+)",
        # 覚えて: xxx | yyy
        r"(?:覚えて|メモして|保存して|記録して|記憶して)[：:\s]*(.+?)\s*[|｜]\s*(.+)",
    ]

    for pat in patterns:
        m = re.search(pat, text)
        if not m:
            continue
        title = (m.group(1) or "").strip(" 。、")
        content = (m.group(2) or "").strip()
        if title and content:
            return title, content

    return None


def _extract_note_delete_title(text: str) -> str:
    # 例: 「メモ削除 タイトル: 資格」「資格のメモを消して」
    m = re.search(r"(?:メモ|ノート)\s*(?:削除|消して|消去)\s*タイトル[：:\s]*(.+)$", text)
    if m:
        return m.group(1).strip(" 。、")

    m = re.search(r"(?:メモ|ノート).*(?:削除|消して|消去).*(?:タイトル[：:\s]*)?(.+)$", text)
    if m:
        return m.group(1).strip(" 。、")

    m = re.search(r"(.+?)の(?:メモ|ノート)を(?:削除|消して|消去)", text)
    if m:
        return m.group(1).strip(" 。、")

    return ""


def _is_note_list_request(text: str) -> bool:
    return bool(re.search(r"(?:メモ|ノート).*(?:一覧|見せて|表示)", text))


def _extract_keep_request_content(text: str) -> str:
    patterns = [
        r"(?:保存しておいて|保存しといて|覚えておいて|記録しておいて|保存しておいてほしい|保存してほしい|覚えておいてほしい|保存して)[：:\s]*(.+)$",
        r"(.+?)(?:を|って)?(?:保存しておいて|保存しといて|覚えておいて|記録しておいて|保存しておいてほしい|保存してほしい|覚えておいてほしい|保存して)$",
    ]
    for pat in patterns:
        m = re.search(pat, text, flags=re.DOTALL)
        if not m:
            continue
        value = (m.group(1) or "").strip(" \t\n\r。、、'\"")
        if value and len(value) <= _MAX_KEEP_CONTENT:
            return value
    return ""


def _extract_keep_document(text: str) -> tuple[str, str] | None:
    normalized = (text or "").strip()
    if not normalized:
        return None

    # 例: 「就活で使う自己PR（サークル）の文書を保存しておいてほしい。本文...」
    patterns = [
        r"(.+?)の(?:文書|文章|テキスト)を(?:保存しておいてほしい|保存してほしい|保存しておいて|保存しといてほしい|保存しといて|覚えておいてほしい|覚えておいて|記録しておいてほしい|記録しておいて|保存して)[。．:\s\n]*(.+)$",
        r"(?:タイトル|件名)[：:\s]*(.+?)(?:\n|,|、)\s*(?:本文|内容|データ)[：:\s]*(.+)$",
    ]

    for pat in patterns:
        m = re.search(pat, normalized, flags=re.DOTALL)
        if not m:
            continue
        title = (m.group(1) or "").strip(" \t\n\r。、、'\"")
        content = (m.group(2) or "").strip()
        if title and content and len(content) <= _MAX_KEEP_CONTENT:
            return title, content

    # フォールバック: 長文 + 保存指示 + 自己PR/文書系キーワードがある場合、先頭行をタイトル扱いで保存
    if re.search(r"(?:保存して|保存してほしい|保存しておいて|保存しといて|覚えておいて|記録しておいて)", normalized):
        if re.search(r"(?:自己PR|文書|文章|ES|志望動機|ガクチカ)", normalized) and "\n" in normalized:
            lines = [ln.strip() for ln in normalized.splitlines() if ln.strip()]
            if lines:
                title = lines[0][:80].strip(" 。、'\"")
                content = "\n".join(lines[1:]).strip()
                if title and content and len(content) <= _MAX_KEEP_CONTENT:
                    return title, content

    return None


def _document_checksum(title: str, content: str) -> str:
    h = hashlib.sha1()
    h.update(((title or "").strip() + "\n" + (content or "").strip()).encode("utf-8", errors="ignore"))
    return h.hexdigest()


def append_keep_request(content: str, source_text: str = "") -> bool:
    value = (content or "").strip()
    if not value:
        return False

    # 長文は通常メモではなく文書としてTXTに保存する
    if len(value) >= _LONG_TEXT_TO_DOC_THRESHOLD or "\n" in value:
        auto_title = _truncate(value.replace("\n", " "), 24)
        return append_keep_document(auto_title, value, source_text=source_text)

    data = load_keep_requests()
    items = data.get("items", [])
    if not isinstance(items, list):
        items = []

    for item in items:
        if not isinstance(item, dict):
            continue
        if (item.get("content") or "").strip() == value:
            return False

    items.append(
        {
            "type": "note",
            "content": value,
            "source": _truncate((source_text or "").strip(), 300),
            "saved_at": _now_iso(),
        }
    )
    data["items"] = items
    save_keep_requests(data)
    return True


def append_keep_document(title: str, content: str, source_text: str = "") -> bool:
    result = create_document_item(title, content, source_text=source_text)
    return bool(result.get("ok"))


def create_document_item(title: str, content: str, source_text: str = "") -> dict[str, Any]:
    t = (title or "").strip()
    c = (content or "").strip()
    if not t or not c:
        return {"ok": False, "error": "タイトルと本文を入力してください。"}

    data = load_keep_requests()
    items = data.get("items", [])
    if not isinstance(items, list):
        items = []

    checksum = _document_checksum(t, c)

    for item in items:
        if not isinstance(item, dict):
            continue
        if (item.get("type") or "") != "document":
            continue
        # 新形式: checksum一致なら重複とみなす
        if (item.get("checksum") or "").strip() == checksum:
            return {"ok": False, "error": "同じ文書は既に保存されています。"}
        # 旧形式: contentを直接持つドキュメントとの互換重複判定
        if (item.get("title") or "").strip() == t and (item.get("content") or "").strip() == c:
            return {"ok": False, "error": "同じ文書は既に保存されています。"}

    saved_at = _now_iso()
    doc_id = _next_document_id()
    abs_file_path = _write_document_text_file(doc_id, t, c, checksum, saved_at)
    rel_file_path = abs_file_path.replace("\\", "/")
    _append_document_db_row(
        doc_id=doc_id,
        created_at=saved_at,
        updated_at=saved_at,
        status="active",
        title=t,
        file_path=rel_file_path,
        char_count=len(c),
        checksum=checksum,
    )

    items.append(
        {
            "type": "document",
            "doc_id": doc_id,
            "title": t,
            "file_path": rel_file_path,
            "chars": len(c),
            "checksum": checksum,
            "preview": _truncate(c.replace("\n", " "), 120),
            "source": _truncate((source_text or "").strip(), 300),
            "saved_at": saved_at,
        }
    )
    data["items"] = items
    save_keep_requests(data)
    created = _find_document_exact(doc_id=doc_id, title=t, file_path=rel_file_path)
    if created:
        _set_current_document(created)
        return {"ok": True, "document": _serialize_document_item(created, include_content=True)}
    return {
        "ok": True,
        "document": {
            "doc_id": doc_id,
            "title": t,
            "file_path": rel_file_path,
            "chars": len(c),
            "checksum": checksum,
            "preview": _truncate(c.replace("\n", " "), 120),
            "source": _truncate((source_text or "").strip(), 300),
            "saved_at": saved_at,
            "content": c,
        },
    }


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip() + "..."


def upsert_titled_note(title: str, content: str) -> bool:
    title = (title or "").strip()
    content = (content or "").strip()
    if not title or not content:
        return False

    notes_data = load_notes()
    notes = notes_data.get("notes", [])

    note_type = "goal" if _is_goal_like_title(title) else "note"

    replaced = False
    for note in notes:
        if (note.get("title") or "").strip() == title:
            note["content"] = content
            note["updated_at"] = _now_iso()
            if note_type == "goal":
                note["type"] = "goal"
                note["priority"] = note.get("priority") or _PRIORITY_DEFAULT
                note["status"] = note.get("status") or "active"
                note["due_date"] = note.get("due_date") or ""
                if not isinstance(note.get("tasks"), list) or not note.get("tasks"):
                    note["tasks"] = _default_tasks_for_goal(title)
            replaced = True
            break

    if not replaced:
        new_note = {"title": title, "content": content, "updated_at": _now_iso()}
        if note_type == "goal":
            new_note.update(
                {
                    "type": "goal",
                    "priority": _PRIORITY_DEFAULT,
                    "status": "active",
                    "due_date": "",
                    "tasks": _default_tasks_for_goal(title),
                }
            )
        notes.append(new_note)

    if len(notes) > _MAX_NOTES:
        notes = notes[-_MAX_NOTES:]

    notes_data["notes"] = notes
    save_notes(notes_data)
    return True


def delete_titled_note(title: str) -> bool:
    title = (title or "").strip()
    if not title:
        return False

    notes_data = load_notes()
    notes = notes_data.get("notes", [])
    filtered = [n for n in notes if (n.get("title") or "").strip() != title]
    if len(filtered) == len(notes):
        return False

    notes_data["notes"] = filtered
    save_notes(notes_data)
    return True


def build_notes_list_text(max_items: int = 8) -> str:
    notes = load_notes().get("notes", [])
    if not notes:
        return "保存メモはまだありません。"

    lines = ["保存メモ一覧:"]
    for note in notes[-max_items:]:
        title = (note.get("title") or "").strip()
        content = (note.get("content") or "").strip()
        note_type = (note.get("type") or "note").strip()
        if not title:
            continue
        if note_type == "goal":
            tasks = note.get("tasks", []) if isinstance(note.get("tasks"), list) else []
            if tasks:
                lines.append(f"- [目標] {title}: タスク{len(tasks)}件")
            else:
                lines.append(f"- [目標] {title}: タスク未設定（会話から抽出待ち）")
        elif note_type == "schedule":
            due = (note.get("due_date") or "未設定").strip() or "未設定"
            lines.append(f"- [予定] {title}: 期限={due}")
        else:
            lines.append(f"- {title}: {_truncate(content, 60)}")
    return "\n".join(lines)


def handle_explicit_note_command_with_meta(text: str) -> dict[str, Any] | None:
    normalized = (text or "").strip()
    if not normalized:
        return None

    pending_choice = _resolve_pending_document_choice(normalized)
    if pending_choice:
        variant_key = _extract_variant_key(normalized)
        _clear_pending_document_choices()
        item = _find_document_exact(
            doc_id=(pending_choice.get("doc_id") or ""),
            file_path=(pending_choice.get("file_path") or ""),
            title=(pending_choice.get("title") or ""),
        )
        if item:
            return _build_document_output_from_item(item, variant_key=variant_key)
        key = (pending_choice.get("title") or "").strip() or normalized
        return _build_document_output_with_meta(key)

    if _is_note_list_request(normalized):
        return {"response": build_notes_list_text()}

    if _is_document_list_request(normalized):
        return {"response": build_document_list_text()}

    if _is_document_show_request(normalized):
        keyword = _extract_document_show_keyword(normalized)
        return _build_document_output_with_meta(keyword)

    updated_message = _update_document_from_text(normalized)
    if updated_message:
        return {"response": updated_message}

    delete_title = _extract_note_delete_title(normalized)
    if delete_title:
        if delete_titled_note(delete_title):
            return {"response": f"メモを削除しました。タイトル: {delete_title}"}
        return {"response": f"指定されたタイトルのメモが見つかりませんでした。タイトル: {delete_title}"}

    extracted = _extract_explicit_note_title_data(normalized)
    if extracted:
        title, content = extracted
        upsert_titled_note(title, content)
        return {"response": f"メモを保存しました。タイトル: {title}"}

    keep_doc = _extract_keep_document(normalized)
    if keep_doc:
        title, content = keep_doc
        if append_keep_document(title, content, source_text=normalized):
            return {"response": f"文書を保存しました。タイトル: {title}"}
        return {"response": f"同じ文書は既に保存されています。タイトル: {title}"}

    keep_content = _extract_keep_request_content(normalized)
    if keep_content:
        append_keep_request(keep_content, source_text=normalized)
        return {"response": "保存しておいてメモに記録しました。"}

    return None


def handle_explicit_note_command(text: str) -> str | None:
    payload = handle_explicit_note_command_with_meta(text)
    if not payload:
        return None
    return str(payload.get("response") or "")


def update_profile_from_text(text: str) -> bool:
    normalized = (text or "").strip()
    if not normalized:
        return False

    profile = load_profile()
    changed = False

    if _is_forget_all(normalized):
        keep_name = profile.get("name", "")
        keep_location = profile.get("location", "")
        profile = _default_profile()
        profile["name"] = keep_name
        profile["location"] = keep_location
        save_profile(profile)
        return True

    targets = _forget_targets(normalized)
    if targets:
        for target in targets:
            before = json.dumps(profile, ensure_ascii=False)
            profile["likes"] = [x for x in profile.get("likes", []) if target not in x]
            profile["dislikes"] = [x for x in profile.get("dislikes", []) if target not in x]
            profile["facts"] = [x for x in profile.get("facts", []) if target not in x]
            after = json.dumps(profile, ensure_ascii=False)
            if before != after:
                changed = True

    name = _extract_name(normalized)
    if name and profile.get("name") != name:
        profile["name"] = name
        changed = True

    location = _extract_location(normalized)
    if location and profile.get("location") != location:
        profile["location"] = location
        changed = True

    like = _extract_like(normalized)
    if like:
        new_likes = _append_limited(profile.get("likes", []), like, _MAX_PREFERENCES)
        if new_likes != profile.get("likes", []):
            profile["likes"] = new_likes
            changed = True

    dislike = _extract_dislike(normalized)
    if dislike:
        new_dislikes = _append_limited(profile.get("dislikes", []), dislike, _MAX_PREFERENCES)
        if new_dislikes != profile.get("dislikes", []):
            profile["dislikes"] = new_dislikes
            changed = True

    fact = _extract_fact(normalized)
    if fact:
        new_facts = _append_limited(profile.get("facts", []), fact, _MAX_FACTS)
        if new_facts != profile.get("facts", []):
            profile["facts"] = new_facts
            changed = True

    if changed:
        save_profile(profile)

    # 会話の中の行動文を、関連する目標のタスクとして追加する
    notes_data = load_notes()
    notes = notes_data.get("notes", []) if isinstance(notes_data.get("notes"), list) else []
    related_goal = _find_related_goal(notes, normalized)
    if related_goal:
        candidates = _extract_task_candidates(normalized)
        if candidates:
            pr = _infer_priority(normalized)
            notes_changed = False
            for task_title in candidates:
                if _append_task_if_new(related_goal, task_title, pr):
                    notes_changed = True
            if notes_changed:
                notes_data["notes"] = notes
                save_notes(notes_data)

    return changed


def build_profile_context(max_facts: int = 5) -> str:
    profile = load_profile()
    notes = load_notes().get("notes", [])
    keep_requests = load_keep_requests().get("items", [])

    lines = ["ユーザープロファイル:"]
    name = (profile.get("name") or "").strip()
    location = (profile.get("location") or "").strip()
    likes = profile.get("likes", [])
    dislikes = profile.get("dislikes", [])
    facts = profile.get("facts", [])

    if name:
        lines.append(f"- 呼び名: {name}")
    if location:
        lines.append(f"- 居住地: {location}")
    if likes:
        lines.append("- 好み: " + "、".join(likes[-4:]))
    if dislikes:
        lines.append("- 苦手: " + "、".join(dislikes[-4:]))
    if facts:
        lines.append("- メモ: " + " / ".join(facts[-max_facts:]))
    if notes:
        rendered = []
        for note in notes[-4:]:
            title = (note.get("title") or "").strip()
            content = (note.get("content") or "").strip()
            if title and content:
                if (note.get("type") or "").strip() == "goal":
                    task_count = len(note.get("tasks", [])) if isinstance(note.get("tasks"), list) else 0
                    rendered.append(f"目標:{title}(残タスク{task_count})")
                else:
                    rendered.append(f"{title}={_truncate(content, 40)}")
        if rendered:
            lines.append("- 保存メモ: " + " / ".join(rendered))
    if keep_requests:
        latest = []
        latest_docs = []
        for item in keep_requests[-3:]:
            if not isinstance(item, dict):
                continue
            item_type = (item.get("type") or "").strip()
            if item_type == "document":
                title = (item.get("title") or "").strip()
                if title:
                    latest_docs.append(_truncate(title, 30))
                continue
            content = (item.get("content") or "").strip()
            if content:
                latest.append(_truncate(content, 40))
        if latest_docs:
            lines.append("- 保存文書: " + " / ".join(latest_docs))
        if latest:
            lines.append("- 保存しておいて指定: " + " / ".join(latest))

    if len(lines) == 1:
        lines.append("- まだ保存情報はありません")

    return "\n".join(lines)


def reset_profile() -> None:
    save_profile(_default_profile())

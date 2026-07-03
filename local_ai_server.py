from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import socket
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse
from uuid import uuid4

import config
from functions.calculator import calculate
from functions.time_func import get_time, get_weekday, get_weekday_from_text
from functions.transit import resolve_navigation
from models.intent_classifier import classify_intent
from models.user_profile_memory import (
  build_profile_context,
  create_document_item,
  handle_explicit_note_command,
  handle_explicit_note_command_with_meta,
  delete_document_item,
  get_current_document_item,
  get_document_item,
  get_document_session,
  list_document_items,
  update_document_item,
  update_profile_from_text,
)
from cloud.local_llm import ask_local_llm, stream_local_llm
from cloud.local_prompt import build_local_prompt
from functions.google_workspace import search_google_web


DEFAULT_HOST = os.getenv("LOCAL_AI_SERVER_HOST", "0.0.0.0")
DEFAULT_PORT = int(os.getenv("LOCAL_AI_SERVER_PORT", "8000"))
MAX_HISTORY_TURNS = int(os.getenv("LOCAL_AI_SERVER_HISTORY", "12"))
REQUEST_TIMEOUT = float(os.getenv("LOCAL_AI_SERVER_TIMEOUT", str(config.OLLAMA_TIMEOUT)))
MAX_RETRIES = int(os.getenv("LOCAL_AI_SERVER_RETRIES", "2"))
RETRY_SUFFIX = "\n\n追加指示: 回答は結論を先に、1〜2文で短く自然に答えてください。"

_SESSION_LOCK = threading.RLock()
_SESSION_HISTORY: dict[str, deque[dict[str, str]]] = {}


_FACT_KEYWORDS = (
  "誰",
  "なに",
  "何",
  "いつ",
  "どこ",
  "だれ",
  "大統領",
  "総理",
  "首相",
  "大臣",
  "法律",
  "歴史",
  "由来",
  "意味",
  "年収",
  "給与",
  "給料",
  "月収",
  "年俸",
)

_RELATIVE_DAY_KEYWORDS = (
  "明後日",
  "あさって",
  "明日",
  "あした",
  "昨日",
  "きのう",
  "一昨日",
  "おととい",
)

_CALC_KEYWORDS = (
  "計算",
  "かける",
  "掛ける",
  "割る",
  "わる",
  "足す",
  "たす",
  "引く",
  "ひく",
  "足し算",
  "掛け算",
  "割り算",
)

_SAVE_CONTEXT_KEYWORDS = (
  "保存",
  "文書",
  "文章",
  "自己PR",
  "ES",
  "ガクチカ",
)

_MATH_EXPR = re.compile(r"[0-9０-９]+\s*[+\-×xX*÷/／]\s*[0-9０-９]+")


def _get_history(session_id: str) -> deque[dict[str, str]]:
    with _SESSION_LOCK:
        history = _SESSION_HISTORY.get(session_id)
        if history is None:
            history = deque(maxlen=MAX_HISTORY_TURNS)
            _SESSION_HISTORY[session_id] = history
        return history


def _append_turn(session_id: str, role: str, content: str) -> None:
    history = _get_history(session_id)
    history.append({"role": role, "content": content})


def _snapshot_session(session_id: str) -> list[dict[str, str]]:
  with _SESSION_LOCK:
    return list(_get_history(session_id))


def _clear_session(session_id: str) -> bool:
  with _SESSION_LOCK:
    return _SESSION_HISTORY.pop(session_id, None) is not None


def _clear_all_sessions() -> None:
  with _SESSION_LOCK:
    _SESSION_HISTORY.clear()


def _list_sessions() -> list[dict[str, Any]]:
  with _SESSION_LOCK:
    sessions: list[dict[str, Any]] = []
    for session_id, history in _SESSION_HISTORY.items():
      sessions.append(
        {
          "session_id": session_id,
          "turns": len(history),
          "last_role": history[-1]["role"] if history else None,
        }
      )
    return sessions


def _looks_like_llm_error(text: str) -> bool:
  stripped = (text or "").strip()
  if not stripped:
    return True

  return stripped.startswith(("（Ollama", "（ローカルLLM"))


def _is_viable_response(text: str) -> bool:
  stripped = (text or "").strip()
  if len(stripped) < 2:
    return False

  if _looks_like_llm_error(stripped):
    return False

  if len(set(stripped)) <= 2 and len(stripped) > 6:
    return False

  content_chars = 0
  for char in stripped:
    if char.isalnum() or "ぁ" <= char <= "ん" or "ァ" <= char <= "ヴ" or "一" <= char <= "龯":
      content_chars += 1

  return content_chars >= max(2, len(stripped) // 5)


def _looks_like_fact_question(text: str) -> bool:
  normalized = (text or "").strip()
  if not normalized:
    return False

  if len(normalized) > 40:
    return False

  return any(keyword in normalized for keyword in _FACT_KEYWORDS) or normalized.endswith(("は", "とは", "ですか", "でしょうか", "？", "?"))


def _looks_like_relative_weekday_question(text: str) -> bool:
  normalized = (text or "").strip()
  if not normalized:
    return False

  if not any(keyword in normalized for keyword in _RELATIVE_DAY_KEYWORDS):
    return False

  return any(keyword in normalized for keyword in ("曜日", "何曜日", "何日"))


def _looks_like_calculation(text: str) -> bool:
  normalized = (text or "").strip()
  if not normalized:
    return False

  if any(keyword in normalized for keyword in _SAVE_CONTEXT_KEYWORDS):
    return False

  return any(keyword in normalized for keyword in _CALC_KEYWORDS) or _MATH_EXPR.search(normalized) is not None


def _ollama_json_get(path: str, timeout: float = 5.0) -> dict[str, Any]:
  request = Request(
    f"{config.OLLAMA_HOST.rstrip('/')}{path}",
    headers={"User-Agent": "Mozilla/5.0"},
    method="GET",
  )

  with urlopen(request, timeout=timeout) as response:
    return json.loads(response.read().decode("utf-8"))


def _health_snapshot() -> dict[str, Any]:
  started = time.perf_counter()
  result: dict[str, Any] = {
    "status": "degraded",
    "server": "ok",
    "ollama": {
      "reachable": False,
      "model_configured": config.OLLAMA_MODEL,
      "host": config.OLLAMA_HOST,
      "version": None,
      "model_available": False,
      "error": None,
    },
    "sessions": len(_list_sessions()),
  }

  try:
    version = _ollama_json_get("/api/version", timeout=min(5.0, REQUEST_TIMEOUT))
    result["ollama"]["reachable"] = True
    result["ollama"]["version"] = version.get("version") if isinstance(version, dict) else None

    tags = _ollama_json_get("/api/tags", timeout=min(5.0, REQUEST_TIMEOUT))
    models = tags.get("models", []) if isinstance(tags, dict) else []
    result["ollama"]["model_available"] = any(
      model.get("name") == config.OLLAMA_MODEL or str(model.get("name", "")).startswith(f"{config.OLLAMA_MODEL}:")
      for model in models
    )

    result["status"] = "ok" if result["ollama"]["model_available"] else "degraded"
  except HTTPError as error:
    result["ollama"]["error"] = f"HTTP {error.code}"
    result["status"] = "down"
  except URLError as error:
    result["ollama"]["error"] = str(error.reason)
    result["status"] = "down"
  except TimeoutError as error:
    result["ollama"]["error"] = f"timeout: {error}"
    result["status"] = "down"
  except Exception as error:
    result["ollama"]["error"] = str(error)
    result["status"] = "down"

  result["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
  return result


def _resolve_local_ip() -> str:
  try:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
      sock.connect(("8.8.8.8", 80))
      return sock.getsockname()[0]
  except Exception:
    try:
      return socket.gethostbyname(socket.gethostname())
    except Exception:
      return "127.0.0.1"


def _server_meta() -> dict[str, Any]:
  local_ip = _resolve_local_ip()
  host = DEFAULT_HOST
  port = DEFAULT_PORT

  return {
    "ok": True,
    "server": {
      "host": host,
      "port": port,
      "local_ip": local_ip,
      "open_urls": [
        f"http://{local_ip}:{port}/",
        f"http://localhost:{port}/",
      ],
    },
    "routes": {
      "chat": "/chat",
      "chat_stream": "/chat/stream",
      "health": "/health",
      "sessions": "/sessions",
      "sessions_clear": "/sessions/clear",
      "meta": "/meta",
    },
    "local_llm": {
      "model": config.OLLAMA_MODEL,
      "host": config.OLLAMA_HOST,
      "timeout": REQUEST_TIMEOUT,
      "retries": MAX_RETRIES,
    },
  }


def _generate_llm_response(prompt: str) -> dict[str, Any]:
  retry_count = max(1, MAX_RETRIES)
  attempts: list[dict[str, Any]] = []
  for attempt_index in range(retry_count):
    if attempt_index == 0:
      attempts.append({"temperature": 0.7, "prompt": prompt, "timeout": REQUEST_TIMEOUT})
    elif attempt_index == 1:
      attempts.append({"temperature": 0.3, "prompt": prompt + RETRY_SUFFIX, "timeout": max(5.0, REQUEST_TIMEOUT / 2)})
    else:
      attempts.append({"temperature": 0.2, "prompt": prompt + RETRY_SUFFIX, "timeout": max(5.0, REQUEST_TIMEOUT / 2)})

  last_error = None
  for attempt_index, attempt in enumerate(attempts, start=1):
    response = ask_local_llm(
      attempt["prompt"],
      temperature=attempt["temperature"],
      timeout=attempt["timeout"],
    )

    if _looks_like_llm_error(response):
      last_error = response
      continue

    if _is_viable_response(response):
      return {
        "ok": True,
        "response": response.strip(),
        "attempt": attempt_index,
        "fallback_used": attempt_index > 1,
      }

    last_error = response

  return {
    "ok": False,
    "error": last_error or "（ローカルLLM応答は不十分でした）",
    "retryable": False,
  }
def _build_chat_payload(message: str, session_id: str) -> dict[str, Any]:
  message = (message or "").strip()
  if not message:
    return {"ok": False, "error": "message is required", "retryable": False}

  # 自動メモリ更新: ユーザー発話から重要情報のみ保存し、削除指示も反映
  update_profile_from_text(message)

  explicit_note_payload = handle_explicit_note_command_with_meta(message)

  _append_turn(session_id, "user", message)
  history = _snapshot_session(session_id)
  profile_context = build_profile_context()

  if explicit_note_payload:
    explicit_note_response = str(explicit_note_payload.get("response") or "")
    _append_turn(session_id, "assistant", explicit_note_response)
    response_payload = {
      "ok": True,
      "response": explicit_note_response,
      "attempt": 1,
      "fallback_used": False,
      "session_id": session_id,
    }
    if isinstance(explicit_note_payload.get("ui"), dict):
      response_payload["ui"] = explicit_note_payload["ui"]
    return response_payload

  intent = classify_intent(message)
  if intent == "relative_weekday" or _looks_like_relative_weekday_question(message):
    response = get_weekday_from_text(message)
    _append_turn(session_id, "assistant", response)
    return {"ok": True, "response": response, "attempt": 1, "fallback_used": False, "session_id": session_id}

  if intent == "weekday":
    response = get_weekday()
    _append_turn(session_id, "assistant", response)
    return {"ok": True, "response": response, "attempt": 1, "fallback_used": False, "session_id": session_id}

  if intent == "time":
    response = get_time()
    _append_turn(session_id, "assistant", response)
    return {"ok": True, "response": response, "attempt": 1, "fallback_used": False, "session_id": session_id}

  if intent == "calculate" or _looks_like_calculation(message):
    response = calculate(message)
    _append_turn(session_id, "assistant", response)
    return {"ok": True, "response": response, "attempt": 1, "fallback_used": False, "session_id": session_id}

  if intent == "navigation":
    response = resolve_navigation(message)
    _append_turn(session_id, "assistant", response)
    return {"ok": True, "response": response, "attempt": 1, "fallback_used": False, "session_id": session_id}

  if intent == "search":
    search_result = search_google_web(message)
    if search_result and not search_result.startswith("検索結果を抽出できませんでした"):
      _append_turn(session_id, "assistant", search_result)
      return {"ok": True, "response": search_result, "attempt": 1, "fallback_used": False, "session_id": session_id}

  if _looks_like_fact_question(message):
    search_result = search_google_web(message)
    if search_result and not search_result.startswith("検索結果を抽出できませんでした"):
      _append_turn(session_id, "assistant", search_result)
      return {"ok": True, "response": search_result, "attempt": 1, "fallback_used": False, "session_id": session_id}

  prompt = build_local_prompt(message, conversation_history=history, user_profile_context=profile_context)
  result = _generate_llm_response(prompt)

  if result.get("ok"):
    _append_turn(session_id, "assistant", result["response"])

  return {**result, "session_id": session_id}


def _stream_chat_payload(message: str, session_id: str):
  message = (message or "").strip()
  if not message:
    yield {"event": "error", "data": {"error": "message is required"}}
    return

  update_profile_from_text(message)
  explicit_note_payload = handle_explicit_note_command_with_meta(message)

  _append_turn(session_id, "user", message)
  history = _snapshot_session(session_id)
  profile_context = build_profile_context()

  if explicit_note_payload:
    explicit_note_response = str(explicit_note_payload.get("response") or "")
    _append_turn(session_id, "assistant", explicit_note_response)
    done_payload = {"response": explicit_note_response, "session_id": session_id}
    if isinstance(explicit_note_payload.get("ui"), dict):
      done_payload["ui"] = explicit_note_payload["ui"]
    yield {"event": "done", "data": done_payload}
    return

  prompt = build_local_prompt(message, conversation_history=history, user_profile_context=profile_context)

  chunks: list[str] = []
  try:
    for chunk in stream_local_llm(prompt, temperature=0.7, timeout=REQUEST_TIMEOUT):
      if chunk:
        chunks.append(chunk)
        yield {"event": "delta", "data": {"delta": chunk, "session_id": session_id}}

    response_text = "".join(chunks).strip()
    if not _is_viable_response(response_text):
      yield {"event": "error", "data": {"error": "（ローカルLLM応答は不十分でした）", "session_id": session_id}}
      return

    _append_turn(session_id, "assistant", response_text)
    yield {"event": "done", "data": {"response": response_text, "session_id": session_id}}

  except HTTPError as error:
    yield {"event": "error", "data": {"error": f"（Ollama HTTPエラー: {error.code}）", "session_id": session_id}}
  except URLError as error:
    yield {"event": "error", "data": {"error": f"（Ollama接続失敗: {error.reason}）", "session_id": session_id}}
  except TimeoutError as error:
    yield {"event": "error", "data": {"error": f"（Ollamaタイムアウト: {error}）", "session_id": session_id}}
  except Exception as error:
    yield {"event": "error", "data": {"error": f"（ローカルLLMエラー: {error}）", "session_id": session_id}}


HTML_PAGE = """<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Local AI Server</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #08111f;
      --panel: rgba(15, 23, 42, 0.82);
      --panel-2: rgba(30, 41, 59, 0.9);
      --text: #e5eefb;
      --muted: #94a3b8;
      --accent: #22c55e;
      --accent-2: #38bdf8;
      --border: rgba(148, 163, 184, 0.25);
      --shadow: 0 20px 60px rgba(0, 0, 0, 0.35);
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      font-family: "Segoe UI", "Yu Gothic UI", sans-serif;
      background:
        radial-gradient(circle at top left, rgba(56, 189, 248, 0.18), transparent 36%),
        radial-gradient(circle at top right, rgba(34, 197, 94, 0.14), transparent 28%),
        linear-gradient(180deg, #050b14 0%, #0b1220 100%);
      color: var(--text);
      min-height: 100vh;
    }

    .shell {
      width: min(1000px, calc(100% - 24px));
      margin: 0 auto;
      padding: 18px 0 24px;
    }

    .hero {
      padding: 18px;
      border: 1px solid var(--border);
      border-radius: 24px;
      background: linear-gradient(180deg, rgba(15, 23, 42, 0.92), rgba(15, 23, 42, 0.75));
      box-shadow: var(--shadow);
      backdrop-filter: blur(16px);
    }

    .hero h1 {
      margin: 0;
      font-size: clamp(28px, 5vw, 44px);
      letter-spacing: 0.02em;
    }

    .hero p {
      margin: 10px 0 0;
      color: var(--muted);
      line-height: 1.7;
    }

    .toolbar {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 14px;
    }

    .chip {
      padding: 8px 12px;
      border-radius: 999px;
      border: 1px solid var(--border);
      background: rgba(15, 23, 42, 0.6);
      color: var(--text);
      font-size: 13px;
    }

    .layout {
      display: grid;
      grid-template-columns: 1.6fr 0.9fr;
      gap: 16px;
      margin-top: 16px;
    }

    .panel {
      border-radius: 24px;
      border: 1px solid var(--border);
      background: var(--panel);
      box-shadow: var(--shadow);
      overflow: hidden;
      backdrop-filter: blur(14px);
    }

    .panel-header {
      padding: 16px 18px;
      border-bottom: 1px solid var(--border);
      background: rgba(2, 6, 23, 0.2);
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
    }

    .panel-header strong {
      font-size: 14px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: #cbd5e1;
    }

    .panel-body {
      padding: 16px;
      position: relative;
    }

    #chat-log {
      min-height: 58vh;
      max-height: 68vh;
      overflow: auto;
      display: flex;
      flex-direction: column;
      gap: 12px;
      padding-right: 4px;
    }

    .bubble {
      max-width: 92%;
      padding: 12px 14px;
      border-radius: 18px;
      border: 1px solid var(--border);
      line-height: 1.7;
      white-space: pre-wrap;
      word-break: break-word;
    }

    .bubble.user {
      align-self: flex-end;
      background: linear-gradient(180deg, rgba(34, 197, 94, 0.2), rgba(34, 197, 94, 0.12));
    }

    .bubble.assistant {
      align-self: flex-start;
      background: linear-gradient(180deg, rgba(30, 41, 59, 0.92), rgba(15, 23, 42, 0.88));
    }

    .bubble.system {
      align-self: center;
      color: var(--muted);
      font-size: 13px;
      padding: 8px 12px;
      background: rgba(15, 23, 42, 0.5);
    }

    .choice-wrap {
      align-self: flex-start;
      width: min(92%, 520px);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 10px;
      background: rgba(15, 23, 42, 0.78);
      display: grid;
      gap: 8px;
    }

    .choice-title {
      font-size: 12px;
      color: var(--muted);
    }

    .choice-grid {
      display: grid;
      gap: 8px;
    }

    .choice-btn {
      width: 100%;
      text-align: left;
      color: var(--text);
      background: rgba(148, 163, 184, 0.14);
      border: 1px solid var(--border);
      box-shadow: none;
      font-weight: 600;
    }

    .composer {
      display: grid;
      gap: 10px;
      position: sticky;
      bottom: 10px;
      padding-top: 8px;
      background: linear-gradient(180deg, rgba(15, 23, 42, 0), rgba(15, 23, 42, 0.92) 25%);
    }

    .row {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }

    .quick-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
      gap: 8px;
    }

    .meta-line {
      font-size: 12px;
      color: var(--muted);
      line-height: 1.6;
      word-break: break-all;
    }

    textarea, input {
      width: 100%;
      border-radius: 16px;
      border: 1px solid var(--border);
      background: var(--panel-2);
      color: var(--text);
      padding: 14px 14px;
      outline: none;
      font: inherit;
    }

    textarea {
      min-height: 92px;
      resize: vertical;
    }

    button {
      border: 0;
      border-radius: 16px;
      padding: 12px 16px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      color: #04111f;
      background: linear-gradient(135deg, #22c55e, #38bdf8);
      box-shadow: 0 10px 30px rgba(56, 189, 248, 0.22);
    }

    button.secondary {
      color: var(--text);
      background: rgba(148, 163, 184, 0.14);
      border: 1px solid var(--border);
      box-shadow: none;
    }

    .doc-manager {
      display: grid;
      gap: 12px;
    }

    .doc-manager-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
    }

    .doc-manager-title {
      font-size: 14px;
      font-weight: 700;
      color: var(--text);
      letter-spacing: 0.04em;
    }

    .doc-list {
      display: grid;
      gap: 8px;
      max-height: 240px;
      overflow: auto;
      padding-right: 2px;
    }

    .doc-item {
      width: 100%;
      text-align: left;
      padding: 12px;
      border-radius: 16px;
      border: 1px solid var(--border);
      background: rgba(15, 23, 42, 0.72);
      color: var(--text);
      box-shadow: none;
      display: grid;
      gap: 6px;
    }

    .doc-item.active {
      border-color: rgba(56, 189, 248, 0.65);
      background: linear-gradient(180deg, rgba(56, 189, 248, 0.18), rgba(34, 197, 94, 0.12));
    }

    .doc-item-title {
      font-size: 14px;
      font-weight: 700;
      line-height: 1.45;
    }

    .doc-item-meta {
      font-size: 12px;
      color: var(--muted);
      line-height: 1.5;
      word-break: break-word;
    }

    .doc-editor {
      display: grid;
      gap: 10px;
      padding: 12px;
      border-radius: 18px;
      border: 1px solid var(--border);
      background: rgba(2, 6, 23, 0.18);
    }

    .doc-editor textarea {
      min-height: 220px;
    }

    .doc-mode {
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
    }

    .doc-actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }

    .doc-actions button {
      flex: 1 1 0;
    }

    .doc-meta {
      font-size: 12px;
      color: var(--muted);
      line-height: 1.6;
      white-space: pre-wrap;
      word-break: break-word;
    }

    .doc-empty {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.6;
    }

    .side-list {
      display: grid;
      gap: 10px;
    }

    .card {
      padding: 14px;
      border-radius: 18px;
      border: 1px solid var(--border);
      background: rgba(15, 23, 42, 0.74);
      color: var(--muted);
      line-height: 1.65;
    }

    .status {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      font-size: 13px;
      color: #bbf7d0;
    }

    .dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: var(--accent);
      box-shadow: 0 0 0 6px rgba(34, 197, 94, 0.15);
    }

    @media (max-width: 860px) {
      .layout { grid-template-columns: 1fr; }
      #chat-log { min-height: 48vh; max-height: none; }
      .bubble { max-width: 100%; }
      .composer { bottom: 0; }
      .row > * { flex: 1 1 100%; }
      button { width: 100%; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <h1>Local AI Server</h1>
      <p>このPC上の Ollama を使う、ローカル完結の会話サーバーです。iPhone からは同じWi-Fi内のURLを Safari で開いて使えます。</p>
      <div class="toolbar">
        <span class="chip status"><span class="dot"></span><span id="health-text">health: checking...</span></span>
        <span class="chip" id="server-url-chip">url: loading...</span>
        <span class="chip" id="server-ip-chip">ip: loading...</span>
        <span class="chip">session-based</span>
      </div>
      <div class="toolbar" style="margin-top:12px;">
        <span class="chip">/chat</span>
        <span class="chip">/chat/stream</span>
        <span class="chip">/health</span>
        <span class="chip">/meta</span>
      </div>
    </section>

    <div class="layout">
      <section class="panel">
        <div class="panel-header">
          <strong>Chat</strong>
          <div class="status"><span class="dot"></span><span id="session-text">session ready</span></div>
        </div>
        <div class="panel-body">
          <div id="chat-log"></div>
          <div class="composer" style="margin-top:16px;">
            <div class="quick-grid">
              <button class="secondary quick-prompt" type="button" data-text="こんにちは">こんにちは</button>
              <button class="secondary quick-prompt" type="button" data-text="今日の天気は？">天気</button>
              <button class="secondary quick-prompt" type="button" data-text="1+1">計算</button>
              <button class="secondary quick-prompt" type="button" data-text="今何時？">時刻</button>
            </div>
            <textarea id="message" placeholder="メッセージを入力..."></textarea>
            <div class="row">
              <input id="session-id" placeholder="session id" />
              <button id="send-btn">Send</button>
              <button id="reset-btn" class="secondary" type="button">Reset</button>
            </div>
          </div>
        </div>
      </section>

      <aside class="panel">
        <div class="panel-header">
          <strong>Info</strong>
        </div>
        <div class="panel-body">
          <div class="side-list">
            <div class="card meta-line" id="meta-card">サーバー情報を取得しています。</div>
            <div class="card doc-manager">
              <div class="doc-manager-header">
                <span class="doc-manager-title">保存文書</span>
                <div class="row" style="margin:0;">
                  <button id="document-new-btn" class="secondary" type="button">新規作成</button>
                  <button id="document-refresh-btn" class="secondary" type="button">更新</button>
                </div>
              </div>
              <div class="doc-list" id="document-list"></div>
              <div class="doc-editor">
                <div class="doc-mode" id="document-mode">新規登録</div>
                <input id="document-title" placeholder="文書タイトル" />
                <textarea id="document-content" placeholder="選択した文書の本文"></textarea>
                <div class="doc-actions">
                  <button id="document-save-btn" type="button">保存</button>
                  <button id="document-delete-btn" class="secondary" type="button">削除</button>
                  <button id="document-clear-btn" class="secondary" type="button">選択解除</button>
                </div>
                <div class="doc-meta" id="document-meta">文書を選択してください。</div>
              </div>
            </div>
            <div class="card">Ollama がローカルで起動している必要があります。</div>
            <div class="card">スマホから使う場合は、iPhone の Safari で上の URL を開いてください。</div>
            <div class="card">会話履歴は session id ごとに分けています。</div>
            <div class="card" id="health-card">サーバー状態を確認しています。</div>
          </div>
        </div>
      </aside>
    </div>
  </div>

  <script>
    const chatLog = document.getElementById('chat-log');
    const messageInput = document.getElementById('message');
    const sessionInput = document.getElementById('session-id');
    const sendBtn = document.getElementById('send-btn');
    const resetBtn = document.getElementById('reset-btn');
    const healthText = document.getElementById('health-text');
    const healthCard = document.getElementById('health-card');
    const metaCard = document.getElementById('meta-card');
    const serverUrlChip = document.getElementById('server-url-chip');
    const serverIpChip = document.getElementById('server-ip-chip');
    const sessionText = document.getElementById('session-text');
    const documentList = document.getElementById('document-list');
    const documentNewBtn = document.getElementById('document-new-btn');
    const documentTitleInput = document.getElementById('document-title');
    const documentContentInput = document.getElementById('document-content');
    const documentMeta = document.getElementById('document-meta');
    const documentMode = document.getElementById('document-mode');
    const documentRefreshBtn = document.getElementById('document-refresh-btn');
    const documentSaveBtn = document.getElementById('document-save-btn');
    const documentDeleteBtn = document.getElementById('document-delete-btn');
    const documentClearBtn = document.getElementById('document-clear-btn');

    const storageKey = 'local-ai-session-id';
    const savedSessionId = localStorage.getItem(storageKey) || (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()));
    localStorage.setItem(storageKey, savedSessionId);
    sessionInput.value = savedSessionId;

    function addBubble(role, text) {
      const el = document.createElement('div');
      el.className = `bubble ${role}`;
      el.textContent = text;
      chatLog.appendChild(el);
      chatLog.scrollTop = chatLog.scrollHeight;
      return el;
    }

    function addChoicePanel(ui) {
      if (!ui || !Array.isArray(ui.options) || ui.options.length === 0) {
        return;
      }
      const wrap = document.createElement('div');
      wrap.className = 'choice-wrap';

      const title = document.createElement('div');
      title.className = 'choice-title';
      title.textContent = ui.title || '候補を選択';
      wrap.appendChild(title);

      const grid = document.createElement('div');
      grid.className = 'choice-grid';
      wrap.appendChild(grid);

      ui.options.forEach((option) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'choice-btn';
        btn.textContent = option.label || option.message || '選択';
        btn.addEventListener('click', () => {
          messageInput.value = option.message || option.label || '';
          sendMessage();
        });
        grid.appendChild(btn);
      });

      chatLog.appendChild(wrap);
      chatLog.scrollTop = chatLog.scrollHeight;
    }

    let documentCache = [];
    let currentDocumentId = '';
    let documentDraftMode = true;

    function renderDocumentList(documents) {
      documentList.innerHTML = '';
      if (!documents.length) {
        const empty = document.createElement('div');
        empty.className = 'doc-empty';
        empty.textContent = '保存文書はまだありません。';
        documentList.appendChild(empty);
        return;
      }

      documents.forEach((item) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = `doc-item ${item.is_current || item.doc_id === currentDocumentId ? 'active' : ''}`.trim();

        const title = document.createElement('div');
        title.className = 'doc-item-title';
        title.textContent = item.title || '無題';
        button.appendChild(title);

        const meta = document.createElement('div');
        meta.className = 'doc-item-meta';
        meta.textContent = `${item.doc_id || 'IDなし'} | ${item.chars || 0}文字 | ${item.saved_at || item.updated_at || '日時不明'}`;
        button.appendChild(meta);

        const preview = document.createElement('div');
        preview.className = 'doc-item-meta';
        preview.textContent = item.preview || 'プレビューなし';
        button.appendChild(preview);

        button.addEventListener('click', () => {
          loadDocument(item.doc_id);
        });
        documentList.appendChild(button);
      });
    }

    function setDocumentEditor(documentData) {
      if (!documentData) {
        currentDocumentId = '';
        documentDraftMode = true;
        documentTitleInput.value = '';
        documentContentInput.value = '';
        documentMode.textContent = '新規登録';
        documentMeta.textContent = '新規文書を入力してください。';
        renderDocumentList(documentCache);
        return;
      }

      currentDocumentId = documentData.doc_id || '';
      documentDraftMode = false;
      documentTitleInput.value = documentData.title || '';
      documentContentInput.value = documentData.content || '';
      documentMode.textContent = '編集中';
      const newline = String.fromCharCode(10);
      documentMeta.textContent = [
        `文書ID: ${documentData.doc_id || 'なし'}`,
        `文字数: ${documentData.chars || (documentData.content || '').length || 0}`,
        `保存時刻: ${documentData.saved_at || documentData.updated_at || '不明'}`,
        `更新時刻: ${documentData.updated_at || '不明'}`,
        `ファイル: ${documentData.file_path || '不明'}`,
      ].join(newline);
      renderDocumentList(documentCache);
    }

    async function refreshDocuments(preferredDocId = currentDocumentId) {
      try {
        const res = await fetch('/documents');
        const data = await res.json();
        if (!data.ok) {
          throw new Error(data.error || 'documents unavailable');
        }

        documentCache = Array.isArray(data.documents) ? data.documents : [];
        renderDocumentList(documentCache);

        if (documentDraftMode && !preferredDocId) {
          return;
        }

        const currentDoc = data.session?.current_doc_id
          ? documentCache.find((item) => item.doc_id === data.session.current_doc_id)
          : null;
        const targetDoc = preferredDocId
          ? documentCache.find((item) => item.doc_id === preferredDocId)
          : null;

        if (targetDoc) {
          await loadDocument(targetDoc.doc_id, { skipRefresh: true });
        } else if (currentDoc) {
          await loadDocument(currentDoc.doc_id, { skipRefresh: true });
        } else if (!documentCache.length) {
          setDocumentEditor(null);
        }
      } catch (e) {
        documentCache = [];
        documentList.innerHTML = '';
        const error = document.createElement('div');
        error.className = 'doc-empty';
        error.textContent = '文書一覧を取得できませんでした。';
        documentList.appendChild(error);
        setDocumentEditor(null);
      }
    }

    async function loadDocument(docId, options = {}) {
      if (!docId) {
        setDocumentEditor(null);
        return;
      }

      try {
        const res = await fetch(`/documents/${encodeURIComponent(docId)}`);
        const data = await res.json();
        if (!data.ok || !data.document) {
          throw new Error(data.error || 'document unavailable');
        }

        setDocumentEditor(data.document);
        if (!options.skipRefresh) {
          await refreshDocuments(docId);
        }
      } catch (e) {
        addBubble('system', '文書の読み込みに失敗しました。');
      }
    }

    async function saveDocument() {
      const title = documentTitleInput.value.trim();
      const content = documentContentInput.value;
      if (!title || !content.trim()) {
        addBubble('system', 'タイトルと本文を入力してください。');
        return;
      }

      try {
        const isNewDocument = !currentDocumentId;
        const res = await fetch(isNewDocument ? '/documents' : `/documents/${encodeURIComponent(currentDocumentId)}`, {
          method: isNewDocument ? 'POST' : 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title, content }),
        });
        const data = await res.json();
        if (!data.ok) {
          throw new Error(data.error || 'update failed');
        }

        addBubble('system', isNewDocument ? '文書を新規登録しました。' : '文書を保存しました。');
        setDocumentEditor(data.document || null);
        await refreshDocuments(data.document?.doc_id || currentDocumentId);
      } catch (e) {
        addBubble('system', currentDocumentId ? '文書の保存に失敗しました。' : '文書の新規登録に失敗しました。');
      }
    }

    async function deleteDocument() {
      if (!currentDocumentId) {
        addBubble('system', '削除する文書を選択してください。');
        return;
      }

      const currentTitle = documentTitleInput.value.trim() || 'この文書';
      if (!window.confirm(`${currentTitle} を削除しますか？`)) {
        return;
      }

      try {
        const res = await fetch(`/documents/${encodeURIComponent(currentDocumentId)}`, {
          method: 'DELETE',
        });
        const data = await res.json();
        if (!data.ok) {
          throw new Error(data.error || 'delete failed');
        }

        addBubble('system', '文書を削除しました。');
        setDocumentEditor(null);
        await refreshDocuments();
      } catch (e) {
        addBubble('system', '文書の削除に失敗しました。');
      }
    }

    function clearDocumentSelection() {
      currentDocumentId = '';
      documentDraftMode = true;
      documentTitleInput.value = '';
      documentContentInput.value = '';
      documentMode.textContent = '新規登録';
      documentMeta.textContent = '新規文書を入力してください。';
      renderDocumentList(documentCache);
    }

    function setStatus(text) {
      healthText.textContent = text;
      healthCard.textContent = text;
    }

    function setMeta(meta) {
      const urls = meta?.server?.open_urls || [];
      const localIp = meta?.server?.local_ip || 'unknown';
      const firstUrl = urls[0] || 'http://localhost:8000/';
      const newline = String.fromCharCode(10);
      serverUrlChip.textContent = `url: ${firstUrl}`;
      serverIpChip.textContent = `ip: ${localIp}`;
      metaCard.textContent = `PCのURL: ${firstUrl}` + newline + `ローカルIP: ${localIp}` + newline + `Ollama: ${meta?.local_llm?.model || 'unknown'}` + newline;
    }

    async function refreshHealth() {
      try {
        const res = await fetch('/health');
        const data = await res.json();
        setStatus(`health: ${data.status} | model: ${data.ollama?.model_configured || data.model}`);
      } catch (e) {
        setStatus('health: offline');
      }
    }

    async function refreshMeta() {
      try {
        const res = await fetch('/meta');
        const data = await res.json();
        if (data.ok) {
          setMeta(data);
        }
      } catch (e) {
        serverUrlChip.textContent = 'url: unavailable';
        serverIpChip.textContent = 'ip: unavailable';
      }
    }

    async function sendMessage() {
      const text = messageInput.value.trim();
      const sessionId = sessionInput.value.trim() || savedSessionId;
      if (!text) {
        return;
      }

      sessionInput.value = sessionId;
      localStorage.setItem(storageKey, sessionId);
      sessionText.textContent = sessionId;

      addBubble('user', text);
      messageInput.value = '';

      const typing = addBubble('system', 'thinking...');
      sendBtn.disabled = true;

      try {
        const res = await fetch('/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: text, session_id: sessionId })
        });
        const data = await res.json();
        typing.remove();
        if (data.ok) {
          addBubble('assistant', data.response);
          if (data.ui) {
            addChoicePanel(data.ui);
          }
          await refreshDocuments();
        } else {
          addBubble('assistant', data.error || 'error');
        }
      } catch (e) {
        typing.remove();
        addBubble('assistant', '通信に失敗しました。');
      } finally {
        sendBtn.disabled = false;
        messageInput.focus();
      }
    }

    sendBtn.addEventListener('click', sendMessage);
    documentNewBtn.addEventListener('click', clearDocumentSelection);
    documentRefreshBtn.addEventListener('click', () => refreshDocuments());
    documentSaveBtn.addEventListener('click', saveDocument);
    documentDeleteBtn.addEventListener('click', deleteDocument);
    documentClearBtn.addEventListener('click', clearDocumentSelection);
    document.querySelectorAll('.quick-prompt').forEach((button) => {
      button.addEventListener('click', () => {
        messageInput.value = button.dataset.text || '';
        messageInput.focus();
      });
    });
    resetBtn.addEventListener('click', () => {
      localStorage.removeItem(storageKey);
      const freshId = crypto.randomUUID ? crypto.randomUUID() : String(Date.now());
      localStorage.setItem(storageKey, freshId);
      sessionInput.value = freshId;
      sessionText.textContent = freshId;
      chatLog.innerHTML = '';
      addBubble('system', 'session reset');
    });
    messageInput.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
      }
    });
    sessionInput.addEventListener('change', () => {
      const value = sessionInput.value.trim();
      if (value) {
        localStorage.setItem(storageKey, value);
        sessionText.textContent = value;
      }
    });

    addBubble('system', 'local-only server ready');
    refreshMeta();
    refreshHealth();
    refreshDocuments();
    setInterval(refreshHealth, 10000);
    setInterval(refreshMeta, 60000);
    setInterval(() => refreshDocuments(), 30000);
    messageInput.focus();
  </script>
</body>
</html>
"""


class LocalAIServerHandler(BaseHTTPRequestHandler):
  server_version = "LocalAIServer/1.0"
  protocol_version = "HTTP/1.1"

  def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    self.send_response(status)
    self.send_header("Content-Type", "application/json; charset=utf-8")
    self.send_header("Content-Length", str(len(body)))
    self.send_header("Cache-Control", "no-store")
    self.end_headers()
    self.wfile.write(body)

  def _send_html(self, html: str) -> None:
    html = re.sub(r"\]\.join\('\s*'\);", "].join(String.fromCharCode(10));", html, count=1)
    body = html.encode("utf-8")
    self.send_response(200)
    self.send_header("Content-Type", "text/html; charset=utf-8")
    self.send_header("Content-Length", str(len(body)))
    self.send_header("Cache-Control", "no-store")
    self.end_headers()
    self.wfile.write(body)

  def _send_sse_headers(self) -> None:
    self.send_response(200)
    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
    self.send_header("Cache-Control", "no-cache, no-transform")
    self.send_header("Connection", "keep-alive")
    self.end_headers()

  def _send_sse_event(self, event: str, data: dict[str, Any]) -> None:
    payload = json.dumps(data, ensure_ascii=False)
    message = f"event: {event}\ndata: {payload}\n\n".encode("utf-8")
    self.wfile.write(message)
    self.wfile.flush()

  def _read_json(self) -> dict[str, Any]:
    length = int(self.headers.get("Content-Length", "0"))
    if length <= 0:
      return {}
    raw = self.rfile.read(length)
    try:
      return json.loads(raw.decode("utf-8"))
    except Exception:
      return {}

  def _document_id_from_path(self, path: str) -> str:
    return path.removeprefix("/documents/").strip("/")

  def do_GET(self) -> None:
    path = urlparse(self.path).path

    if path == "/" or path == "/index.html":
      self._send_html(HTML_PAGE)
      return

    if path == "/health":
      self._send_json(_health_snapshot())
      return

    if path == "/meta":
      self._send_json(_server_meta())
      return

    if path == "/sessions":
      self._send_json({"ok": True, "sessions": _list_sessions()})
      return

    if path == "/documents":
      self._send_json({"ok": True, "documents": list_document_items(), "session": get_document_session()})
      return

    if path == "/documents/current":
      self._send_json({"ok": True, "document": get_current_document_item(), "session": get_document_session()})
      return

    if path.startswith("/sessions/"):
      session_id = path.removeprefix("/sessions/").strip("/")
      if not session_id:
        self._send_json({"ok": False, "error": "session_id is required"}, status=400)
        return

      self._send_json({"ok": True, "session_id": session_id, "history": _snapshot_session(session_id)})
      return

    if path.startswith("/documents/"):
      doc_id = self._document_id_from_path(path)
      if not doc_id:
        self._send_json({"ok": False, "error": "doc_id is required"}, status=400)
        return

      document = get_document_item(doc_id=doc_id)
      if not document:
        self._send_json({"ok": False, "error": "not found"}, status=404)
        return

      self._send_json({"ok": True, "document": document, "session": get_document_session()})
      return

    self._send_json({"ok": False, "error": "not found"}, status=404)

  def do_POST(self) -> None:
    path = urlparse(self.path).path

    if path not in {"/chat", "/chat/stream", "/sessions/clear", "/documents"}:
      self._send_json({"ok": False, "error": "not found"}, status=404)
      return

    data = self._read_json()
    message = str(data.get("message", ""))

    if path == "/sessions/clear":
      session_id = str(data.get("session_id", "")).strip()
      if session_id:
        cleared = _clear_session(session_id)
        self._send_json({"ok": True, "cleared": cleared, "session_id": session_id})
      else:
        _clear_all_sessions()
        self._send_json({"ok": True, "cleared": True, "scope": "all"})
      return

    if path == "/documents":
      title = str(data.get("title", "")).strip()
      content = str(data.get("content", "")).strip()
      result = create_document_item(title, content, source_text=str(data.get("source_text", "")))
      self._send_json(result, status=200 if result.get("ok") else 400)
      return

    session_id = str(data.get("session_id") or uuid4().hex)

    if path == "/chat/stream":
      self._send_sse_headers()
      for event in _stream_chat_payload(message, session_id):
        self._send_sse_event(event["event"], event["data"])
      return

    response = _build_chat_payload(message, session_id)
    self._send_json(response, status=200 if response.get("ok") else 400)

  def do_PUT(self) -> None:
    path = urlparse(self.path).path

    if not path.startswith("/documents/"):
      self._send_json({"ok": False, "error": "not found"}, status=404)
      return

    doc_id = self._document_id_from_path(path)
    if not doc_id:
      self._send_json({"ok": False, "error": "doc_id is required"}, status=400)
      return

    data = self._read_json()
    title = data.get("title")
    content = data.get("content")
    result = update_document_item(doc_id, title=str(title) if title is not None else None, content=str(content) if content is not None else None)
    self._send_json(result, status=200 if result.get("ok") else 400)

  def do_DELETE(self) -> None:
    path = urlparse(self.path).path

    if path == "/sessions":
      _clear_all_sessions()
      self._send_json({"ok": True, "cleared": True, "scope": "all"})
      return

    if path.startswith("/documents/"):
      doc_id = self._document_id_from_path(path)
      if not doc_id:
        self._send_json({"ok": False, "error": "doc_id is required"}, status=400)
        return

      result = delete_document_item(doc_id)
      self._send_json(result, status=200 if result.get("ok") else 400)
      return

    if path.startswith("/sessions/"):
      session_id = path.removeprefix("/sessions/").strip("/")
      if not session_id:
        self._send_json({"ok": False, "error": "session_id is required"}, status=400)
        return

      cleared = _clear_session(session_id)
      self._send_json({"ok": True, "cleared": cleared, "session_id": session_id})
      return

    self._send_json({"ok": False, "error": "not found"}, status=404)

  def log_message(self, format: str, *args: Any) -> None:
    return


class QuietThreadingHTTPServer(ThreadingHTTPServer):
  def handle_error(self, request, client_address) -> None:
    exc_type, exc_value, _ = sys.exc_info()
    if exc_type is not None and issubclass(exc_type, (ConnectionResetError, BrokenPipeError, TimeoutError)):
      return

    if isinstance(exc_value, OSError) and getattr(exc_value, "winerror", None) in {10053, 10054, 10060}:
      return

    super().handle_error(request, client_address)


def run_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    server = QuietThreadingHTTPServer((host, port), LocalAIServerHandler)
    print(f"Local AI server running on http://{host}:{port}")
    print(f"Open the UI on the PC or from your smartphone on the same network.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down local AI server...")
    finally:
        server.server_close()


if __name__ == "__main__":
    run_server()
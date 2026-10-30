"""ブラウザからの入力を受け、専用機能・ローカルLLM・クラウドAIへ振り分けて応答するHTTPサーバーで、ローカル優先の対話UIを動かします。"""

# ブラウザからの入力を受け、専用機能・ローカルLLM・クラウドAIへ振り分けて応答を返すHTTPサーバーです。会話履歴、入力判定、文書管理、評価記録、画面表示を一体で制御し、ローカル優先の対話UIを動かします。

from __future__ import annotations  # 型注釈の評価を遅らせ、後で定義する型も参照できるようにする

import json       # JSON形式のデータをPythonの値に変換し、その逆の変換も行う
import mimetypes
import os         # 環境変数からサーバー設定を読み込む
import re         # 正規表現で入力文の判定や文字列処理を行う
import sys        # 発生中の例外情報を取得する
import threading  # 複数処理から共有データを扱う際のロックに使う
import time       # 処理時間の計測やキャッシュ期限の判定に使う
import queue
import socket     # ネットワーク接続に使うPCのIPアドレスを取得する

from collections import deque  # 保存件数に上限を設けられるキューで会話履歴を管理する
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # HTTPリクエスト処理と複数接続対応のサーバーに使う
from typing import Any  # 任意の型の値を受け取ることを型注釈で示す
from urllib.error import HTTPError, URLError  # HTTP応答のエラーや接続エラーを扱う
from urllib.request import Request, urlopen  # HTTPリクエストを作成・送信し、応答を取得する
from urllib.parse import parse_qs, urlparse  # URLを分解し、リクエストのパスとクエリを取り出す
from uuid import uuid4  # セッションIDやリクエストIDなどに使う識別子を生成する


import config  # モデル名や接続先など、システム設定を読み込む
from functions.calculator import calculate  # 入力文に含まれる計算を実行する
from functions.calculator import _extract_expression  # 入力文から計算式を抽出する
from functions.location import get_location_details  # 現在地の詳細情報を取得する
from functions.time_func import get_time, get_weekday, get_weekday_from_text  # 現在時刻・今日の曜日・指定日の曜日を取得する
from functions.transit import _extract_destination, resolve_navigation  # 目的地の抽出と経路案内を行う
from models.intent_classifier import classify_intent  # 入力文から質問や依頼の種類を判定する
from models.user_profile_memory import (  # 利用者情報と保存文書を管理する関数を読み込む
    build_profile_context,  # AIへ渡す利用者情報をまとめる
    create_document_item,  # 文書を新規保存する
    ensure_memory_stores,  # メモリや文書の保存領域を準備・確認する
    handle_explicit_note_command,  # 明示的なメモ・文書操作の指示を処理する
    handle_explicit_note_command_with_meta,  # 操作結果に画面表示用の情報などを付けて返す
    delete_document_item,  # 保存文書を削除する
    get_current_document_item,  # 現在選択されている文書を取得する
    get_document_item,  # 指定した文書を取得する
    get_document_session,  # 文書の選択状態などを取得する
    get_storage_status,  # 保存領域の状態を取得する
    list_document_items,  # 保存文書の一覧を取得する
    update_document_item,  # 保存文書の内容を更新する
    update_profile_from_text,  # 入力文をもとに利用者情報を更新する
)


from cloud.local_llm import ask_local_llm as _ask_local_llm, ask_local_llm_json, stream_local_llm  # ローカルLLMから通常回答・JSON回答・逐次生成の回答を取得する
from cloud.local_prompt import build_local_prompt  # 質問や会話履歴、利用者情報からローカルLLMへの指示文を作る
from cloud.openai_client import ask_cloud_ai as _ask_cloud_ai  # クラウドAIへ指示文を送り、回答を取得する
from functions.google_workspace import search_google_web, search_google_web_structured  # Google検索の結果を文章形式・構造化データ形式で取得する
from functions.weather import get_weather, parse_weather_query  # 指定地域などの天気情報を取得する
from models.evaluation_metrics import build_user_facing_evaluation, evaluation_metrics  # 画面用の評価情報を作成し、評価記録の保存・集計を行う


from functions.system_monitor import system_monitor
from functions.research_tools import translate_text_structured, wikipedia_summary
from functions.dashboard_tools import youtube_results, local_qr
from models.execution_trace import (traced_request, run_stage, add_card, mark_text_ready,
                                    event_sink, processing_history, save_client_timings, processing_csv)


def _tool_call(kind, function, *args, **kwargs):
    def outcome(value):
        if isinstance(value, dict):
            return bool(value.get('ok', True))
        return not (isinstance(value, str) and re.search(r'取得できません|取得に失敗|検索に失敗|失敗しました|未設定です|特定できません', value))
    result = run_stage('tool', function, *args, tool_name=kind, success_check=outcome, **kwargs)
    if kind == 'document':
        if isinstance(result, dict) and ('document' in result or 'documents' in result):
            add_card(kind, result, success=result.get('ok', True))
    else:
        data = result if isinstance(result, dict) else {'text': str(result), 'query': str(args[0]) if args else ''}
        success = bool(data.get('ok', True))
        if isinstance(result, str) and re.search(r'取得できません|取得に失敗|検索に失敗|失敗しました|未設定です', result):
            success = False
        add_card(kind, data, success=success)
    return result


def _parse_dashboard_request(text):
    # これは実行するツールの選択。カードは実行後の戻り値からのみ作る。
    if re.search(r'(?:CPU|GPU|RAM|メモリ|ディスク|ネットワーク).*(?:使用|状態|温度|空き)|システム(?:情報|モニター)', text, re.I):
        return {'kind': 'system'}
    if re.search(r'QR(?:コード)?', text, re.I):
        match = re.search(r'(?:QR(?:コード)?(?:を)?(?:作成|生成|にして|化して)?[：:\s]+)(.+)', text, re.I | re.S)
        value = match.group(1).strip() if match else re.sub(r'(?:を|の)?QRコード.*$', '', text, flags=re.I).strip()
        return {'kind': 'qr', 'text': value}
    if re.search(r'YouTube|ユーチューブ', text, re.I):
        query = re.sub(r'YouTube|ユーチューブ|で検索して|を検索して|を探して|で探して|検索して', '', text, flags=re.I).strip(' ：:をで')
        return {'kind': 'youtube', 'query': query}
    if re.search(r'Wikipedia|ウィキペディア', text, re.I):
        query = re.sub(r'Wikipedia|ウィキペディア|で調べて|で検索して|を調べて|を検索して', '', text, flags=re.I).strip(' ：:をで')
        return {'kind': 'wikipedia', 'query': query}
    match = re.search(r'^(?:次の(?:文章|英文|文|テキスト)を)?(日本語|英語|中国語|韓国語|フランス語|ドイツ語)に(?:翻訳してください|翻訳して|翻訳|訳して)[：:\s]+(.+)$', text, re.S)
    if match:
        languages = {'日本語':'ja','英語':'en','中国語':'zh-CN','韓国語':'ko','フランス語':'fr','ドイツ語':'de'}
        return {'kind': 'translate', 'text': match.group(2).strip(), 'target_lang': languages[match.group(1)], 'source_lang':'auto'}
    match = re.search(r'(.+?)(?:を|って)(日本語|英語|中国語|韓国語)に(?:翻訳して|訳して)', text, re.S)
    if match:
        return {'kind':'translate','text':match.group(1).strip('「」 '),'target_lang':{'日本語':'ja','英語':'en','中国語':'zh-CN','韓国語':'ko'}[match.group(2)],'source_lang':'auto'}
    return None


def _dispatch_dashboard_tool(request):
    kind = str(request.get('kind') or '')
    query = str(request.get('query') or '')[:4000]
    if kind == 'translate':
        text = str(request.get('text') or '')[:10000]
        source = str(request.get('source_lang') or 'auto')
        target = str(request.get('target_lang') or 'en')
        if source not in {'auto','ja','en','zh-CN','ko','fr','de','es'} or target not in {'ja','en','zh-CN','ko','fr','de','es'}:
            raise ValueError('対応する言語を選択してください。')
        result = run_stage('tool', translate_text_structured, text, target_lang=target, source_lang=source, tool_name='translate')
        add_card('translate', {**result, 'original_text':text, 'target_language':target,
                              'external_url':'https://translate.google.com/?sl='+source+'&tl='+target+'&text='+__import__('urllib.parse',fromlist=['quote']).quote(text)+'&op=translate'}, success=result.get('ok'))
        return bool(result.get('ok')), str(result.get('translated_text') or result.get('error') or '翻訳に失敗しました。')
    if kind == 'system':
        result = _tool_call('system', system_monitor.snapshot)
        if not result.get('ok'):
            return False, result.get('error','取得できませんでした。')
        return True, f"バックエンドPCのCPU使用率は{result['cpu']['usage_percent']}%、RAM使用率は{result['memory']['usage_percent']}%です。"
    if kind == 'document':
        def read_document():
            doc_id = str(request.get('doc_id') or '')
            if doc_id:
                document = get_document_item(doc_id=doc_id)
                return {'ok': bool(document), 'document': document, 'error':'' if document else '文書が見つかりませんでした。'}
            return {'ok': True, 'documents': list_document_items()}
        result = _tool_call('document', read_document)
        document = result.get('document') or {}
        return bool(result.get('ok')), str(document.get('content') or result.get('error') or f"保存文書は{len(result.get('documents',[]))}件です。文書パネルで選択できます。")
    if kind in {'youtube','qr'}:
        result = _tool_call(kind, youtube_results if kind == 'youtube' else local_qr, query if kind == 'youtube' else str(request.get('text') or ''))
        return bool(result.get('ok')), str(result.get('error') or ('動画一覧を表示しました。' if kind == 'youtube' else 'QRコードをPC内で生成しました。'))
    if kind == 'wikipedia':
        result = _tool_call('search', wikipedia_summary, query)
        return '失敗しました' not in result and '取得できません' not in result, result
    if kind == 'search':
        result = _tool_call('search', search_google_web_structured, query)
        return bool(result.get('ok')), _format_structured_search_response(result) if result.get('ok') else '検索結果を取得できませんでした。'
    if kind == 'weather':
        result = _tool_call('weather', get_weather, query)
        return not bool(re.search(r'取得できません|取得に失敗',result)), result
    if kind == 'map':
        result = _tool_call('map', resolve_navigation, query)
        return not bool(re.search(r'失敗しました',result)), result
    raise ValueError('対応していないツールです。')


# リクエストごとに実行中の処理状態をSSEへ通知する。
_ACTIVITY = threading.local()


def _notify_activity(state):
    callback = getattr(_ACTIVITY, "callback", None)
    if callback:
        callback({"state": state})


def ask_local_llm(*args, **kwargs):
    _notify_activity("thinking")
    return _ask_local_llm(*args, **kwargs)


def ask_cloud_ai(*args, **kwargs):
    _notify_activity("cloud")
    return _ask_cloud_ai(*args, **kwargs)


def _chat_activity_events(message, session_id, **kwargs):
    """通常の/chat処理を維持し、状態と最終結果のみを別スレッドから通知。"""
    events = queue.Queue()

    def work():
        _ACTIVITY.callback = lambda data: events.put({"event": "status", "data": data})
        try:
            _notify_activity("analyzing")
            with event_sink(events.put):
                payload = _build_chat_payload(message, session_id, **kwargs)
            events.put({"event": "done" if payload.get("ok") else "error", "data": payload})
        except Exception:
            events.put({"event": "error", "data": {"ok": False, "error": "処理中にエラーが発生しました。"}})
        finally:
            del _ACTIVITY.callback

    threading.Thread(target=work, daemon=True).start()
    while True:
        try:
            event = events.get(timeout=10)
        except queue.Empty:
            yield {"event": "ping", "data": {}}
            continue
        yield event
        if event["event"] in {"done", "error"}:
            break


# サーバー全体で使う基本設定
DEFAULT_HOST = os.getenv("LOCAL_AI_SERVER_HOST", "0.0.0.0")
DEFAULT_PORT = int(os.getenv("LOCAL_AI_SERVER_PORT", "8000"))
MAX_HISTORY_TURNS = int(os.getenv("LOCAL_AI_SERVER_HISTORY", "12"))
REQUEST_TIMEOUT = float(os.getenv("LOCAL_AI_SERVER_TIMEOUT", str(config.OLLAMA_TIMEOUT)))
MAX_RETRIES = int(os.getenv("LOCAL_AI_SERVER_RETRIES", "2"))
ROUTING_MODE_DEFAULT = os.getenv("ROUTING_MODE", "DYNAMIC_ROUTING").strip().upper()
VALID_ROUTING_MODES = {"LOCAL_ONLY", "FIXED_ROUTING", "DYNAMIC_ROUTING"}
RETRY_SUFFIX = "\n\n追加指示: 回答は結論を先に、1〜2文で短く自然に答えてください。"

# 画面から直接選べる代表的な操作テンプレート
CAPABILITY_ITEMS = [
  {
    "id": "capability_overview",
    "title": "できること一覧を見る",
    "summary": "このローカルサーバーで今すぐ使える処理一覧を返します。",
    "template": "このローカルサーバーでできることを具体例つきで教えて",
  },
  {
    "id": "time",
    "title": "時刻・曜日",
    "summary": "現在時刻や曜日を返します。",
    "template": "今何時？",
  },
  {
    "id": "weekday",
    "title": "日付・曜日確認",
    "summary": "相対日付を含む曜日確認に使えます。",
    "template": "明日の曜日は？",
  },
  {
    "id": "calc",
    "title": "計算",
    "summary": "簡単な四則演算を返します。",
    "template": "(150+230)÷19 を計算して",
  },
  {
    "id": "route",
    "title": "ルート検索",
    "summary": "経路案内とGoogle Mapsリンクを返します。",
    "template": "ここから東京駅までの行き方を教えて",
  },
  {
    "id": "search",
    "title": "Web検索",
    "summary": "事実確認系の質問を検索結果ベースで返します。",
    "template": "エッジAIとは何か調べて",
  },
  {
    "id": "save_doc",
    "title": "文書保存",
    "summary": "自己PRやES文面を文書DBに保存します。",
    "template": "タイトル「就活で使う自己PR_研究」で本文「私はローカルAIとエッジAIの研究を進めています。」を保存して",
  },
  {
    "id": "list_docs",
    "title": "保存文書一覧",
    "summary": "保存済みの自己PR文書を一覧表示します。",
    "template": "保存してある自己PR文書を一覧で見せて",
  },
  {
    "id": "show_doc",
    "title": "文書表示",
    "summary": "文書IDやキーワードで本文を表示します。",
    "template": "DOC000005を表示して",
  },
  {
    "id": "update_doc",
    "title": "文書更新",
    "summary": "既存文書の本文を更新します。",
    "template": "DOC000005の本文を次の内容に更新して: 強みは全体最適を実現するマネジメント力です。",
  },
  {
    "id": "delete_doc",
    "title": "文書削除",
    "summary": "不要な保存文書を削除します。",
    "template": "DOC000005を削除して",
  },
  {
    "id": "chat",
    "title": "ローカル会話",
    "summary": "短い相談や説明依頼にローカルLLMで応答します。",
    "template": "この研究テーマを30秒で説明できる文章にして",
  },
]

# メモリや文書DBの保存先を先に整える
ensure_memory_stores()

_SESSION_LOCK = threading.RLock()
_SESSION_HISTORY: dict[str, deque[dict[str, str]]] = {}
_SESSION_LOCATION_CONTEXT: dict[str, dict[str, Any]] = {}
_PENDING_API_APPROVAL: dict[str, dict[str, str]] = {}
_SESSION_LOCATION_TTL_SECONDS = max(0, int(os.getenv("SESSION_LOCATION_TTL_SECONDS", "300")))
_LOCATION_WEATHER_CACHE_TTL_SECONDS = max(60, int(os.getenv("LOCATION_WEATHER_CACHE_TTL_SECONDS", "1800")))
_LOCATION_WEATHER_CACHE: dict[str, Any] = {
  "payload": None,
  "expires_at": 0.0,
  "cache_key": "",
}

API_APPROVE_PREFIX = "__API_APPROVE__"
API_REJECT_PREFIX = "__API_REJECT__"


# 入力の種類を見分けるためのキーワード群
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
_COMPARISON_KEYWORDS = ("比較", "違い", "比べ", "どっち", "どちら")
_DEICTIC_MARKERS = ("これ", "それ", "あれ", "この", "その", "あの", "指定した", "さっきの", "前の")
_GENERIC_REQUEST_KEYWORDS = ("して", "教えて", "作って", "まとめて", "比較", "違い", "提案", "案内")
_NAVIGATION_PLACEHOLDER_PATTERNS = (
  "指定した場所",
  "その場所",
  "あの場所",
  "目的地",
  "行き先",
)
_CLARIFICATION_TEMPLATE_RE = re.compile(
  r"^元の依頼：(?P<original>.+?)\n追加情報：(?P<extra>.+?)\n上記の追加情報を使って元の依頼を再計算してください。?$",
  re.DOTALL,
)


# 会話履歴とセッション状態の管理
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
    cleared_history = _SESSION_HISTORY.pop(session_id, None) is not None
    _SESSION_LOCATION_CONTEXT.pop(session_id, None)
    return cleared_history


def _clear_all_sessions() -> None:
  with _SESSION_LOCK:
    _SESSION_HISTORY.clear()
    _SESSION_LOCATION_CONTEXT.clear()


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


def _get_session_location_details(session_id: str) -> dict[str, Any] | None:
  now = time.time()
  with _SESSION_LOCK:
    cached = _SESSION_LOCATION_CONTEXT.get(session_id)
    if cached:
      expires_at = float(cached.get("expires_at") or 0.0)
      if expires_at > now:
        details = dict(cached.get("details") or {})
        details["session_cache_hit"] = True
        return details

  details = get_location_details(use_cache=True)
  if not isinstance(details, dict):
    return None

  with _SESSION_LOCK:
    _SESSION_LOCATION_CONTEXT[session_id] = {
      "details": dict(details),
      "expires_at": now + _SESSION_LOCATION_TTL_SECONDS,
    }

  provider = details.get("provider") or "unknown"
  lat = details.get("latitude")
  lon = details.get("longitude")
  print(f"session_location session={session_id} provider={provider} lat={lat} lon={lon}")
  details["session_cache_hit"] = False
  return details


# 応答品質の判定と質問タイプの推定
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


def _looks_like_capability_question(text: str) -> bool:
  normalized = (text or "").strip().lower()
  if not normalized:
    return False

  capability_keywords = (
    "何ができる",
    "できること",
    "使える機能",
    "どんなことができる",
    "何を頼める",
    "機能一覧",
    "このローカル",
    "このサーバー",
  )
  return any(keyword in normalized for keyword in capability_keywords)


def _looks_like_greeting(text: str) -> bool:
  normalized = (text or "").strip()
  return bool(re.search(r"^(こんにちは|こんばんは|おはよう|やあ|もしもし|はじめまして)[!！。\s]*$", normalized))


def _looks_like_translation_history_question(text: str) -> bool:
  normalized = (text or "").strip()
  if not normalized:
    return False
  return bool(re.search(r"(直前|さっき|前回|前の).*(翻訳).*(英文|英語)", normalized))


def _extract_recent_translation_english(history: list[dict[str, str]]) -> str:
  for turn in reversed(history[:-1]):
    if turn.get("role") != "user":
      continue
    content = str(turn.get("content") or "").strip()
    if not content:
      continue
    if _looks_like_translation_history_question(content):
      continue
    if not re.search(r"[A-Za-z]", content):
      continue

    quoted = re.search(r"[\"'“”‘’]([A-Za-z][^\"'“”‘’]{2,})[\"'“”‘’]", content)
    if quoted:
      return quoted.group(1).strip()

    cleaned = re.sub(r"^(翻訳して|訳して|英訳して|和訳して|次を翻訳して|これを翻訳して)[：:\s]*", "", content, flags=re.IGNORECASE)
    if re.search(r"[A-Za-z]", cleaned):
      return cleaned.strip()
    return content
  return ""


def _build_capability_payload() -> dict[str, Any]:
  lines = [
    "このローカルサーバーで今すぐ使える処理は次のとおりです。",
    "- 時刻・曜日確認: 今何時？ / 明日の曜日は？",
    "- 計算: 1250×38を計算して",
    "- ルート検索: ここから東京駅まで / 新宿駅から渋谷駅までの行き方",
    "- Web検索: エッジAIとは何か調べて / ○○の意味を教えて",
    "- 文書保存: タイトル「自己PR」で本文「...」を保存して",
    "- 文書一覧・表示: 保存文書を一覧で見せて / DOC000005を表示して",
    "- 文書更新・削除: DOC000005の本文を更新して / DOC000005を削除して",
    "- ローカル会話: この研究テーマを30秒で説明できる文章にして",
    "下の候補を押すと、送信せずに質問テンプレートを入力欄へ入れられます。",
  ]
  return {
    "response": "\n".join(lines),
    "ui": {
      "type": "capability_templates",
      "title": "使いたい処理テンプレートを選択",
      "description": "押すと入力欄にテンプレートを入れます。必要なら少し書き換えて送信してください。",
      "interaction": "fill",
      "options": [
        {
          "label": item["title"],
          "message": item["template"],
          "description": item["summary"],
        }
        for item in CAPABILITY_ITEMS
      ],
    },
  }


def _capabilities_api_payload() -> dict[str, Any]:
  capability_payload = _build_capability_payload()
  return {
    "ok": True,
    "summary": capability_payload["response"],
    "templates": CAPABILITY_ITEMS,
    "ui": capability_payload["ui"],
  }


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


def _parse_clarification_followup(text: str) -> tuple[str, str] | None:
  match = _CLARIFICATION_TEMPLATE_RE.match((text or "").strip())
  if not match:
    return None

  original = match.group("original").strip()
  extra = match.group("extra").strip()
  if not original or not extra:
    return None
  return original, extra


def _build_general_clarification_ui(original_message: str, question: str) -> dict[str, Any]:
  original = (original_message or "").strip()
  template = f"元の依頼：{original}\n追加情報：{{value}}\n上記の追加情報を使って元の依頼を再計算してください。"
  return _build_missing_info_ui(
    title=(question or "必要な情報を入力してください").strip(),
    placeholder="不足している情報を入力してください",
    field="clarification_answer",
    question=template,
  )


def _build_clarification_followup_prompt(original_message: str, additional_info: str) -> str:
  original = (original_message or "").strip()
  extra = (additional_info or "").strip()
  return (
    f"元の依頼：{original}\n"
    f"追加情報：{extra}\n"
    "指示：追加情報を必ず使って、元の依頼に対する最終回答だけを日本語で返してください。"
  )


def _needs_navigation_destination(text: str) -> bool:
  destination = _extract_destination((text or "").strip())
  if not destination:
    return True

  if any(token in destination for token in _NAVIGATION_PLACEHOLDER_PATTERNS):
    return True

  if destination in {"ここ", "そこ", "あそこ", "この場所", "その場所", "あの場所"}:
    return True

  return False


def _extract_comparison_targets(text: str) -> tuple[str, str] | None:
  normalized = (text or "").strip()
  patterns = [
    r"(?P<left>[^\s、,。]+)と(?P<right>[^\s、,。]+?)(?:の(?:主な)?違い|を比較|を比べ|のメリット・デメリット|のメリットとデメリット|どっち|どちら)",
    r"(?P<left>[^\s、,。]+)、(?P<right>[^\s、,。]+?)(?:の違い|を比較|を比べ)",
    r"(?P<left>[^\s、,。]+)\s*(?:vs|VS|Vs)\s*(?P<right>[^\s、,。]+)",
  ]
  for pattern in patterns:
    match = re.search(pattern, normalized)
    if not match:
      continue

    left = match.group("left").strip()
    right = match.group("right").strip()
    if not left or not right:
      continue
    if left in _DEICTIC_MARKERS or right in _DEICTIC_MARKERS:
      continue
    return left, right

  return None


def _build_clarification_decision_prompt(message: str, conversation_history: list[dict[str, str]]) -> str:
  lines = [
    "あなたはユーザー依頼の入力不足を判定するアシスタントです。",
    "現在の情報だけで回答を開始できるかを判定してください。",
    "不足しているのが回答に不可欠な情報である場合だけ needs_clarification を true にしてください。",
    "任意の好み、追加の深掘り、雑談の広がりは不足情報に含めません。",
    "比較依頼では比較対象が2つ必要です。計算依頼では式または数値が必要です。行き方依頼では目的地が必要です。",
    "質問は1つだけ、日本語で簡潔にしてください。",
    "出力は JSON のみです。キーは answerable, needs_clarification, question を使ってください。",
    "question には、ユーザーが追加で入力すべき内容を具体例つきで1つだけ書いてください。",
    "判断できない場合は answerable=true, needs_clarification=false, question=\"\" にしてください。",
    "",
    "会話履歴:",
  ]

  for turn in conversation_history[-6:]:
    role = turn.get("role", "user")
    speaker = "ユーザー" if role == "user" else "アシスタント"
    lines.append(f"{speaker}: {turn.get('content', '')}")

  lines.extend([
    "",
    f"ユーザー入力: {message}",
    "JSON:",
  ])
  return "\n".join(lines)


def _normalize_clarification_decision(payload: dict[str, Any] | None) -> dict[str, Any] | None:
  if not isinstance(payload, dict):
    return None

  answerable = bool(payload.get("answerable", False))
  needs_clarification = bool(payload.get("needs_clarification", False))
  question = str(payload.get("question", "") or "").strip()

  if not needs_clarification:
    return {
      "answerable": True,
      "needs_clarification": False,
      "question": "",
    }

  if not question:
    return None

  if answerable and needs_clarification:
    answerable = False

  return {
    "answerable": answerable,
    "needs_clarification": True,
    "question": question,
  }


def _should_probe_general_clarification(message: str) -> bool:
  text = (message or "").strip()
  if not text:
    return False

  if _parse_clarification_followup(text):
    return False

  if any(keyword in text for keyword in _COMPARISON_KEYWORDS):
    return True

  if any(keyword in text for keyword in _DEICTIC_MARKERS) and any(keyword in text for keyword in _GENERIC_REQUEST_KEYWORDS):
    return True

  return False


def _detect_required_clarification(message: str, conversation_history: list[dict[str, str]], intent: str) -> dict[str, Any] | None:
  followup = _parse_clarification_followup(message)
  if followup:
    return None

  if intent == "calculate" and _extract_expression(message) is None:
    return {
      "answerable": False,
      "needs_clarification": True,
      "question": "計算したい式や数値を1つ入力してください（例: 10+20 / 1250×38）。",
    }

  if intent == "navigation" and _needs_navigation_destination(message):
    return {
      "answerable": False,
      "needs_clarification": True,
      "question": "目的地を1つ入力してください（例: 東京駅 / 京都駅）。",
    }

  if any(keyword in message for keyword in _COMPARISON_KEYWORDS):
    comparison_targets = _extract_comparison_targets(message)
    if comparison_targets is not None:
      return None
    if any(marker in message for marker in _DEICTIC_MARKERS):
      return {
        "answerable": False,
        "needs_clarification": True,
        "question": "比較したい2つの対象を入力してください（例: PythonとJava）。",
      }

  if not _should_probe_general_clarification(message):
    return None

  prompt = _build_clarification_decision_prompt(message, conversation_history)
  return _normalize_clarification_decision(ask_local_llm_json(prompt, timeout=max(5.0, REQUEST_TIMEOUT / 2)))


# 外部サービスとの接続とサーバー応答の生成
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


def _build_comparison_answer(left: str, right: str) -> str:
  normalized_left = left.strip().lower()
  normalized_right = right.strip().lower()
  if {normalized_left, normalized_right} & {"iphone", "android"}:
    return (
      f"{left} と {right} の比較です。\n"
      "共通点: どちらもスマートフォンで、通話・SNS・写真撮影・決済・アプリ利用ができます。\n"
      f"主な違い: {left} はAppleの一体設計で操作性とOS更新の安定感が強く、{right} は機種の選択肢が広く価格帯の自由度が高いです。\n"
      f"向いている利用者: {left} は操作の分かりやすさや長期の更新を重視する人、{right} は予算や機種の選択肢を重視する人に向いています。"
    )

  return (
    f"{left} と {right} の比較です。\n"
    f"共通点: どちらも同じ用途の道具として使えます。\n"
    f"主な違い: {left} は設計思想や機能の重みづけが異なり、{right} も同様に別の強みがあります。\n"
    "向いている利用者: 具体的な用途や予算で選ぶと判断しやすいです。"
  )


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
      "location_weather": "/panel/location-weather",
      "evaluation_summary": "/evaluation/summary",
      "evaluation_feedback": "/evaluation/feedback",
      "evaluation_csv": "/evaluation/export.csv",
      "health": "/health",
      "sessions": "/sessions",
      "sessions_clear": "/sessions/clear",
      "meta": "/meta",
      "storage": "/storage",
      "capabilities": "/capabilities",
    },
    "local_llm": {
      "model": config.OLLAMA_MODEL,
      "host": config.OLLAMA_HOST,
      "timeout": REQUEST_TIMEOUT,
      "retries": MAX_RETRIES,
    },
    "routing": {
      "default_mode": _resolve_routing_mode(None),
      "valid_modes": sorted(VALID_ROUTING_MODES),
    },
  }


def _parse_weather_panel_metrics(text: str) -> dict[str, str]:
  source = str(text or "")

  def pick(pattern: str) -> str:
    match = re.search(pattern, source)
    if not match:
      return "—"
    value = str(match.group(1) or "").strip()
    return value or "—"

  weather = pick(r"天気は(.+?)です。")
  current_temp = pick(r"現在気温：([^\n]+)")
  high_temp = pick(r"最高気温：([^\n]+)")
  low_temp = pick(r"最低気温：([^\n]+)")
  precipitation = pick(r"最大降水確率：([^\n]+)")
  humidity = pick(r"(?:現在湿度|予想最大湿度)：([^\n]+)")
  wind_speed = pick(r"(?:現在風速|予想最大風速)：([^\n]+)")
  wind_direction = pick(r"風向：([^\n]+)")
  timezone_name = pick(r"タイムゾーン：([^\n]+)")
  local_time = pick(r"現地時刻：([^\n]+)")
  observed_at = pick(r"取得日時：([^\n]+)")

  return {
    "weather": weather,
    "current_temp": current_temp,
    "high_temp": high_temp,
    "low_temp": low_temp,
    "precipitation": precipitation,
    "humidity": humidity,
    "wind_speed": wind_speed,
    "wind_direction": wind_direction,
    "timezone": timezone_name,
    "local_time": local_time,
    "observed_at": observed_at,
  }


def _to_float_or_none(value: Any) -> float | None:
  try:
    if value in (None, ""):
      return None
    return float(value)
  except Exception:
    return None


def _sanitize_label(value: str) -> str:
  label = re.sub(r"\s+", " ", str(value or "").strip())
  return label[:120]


def _location_weather_cache_key(mode: str, details: dict[str, Any], manual_label: str, reason: str) -> str:
  lat = _to_float_or_none(details.get("latitude"))
  lon = _to_float_or_none(details.get("longitude"))
  if mode == "device" and lat is not None and lon is not None:
    return f"device:{lat:.4f}:{lon:.4f}"
  if mode == "manual":
    base = manual_label or str(details.get("city") or details.get("region") or details.get("country") or "manual")
    return f"manual:{_sanitize_label(base).lower()}"
  reason_key = _sanitize_label(reason).lower() if reason else ""
  return f"ip:{reason_key}"


def _build_location_weather_payload(
  force_refresh: bool = False,
  requested_mode: str = "ip",
  location_details: dict[str, Any] | None = None,
  manual_label: str = "",
  accuracy_m: float | None = None,
  fallback_reason: str = "",
) -> dict[str, Any]:
  mode = str(requested_mode or "ip").strip().lower()
  if mode not in {"device", "ip", "manual"}:
    mode = "ip"

  details = dict(location_details or {}) if isinstance(location_details, dict) else {}

  if mode == "ip" and not details:
    details = get_location_details(use_cache=True) or {}

  if mode == "manual" and not details:
    details = {
      "city": manual_label,
      "region": "",
      "country": "",
      "latitude": None,
      "longitude": None,
      "provider": "manual",
    }

  lat = _to_float_or_none(details.get("latitude"))
  lon = _to_float_or_none(details.get("longitude"))

  if mode == "device" and (lat is None or lon is None):
    ip_details = get_location_details(use_cache=True)
    if isinstance(ip_details, dict):
      details = dict(ip_details)
      mode = "ip"
    else:
      mode = "ip"

  cache_key = _location_weather_cache_key(mode, details, manual_label, fallback_reason)
  now = time.time()
  with _SESSION_LOCK:
    cached = _LOCATION_WEATHER_CACHE.get("payload")
    expires_at = float(_LOCATION_WEATHER_CACHE.get("expires_at") or 0.0)
    cached_key = str(_LOCATION_WEATHER_CACHE.get("cache_key") or "")
    if not force_refresh and isinstance(cached, dict) and expires_at > now and cached_key == cache_key:
      payload = dict(cached)
      payload["cache_hit"] = True
      return payload

  if not isinstance(details, dict) or not details:
    payload = {
      "ok": False,
      "status": "location_failed",
      "message": "現在地を取得できませんでした。IP推定も失敗しました。チャットはそのまま利用できます。",
      "location": {
        "label": "現在地: 取得失敗",
        "city": "—",
        "region": "—",
        "country": "—",
        "latitude": None,
        "longitude": None,
        "provider": "—",
        "mode": "failed",
        "accuracy_m": None,
      },
      "weather": {
        "weather": "—",
        "current_temp": "—",
        "high_temp": "—",
        "low_temp": "—",
        "precipitation": "—",
      },
      "cache_hit": False,
      "updated_at": int(now),
      "next_refresh_sec": _LOCATION_WEATHER_CACHE_TTL_SECONDS,
      "cache_key": cache_key,
    }
    with _SESSION_LOCK:
      _LOCATION_WEATHER_CACHE["payload"] = payload
      _LOCATION_WEATHER_CACHE["cache_key"] = cache_key
      _LOCATION_WEATHER_CACHE["expires_at"] = now + min(120, _LOCATION_WEATHER_CACHE_TTL_SECONDS)
    return payload

  city = str(details.get("city") or "").strip()
  region = str(details.get("region") or "").strip()
  country = str(details.get("country") or "").strip()
  lat = _to_float_or_none(details.get("latitude"))
  lon = _to_float_or_none(details.get("longitude"))
  provider = str(details.get("provider") or "unknown")

  label_parts = [part for part in [city, region, country] if part and part != "—"]
  location_label = " / ".join(label_parts) if label_parts else _sanitize_label(manual_label) or "不明"

  if mode == "manual":
    weather_query = f"{location_label}の天気"
    weather_text = get_weather(weather_query)
    message = "手動指定の地域で天気を表示しています。"
  else:
    weather_query = f"{location_label}の天気"
    weather_text = get_weather(weather_query, current_location_details={
      "city": city,
      "region": region,
      "country": country,
      "latitude": lat,
      "longitude": lon,
    })
    if mode == "device":
      message = "端末位置で天気を表示しています。"
    else:
      fallback_suffix = f"（理由: {fallback_reason}）" if fallback_reason else ""
      message = f"IP推定で天気を表示しています。{fallback_suffix}".strip()

  metrics = _parse_weather_panel_metrics(weather_text)

  mode_label = {
    "device": "端末位置",
    "ip": "IP推定",
    "manual": "手動",
  }.get(mode, "IP推定")

  provider_label = provider
  if mode == "manual":
    provider_label = "manual"

  payload = {
    "ok": True,
    "status": "ready",
    "message": message,
    "location": {
      "label": f"{mode_label}: {location_label}",
      "city": city or "—",
      "region": region or "—",
      "country": country or "—",
      "latitude": lat,
      "longitude": lon,
      "provider": provider_label,
      "mode": mode,
      "accuracy_m": _to_float_or_none(accuracy_m),
    },
    "weather": metrics,
    "raw_weather_text": weather_text,
    "cache_hit": False,
    "updated_at": int(now),
    "next_refresh_sec": _LOCATION_WEATHER_CACHE_TTL_SECONDS,
    "cache_key": cache_key,
  }

  with _SESSION_LOCK:
    _LOCATION_WEATHER_CACHE["payload"] = payload
    _LOCATION_WEATHER_CACHE["cache_key"] = cache_key
    _LOCATION_WEATHER_CACHE["expires_at"] = now + _LOCATION_WEATHER_CACHE_TTL_SECONDS

  return payload


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


def _route_label(route: str) -> str:
  mapping = {
    "local_function": "ローカル処理",
    "local_search": "ローカル処理",
    "local_llm": "ローカルLLM",
    "cloud_fallback": "クラウドフォールバック",
    "error": "エラー",
  }
  return mapping.get(route, route)


def _resolve_routing_mode(mode_override: str | None = None) -> str:
  mode = (mode_override or ROUTING_MODE_DEFAULT or "DYNAMIC_ROUTING").strip().upper()
  if mode not in VALID_ROUTING_MODES:
    return "DYNAMIC_ROUTING"
  return mode


def _approval_token(command_text: str, prefix: str) -> str:
  text = (command_text or "").strip()
  if not text.startswith(prefix):
    return ""
  parts = text.split(":", 1)
  if len(parts) != 2:
    return ""
  return parts[1].strip()


def _has_pending_api_approval_for_session(session_id: str) -> bool:
  with _SESSION_LOCK:
    return any((item.get("session_id") or "") == session_id for item in _PENDING_API_APPROVAL.values())


def _clear_pending_api_approval_for_session(session_id: str) -> None:
  with _SESSION_LOCK:
    stale_tokens = [
      token
      for token, item in _PENDING_API_APPROVAL.items()
      if (item.get("session_id") or "") == session_id
    ]
    for token in stale_tokens:
      _PENDING_API_APPROVAL.pop(token, None)


def _prefer_local_llm_over_search(text: str) -> bool:
  normalized = (text or "").strip()
  if not normalized:
    return False

  if re.search(r"^(こんにちは|こんばんは|おはよう|やあ|もしもし|はじめまして)", normalized):
    return True
  if re.search(r"(翻訳して|訳して|英訳|和訳)", normalized):
    return True
  if re.search(r"(さっき|直前|前の|この前).*(話|会話|質問|回答)|前述", normalized):
    return True
  if re.search(r"(ローカルLLM|ローカルモデル).*(使って|で|優先)", normalized):
    return True
  return False


def _set_pending_api_approval(token: str, payload: dict[str, str]) -> None:
  with _SESSION_LOCK:
    _PENDING_API_APPROVAL[token] = payload


def _pop_pending_api_approval(token: str) -> dict[str, str] | None:
  with _SESSION_LOCK:
    return _PENDING_API_APPROVAL.pop(token, None)


def _build_google_then_api_prompt(message: str, search_result: str) -> str:
  lines = [
    "ローカル処理だけでは回答の確度が不足した可能性があります。",
    "先にGoogle検索の要点を示します。必要であればAPIを使った深掘り回答を行います。",
    "",
    "[Google検索結果]",
    (search_result or "検索結果を取得できませんでした。"),
    "",
    "このままローカル検索結果で十分なら『今回はローカル結果でOK』を選択してください。",
    "より詳細な回答が必要なら『APIを使って詳細回答を生成』を選択してください。",
  ]
  return "\n".join(lines)


def _build_search_failure_ui() -> dict[str, Any]:
  return {
    "type": "search_failure_actions",
    "title": "検索結果が取得できませんでした",
    "description": "検索語を変更して再検索するか、ローカルLLMまたはクラウドAPIで回答できます。",
    "interaction": "choice",
    "options": [
      {
        "label": "検索語を変更して再検索",
        "message": "検索語を変更して再検索します。",
        "description": "検索語を短くしたり、対象語を明確にします。",
      },
      {
        "label": "ローカルLLMで回答",
        "message": "ローカルLLMで回答してください。",
        "description": "検索せずにローカル会話で回答します。",
      },
      {
        "label": "クラウドAPIで詳細回答",
        "message": "クラウドAPIで詳細回答を生成してください。",
        "description": "必要に応じてクラウドへ切り替えます。",
      },
    ],
  }


def _build_search_success_ui() -> dict[str, Any]:
  return {
    "type": "search_result_confirmation",
    "title": "検索結果を確認しました",
    "description": "検索結果で十分ならそのまま続行し、必要なら別の処理へ切り替えられます。",
    "interaction": "choice",
    "options": [
      {
        "label": "このまま検索結果で十分",
        "message": "このまま検索結果で十分です。",
        "description": "検索結果だけで回答を終了します。",
      },
      {
        "label": "ローカルLLMで回答",
        "message": "ローカルLLMで回答してください。",
        "description": "検索結果を使わずにローカル会話へ切り替えます。",
      },
      {
        "label": "クラウドAPIで詳細回答",
        "message": "クラウドAPIで詳細回答を生成してください。",
        "description": "必要に応じて詳細な補足を生成します。",
      },
    ],
  }


def _format_structured_search_response(payload: dict[str, Any]) -> str:
  lines = []
  detected_language = str(payload.get("detected_language") or "unknown")
  language_label = {
    "en": "英語",
    "zh": "中国語",
    "ko": "韓国語",
    "ja": "日本語",
  }.get(detected_language, "不明")
  original_query = str(payload.get("original_query") or "")
  translated_query = payload.get("translated_query")
  actual_search_query = str(payload.get("actual_search_query") or "")
  summary_ja = str(payload.get("summary_ja") or "")
  results = payload.get("results") or []

  lines.append(f"入力言語：{language_label}")
  lines.append("元の入力：")
  lines.append(original_query)
  if translated_query:
    lines.append("")
    lines.append("日本語訳：")
    lines.append(str(translated_query))
  if actual_search_query:
    lines.append("")
    lines.append("実際の検索語：")
    lines.append(actual_search_query)
  if summary_ja:
    lines.append("")
    lines.append("検索結果の要約：")
    lines.append(summary_ja)
  if results:
    lines.append("")
    lines.append("参照リンク：")
    for item in results[:5]:
      url = str(item.get("url") or "").strip()
      if url:
        lines.append(url)
  lines.append("")
  lines.append(f"処理経路：{payload.get('route')}")
  return "\n".join(lines).strip()


def _build_missing_info_ui(*, title: str, placeholder: str, field: str, question: str) -> dict[str, Any]:
  return {
    "type": "prompt_input",
    "title": title,
    "description": "不足している情報を入力すると、同じ質問を再演算します。",
    "interaction": "recompute",
    "placeholder": placeholder,
    "field": field,
    "button_label": "再演算",
    "template": question,
  }


def _build_clarification_ui(original_message: str, response_text: str) -> dict[str, Any] | None:
  """Convert the LLM clarification contract into a recompute input panel."""
  response = (response_text or "").strip()
  match = re.match(r"^確認質問[：:]\s*(.+)$", response, re.DOTALL)
  if not match:
    return None

  question = match.group(1).strip()
  if not question:
    return None

  original = (original_message or "").strip()
  template = f"元の依頼：{original}\n追加情報：{{value}}\n上記の追加情報を使って元の依頼を再計算してください。"
  return _build_missing_info_ui(
    title=question,
    placeholder="不足している情報を入力してください",
    field="clarification_answer",
    question=template,
  )


def _attach_evaluation(
  *,
  base_payload: dict[str, Any],
  request_id: str,
  experiment_mode: str,
  test_case_id: str,
  message: str,
  response_text: str,
  route: str,
  response_time_sec: float,
  local_time_sec: float,
  cloud_time_sec: float,
  api_called: bool,
  success: bool,
) -> dict[str, Any]:
  record = evaluation_metrics.build_record(
    request_id=request_id,
    experiment_mode=experiment_mode,
    test_case_id=test_case_id,
    entry_point="local_ai_server.chat",
    input_text=message,
    response_text=response_text,
    route=_route_label(route),
    response_time_sec=response_time_sec,
    local_time_sec=local_time_sec,
    cloud_time_sec=cloud_time_sec,
    api_called=api_called,
    success=success,
  )
  evaluation_metrics.save(record)
  summary = evaluation_metrics.get_summary()
  base_payload["evaluation"] = build_user_facing_evaluation(record, summary)
  return base_payload


# メッセージを受け取り、最終レスポンスとUI情報を組み立てる本体処理
@traced_request
def _build_chat_payload(
  message: str,
  session_id: str,
  *,
  current_location: str = "",
  experiment_mode: str | None = None,
  test_case_id: str = "",
  tool_request: dict | None = None,
) -> dict[str, Any]:
  message = (message or "").strip()
  current_location = (current_location or "").strip()
  if not message:
    return {"ok": False, "error": "message is required", "retryable": False}

  clarification_followup = _parse_clarification_followup(message)
  effective_message = clarification_followup[0] if clarification_followup else message
  recompute_message = (
    f"{clarification_followup[0]}\n{clarification_followup[1]}"
    if clarification_followup
    else effective_message
  )
  llm_message = _build_clarification_followup_prompt(*clarification_followup) if clarification_followup else message

  approve_token = _approval_token(message, API_APPROVE_PREFIX)
  reject_token = _approval_token(message, API_REJECT_PREFIX)

  request_id = uuid4().hex
  experiment_mode = _resolve_routing_mode(experiment_mode)
  test_case_id = (test_case_id or "").strip()
  started = time.perf_counter()
  local_time_sec = 0.0
  cloud_time_sec = 0.0
  api_called = False

  def finalize(
    *,
    ok: bool,
    route: str,
    response: str | None = None,
    error: str | None = None,
    attempt: int = 1,
    fallback_used: bool = False,
    extra: dict[str, Any] | None = None,
  ) -> dict[str, Any]:
    response_text = (response or "").strip() if ok else (error or "").strip()
    payload: dict[str, Any] = {
      "ok": ok,
      "attempt": attempt,
      "fallback_used": fallback_used,
      "session_id": session_id,
      "experiment_mode": experiment_mode,
      "test_case_id": test_case_id,
      "route": route,
    }
    if ok:
      payload["response"] = response_text
    else:
      payload["error"] = response_text or "error"
    if extra:
      payload.update(extra)

    mark_text_ready()
    elapsed = time.perf_counter() - started
    return _attach_evaluation(
      base_payload=payload,
      request_id=request_id,
      experiment_mode=experiment_mode,
      test_case_id=test_case_id,
      message=message,
      response_text=response_text,
      route=route,
      response_time_sec=elapsed,
      local_time_sec=local_time_sec,
      cloud_time_sec=cloud_time_sec,
      api_called=api_called,
      success=ok,
    )

  requested_tool = tool_request or run_stage('intent', _parse_dashboard_request, effective_message)
  if requested_tool:
    try:
      tool_started = time.perf_counter()
      ok, response = _dispatch_dashboard_tool(requested_tool)
      local_time_sec += time.perf_counter() - tool_started
      _append_turn(session_id, 'user', message)
      _append_turn(session_id, 'assistant', response)
      return finalize(ok=ok, route='local_function' if ok else 'error', response=response, error=None if ok else response)
    except Exception as error:
      return finalize(ok=False, route='error', error=f'ツールを実行できませんでした: {error}')

  if approve_token:
    pending = _pop_pending_api_approval(approve_token)
    if not pending or pending.get("session_id") != session_id:
      return finalize(ok=False, route="error", error="承認待ちのAPI呼び出しが見つかりませんでした。")

    cloud_started = time.perf_counter()
    try:
      cloud_response = ask_cloud_ai(str(pending.get("prompt", "")))
      cloud_time_sec += time.perf_counter() - cloud_started
      api_called = True
      _append_turn(session_id, "assistant", cloud_response)
      return finalize(ok=True, route="cloud_fallback", response=cloud_response)
    except Exception as error:
      cloud_time_sec += time.perf_counter() - cloud_started
      api_called = True
      return finalize(ok=False, route="error", error=f"（クラウド呼び出し失敗: {error}）")

  if message.startswith(API_APPROVE_PREFIX) and not approve_token:
    return finalize(ok=False, route="error", error="承認コマンド形式が不正です。承認ボタンから送信してください。")

  if reject_token:
    pending = _pop_pending_api_approval(reject_token)
    if not pending or pending.get("session_id") != session_id:
      return finalize(ok=False, route="error", error="承認待ちのAPI呼び出しが見つかりませんでした。")

    response_text = "承知しました。今回はクラウドAPIを使わず、Google検索結果のみで終了します。"
    _clear_pending_api_approval_for_session(session_id)
    _append_turn(session_id, "assistant", response_text)
    return finalize(ok=True, route="local_search", response=response_text)

  if "今回はローカル結果でOK" in message and _has_pending_api_approval_for_session(session_id):
    _clear_pending_api_approval_for_session(session_id)
    response_text = "承知しました。今回はクラウドAPIを使わず、Google検索結果のみで終了します。"
    _append_turn(session_id, "assistant", response_text)
    return finalize(ok=True, route="local_search", response=response_text)

  # 自動メモリ更新: ユーザー発話から重要情報のみ保存し、削除指示も反映
  update_profile_from_text(effective_message)

  explicit_note_payload = _tool_call('document', handle_explicit_note_command_with_meta, effective_message)

  _append_turn(session_id, "user", message)
  history = _snapshot_session(session_id)
  profile_context = build_profile_context()

  if _looks_like_capability_question(effective_message):
    local_started = time.perf_counter()
    capability_payload = _build_capability_payload()
    capability_response = str(capability_payload.get("response") or "")
    local_time_sec += time.perf_counter() - local_started
    _append_turn(session_id, "assistant", capability_response)
    return finalize(
      ok=True,
      route="local_function",
      response=capability_response,
      extra={"ui": capability_payload["ui"]},
    )

  if _looks_like_greeting(effective_message):
    response_text = "こんにちは。ローカルで応答しています。"
    _append_turn(session_id, "assistant", response_text)
    return finalize(ok=True, route="local_function", response=response_text)

  if _looks_like_translation_history_question(effective_message):
    recent_english = _extract_recent_translation_english(history)
    if recent_english:
      response_text = f"直前に翻訳を頼まれた英文は次の内容です。\n{recent_english}"
    else:
      response_text = "このセッション内で翻訳対象の英文が見つかりませんでした。"
    _append_turn(session_id, "assistant", response_text)
    return finalize(ok=True, route="local_function", response=response_text)

  if explicit_note_payload:
    local_started = time.perf_counter()
    explicit_note_response = str(explicit_note_payload.get("response") or "")
    local_time_sec += time.perf_counter() - local_started
    _append_turn(session_id, "assistant", explicit_note_response)
    response_payload: dict[str, Any] = {}
    if isinstance(explicit_note_payload.get("ui"), dict):
      response_payload["ui"] = explicit_note_payload["ui"]
    return finalize(ok=True, route="local_function", response=explicit_note_response, extra=response_payload)

  intent = run_stage('intent', classify_intent, effective_message)
  prefer_local_llm = _prefer_local_llm_over_search(effective_message)
  clarification_decision = None
  if not clarification_followup and experiment_mode != "FIXED_ROUTING":
    clarification_decision = run_stage('intent', _detect_required_clarification, effective_message, history, intent)

  if clarification_decision and clarification_decision.get("needs_clarification"):
    question = str(clarification_decision.get("question") or "").strip()
    response_text = f"確認質問：{question}"
    _append_turn(session_id, "assistant", response_text)
    clarification_ui = _build_general_clarification_ui(message, question)
    clarification_route = "local_function" if intent in {"calculate", "navigation"} else "local_llm"
    return finalize(
      ok=True,
      route=clarification_route,
      response=response_text,
      extra={"ui": clarification_ui},
    )

  if intent == "relative_weekday" or _looks_like_relative_weekday_question(message):
    local_started = time.perf_counter()
    response = run_stage('tool', get_weekday_from_text, effective_message)
    local_time_sec += time.perf_counter() - local_started
    _append_turn(session_id, "assistant", response)
    return finalize(ok=True, route="local_function", response=response)

  if intent == "weekday":
    local_started = time.perf_counter()
    response = run_stage('tool', get_weekday)
    local_time_sec += time.perf_counter() - local_started
    _append_turn(session_id, "assistant", response)
    return finalize(ok=True, route="local_function", response=response)

  if intent == "time":
    local_started = time.perf_counter()
    response = run_stage('tool', get_time)
    local_time_sec += time.perf_counter() - local_started
    _append_turn(session_id, "assistant", response)
    return finalize(ok=True, route="local_function", response=response)

  if intent == "calculate" or _looks_like_calculation(effective_message):
    calc_input = clarification_followup[1] if clarification_followup else recompute_message
    local_started = time.perf_counter()
    response = run_stage('tool', calculate, calc_input)
    local_time_sec += time.perf_counter() - local_started
    _append_turn(session_id, "assistant", response)
    return finalize(ok=True, route="local_function", response=response)

  if intent == "navigation":
    navigation_input = recompute_message
    if clarification_followup:
      navigation_input = f"ここから{clarification_followup[1]}までの行き方を教えて"
    location_details = _get_session_location_details(session_id)
    if current_location:
      navigation_input = navigation_input.replace("ここから", f"{current_location}から")
    local_started = time.perf_counter()
    response = _tool_call('map', resolve_navigation,
      navigation_input,
      current_location=current_location,
      current_location_details=location_details,
    )
    local_time_sec += time.perf_counter() - local_started
    _append_turn(session_id, "assistant", response)
    return finalize(ok=True, route="local_function", response=response)

  if intent == "weather":
    location_details = _get_session_location_details(session_id)
    weather_query = recompute_message
    if current_location and not parse_weather_query(recompute_message).get("location"):
      weather_query = current_location + "の天気"
    local_started = time.perf_counter()
    response = _tool_call('weather', get_weather, weather_query, current_location_details=location_details)
    local_time_sec += time.perf_counter() - local_started
    _append_turn(session_id, "assistant", response)
    weather_ui = _build_missing_info_ui(
      title="地域や日付を指定して再検索",
      placeholder="例: 大阪の明日 / 東京の3日後 / 札幌の天気",
      field="weather_query",
      question="{value}",
    )
    return finalize(
      ok=True,
      route="local_function",
      response=response,
      extra={"ui": weather_ui},
    )

  if intent == "search" and not prefer_local_llm:
    local_started = time.perf_counter()
    search_payload = _tool_call('search', search_google_web_structured, recompute_message)
    local_time_sec += time.perf_counter() - local_started
    fallback_search_result = run_stage('tool', search_google_web, recompute_message, tool_name='search_fallback') if not search_payload.get('ok') or search_payload.get('search_engine') == 'Demo' else ''
    if search_payload.get("ok") and str(search_payload.get("search_engine") or "") == "Demo" and fallback_search_result and fallback_search_result not in {
      "Google検索結果を取得できませんでした。",
      "入力された文章を日本語へ翻訳できませんでした。日本語で入力し直すか、翻訳を再試行してください。",
    }:
      search_payload = {
        **search_payload,
        "summary_ja": fallback_search_result,
        "search_engine": "Google",
      }
    if search_payload.get("ok"):
      route_label = "local_search"
      response_text = _format_structured_search_response(search_payload)
      _append_turn(session_id, "assistant", response_text)
      print(f"route={route_label}")
      return finalize(ok=True, route=route_label, response=response_text, extra={"ui": _build_search_success_ui()})

    if fallback_search_result and fallback_search_result not in {
      "Google検索結果を取得できませんでした。",
      "入力された文章を日本語へ翻訳できませんでした。日本語で入力し直すか、翻訳を再試行してください。",
    }:
      route_label = "local_search"
      add_card("search", {"text": fallback_search_result, "query": recompute_message})
      _append_turn(session_id, "assistant", fallback_search_result)
      print(f"route={route_label}")
      return finalize(ok=True, route=route_label, response=fallback_search_result, extra={"ui": _build_search_success_ui()})

    error_type = str(search_payload.get("error_type") or "search_fetch_failed")
    search_failure = "Google検索結果を取得できませんでした。"
    _append_turn(session_id, "assistant", search_failure)
    print("route=search_failed")
    return finalize(ok=True, route="search_failed", response=search_failure, extra={"ui": _build_search_failure_ui(), "error_type": error_type})

  if _looks_like_fact_question(effective_message) and not prefer_local_llm:
    local_started = time.perf_counter()
    search_payload = _tool_call('search', search_google_web_structured, recompute_message)
    local_time_sec += time.perf_counter() - local_started
    fallback_search_result = run_stage('tool', search_google_web, recompute_message, tool_name='search_fallback') if not search_payload.get('ok') or search_payload.get('search_engine') == 'Demo' else ''
    if search_payload.get("ok") and str(search_payload.get("search_engine") or "") == "Demo" and fallback_search_result and fallback_search_result not in {
      "Google検索結果を取得できませんでした。",
      "入力された文章を日本語へ翻訳できませんでした。日本語で入力し直すか、翻訳を再試行してください。",
    }:
      search_payload = {
        **search_payload,
        "summary_ja": fallback_search_result,
        "search_engine": "Google",
      }
    if search_payload.get("ok"):
      route_label = "local_search"
      response_text = _format_structured_search_response(search_payload)
      _append_turn(session_id, "assistant", response_text)
      print(f"route={route_label}")
      return finalize(ok=True, route=route_label, response=response_text, extra={"ui": _build_search_success_ui()})

    if fallback_search_result and fallback_search_result not in {
      "Google検索結果を取得できませんでした。",
      "入力された文章を日本語へ翻訳できませんでした。日本語で入力し直すか、翻訳を再試行してください。",
    }:
      route_label = "local_search"
      add_card("search", {"text": fallback_search_result, "query": recompute_message})
      _append_turn(session_id, "assistant", fallback_search_result)
      print(f"route={route_label}")
      return finalize(ok=True, route=route_label, response=fallback_search_result, extra={"ui": _build_search_success_ui()})

    error_type = str(search_payload.get("error_type") or "search_fetch_failed")
    search_failure = "Google検索結果を取得できませんでした。"
    _append_turn(session_id, "assistant", search_failure)
    print("route=search_failed")
    return finalize(ok=True, route="search_failed", response=search_failure, extra={"ui": _build_search_failure_ui(), "error_type": error_type})

  history_for_prompt = [] if clarification_followup else history
  prompt = build_local_prompt(
    llm_message,
    conversation_history=history_for_prompt,
    user_profile_context=profile_context,
  )

  if experiment_mode == "FIXED_ROUTING":
    cloud_started = time.perf_counter()
    try:
      cloud_response = ask_cloud_ai(prompt)
      cloud_time_sec += time.perf_counter() - cloud_started
      api_called = True
      _append_turn(session_id, "assistant", cloud_response)
      clarification_ui = None if clarification_followup else _build_clarification_ui(effective_message, cloud_response)
      return finalize(
        ok=True,
        route="cloud_fallback",
        response=cloud_response,
        extra={"ui": clarification_ui} if clarification_ui else None,
      )
    except Exception as error:
      cloud_time_sec += time.perf_counter() - cloud_started
      api_called = True
      return finalize(ok=False, route="error", error=f"（FIXED_ROUTINGのクラウド呼び出し失敗: {error}）")

  local_started = time.perf_counter()
  result = _generate_llm_response(prompt)
  local_time_sec += time.perf_counter() - local_started

  if result.get("ok"):
    response_text = str(result.get("response") or "")
    clarification_ui = None if clarification_followup else _build_clarification_ui(effective_message, response_text)
    _append_turn(session_id, "assistant", response_text)
    return finalize(
      ok=True,
      route="local_llm",
      response=response_text,
      attempt=int(result.get("attempt", 1) or 1),
      fallback_used=bool(result.get("fallback_used", False)),
      extra={"ui": clarification_ui} if clarification_ui else None,
    )

  if experiment_mode == "LOCAL_ONLY":
    return finalize(
      ok=False,
      route="error",
      error="（LOCAL_ONLYモードのためクラウドフォールバックは無効です）",
      attempt=int(result.get("attempt", 1) or 1),
      fallback_used=False,
    )

  if clarification_followup:
    fallback_response = _build_comparison_answer(clarification_followup[0], clarification_followup[1])
    _append_turn(session_id, "assistant", fallback_response)
    return finalize(ok=True, route="local_llm", response=fallback_response)

  if _prefer_local_llm_over_search(effective_message):
    return finalize(
      ok=False,
      route="error",
      error=str(result.get("error") or "（ローカルLLM応答は不十分でした）"),
      attempt=int(result.get("attempt", 1) or 1),
      fallback_used=bool(result.get("fallback_used", False)),
    )

  # DYNAMIC_ROUTING: do not call cloud immediately.
  # First show Google evidence and ask user whether cloud API usage is allowed.
  local_started = time.perf_counter()
  search_payload = _tool_call('search', search_google_web_structured, message)
  local_time_sec += time.perf_counter() - local_started
  fallback_search_result = run_stage('tool', search_google_web, message, tool_name='search_fallback') if not search_payload.get('ok') else ''
  if search_payload.get("ok") or (fallback_search_result and fallback_search_result not in {"Google検索結果を取得できませんでした。", "入力された文章を日本語へ翻訳できませんでした。日本語で入力し直すか、翻訳を再試行してください。"}):
    approval_token = uuid4().hex
    reject_token = uuid4().hex
    _set_pending_api_approval(
      approval_token,
      {
        "session_id": session_id,
        "prompt": prompt,
        "message": message,
      },
    )
    _set_pending_api_approval(
      reject_token,
      {
        "session_id": session_id,
        "prompt": prompt,
        "message": message,
      },
    )

    response_text = _format_structured_search_response(search_payload) if search_payload.get("ok") else fallback_search_result
    _append_turn(session_id, "assistant", response_text)
    return finalize(
      ok=True,
      route="local_search",
      response=response_text,
      fallback_used=True,
      extra={
        "ui": {
          "type": "cloud_api_consent",
          "title": "クラウドAPIを使って詳細回答を生成しますか？",
          "description": "料金が発生する可能性があります。実行する場合のみ選択してください。",
          "interaction": "send",
          "options": [
            {
              "label": "APIを使って詳細回答を生成",
              "message": f"{API_APPROVE_PREFIX}:{approval_token}",
              "description": "クラウドAPIで詳細回答を生成します。",
            },
            {
              "label": "今回はローカル結果でOK",
              "message": f"{API_REJECT_PREFIX}:{reject_token}",
              "description": "Google検索結果だけで終了します。",
            },
          ],
        },
      },
    )

  response_text = "Google検索結果を取得できませんでした。"
  _append_turn(session_id, "assistant", response_text)
  return finalize(
    ok=True,
    route="search_failed",
    response=response_text,
    fallback_used=False,
    extra={"ui": _build_search_failure_ui(), "error_type": search_payload.get("error_type") or "search_fetch_failed"},
  )


# SSEで逐次応答を返すストリーミング処理
def _stream_chat_payload(
  message: str,
  session_id: str,
  *,
  current_location: str = "",
  experiment_mode: str | None = None,
  test_case_id: str = "",
):
  message = (message or "").strip()
  current_location = (current_location or "").strip()
  if not message:
    yield {"event": "error", "data": {"error": "message is required"}}
    return

  request_id = uuid4().hex
  resolved_mode = _resolve_routing_mode(experiment_mode)
  test_case_id = (test_case_id or "").strip()
  started = time.perf_counter()
  local_time_sec = 0.0
  cloud_time_sec = 0.0
  api_called = False

  def finalize_payload(route: str, response_text: str, success: bool) -> dict[str, Any]:
    record = evaluation_metrics.build_record(
      request_id=request_id,
      experiment_mode=resolved_mode,
      test_case_id=test_case_id,
      entry_point="local_ai_server.chat_stream",
      input_text=message,
      response_text=response_text,
      route=_route_label(route),
      response_time_sec=time.perf_counter() - started,
      local_time_sec=local_time_sec,
      cloud_time_sec=cloud_time_sec,
      api_called=api_called,
      success=success,
    )
    evaluation_metrics.save(record)
    return build_user_facing_evaluation(record, evaluation_metrics.get_summary())

  if resolved_mode in {"LOCAL_ONLY", "FIXED_ROUTING"}:
    payload = _build_chat_payload(
      message,
      session_id,
      current_location=current_location,
      experiment_mode=resolved_mode,
      test_case_id=test_case_id,
    )
    if payload.get("ok"):
      yield {"event": "done", "data": payload}
    else:
      yield {"event": "error", "data": payload}
    return

  if (
    message.startswith(API_APPROVE_PREFIX)
    or message.startswith(API_REJECT_PREFIX)
    or ("今回はローカル結果でOK" in message and _has_pending_api_approval_for_session(session_id))
  ):
    payload = _build_chat_payload(
      message,
      session_id,
      current_location=current_location,
      experiment_mode=resolved_mode,
      test_case_id=test_case_id,
    )
    if payload.get("ok"):
      yield {"event": "done", "data": payload}
    else:
      yield {"event": "error", "data": payload}
    return

  clarification_followup = _parse_clarification_followup(message)
  effective_message = clarification_followup[0] if clarification_followup else message

  update_profile_from_text(effective_message)
  explicit_note_payload = handle_explicit_note_command_with_meta(effective_message)

  # /chat/stream では通常経路がLLMへ進みやすいため、DOC ID指定の表示要求は先にローカル処理する。
  if not explicit_note_payload:
    doc_match = re.search(r"\b(DOC\d{6})\b", effective_message, flags=re.IGNORECASE)
    wants_show = bool(re.search(r"(出して|見せて|表示して|表示|見たい)", effective_message))
    if doc_match and wants_show:
      local_started = time.perf_counter()
      doc_id = (doc_match.group(1) or "").upper()
      document = get_document_item(doc_id=doc_id)
      local_time_sec += time.perf_counter() - local_started

      if document:
        title = str(document.get("title") or "無題").strip() or "無題"
        content = str(document.get("content") or "").strip() or "(本文なし)"
        response_text = f"文書タイトル: {title}\n文書ID: {doc_id}\n本文:\n{content}"
      else:
        response_text = f"指定された文書が見つかりませんでした。文書ID: {doc_id}"

      _append_turn(session_id, "assistant", response_text)
      yield {
        "event": "done",
        "data": {
          "response": response_text,
          "session_id": session_id,
          "experiment_mode": resolved_mode,
          "test_case_id": test_case_id,
          "evaluation": finalize_payload("local_function", response_text, True),
        },
      }
      return

  _append_turn(session_id, "user", message)
  history = _snapshot_session(session_id)
  profile_context = build_profile_context()

  if _looks_like_capability_question(message):
    local_started = time.perf_counter()
    capability_payload = _build_capability_payload()
    local_time_sec += time.perf_counter() - local_started
    capability_response = str(capability_payload.get("response") or "")
    _append_turn(session_id, "assistant", capability_response)
    evaluation = finalize_payload("local_function", capability_response, True)
    yield {
      "event": "done",
      "data": {
        "response": capability_response,
        "session_id": session_id,
        "experiment_mode": resolved_mode,
        "test_case_id": test_case_id,
        "ui": capability_payload["ui"],
        "evaluation": evaluation,
      },
    }
    return

  if _looks_like_greeting(message):
    response_text = "こんにちは。ローカルで応答しています。"
    _append_turn(session_id, "assistant", response_text)
    yield {
      "event": "done",
      "data": {
        "response": response_text,
        "session_id": session_id,
        "experiment_mode": resolved_mode,
        "test_case_id": test_case_id,
        "evaluation": finalize_payload("local_function", response_text, True),
      },
    }
    return

  if _looks_like_translation_history_question(message):
    recent_english = _extract_recent_translation_english(history)
    if recent_english:
      response_text = f"直前に翻訳を頼まれた英文は次の内容です。\n{recent_english}"
    else:
      response_text = "このセッション内で翻訳対象の英文が見つかりませんでした。"
    _append_turn(session_id, "assistant", response_text)
    yield {
      "event": "done",
      "data": {
        "response": response_text,
        "session_id": session_id,
        "experiment_mode": resolved_mode,
        "test_case_id": test_case_id,
        "evaluation": finalize_payload("local_function", response_text, True),
      },
    }
    return

  if explicit_note_payload:
    local_started = time.perf_counter()
    explicit_note_response = str(explicit_note_payload.get("response") or "")
    local_time_sec += time.perf_counter() - local_started
    _append_turn(session_id, "assistant", explicit_note_response)
    done_payload = {
      "response": explicit_note_response,
      "session_id": session_id,
      "experiment_mode": resolved_mode,
      "test_case_id": test_case_id,
      "evaluation": finalize_payload("local_function", explicit_note_response, True),
    }
    if isinstance(explicit_note_payload.get("ui"), dict):
      done_payload["ui"] = explicit_note_payload["ui"]
    yield {"event": "done", "data": done_payload}
    return

  prompt = build_local_prompt(message, conversation_history=history, user_profile_context=profile_context)

  chunks: list[str] = []
  try:
    local_started = time.perf_counter()
    for chunk in stream_local_llm(prompt, temperature=0.7, timeout=REQUEST_TIMEOUT):
      if chunk:
        chunks.append(chunk)
        yield {"event": "delta", "data": {"delta": chunk, "session_id": session_id}}
    local_time_sec += time.perf_counter() - local_started

    response_text = "".join(chunks).strip()
    if not _is_viable_response(response_text):
      evaluation = finalize_payload("error", "（ローカルLLM応答は不十分でした）", False)
      yield {
        "event": "error",
        "data": {
          "error": "（ローカルLLM応答は不十分でした）",
          "session_id": session_id,
          "evaluation": evaluation,
        },
      }
      return

    _append_turn(session_id, "assistant", response_text)
    yield {
      "event": "done",
      "data": {
        "response": response_text,
        "session_id": session_id,
        "experiment_mode": resolved_mode,
        "test_case_id": test_case_id,
        "evaluation": finalize_payload("local_llm", response_text, True),
      },
    }

  except HTTPError as error:
    message_text = f"（Ollama HTTPエラー: {error.code}）"
    yield {
      "event": "error",
      "data": {
        "error": message_text,
        "session_id": session_id,
        "evaluation": finalize_payload("error", message_text, False),
      },
    }
  except URLError as error:
    message_text = f"（Ollama接続失敗: {error.reason}）"
    yield {
      "event": "error",
      "data": {
        "error": message_text,
        "session_id": session_id,
        "evaluation": finalize_payload("error", message_text, False),
      },
    }
  except TimeoutError as error:
    message_text = f"（Ollamaタイムアウト: {error}）"
    yield {
      "event": "error",
      "data": {
        "error": message_text,
        "session_id": session_id,
        "evaluation": finalize_payload("error", message_text, False),
      },
    }
  except Exception as error:
    message_text = f"（ローカルLLMエラー: {error}）"
    yield {
      "event": "error",
      "data": {
        "error": message_text,
        "session_id": session_id,
        "evaluation": finalize_payload("error", message_text, False),
      },
    }


  # ブラウザに返すローカルUI全体のHTML
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
      --panel: rgba(8, 16, 30, 0.18);
      --panel-2: rgba(8, 16, 30, 0.26);
      --text: #e5eefb;
      --muted: #94a3b8;
      --accent: #22c55e;
      --accent-2: #38bdf8;
      --border: rgba(103, 232, 249, 0.18);
      --shadow: 0 0 0 rgba(0, 0, 0, 0);
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
      border-radius: 12px;
      border: 1px solid rgba(103, 232, 249, 0.14);
      background: rgba(2, 10, 20, 0.08);
      box-shadow: var(--shadow);
      overflow: hidden;
      backdrop-filter: blur(3px);
    }

    .panel-header {
      padding: 14px 16px;
      border-bottom: 1px solid rgba(103, 232, 249, 0.14);
      background: rgba(2, 10, 20, 0.06);
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
    }

    .panel-header strong {
      font-size: 14px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: #d8f3ff;
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
      position: relative;
      padding-right: 44px;
    }

    .bubble-head {
      position: absolute;
      right: 8px;
      bottom: 8px;
      margin: 0;
    }

    .bubble-copy-btn {
      width: 32px;
      height: 32px;
      min-width: 32px;
      min-height: 32px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border: none;
      border-radius: 8px;
      background: transparent;
      color: var(--muted);
      padding: 0;
      cursor: pointer;
      opacity: 0;
      visibility: hidden;
      transition: opacity 0.16s ease, color 0.16s ease, background-color 0.16s ease;
      -webkit-tap-highlight-color: transparent;
    }

    .bubble-copy-btn svg {
      width: 18px;
      height: 18px;
      stroke: currentColor;
      stroke-width: 1.8;
      fill: none;
      pointer-events: none;
    }

    .bubble:hover .bubble-copy-btn,
    .bubble:focus-within .bubble-copy-btn {
      opacity: 1;
      visibility: visible;
    }

    .bubble-copy-btn:hover,
    .bubble-copy-btn:focus-visible {
      color: var(--accent-2);
      background: rgba(148, 163, 184, 0.14);
      outline: none;
    }

    .bubble-copy-btn.is-copied {
      color: #86efac;
      opacity: 1;
      visibility: visible;
    }

    @media (hover: none), (pointer: coarse) {
      .bubble-copy-btn {
        opacity: 1;
        visibility: visible;
      }
    }

    .bubble a {
      color: #7dd3fc;
      text-decoration: underline;
      word-break: break-all;
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

    .geo-panel {
      display: grid;
      gap: 12px;
      border-color: rgba(103, 232, 249, 0.2);
      background: rgba(1, 10, 24, 0.08);
    }

    .geo-header {
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.08em;
      color: #bae6fd;
      text-transform: uppercase;
    }

    .geo-controls {
      display: grid;
      grid-template-columns: auto minmax(0, 1fr) auto;
      gap: 8px;
      align-items: center;
    }

    .geo-source-select,
    .geo-manual-input {
      border-radius: 8px;
      border: 1px solid rgba(103, 232, 249, 0.2);
      background: rgba(2, 8, 20, 0.2);
      color: var(--text);
      padding: 8px 10px;
      font-size: 12px;
      min-height: 36px;
    }

    .geo-manual-input {
      width: 100%;
    }

    .geo-action-btn {
      width: 36px;
      height: 36px;
      min-width: 36px;
      border-radius: 8px;
      border: 1px solid rgba(103, 232, 249, 0.2);
      background: rgba(2, 8, 20, 0.2);
      color: #a5f3fc;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 0;
      box-shadow: none;
      transition: background-color 0.16s ease, color 0.16s ease, border-color 0.16s ease;
    }

    .geo-action-btn svg {
      width: 18px;
      height: 18px;
      stroke: currentColor;
      fill: none;
      stroke-width: 1.8;
    }

    .geo-action-btn:hover,
    .geo-action-btn:focus-visible {
      background: rgba(125, 211, 252, 0.08);
      color: #67e8f9;
      border-color: rgba(125, 211, 252, 0.42);
      outline: none;
    }

    .geo-maps-wrap {
      display: grid;
      gap: 10px;
      margin-bottom: 10px;
    }

    .geo-map-block {
      display: grid;
      gap: 6px;
    }

    .geo-map-title {
      font-size: 11px;
      letter-spacing: 0.08em;
      color: #7dd3fc;
      font-weight: 700;
    }

    .geo-map-frame {
      position: relative;
      width: 100%;
      aspect-ratio: 960 / 460;
      border-radius: 8px;
      overflow: hidden;
      border: 1px solid rgba(103, 232, 249, 0.2);
      background: transparent;
    }

    .geo-map-svg {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      display: block;
      opacity: 0.92;
    }

    .geo-map-sea {
      fill: transparent;
    }

    .geo-map-grid {
      fill: none;
      stroke: rgba(103, 232, 249, 0.22);
      stroke-width: 0.75;
      vector-effect: non-scaling-stroke;
    }

    .geo-map-land {
      fill: rgba(6, 182, 212, 0.05);
      stroke: rgba(103, 232, 249, 0.42);
      stroke-width: 0.8;
      vector-effect: non-scaling-stroke;
    }

    .geo-map-border {
      fill: none;
      stroke: rgba(125, 211, 252, 0.28);
      stroke-width: 0.65;
      vector-effect: non-scaling-stroke;
    }

    .geo-map-city {
      fill: rgba(103, 232, 249, 0.74);
      font-size: 15px;
      font-family: "Segoe UI", "Noto Sans JP", sans-serif;
      paint-order: stroke;
      stroke: rgba(2, 6, 23, 0.55);
      stroke-width: 3;
      stroke-linejoin: round;
    }

    .geo-map-marker,
    .geo-map-wave {
      position: absolute;
      left: 50%;
      top: 50%;
      transform: translate(-50%, -50%);
    }

    .geo-map-marker {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #ff4d4d;
      box-shadow: 0 0 8px rgba(255, 77, 77, 0.92), 0 0 16px rgba(255, 77, 77, 0.45);
      z-index: 3;
      cursor: pointer;
      pointer-events: auto;
    }

    .geo-map-wave {
      width: 14px;
      height: 14px;
      border-radius: 50%;
      border: 1px solid rgba(255, 95, 95, 0.72);
      animation: geo-wave 3s ease-out infinite;
      z-index: 2;
      pointer-events: none;
    }

    .geo-map-label {
      position: absolute;
      left: 8px;
      bottom: 8px;
      font-size: 11px;
      color: #d8f3ff;
      padding: 2px 0;
      border-radius: 0;
      border: none;
      background: transparent;
      text-shadow: 0 0 8px rgba(56, 189, 248, 0.25);
      z-index: 3;
    }

    .geo-map-outside {
      position: absolute;
      right: 8px;
      top: 8px;
      font-size: 11px;
      color: #fda4af;
      border: 1px solid rgba(251, 113, 133, 0.3);
      background: rgba(76, 5, 25, 0.18);
      border-radius: 6px;
      padding: 3px 7px;
      opacity: 0;
      transform: translateY(-4px);
      transition: opacity 0.2s ease, transform 0.2s ease;
      pointer-events: none;
      z-index: 3;
    }

    .geo-map-outside.show {
      opacity: 1;
      transform: translateY(0);
    }

    .geo-map-marker.hidden,
    .geo-map-wave.hidden {
      opacity: 0;
    }

    .geo-panel.paused .geo-map-wave {
      animation-play-state: paused;
    }

    .geo-map-land.muted {
      fill: rgba(6, 182, 212, 0.03);
      stroke: rgba(103, 232, 249, 0.2);
    }

    .geo-map-land.focus {
      fill: rgba(255, 77, 77, 0.12);
      stroke: rgba(255, 122, 122, 0.6);
      stroke-width: 1.1;
    }

    .geo-map-nav {
      display: grid;
      gap: 6px;
    }

    .geo-breadcrumb {
      font-size: 11px;
      color: #e7f8ff;
      letter-spacing: 0.03em;
      border-bottom: 1px solid rgba(103, 232, 249, 0.16);
      padding-bottom: 4px;
    }

    .geo-nav-actions {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
    }

    .geo-nav-btn {
      width: auto;
      padding: 6px 10px;
      border-radius: 7px;
      border: 1px solid rgba(103, 232, 249, 0.2);
      background: rgba(2, 8, 20, 0.2);
      color: #bae6fd;
      font-size: 11px;
      font-weight: 600;
      box-shadow: none;
    }

    .geo-nav-btn:hover,
    .geo-nav-btn:focus-visible {
      border-color: rgba(125, 211, 252, 0.42);
      color: #e7f8ff;
      outline: none;
    }

    .geo-manual-candidates {
      display: grid;
      gap: 6px;
      margin-top: 6px;
    }

    .geo-manual-candidate {
      width: 100%;
      text-align: left;
      padding: 8px;
      border-radius: 7px;
      border: 1px solid rgba(103, 232, 249, 0.18);
      background: rgba(2, 8, 20, 0.2);
      color: #e2f3ff;
      box-shadow: none;
    }

    .geo-manual-candidate small {
      display: block;
      color: rgba(186, 230, 253, 0.68);
      margin-top: 2px;
      line-height: 1.35;
    }

    .geo-info {
      display: grid;
      gap: 6px;
      min-width: 0;
    }

    .geo-label {
      color: #e7f8ff;
      font-size: 13px;
      font-weight: 700;
      line-height: 1.4;
      word-break: break-word;
    }

    .geo-meta {
      color: rgba(186, 230, 253, 0.72);
      font-size: 12px;
      line-height: 1.45;
      word-break: break-word;
    }

    .geo-weather-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }

    .geo-weather-item {
      border: 1px solid rgba(103, 232, 249, 0.16);
      border-radius: 6px;
      padding: 7px 8px;
      background: transparent;
      display: grid;
      gap: 2px;
    }

    .geo-weather-item span {
      color: #93c5fd;
      font-size: 11px;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }

    .geo-weather-item strong {
      color: #eaf7ff;
      font-size: 14px;
      font-weight: 700;
      line-height: 1.35;
      word-break: break-word;
    }

    .geo-status {
      color: rgba(148, 163, 184, 0.82);
      font-size: 12px;
      line-height: 1.45;
      word-break: break-word;
    }

    .geo-panel.state-loading .geo-status {
      color: #93c5fd;
    }

    .geo-panel.state-error .geo-status {
      color: #fda4af;
    }

    @keyframes geo-spin {
      from { transform: rotate(0deg); }
      to { transform: rotate(360deg); }
    }

    @keyframes geo-wave {
      0% { transform: translate(-50%, -50%) scale(0.72); opacity: 0.75; }
      80% { transform: translate(-50%, -50%) scale(2.25); opacity: 0.06; }
      100% { transform: translate(-50%, -50%) scale(2.45); opacity: 0; }
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

    .evaluation-wrap {
      align-self: flex-start;
      width: min(92%, 560px);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 10px;
      background: rgba(15, 23, 42, 0.78);
      display: grid;
      gap: 8px;
    }

    .evaluation-actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }

    .evaluation-actions button {
      flex: 1 1 120px;
      width: auto;
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
      color: rgba(186, 230, 253, 0.72);
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

    .template-manager {
      display: grid;
      gap: 12px;
    }

    .template-list {
      display: grid;
      gap: 8px;
      max-height: 280px;
      overflow: auto;
      padding-right: 2px;
    }

    .template-item {
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

    .template-item-title {
      font-size: 14px;
      font-weight: 700;
      line-height: 1.45;
    }

    .template-item-meta {
      font-size: 12px;
      color: var(--muted);
      line-height: 1.5;
      word-break: break-word;
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
      border-radius: 10px;
      border: 1px solid rgba(103, 232, 249, 0.14);
      background: rgba(2, 10, 20, 0.06);
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

    .jarvis-shell {
      width: min(1820px, calc(100% - 20px));
      padding: 10px 0 20px;
    }

    .first-screen {
      min-height: calc(100vh - 22px);
      display: grid;
      grid-template-columns: 320px minmax(0, 1fr) 330px;
      gap: 10px;
      align-items: stretch;
    }

    .hero,
    .layout {
      display: none;
    }

    .hud-left,
    .hud-center {
      min-height: 0;
    }

    .hud-left .panel-body,
    .hud-center .panel-body {
      height: calc(100% - 56px);
      min-height: 0;
    }

    .hud-center {
      display: flex;
      flex-direction: column;
      min-width: 0;
    }

    .chat-body {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .chat-body #chat-log {
      min-height: 0;
      max-height: none;
      flex: 1;
    }

    .hud-right {
      display: grid;
      grid-template-rows: auto auto 1fr;
      gap: 10px;
      min-height: 0;
    }

    .clock-panel .panel-body {
      display: grid;
      gap: 4px;
    }

    .clock-time {
      font-size: clamp(36px, 4vw, 46px);
      line-height: 1;
      letter-spacing: 0.03em;
      color: #dbeafe;
      font-weight: 700;
    }

    .clock-date {
      font-size: 14px;
      color: rgba(186, 230, 253, 0.68);
      letter-spacing: 0.04em;
    }

    .runtime-grid {
      display: grid;
      gap: 6px;
    }

    .runtime-log-list {
      margin: 0;
      padding-left: 16px;
      display: grid;
      gap: 6px;
      color: #cbd5e1;
      font-size: 12px;
      line-height: 1.5;
      max-height: 190px;
      overflow: auto;
    }

    .scroll-guide {
      grid-column: 1 / -1;
      justify-self: center;
      align-self: end;
      font-size: 12px;
      color: #93c5fd;
      opacity: 0.82;
      padding: 6px 10px;
      border-radius: 999px;
      border: 1px solid rgba(147, 197, 253, 0.25);
      background: rgba(2, 6, 23, 0.38);
      margin-bottom: 2px;
    }

    .lower-section {
      display: grid;
      grid-template-columns: 1.3fr 1fr;
      gap: 12px;
      margin-top: 14px;
      align-items: start;
    }

    .lower-section .panel .panel-body {
      max-height: none;
    }

    .geo-panel {
      background:
        radial-gradient(circle at 16% 10%, rgba(56, 189, 248, 0.08), transparent 34%),
        linear-gradient(170deg, rgba(1, 8, 22, 0.12), rgba(4, 14, 30, 0.08));
      padding: 12px;
    }

    .hud-left,
    .hud-right > .panel {
      background: rgba(2, 8, 20, 0.05);
      border-color: rgba(103, 232, 249, 0.14);
    }

    .hud-center {
      background: linear-gradient(180deg, rgba(2, 8, 20, 0.46), rgba(2, 8, 20, 0.36));
      border-color: rgba(148, 163, 184, 0.2);
      backdrop-filter: blur(8px);
    }

    .geo-row {
      grid-template-columns: 136px 1fr;
      gap: 10px;
    }

    .geo-globe-wrap {
      width: 136px;
      height: 136px;
    }

    .geo-globe {
      width: 124px;
      height: 124px;
    }

    .geo-settings-fold {
      margin-top: 8px;
      border-top: 1px solid rgba(148, 163, 184, 0.24);
      padding-top: 8px;
    }

    .geo-settings-fold summary {
      list-style: none;
      cursor: pointer;
      color: #93c5fd;
      font-size: 12px;
      letter-spacing: 0.03em;
      user-select: none;
    }

    .geo-settings-fold summary::-webkit-details-marker {
      display: none;
    }

    .geo-settings-fold[open] summary {
      margin-bottom: 8px;
    }

    .geo-status {
      margin-top: 8px;
    }

    .geo-weather-grid {
      margin-top: 8px;
    }

    @media (max-width: 1500px) {
      .first-screen {
        grid-template-columns: 300px minmax(0, 1fr) 300px;
      }
    }

    @media (max-width: 1366px) {
      .first-screen {
        grid-template-columns: 280px minmax(0, 1fr) 280px;
      }

      .clock-time {
        font-size: 34px;
      }

      .quick-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
    }

    @media (max-width: 860px) {
      .first-screen { grid-template-columns: 1fr; min-height: auto; }
      .lower-section { grid-template-columns: 1fr; }
      .hud-right { grid-template-rows: auto auto auto; }
      #chat-log { min-height: 48vh; max-height: none; }
      .bubble { max-width: 100%; }
      .composer { bottom: 0; }
      .row > * { flex: 1 1 100%; }
      button { width: 100%; }
      .geo-controls { grid-template-columns: auto 1fr auto; }
      .geo-action-btn { width: 36px; }
      .geo-map-label,
      .geo-map-outside { font-size: 10px; }
      .geo-weather-grid { grid-template-columns: 1fr; }
      .scroll-guide { display: none; }
    }
  </style>
  <link rel="stylesheet" href="/site/dashboard/dashboard.css" />
</head>
<body>
  <div class="shell jarvis-shell">
    <header class="dashboard-header">
      <div class="dashboard-brand">AI<span> / </span>CORE <small>LOCAL FIRST ASSISTANT</small></div>
      <nav class="dashboard-nav" aria-label="情報パネル">
        <button type="button" data-open-panel="weather" aria-expanded="false">天気</button>
        <button type="button" data-open-panel="map" aria-expanded="false">地図</button>
        <button type="button" data-open-panel="location" aria-expanded="false">現在地</button>
        <button type="button" data-open-panel="translate" aria-expanded="false">翻訳</button>
        <button type="button" data-open-panel="search" aria-expanded="false">検索</button>
        <button type="button" id="close-all-panels">すべて閉じる</button>
        <button type="button" id="open-workspace" aria-expanded="false">文書・設定</button>
      </nav>
    </header>
    <section class="first-screen">
      <aside class="panel hud-left" data-info-panel="location" hidden>
        <div class="panel-header"><strong>現在地</strong></div>
        <div class="panel-body">
          <div class="card geo-panel" id="geo-panel-card">
            <div class="geo-maps-wrap">
              <div class="geo-map-block">
                <div class="geo-map-title">WORLD</div>
                <div class="geo-map-frame" id="world-map-frame">
                  <svg class="geo-map-svg" id="world-map-svg" viewBox="0 0 960 460" preserveAspectRatio="xMidYMid meet" aria-hidden="true"></svg>
                  <div class="geo-map-marker" id="world-map-marker"></div>
                  <div class="geo-map-wave" id="world-map-wave"></div>
                  <div class="geo-map-label" id="world-map-label">—</div>
                  <div class="geo-map-outside" id="world-map-outside"></div>
                </div>
              </div>
              <div class="geo-map-block">
                <div class="geo-map-title" id="geo-detail-title">JAPAN</div>
                <div class="geo-map-frame" id="japan-map-frame">
                  <svg class="geo-map-svg" id="japan-map-svg" viewBox="0 0 960 460" preserveAspectRatio="xMidYMid meet" aria-hidden="true"></svg>
                  <div class="geo-map-marker" id="japan-map-marker"></div>
                  <div class="geo-map-wave" id="japan-map-wave"></div>
                  <div class="geo-map-label" id="japan-map-label">—</div>
                  <div class="geo-map-outside" id="japan-map-outside">日本国外</div>
                </div>
              </div>
            </div>
            <div class="geo-map-nav">
              <div class="geo-breadcrumb" id="geo-breadcrumb">世界</div>
              <div class="geo-nav-actions">
                <button class="geo-nav-btn" id="geo-nav-back-btn" type="button">戻る</button>
                <button class="geo-nav-btn" id="geo-nav-home-btn" type="button">全体表示</button>
              </div>
            </div>
            <div class="geo-info">
              <div class="geo-label" id="geo-location-label">地点: 取得中...</div>
              <div class="geo-meta" id="geo-location-meta">地域: — / 国: —</div>
              <div class="geo-meta" id="geo-provider">取得元: —</div>
              <div class="geo-meta" id="geo-latlon">緯度: — / 経度: —</div>
              <div class="geo-meta" id="geo-accuracy">精度: —</div>
              <div class="geo-meta">タイムゾーン: <span id="geo-timezone">—</span></div>
              <div class="geo-meta">現地時刻: <span id="geo-local-time">—</span></div>
              <div class="geo-meta">天気: <span id="geo-weather">—</span></div>
              <div class="geo-meta">気温: <span id="geo-temp">—</span></div>
              <div class="geo-meta">湿度: <span id="geo-humidity">—</span></div>
              <div class="geo-meta">風: <span id="geo-wind">—</span></div>
              <div class="geo-meta">更新時刻: <span id="geo-observed-at">—</span></div>
            </div>
            <details class="geo-settings-fold">
              <summary>位置設定</summary>
              <div class="geo-controls">
                <button class="geo-action-btn" id="geo-fetch-btn" type="button" aria-label="現在地を取得" title="現在地を取得">
                  <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                    <circle cx="12" cy="12" r="5"></circle>
                    <path d="M12 2v3M12 19v3M2 12h3M19 12h3"></path>
                  </svg>
                </button>
                <select class="geo-source-select" id="geo-source-select" aria-label="位置情報モード">
                  <option value="device">端末位置</option>
                  <option value="ip" selected>IP推定</option>
                  <option value="manual">手動</option>
                </select>
                <button class="geo-action-btn" id="geo-manual-apply-btn" type="button" aria-label="手動地域を反映" title="手動地域を反映">
                  <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                    <path d="M5 12h14"></path>
                    <path d="M13 6l6 6-6 6"></path>
                  </svg>
                </button>
              </div>
              <input class="geo-manual-input" id="geo-manual-input" placeholder="手動地域（例: 京都）" />
              <div class="geo-manual-candidates" id="geo-manual-candidates"></div>
              <div class="geo-weather-grid">
                <div class="geo-weather-item"><span>最高/最低</span><strong id="geo-hi-lo">— / —</strong></div>
                <div class="geo-weather-item"><span>降水確率</span><strong id="geo-rain">—</strong></div>
              </div>
              <div class="geo-status" id="geo-status">取得中...</div>
            </details>
          </div>
        </div>
      </aside>

      <aside class="monitor-column">
        <section class="panel system-monitor">
          <div class="panel-header"><strong>SYSTEM MONITOR</strong><span class="live-badge" id="monitor-status">接続中</span></div>
          <div class="panel-body" id="system-monitor-content"><p>PC情報を取得しています…</p></div>
        </section>
        <section class="panel ai-core-panel">
          <div class="panel-header"><strong>AI CORE</strong><span class="core-mode">LIVE STATE</span></div>
          <div id="ai-core" data-state="idle" role="img" aria-label="AIの状態: 待機中">
            <div class="core-orbit"></div><div class="core-inner"></div><div class="core-center">AI</div>
          </div>
          <div id="core-state-label" role="status" aria-live="polite">待機中</div>
          <p class="core-caption" id="core-caption">ローカルアシスタント</p>
          <div class="voice-controls"><button type="button" id="voice-start">音声入力</button><label><input type="checkbox" id="speak-enabled" /> 読み上げ</label></div>
          <p class="core-caption" id="voice-support"></p>
        </section>
      </aside>
      <section class="panel hud-center">
        <div class="panel-header">
          <strong>CHAT / 会話</strong>
          <div class="status"><span class="dot"></span><span id="session-text">session ready</span></div>
        </div>
        <div class="panel-body chat-body">
          <div id="chat-log"></div>
          <div class="composer">
            <div class="quick-grid">
              <button class="secondary quick-prompt" type="button" data-text="このローカルサーバーでできることを具体例つきで教えて">できること</button>
              <button class="secondary quick-prompt" type="button" data-text="ここから東京駅までの行き方を教えて">ルート</button>
              <button class="secondary quick-prompt" type="button" data-text="(150+230)÷19 を計算して">計算</button>
              <button class="secondary quick-prompt" type="button" data-text="保存してある自己PR文書を一覧で見せて">文書一覧</button>
            </div>
            <label class="composer-label" for="message">メッセージ</label><textarea id="message" aria-label="メッセージ" placeholder="メッセージを入力…（Shift + Enterで改行）"></textarea>
            <div class="row">
              <input id="session-id" placeholder="session id" />
              <input id="current-location" placeholder="現在地（任意）" />
              <button id="send-btn" type="button">送信</button>
              <button id="reset-btn" class="secondary" type="button">新しい会話</button>
            </div>
          </div>
        </div>
      </section>

      <aside class="hud-right">
        <div id="info-panel-dock">
          <div id="panels-empty"><span>INFORMATION</span><h2>会話に、必要な情報を。</h2><p>上のボタンからパネルを開けます。<br>ピン留めしたパネルは表示を維持します。</p></div>
          <section class="panel" data-info-panel="weather" hidden><div class="panel-header"><strong>天気</strong></div><div class="panel-body" id="weather-summary"><p>現在地の天気を取得しています…</p></div></section>
          <section class="panel" data-info-panel="map" hidden><div class="panel-header"><strong>地図</strong></div><div class="panel-body" id="map-panel-content"><p class="core-caption">現在地パネルで選択した地域を表示します。</p></div></section>
          <section class="panel" data-info-panel="translate" hidden><div class="panel-header"><strong>翻訳</strong></div><div class="panel-body"><p>翻訳は中央のチャットから依頼できます。</p><p class="core-caption">翻訳結果のカード連携は保留中です。</p><button type="button" data-panel-prompt="次の文章を日本語に翻訳して：">チャットで翻訳する</button></div></section>
          <section class="panel" data-info-panel="search" hidden><div class="panel-header"><strong>検索</strong></div><div class="panel-body"><p>調べたい内容を中央のチャットに入力してください。</p><p class="core-caption">検索結果のカード連携は保留中です。</p><button type="button" data-panel-prompt="次の内容を検索して：">チャットで検索する</button></div></section>
        </div>
        <section class="panel clock-panel">
          <div class="panel-body">
            <div class="clock-time" id="clock-time">--:--:--</div>
            <div class="clock-date" id="clock-date">----/--/-- (---)</div>
          </div>
        </section>
        <section class="panel runtime-panel">
          <div class="panel-header"><strong>Runtime</strong></div>
          <div class="panel-body runtime-grid">
            <div class="meta-line">接続: <span id="runtime-connection">—</span></div>
            <div class="meta-line">モデル: <span id="runtime-model">—</span></div>
            <div class="meta-line">処理状態: <span id="runtime-processing">—</span></div>
            <div class="meta-line">応答時間: <span id="runtime-latency">—</span></div>
            <div class="meta-line">処理経路: <span id="runtime-route">—</span></div>
            <div class="meta-line">クラウドLLM: <span id="runtime-cloud">—</span></div>
            <div class="meta-line">health: <span id="health-text">checking...</span></div>
            <div class="meta-line" id="server-url-chip">url: loading...</div>
            <div class="meta-line" id="server-ip-chip">ip: loading...</div>
          </div>
        </section>
        <section class="panel log-panel">
          <div class="panel-header"><strong>Recent Logs</strong></div>
          <div class="panel-body">
            <ul class="runtime-log-list" id="runtime-log-list">
              <li>—</li>
            </ul>
          </div>
        </section>
      </aside>


    </section>

    <section class="lower-section" id="workspace-drawer" hidden role="dialog" aria-label="文書管理と詳細設定" aria-modal="true" tabindex="-1"><button type="button" id="close-workspace">閉じる ×</button>
      <div class="panel">
        <div class="panel-header">
          <strong>Documents</strong>
          <div class="row" style="margin:0;">
            <button id="document-new-btn" class="secondary" type="button">新規作成</button>
            <button id="document-refresh-btn" class="secondary" type="button">更新</button>
          </div>
        </div>
        <div class="panel-body">
          <div class="card doc-manager">
            <div class="doc-meta" id="document-current-card">現在表示中: なし</div>
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
        </div>
      </div>

      <div class="panel">
        <div class="panel-header"><strong>Details</strong></div>
        <div class="panel-body side-list">
          <div class="card meta-line" id="meta-card">サーバー情報を取得しています。</div>
          <div class="card template-manager">
            <div class="doc-manager-header">
              <span class="doc-manager-title">使える処理テンプレート</span>
              <button id="capability-refresh-btn" class="secondary" type="button">更新</button>
            </div>
            <div class="doc-meta" id="capability-guide">このローカルサーバーで実行できる質問テンプレートを表示します。</div>
            <div class="template-list" id="capability-template-list"></div>
          </div>
          <div class="card" id="storage-card">DB状態を確認しています。</div>
          <div class="card" id="health-card">サーバー状態を確認しています。</div>
          <div class="card">Ollama がローカルで起動している必要があります。</div>
          <div class="card">スマホから使う場合は、iPhone の Safari で上の URL を開いてください。</div>
          <div class="card">会話履歴は session id ごとに分けています。</div>
        </div>
      </div>
    </section>
  </div>

  <script src="/site/maps/topojson-client.min.js"></script>
  <script src="/site/dashboard/dashboard.js"></script>
  <script src="/site/dashboard/workbench.js"></script>
  <script>
    const chatLog = document.getElementById('chat-log');
    const messageInput = document.getElementById('message');
    const sessionInput = document.getElementById('session-id');
    const locationInput = document.getElementById('current-location');
    const sendBtn = document.getElementById('send-btn');
    const resetBtn = document.getElementById('reset-btn');
    const healthText = document.getElementById('health-text');
    const healthCard = document.getElementById('health-card');
    const storageCard = document.getElementById('storage-card');
    const metaCard = document.getElementById('meta-card');
    const serverUrlChip = document.getElementById('server-url-chip');
    const serverIpChip = document.getElementById('server-ip-chip');
    const sessionText = document.getElementById('session-text');
    const capabilityGuide = document.getElementById('capability-guide');
    const capabilityTemplateList = document.getElementById('capability-template-list');
    const capabilityRefreshBtn = document.getElementById('capability-refresh-btn');
    const documentList = document.getElementById('document-list');
    const documentNewBtn = document.getElementById('document-new-btn');
    const documentTitleInput = document.getElementById('document-title');
    const documentContentInput = document.getElementById('document-content');
    const documentMeta = document.getElementById('document-meta');
    const documentCurrentCard = document.getElementById('document-current-card');
    const documentMode = document.getElementById('document-mode');
    const documentRefreshBtn = document.getElementById('document-refresh-btn');
    const documentSaveBtn = document.getElementById('document-save-btn');
    const documentDeleteBtn = document.getElementById('document-delete-btn');
    const documentClearBtn = document.getElementById('document-clear-btn');
    const geoPanelCard = document.getElementById('geo-panel-card');
    const geoFetchBtn = document.getElementById('geo-fetch-btn');
    const geoManualApplyBtn = document.getElementById('geo-manual-apply-btn');
    const geoSourceSelect = document.getElementById('geo-source-select');
    const geoManualInput = document.getElementById('geo-manual-input');
    const worldMapSvg = document.getElementById('world-map-svg');
    const japanMapSvg = document.getElementById('japan-map-svg');
    const worldMapMarker = document.getElementById('world-map-marker');
    const worldMapWave = document.getElementById('world-map-wave');
    const japanMapMarker = document.getElementById('japan-map-marker');
    const japanMapWave = document.getElementById('japan-map-wave');
    const worldMapLabel = document.getElementById('world-map-label');
    const japanMapLabel = document.getElementById('japan-map-label');
    const japanMapOutside = document.getElementById('japan-map-outside');
    const geoDetailTitle = document.getElementById('geo-detail-title');
    const geoBreadcrumb = document.getElementById('geo-breadcrumb');
    const geoNavBackBtn = document.getElementById('geo-nav-back-btn');
    const geoNavHomeBtn = document.getElementById('geo-nav-home-btn');
    const geoManualCandidates = document.getElementById('geo-manual-candidates');
    const geoLocationLabel = document.getElementById('geo-location-label');
    const geoLocationMeta = document.getElementById('geo-location-meta');
    const geoLatLon = document.getElementById('geo-latlon');
    const geoProvider = document.getElementById('geo-provider');
    const geoAccuracy = document.getElementById('geo-accuracy');
    const geoTimezone = document.getElementById('geo-timezone');
    const geoLocalTime = document.getElementById('geo-local-time');
    const geoHumidity = document.getElementById('geo-humidity');
    const geoWind = document.getElementById('geo-wind');
    const geoObservedAt = document.getElementById('geo-observed-at');
    const geoWeather = document.getElementById('geo-weather');
    const geoTemp = document.getElementById('geo-temp');
    const geoHiLo = document.getElementById('geo-hi-lo');
    const geoRain = document.getElementById('geo-rain');
    const geoStatus = document.getElementById('geo-status');
    const clockTime = document.getElementById('clock-time');
    const clockDate = document.getElementById('clock-date');
    const runtimeConnection = document.getElementById('runtime-connection');
    const runtimeModel = document.getElementById('runtime-model');
    const runtimeProcessing = document.getElementById('runtime-processing');
    const runtimeLatency = document.getElementById('runtime-latency');
    const runtimeRoute = document.getElementById('runtime-route');
    const runtimeCloud = document.getElementById('runtime-cloud');
    const runtimeLogList = document.getElementById('runtime-log-list');

    const storageKey = 'local-ai-session-id';
    const locationStorageKey = 'local-ai-current-location';
    const geoPanelCacheKey = 'local-ai-geo-panel-cache-v1';
    const geoPanelModeKey = 'local-ai-geo-mode-v1';
    const geoManualRegionKey = 'local-ai-geo-manual-region-v1';

    const geoState = {
      mode: 'ip',
      device: null,
      manual: '',
      manualResolvedAddress: '',
      manualCandidates: [],
      manualLock: false,
      targetCoord: null,
      panelVisible: true,
      isInitialized: false,
      requestSeq: 0,
      appliedSeq: 0,
      worldReady: false,
      japanReady: false,
      worldFeatures: [],
      japanFeatures: [],
      detailHistory: ['world'],
      detailPath: ['世界'],
      detailLevel: 'world',
      selectedCountry: '',
      selectedRegionBand: '',
      selectedPrefecture: '',
      selectedPrefCode: '',
    };

    const runtimeLogItems = [];

    function appendRuntimeLog(message) {
      const line = String(message || '').trim();
      if (!line) {
        return;
      }
      runtimeLogItems.unshift(line);
      while (runtimeLogItems.length > 5) {
        runtimeLogItems.pop();
      }
      runtimeLogList.innerHTML = '';
      runtimeLogItems.forEach((item) => {
        const li = document.createElement('li');
        li.textContent = item;
        runtimeLogList.appendChild(li);
      });
    }

    function formatTokyoNow() {
      const now = new Date();
      const time = new Intl.DateTimeFormat('ja-JP', {
        timeZone: 'Asia/Tokyo',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
      }).format(now);
      const date = new Intl.DateTimeFormat('ja-JP', {
        timeZone: 'Asia/Tokyo',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        weekday: 'short',
      }).format(now);
      return { time, date };
    }

    function refreshTokyoClock() {
      const current = formatTokyoNow();
      clockTime.textContent = current.time;
      clockDate.textContent = current.date;
    }

    function makeSessionId() {
      try {
        if (window.crypto && typeof window.crypto.randomUUID === 'function') {
          return window.crypto.randomUUID();
        }
      } catch (e) {
      }
      return String(Date.now());
    }

    function safeStorageGet(key) {
      try {
        return window.localStorage.getItem(key);
      } catch (e) {
        return null;
      }
    }

    function safeStorageSet(key, value) {
      try {
        window.localStorage.setItem(key, value);
      } catch (e) {
      }
    }

    function safeStorageRemove(key) {
      try {
        window.localStorage.removeItem(key);
      } catch (e) {
      }
    }

    function getPathValue(obj, path, fallbackValue) {
      let cursor = obj;
      for (let i = 0; i < path.length; i += 1) {
        if (!cursor || typeof cursor !== 'object' || !(path[i] in cursor)) {
          return fallbackValue;
        }
        cursor = cursor[path[i]];
      }
      return cursor == null ? fallbackValue : cursor;
    }

    const savedSessionId = safeStorageGet(storageKey) || makeSessionId();
    safeStorageSet(storageKey, savedSessionId);
    sessionInput.value = savedSessionId;
    const savedCurrentLocation = safeStorageGet(locationStorageKey) || '';
    locationInput.value = savedCurrentLocation;
    const savedGeoMode = safeStorageGet(geoPanelModeKey) || 'ip';
    const savedManualRegion = safeStorageGet(geoManualRegionKey) || '';
    geoState.mode = ['device', 'ip', 'manual'].includes(savedGeoMode) ? savedGeoMode : 'ip';
    geoState.manual = savedManualRegion;
    if (geoSourceSelect) {
      geoSourceSelect.value = geoState.mode;
    }
    if (geoManualInput) {
      geoManualInput.value = geoState.manual;
    }

    function persistCurrentLocation(value) {
      safeStorageSet(locationStorageKey, value || '');
    }

    function persistGeoMode(mode) {
      safeStorageSet(geoPanelModeKey, mode || 'ip');
    }

    function persistManualRegion(value) {
      safeStorageSet(geoManualRegionKey, value || '');
    }

    function normalizeMode(value) {
      const mode = String(value || '').trim().toLowerCase();
      if (mode === 'device' || mode === 'manual' || mode === 'ip') {
        return mode;
      }
      return 'ip';
    }

    function clearGeoPanelCache() {
      safeStorageRemove(geoPanelCacheKey);
    }

    function setGeoPanelState(state) {
      if (!geoPanelCard) {
        return;
      }
      geoPanelCard.classList.remove('state-loading', 'state-error', 'state-ready');
      geoPanelCard.classList.add(`state-${state}`);
    }

    function formatLatLon(value) {
      if (typeof value !== 'number' || Number.isNaN(value)) {
        return '—';
      }
      return value.toFixed(4);
    }

    function formatAccuracy(value) {
      const numeric = Number(value);
      if (!Number.isFinite(numeric) || numeric <= 0) {
        return '—';
      }
      return `±${Math.round(numeric)}m`;
    }

    const PREF_CODE_TO_NAME = {
      1: '北海道', 2: '青森県', 3: '岩手県', 4: '宮城県', 5: '秋田県', 6: '山形県', 7: '福島県',
      8: '茨城県', 9: '栃木県', 10: '群馬県', 11: '埼玉県', 12: '千葉県', 13: '東京都', 14: '神奈川県',
      15: '新潟県', 16: '富山県', 17: '石川県', 18: '福井県', 19: '山梨県', 20: '長野県',
      21: '岐阜県', 22: '静岡県', 23: '愛知県', 24: '三重県', 25: '滋賀県', 26: '京都府', 27: '大阪府',
      28: '兵庫県', 29: '奈良県', 30: '和歌山県', 31: '鳥取県', 32: '島根県', 33: '岡山県', 34: '広島県',
      35: '山口県', 36: '徳島県', 37: '香川県', 38: '愛媛県', 39: '高知県', 40: '福岡県', 41: '佐賀県',
      42: '長崎県', 43: '熊本県', 44: '大分県', 45: '宮崎県', 46: '鹿児島県', 47: '沖縄県'
    };

    const EAST_PREF_SET = new Set([
      '北海道', '青森県', '岩手県', '宮城県', '秋田県', '山形県', '福島県',
      '茨城県', '栃木県', '群馬県', '埼玉県', '千葉県', '東京都', '神奈川県',
      '新潟県', '富山県', '石川県', '福井県', '山梨県', '長野県',
      '岐阜県', '静岡県', '愛知県'
    ]);

    const WEST_PREF_SET = new Set(Object.values(PREF_CODE_TO_NAME).filter((name) => !EAST_PREF_SET.has(name)));

    const PREF_EN_ALIAS = {
      hokkaido: '北海道', aomori: '青森県', iwate: '岩手県', miyagi: '宮城県', akita: '秋田県', yamagata: '山形県', fukushima: '福島県',
      ibaraki: '茨城県', tochigi: '栃木県', gunma: '群馬県', saitama: '埼玉県', chiba: '千葉県', tokyo: '東京都', kanagawa: '神奈川県',
      niigata: '新潟県', toyama: '富山県', ishikawa: '石川県', fukui: '福井県', yamanashi: '山梨県', nagano: '長野県',
      gifu: '岐阜県', shizuoka: '静岡県', aichi: '愛知県', mie: '三重県', shiga: '滋賀県', kyoto: '京都府', osaka: '大阪府',
      hyogo: '兵庫県', nara: '奈良県', wakayama: '和歌山県', tottori: '鳥取県', shimane: '島根県', okayama: '岡山県', hiroshima: '広島県',
      yamaguchi: '山口県', tokushima: '徳島県', kagawa: '香川県', ehime: '愛媛県', kochi: '高知県', fukuoka: '福岡県', saga: '佐賀県',
      nagasaki: '長崎県', kumamoto: '熊本県', oita: '大分県', miyazaki: '宮崎県', kagoshima: '鹿児島県', okinawa: '沖縄県'
    };

    function normalizePrefName(value) {
      const raw = String(value || '').trim();
      if (!raw) {
        return '';
      }
      const base = raw
        .replace(/都道府県|都|道|府|県/g, '')
        .replace(/\s+/g, '')
        .toLowerCase();
      if (PREF_EN_ALIAS[base]) {
        return PREF_EN_ALIAS[base];
      }
      const entries = Object.values(PREF_CODE_TO_NAME);
      for (let i = 0; i < entries.length; i += 1) {
        const pref = entries[i];
        const key = pref.replace(/都道府県|都|道|府|県/g, '').toLowerCase();
        if (key === base || pref === raw) {
          return pref;
        }
      }
      return raw;
    }

    function updateDetailBreadcrumb() {
      if (!geoBreadcrumb) {
        return;
      }
      geoBreadcrumb.textContent = geoState.detailPath.join(' > ');
      if (geoDetailTitle) {
        if (geoState.detailLevel === 'world') {
          geoDetailTitle.textContent = 'JAPAN';
        } else if (geoState.detailLevel === 'country') {
          geoDetailTitle.textContent = isJapanCountryName(geoState.selectedCountry || '') ? 'JAPAN' : (geoState.selectedCountry || 'COUNTRY');
        } else if (geoState.detailLevel === 'east-west') {
          geoDetailTitle.textContent = geoState.selectedRegionBand || 'JAPAN';
        } else if (geoState.detailLevel === 'prefecture') {
          geoDetailTitle.textContent = geoState.selectedPrefecture || 'JAPAN';
        }
      }
    }

    function pushDetailState(level, label) {
      geoState.detailLevel = level;
      const current = geoState.detailHistory[geoState.detailHistory.length - 1];
      if (current !== level) {
        geoState.detailHistory.push(level);
      }
      if (label) {
        const lastLabel = geoState.detailPath[geoState.detailPath.length - 1];
        if (lastLabel !== label) {
          geoState.detailPath.push(label);
        }
      }
      updateDetailBreadcrumb();
    }

    function resetDetailState() {
      geoState.detailHistory = ['world'];
      geoState.detailPath = ['世界'];
      geoState.detailLevel = 'world';
      geoState.selectedCountry = '';
      geoState.selectedRegionBand = '';
      geoState.selectedPrefecture = '';
      geoState.selectedPrefCode = '';
      updateDetailBreadcrumb();
    }

    function setupGeoVisibilityWatcher() {
      if (!geoPanelCard || typeof IntersectionObserver !== 'function') {
        return;
      }
      const observer = new IntersectionObserver((entries) => {
        const entry = entries && entries[0];
        geoState.panelVisible = !!(entry && entry.isIntersecting);
        geoPanelCard.classList.toggle('paused', !geoState.panelVisible);
      }, { threshold: 0.1 });
      observer.observe(geoPanelCard);
      document.addEventListener('visibilitychange', () => {
        geoPanelCard.classList.toggle('paused', document.hidden || !geoState.panelVisible);
      });
    }

    function projectWorldPoint(latitude, longitude) {
      const width = 960;
      const height = 460;
      const x = ((longitude + 180) / 360) * width;
      const y = ((90 - latitude) / 180) * height;
      return { x, y };
    }

    function projectJapanPoint(latitude, longitude) {
      const minLon = 122;
      const maxLon = 154;
      const minLat = 24;
      const maxLat = 46;
      if (longitude < minLon || longitude > maxLon || latitude < minLat || latitude > maxLat) {
        return null;
      }
      const width = 960;
      const height = 460;
      const x = ((longitude - minLon) / (maxLon - minLon)) * width;
      const y = ((maxLat - latitude) / (maxLat - minLat)) * height;
      return { x, y };
    }

    function drawMapSvg(svgElement, features, projectionMode, options = {}) {
      if (!svgElement || !Array.isArray(features)) {
        return;
      }
      const pathParts = [];
      const lineParts = [];

      const project = projectionMode === 'japan' ? projectJapanPoint : projectWorldPoint;
      const highlightPref = normalizePrefName(options.highlightPrefecture || '');
      const regionBand = options.regionBand || '';

      function ringToPath(ring) {
        const points = [];
        ring.forEach((coord) => {
          const lon = Number(coord[0]);
          const lat = Number(coord[1]);
          if (!Number.isFinite(lon) || !Number.isFinite(lat)) {
            return;
          }
          const p = project(lat, lon);
          if (!p) {
            return;
          }
          points.push(p);
        });
        if (points.length < 2) {
          return '';
        }
        return `M${points[0].x.toFixed(2)},${points[0].y.toFixed(2)} ` + points.slice(1).map((p) => `L${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' ') + ' Z';
      }

      function geometryPath(geometry) {
        if (!geometry) {
          return '';
        }
        const segments = [];
        if (geometry.type === 'Polygon') {
          (geometry.coordinates || []).forEach((ring) => {
            const d = ringToPath(ring);
            if (d) {
              segments.push(d);
            }
          });
        } else if (geometry.type === 'MultiPolygon') {
          (geometry.coordinates || []).forEach((poly) => {
            (poly || []).forEach((ring) => {
              const d = ringToPath(ring);
              if (d) {
                segments.push(d);
              }
            });
          });
        }
        return segments.join(' ');
      }

      features.forEach((feature) => {
        const geometry = feature && feature.geometry;
        const d = geometryPath(geometry);
        if (!d) {
          return;
        }

        if (projectionMode === 'japan') {
          const code = Number(feature.id);
          const prefName = PREF_CODE_TO_NAME[code] || '';
          const isEast = EAST_PREF_SET.has(prefName);
          const inBand = regionBand ? ((regionBand === '東日本' && isEast) || (regionBand === '西日本' && WEST_PREF_SET.has(prefName))) : true;
          const isHighlight = highlightPref && prefName === highlightPref;
          const fillClass = isHighlight ? 'geo-map-land focus' : (inBand ? 'geo-map-land' : 'geo-map-land muted');
          pathParts.push(`<path class="${fillClass}" data-pref-code="${code}" data-pref-name="${prefName}" d="${d}"></path>`);
          lineParts.push(`<path class="geo-map-border" d="${d}"></path>`);
        } else {
          pathParts.push(`<path class="geo-map-land" d="${d}"></path>`);
          lineParts.push(`<path class="geo-map-border" d="${d}"></path>`);
        }
      });

      const width = 960;
      const height = 460;
      const graticules = [
        `<path class="geo-map-grid" d="M0 ${height / 2} L${width} ${height / 2}"></path>`,
        `<path class="geo-map-grid" d="M${width / 4} 0 L${width / 4} ${height}"></path>`,
        `<path class="geo-map-grid" d="M${width / 2} 0 L${width / 2} ${height}"></path>`,
        `<path class="geo-map-grid" d="M${(width * 3) / 4} 0 L${(width * 3) / 4} ${height}"></path>`,
      ];

      const labels = projectionMode === 'world'
        ? [
            { name: 'Tokyo', lat: 35.68, lon: 139.76 },
            { name: 'London', lat: 51.51, lon: -0.13 },
            { name: 'New York', lat: 40.71, lon: -74.0 },
            { name: 'Sydney', lat: -33.86, lon: 151.21 },
          ]
        : [
            { name: '札幌', lat: 43.06, lon: 141.35 },
            { name: '東京', lat: 35.68, lon: 139.76 },
            { name: '名古屋', lat: 35.18, lon: 136.91 },
            { name: '大阪', lat: 34.69, lon: 135.50 },
            { name: '福岡', lat: 33.59, lon: 130.40 },
          ];
      const labelMarkup = labels
        .map((item) => {
          const p = project(item.lat, item.lon);
          if (!p) {
            return '';
          }
          return `<text class="geo-map-city" x="${p.x.toFixed(1)}" y="${(p.y - 4).toFixed(1)}">${item.name}</text>`;
        })
        .join('');

      svgElement.innerHTML = [
        '<rect class="geo-map-sea" x="0" y="0" width="960" height="460"></rect>',
        ...graticules,
        ...pathParts,
        ...lineParts,
        labelMarkup,
      ].join('');
    }

    function applyJapanViewBox(level, prefCode = '') {
      if (!japanMapSvg) {
        return;
      }
      japanMapSvg.style.transition = 'all 220ms ease';
      if (level === 'world' || level === 'country') {
        japanMapSvg.setAttribute('viewBox', '0 0 960 460');
        return;
      }
      if (level === 'east-west') {
        if (geoState.selectedRegionBand === '東日本') {
          japanMapSvg.setAttribute('viewBox', '380 20 560 380');
        } else if (geoState.selectedRegionBand === '西日本') {
          japanMapSvg.setAttribute('viewBox', '120 80 620 340');
        } else {
          japanMapSvg.setAttribute('viewBox', '0 0 960 460');
        }
        return;
      }
      if (level === 'prefecture') {
        const node = japanMapSvg.querySelector(`[data-pref-code="${prefCode}"]`);
        if (node && typeof node.getBBox === 'function') {
          const box = node.getBBox();
          const padX = Math.max(40, box.width * 0.8);
          const padY = Math.max(30, box.height * 0.8);
          const x = Math.max(0, box.x - padX);
          const y = Math.max(0, box.y - padY);
          const w = Math.min(960 - x, box.width + (padX * 2));
          const h = Math.min(460 - y, box.height + (padY * 2));
          japanMapSvg.setAttribute('viewBox', `${x.toFixed(1)} ${y.toFixed(1)} ${Math.max(120, w).toFixed(1)} ${Math.max(90, h).toFixed(1)}`);
          return;
        }
      }
      japanMapSvg.setAttribute('viewBox', '0 0 960 460');
    }

    function renderDetailMap() {
      if (!geoState.japanReady) {
        return;
      }

      if (geoState.selectedCountry && geoState.selectedCountry !== 'Japan') {
        drawMapSvg(japanMapSvg, geoState.worldFeatures, 'world');
        applyJapanViewBox('country');
        japanMapOutside.classList.add('show');
        return;
      }

      drawMapSvg(japanMapSvg, geoState.japanFeatures, 'japan', {
        regionBand: geoState.detailLevel === 'east-west' ? geoState.selectedRegionBand : '',
        highlightPrefecture: geoState.selectedPrefecture,
      });
      applyJapanViewBox(geoState.detailLevel, geoState.selectedPrefCode);
      japanMapOutside.classList.remove('show');
    }

    function isJapanCountryName(country) {
      const value = String(country || '').trim().toLowerCase();
      return value === 'japan' || value === '日本';
    }

    function resolveRegionBandFromPref(prefName) {
      const normalized = normalizePrefName(prefName);
      if (!normalized) {
        return '';
      }
      if (EAST_PREF_SET.has(normalized)) {
        return '東日本';
      }
      if (WEST_PREF_SET.has(normalized)) {
        return '西日本';
      }
      return '';
    }

    async function initializeGeoMaps() {
      if (geoState.worldReady && geoState.japanReady) {
        return;
      }
      try {
        const [worldRes, japanRes] = await Promise.all([
          fetch('/site/maps/world-110m.topojson'),
          fetch('/site/maps/japan.topojson'),
        ]);
        const worldTopo = await worldRes.json();
        const japanTopo = await japanRes.json();
        const worldFeatures = window.topojson.feature(worldTopo, worldTopo.objects.countries).features;
        const japanFeatures = window.topojson.feature(japanTopo, japanTopo.objects.japan).features;
        geoState.worldFeatures = worldFeatures;
        geoState.japanFeatures = japanFeatures;
        drawMapSvg(worldMapSvg, worldFeatures, 'world');
        drawMapSvg(japanMapSvg, japanFeatures, 'japan');
        geoState.worldReady = true;
        geoState.japanReady = true;
        resetDetailState();
        updateDetailBreadcrumb();
      } catch (e) {
        geoStatus.textContent = '地図データを読み込めませんでした。';
      }
    }

    function attachGeoMapInteractions() {
      if (worldMapMarker) {
        worldMapMarker.addEventListener('click', () => {
          if (!geoState.targetCoord) {
            return;
          }
          const selectedCountry = geoState.selectedCountry || '';
          if (!selectedCountry) {
            return;
          }
          if (isJapanCountryName(selectedCountry)) {
            geoState.detailLevel = 'country';
            pushDetailState('country', '日本');
            const band = geoState.selectedRegionBand || resolveRegionBandFromPref(geoState.selectedPrefecture);
            if (band) {
              geoState.selectedRegionBand = band;
              pushDetailState('east-west', band);
            }
          } else {
            geoState.detailLevel = 'country';
            pushDetailState('country', selectedCountry);
          }
          renderDetailMap();
          if (geoState.targetCoord) {
            setGeoMapMarkers(geoState.targetCoord.latitude, geoState.targetCoord.longitude, japanMapLabel.textContent);
          }
        });
      }

      if (japanMapSvg) {
        japanMapSvg.addEventListener('click', (event) => {
          const target = event.target;
          if (!target || typeof target.getAttribute !== 'function') {
            return;
          }
          const prefCode = target.getAttribute('data-pref-code');
          const prefName = target.getAttribute('data-pref-name');
          if (!prefCode || !prefName || !isJapanCountryName(geoState.selectedCountry || '')) {
            return;
          }
          const band = resolveRegionBandFromPref(prefName);
          if (band) {
            geoState.selectedRegionBand = band;
            if (geoState.detailLevel !== 'east-west') {
              pushDetailState('east-west', band);
            }
          }
          geoState.selectedPrefecture = prefName;
          geoState.selectedPrefCode = prefCode;
          pushDetailState('prefecture', prefName);
          renderDetailMap();
          if (geoState.targetCoord) {
            setGeoMapMarkers(geoState.targetCoord.latitude, geoState.targetCoord.longitude, japanMapLabel.textContent);
          }
        });
      }
    }

    function setMapMarker(marker, wave, label, projectedPoint, labelText, hide = false) {
      if (!marker || !wave || !label) {
        return;
      }
      if (hide || !projectedPoint) {
        marker.classList.add('hidden');
        wave.classList.add('hidden');
        label.textContent = labelText || '—';
        return;
      }
      marker.classList.remove('hidden');
      wave.classList.remove('hidden');
      const frame = marker.parentElement;
      const frameWidth = frame ? (frame.clientWidth || 960) : 960;
      const frameHeight = frame ? (frame.clientHeight || 460) : 460;
      const left = (projectedPoint.x / 960) * frameWidth;
      const top = (projectedPoint.y / 460) * frameHeight;
      marker.style.left = `${left}px`;
      marker.style.top = `${top}px`;
      wave.style.left = `${left}px`;
      wave.style.top = `${top}px`;
      label.textContent = labelText || '—';
    }

    function setGeoMapMarkers(latitude, longitude, labelText) {
      if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) {
        setMapMarker(worldMapMarker, worldMapWave, worldMapLabel, null, '座標なし', true);
        setMapMarker(japanMapMarker, japanMapWave, japanMapLabel, null, '座標なし', true);
        japanMapOutside.classList.remove('show');
        return;
      }

      const worldPoint = projectWorldPoint(latitude, longitude);
      const japanPoint = projectJapanPoint(latitude, longitude);
      setMapMarker(worldMapMarker, worldMapWave, worldMapLabel, worldPoint, labelText || `${formatLatLon(latitude)}, ${formatLatLon(longitude)}`);

      if (!japanPoint) {
        setMapMarker(japanMapMarker, japanMapWave, japanMapLabel, null, '日本国外', true);
        japanMapOutside.classList.add('show');
      } else {
        japanMapOutside.classList.remove('show');
        setMapMarker(japanMapMarker, japanMapWave, japanMapLabel, japanPoint, labelText || `${formatLatLon(latitude)}, ${formatLatLon(longitude)}`);
      }
    }

    function buildGeoRequestKey(params) {
      const keys = Object.keys(params || {}).sort();
      return keys.map((key) => `${key}:${params[key]}`).join('|');
    }

    function renderGeoPanel(payload, requestMode = geoState.mode) {
      const location = getPathValue(payload, ['location'], {});
      const weather = getPathValue(payload, ['weather'], {});
      const status = getPathValue(payload, ['status'], 'error');
      const mode = normalizeMode(location.mode || requestMode);

      const latitude = Number(location.latitude);
      const longitude = Number(location.longitude);
      const hasCoord = Number.isFinite(latitude) && Number.isFinite(longitude);
      geoState.targetCoord = hasCoord ? { latitude, longitude } : null;
      geoState.selectedCountry = String(location.country || '').trim();

      const prefCandidate = normalizePrefName(location.region || location.city || '');
      geoState.selectedPrefecture = prefCandidate;
      geoState.selectedPrefCode = String(
        Object.keys(PREF_CODE_TO_NAME).find((code) => PREF_CODE_TO_NAME[Number(code)] === prefCandidate) || ''
      );
      geoState.selectedRegionBand = resolveRegionBandFromPref(prefCandidate);

      setGeoMapMarkers(
        hasCoord ? latitude : NaN,
        hasCoord ? longitude : NaN,
        `${location.region || location.city || location.country || '地点不明'}`
      );
      renderDetailMap();

      geoLocationLabel.textContent = location.label || '地点: —';
      const formalAddress = [location.city, location.region, location.country].filter((item) => item && item !== '—').join(', ') || '—';
      geoLocationMeta.textContent = `地域: ${location.region || location.city || '—'} / 国: ${location.country || '—'} / 住所: ${formalAddress}`;
      geoLatLon.textContent = `緯度: ${formatLatLon(location.latitude)} / 経度: ${formatLatLon(location.longitude)}`;
      geoProvider.textContent = `取得元: ${mode === 'device' ? '端末位置' : mode === 'manual' ? '手動' : 'IP推定'} / ${location.provider || '—'}`;
      geoAccuracy.textContent = mode === 'ip' ? '精度: IPによる概算（誤差は不明）' : mode === 'manual' ? '精度: 指定地域の代表地点' : `精度: ${formatAccuracy(location.accuracy_m)}`;
      geoTimezone.textContent = weather.timezone || '—';
      geoLocalTime.textContent = weather.local_time || '—';
      geoWeather.textContent = weather.weather || '—';
      geoTemp.textContent = weather.current_temp || '—';
      geoHumidity.textContent = weather.humidity || '—';
      geoWind.textContent = `${weather.wind_speed || '—'} / ${weather.wind_direction || '—'}`;
      geoObservedAt.textContent = weather.observed_at || '—';
      geoHiLo.textContent = `${weather.high_temp || '—'} / ${weather.low_temp || '—'}`;
      geoRain.textContent = weather.precipitation || '—';
      geoStatus.textContent = payload.message || (status === 'ready' ? '表示中' : '取得に失敗しました。チャットは利用可能です。');

      if (mode === 'manual') {
        const manualLabel = location.region || location.city || location.country || '未設定';
        const representative = geoState.manualResolvedAddress && geoState.manualResolvedAddress.includes('代表地点') ? '（代表地点）' : '';
        locationInput.value = `手動: ${manualLabel}${representative}`;
      } else if (mode === 'device') {
        locationInput.value = `端末位置: ${location.region || location.city || location.country || '現在地'}`;
      } else {
        locationInput.value = `IP推定: ${location.region || location.city || location.country || '不明'}`;
      }
      persistCurrentLocation(locationInput.value.trim());

      if (status === 'ready') {
        setGeoPanelState('ready');
      } else if (status === 'location_failed') {
        setGeoPanelState('error');
      } else {
        setGeoPanelState('loading');
      }
    }

    function readGeoPanelCache() {
      const raw = safeStorageGet(geoPanelCacheKey);
      if (!raw) {
        return null;
      }
      try {
        const parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== 'object') {
          return null;
        }
        const expiresAt = Number(parsed.expires_at || 0);
        if (expiresAt <= Date.now()) {
          return null;
        }
        if ((parsed.request_key || '') !== (geoState.requestKey || '')) {
          return null;
        }
        return parsed.payload || null;
      } catch (e) {
        return null;
      }
    }

    function writeGeoPanelCache(payload, ttlSec) {
      const ttl = Math.max(60, Number(ttlSec || 1800));
      safeStorageSet(
        geoPanelCacheKey,
        JSON.stringify({
          request_key: geoState.requestKey || '',
          payload,
          expires_at: Date.now() + (ttl * 1000),
        })
      );
    }

    function geolocationErrorMessage(error) {
      if (!error || typeof error !== 'object') {
        return '位置情報を取得できませんでした。';
      }
      if (error.code === 1) {
        return '位置情報の利用が拒否されました。';
      }
      if (error.code === 2) {
        return '位置情報を取得できませんでした。電波やネットワークを確認してください。';
      }
      if (error.code === 3) {
        return '位置情報の取得がタイムアウトしました。';
      }
      return error.message || '位置情報を取得できませんでした。';
    }

    async function reverseGeocodeByCoords(latitude, longitude) {
      const url = new URL('https://geocoding-api.open-meteo.com/v1/reverse');
      url.searchParams.set('latitude', String(latitude));
      url.searchParams.set('longitude', String(longitude));
      url.searchParams.set('language', 'ja');
      url.searchParams.set('count', '1');
      url.searchParams.set('format', 'json');

      const response = await fetch(url.toString());
      const data = await response.json();
      const result = (data.results && data.results[0]) || {};
      return {
        city: result.name || '',
        region: result.admin1 || result.admin2 || '',
        country: result.country || '',
      };
    }

    async function geocodeManualRegion(regionName) {
      const text = String(regionName || '').trim();
      if (!text) {
        return [];
      }
      const url = new URL('https://geocoding-api.open-meteo.com/v1/search');
      url.searchParams.set('name', text);
      url.searchParams.set('count', '6');
      url.searchParams.set('language', 'ja');
      url.searchParams.set('format', 'json');

      const response = await fetch(url.toString());
      const data = await response.json();
      const results = Array.isArray(data.results) ? data.results : [];
      return results.map((result) => {
        const city = result.name || text;
        const region = result.admin1 || result.admin2 || '';
        const country = result.country || '';
        const addressParts = [city, region, country].filter(Boolean);
        const featureCode = String(result.feature_code || '').toUpperCase();
        const isRepresentative = featureCode === 'ADM3' || featureCode === 'ADM2' || featureCode === 'ADM1';
        return {
          city,
          region,
          country,
          latitude: Number(result.latitude),
          longitude: Number(result.longitude),
          address: addressParts.join(', '),
          representative: isRepresentative,
        };
      });
    }

    function renderManualCandidates(candidates) {
      if (!geoManualCandidates) {
        return;
      }
      geoManualCandidates.innerHTML = '';
      if (!Array.isArray(candidates) || candidates.length === 0) {
        return;
      }
      const title = document.createElement('div');
      title.className = 'geo-meta';
      title.textContent = '候補を選択してください（自動確定しません）';
      geoManualCandidates.appendChild(title);

      candidates.forEach((candidate, index) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'geo-manual-candidate';
        const name = candidate.city || '名称不明';
        const address = candidate.address || [candidate.region, candidate.country].filter(Boolean).join(', ') || '住所不明';
        const representative = candidate.representative ? '（代表地点）' : '';
        button.innerHTML = `${escapeHtml(name)}${representative}<small>${escapeHtml(address)}</small>`;
        button.addEventListener('click', async () => {
          await confirmManualCandidate(index);
        });
        geoManualCandidates.appendChild(button);
      });
    }

    async function confirmManualCandidate(index) {
      const candidate = Array.isArray(geoState.manualCandidates) ? geoState.manualCandidates[index] : null;
      if (!candidate) {
        return;
      }
      geoState.manualDetails = {
        city: candidate.city || '',
        region: candidate.region || '',
        country: candidate.country || '',
        latitude: Number(candidate.latitude),
        longitude: Number(candidate.longitude),
      };
      geoState.manualResolvedAddress = `${candidate.address || ''}${candidate.representative ? '（代表地点）' : ''}`;
      geoState.manualLock = true;
      geoState.mode = 'manual';
      persistGeoMode('manual');
      if (geoSourceSelect) {
        geoSourceSelect.value = 'manual';
      }
      geoManualCandidates.innerHTML = '';
      clearGeoPanelCache();
      await refreshGeoPanel(true, 'manual');
    }

    function buildGeoQuery(mode, reasonText = '') {
      const selectedMode = normalizeMode(mode || geoState.mode);
      const query = { source: selectedMode };

      if (selectedMode === 'device' && geoState.device) {
        query.lat = String(geoState.device.latitude);
        query.lon = String(geoState.device.longitude);
        query.accuracy = String(geoState.device.accuracy || '');
        query.city = geoState.device.city || '';
        query.region = geoState.device.region || '';
        query.country = geoState.device.country || '';
        query.provider = 'browser_geolocation';
      }

      if (selectedMode === 'manual') {
        query.manual = geoState.manual || '';
        if (geoState.manualDetails) {
          query.lat = String(geoState.manualDetails.latitude);
          query.lon = String(geoState.manualDetails.longitude);
          query.city = geoState.manualDetails.city || '';
          query.region = geoState.manualDetails.region || '';
          query.country = geoState.manualDetails.country || '';
          query.provider = 'manual_geocode';
        }
      }

      if (selectedMode === 'ip' && reasonText) {
        query.reason = reasonText;
      }

      return query;
    }

    async function refreshGeoPanel(force = false, mode = geoState.mode, reasonText = '') {
      const normalizedMode = normalizeMode(mode || geoState.mode);
      if (geoState.manualLock && normalizedMode !== 'manual') {
        return;
      }
      await initializeGeoMaps();
      const requestSeq = (geoState.requestSeq || 0) + 1;
      geoState.requestSeq = requestSeq;
      const query = buildGeoQuery(normalizedMode, reasonText);
      geoState.requestKey = buildGeoRequestKey(query);
      if (!force) {
        const cached = readGeoPanelCache();
        if (cached) {
          if (requestSeq < geoState.requestSeq) {
            return;
          }
          geoState.appliedSeq = requestSeq;
          renderGeoPanel(cached, normalizedMode);
          return;
        }
      }

      setGeoPanelState('loading');
      geoStatus.textContent = '取得中...';
      try {
        const url = new URL('/panel/location-weather', window.location.origin);
        Object.entries(query).forEach(([key, value]) => {
          if (value != null && String(value).trim() !== '') {
            url.searchParams.set(key, String(value));
          }
        });

        const res = await fetch(url.toString());
        const data = await res.json();
        if (requestSeq < geoState.requestSeq) {
          return;
        }
        geoState.appliedSeq = requestSeq;
        renderGeoPanel(data || {}, normalizedMode);
        writeGeoPanelCache(data || {}, Number(getPathValue(data, ['next_refresh_sec'], 1800)));
        appendRuntimeLog(`location ${normalizeMode(normalizedMode)}: ${getPathValue(data, ['location', 'region'], '—') || '—'}`);
      } catch (e) {
        if (requestSeq < geoState.requestSeq) {
          return;
        }
        geoState.appliedSeq = requestSeq;
        renderGeoPanel({
          status: 'location_failed',
          message: '取得に失敗しました。チャットは利用可能です。',
          location: { label: '現在地: 取得失敗', city: '—', region: '—', country: '—', latitude: null, longitude: null, provider: '—', mode: normalizedMode },
          weather: { weather: '—', current_temp: '—', high_temp: '—', low_temp: '—', precipitation: '—' },
        }, normalizedMode);
        appendRuntimeLog(`location ${normalizeMode(normalizedMode)}: failed`);
      }
    }

    async function applyManualLocation() {
      const manual = (geoManualInput.value || '').trim();
      geoState.manual = manual;
      persistManualRegion(manual);
      geoState.mode = 'manual';
      geoState.manualLock = true;
      persistGeoMode('manual');
      if (geoSourceSelect) {
        geoSourceSelect.value = 'manual';
      }
      geoState.manualDetails = null;
      geoState.manualResolvedAddress = '';
      geoState.manualCandidates = [];
      if (geoManualCandidates) {
        geoManualCandidates.innerHTML = '';
      }

      if (!manual) {
        geoStatus.textContent = '手動地点を入力してください。';
        setGeoMapMarkers(NaN, NaN, '座標未確定');
        return;
      }

      try {
        const candidates = await geocodeManualRegion(manual);
        geoState.manualCandidates = candidates;
        if (!candidates.length) {
          geoStatus.textContent = '候補が見つかりません。入力を修正してください。';
          setGeoMapMarkers(NaN, NaN, '座標未確定');
          renderManualCandidates([]);
          return;
        }
        if (candidates.length === 1) {
          await confirmManualCandidate(0);
          geoStatus.textContent = '手動地点を確定しました。';
          return;
        }
        renderManualCandidates(candidates);
        geoStatus.textContent = '候補から地点を選択してください。';
        setGeoMapMarkers(NaN, NaN, '座標未確定');
        return;
      } catch (e) {
        geoState.manualDetails = null;
        geoState.manualCandidates = [];
        geoStatus.textContent = '手動地点の検索に失敗しました。';
        setGeoMapMarkers(NaN, NaN, '座標未確定');
        return;
      }
    }

    async function requestDeviceLocation() {
      geoState.manualLock = false;
      if (!navigator.geolocation) {
        const reason = 'このブラウザは位置情報APIに対応していません。IP推定に切り替えます。';
        geoState.mode = 'ip';
        persistGeoMode('ip');
        if (geoSourceSelect) {
          geoSourceSelect.value = 'ip';
        }
        clearGeoPanelCache();
        await refreshGeoPanel(true, 'ip', reason);
        appendRuntimeLog('device location unsupported -> ip');
        return;
      }

      if (!window.isSecureContext && window.location.hostname !== 'localhost') {
        const reason = 'この接続（LAN内HTTP）は位置情報取得が制限される場合があります。IP推定に切り替えます。';
        geoState.mode = 'ip';
        persistGeoMode('ip');
        if (geoSourceSelect) {
          geoSourceSelect.value = 'ip';
        }
        clearGeoPanelCache();
        await refreshGeoPanel(true, 'ip', reason);
        appendRuntimeLog('device location blocked on insecure context -> ip');
        return;
      }

      setGeoPanelState('loading');
      geoStatus.textContent = '端末位置を取得中...';
      navigator.geolocation.getCurrentPosition(
        async (position) => {
          const latitude = Number(position.coords.latitude);
          const longitude = Number(position.coords.longitude);
          const accuracy = Number(position.coords.accuracy);
          const place = { city: '', region: '', country: '' };
          try {
            const resolved = await reverseGeocodeByCoords(latitude, longitude);
            place.city = resolved.city || '';
            place.region = resolved.region || '';
            place.country = resolved.country || '';
          } catch (e) {
          }

          geoState.device = {
            latitude,
            longitude,
            accuracy,
            city: place.city,
            region: place.region,
            country: place.country,
          };
          geoState.mode = 'device';
          persistGeoMode('device');
          if (geoSourceSelect) {
            geoSourceSelect.value = 'device';
          }

          clearGeoPanelCache();
          await refreshGeoPanel(true, 'device');
          appendRuntimeLog('device location: success');
        },
        async (error) => {
          if (geoState.manualLock) {
            geoStatus.textContent = geolocationErrorMessage(error);
            return;
          }
          const reason = `${geolocationErrorMessage(error)} LAN内HTTPではブラウザ制限で失敗することがあります。`;
          geoState.mode = 'ip';
          persistGeoMode('ip');
          if (geoSourceSelect) {
            geoSourceSelect.value = 'ip';
          }
          clearGeoPanelCache();
          await refreshGeoPanel(true, 'ip', reason);
          appendRuntimeLog('device location denied/failed -> ip');
        },
        { enableHighAccuracy: true, timeout: 7000, maximumAge: 30000 }
      );
    }

    function escapeHtml(text) {
      return String(text || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    function linkifyText(text) {
      const escaped = escapeHtml(text);
      const urlPattern = new RegExp('(https?://[^\\\\s<]+)', 'g');
      return escaped.replace(urlPattern, (url) => `<a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a>`);
    }

    function addBubble(role, text) {
      const el = document.createElement('div');
      el.className = `bubble ${role}`;
      const rawText = String(text || '');

      const copyIconSvg = [
        '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">',
        '<rect x="9" y="9" width="11" height="11" rx="2"></rect>',
        '<rect x="4" y="4" width="11" height="11" rx="2"></rect>',
        '</svg>',
      ].join('');
      const copiedIconSvg = [
        '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">',
        '<path d="M5 12.5l4.2 4.2L19 7.5"></path>',
        '</svg>',
      ].join('');

      if (role === 'user' || role === 'assistant') {
        const head = document.createElement('div');
        head.className = 'bubble-head';
        const copyBtn = document.createElement('button');
        copyBtn.type = 'button';
        copyBtn.className = 'bubble-copy-btn';
        copyBtn.innerHTML = copyIconSvg;
        copyBtn.setAttribute('aria-label', '全文をコピー');
        copyBtn.setAttribute('title', '全文をコピー');
        copyBtn.addEventListener('click', async () => {
          try {
            if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
              await navigator.clipboard.writeText(rawText);
            } else {
              const area = document.createElement('textarea');
              area.value = rawText;
              document.body.appendChild(area);
              area.select();
              document.execCommand('copy');
              document.body.removeChild(area);
            }
            copyBtn.classList.add('is-copied');
            copyBtn.innerHTML = copiedIconSvg;
            setTimeout(() => {
              copyBtn.classList.remove('is-copied');
              copyBtn.innerHTML = copyIconSvg;
            }, 1500);
          } catch (e) {
          }
        });
        head.appendChild(copyBtn);
        el.appendChild(head);
      }

      const body = document.createElement('div');
      body.innerHTML = linkifyText(rawText).split(String.fromCharCode(10)).join('<br>');
      el.appendChild(body);
      chatLog.appendChild(el);
      chatLog.scrollTop = chatLog.scrollHeight;
      return el;
    }

    function showEvaluation(evaluation) {
      if (!evaluation || typeof evaluation !== 'object') {
        return;
      }

      const requestId = evaluation.request_id || '';
      const route = evaluation.route || '不明';
      const responseTime = Number(evaluation.response_time_sec || 0).toFixed(2);
      const apiLabel = evaluation.api_called ? 'あり' : 'なし';
      const savedCost = Number(evaluation.saved_cost_yen || 0).toFixed(4);
      const reductionRate = Number(evaluation.cloud_api_call_reduction_rate || evaluation.api_reduction_rate || 0).toFixed(1);
      runtimeRoute.textContent = route || '—';
      runtimeLatency.textContent = `${responseTime}秒`;
      runtimeCloud.textContent = evaluation.api_called ? '使用あり' : '未使用';
      appendRuntimeLog(`route=${route} / ${responseTime}秒 / cloud=${evaluation.api_called ? 'on' : 'off'}`);
      const lines = [
        `処理経路：${route}`,
        `応答時間：${responseTime}秒`,
        `API使用：${apiLabel}`,
        `今回の推定削減額：${savedCost}円`,
        `累計クラウドAPI呼出削減率：${reductionRate}％`,
      ];

      const wrap = document.createElement('details');
      wrap.className = 'evaluation-wrap';
      const summary = document.createElement('summary');
      summary.textContent = '回答の評価・API使用の詳細';
      wrap.appendChild(summary);

      const body = document.createElement('div');
      body.className = 'meta-line';
      body.textContent = lines.join(String.fromCharCode(10));
      wrap.appendChild(body);

      if (requestId) {
        const actionTitle = document.createElement('div');
        actionTitle.className = 'choice-title';
        actionTitle.textContent = '回答品質評価';
        wrap.appendChild(actionTitle);

        const actions = document.createElement('div');
        actions.className = 'evaluation-actions';

        const options = [
          { label: '良い', value: 'good' },
          { label: '一部修正', value: 'partial' },
          { label: '悪い', value: 'bad' },
        ];

        const status = document.createElement('div');
        status.className = 'meta-line';
        status.textContent = `request_id: ${requestId}`;
        wrap.appendChild(status);

        options.forEach((option) => {
          const button = document.createElement('button');
          button.type = 'button';
          button.className = 'secondary';
          button.textContent = option.label;
          button.addEventListener('click', async () => {
            button.disabled = true;
            status.textContent = `request_id: ${requestId} | 評価を送信中...`;
            try {
              const res = await fetch('/evaluation/feedback', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ request_id: requestId, rating: option.value }),
              });
              const data = await res.json();
              if (!data.ok) {
                throw new Error(data.error || 'feedback failed');
              }
              status.textContent = `request_id: ${requestId} | 評価: ${option.label} を保存しました`;
              actions.querySelectorAll('button').forEach((btn) => {
                btn.disabled = true;
              });
            } catch (error) {
              status.textContent = `request_id: ${requestId} | 評価保存に失敗しました`;
              actions.querySelectorAll('button').forEach((btn) => {
                btn.disabled = false;
              });
            }
          });
          actions.appendChild(button);
        });

        wrap.appendChild(actions);
      }

      chatLog.appendChild(wrap);
      chatLog.scrollTop = chatLog.scrollHeight;
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

      if (ui.description) {
        const description = document.createElement('div');
        description.className = 'choice-title';
        description.textContent = ui.description;
        wrap.appendChild(description);
      }

      const grid = document.createElement('div');
      grid.className = 'choice-grid';
      wrap.appendChild(grid);

      ui.options.forEach((option) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'choice-btn';
        const label = document.createElement('div');
        label.textContent = option.label || option.message || '選択';
        btn.appendChild(label);
        if (option.description) {
          const meta = document.createElement('div');
          meta.className = 'template-item-meta';
          meta.textContent = option.description;
          btn.appendChild(meta);
        }
        btn.addEventListener('click', () => {
          messageInput.value = option.message || option.label || '';
          messageInput.focus();
          if ((ui.interaction || option.interaction || '').toLowerCase() === 'send') {
            sendMessage();
          }
        });
        grid.appendChild(btn);
      });

      chatLog.appendChild(wrap);
      chatLog.scrollTop = chatLog.scrollHeight;
    }

    function addPromptInputPanel(ui) {
      if (!ui || !ui.type || ui.type !== 'prompt_input') {
        return;
      }

      const wrap = document.createElement('div');
      wrap.className = 'choice-wrap';

      const title = document.createElement('div');
      title.className = 'choice-title';
      title.textContent = ui.title || '入力してください';
      wrap.appendChild(title);

      if (ui.description) {
        const desc = document.createElement('div');
        desc.className = 'template-item-meta';
        desc.textContent = ui.description;
        wrap.appendChild(desc);
      }

      const row = document.createElement('div');
      row.className = 'row';
      row.style.marginTop = '8px';

      const input = document.createElement('input');
      input.type = 'text';
      input.placeholder = ui.placeholder || '入力してください';
      input.style.flex = '1';
      input.value = '';
      row.appendChild(input);

      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'secondary';
      btn.textContent = ui.button_label || '再演算';
      btn.addEventListener('click', () => {
        const value = input.value.trim();
        if (!value) {
          input.focus();
          return;
        }
        const finalText = (ui.template || '{value}').replace('{value}', value);
        messageInput.value = finalText;
        messageInput.focus();
        sendMessage();
      });
      row.appendChild(btn);
      wrap.appendChild(row);

      chatLog.appendChild(wrap);
      chatLog.scrollTop = chatLog.scrollHeight;
    }

    let documentCache = [];
    let currentDocumentId = '';
    let documentDraftMode = true;

    function applyTemplate(templateText) {
      messageInput.value = templateText || '';
      messageInput.focus();
    }

    function renderCapabilityTemplates(templates) {
      capabilityTemplateList.innerHTML = '';
      if (!Array.isArray(templates) || templates.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'doc-empty';
        empty.textContent = 'テンプレートを取得できませんでした。';
        capabilityTemplateList.appendChild(empty);
        return;
      }

      templates.forEach((item) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'template-item';

        const title = document.createElement('div');
        title.className = 'template-item-title';
        title.textContent = item.title || '無題';
        button.appendChild(title);

        const summary = document.createElement('div');
        summary.className = 'template-item-meta';
        summary.textContent = item.summary || '説明なし';
        button.appendChild(summary);

        const example = document.createElement('div');
        example.className = 'template-item-meta';
        example.textContent = `テンプレート: ${item.template || ''}`;
        button.appendChild(example);

        button.addEventListener('click', () => {
          applyTemplate(item.template || '');
        });

        capabilityTemplateList.appendChild(button);
      });
    }

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
        documentCurrentCard.textContent = '現在表示中: なし';
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
      const preview = (documentData.preview || documentData.content || '').replace(new RegExp('\\\\s+', 'g'), ' ').trim();
      documentCurrentCard.textContent = `現在表示中: ${documentData.title || '無題'} (${documentData.doc_id || 'IDなし'})` + newline + `概要: ${preview ? preview.slice(0, 80) : '本文なし'}`;
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

        const currentSessionDocId = getPathValue(data, ['session', 'current_doc_id'], '');
        const currentDoc = currentSessionDocId
          ? documentCache.find((item) => item.doc_id === currentSessionDocId)
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
        const savedDocId = getPathValue(data, ['document', 'doc_id'], '');
        await refreshDocuments(savedDocId || currentDocumentId);
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
      const urls = getPathValue(meta, ['server', 'open_urls'], []);
      const localIp = getPathValue(meta, ['server', 'local_ip'], 'unknown');
      const modelName = getPathValue(meta, ['local_llm', 'model'], 'unknown');
      const firstUrl = urls[0] || `${window.location.origin}/`;
      const newline = String.fromCharCode(10);
      serverUrlChip.textContent = `url: ${firstUrl}`;
      serverIpChip.textContent = `ip: ${localIp}`;
      runtimeModel.textContent = modelName || '—';
      metaCard.textContent = `PCのURL: ${firstUrl}` + newline + `ローカルIP: ${localIp}` + newline + `Ollama: ${modelName}` + newline;
    }

    async function refreshHealth() {
      try {
        const res = await fetch('/health');
        const data = await res.json();
        const modelName = getPathValue(data, ['ollama', 'model_configured'], data.model || 'unknown');
        setStatus(`health: ${data.status} | model: ${modelName}`);
        runtimeConnection.textContent = data.status || '—';
        runtimeModel.textContent = modelName || '—';
      } catch (e) {
        setStatus('health: offline');
        runtimeConnection.textContent = 'offline';
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

    async function refreshStorage() {
      try {
        const res = await fetch('/storage');
        const data = await res.json();
        if (!data || !data.ok) {
          throw new Error('storage unavailable');
        }

        const dbPath = getPathValue(data, ['paths', 'documents_db'], 'unknown');
        const dbRows = getPathValue(data, ['counts', 'documents_db_rows'], 0);
        const docItems = getPathValue(data, ['counts', 'document_items'], 0);
        const repaired = getPathValue(data, ['db_repaired_rows'], 0);
        const newline = String.fromCharCode(10);
        storageCard.textContent = `DB: ${dbPath}` + newline + `DB行数: ${dbRows} | 文書件数: ${docItems}` + newline + `自己修復: ${repaired}行`;
      } catch (e) {
        storageCard.textContent = 'DB状態を取得できませんでした。';
      }
    }

    async function refreshCapabilities() {
      try {
        const res = await fetch('/capabilities');
        const data = await res.json();
        if (!data || !data.ok) {
          throw new Error('capabilities unavailable');
        }

        capabilityGuide.textContent = '選ぶと入力欄にテンプレートを入れます。必要なら少し直して送信してください。';
        renderCapabilityTemplates(data.templates || []);
      } catch (e) {
        capabilityGuide.textContent = 'テンプレート一覧を取得できませんでした。';
        renderCapabilityTemplates([]);
      }
    }

    let isSending = false;
    let queuedMessage = '';

    async function sendMessage() {
      const text = messageInput.value.trim();
      const sessionId = sessionInput.value.trim() || savedSessionId;
      const currentLocation = locationInput.value.trim() || savedCurrentLocation;
      if (!text) {
        return;
      }

      if (window.workbench?.busy() && !isSending) return;
      if (isSending) {
        queuedMessage = text;
        messageInput.value = text;
        return;
      }

      sessionInput.value = sessionId;
      safeStorageSet(storageKey, sessionId);
      persistCurrentLocation(currentLocation);
      sessionText.textContent = sessionId;

      isSending = true;
      sendBtn.disabled = true;
      runtimeProcessing.textContent = '処理中';
      window.aiCore.setState('thinking');
      addBubble('user', text);
      messageInput.value = '';

      const typing = addBubble('system', 'thinking...');

      try {
        const data = await window.dashboardRequest({ message: text, session_id: sessionId, current_location: currentLocation });
        typing.remove();
        if (data.ok) {
          addBubble('assistant', data.response);
          window.workbench.complete(data);
          if (window.workbench.succeeded(data)) window.aiCore.answer(data.response, data.evaluation);
          else window.aiCore.setState('error');
          showEvaluation(data.evaluation);
          appendRuntimeLog(`message ok: ${text.slice(0, 36)}`);
          if (data.ui) {
            if (data.ui.type === 'prompt_input') {
              addPromptInputPanel(data.ui);
            } else {
              addChoicePanel(data.ui);
            }
          }
          await refreshDocuments();
        } else {
          addBubble('assistant', data.error || 'error');
          window.aiCore.setState('error');
          window.workbench.complete(data);
          showEvaluation(data.evaluation);
          appendRuntimeLog(`message error: ${String(data.error || 'error').slice(0, 36)}`);
        }
      } catch (e) {
        typing.remove();
        window.aiCore.setState('error');
        window.workbench.fail();
        const detail = e && e.message ? ` (${e.message})` : '';
        addBubble('assistant', `通信に失敗しました。${detail}`);
        appendRuntimeLog(`network error${detail}`);
      } finally {
        isSending = false;
        runtimeProcessing.textContent = '待機中';

        if (queuedMessage) {
          const nextText = queuedMessage;
          queuedMessage = '';
          messageInput.value = nextText;
          sendBtn.disabled = true;
          setTimeout(() => {
            if (!messageInput.value.trim()) {
              messageInput.value = nextText;
            }
            sendMessage();
          }, 0);
          return;
        }

        sendBtn.disabled = false;
        messageInput.focus();
      }
    }

    sendBtn.addEventListener('click', sendMessage);
    capabilityRefreshBtn.addEventListener('click', () => refreshCapabilities());
    documentNewBtn.addEventListener('click', clearDocumentSelection);
    documentRefreshBtn.addEventListener('click', () => refreshDocuments());
    documentSaveBtn.addEventListener('click', saveDocument);
    documentDeleteBtn.addEventListener('click', deleteDocument);
    documentClearBtn.addEventListener('click', clearDocumentSelection);
    geoFetchBtn.addEventListener('click', () => {
      requestDeviceLocation();
    });
    geoManualApplyBtn.addEventListener('click', () => {
      applyManualLocation();
    });
    geoManualInput.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        applyManualLocation();
      }
    });
    geoSourceSelect.addEventListener('change', async () => {
      const mode = normalizeMode(geoSourceSelect.value);
      geoState.mode = mode;
      if (mode !== 'manual') {
        geoState.manualLock = false;
      }
      persistGeoMode(mode);

      if (mode === 'device') {
        await requestDeviceLocation();
        return;
      }

      if (mode === 'manual') {
        await applyManualLocation();
        return;
      }

      clearGeoPanelCache();
      await refreshGeoPanel(true, 'ip');
    });
    geoNavBackBtn.addEventListener('click', () => {
      if (geoState.detailHistory.length <= 1 || geoState.detailPath.length <= 1) {
        return;
      }
      geoState.detailHistory.pop();
      geoState.detailPath.pop();
      geoState.detailLevel = geoState.detailHistory[geoState.detailHistory.length - 1] || 'world';
      if (geoState.detailLevel !== 'prefecture') {
        geoState.selectedPrefecture = '';
        geoState.selectedPrefCode = '';
      }
      if (geoState.detailLevel === 'country') {
        geoState.selectedRegionBand = '';
      }
      updateDetailBreadcrumb();
      renderDetailMap();
      if (geoState.targetCoord) {
        setGeoMapMarkers(geoState.targetCoord.latitude, geoState.targetCoord.longitude, japanMapLabel.textContent);
      }
    });
    geoNavHomeBtn.addEventListener('click', () => {
      resetDetailState();
      renderDetailMap();
      if (geoState.targetCoord) {
        setGeoMapMarkers(geoState.targetCoord.latitude, geoState.targetCoord.longitude, japanMapLabel.textContent);
      }
    });
    document.querySelectorAll('.quick-prompt').forEach((button) => {
      button.addEventListener('click', () => {
        messageInput.value = button.dataset.text || '';
        messageInput.focus();
      });
    });
    resetBtn.addEventListener('click', () => {
      safeStorageRemove(storageKey);
      const freshId = makeSessionId();
      safeStorageSet(storageKey, freshId);
      sessionInput.value = freshId;
      sessionText.textContent = freshId;
      chatLog.innerHTML = '';
      addBubble('system', 'session reset');
    });
    messageInput.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
        event.preventDefault();
        sendMessage();
      }
    });
    sessionInput.addEventListener('change', () => {
      const value = sessionInput.value.trim();
      if (value) {
        safeStorageSet(storageKey, value);
        sessionText.textContent = value;
      }
    });
    locationInput.addEventListener('change', () => {
      persistCurrentLocation(locationInput.value.trim());
    });

    setupGeoVisibilityWatcher();
    initializeGeoMaps();
    attachGeoMapInteractions();

    addBubble('system', 'local-only server ready');
    runtimeProcessing.textContent = '待機中';
    runtimeConnection.textContent = '—';
    runtimeRoute.textContent = '—';
    runtimeLatency.textContent = '—';
    runtimeCloud.textContent = '—';
    refreshTokyoClock();
    setInterval(refreshTokyoClock, 1000);
    refreshMeta();
    refreshHealth();
    refreshStorage();
    refreshCapabilities();
    if (geoState.mode === 'device') {
      requestDeviceLocation();
    } else if (geoState.mode === 'manual' && geoState.manual) {
      applyManualLocation();
    } else {
      refreshGeoPanel(false, 'ip');
    }
    refreshDocuments();
    setInterval(refreshHealth, 10000);
    setInterval(refreshMeta, 60000);
    setInterval(refreshStorage, 30000);
    setInterval(() => refreshGeoPanel(true, geoState.mode), 30 * 60 * 1000);
    setInterval(() => refreshDocuments(), 30000);
    window.initDashboard();
    window.initWorkbench();
    messageInput.focus({ preventScroll: true });
  </script>
</body>
</html>
"""


# HTTPリクエストを処理するハンドラ
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

  def _send_csv_text(self, csv_text: str, filename: str = "evaluation_log.csv") -> None:
    body = csv_text.encode("utf-8-sig")
    self.send_response(200)
    self.send_header("Content-Type", "text/csv; charset=utf-8")
    self.send_header("Content-Disposition", f"attachment; filename={filename}")
    self.send_header("Content-Length", str(len(body)))
    self.send_header("Cache-Control", "no-store")
    self.end_headers()
    self.wfile.write(body)

  def _send_file(self, file_path: str) -> None:
    if not os.path.isfile(file_path):
      self._send_json({"ok": False, "error": "not found"}, status=404)
      return

    with open(file_path, "rb") as file:
      body = file.read()

    content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    self.send_response(200)
    self.send_header("Content-Type", content_type)
    self.send_header("Content-Length", str(len(body)))
    self.send_header("Cache-Control", "public, max-age=3600")
    self.end_headers()
    self.wfile.write(body)

  def _send_sse_headers(self) -> None:
    self.send_response(200)
    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
    self.send_header("Cache-Control", "no-cache, no-transform")
    self.send_header("Connection", "close")
    self.close_connection = True
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
    parsed = urlparse(self.path)
    path = parsed.path
    query = parse_qs(parsed.query or "")

    if path == "/" or path == "/index.html":
      self._send_html(HTML_PAGE)
      return

    if path.startswith("/site/maps/"):
      base_dir = os.path.join(os.path.dirname(__file__), "site", "maps")
      target = path.removeprefix("/site/maps/").strip("/")
      if not target or ".." in target:
        self._send_json({"ok": False, "error": "not found"}, status=404)
        return
      file_path = os.path.join(base_dir, target)
      self._send_file(file_path)
      return

    if path in {"/site/dashboard/dashboard.css", "/site/dashboard/dashboard.js", "/site/dashboard/workbench.js"}:
      self._send_file(os.path.join(os.path.dirname(__file__), "site", "dashboard", path.rsplit("/", 1)[-1]))
      return

    if path == '/processing/export.csv':
      session_id = str((query.get('session_id') or [''])[0])
      self._send_csv_text(processing_csv(session_id), filename='processing_timings.csv')
      return

    if path == '/processing/history':
      session_id = str((query.get('session_id') or [''])[0])
      self._send_json({'ok': True, 'records': processing_history(session_id)})
      return

    if path == "/system/metrics":
      try:
        payload = system_monitor.snapshot()
        self._send_json(payload, status=200 if payload.get("ok") else 503)
      except (OSError, RuntimeError):
        self._send_json({"ok": False, "error": "PC情報を取得できませんでした。"}, status=503)
      return

    if path == "/health":
      self._send_json(_health_snapshot())
      return

    if path == "/meta":
      self._send_json(_server_meta())
      return

    if path == "/storage":
      self._send_json(ensure_memory_stores())
      return

    if path == "/capabilities":
      self._send_json(_capabilities_api_payload())
      return

    if path == "/panel/location-weather":
      source = str((query.get("source") or ["ip"])[0] or "ip").strip().lower()
      manual_label = str((query.get("manual") or [""])[0] or "").strip()
      city = str((query.get("city") or [""])[0] or "").strip()
      region = str((query.get("region") or [""])[0] or "").strip()
      country = str((query.get("country") or [""])[0] or "").strip()
      provider = str((query.get("provider") or [""])[0] or "").strip()
      fallback_reason = str((query.get("reason") or [""])[0] or "").strip()

      lat = _to_float_or_none((query.get("lat") or [None])[0])
      lon = _to_float_or_none((query.get("lon") or [None])[0])
      accuracy = _to_float_or_none((query.get("accuracy") or [None])[0])

      location_details = None
      if source == "device":
        location_details = {
          "city": city,
          "region": region,
          "country": country,
          "latitude": lat,
          "longitude": lon,
          "provider": provider or "browser_geolocation",
        }
      elif source == "manual":
        location_details = {
          "city": city or manual_label,
          "region": region,
          "country": country,
          "latitude": lat,
          "longitude": lon,
          "provider": provider or "manual",
        }

      self._send_json(
        _build_location_weather_payload(
          requested_mode=source,
          location_details=location_details,
          manual_label=manual_label,
          accuracy_m=accuracy,
          fallback_reason=fallback_reason,
        )
      )
      return

    if path == "/evaluation/summary":
      self._send_json({"ok": True, "summary": evaluation_metrics.get_summary()})
      return

    if path == "/evaluation/export.csv":
      csv_path = evaluation_metrics.export_csv()
      with open(csv_path, "r", encoding="utf-8-sig") as file:
        self._send_csv_text(file.read(), filename="evaluation_log.csv")
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

    if path not in {"/chat", "/chat/stream", "/sessions/clear", "/documents", "/evaluation/feedback", "/processing/client"}:
      self._send_json({"ok": False, "error": "not found"}, status=404)
      return

    data = self._read_json()
    message = str(data.get("message", ""))
    experiment_mode = str(data.get("experiment_mode", "")).strip() or None
    test_case_id = str(data.get("test_case_id", "")).strip()
    tool_request = data.get("tool_request") if isinstance(data.get("tool_request"), dict) else None

    if path == '/processing/client':
      timings = data.get('timings')
      if not isinstance(timings, dict):
        self._send_json({'ok': False, 'error': 'timings must be an object'}, status=400)
        return
      ok = save_client_timings(str(data.get('request_id') or ''), str(data.get('session_id') or ''), timings)
      self._send_json({'ok': ok}, status=200 if ok else 404)
      return

    if path == "/evaluation/feedback":
      request_id = str(data.get("request_id", "")).strip()
      rating = str(data.get("rating", "")).strip()
      notes = str(data.get("notes", "")).strip()
      if not request_id or rating not in {"good", "partial", "bad"}:
        self._send_json({"ok": False, "error": "request_id and valid rating are required"}, status=400)
        return

      updated = evaluation_metrics.set_user_feedback(request_id, rating=rating, notes=notes)
      if not updated:
        self._send_json({"ok": False, "error": "request_id not found"}, status=404)
        return

      self._send_json({"ok": True, "request_id": request_id, "rating": rating, "summary": evaluation_metrics.get_summary()})
      return

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
    current_location = str(data.get("current_location") or "").strip()

    if path == "/chat/stream":
      self._send_sse_headers()
      for event in _stream_chat_payload(
        message,
        session_id,
        current_location=current_location,
        experiment_mode=experiment_mode,
        test_case_id=test_case_id,
      ):
        self._send_sse_event(event["event"], event["data"])
      return

    if "text/event-stream" in self.headers.get("Accept", ""):
      self._send_sse_headers()
      try:
        for event in _chat_activity_events(message, session_id, current_location=current_location,
                                         experiment_mode=experiment_mode, test_case_id=test_case_id, tool_request=tool_request):
          self._send_sse_event(event["event"], event["data"])
      except (BrokenPipeError, ConnectionResetError):
        pass
      return

    response = _build_chat_payload(
      message,
      session_id,
      current_location=current_location,
      experiment_mode=experiment_mode,
      test_case_id=test_case_id,
      tool_request=tool_request,
    )
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


# 静かなHTTPサーバー設定と起動処理
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

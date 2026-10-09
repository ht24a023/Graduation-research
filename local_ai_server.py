"""ブラウザからの入力を受け、専用機能・ローカルLLM・クラウドAIへ振り分けて応答するHTTPサーバーで、ローカル優先の対話UIを動かします。"""

# ブラウザからの入力を受け、専用機能・ローカルLLM・クラウドAIへ振り分けて応答を返すHTTPサーバーです。会話履歴、入力判定、文書管理、評価記録、画面表示を一体で制御し、ローカル優先の対話UIを動かします。

from __future__ import annotations  # 型注釈の評価を遅らせ、後で定義する型も参照できるようにする

import json       # JSON形式のデータをPythonの値に変換し、その逆の変換も行う
import os         # 環境変数からサーバー設定を読み込む
import re         # 正規表現で入力文の判定や文字列処理を行う
import sys        # 発生中の例外情報を取得する
import threading  # 複数処理から共有データを扱う際のロックに使う
import time       # 処理時間の計測やキャッシュ期限の判定に使う
import socket     # ネットワーク接続に使うPCのIPアドレスを取得する

from collections import deque  # 保存件数に上限を設けられるキューで会話履歴を管理する
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # HTTPリクエスト処理と複数接続対応のサーバーに使う
from typing import Any  # 任意の型の値を受け取ることを型注釈で示す
from urllib.error import HTTPError, URLError  # HTTP応答のエラーや接続エラーを扱う
from urllib.request import Request, urlopen  # HTTPリクエストを作成・送信し、応答を取得する
from urllib.parse import urlparse  # URLを分解し、リクエストのパスを取り出す
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


from cloud.local_llm import ask_local_llm, ask_local_llm_json, stream_local_llm  # ローカルLLMから通常回答・JSON回答・逐次生成の回答を取得する
from cloud.local_prompt import build_local_prompt  # 質問や会話履歴、利用者情報からローカルLLMへの指示文を作る
from cloud.openai_client import ask_cloud_ai  # クラウドAIへ指示文を送り、回答を取得する
from functions.google_workspace import search_google_web, search_google_web_structured  # Google検索の結果を文章形式・構造化データ形式で取得する
from functions.weather import get_weather  # 指定地域などの天気情報を取得する
from models.evaluation_metrics import build_user_facing_evaluation, evaluation_metrics  # 画面用の評価情報を作成し、評価記録の保存・集計を行う


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
def _build_chat_payload(
  message: str,
  session_id: str,
  *,
  current_location: str = "",
  experiment_mode: str | None = None,
  test_case_id: str = "",
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

  if reject_token:
    pending = _pop_pending_api_approval(reject_token)
    if not pending or pending.get("session_id") != session_id:
      return finalize(ok=False, route="error", error="承認待ちのAPI呼び出しが見つかりませんでした。")

    response_text = "承知しました。今回はクラウドAPIを使わず、Google検索結果のみで終了します。"
    _append_turn(session_id, "assistant", response_text)
    return finalize(ok=True, route="local_search", response=response_text)

  # 自動メモリ更新: ユーザー発話から重要情報のみ保存し、削除指示も反映
  update_profile_from_text(effective_message)

  explicit_note_payload = handle_explicit_note_command_with_meta(effective_message)

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

  if explicit_note_payload:
    local_started = time.perf_counter()
    explicit_note_response = str(explicit_note_payload.get("response") or "")
    local_time_sec += time.perf_counter() - local_started
    _append_turn(session_id, "assistant", explicit_note_response)
    response_payload: dict[str, Any] = {}
    if isinstance(explicit_note_payload.get("ui"), dict):
      response_payload["ui"] = explicit_note_payload["ui"]
    return finalize(ok=True, route="local_function", response=explicit_note_response, extra=response_payload)

  intent = classify_intent(effective_message)
  clarification_decision = None
  if not clarification_followup and experiment_mode != "FIXED_ROUTING":
    clarification_decision = _detect_required_clarification(effective_message, history, intent)

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
    response = get_weekday_from_text(effective_message)
    local_time_sec += time.perf_counter() - local_started
    _append_turn(session_id, "assistant", response)
    return finalize(ok=True, route="local_function", response=response)

  if intent == "weekday":
    local_started = time.perf_counter()
    response = get_weekday()
    local_time_sec += time.perf_counter() - local_started
    _append_turn(session_id, "assistant", response)
    return finalize(ok=True, route="local_function", response=response)

  if intent == "time":
    local_started = time.perf_counter()
    response = get_time()
    local_time_sec += time.perf_counter() - local_started
    _append_turn(session_id, "assistant", response)
    return finalize(ok=True, route="local_function", response=response)

  if intent == "calculate" or _looks_like_calculation(effective_message):
    calc_input = clarification_followup[1] if clarification_followup else recompute_message
    local_started = time.perf_counter()
    response = calculate(calc_input)
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
    response = resolve_navigation(
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
    response = get_weather(weather_query, current_location_details=location_details)
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

  if intent == "search":
    local_started = time.perf_counter()
    search_payload = search_google_web_structured(recompute_message)
    local_time_sec += time.perf_counter() - local_started
    if search_payload.get("ok"):
      route_label = str(search_payload.get("route") or "search")
      response_text = _format_structured_search_response(search_payload)
      _append_turn(session_id, "assistant", response_text)
      print(f"route={route_label}")
      return finalize(ok=True, route=route_label, response=response_text, extra={"ui": _build_search_success_ui()})

    fallback_search_result = search_google_web(recompute_message)
    if fallback_search_result and fallback_search_result not in {
      "Google検索結果を取得できませんでした。",
      "入力された文章を日本語へ翻訳できませんでした。日本語で入力し直すか、翻訳を再試行してください。",
    }:
      route_label = "local_search"
      _append_turn(session_id, "assistant", fallback_search_result)
      print(f"route={route_label}")
      return finalize(ok=True, route=route_label, response=fallback_search_result, extra={"ui": _build_search_success_ui()})

    error_type = str(search_payload.get("error_type") or "search_fetch_failed")
    search_failure = "Google検索結果を取得できませんでした。"
    _append_turn(session_id, "assistant", search_failure)
    print("route=search_failed")
    return finalize(ok=True, route="search_failed", response=search_failure, extra={"ui": _build_search_failure_ui(), "error_type": error_type})

  if _looks_like_fact_question(effective_message):
    local_started = time.perf_counter()
    search_payload = search_google_web_structured(recompute_message)
    local_time_sec += time.perf_counter() - local_started
    if search_payload.get("ok"):
      route_label = str(search_payload.get("route") or "search")
      response_text = _format_structured_search_response(search_payload)
      _append_turn(session_id, "assistant", response_text)
      print(f"route={route_label}")
      return finalize(ok=True, route=route_label, response=response_text, extra={"ui": _build_search_success_ui()})

    fallback_search_result = search_google_web(recompute_message)
    if fallback_search_result and fallback_search_result not in {
      "Google検索結果を取得できませんでした。",
      "入力された文章を日本語へ翻訳できませんでした。日本語で入力し直すか、翻訳を再試行してください。",
    }:
      route_label = "local_search"
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

  # DYNAMIC_ROUTING: do not call cloud immediately.
  # First show Google evidence and ask user whether cloud API usage is allowed.
  local_started = time.perf_counter()
  search_payload = search_google_web_structured(message)
  local_time_sec += time.perf_counter() - local_started
  fallback_search_result = search_google_web(message)
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

  update_profile_from_text(message)
  explicit_note_payload = handle_explicit_note_command_with_meta(message)

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
        <span class="chip">/storage</span>
        <span class="chip">/capabilities</span>
        <span class="chip">/evaluation/summary</span>
        <span class="chip">/evaluation/feedback</span>
        <span class="chip">/evaluation/export.csv</span>
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
              <button class="secondary quick-prompt" type="button" data-text="このローカルサーバーでできることを具体例つきで教えて">できること</button>
              <button class="secondary quick-prompt" type="button" data-text="ここから東京駅までの行き方を教えて">ルート</button>
              <button class="secondary quick-prompt" type="button" data-text="(150+230)÷19 を計算して">計算</button>
              <button class="secondary quick-prompt" type="button" data-text="保存してある自己PR文書を一覧で見せて">文書一覧</button>
            </div>
            <textarea id="message" placeholder="メッセージを入力..."></textarea>
            <div class="row">
              <input id="session-id" placeholder="session id" />
              <input id="current-location" placeholder="現在地（任意）" />
              <button id="send-btn" type="button">Send</button>
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
            <div class="card template-manager">
              <div class="doc-manager-header">
                <span class="doc-manager-title">使える処理テンプレート</span>
                <button id="capability-refresh-btn" class="secondary" type="button">更新</button>
              </div>
              <div class="doc-meta" id="capability-guide">このローカルサーバーで実行できる質問テンプレートを表示します。</div>
              <div class="template-list" id="capability-template-list"></div>
            </div>
            <div class="card doc-manager">
              <div class="doc-manager-header">
                <span class="doc-manager-title">保存文書（自己PR）</span>
                <div class="row" style="margin:0;">
                  <button id="document-new-btn" class="secondary" type="button">新規作成</button>
                  <button id="document-refresh-btn" class="secondary" type="button">更新</button>
                </div>
              </div>
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
            <div class="card">Ollama がローカルで起動している必要があります。</div>
            <div class="card">スマホから使う場合は、iPhone の Safari で上の URL を開いてください。</div>
            <div class="card">会話履歴は session id ごとに分けています。</div>
            <div class="card" id="storage-card">DB状態を確認しています。</div>
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

    const storageKey = 'local-ai-session-id';
    const locationStorageKey = 'local-ai-current-location';

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

    function persistCurrentLocation(value) {
      safeStorageSet(locationStorageKey, value || '');
    }

    function refreshBrowserLocation() {
      if (!navigator.geolocation) {
        return;
      }

      navigator.geolocation.getCurrentPosition(
        (position) => {
          const latitude = Number(position.coords.latitude || 0).toFixed(6);
          const longitude = Number(position.coords.longitude || 0).toFixed(6);
          const label = `緯度${latitude} 経度${longitude}`;
          locationInput.value = label;
          persistCurrentLocation(label);
        },
        () => {
        },
        { enableHighAccuracy: true, timeout: 5000, maximumAge: 60000 }
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
      el.innerHTML = linkifyText(text).split(String.fromCharCode(10)).join('<br>');
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
      const lines = [
        `処理経路：${route}`,
        `応答時間：${responseTime}秒`,
        `API使用：${apiLabel}`,
        `今回の推定削減額：${savedCost}円`,
        `累計クラウドAPI呼出削減率：${reductionRate}％`,
      ];

      const wrap = document.createElement('div');
      wrap.className = 'evaluation-wrap';

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
      metaCard.textContent = `PCのURL: ${firstUrl}` + newline + `ローカルIP: ${localIp}` + newline + `Ollama: ${modelName}` + newline;
    }

    async function refreshHealth() {
      try {
        const res = await fetch('/health');
        const data = await res.json();
        const modelName = getPathValue(data, ['ollama', 'model_configured'], data.model || 'unknown');
        setStatus(`health: ${data.status} | model: ${modelName}`);
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
      addBubble('user', text);
      messageInput.value = '';

      const typing = addBubble('system', 'thinking...');

      try {
        const res = await fetch('/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: text, session_id: sessionId, current_location: currentLocation })
        });
        const data = await res.json();
        typing.remove();
        if (data.ok) {
          addBubble('assistant', data.response);
          showEvaluation(data.evaluation);
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
          showEvaluation(data.evaluation);
        }
      } catch (e) {
        typing.remove();
        const detail = e && e.message ? ` (${e.message})` : '';
        addBubble('assistant', `通信に失敗しました。${detail}`);
      } finally {
        isSending = false;

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
      if (event.key === 'Enter' && !event.shiftKey) {
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

    addBubble('system', 'local-only server ready');
    refreshBrowserLocation();
    refreshMeta();
    refreshHealth();
    refreshStorage();
    refreshCapabilities();
    refreshDocuments();
    setInterval(refreshHealth, 10000);
    setInterval(refreshMeta, 60000);
    setInterval(refreshStorage, 30000);
    setInterval(() => refreshDocuments(), 30000);
    messageInput.focus();
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

    if path == "/storage":
      self._send_json(ensure_memory_stores())
      return

    if path == "/capabilities":
      self._send_json(_capabilities_api_payload())
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

    if path not in {"/chat", "/chat/stream", "/sessions/clear", "/documents", "/evaluation/feedback"}:
      self._send_json({"ok": False, "error": "not found"}, status=404)
      return

    data = self._read_json()
    message = str(data.get("message", ""))
    experiment_mode = str(data.get("experiment_mode", "")).strip() or None
    test_case_id = str(data.get("test_case_id", "")).strip()

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

    response = _build_chat_payload(
      message,
      session_id,
      current_location=current_location,
      experiment_mode=experiment_mode,
      test_case_id=test_case_id,
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

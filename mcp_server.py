"""MCP経由で時刻・計算・地図・検索・文書管理を提供するサーバーで、外部ツール連携を可能にします。"""

from __future__ import annotations

from collections import deque
import csv
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import re
import time
from uuid import uuid4

from mcp.server.fastmcp import FastMCP

from cloud.local_llm import ask_local_llm
from cloud.local_policy import is_local_only_request, respond_local_only
from cloud.local_prompt import build_local_prompt
from cloud.openai_client import ask_cloud_ai
from functions.calculator import calculate as calculate_expression
from functions.google_workspace import get_google_maps_directions, search_gmail, search_google_maps, search_google_web, send_gmail
from functions.location import get_current_location as read_current_location
from functions.time_func import get_time as read_time
from functions.transit import resolve_navigation, search_transit, navigate
from functions.weather import get_weather as read_weather
from functions.research_tools import (
    generate_qr_code,
    summarize_web_url,
    translate_text,
    wikipedia_summary,
    youtube_search,
)
from models.text_normalizer import normalize_asr_text
from models.evaluation_metrics import build_user_facing_evaluation, evaluation_metrics
from models.user_profile_memory import build_profile_context, handle_explicit_note_command, update_profile_from_text

MAX_HISTORY_TURNS = 8
ROUTING_LOG_PATH = Path("logs") / "cloud_routing_log.txt"
ROUTING_LOG_CSV_PATH = Path("logs") / "cloud_routing_log.csv"
ROUTING_LOG_CSV_HEADER = ["日時", "入力内容", "判定", "理由", "処理時間ms"]

AVAILABLE_FUNCTIONS = [
    "現在時刻取得",
    "四則演算",
    "会話履歴取得",
    "会話履歴クリア",
    "ルート検索",
    "天気",
    "Wikipedia要約",
    "YouTube検索",
    "QRコード生成",
    "翻訳",
    "URL要約",
]


@dataclass
class ConversationSession:
    turns: deque = field(default_factory=lambda: deque(maxlen=MAX_HISTORY_TURNS))

    def add_user(self, text: str) -> None:
        self.turns.append({"role": "user", "content": text})

    def add_assistant(self, text: str) -> None:
        self.turns.append({"role": "assistant", "content": text})

    def clear(self) -> None:
        self.turns.clear()

    def snapshot(self) -> list[dict[str, str]]:
        return list(self.turns)


conversation = ConversationSession()

mcp = FastMCP(
    "sotuken-assistant",
    instructions=(
        "日本語の会話型アシスタントをMCP toolとして公開するサーバーです。"
        "時間、計算、現在地、天気のような簡単な処理は既存のローカル関数を優先し、"
        "一般的な会話はローカルLLMを試し、失敗時のみクラウドAIへ切り替えます。"
    ),
)


def _format_available_functions() -> str:
    lines = ["利用可能な機能:"]
    for item in AVAILABLE_FUNCTIONS:
        lines.append(f"- {item}")
    return "\n".join(lines)


def _looks_like_capability_question(text: str) -> bool:
    normalized = (text or "").strip()
    if not normalized:
        return False
    capability_keywords = (
        "何ができる",
        "できること",
        "機能",
        "使える",
        "対応",
        "クラウドai",
        "有名なクラウドai",
        "得意",
    )
    return any(keyword in normalized.lower() for keyword in capability_keywords)


def _append_routing_log(user_input: str, decision: str, reason: str, elapsed_ms: float) -> None:
    ROUTING_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"[{timestamp}]",
        f"入力内容: {user_input}",
        f"判定: {decision}",
        f"理由: {reason}",
        f"処理時間: {elapsed_ms:.1f}ms",
        "",
    ]
    with ROUTING_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines))

    csv_exists = ROUTING_LOG_CSV_PATH.exists()
    if not csv_exists:
        with ROUTING_LOG_CSV_PATH.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(ROUTING_LOG_CSV_HEADER)

    with ROUTING_LOG_CSV_PATH.open("a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([timestamp, user_input, decision, reason, f"{elapsed_ms:.1f}"])


def _generate_response_with_meta(text: str) -> dict[str, str | float]:
    request_id = uuid4().hex
    started = time.perf_counter()
    local_time_sec = 0.0
    cloud_time_sec = 0.0
    api_called = False

    def finalize(response: str, decision: str, reason: str, route: str, success: bool = True) -> dict[str, str | float]:
        elapsed_ms = (time.perf_counter() - started) * 1000
        _append_routing_log(normalized_text, decision, reason, elapsed_ms)
        conversation.add_assistant(response)

        record = evaluation_metrics.build_record(
            request_id=request_id,
            entry_point="mcp_server.chat",
            input_text=normalized_text,
            response_text=response,
            route=route,
            response_time_sec=elapsed_ms / 1000.0,
            local_time_sec=local_time_sec,
            cloud_time_sec=cloud_time_sec,
            api_called=api_called,
            success=success,
        )
        evaluation_metrics.save(record)
        summary = evaluation_metrics.get_summary()

        return {
            "response": response,
            "decision": decision,
            "reason": reason,
            "elapsed_ms": elapsed_ms,
            "evaluation": build_user_facing_evaluation(record, summary),
        }

    conversation.add_user(text)
    normalized_text = normalize_asr_text(text)
    update_profile_from_text(normalized_text)
    profile_context = build_profile_context()
    explicit_note_response = handle_explicit_note_command(normalized_text)

    if explicit_note_response:
        decision = "ローカル処理"
        reason = "メモ保存/参照コマンドをローカルで処理"
        return finalize(explicit_note_response, decision, reason, route="ローカル処理", success=True)

    if _looks_like_capability_question(normalized_text):
        response = _format_available_functions()
        decision = "ローカル処理"
        reason = "利用可能機能の問い合わせは固定リストで回答可能"
        return finalize(response, decision, reason, route="ローカル処理", success=True)

    if is_local_only_request(normalized_text):
        local_started = time.perf_counter()
        response = respond_local_only(normalized_text, conversation_history=conversation.snapshot())
        local_time_sec += time.perf_counter() - local_started
        decision = "ローカル処理"
        reason = "時刻/計算/天気/定型処理はローカル関数で実行可能"
        return finalize(response, decision, reason, route="ローカル処理", success=True)

    prompt = build_local_prompt(
        normalized_text,
        conversation_history=conversation.snapshot(),
        user_profile_context=profile_context,
    )

    try:
        local_started = time.perf_counter()
        response = ask_local_llm(prompt)
        local_time_sec += time.perf_counter() - local_started
        if response.startswith("（Ollama") or response.startswith("（ローカルLLM") or response.startswith("（ローカルLLMエラー"):
            raise RuntimeError(response)
        decision = "ローカル処理"
        reason = "一般質問だがローカルLLMが正常応答"
        return finalize(response, decision, reason, route="ローカルLLM", success=True)
    except Exception:
        try:
            cloud_started = time.perf_counter()
            response = ask_cloud_ai(prompt)
            cloud_time_sec += time.perf_counter() - cloud_started
            api_called = True
            decision = "クラウド処理候補"
            reason = "ローカルLLMで十分な応答を生成できないためクラウドへ委託"
            return finalize(response, decision, reason, route="クラウドフォールバック", success=True)
        except Exception as error:
            cloud_time_sec += time.perf_counter() - cloud_started
            api_called = True
            response = f"（クラウド呼び出し失敗: {error}）"
            decision = "クラウド処理候補"
            reason = "ローカルLLM失敗後にクラウド呼び出しも失敗"
            return finalize(response, decision, reason, route="エラー", success=False)


def _generate_response(text: str) -> str:
    return str(_generate_response_with_meta(text)["response"])


@mcp.tool(name="chat", description="会話型の応答を返します。会話履歴を保持し、必要に応じてローカルLLMとクラウドAIを切り替えます。")
def chat(text: str) -> str:
    return _generate_response(text)


@mcp.tool(name="list_available_tools", description="利用可能な機能一覧を返します。")
def list_available_tools() -> str:
    return _format_available_functions()


@mcp.tool(name="evaluate_processing_speed", description="入力を実際に処理し、判定理由と処理時間(ms)を返します。")
def evaluate_processing_speed(text: str) -> str:
    result = _generate_response_with_meta(text)
    response = str(result["response"])[:120]
    return (
        f"入力内容: {text}\n"
        f"判定: {result['decision']}\n"
        f"理由: {result['reason']}\n"
        f"処理時間: {float(result['elapsed_ms']):.1f}ms\n"
        f"応答プレビュー: {response}"
    )


@mcp.tool(name="get_evaluation_summary", description="累計のAPI削減率・応答時間・推定料金を返します。")
def get_evaluation_summary() -> dict:
    return evaluation_metrics.get_summary()


@mcp.tool(name="get_time", description="現在時刻と、必要なら本日の行事情報を返します。")
def get_time() -> str:
    return read_time()


@mcp.tool(name="calculate", description="入力文から数値を読み取り、簡単な計算結果を返します。")
def calculate(text: str) -> str:
    return calculate_expression(text)


@mcp.tool(name="get_current_location", description="公開IPベースの現在地推定を返します。")
def get_current_location() -> str:
    return read_current_location()


@mcp.tool(name="get_weather", description="現在地または指定した地域・日付の天気を返します。")
def get_weather(query: str = "") -> str:
    return read_weather(query)


@mcp.tool(name="wikipedia_summary", description="Wikipediaの要約を返します。")
def wikipedia_summary_tool(query: str, language: str = "ja") -> str:
    return wikipedia_summary(query, language=language)


@mcp.tool(name="youtube_search", description="YouTube検索結果ページのリンクを返します。")
def youtube_search_tool(query: str) -> str:
    return youtube_search(query)


@mcp.tool(name="generate_qr_code", description="入力文字列のQRコード画像URLを生成します。")
def generate_qr_code_tool(text: str, size: int = 300) -> str:
    return generate_qr_code(text, size=size)


@mcp.tool(name="translate_text", description="テキストを翻訳します。")
def translate_text_tool(text: str, target_lang: str = "en", source_lang: str = "auto") -> str:
    return translate_text(text, target_lang=target_lang, source_lang=source_lang)


@mcp.tool(name="summarize_url", description="指定URLのページ内容を要約します。")
def summarize_url_tool(url: str) -> str:
    return summarize_web_url(url)


@mcp.tool(name="search_google_maps", description="Google Maps で場所を検索し、候補と Maps URL を返します。")
def search_google_maps_tool(query: str, max_results: int = 5) -> str:
    return search_google_maps(query, max_results=max_results)


@mcp.tool(name="search_google_web", description="Google 検索を API なしで実行し、簡易結果を返します。事実確認・最新情報の取得に適しています。")
def search_google_web_tool(query: str, max_results: int = 5) -> str:
    return search_google_web(query, max_results=max_results)


@mcp.tool(name="search_transit", description="公共交通機関の経路検索。Yahoo乗換案内API（YAHOO_APP_IDが設定済みの場合）を優先し、失敗時はGoogle Maps transit/drivingにフォールバックします。")
def search_transit_tool(origin: str, destination: str) -> str:
    return search_transit(origin, destination)


@mcp.tool(name="navigate", description="車または徒歩でのナビ経路をGoogle Mapsで返します。modeは driving（車）または walking（徒歩）を指定できます。")
def navigate_tool(origin: str, destination: str, mode: str = "driving") -> str:
    return navigate(origin, destination, mode=mode)


@mcp.tool(name="resolve_navigation", description="自然文からナビ・乗換案内を解決します。「新宿から渋谷まで電車で」のような文をそのまま渡せます。")
def resolve_navigation_tool(text: str, current_location: str = "") -> str:
    return resolve_navigation(text, current_location=current_location)


@mcp.tool(name="get_google_maps_directions", description="Google Maps で出発地から目的地までの経路を返します。")
def get_google_maps_directions_tool(origin: str, destination: str, mode: str = "driving") -> str:
    return get_google_maps_directions(origin, destination, mode=mode)


@mcp.tool(name="search_gmail", description="Gmail を検索してメール候補を返します。OAuth 認証が必要です。")
def search_gmail_tool(query: str, max_results: int = 5) -> str:
    return search_gmail(query, max_results=max_results)


@mcp.tool(name="send_gmail", description="Gmail でメールを送信します。OAuth 認証が必要です。")
def send_gmail_tool(to: str, subject: str, body: str, cc: str | None = None, bcc: str | None = None) -> str:
    return send_gmail(to, subject, body, cc=cc, bcc=bcc)


@mcp.tool(name="get_conversation_history", description="現在の会話履歴を返します。")
def get_conversation_history() -> list[dict[str, str]]:
    return conversation.snapshot()


@mcp.tool(name="clear_conversation_history", description="保持している会話履歴を消去します。")
def clear_conversation_history() -> str:
    conversation.clear()
    return "会話履歴を消去しました。"


if __name__ == "__main__":
    mcp.run(transport="stdio")

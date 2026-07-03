from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

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
from models.text_normalizer import normalize_asr_text
from models.user_profile_memory import build_profile_context, handle_explicit_note_command, update_profile_from_text

MAX_HISTORY_TURNS = 8


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


def _generate_response(text: str) -> str:
    conversation.add_user(text)
    normalized_text = normalize_asr_text(text)
    update_profile_from_text(normalized_text)
    profile_context = build_profile_context()
    explicit_note_response = handle_explicit_note_command(normalized_text)

    if explicit_note_response:
        conversation.add_assistant(explicit_note_response)
        return explicit_note_response

    if is_local_only_request(normalized_text):
        response = respond_local_only(normalized_text, conversation_history=conversation.snapshot())
    else:
        prompt = build_local_prompt(
            normalized_text,
            conversation_history=conversation.snapshot(),
            user_profile_context=profile_context,
        )

        try:
            response = ask_local_llm(prompt)
            if response.startswith("（Ollama") or response.startswith("（ローカルLLM") or response.startswith("（ローカルLLMエラー"):
                raise RuntimeError(response)
        except Exception:
            try:
                response = ask_cloud_ai(prompt)
            except Exception as error:
                response = f"（クラウド呼び出し失敗: {error}）"

    conversation.add_assistant(response)
    return response


@mcp.tool(name="chat", description="会話型の応答を返します。会話履歴を保持し、必要に応じてローカルLLMとクラウドAIを切り替えます。")
def chat(text: str) -> str:
    return _generate_response(text)


@mcp.tool(name="get_time", description="現在時刻と、必要なら本日の行事情報を返します。")
def get_time() -> str:
    return read_time()


@mcp.tool(name="calculate", description="入力文から数値を読み取り、簡単な計算結果を返します。")
def calculate(text: str) -> str:
    return calculate_expression(text)


@mcp.tool(name="get_current_location", description="公開IPベースの現在地推定を返します。")
def get_current_location() -> str:
    return read_current_location()


@mcp.tool(name="get_weather", description="現在地の天気を取得して返します。")
def get_weather() -> str:
    return read_weather()


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

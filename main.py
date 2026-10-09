"""テキスト入力から応答生成までをつなぐメイン実行ファイルで、対話アシスタント全体を起動します。"""

import asyncio
import datetime
import os
from uuid import uuid4
from collections import deque
from dataclasses import dataclass, field

from models.intent_classifier import classify_intent
from functions.time_func import get_time, get_weekday, get_weekday_from_text
from functions.calculator import calculate
from functions.location import get_current_location
from functions.weather import get_weather
from functions.google_workspace import search_google_web
from functions.transit import resolve_navigation

from cloud.openai_client import ask_cloud_ai
from cloud.local_llm import ask_local_llm
from cloud.local_prompt import build_local_prompt
from cloud.local_policy import is_local_only_request, respond_local_only
from models.evaluation_metrics import build_user_facing_evaluation, evaluation_metrics
from models.user_profile_memory import build_profile_context, handle_explicit_note_command, update_profile_from_text

import config


LOG_PATH = os.path.join("logs", "log.txt")
MAX_HISTORY_TURNS = 8

# バックグラウンドタスク管理
_PENDING_TASKS = set()
_LIVE_PARTIAL_LINE = ""


@dataclass
class ConversationSession:

    turns: deque = field(default_factory=lambda: deque(maxlen=MAX_HISTORY_TURNS))

    def add_user(self, text):

        self.turns.append({"role": "user", "content": text})


    def add_assistant(self, text):

        self.turns.append({"role": "assistant", "content": text})


    def build_prompt(self, current_text):
        return build_local_prompt(
            current_text,
            conversation_history=list(self.turns),
            mode="voice",
            user_profile_context=build_profile_context(),
        )


conversation = ConversationSession()


async def _run_and_track(coro):
    task = asyncio.create_task(coro)
    _PENDING_TASKS.add(task)

    try:
        return await task
    finally:
        _PENDING_TASKS.discard(task)


def _ensure_log():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)


def _log(kind, text):
    _ensure_log()

    ts = datetime.datetime.now().isoformat(
        sep=" ",
        timespec="seconds"
    )

    line = f"[{ts}] {kind}: {text}\n"

    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line)


def _route_label(route: str) -> str:
    mapping = {
        "memory_note": "ローカル処理",
        "time": "ローカル処理",
        "weekday": "ローカル処理",
        "relative_weekday": "ローカル処理",
        "calculate": "ローカル処理",
        "navigation": "ローカル処理",
        "search": "ローカル処理",
        "weather": "ローカル処理",
        "location": "ローカル処理",
        "local_only": "ローカル処理",
        "local_llm": "ローカルLLM",
        "cloud": "クラウドフォールバック",
        "error": "エラー",
    }
    return mapping.get(route, route)


async def handle_final_text(text, confidence=None, chunks=None):

    ts = datetime.datetime.now().strftime("%H:%M:%S")

    # Move to the next line before FINAL to avoid overlapping with live PARTIAL line.
    print()
    print(f"[{ts}] FINAL: {text}")

    _log("FINAL", text)
    conversation.add_user(text)

    # Split into sentence-like segments (Japanese punctuation aware)
    parts = __import__('re').findall(r'.+?[。！？\n]|.+?$', text)
    segments = [p.strip() for p in parts if p.strip()]

    for i, seg in enumerate(segments, start=1):
        request_id = uuid4().hex
        elapsed_started = asyncio.get_running_loop().time()
        local_time_sec = 0.0
        cloud_time_sec = 0.0
        api_called = False

        normalized_seg = seg.strip()
        update_profile_from_text(normalized_seg)
        profile_context = build_profile_context()
        explicit_note_response = handle_explicit_note_command(normalized_seg)
        intent = classify_intent(normalized_seg)
        print(f"SEGMENT[{i}/{len(segments)}]: {normalized_seg} -> intent={intent}")
        _log("SEGMENT", f"{normalized_seg} | intent={intent}")

        # Route per intent: simple prototype
        route = None
        if explicit_note_response:
            route = "memory_note"
            response = explicit_note_response

        elif intent == "time":
            route = "time"
            local_started = asyncio.get_running_loop().time()
            time_text = await asyncio.to_thread(get_time)
            local_time_sec += asyncio.get_running_loop().time() - local_started
            response = time_text

        elif intent == "weekday":
            route = "weekday"
            local_started = asyncio.get_running_loop().time()
            response = await asyncio.to_thread(get_weekday)
            local_time_sec += asyncio.get_running_loop().time() - local_started

        elif intent == "relative_weekday":
            route = "relative_weekday"
            local_started = asyncio.get_running_loop().time()
            response = await asyncio.to_thread(get_weekday_from_text, normalized_seg)
            local_time_sec += asyncio.get_running_loop().time() - local_started

        elif intent == "calculate":
            route = "calculate"
            local_started = asyncio.get_running_loop().time()
            response = await asyncio.to_thread(calculate, normalized_seg)
            local_time_sec += asyncio.get_running_loop().time() - local_started

        elif intent == "navigation":
            route = "navigation"
            print("ナビ/乗換案内で応答します...")
            local_started = asyncio.get_running_loop().time()
            response = await asyncio.to_thread(resolve_navigation, normalized_seg)
            local_time_sec += asyncio.get_running_loop().time() - local_started

        elif intent == "search":
            route = "search"
            print("Google検索で応答します...")
            local_started = asyncio.get_running_loop().time()
            response = await asyncio.to_thread(search_google_web, normalized_seg)
            local_time_sec += asyncio.get_running_loop().time() - local_started
            if not response or response.startswith("検索結果を抽出できませんでした"):
                response = "検索に失敗したためローカル回答へ切り替えました。"
                prompt = build_local_prompt(
                    normalized_seg,
                    conversation_history=list(conversation.turns),
                    user_profile_context=profile_context,
                )
                try:
                    local_started = asyncio.get_running_loop().time()
                    llm_response = await _run_and_track(asyncio.to_thread(ask_local_llm, prompt))
                    local_time_sec += asyncio.get_running_loop().time() - local_started
                    route = "local_llm"
                    response = f"{response}\n{llm_response}"
                except Exception as e:
                    route = "error"
                    response = f"検索に失敗したためローカル回答へ切り替えました。\n（ローカルLLM失敗: {e}）"

        elif intent == "weather":
            route = "weather"
            local_started = asyncio.get_running_loop().time()
            response = await asyncio.to_thread(get_weather, normalized_seg)
            local_time_sec += asyncio.get_running_loop().time() - local_started

        elif intent == "location":
            route = "location"
            local_started = asyncio.get_running_loop().time()
            response = await asyncio.to_thread(get_current_location)
            local_time_sec += asyncio.get_running_loop().time() - local_started

        elif is_local_only_request(normalized_seg):
            route = "local_only"
            print("ローカル専用で応答します...")
            local_started = asyncio.get_running_loop().time()
            response = await asyncio.to_thread(
                respond_local_only,
                normalized_seg,
                list(conversation.turns),
            )
            local_time_sec += asyncio.get_running_loop().time() - local_started

        else:
            route = "local_llm"
            prompt = build_local_prompt(
                normalized_seg,
                conversation_history=list(conversation.turns),
                user_profile_context=profile_context,
            )
            print("ローカルLLMに送信中...")

            try:
                local_started = asyncio.get_running_loop().time()
                response = await _run_and_track(asyncio.to_thread(ask_local_llm, prompt))
                local_time_sec += asyncio.get_running_loop().time() - local_started
                if response.startswith("（Ollama") or response.startswith("（ローカルLLM") or response.startswith("（ローカルLLMエラー"):
                    raise RuntimeError(response)
            except Exception:
                print("ローカルLLM失敗のためGoogle簡易検索を試します...")
                try:
                    local_started = asyncio.get_running_loop().time()
                    response = await _run_and_track(asyncio.to_thread(search_google_web, normalized_seg))
                    local_time_sec += asyncio.get_running_loop().time() - local_started
                    if response.startswith("Google 検索のページ取得に失敗しました") or response.startswith("検索結果を抽出できませんでした"):
                        raise RuntimeError(response)
                    route = "search"
                except Exception:
                    print("Google簡易検索でも失敗したためクラウドAIへ切り替えます...")
                    try:
                        cloud_started = asyncio.get_running_loop().time()
                        response = await _run_and_track(asyncio.to_thread(ask_cloud_ai, prompt))
                        cloud_time_sec += asyncio.get_running_loop().time() - cloud_started
                        api_called = True
                        route = "cloud"
                    except Exception as e:
                        cloud_time_sec += asyncio.get_running_loop().time() - cloud_started
                        api_called = True
                        route = "error"
                        response = f"（クラウド呼び出し失敗: {e}）"
        # route が決まっていなければ 'cloud' とする
        route = route or "cloud"
        print(f"route={route} response=", response)
        _log("RESPONSE", response)
        conversation.add_assistant(response)

        response_time_sec = asyncio.get_running_loop().time() - elapsed_started
        record = evaluation_metrics.build_record(
            request_id=request_id,
            entry_point="main.voice",
            input_text=normalized_seg,
            response_text=response,
            route=_route_label(route),
            response_time_sec=response_time_sec,
            local_time_sec=local_time_sec,
            cloud_time_sec=cloud_time_sec,
            api_called=api_called,
            success=not str(response).startswith("（"),
        )
        evaluation_metrics.save(record)
        summary = evaluation_metrics.get_summary()
        view = build_user_facing_evaluation(record, summary)

        print(
            "\n".join(
                [
                    f"回答経路：{view['route']}",
                    f"応答時間：{float(view['response_time_sec']):.2f}秒",
                    f"ローカル処理時間：{float(view['local_time_sec']):.2f}秒",
                    f"クラウド処理時間：{float(view['cloud_time_sec']):.2f}秒",
                    f"クラウドAPI呼出：{view['cloud_api_call']}",
                    f"推定API削減：{int(view['estimated_api_reduction_count'])}回",
                    f"推定料金削減：{float(view['saved_cost_yen']):.3f}円",
                    f"累計クラウドAPI呼出削減率：{float(view.get('cloud_api_call_reduction_rate', view['api_reduction_rate'])):.1f}％",
                ]
            )
        )
        _log("EVALUATION", str(view))

async def console_input_loop():
    """Allow user to type text directly into the terminal as an alternative input.

    Enter sends the line to the same final-text handler. Type '/exit' to stop console input loop.
    """
    print("\nテキスト入力モード: ターミナルに直接入力してEnterで送信。'/exit'で終了。")
    while True:
        try:
            text = await asyncio.to_thread(input, "\n[INPUT] ")
        except (EOFError, KeyboardInterrupt):
            print("コンソール入力を終了します。")
            break

        if text is None:
            continue

        t = text.strip()
        if not t:
            continue

        if t.lower() in {"/exit", "exit", "quit"}:
            print("コンソール入力を終了します。")
            break

        # send to final handler just like ASR final
        try:
            await handle_final_text(t, confidence=1.0, chunks=None)
        except Exception as e:
            print(f"コンソール入力処理でエラー: {e}")


async def main():

    print("テキスト入力モードで起動しました。Ctrl+C で終了します。")

    # Start console input loop so user can type queries directly
    console_task = asyncio.create_task(console_input_loop())

    try:

        await console_task

    finally:
        if not console_task.done():
            console_task.cancel()
            try:
                await console_task
            except Exception:
                pass

    if _PENDING_TASKS:

        print(
            "[INFO] Waiting for background tasks..."
        )

        try:

            await asyncio.wait_for(

                asyncio.gather(
                    *list(_PENDING_TASKS)
                ),

                timeout=30
            )

        except asyncio.TimeoutError:

            print(
                "[WARN] Background task timeout."
            )


if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        print(
            "\nInterrupted by user."
        )
import asyncio
import datetime
import os
from contextlib import suppress
from collections import deque
from dataclasses import dataclass, field
import sounddevice as sd

from audio.speaker import speak
from audio.audio_stream import RealtimeSpeechPipeline

from models.intent_classifier import classify_intent
from models.text_normalizer import normalize_asr_text

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


async def _speak_after_delay(text, delay_seconds=0.8):

    await asyncio.sleep(delay_seconds)
    await asyncio.to_thread(speak, text)


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
        normalized_seg = normalize_asr_text(seg)
        update_profile_from_text(normalized_seg)
        profile_context = build_profile_context()
        explicit_note_response = handle_explicit_note_command(normalized_seg)
        # If the ASR result looks like a greeting, always try aggressive re-transcription
        # with a larger beam: user likely asked a short question but ASR returned an utterance.
        if chunks is not None and any(g in normalized_seg for g in ["おはよう", "こんにちは", "こんばんは", "やあ"]):
            try:
                from audio.transcriber import transcribe_with_beam

                # concatenate chunks into a single numpy array for re-transcription
                import numpy as _np

                valid = [_np.asarray(c) for c in chunks if _np.asarray(c).size > 0]
                if valid:
                    audio_np = _np.concatenate(valid)
                    alt_text, alt_conf = await _run_and_track(asyncio.to_thread(transcribe_with_beam, audio_np, 16000, 9))
                    alt_norm = normalize_asr_text(alt_text)
                    if "何時" in alt_norm or "時間" in alt_norm:
                        normalized_seg = alt_norm
                        intent = "time"
                        print("Aggressive re-transcription detected time:", normalized_seg)
            except Exception:
                pass
        # 優先ルール: 直近の PARTIAL 表示に時刻関連キーワードがあれば 'time' を優先
        last_partial = _LIVE_PARTIAL_LINE or ""
        if any(k in last_partial for k in ["時間", "何時"]):
            intent = "time"
        else:
            intent = classify_intent(normalized_seg)
        print(f"SEGMENT[{i}/{len(segments)}]: {normalized_seg} -> intent={intent}")
        _log("SEGMENT", f"{normalized_seg} | intent={intent}")

        # speak filler for segment (only if TTS enabled)
        filler = "少々お待ちください。確認しています。"
        if config.TTS_ENABLED:
            await _run_and_track(asyncio.to_thread(speak, filler))

        # Route per intent: simple prototype
        route = None
        if explicit_note_response:
            route = "memory_note"
            response = explicit_note_response

        elif intent == "time":
            route = "time"
            # if the user's final (or partial) contained a greeting, include a polite greeting before the time
            GREETINGS = ["おはよう", "こんにちは", "こんばんは", "やあ"]
            has_greeting = any(k in normalized_seg for k in GREETINGS) or any(k in (last_partial or "") for k in GREETINGS)

            time_text = await asyncio.to_thread(get_time)

            if has_greeting:
                # choose appropriate greeting based on current hour
                now_h = datetime.datetime.now().hour
                if 5 <= now_h < 12:
                    greet = "おはようございます。"
                elif 12 <= now_h < 18:
                    greet = "こんにちは。"
                else:
                    greet = "こんばんは。"

                response = f"{greet} {time_text}"
            else:
                response = time_text

        elif intent == "weekday":
            route = "weekday"
            response = await asyncio.to_thread(get_weekday)

        elif intent == "relative_weekday":
            route = "relative_weekday"
            response = await asyncio.to_thread(get_weekday_from_text, normalized_seg)

        elif intent == "calculate":
            route = "calculate"
            response = await asyncio.to_thread(calculate, normalized_seg)

        elif intent == "navigation":
            route = "navigation"
            print("ナビ/乗換案内で応答します...")
            response = await asyncio.to_thread(resolve_navigation, normalized_seg)

        elif intent == "search":
            route = "search"
            print("Google検索で応答します...")
            response = await asyncio.to_thread(search_google_web, normalized_seg)
            if not response or response.startswith("検索結果を抽出できませんでした"):
                # 検索失敗時のみクラウドLLMへ
                prompt = build_local_prompt(
                    normalized_seg,
                    conversation_history=list(conversation.turns),
                    user_profile_context=profile_context,
                )
                try:
                    response = await _run_and_track(asyncio.to_thread(ask_cloud_ai, prompt))
                except Exception as e:
                    response = f"（検索・クラウド失敗: {e}）"

        elif intent == "weather":
            route = "weather"
            response = await asyncio.to_thread(get_weather)

        elif intent == "location":
            route = "location"
            response = await asyncio.to_thread(get_current_location)

        elif is_local_only_request(normalized_seg):
            route = "local_only"
            print("ローカル専用で応答します...")
            response = await asyncio.to_thread(
                respond_local_only,
                normalized_seg,
                list(conversation.turns),
            )

        else:
            prompt = build_local_prompt(
                normalized_seg,
                conversation_history=list(conversation.turns),
                user_profile_context=profile_context,
            )
            print("ローカルLLMに送信中...")

            filler_task = asyncio.create_task(
                _speak_after_delay("少々お待ちください。確認しています。")
            )

            try:
                response = await _run_and_track(asyncio.to_thread(ask_local_llm, prompt))
                if response.startswith("（Ollama") or response.startswith("（ローカルLLM") or response.startswith("（ローカルLLMエラー"):
                    raise RuntimeError(response)
            except Exception:
                print("ローカルLLM失敗のためGoogle簡易検索を試します...")
                try:
                    response = await _run_and_track(asyncio.to_thread(search_google_web, normalized_seg))
                    if response.startswith("Google 検索のページ取得に失敗しました") or response.startswith("検索結果を抽出できませんでした"):
                        raise RuntimeError(response)
                except Exception:
                    print("Google簡易検索でも失敗したためクラウドAIへ切り替えます...")
                    try:
                        response = await _run_and_track(asyncio.to_thread(ask_cloud_ai, prompt))
                    except Exception as e:
                        response = f"（クラウド呼び出し失敗: {e}）"
            finally:
                filler_task.cancel()
                with suppress(asyncio.CancelledError):
                    await filler_task

        # route が決まっていなければ 'cloud' とする
        route = route or "cloud"
        print(f"route={route} response=", response)
        _log("RESPONSE", response)
        conversation.add_assistant(response)

        # Always print text response. Speak only if enabled.
        if config.TTS_ENABLED:
            await _run_and_track(asyncio.to_thread(speak, response))


async def handle_partial_text(text):

    ts = datetime.datetime.now().strftime("%H:%M:%S")

    global _LIVE_PARTIAL_LINE

    prev_line = _LIVE_PARTIAL_LINE
    line = f"[{ts}] PARTIAL: {text}"
    clear = " " * max(0, len(prev_line) + 24)
    print(f"\r{clear}\r{line}", end="", flush=True)
    _LIVE_PARTIAL_LINE = text

    _log("PARTIAL", text)


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

    print(
        "マイク待機中... Ctrl+C で終了"
    )

    try:

        print(
            "Default input device:",
            sd.default.device
        )

    except Exception:
        pass

    pipeline = RealtimeSpeechPipeline(

        debug=False,

        force_transcribe=False,

        partial_window_seconds=2.0,

        partial_min_interval_sec=0.8,

        partial_emit_min_chars=4,
    )

    pipeline_task = asyncio.create_task(

        pipeline.run(
            on_partial=handle_partial_text,
            on_final=handle_final_text
        )
    )

    # Start console input loop so user can type queries when ASR fails
    console_task = asyncio.create_task(console_input_loop())

    try:

        # Run indefinitely; stop with Ctrl+C. Final handling still runs per utterance.
        await asyncio.Event().wait()

    finally:

        try:

            await pipeline.stop()

        except Exception:
            pass

        if not pipeline_task.done():

            pipeline_task.cancel()

            try:

                await pipeline_task

            except Exception:
                pass
        # stop console input loop if running
        if 'console_task' in locals() and not console_task.done():
            console_task.cancel()
            with suppress(asyncio.CancelledError):
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
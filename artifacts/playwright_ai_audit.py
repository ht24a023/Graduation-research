"""PlaywrightでUIやルーティングを点検する監査スクリプトで、画面の動作確認を自動化します。"""

import json
import re
import sys
import time
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from models.intent_classifier import classify_intent

BASE_URL = "http://localhost:8000"

CASES = [
    ("A", "Edge AIについて英語の情報を検索して", None),
    ("B", "What is edge AI? Please search the web and summarize the results.", None),
    ("C", "什么是边缘人工智能？请搜索并用日语总结。", None),
    ("D", "엣지 AI란 무엇인가요? 검색해서 일본어로 요약해 주세요.", None),
    ("E", "この2つを比較して", "PythonとJava"),
    ("F", "これを計算して", "(150+230)÷19"),
    ("G", "PythonとJavaの主な違いを比較して", None),
    ("H", "10と20を足して", None),
    ("I", "ここから目的地までの行き方を教えて", "京都駅"),
]


def wait_server(timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            response = requests.get(BASE_URL + "/", timeout=5)
            if response.ok and "Local AI Server" in response.text:
                return
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError("server not ready")


def safe_json(value):
    try:
        return json.loads(value)
    except Exception:
        return {"raw": value}


def run_audit():
    wait_server()
    results = []
    post_bodies = []
    chat_json_responses = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1200})

        def on_request(req):
            if req.url.endswith("/chat") and req.method == "POST":
                post_bodies.append(safe_json(req.post_data or "{}"))

        def on_response(resp):
            if resp.url.endswith("/chat") and resp.request.method == "POST":
                try:
                    chat_json_responses.append(resp.json())
                except Exception:
                    chat_json_responses.append({"parse_error": True})

        page.on("request", on_request)
        page.on("response", on_response)
        page.goto(BASE_URL + "/", wait_until="domcontentloaded", timeout=30000)

        for label, prompt, followup in CASES:
            case_session_id = f"audit-{label.lower()}-{uuid4().hex}"
            page.evaluate(
                """
                (sid) => {
                    const storageKey = 'local-ai-session-id';
                    try { window.localStorage.setItem(storageKey, sid); } catch (e) {}
                    const input = document.querySelector('#session-id');
                    if (input) {
                        input.value = sid;
                        input.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }
                """,
                case_session_id,
            )

            before_req = len(post_bodies)
            before_resp = len(chat_json_responses)
            before_assistant = page.locator(".bubble.assistant").count()
            before_wrap = page.locator(".choice-wrap").count()

            page.fill("#message", prompt)
            page.click("#send-btn")

            timed_out = False
            try:
                page.wait_for_function(
                    "() => { const btn = document.querySelector('#send-btn'); return !!btn && !btn.disabled; }",
                    timeout=180000,
                )
                page.wait_for_function(
                    f"() => document.querySelectorAll('.bubble.assistant').length > {before_assistant}",
                    timeout=180000,
                )
            except PlaywrightTimeoutError:
                timed_out = True

            after_wrap = page.locator(".choice-wrap").count()
            panel_text = ""
            has_prompt_input = False
            if after_wrap > before_wrap:
                last_wrap = page.locator(".choice-wrap").nth(after_wrap - 1)
                panel_text = last_wrap.inner_text()
                has_prompt_input = last_wrap.locator("input").count() > 0

            assistant_count = page.locator(".bubble.assistant").count()
            user_count = page.locator(".bubble.user").count()
            assistant_text = page.locator(".bubble.assistant").nth(assistant_count - 1).inner_text() if assistant_count else ""
            user_text = page.locator(".bubble.user").nth(user_count - 1).inner_text() if user_count else ""

            post_payload = post_bodies[before_req] if len(post_bodies) > before_req else {}
            response_payload = chat_json_responses[before_resp] if len(chat_json_responses) > before_resp else {}

            followup_payload = {}
            followup_response = {}
            followup_assistant_text = ""
            followup_panel_text = ""
            followup_timed_out = False

            if followup and has_prompt_input:
                followup_before_req = len(post_bodies)
                followup_before_resp = len(chat_json_responses)
                followup_before_assistant = page.locator(".bubble.assistant").count()
                latest_wrap = page.locator(".choice-wrap").nth(after_wrap - 1)

                latest_wrap.locator('input[placeholder*="不足している情報"]').fill(followup)
                latest_wrap.locator('button:has-text("再演算")').click()

                try:
                    page.wait_for_function(
                        "() => { const btn = document.querySelector('#send-btn'); return !!btn && !btn.disabled; }",
                        timeout=180000,
                    )
                    page.wait_for_function(
                        f"() => document.querySelectorAll('.bubble.assistant').length > {followup_before_assistant}",
                        timeout=180000,
                    )
                except PlaywrightTimeoutError:
                    followup_timed_out = True

                after_wrap_followup = page.locator(".choice-wrap").count()
                if after_wrap_followup > after_wrap:
                    followup_wrap = page.locator(".choice-wrap").nth(after_wrap_followup - 1)
                    followup_panel_text = followup_wrap.inner_text()

                followup_assistant_count = page.locator(".bubble.assistant").count()
                if followup_assistant_count > 0:
                    followup_assistant_text = page.locator(".bubble.assistant").nth(followup_assistant_count - 1).inner_text()

                followup_payload = post_bodies[followup_before_req] if len(post_bodies) > followup_before_req else {}
                followup_response = chat_json_responses[followup_before_resp] if len(chat_json_responses) > followup_before_resp else {}
            response_str = json.dumps(response_payload, ensure_ascii=False)
            has_reference_links = bool(re.search(r"https?://", response_str))

            assistant_head_lines = [line for line in assistant_text.splitlines() if line.strip()][:5]
            output_order = {
                "has_translation_heading": "日本語訳" in assistant_text,
                "has_summary_heading": "日本語による要約" in assistant_text,
                "has_links_heading": "参照リンク" in assistant_text,
                "first_5_lines": assistant_head_lines,
            }

            results.append(
                {
                    "id": label,
                    "session_id": case_session_id,
                    "input": prompt,
                    "followup_input": followup,
                    "intent": classify_intent(prompt),
                    "route": response_payload.get("route") if isinstance(response_payload, dict) else None,
                    "post_body": post_payload,
                    "response_json": response_payload,
                    "followup_post_body": followup_payload,
                    "followup_response_json": followup_response,
                    "followup_final_answer": followup_response.get("response") if isinstance(followup_response, dict) else "",
                    "ui_text_full": {
                        "user_bubble": user_text,
                        "assistant_bubble": assistant_text,
                        "panel_text": panel_text,
                        "followup_assistant_bubble": followup_assistant_text,
                        "followup_panel_text": followup_panel_text,
                    },
                    "prompt_input": has_prompt_input,
                    "has_reference_links": has_reference_links,
                    "timed_out": timed_out or followup_timed_out,
                    "output_order": output_order,
                }
            )

        browser.close()

    return results


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    results = run_audit()
    out_dir = Path("artifacts")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "ai_audit_results.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out_path.as_posix())
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

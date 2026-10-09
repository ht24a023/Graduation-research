import json
import time

import pytest
import requests
from playwright.sync_api import sync_playwright


BASE_URL = "http://localhost:8000"


def wait_for_server(url: str, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
      try:
        response = requests.get(url, timeout=10)
        if response.ok and "Local AI Server" in response.text:
          return
      except Exception:
        pass
      time.sleep(0.5)
    raise RuntimeError(f"server at {url} did not become ready in time")


@pytest.mark.e2e
def test_general_clarification_recompute_flow_and_control_case():
    wait_for_server(BASE_URL)
    chat_posts = []
    chat_responses = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1200})
        page.on(
            "request",
            lambda req: chat_posts.append(json.loads(req.post_data or "{}"))
            if req.url.endswith("/chat") and req.method == "POST"
            else None,
        )

        def capture_response(resp):
            if resp.url.endswith("/chat") and resp.request.method == "POST":
                try:
                    chat_responses.append(resp.json())
                except Exception:
                    chat_responses.append({})

        page.on("response", capture_response)
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)

        page.fill("#message", "この2つを比較して")
        page.click("#send-btn")

        page.wait_for_function(
            "() => { const bubbles = Array.from(document.querySelectorAll('.bubble.assistant')); return bubbles.some((el) => (el.textContent || '').includes('確認質問')); }",
            timeout=120000,
        )
        page.wait_for_function(
            "() => document.querySelectorAll('input[placeholder*=\"不足している情報\"]').length > 0",
            timeout=120000,
        )

        first_response = chat_responses[-1]
        assert first_response.get("ui", {}).get("type") == "prompt_input", first_response
        assert first_response.get("ui", {}).get("interaction") == "recompute", first_response
        assert "比較したい" in first_response.get("response", "") or "入力してください" in first_response.get("response", "")

        page.fill('input[placeholder*="不足している情報"]', "PythonとJava")
        page.click('button:has-text("再演算")')

        page.wait_for_function(
            "() => { const buttons = document.querySelectorAll('#send-btn'); return buttons.length > 0 && !buttons[0].disabled; }",
            timeout=120000,
        )
        page.wait_for_function(
            "() => { const bubbles = Array.from(document.querySelectorAll('.bubble.assistant')); return bubbles.some((el) => (el.textContent || '').includes('Python')) && bubbles.some((el) => (el.textContent || '').includes('Java')); }",
            timeout=120000,
        )

        assert len(chat_posts) >= 2, chat_posts
        first_post = chat_posts[0]
        second_post = chat_posts[1]
        assert first_post.get("message") == "この2つを比較して", first_post
        assert "元の依頼：この2つを比較して" in second_post.get("message", ""), second_post
        assert "追加情報：PythonとJava" in second_post.get("message", ""), second_post

        second_response = chat_responses[-1]
        assert second_response.get("ok") is True, second_response
        assert second_response.get("ui") in (None, {}), second_response
        assert "Python" in second_response.get("response", ""), second_response
        assert "Java" in second_response.get("response", ""), second_response

        users = page.locator(".bubble.user").all_text_contents()
        assistants = page.locator(".bubble.assistant").all_text_contents()
        assert any("この2つを比較して" in text for text in users), users
        assert any("元の依頼：この2つを比較して" in text and "追加情報：PythonとJava" in text for text in users), users
        assert any("確認質問" in text for text in assistants), assistants
        assert any("Python" in text and "Java" in text for text in assistants), assistants
        assert page.locator("#send-btn").is_enabled()

        browser.close()


def _send_and_wait_prompt(page, message: str):
    before_assistant = page.locator(".bubble.assistant").count()
    page.fill("#message", message)
    page.click("#send-btn")
    page.wait_for_function(
        "() => { const btn = document.querySelector('#send-btn'); return !!btn && !btn.disabled; }",
        timeout=120000,
    )
    page.wait_for_function(
        f"() => document.querySelectorAll('.bubble.assistant').length > {before_assistant}",
        timeout=120000,
    )


def _submit_prompt_input_and_wait(page, value: str):
    before_assistant = page.locator(".bubble.assistant").count()
    latest_wrap = page.locator(".choice-wrap").last
    latest_wrap.locator('input[placeholder*="不足している情報"]').fill(value)
    latest_wrap.locator('button:has-text("再演算")').click()
    page.wait_for_function(
        "() => { const btn = document.querySelector('#send-btn'); return !!btn && !btn.disabled; }",
        timeout=120000,
    )
    page.wait_for_function(
        f"() => document.querySelectorAll('.bubble.assistant').length > {before_assistant}",
        timeout=120000,
    )


@pytest.mark.e2e
def test_recompute_flow_for_calculation_and_navigation():
    wait_for_server(BASE_URL)
    chat_posts = []
    chat_responses = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1200})
        page.on(
            "request",
            lambda req: chat_posts.append(json.loads(req.post_data or "{}"))
            if req.url.endswith("/chat") and req.method == "POST"
            else None,
        )

        def capture_response(resp):
            if resp.url.endswith("/chat") and resp.request.method == "POST":
                try:
                    chat_responses.append(resp.json())
                except Exception:
                    chat_responses.append({})

        page.on("response", capture_response)
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)

        # F: 計算の再演算
        _send_and_wait_prompt(page, "これを計算して")
        first_calc_response = chat_responses[-1]
        assert first_calc_response.get("ui", {}).get("type") == "prompt_input", first_calc_response
        _submit_prompt_input_and_wait(page, "(150+230)÷19")
        final_calc_response = chat_responses[-1]
        assert final_calc_response.get("route") == "local_function", final_calc_response
        assert "20" in final_calc_response.get("response", ""), final_calc_response
        assert "入力してください" not in final_calc_response.get("response", ""), final_calc_response

        # I: 経路案内の再演算
        _send_and_wait_prompt(page, "ここから目的地までの行き方を教えて")
        first_nav_response = chat_responses[-1]
        assert first_nav_response.get("ui", {}).get("type") == "prompt_input", first_nav_response
        _submit_prompt_input_and_wait(page, "京都駅")
        final_nav_response = chat_responses[-1]
        assert final_nav_response.get("route") == "local_function", final_nav_response
        assert "京都駅" in final_nav_response.get("response", ""), final_nav_response
        assert "Google Maps" in final_nav_response.get("response", ""), final_nav_response
        assert "http" in final_nav_response.get("response", ""), final_nav_response
        assert "目的地を1つ入力してください" not in final_nav_response.get("response", ""), final_nav_response

        # 2回目POST証跡
        calc_first = next((p for p in chat_posts if p.get("message") == "これを計算して"), None)
        calc_second = next((p for p in chat_posts if "元の依頼：これを計算して" in p.get("message", "")), None)
        nav_first = next((p for p in chat_posts if p.get("message") == "ここから目的地までの行き方を教えて"), None)
        nav_second = next((p for p in chat_posts if "元の依頼：ここから目的地までの行き方を教えて" in p.get("message", "")), None)

        assert calc_first is not None, chat_posts
        assert calc_second is not None, chat_posts
        assert "追加情報：(150+230)÷19" in calc_second.get("message", ""), calc_second
        assert nav_first is not None, chat_posts
        assert nav_second is not None, chat_posts
        assert "追加情報：京都駅" in nav_second.get("message", ""), nav_second

        assert page.locator("#send-btn").is_enabled()
        browser.close()
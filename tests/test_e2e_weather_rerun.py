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
def test_weather_rerun_posts_second_request_with_city_name():
    wait_for_server(BASE_URL)
    chat_posts = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1200})
        page.on("request", lambda req: chat_posts.append(req) if req.url.endswith("/chat") and req.method == "POST" else None)

        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
        page.fill("#message", "今日の天気は？")
        page.click("#send-btn")

        page.wait_for_function(
            "() => { const bubbles = Array.from(document.querySelectorAll('.bubble.assistant')); return bubbles.some((el) => /今日の天気|明日|最高|最低/.test(el.textContent || '')); }",
            timeout=120000,
        )

        page.wait_for_function(
            "() => document.querySelectorAll('input[placeholder*=\"大阪の明日\"]').length > 0",
            timeout=120000,
        )
        page.wait_for_function(
            "() => document.querySelector('#send-btn') !== null",
            timeout=120000,
        )

        selector = 'input[placeholder*="大阪の明日"]'
        page.fill(selector, "大阪の明日")
        page.click('button:has-text("再演算")')

        page.wait_for_function(
            "() => { const items = Array.from(document.querySelectorAll('.bubble.user')); return items.some((el) => (el.textContent || '').includes('大阪の明日')); }",
            timeout=120000,
        )

        page.wait_for_function(
            "() => { const buttons = document.querySelectorAll('#send-btn'); return buttons.length > 0 && !buttons[0].disabled; }",
            timeout=120000,
        )

        chat_requests = [
            req
            for req in chat_posts
            if req.url.endswith("/chat") and req.method == "POST"
        ]
        assert len(chat_requests) >= 2, f"expected at least two /chat POSTs; saw {len(chat_requests)}"

        second_payload = json.loads(chat_requests[1].post_data or "{}")
        assert second_payload.get("message") == "大阪の明日", second_payload
        assert second_payload.get("session_id"), second_payload

        assistant_text = page.locator(".bubble.assistant").all_text_contents()
        assert any("大阪" in text and "明日" in text for text in assistant_text), assistant_text

        browser.close()

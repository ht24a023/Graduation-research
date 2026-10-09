"""調査や検索補助の処理をまとめる関数群で、研究向けの情報整理を助けます。"""

from __future__ import annotations

import json
import re
import time
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.parse import quote, quote_plus, urlencode
from urllib.request import Request, urlopen


_TRANSLATION_CACHE: dict[tuple[str, str, str], dict[str, object]] = {}


def _http_get_text(url: str, timeout: int = 12) -> str:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def wikipedia_summary(query: str, language: str = "ja") -> str:
    title = (query or "").strip()
    if not title:
        return "Wikipedia検索語を入力してください。"

    lang = (language or "ja").strip().lower()
    url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(title)}"

    try:
        payload = json.loads(_http_get_text(url))
    except (HTTPError, URLError, TimeoutError, Exception) as error:
        return f"Wikipedia要約の取得に失敗しました: {error}"

    extract = (payload.get("extract") or "").strip()
    page_url = (
        payload.get("content_urls", {})
        .get("desktop", {})
        .get("page", "")
        .strip()
    )

    if not extract:
        return "Wikipediaの要約を取得できませんでした。"

    lines = [f"Wikipedia要約: {title}", extract]
    if page_url:
        lines.append(f"リンク:\n{page_url}")
    return "\n\n".join(lines)


def youtube_search(query: str) -> str:
    text = (query or "").strip()
    if not text:
        return "YouTube検索語を入力してください。"

    url = f"https://www.youtube.com/results?search_query={quote_plus(text)}"
    return f"YouTube検索: {text}\nリンク:\n{url}"


def generate_qr_code(text: str, size: int = 300) -> str:
    payload = (text or "").strip()
    if not payload:
        return "QRコード化する文字列を入力してください。"

    safe_size = min(max(int(size or 300), 100), 1000)
    qr_url = "https://quickchart.io/qr?" + urlencode({"text": payload, "size": str(safe_size)})
    return f"QRコードを生成しました。\nリンク:\n{qr_url}"


def _translate_text_structured(text: str, target_lang: str = "en", source_lang: str = "auto") -> dict[str, object]:
    source = (source_lang or "auto").strip().lower()
    target = (target_lang or "en").strip().lower()
    payload = (text or "").strip()

    if not payload:
        return {
            "ok": False,
            "translated_text": "",
            "source_language": source,
            "error": "翻訳するテキストを入力してください。",
            "retryable": False,
        }

    cache_key = (payload, target, source)
    cached = _TRANSLATION_CACHE.get(cache_key)
    if cached is not None:
        return dict(cached)

    url = (
        "https://translate.googleapis.com/translate_a/single?"
        + urlencode(
            {
                "client": "gtx",
                "sl": source,
                "tl": target,
                "dt": "t",
                "q": payload,
            }
        )
    )

    def _build_error(message: str, retryable: bool, translated_text: str = "") -> dict[str, object]:
        result = {
            "ok": False,
            "translated_text": translated_text,
            "source_language": source,
            "error": message,
            "retryable": retryable,
        }
        return result

    retry_after_seconds = None
    try:
        raw = _http_get_text(url)
        data = json.loads(raw)
    except HTTPError as error:
        retry_after = error.headers.get("Retry-After") if getattr(error, "headers", None) else None
        try:
            retry_after_seconds = int(retry_after) if retry_after else None
        except (TypeError, ValueError):
            retry_after_seconds = None
        retryable = error.code == 429 or 500 <= error.code < 600
        message = f"翻訳に失敗しました: HTTP Error {error.code}"
        if error.code == 429:
            message = "翻訳に失敗しました: HTTP Error 429"
        result = _build_error(message, retryable)
        if retry_after_seconds is not None:
            result["retry_after_seconds"] = retry_after_seconds
        return result
    except (URLError, TimeoutError, Exception) as error:
        return _build_error(f"翻訳に失敗しました: {error}", True)

    try:
        translated = "".join(part[0] for part in data[0] if part and part[0])
    except Exception:
        translated = ""

    if not translated:
        return _build_error("翻訳結果を取得できませんでした。", True)

    result = {
        "ok": True,
        "translated_text": translated.strip(),
        "source_language": source,
        "error": "",
        "retryable": False,
    }
    _TRANSLATION_CACHE[cache_key] = dict(result)
    return result


def translate_text(text: str, target_lang: str = "en", source_lang: str = "auto") -> str:
    result = _translate_text_structured(text, target_lang=target_lang, source_lang=source_lang)
    if result.get("ok"):
        return f"翻訳 ({result.get('source_language')} -> {target_lang}):\n{result.get('translated_text', '')}"

    error = str(result.get("error") or "翻訳に失敗しました。")
    return error


def translate_text_structured(text: str, target_lang: str = "en", source_lang: str = "auto") -> dict[str, object]:
    return _translate_text_structured(text, target_lang=target_lang, source_lang=source_lang)


def summarize_web_url(url: str) -> str:
    target = (url or "").strip()
    if not target:
        return "要約するURLを入力してください。"

    if not re.match(r"^https?://", target, re.IGNORECASE):
        return "URLは http:// または https:// から始めてください。"

    try:
        html = _http_get_text(target)
    except (HTTPError, URLError, TimeoutError, Exception) as error:
        return f"URL要約の取得に失敗しました: {error}"

    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    title = unescape(re.sub(r"\s+", " ", title_match.group(1))).strip() if title_match else "(タイトル不明)"

    desc_match = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
        html,
        re.IGNORECASE | re.DOTALL,
    )
    description = unescape(re.sub(r"\s+", " ", desc_match.group(1))).strip() if desc_match else ""

    paragraph_match = re.search(r"<p[^>]*>(.*?)</p>", html, re.IGNORECASE | re.DOTALL)
    paragraph = ""
    if paragraph_match:
        paragraph = re.sub(r"<[^>]+>", " ", paragraph_match.group(1))
        paragraph = unescape(re.sub(r"\s+", " ", paragraph)).strip()

    summary_text = description or paragraph
    if len(summary_text) > 240:
        summary_text = summary_text[:240].rstrip() + "..."

    lines = [f"URL要約: {title}"]
    if summary_text:
        lines.append(f"要点: {summary_text}")
    else:
        lines.append("要点: 本文要約を抽出できませんでした。")
    lines.append(f"リンク:\n{target}")

    return "\n".join(lines)

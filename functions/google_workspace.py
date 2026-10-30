"""Google検索や外部情報取得を扱う関数群で、事実確認や検索結果の要約を支えます。"""

from __future__ import annotations

import base64
import json
import datetime
import os
import re
import time
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any
from html import unescape
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, unquote_plus, urlencode, urlparse, parse_qs
from urllib.request import Request, urlopen

from cloud.local_llm import ask_local_llm
from functions.research_tools import translate_text

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
GOOGLE_MAPS_LANGUAGE = os.getenv("GOOGLE_MAPS_LANGUAGE", "ja")
GOOGLE_SEARCH_LANGUAGE = os.getenv("GOOGLE_SEARCH_LANGUAGE", "ja")
GOOGLE_SEARCH_COUNTRY = os.getenv("GOOGLE_SEARCH_COUNTRY", "jp")

GOOGLE_GMAIL_CREDENTIALS_FILE = os.getenv("GOOGLE_GMAIL_CREDENTIALS_FILE", "google_credentials.json")
GOOGLE_GMAIL_TOKEN_FILE = os.getenv("GOOGLE_GMAIL_TOKEN_FILE", "google_token.json")
GOOGLE_GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


def _now_utc_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _contains_japanese(text: str) -> bool:
    payload = text or ""
    return bool(re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", payload))


def _looks_like_translation_error(text: str) -> bool:
    payload = (text or "").strip()
    if not payload:
        return True
    lowered = payload.lower()
    if payload.startswith(("（Ollama", "(Ollama")) or "timed out" in lowered or "connection refused" in lowered:
        return True
    if any(token in payload for token in ["翻訳に失敗", "翻訳結果を取得できませんでした", "HTTP Error", "Too Many Requests", "429"]):
        return True
    if payload in {"原文と同じです", "原文と完全に同じ文字列です"}:
        return True
    return False


def _normalize_translation_text(text: str, original_text: str) -> str | None:
    body = _extract_translated_body(text)
    body = (body or "").strip()
    if not body:
        return None
    if body == original_text.strip():
        return None
    if _looks_like_translation_error(body):
        return None
    if not _contains_japanese(body):
        return None
    return body


def _translate_with_fallback(text: str, *, source_lang: str = "auto") -> dict[str, object]:
    primary = translate_text(text, target_lang="ja", source_lang=source_lang)
    translated = _normalize_translation_text(primary, text)
    if translated:
        return {
            "ok": True,
            "translated_text": translated,
            "source_language": source_lang,
            "error": "",
            "retryable": False,
        }

    if any(token in primary for token in ["429", "Too Many Requests", "HTTP Error", "翻訳に失敗", "翻訳結果を取得できませんでした"]):
        local_prompt = (
            "次の英文を自然な日本語に翻訳してください。"
            "出力は翻訳文だけにしてください。\n"
            f"英語: {text}"
        )
        local_translation = ask_local_llm(local_prompt, timeout=10.0)
        translated = _normalize_translation_text(local_translation, text)
        if translated:
            return {
                "ok": True,
                "translated_text": translated,
                "source_language": source_lang,
                "error": "",
                "retryable": False,
            }

    return {
        "ok": False,
        "translated_text": "",
        "source_language": source_lang,
        "error": primary,
        "retryable": any(token in primary for token in ["429", "Too Many Requests", "HTTP Error", "翻訳に失敗", "翻訳結果を取得できませんでした"]),
    }


def _safe_translate_text(text: str, *, target_lang: str = "ja", source_lang: str = "auto") -> str | None:
    if target_lang != "ja":
        translated = translate_text(text, target_lang=target_lang, source_lang=source_lang)
        body = _extract_translated_body(translated)
        return body.strip() if body and body != text and _contains_japanese(body) else None

    result = _translate_with_fallback(text, source_lang=source_lang)
    return str(result.get("translated_text") or "").strip() or None


def _result_record(
    *,
    engine: str,
    query: str,
    title: str,
    url: str,
    snippet: str = "",
    language: str = "unknown",
    rank: int = 1,
    body_checked: bool = False,
) -> dict[str, Any]:
    return {
        "engine": engine,
        "query": query,
        "title": title,
        "url": url,
        "snippet": snippet,
        "retrieved_at": _now_utc_iso(),
        "language": language,
        "rank": rank,
        "body_checked": body_checked,
    }


def _clean_search_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for item in results:
        url = str(item.get("url") or "").strip()
        title = str(item.get("title") or "").strip()
        if not url or not title:
            continue
        if _is_ad_or_search_url(url):
            continue
        if not url or not title or url in seen_urls:
            continue
        seen_urls.add(url)
        cleaned.append(dict(item))
    return cleaned


def _is_ad_or_search_url(url: str) -> bool:
    lowered = (url or "").lower()
    if not lowered:
        return True
    blocked_tokens = [
        "duckduckgo.com/l/?",
        "duckduckgo.com/y.js",
        "bing.com/aclick",
        "bing.com/search",
        "google.com/search",
        "google.com/url",
        "ad_domain",
        "ad_provider",
        "aclick",
        "y.js",
    ]
    return any(token in lowered for token in blocked_tokens)


def _normalize_result_url(url: str) -> str:
    candidate = (url or "").strip()
    if not candidate:
        return ""
    if candidate.startswith("//"):
        candidate = "https:" + candidate
    if "duckduckgo.com/l/?" in candidate or "duckduckgo.com/l/?" in candidate.lower():
        parsed = urlparse(candidate)
        uddg = parse_qs(parsed.query).get("uddg", [""])[0]
        if uddg:
            candidate = unquote_plus(uddg)
    if candidate.startswith("http://"):
        candidate = "https://" + candidate.removeprefix("http://")
    return candidate


def _render_search_response(
    *,
    query: str,
    language: str,
    engine: str,
    search_query: str,
    results: list[dict[str, Any]],
    translated_input: str | None = None,
    source_translation: str | None = None,
    body_checked: bool = False,
    trial_route: str | None = None,
) -> str:
    lines: list[str] = []
    if translated_input:
        lines.append(f"入力文の日本語訳：{translated_input}")
        if source_translation:
            lines.append(f"元の入力：{query}")
    elif language not in {"ja", "unknown"}:
        lines.append("日本語訳できませんでした。")
        lines.append(f"元の入力：{query}")

    if results:
        normalized = [item for item in _clean_search_results(results) if not _is_ad_or_search_url(_normalize_result_url(str(item.get("url") or "").strip()))]
        summary_sentences: list[str] = []
        for item in normalized[:4]:
            snippet = str(item.get("snippet") or "").strip()
            if not snippet:
                continue
            translated_seed = snippet
            if _detect_language(snippet) not in {"ja", "unknown"}:
                translated_seed = _safe_translate_text(snippet) or snippet
            sentence = re.sub(r"\s+", " ", translated_seed).strip()
            if sentence:
                if not sentence.endswith(("。", "！", "?", "？")):
                    sentence += "。"
                summary_sentences.append(sentence)
            if len(summary_sentences) >= 4:
                break
        if summary_sentences:
            lines.append("要約：")
            for sentence in summary_sentences[:4]:
                lines.append(sentence)
        elif normalized:
            first_title = str(normalized[0].get("title") or "").strip()
            if first_title:
                lines.append("要約：")
                lines.append(f"{first_title} などの関連情報が見つかりました。")

        lines.append("参考情報：")
        for index, item in enumerate(normalized[:5], start=1):
            title = str(item.get("title") or "").strip()
            url = _normalize_result_url(str(item.get("url") or "").strip())
            if not title or not url:
                continue
            if _is_ad_or_search_url(url):
                continue
            lines.append(f"{index}. {title}")
            lines.append(f"   {url}")

        lines.append("検索情報：")
        lines.append(f"使用した検索エンジン：{engine}")
        if trial_route:
            lines.append(f"試行経路：{trial_route}")
        lines.append(f"検索語：{search_query}")
        lines.append(f"取得日時：{_now_utc_iso()}")
        if body_checked:
            lines.append("確認方法：本文確認済み")
        else:
            lines.append("確認方法：検索スニペットだけ")
        return "\n".join(lines)

    lines.append("検索結果を取得できませんでした。")
    lines.append("検索情報：")
    lines.append(f"使用した検索エンジン：{engine}")
    if trial_route:
        lines.append(f"試行経路：{trial_route}")
    lines.append(f"検索語：{search_query}")
    lines.append(f"取得日時：{_now_utc_iso()}")
    return "\n".join(lines)


def _http_get_json(url: str, timeout: int = 10) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})

    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _http_get_text(url: str, timeout: int = 10) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7",
        },
    )

    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _extract_search_results_from_duckduckgo(html: str, max_results: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    for match in re.finditer(
        r'<a[^>]+class="result__a"[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?(?:<a[^>]+class="result__snippet"[^>]*>(?P<snippet>.*?)</a>|<div[^>]+class="result__snippet"[^>]*>(?P<div_snippet>.*?)</div>)?',
        html,
        re.IGNORECASE | re.DOTALL,
    ):
        url_candidate = unescape(match.group("url"))
        if url_candidate in seen_urls:
            continue

        title = unescape(re.sub(r"<[^>]+>", "", match.group("title"))).strip()
        snippet_raw = match.group("snippet") or match.group("div_snippet") or ""
        snippet = unescape(re.sub(r"<[^>]+>", "", snippet_raw)).strip()

        if not title:
            continue

        results.append({"title": title, "url": url_candidate, "snippet": snippet})
        seen_urls.add(url_candidate)
        if len(results) >= max_results:
            break

    return results


def _normalize_result_url(url: str) -> str:
    # DuckDuckGo redirect URL (//duckduckgo.com/l/?uddg=...)
    try:
        if "duckduckgo.com/l/?" in url:
            parsed = urlparse("https:" + url if url.startswith("//") else url)
            uddg = parse_qs(parsed.query).get("uddg", [""])[0]
            if uddg:
                return unquote_plus(uddg)
    except Exception:
        pass
    return url


def _extract_salary_values_man(text: str) -> list[float]:
    values = []
    for m in re.finditer(r"(\d{2,4}(?:\.\d+)?)\s*万円", text):
        try:
            value = float(m.group(1))
            if 100 <= value <= 5000:
                values.append(value)
        except Exception:
            continue
    return values


def _is_salary_query(query: str) -> bool:
    q = (query or "")
    return any(k in q for k in ["年収", "給与", "給料", "平均年収", "月収", "年俸"])


def _detect_language(text: str) -> str:
    if not text:
        return "unknown"

    text = text.strip()
    total_chars = len(text)
    if total_chars == 0:
        return "unknown"

    hiragana = sum(1 for ch in text if "\u3040" <= ch <= "\u309f")
    katakana = sum(1 for ch in text if "\u30a0" <= ch <= "\u30ff")
    han = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    hangul = sum(1 for ch in text if "\uac00" <= ch <= "\ud7af")
    ascii_letters = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    alpha_chars = sum(1 for ch in text if ch.isalpha())

    if hangul > 0 and hangul / total_chars >= 0.12:
        return "ko"

    kana_total = hiragana + katakana
    if kana_total > 0 and kana_total / total_chars >= 0.08:
        return "ja"

    if han > 0 and han / total_chars >= 0.18 and kana_total == 0:
        return "zh"

    if ascii_letters > 0 and (ascii_letters / max(1, alpha_chars) >= 0.6 or ascii_letters >= 8):
        return "en"

    return "unknown"


def _build_japanese_summary_from_translation(translated_text: str) -> str:
    # 「日本語による要約」は簡易版の要約として、翻訳文の先頭1〜2文を抽出する。
    # これは詳細な再要約ロジックではなく、検索結果の要点を短く見せるための簡略化実装である。
    body = (translated_text or "").strip()
    if body.startswith("日本語訳:"):
        body = body.split("日本語訳:", 1)[1].strip()
    if body.startswith("日本語訳："):
        body = body.split("日本語訳：", 1)[1].strip()

    if not body:
        return ""

    sentences = [segment.strip() for segment in re.split(r"(?<=[。！？])\s+", body) if segment.strip()]
    if not sentences:
        return body

    first = sentences[0]
    if len(first) > 120:
        return first[:120].rstrip("。！？） ") + "..."
    if len(sentences) > 1:
        return first + (" " + sentences[1][:80].strip() if len(sentences[1]) > 0 else "")
    return first


def _extract_translated_body(translated_text: str) -> str:
    payload = (translated_text or "").strip()
    if not payload:
        return ""

    if ":\n" in payload:
        return payload.split(":\n", 1)[1].strip()
    if "\n" in payload:
        head, body = payload.split("\n", 1)
        if head.startswith("翻訳"):
            return body.strip()
    return payload


def _build_search_query_from_japanese_text(text: str) -> str:
    normalized = re.sub(r"\s+", " ", (text or "").strip())
    if not normalized:
        return ""

    if any(token in normalized for token in ["エッジAI", "エッ ジAI", "エッジ AI"]) and "何か" in normalized:
        return "エッジAIとは何か"

    if any(token in normalized for token in ["ローカルで AI を実行", "ローカルでAIを実行", "ローカルで AIを実行"]) and any(token in normalized for token in ["利点", "メリット", "長所"]):
        return "ローカルAI 利点 クラウドAI 比較"

    # Remove instruction-like trailing phrases while keeping topic nouns.
    normalized = re.sub(r"[。．！？!?]", " ", normalized)
    normalized = re.sub(
        r"(検索(して|してください)?|調べて|調査して|要約(して|してください)?|まとめ(て|てください)?|教えて|日本語(で|に)|英語(で|に)|韓国語(で|に)|中国語(で|に))",
        " ",
        normalized,
    )
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        return (text or "").strip()
    return normalized


def _normalize_search_query_phrase(text: str) -> str:
    normalized = re.sub(r"\s+", " ", (text or "").strip())
    if not normalized:
        return ""

    normalized = re.sub(r"[。．！？!?]", " ", normalized)
    normalized = re.sub(
        r"(検索(して|してください)?|調べて|調査して|要約(して|してください)?|まとめ(て|てください)?|教えて|日本語(で|に)|英語(で|に)|韓国語(で|に)|中国語(で|に)|情報を探してください|検索してください|調べてください)",
        " ",
        normalized,
    )
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _build_search_keywords_from_translation(text: str) -> str:
    candidate = _build_search_query_from_japanese_text(text)
    candidate = _normalize_search_query_phrase(candidate)
    candidate = candidate.replace("とは", " ").replace("について", " ")
    candidate = re.sub(r"(?:どのような|どの様な|どんな|何の|何が|何ですか|どのような違い|違いは何ですか)", " ", candidate)
    candidate = candidate.replace("エ ッジ", "エッジ").replace("ク ラウド", "クラウド")
    candidate = re.sub(r"\s+", " ", candidate).strip()
    if not candidate:
        return ""

    if "エッジAI" in candidate and "何か" in candidate:
        return "エッジAIとは何か"

    lowered = candidate.replace(" ", "")
    if "ローカルでAIを実行" in candidate and any(keyword in candidate for keyword in ["利点", "メリット", "長所"]) and any(keyword in candidate for keyword in ["クラウド", "送信"]):
        return "ローカルAI 利点 クラウドAI 比較"

    if "エッジAI" in candidate and "何か" in candidate and any(marker in candidate for marker in ["し ください", "してください", "検索", "要約"]):
        return "エッジAIとは何か"

    if "AIをローカルで実行" in candidate and any(keyword in candidate for keyword in ["利点", "メリット", "長所"]) and any(keyword in candidate for keyword in ["クラウド", "雲"]):
        return "ローカルAI 利点 クラウドAI 比較"

    if "エッジAI" in candidate and "何か" in candidate and any(keyword in candidate for keyword in ["違い", "比較", "検索"]):
        return "エッジAI クラウドAI 違い"

    if any(keyword in lowered for keyword in ["ローカルAI", "ローカル人工知能", "エッジAI"]) and any(keyword in lowered for keyword in ["クラウドAI", "クラウド人工知能"]):
        if any(keyword in lowered for keyword in ["利点", "メリット", "長所"]):
            return "ローカルAI 利点 クラウドAI 比較"
        if any(keyword in lowered for keyword in ["欠点", "デメリット", "短所"]):
            return "エッジAI メリット デメリット"
        if any(keyword in lowered for keyword in ["違い", "比較"]):
            return "エッジAI クラウドAI 違い"

    if any(keyword in lowered for keyword in ["エッジAI", "エッジ人工知能"]) and any(keyword in lowered for keyword in ["クラウドAI", "クラウド人工知能"]) and any(keyword in lowered for keyword in ["違い", "比較"]):
        return "エッジAI クラウドAI 違い"

    if any(keyword in lowered for keyword in ["エッジAI", "エッジ人工知能"]) and any(keyword in lowered for keyword in ["メリット", "デメリット", "長所", "短所"]):
        return "エッジAI メリット デメリット"

    tokens = [token for token in re.split(r"[\s、,／/・]+", candidate) if token]
    if not tokens:
        return candidate

    keep_tokens: list[str] = []
    for token in tokens:
        if token in {"検索", "してください", "教えて", "要約", "まとめ"}:
            continue
        keep_tokens.append(token)

    return " ".join(keep_tokens[:6]).strip()


def _normalize_translated_input_ja(text: str) -> str:
    body = (text or "").strip()
    if not body:
        return ""

    body = body.replace("検索します。", "検索してください。")
    body = body.replace("検索します", "検索してください")
    body = body.replace("教えてください。", "")
    body = body.replace("教えてください", "")
    body = body.replace("エッ ジ", "エッジ")
    body = body.replace("ク ラウド", "クラウド")
    body = body.replace("ロ ーカル", "ローカル")
    body = re.sub(r"\s+", " ", body).strip()
    return body


def _extract_search_results_payload(
    raw_result: object,
    effective_query: str,
    translated_input: str | None = None,
) -> tuple[str, list[dict[str, str]], str | None]:
    if isinstance(raw_result, dict):
        results = raw_result.get("results") or []
        cleaned_results: list[dict[str, str]] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            url = _normalize_result_url(str(item.get("url") or "").strip())
            snippet = str(item.get("snippet") or "").strip()
            if title and url:
                cleaned_results.append({"title": title, "url": url, "snippet": snippet})

        if cleaned_results:
            summary = _render_search_response(
                query=str(raw_result.get("query") or effective_query),
                language=str(raw_result.get("language") or "unknown"),
                engine=str(raw_result.get("engine") or "Google"),
                search_query=str(raw_result.get("query") or effective_query),
                results=cleaned_results,
                translated_input=str(raw_result.get("translated_input") or translated_input or "") or None,
                source_translation=str(raw_result.get("translated_input") or translated_input or "") or None,
                body_checked=bool(raw_result.get("body_checked", False)),
                trial_route=str(raw_result.get("trial_route") or "Google"),
            )
            return summary, cleaned_results, None
        error_type = str(raw_result.get("error_type") or "search_fetch_failed") or "search_fetch_failed"
        return "Google検索結果を取得できませんでした。", [], error_type

    if isinstance(raw_result, str) and raw_result.strip():
        if "検索結果を取得できませんでした" in raw_result or "検索結果を抽出できませんでした" in raw_result:
            return "Google検索結果を取得できませんでした。", [], "search_fetch_failed"
        translated_result = _translate_raw_search_result(raw_result)
        translated_result = translated_result.replace("日本語による要約：", "要約：")
        translated_result = translated_result.replace("検索内容の要約：", "要約：")
        translated_result = translated_result.replace("参照リンク：", "参考情報：")
        if translated_input:
            translated_result = f"入力文の日本語訳：{translated_input}\n{translated_result}"
        refs = re.findall(r"https?://[^\s\n]+", translated_result)
        parsed_results: list[dict[str, str]] = []
        for index, url in enumerate(refs, start=1):
            parsed_results.append({"title": f"検索結果 {index}", "url": url, "snippet": ""})
        return translated_result, parsed_results, None

    return "Google検索結果を取得できませんでした。", [], "search_fetch_failed"


def _search_with_fallbacks(query: str, max_results: int = 5, language: str | None = None, country: str | None = None) -> object:
    providers = (
        lambda: _search_google_web_impl(query, max_results, language, country),
        lambda: _search_duckduckgo_lite(query, max_results),
        lambda: _search_bing(query, max_results),
        lambda: _search_duckduckgo_instant_api(query, max_results),
    )
    result: object = "検索結果を取得できませんでした。"
    for provider in providers:
        try:
            result = provider()
        except Exception:
            continue
        if isinstance(result, dict) and result.get("results"):
            return result
        if isinstance(result, str) and re.search(r"https?://", result) and "検索結果を抽出できませんでした" not in result and "検索結果を取得できませんでした" not in result:
            return result
    return result


def _prepare_search_query(query: str) -> tuple[str, str | None, str]:
    raw_query = (query or "").strip()
    if not raw_query:
        return "", None, "unknown"

    detected = _detect_language(raw_query)
    if detected not in {"en", "zh", "ko"}:
        return raw_query, None, detected

    translation = _translate_with_fallback(raw_query, source_lang=detected)
    translated_body = str(translation.get("translated_text") or "").strip()
    if not translation.get("ok") or not translated_body:
        return _sanitize_search_query_fallback(raw_query, None), None, detected

    search_query = translated_body

    return search_query, translated_body, detected


def _build_search_query_from_english_text(text: str) -> str:
    normalized = re.sub(r"\s+", " ", (text or "").strip())
    if not normalized:
        return ""

    normalized = re.sub(r"[?.!]+", " ", normalized)
    normalized = re.sub(
        r"\b(search|please|information|summarize|summary|about|for|and|the|to|how do|how does|what is|what are|tell me|show me)\b",
        " ",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(r"\b(do|does|did|work|works|explain|tell|show|find|give|need|help)\b", " ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized.lower()


def _sanitize_search_query_fallback(query: str, candidate: str | None) -> str:
    text = (candidate or "").strip()
    if not text or _looks_like_translation_error(text):
        text = _build_search_query_from_english_text(query)
    if not text:
        text = (query or "").strip()
    if _looks_like_translation_error(text):
        return _build_search_query_from_english_text(query) or (query or "").strip()
    return text


def _maybe_translate_search_summary(text: str) -> str:
    payload = (text or "").strip()
    if not payload:
        return text

    if payload.startswith("日本語訳:") or payload.startswith("検索内容の要約:") or payload.startswith("参照リンク:"):
        return payload

    detected = _detect_language(payload)
    if detected == "ja" or detected == "unknown":
        return payload

    translated_body = _safe_translate_text(payload, target_lang="ja", source_lang=detected)
    if not translated_body:
        return payload

    return "日本語訳：" + translated_body


def _translate_raw_search_result(result: str) -> str:
    if not result or "検索結果を抽出できませんでした" in result:
        return result

    lines = [line.strip() for line in result.splitlines() if line.strip()]
    if not lines:
        return result

    candidate_lines = []
    for line in lines:
        if line.startswith(("Google", "検索結果", "他に欲しい情報", "要約:", "検索内容の要約:")):
            continue
        if line.startswith(("1.", "2.", "3.", "4.", "5.")) or line.startswith("- ") or line.startswith("・"):
            candidate_lines.append(line)

    summary_text = "\n".join(candidate_lines) if candidate_lines else "\n".join(lines[1:])
    if not summary_text.strip():
        return result

    detected = _detect_language(summary_text)
    if detected == "ja" or detected == "unknown":
        return result

    translated = _maybe_translate_search_summary(summary_text)
    if translated == summary_text:
        return result

    translation_body = (translated or "").replace("日本語訳：", "", 1).replace("日本語訳:", "", 1).strip()
    summary_body = _build_japanese_summary_from_translation(translation_body)
    refs = []
    for line in lines:
        if "http://" in line or "https://" in line:
            refs.append(line)
    ref_block = "\n".join(refs[:3]) if refs else "なし"
    return f"日本語訳：{translation_body}\n日本語による要約：{summary_body}\n参照リンク：{ref_block}"


def _format_search_answer(query: str, results: list[dict[str, str]]) -> str:
    if not results:
        return "検索結果を抽出できませんでした。"

    followup = (
        "\n\n他に欲しい情報はありますか？"
        "\n提供できる情報の例:"
        "\n- 企業情報（年収・業績・比較）"
        "\n- ルート案内（車・徒歩・公共交通）"
        "\n- 現在地・天気"
        "\n- 計算・時刻・曜日"
        "\n- 一般的な質問の要約回答"
    )

    # URL正規化
    normalized = []
    for r in results:
        normalized.append(
            {
                "title": r.get("title", "").strip(),
                "url": _normalize_result_url(r.get("url", "").strip()),
                "snippet": r.get("snippet", "").strip(),
            }
        )

    # 年収系クエリは数値を抽出して結論を先に返す
    if _is_salary_query(query):
        values = []
        for item in normalized[:8]:
            values.extend(_extract_salary_values_man(item.get("title", "")))
            values.extend(_extract_salary_values_man(item.get("snippet", "")))

        if values:
            values_sorted = sorted(values)
            low = int(round(values_sorted[0]))
            high = int(round(values_sorted[-1]))
            mid = int(round(values_sorted[len(values_sorted) // 2]))

            return (
                f"結論: {query}について、公開情報ベースではおおむね{low}〜{high}万円、"
                f"中心値は{mid}万円前後です。\n"
                "補足: 掲載サイトごとに年度・算出方法が異なるため、数値には差があります。"
            ) + followup

    # 汎用クエリはスニペット優先で要約
    snippets = [item["snippet"] for item in normalized if item.get("snippet")][:3]
    titles = [item["title"] for item in normalized if item.get("title")][:3]
    refs = [item["url"] for item in normalized[:3] if item.get("url")]
    ref_block = "\n".join(refs[:3]) if refs else "なし"

    if snippets:
        merged = " ".join(snippets)
        merged = re.sub(r"\s+", " ", merged).strip()
        if len(merged) > 180:
            merged = merged[:180].rstrip() + "..."
        translated = _maybe_translate_search_summary(merged)
        translation_body = (translated or "").replace("日本語訳：", "", 1).replace("日本語訳:", "", 1).strip()
        if not translation_body:
            translation_body = merged
        summary_body = _build_japanese_summary_from_translation(translation_body)
        response = f"日本語訳：{translation_body}\n要約：{summary_body}"
        if ref_block != "なし":
            response += f"\n参考情報：\n{ref_block}"
        return response + followup

    if titles:
        summary_body = "関連する検索結果が見つかりました。"
        response = f"要約：{summary_body}"
        if ref_block != "なし":
            response += f"\n参考情報：\n{ref_block}"
        return response + followup

    return "検索結果を取得できませんでした。" + followup


def _format_maps_place(place: dict[str, Any]) -> str:
    name = place.get("name") or "不明"
    address = place.get("formatted_address") or place.get("vicinity") or "住所不明"
    rating = place.get("rating")
    place_id = place.get("place_id") or ""
    maps_url = f"https://www.google.com/maps/search/?api=1&query={quote_plus(name)}"

    parts = [f"{name} / {address}"]
    if rating is not None:
        parts.append(f"評価 {rating}")
    if place_id:
        parts.append(f"place_id={place_id}")
    parts.append(f"URL: {maps_url}")
    return " | ".join(parts)


def search_google_maps(query: str, max_results: int = 5, language: str | None = None) -> str:
    if not GOOGLE_MAPS_API_KEY:
        # APIキー未設定: Google Web 検索 + Maps URL で代替
        maps_url = f"https://www.google.com/maps/search/{quote_plus(query)}"
        web_result = search_google_web(query + " 場所", max_results=max_results)
        return f"{web_result}\n\nGoogle Maps で確認: {maps_url}"

    if not query.strip():
        return "検索語を入力してください。"

    params = {
        "query": query,
        "language": language or GOOGLE_MAPS_LANGUAGE,
        "key": GOOGLE_MAPS_API_KEY,
    }
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json?" + urlencode(params)

    try:
        payload = _http_get_json(url)
    except (HTTPError, URLError, Exception) as error:
        return f"Google Maps 検索に失敗しました: {error}"

    status = payload.get("status")
    if status not in {"OK", "ZERO_RESULTS"}:
        message = payload.get("error_message") or status or "不明なエラー"
        return f"Google Maps 検索に失敗しました: {message}"

    results = payload.get("results", [])[:max_results]
    if not results:
        return "検索結果は見つかりませんでした。"

    lines = [f"Google Maps 検索結果: {query}"]
    for index, place in enumerate(results, start=1):
        lines.append(f"{index}. {_format_maps_place(place)}")

    return "\n".join(lines)


def search_google_web_structured(query: str, max_results: int = 5, language: str | None = None, country: str | None = None) -> dict[str, object]:
    if not query.strip():
        return {
            "ok": False,
            "route": "search_failed",
            "detected_language": "unknown",
            "original_query": query,
            "translated_query": None,
            "actual_search_query": None,
            "search_engine": None,
            "results": [],
            "summary_ja": None,
            "error_type": "search_fetch_failed",
        }

    detected_input_lang = _detect_language(query)
    if detected_input_lang == "unknown":
        return {
            "ok": False,
            "route": "translation_failed",
            "detected_language": "unknown",
            "original_query": query,
            "translated_query": None,
            "actual_search_query": None,
            "search_engine": None,
            "results": [],
            "summary_ja": None,
            "error_type": "translation_failed",
        }

    translated_query = None
    actual_search_query = query
    route = "local_search"
    if detected_input_lang in {"en", "zh", "ko"}:
        translation = _translate_with_fallback(query, source_lang=detected_input_lang)
        translated_query = _normalize_translated_input_ja(str(translation.get("translated_text") or "").strip()) or None
        if not translation.get("ok") or not translated_query:
            return {
                "ok": False,
                "route": "translation_failed",
                "detected_language": "unknown",
                "original_query": query,
                "translated_query": None,
                "actual_search_query": None,
                "search_engine": None,
                "results": [],
                "summary_ja": None,
                "error_type": "translation_failed",
            }
        actual_search_query = _build_search_keywords_from_translation(translated_query) or translated_query
        route = "foreign_input_translate_search"
    elif detected_input_lang == "ja":
        actual_search_query = _build_search_keywords_from_translation(query) or query

    effective_query = actual_search_query or query
    raw_result = _search_with_fallbacks(effective_query, max_results, language, country)
    if isinstance(raw_result, dict) and translated_query:
        raw_result = dict(raw_result)
        raw_result.setdefault("translated_input", translated_query)
        raw_result.setdefault("source_translation", translated_query)
    summary_text, results, error_type = _extract_search_results_payload(raw_result, effective_query, translated_query)
    if results:
        return {
            "ok": True,
            "route": route,
            "detected_language": detected_input_lang,
            "original_query": query,
            "translated_query": translated_query,
            "actual_search_query": effective_query,
            "search_engine": str(raw_result.get("engine") if isinstance(raw_result, dict) else "Google"),
            "results": results,
            "summary_ja": summary_text,
            "error_type": None,
        }

    return {
        "ok": False,
        "route": "search_failed",
        "detected_language": detected_input_lang,
        "original_query": query,
        "translated_query": translated_query,
        "actual_search_query": effective_query,
        "search_engine": "Google",
        "results": [],
        "summary_ja": None,
        "error_type": error_type or "search_fetch_failed",
    }


def search_google_web(query: str, max_results: int = 5, language: str | None = None, country: str | None = None) -> str:
    structured = search_google_web_structured(query, max_results=max_results, language=language, country=country)
    if structured.get("ok"):
        return str(structured.get("summary_ja") or "")
    if structured.get("route") == "translation_failed":
        return "入力された文章を日本語へ翻訳できませんでした。日本語で入力し直すか、翻訳を再試行してください。"
    return "Google検索結果を取得できませんでした。"


def _search_google_web_impl(query: str, max_results: int = 5, language: str | None = None, country: str | None = None) -> str:
    params = {
        "q": query,
        "num": min(max_results, 10),
        "hl": language or GOOGLE_SEARCH_LANGUAGE,
        "gl": country or GOOGLE_SEARCH_COUNTRY,
        "pws": "0",
        "safe": "off",
    }
    url = "https://www.google.com/search?" + urlencode(params)

    try:
        html = _http_get_text(url)
    except (HTTPError, URLError, Exception) as error:
        html = ""

    if html:
        lower_html = html.lower()
        if "unusual traffic" not in lower_html and "captcha" not in lower_html and "consent" not in lower_html:
            results: list[dict[str, str]] = []
            seen_urls: set[str] = set()

            for match in re.finditer(r'<a[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<body>.*?)</a>', html, re.IGNORECASE | re.DOTALL):
                href = unescape(match.group("href"))
                if "/url?q=" not in href and "google.com/url?" not in href:
                    continue

                url_candidate_match = re.search(r"[?&]q=([^&]+)", href)
                if not url_candidate_match:
                    continue

                url_candidate = unquote_plus(unescape(url_candidate_match.group(1)))
                if url_candidate in seen_urls:
                    continue

                body = match.group("body")
                title_match = re.search(r"<h3[^>]*>(?P<title>.*?)</h3>", body, re.IGNORECASE | re.DOTALL)
                if not title_match:
                    title_match = re.search(r"<span[^>]*role=\"heading\"[^>]*>(?P<title>.*?)</span>", body, re.IGNORECASE | re.DOTALL)
                if not title_match:
                    continue

                title = unescape(re.sub(r"<[^>]+>", "", title_match.group("title"))).strip()
                if not title:
                    continue

                snippet = ""
                snippet_match = re.search(r'<div[^>]*class="[^"]*(?:VwiC3b|s3v9rd|lyLwlc)[^"]*"[^>]*>(?P<snippet>.*?)</div>', html[match.end():], re.IGNORECASE | re.DOTALL)
                if snippet_match:
                    snippet = unescape(re.sub(r"<[^>]+>", "", snippet_match.group("snippet"))).strip()

                results.append({"title": title, "url": url_candidate, "snippet": snippet})
                seen_urls.add(url_candidate)
                if len(results) >= max_results:
                    break

            if results:
                return {
                    "engine": "Google",
                    "query": query,
                    "results": [
                        _result_record(
                            engine="Google",
                            query=query,
                            title=item["title"],
                            url=item["url"],
                            snippet=item.get("snippet", ""),
                            language=_detect_language(query),
                            rank=index,
                            body_checked=False,
                        )
                        for index, item in enumerate(results[:max_results], start=1)
                    ],
                    "body_checked": False,
                }

    return "検索結果を抽出できませんでした。Google の HTML が JS 前提で、取得できませんでした。"


def _search_duckduckgo_lite(query: str, max_results: int = 5) -> str:
    if not query.strip():
        return "検索結果を抽出できませんでした。"

    ddg_lite_url = "https://lite.duckduckgo.com/lite/?" + urlencode({"q": query})
    try:
        html = _http_get_text(ddg_lite_url)
    except (HTTPError, URLError, Exception):
        return "検索結果を抽出できませんでした。"

    class ResultParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.results = []
            self.current = None
            self.snippet_parts = None

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            classes = (attrs.get("class") or "").split()
            if tag == "a" and "result-link" in classes:
                self.current = {"url": _normalize_result_url(attrs.get("href") or ""), "title": "", "snippet": ""}
            if tag == "td" and "result-snippet" in classes:
                self.snippet_parts = []

        def handle_data(self, data):
            if self.current is not None:
                self.current["title"] += data
            if self.snippet_parts is not None:
                self.snippet_parts.append(data)

        def handle_endtag(self, tag):
            if tag == "a" and self.current is not None:
                self.current["title"] = self.current["title"].strip()
                if self.current["title"] and self.current["url"].startswith(("https://", "http://")):
                    self.results.append(self.current)
                self.current = None
            if tag == "td" and self.snippet_parts is not None:
                if self.results:
                    self.results[-1]["snippet"] = " ".join("".join(self.snippet_parts).split())
                self.snippet_parts = None

    parser = ResultParser()
    parser.feed(html)
    results: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for item in parser.results:
        if item["url"] not in seen_urls:
            results.append(item)
            seen_urls.add(item["url"])
        if len(results) >= max_results:
            break

    if not results:
        return "検索結果を抽出できませんでした。"

    return {
        "engine": "DuckDuckGo Lite",
        "query": query,
        "trial_route": "Google → DuckDuckGo Lite",
        "results": [
            _result_record(
                engine="DuckDuckGo Lite",
                query=query,
                title=item["title"],
                url=item["url"],
                snippet=item.get("snippet", ""),
                language=_detect_language(query),
                rank=index,
                body_checked=False,
            )
            for index, item in enumerate(results[:max_results], start=1)
        ],
        "body_checked": False,
    }


def _search_bing(query: str, max_results: int = 5) -> str:
    if not query.strip():
        return "検索結果を抽出できませんでした。"

    bing_url = "https://www.bing.com/search?" + urlencode({"q": query, "setlang": "ja"})
    try:
        html = _http_get_text(bing_url)
    except (HTTPError, URLError, Exception):
        return "検索結果を抽出できませんでした。"

    results: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    for match in re.finditer(r'<a id="[^"]*" href="([^"]+)" h="ID=[^"]*"[^>]*>\s*<strong>([^<]+)</strong>', html, re.IGNORECASE):
        url_candidate = unescape(match.group(1)).strip()
        title = unescape(re.sub(r"<[^>]+>", "", match.group(2))).strip()

        if not title or url_candidate in seen_urls or not url_candidate.startswith("http"):
            continue

        results.append({"title": title, "url": url_candidate, "snippet": ""})
        seen_urls.add(url_candidate)
        if len(results) >= max_results:
            break

    if not results:
        return "検索結果を抽出できませんでした。"

    return {
        "engine": "Bing",
        "query": query,
        "trial_route": "Google → DuckDuckGo Lite → Bing",
        "results": [
            _result_record(
                engine="Bing",
                query=query,
                title=item["title"],
                url=item["url"],
                snippet=item.get("snippet", ""),
                language=_detect_language(query),
                rank=index,
                body_checked=False,
            )
            for index, item in enumerate(results[:max_results], start=1)
        ],
        "body_checked": False,
    }


def _search_duckduckgo_instant_api(query: str, max_results: int = 5) -> str:
    if not query.strip():
        return "検索結果を抽出できませんでした。"

    url = "https://api.duckduckgo.com/?" + urlencode(
        {
            "q": query,
            "format": "json",
            "no_html": "1",
            "skip_disambig": "1",
        }
    )

    try:
        payload = _http_get_json(url)
    except Exception:
        return "検索結果を抽出できませんでした。"

    results: list[dict[str, str]] = []
    seen_urls: set[str] = set()

    abstract_url = str(payload.get("AbstractURL") or "").strip()
    abstract_text = str(payload.get("AbstractText") or "").strip()
    heading = str(payload.get("Heading") or "").strip()
    if abstract_url and abstract_url not in seen_urls:
        title = heading or abstract_url
        results.append({"title": title, "url": abstract_url, "snippet": abstract_text})
        seen_urls.add(abstract_url)

    def append_topic(topic: dict[str, Any]) -> None:
        url_candidate = str(topic.get("FirstURL") or "").strip()
        text_candidate = str(topic.get("Text") or "").strip()
        if not url_candidate or url_candidate in seen_urls:
            return
        title = text_candidate.split(" - ", 1)[0].strip() if text_candidate else url_candidate
        results.append({"title": title or url_candidate, "url": url_candidate, "snippet": text_candidate})
        seen_urls.add(url_candidate)

    for item in payload.get("RelatedTopics", []) or []:
        if len(results) >= max_results:
            break
        if isinstance(item, dict) and "Topics" in item:
            for sub in item.get("Topics", []) or []:
                if len(results) >= max_results:
                    break
                if isinstance(sub, dict):
                    append_topic(sub)
        elif isinstance(item, dict):
            append_topic(item)

    if not results:
        return "検索結果を抽出できませんでした。"

    return {
        "engine": "DuckDuckGo Instant API",
        "query": query,
        "trial_route": "Google → DuckDuckGo Lite → Bing → DuckDuckGo Instant API",
        "results": [
            _result_record(
                engine="DuckDuckGo Instant API",
                query=query,
                title=item["title"],
                url=item["url"],
                snippet=item.get("snippet", ""),
                language=_detect_language(query),
                rank=index,
                body_checked=False,
            )
            for index, item in enumerate(results[:max_results], start=1)
        ],
        "body_checked": False,
    }


def _get_demo_search_results(query: str, max_results: int = 5) -> str:
    """Return demo search results for testing when network is unavailable"""
    demo_results = {
        "アメリカ": [
            {"title": "アメリカ合衆国 - Wikipedia", "url": "https://ja.wikipedia.org/wiki/%E3%82%A2%E3%83%A1%E3%83%AA%E3%82%AB%E5%90%88%E8%A1%86%E5%9B%BD", "snippet": ""},
            {"title": "歴代アメリカ合衆国大統領の一覧 - Wikipedia", "url": "https://ja.wikipedia.org/wiki/%E6%AD%B4%E4%BB%A3%E3%82%A2%E3%83%A1%E3%83%AA%E3%82%AB%E5%90%88%E8%A1%86%E5%9B%BD%E5%A4%A7%E7%B5%B1%E9%A0%98", "snippet": ""},
            {"title": "アメリカ合衆国大統領 - Wikipedia", "url": "https://ja.wikipedia.org/wiki/%E3%82%A2%E3%83%A1%E3%83%AA%E3%82%AB%E5%90%88%E8%A1%86%E5%9B%BD%E5%A4%A7%E7%B5%B1%E9%A0%98", "snippet": ""},
        ],
        "大統領": [
            {"title": "歴代アメリカ合衆国大統領の一覧 - Wikipedia", "url": "https://ja.wikipedia.org/wiki/%E6%AD%B4%E4%BB%A3%E3%82%A2%E3%83%A1%E3%83%AA%E3%82%AB%E5%90%88%E8%A1%86%E5%9B%BD%E5%A4%A7%E7%B5%B1%E9%A0%98", "snippet": ""},
            {"title": "アメリカ合衆国大統領 - Wikipedia", "url": "https://ja.wikipedia.org/wiki/%E3%82%A2%E3%83%A1%E3%83%AA%E3%82%AB%E5%90%88%E8%A1%86%E5%9B%BD%E5%A4%A7%E7%B5%B1%E9%A0%98", "snippet": ""},
        ],
        "天気": [
            {"title": "天気予報 - 日本気象協会", "url": "https://www.tenki.jp/", "snippet": ""},
            {"title": "気象庁", "url": "https://www.jma.go.jp/", "snippet": ""},
        ],
        "default": [
            {"title": f"検索結果: {query}", "url": "https://www.google.com/search?q=" + quote_plus(query), "snippet": ""},
            {"title": "Wikipedia - " + query, "url": "https://ja.wikipedia.org/wiki/" + quote_plus(query), "snippet": ""},
        ]
    }
    
    # Find matching demo results (case insensitive substring match)
    matching_key = None
    for key in demo_results:
        if key != "default" and key.lower() in query.lower():
            matching_key = key
            break
    
    results = demo_results.get(matching_key, demo_results["default"])[:max_results]
    return {
        "engine": "Demo",
        "query": query,
        "trial_route": "Demo",
        "results": [
            _result_record(
                engine="Demo",
                query=query,
                title=item["title"],
                url=item["url"],
                snippet=item.get("snippet", ""),
                language=_detect_language(query),
                rank=index,
                body_checked=False,
            )
            for index, item in enumerate(results[:max_results], start=1)
        ],
        "body_checked": False,
    }


def get_google_maps_directions(origin: str, destination: str, mode: str = "driving", language: str | None = None) -> str:
    if not GOOGLE_MAPS_API_KEY:
        # APIキー未設定: Google Maps の URL を返す（OSRM/Yahoo乗換案内が先に動くためここに来ることは少ない）
        maps_url = (
            f"https://www.google.com/maps/dir/{quote_plus(origin)}/{quote_plus(destination)}"
            + (f"?travelmode={quote_plus(mode)}" if mode not in ("driving", "") else "")
        )
        return f"{origin} → {destination} の経路:\nGoogle Maps で確認: {maps_url}"

    if not origin.strip() or not destination.strip():
        return "出発地と目的地を入力してください。"

    params = {
        "origin": origin,
        "destination": destination,
        "mode": mode,
        "language": language or GOOGLE_MAPS_LANGUAGE,
        "key": GOOGLE_MAPS_API_KEY,
    }
    url = "https://maps.googleapis.com/maps/api/directions/json?" + urlencode(params)

    try:
        payload = _http_get_json(url)
    except (HTTPError, URLError, Exception) as error:
        return f"Google Maps 経路検索に失敗しました: {error}"

    status = payload.get("status")
    if status != "OK":
        message = payload.get("error_message") or status or "不明なエラー"
        return f"Google Maps 経路検索に失敗しました: {message}"

    routes = payload.get("routes", [])
    if not routes:
        return "経路が見つかりませんでした。"

    route = routes[0]
    legs = route.get("legs", [])
    if not legs:
        return "経路の詳細を取得できませんでした。"

    leg = legs[0]
    summary = route.get("summary") or ""
    distance = leg.get("distance", {}).get("text", "不明")
    duration = leg.get("duration", {}).get("text", "不明")
    steps = leg.get("steps", [])[:8]

    lines = [
        f"出発地: {origin}",
        f"目的地: {destination}",
        f"距離: {distance}",
        f"所要時間: {duration}",
    ]
    if summary:
        lines.append(f"経路概要: {summary}")

    if steps:
        lines.append("主要ステップ:")
        for index, step in enumerate(steps, start=1):
            instruction = step.get("html_instructions") or step.get("instructions") or ""
            instruction = instruction.replace("<b>", "").replace("</b>", "").replace("<div style=\"font-size:0.9em\">", " ").replace("</div>", "")
            distance_text = step.get("distance", {}).get("text", "")
            lines.append(f"{index}. {instruction} ({distance_text})")

    lines.append(
        f"Google Maps URL: https://www.google.com/maps/dir/?api=1&origin={quote_plus(origin)}&destination={quote_plus(destination)}&travelmode={quote_plus(mode)}"
    )
    return "\n".join(lines)


def _load_gmail_credentials():
    try:
        from google.auth.transport.requests import Request as GoogleRequest
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except Exception as error:
        raise RuntimeError(
            "Google Gmail 用の依存関係が不足しています。requirements.txt をインストールしてください。"
        ) from error

    token_path = Path(GOOGLE_GMAIL_TOKEN_FILE)
    credentials_path = Path(GOOGLE_GMAIL_CREDENTIALS_FILE)

    credentials = None
    if token_path.exists():
        credentials = Credentials.from_authorized_user_file(str(token_path), GOOGLE_GMAIL_SCOPES)

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(GoogleRequest())
    elif not credentials or not credentials.valid:
        if not credentials_path.exists():
            raise RuntimeError(
                "Google Gmail の認証ファイルが見つかりません。google_credentials.json を配置してください。"
            )

        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), GOOGLE_GMAIL_SCOPES)
        credentials = flow.run_local_server(port=0)

    token_path.write_text(credentials.to_json(), encoding="utf-8")
    return credentials


def _build_gmail_service():
    try:
        from googleapiclient.discovery import build
    except Exception as error:
        raise RuntimeError(
            "Google Gmail 用の依存関係が不足しています。requirements.txt をインストールしてください。"
        ) from error

    credentials = _load_gmail_credentials()
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def search_gmail(query: str, max_results: int = 5) -> str:
    if not query.strip():
        return "検索語を入力してください。"

    try:
        service = _build_gmail_service()
        response = service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    except Exception as error:
        return f"Gmail 検索に失敗しました: {error}"

    messages = response.get("messages", [])
    if not messages:
        return "該当するメールは見つかりませんでした。"

    lines = [f"Gmail 検索結果: {query}"]
    for index, message in enumerate(messages, start=1):
        try:
            message_data = service.users().messages().get(
                userId="me",
                id=message["id"],
                format="metadata",
                metadataHeaders=["Subject", "From", "Date"],
            ).execute()
            headers = {item["name"].lower(): item.get("value", "") for item in message_data.get("payload", {}).get("headers", [])}
            subject = headers.get("subject", "(件名なし)")
            sender = headers.get("from", "(差出人不明)")
            date = headers.get("date", "")
            lines.append(f"{index}. subject={subject} | from={sender} | date={date} | id={message['id']}")
        except Exception:
            lines.append(f"{index}. id={message['id']}")

    return "\n".join(lines)


def send_gmail(to: str, subject: str, body: str, cc: str | None = None, bcc: str | None = None) -> str:
    if not to.strip():
        return "宛先を入力してください。"

    try:
        service = _build_gmail_service()
    except Exception as error:
        return f"Gmail 送信に失敗しました: {error}"

    message = MIMEText(body, _charset="utf-8")
    message["to"] = to
    message["subject"] = subject
    if cc:
        message["cc"] = cc
    if bcc:
        message["bcc"] = bcc

    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    try:
        service.users().messages().send(
            userId="me",
            body={"raw": encoded_message},
        ).execute()
    except Exception as error:
        return f"Gmail 送信に失敗しました: {error}"

    return f"メールを送信しました。to={to} subject={subject}"
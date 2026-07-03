from __future__ import annotations

import base64
import json
import os
import re
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, unquote_plus, urlencode, urlparse, parse_qs
from urllib.request import Request, urlopen

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

    if snippets:
        merged = " ".join(snippets)
        merged = re.sub(r"\s+", " ", merged).strip()
        if len(merged) > 180:
            merged = merged[:180].rstrip() + "..."
        return f"要約: {merged}" + followup

    if titles:
        return f"要約: {' / '.join(titles)}" + followup

    return "要約: 情報を抽出できませんでした。" + followup


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


def search_google_web(query: str, max_results: int = 5, language: str | None = None, country: str | None = None) -> str:
    if not query.strip():
        return "検索語を入力してください。"

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
                return _format_search_answer(query, results)

    ddg_url = "https://html.duckduckgo.com/html/?" + urlencode({"q": query})
    try:
        ddg_html = _http_get_text(ddg_url)
    except (HTTPError, URLError, Exception):
        return "検索結果を抽出できませんでした。Google の HTML が JS 前提で、代替検索も取得できませんでした。"

    results = _extract_search_results_from_duckduckgo(ddg_html, max_results=max_results)
    if not results:
        return "検索結果を抽出できませんでした。Google の HTML が JS 前提で、代替検索も取得できませんでした。"

    return _format_search_answer(query, results)


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
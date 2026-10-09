"""経路案内の目的地抽出とルート生成を行う関数群で、移動案内を支えます。"""

"""
transit.py — APIキー不要の経路検索モジュール

ドライブ/徒歩:  OpenStreetMap Nominatim（ジオコーディング）+ OSRM（経路計算）
公共交通:       Yahoo乗換案内 HTML スクレイピング
フォールバック: Google Maps API（GOOGLE_MAPS_API_KEY が設定されている場合のみ）
"""
from __future__ import annotations

import json
import os
import re
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from functions.location import get_location_details

TRANSIT_TIMEOUT = int(os.getenv("TRANSIT_TIMEOUT", "10"))
WALKING_MAX_MINUTES = 30

_HERE_WORDS = {"ここ", "現在地", "ここから", "いまいる場所", "今いる場所", "現在位置"}

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


def _build_google_maps_directions_url(origin: str, destination: str, travelmode: str | None = None) -> str:
    params = {
        "api": "1",
        "origin": (origin or "").strip(),
        "destination": (destination or "").strip(),
    }
    if travelmode:
        params["travelmode"] = travelmode
    return "https://www.google.com/maps/dir/?" + urlencode(params)


# ─────────────────────────────────────────────
# Nominatim: 住所 → (lat, lon)
# ─────────────────────────────────────────────

def _geocode(place: str) -> tuple[float, float] | None:
    """OpenStreetMap Nominatim で地名・住所を座標に変換する。"""
    params = urlencode({"q": place, "format": "json", "limit": 1, "accept-language": "ja"})
    url = f"https://nominatim.openstreetmap.org/search?{params}"
    req = Request(url, headers={"User-Agent": _UA})
    try:
        with urlopen(req, timeout=TRANSIT_TIMEOUT) as resp:
            results = json.loads(resp.read().decode("utf-8"))
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception:
        pass
    return None


def _label_from_location_details(details: dict | None) -> str:
    if not details:
        return "現在地"
    parts = [details.get("city"), details.get("region"), details.get("country")]
    parts = [p for p in parts if p]
    return " / ".join(parts) if parts else "現在地"


def _resolve_origin(
    origin: str,
    current_location: str = "",
    current_location_details: dict | None = None,
) -> tuple[str, tuple[float, float] | None, dict | None]:
    normalized_origin = (origin or "").strip()

    if (not normalized_origin) or (normalized_origin in _HERE_WORDS):
        details = current_location_details if isinstance(current_location_details, dict) else get_location_details()
        label = (current_location or "").strip() or _label_from_location_details(details)
        if details and details.get("latitude") is not None and details.get("longitude") is not None:
            return label, (float(details["latitude"]), float(details["longitude"])), details
        return label, None, details

    return normalized_origin, _geocode(normalized_origin), None


# ─────────────────────────────────────────────
# OSRM: 車・徒歩ルート（APIキー不要）
# ─────────────────────────────────────────────

def _osrm_route(
    origin_coord: tuple[float, float],
    dest_coord: tuple[float, float],
    profile: str = "driving",
) -> str:
    """OSRM パブリックAPIで経路を取得し整形して返す。profile は driving / foot。"""
    data = _osrm_route_data(origin_coord, dest_coord, profile=profile)
    if not data:
        return "ルートが見つかりませんでした。"

    mode_label = "車" if profile == "driving" else "徒歩"
    lines = [f"経路: {mode_label}で約{data['duration_min']}分（{data['distance_km']} km）"]

    for step_line in data.get("steps", [])[:8]:
        lines.append(step_line)

    return "\n".join(lines)


def _osrm_route_data(
    origin_coord: tuple[float, float],
    dest_coord: tuple[float, float],
    profile: str = "driving",
) -> dict | None:
    """OSRM から経路データを取得して最小限の情報を返す。"""
    lat1, lon1 = origin_coord
    lat2, lon2 = dest_coord
    url = (
        f"http://router.project-osrm.org/route/v1/{profile}/"
        f"{lon1},{lat1};{lon2},{lat2}"
        "?overview=false&steps=true&annotations=false"
    )
    req = Request(url, headers={"User-Agent": _UA})
    try:
        with urlopen(req, timeout=TRANSIT_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

    if payload.get("code") != "Ok":
        return None

    route = payload["routes"][0]
    duration_min = round(route["duration"] / 60)
    distance_km = round(route["distance"] / 1000, 1)
    lines: list[str] = []

    # ステップを最大8件表示
    for leg in route.get("legs", [])[:1]:
        for step in leg.get("steps", [])[:8]:
            maneuver = step.get("maneuver", {})
            maneuver_type = maneuver.get("type", "")
            modifier = maneuver.get("modifier", "")
            name = step.get("name", "")
            dist = round(step.get("distance", 0))
            if maneuver_type == "arrive":
                lines.append(f"  → 目的地に到着")
                continue
            direction = _maneuver_to_ja(maneuver_type, modifier)
            if name:
                lines.append(f"  {direction}「{name}」({dist}m)")
            elif direction:
                lines.append(f"  {direction} ({dist}m)")

    return {
        "duration_min": duration_min,
        "distance_km": distance_km,
        "steps": lines,
    }


def _maneuver_to_ja(m_type: str, modifier: str) -> str:
    table = {
        ("depart", ""): "出発",
        ("turn", "left"): "左折",
        ("turn", "right"): "右折",
        ("turn", "slight left"): "やや左",
        ("turn", "slight right"): "やや右",
        ("turn", "sharp left"): "大きく左折",
        ("turn", "sharp right"): "大きく右折",
        ("turn", "straight"): "直進",
        ("continue", ""): "直進",
        ("merge", "left"): "左に合流",
        ("merge", "right"): "右に合流",
        ("roundabout", ""): "ロータリー",
        ("exit roundabout", ""): "ロータリーを出る",
    }
    return table.get((m_type, modifier)) or table.get((m_type, "")) or m_type


# ─────────────────────────────────────────────
# Yahoo乗換案内: HTML スクレイピング（APIキー不要）
# ─────────────────────────────────────────────

def _yahoo_transit_scrape(origin: str, destination: str) -> str:
    """Yahoo乗換案内をスクレイピングして経路を返す。"""
    params = urlencode({"from": origin, "to": destination, "sf": 1, "al": 1, "shin": 1, "ex": 1, "hb": 1, "lb": 1, "sr": 1})
    url = f"https://transit.yahoo.co.jp/search/result?{params}"
    req = Request(url, headers={"User-Agent": _UA, "Accept-Language": "ja-JP,ja;q=0.9"})

    try:
        with urlopen(req, timeout=TRANSIT_TIMEOUT) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return f"（Yahoo乗換案内取得失敗: {e}）"

    # ルートブロックを抽出
    route_blocks = re.findall(
        r'<div[^>]+class="[^"]*routeWrap[^"]*"[^>]*>(.*?)</div>\s*</div>\s*</section>',
        html, re.DOTALL
    )
    if not route_blocks:
        # より広いパターンで再試行
        route_blocks = re.findall(
            r'<li[^>]+class="[^"]*routeList[^"]*"[^>]*>(.*?)</li>',
            html, re.DOTALL
        )

    if not route_blocks:
        return ""

    lines: list[str] = [f"乗換案内（Yahoo）: {origin} → {destination}"]

    for idx, block in enumerate(route_blocks[:3], start=1):
        text = unescape(re.sub(r"<[^>]+>", " ", block))
        text = re.sub(r"\s{2,}", " ", text).strip()
        if text:
            lines.append(f"\n--- ルート{idx} ---")
            # 時間・料金だけ抽出して表示
            time_m = re.search(r"(\d+)分", text)
            fare_m = re.search(r"(\d[\d,]+)円", text)
            transfer_m = re.search(r"乗換(\d+)回", text)
            if time_m:
                lines.append(f"所要時間: {time_m.group(1)}分")
            if transfer_m:
                lines.append(f"乗換: {transfer_m.group(1)}回")
            if fare_m:
                lines.append(f"料金: {fare_m.group(1)}円")

    # 路線情報も抽出
    line_names = re.findall(r'<span[^>]+class="[^"]*lineName[^"]*"[^>]*>([^<]+)</span>', html)
    if line_names:
        unique_lines = list(dict.fromkeys(ln.strip() for ln in line_names[:8] if ln.strip()))
        lines.append(f"路線: {' / '.join(unique_lines)}")

    # Google Mapsリンク
    lines.append(f"\nGoogle Mapsリンク:\n{_build_google_maps_directions_url(origin, destination, travelmode='transit')}")
    return "\n".join(lines)


def _yahoo_transit_summary(origin: str, destination: str) -> str:
    """Yahoo乗換案内の最短要約（所要時間・乗換回数・料金）を返す。"""
    params = urlencode({"from": origin, "to": destination, "sf": 1, "al": 1, "shin": 1, "ex": 1, "hb": 1, "lb": 1, "sr": 1})
    url = f"https://transit.yahoo.co.jp/search/result?{params}"
    req = Request(url, headers={"User-Agent": _UA, "Accept-Language": "ja-JP,ja;q=0.9"})

    try:
        with urlopen(req, timeout=TRANSIT_TIMEOUT) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return "公共交通機関: 取得できませんでした。"

    route_blocks = re.findall(
        r'<div[^>]+class="[^"]*routeWrap[^"]*"[^>]*>(.*?)</div>\s*</div>\s*</section>',
        html,
        re.DOTALL,
    )
    if not route_blocks:
        route_blocks = re.findall(
            r'<li[^>]+class="[^"]*routeList[^"]*"[^>]*>(.*?)</li>',
            html,
            re.DOTALL,
        )

    if not route_blocks:
        return "公共交通機関: 取得できませんでした。"

    block_text = unescape(re.sub(r"<[^>]+>", " ", route_blocks[0]))
    block_text = re.sub(r"\s{2,}", " ", block_text)

    time_m = re.search(r"(\d+)分", block_text)
    fare_m = re.search(r"(\d[\d,]+)円", block_text)
    transfer_m = re.search(r"乗換\s*(\d+)回", block_text)

    chunks = []
    if time_m and int(time_m.group(1)) > 0:
        chunks.append(f"約{time_m.group(1)}分")
    if transfer_m:
        chunks.append(f"乗換{transfer_m.group(1)}回")
    if fare_m:
        chunks.append(f"{fare_m.group(1)}円")

    if not chunks:
        return "公共交通機関: 取得できませんでした。"

    return "公共交通機関: " + " / ".join(chunks)


# ─────────────────────────────────────────────
# テキスト解析
# ─────────────────────────────────────────────

def _extract_from_to(text: str) -> tuple[str, str]:
    """テキストから出発地と目的地を抽出する。"""
    patterns = [
        r"(.+?)から(.+?)(?:まで|へ|に行|行き方|への)",
        r"(.+?)→(.+)",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(1).strip(), m.group(2).strip()
    return "", ""


def _extract_destination(text: str) -> str:
    """目的地だけ抽出する。"""
    m = re.search(r"(.+?)(?:まで|へ行く|に行く|行き方|への行き方|のルート|へのナビ)", text)
    return m.group(1).strip() if m else text.strip()


# ─────────────────────────────────────────────
# 公開API
# ─────────────────────────────────────────────

def navigate(origin: str, destination: str, mode: str = "driving") -> str:
    """
    車または徒歩の経路を返す。
    Nominatim でジオコーディングし OSRM で計算（APIキー不要）。
    OSRM 失敗時は Google Maps API にフォールバック（APIキーがある場合のみ）。
    """
    if not origin or not destination:
        return "出発地と目的地を指定してください。"

    orig_coord = _geocode(origin)
    dest_coord = _geocode(destination)

    if orig_coord and dest_coord:
        profile = "foot" if mode == "walking" else "driving"
        result = _osrm_route(orig_coord, dest_coord, profile=profile)
        if not result.startswith("（"):
            result += f"\n\nGoogle Maps: {_build_google_maps_directions_url(origin, destination, travelmode=mode)}"
            return result

    # フォールバック: Google Maps API（キーがある場合）
    from functions.google_workspace import get_google_maps_directions, GOOGLE_MAPS_API_KEY
    if GOOGLE_MAPS_API_KEY:
        return get_google_maps_directions(origin, destination, mode=mode)

    # 最終フォールバック: Google Maps URLのみ返す
    maps_url = _build_google_maps_directions_url(origin, destination, travelmode=mode)
    return f"{origin} → {destination} の経路:\nGoogle Mapsリンク:\n{maps_url}"


def search_transit(origin: str, destination: str) -> str:
    """
    公共交通機関の経路を返す。
    Yahoo乗換案内スクレイピングを優先し、失敗時は OSRM（徒歩）または Google Maps にフォールバック。
    """
    if not origin or not destination:
        return "出発地と目的地を指定してください。"

    # Yahoo乗換案内スクレイピング（APIキー不要）
    yahoo_result = _yahoo_transit_scrape(origin, destination)
    if yahoo_result and not yahoo_result.startswith("（"):
        return yahoo_result

    # フォールバック: Google Maps transit モード（APIキーがある場合）
    from functions.google_workspace import get_google_maps_directions, GOOGLE_MAPS_API_KEY
    if GOOGLE_MAPS_API_KEY:
        result = get_google_maps_directions(origin, destination, mode="transit")
        if "API key" not in result:
            return result

    # 最終フォールバック: 徒歩経路 + Google Maps URL
    walk = navigate(origin, destination, mode="walking")
    maps_url = _build_google_maps_directions_url(origin, destination, travelmode="transit")
    return f"{walk}\n\n電車ルートの詳細はこちら:\n{maps_url}"


def resolve_navigation(
    text: str,
    current_location: str = "",
    current_location_details: dict | None = None,
) -> str:
    """
    自然文からナビ/乗換案内を解決する。
    「〜から〜まで電車で」「〜への行き方」などを解析してルート検索する。
    """
    normalized = text.strip()

    origin_raw, destination = _extract_from_to(normalized)

    if not destination:
        destination = _extract_destination(normalized)

    origin_label, origin_coord, origin_details = _resolve_origin(
        origin_raw,
        current_location=current_location,
        current_location_details=current_location_details,
    )

    transit_keywords = ["電車", "乗換", "乗り換え", "路線", "地下鉄", "バス", "公共交通", "電車で", "バスで"]
    walking_keywords = ["歩い", "徒歩", "歩いて"]

    if any(kw in normalized for kw in transit_keywords):
        return search_transit(origin_label, destination)

    if any(kw in normalized for kw in walking_keywords):
        return navigate(origin_label, destination, mode="walking")

    # デフォルト: 車 + 公共交通 + 徒歩(30分以内のみ) をまとめて返す
    dest_coord = _geocode(destination)
    lines = [f"{origin_label} → {destination} の目安です。"]
    if origin_details and ((not origin_raw) or ((origin_raw or "").strip() in _HERE_WORDS)):
        provider = origin_details.get("provider") or "unknown"
        lat = origin_details.get("latitude")
        lon = origin_details.get("longitude")
        if lat is not None and lon is not None:
            lines.append(f"出発地推定: IPベースの概算（provider: {provider}, 緯度{lat}, 経度{lon}）")
        else:
            lines.append(f"出発地推定: IPベースの概算（provider: {provider}）")
        lines.append("地点が異なる場合は『新宿駅から京都駅まで』のように出発地を明示してください。")

    if origin_coord and dest_coord:
        car = _osrm_route_data(origin_coord, dest_coord, profile="driving")
        if car:
            lines.append(f"車: 約{car['duration_min']}分（{car['distance_km']} km）")
        else:
            lines.append("車: 取得できませんでした。")

        walk = _osrm_route_data(origin_coord, dest_coord, profile="foot")
        if walk and walk["duration_min"] <= WALKING_MAX_MINUTES:
            lines.append(f"徒歩: 約{walk['duration_min']}分（{walk['distance_km']} km）")

        lines.append(_yahoo_transit_summary(origin_label, destination))
    else:
        # 片方の座標が取れない場合でも公共交通は試す
        lines.append("車: 取得できませんでした。")
        lines.append(_yahoo_transit_summary(origin_label, destination))

    maps_url = _build_google_maps_directions_url(origin_label, destination)
    lines.append(f"Google Mapsリンク:\n{maps_url}")

    return "\n".join(lines)

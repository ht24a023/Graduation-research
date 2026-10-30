"""天気情報を取得して整形する関数群で、地域指定の天気質問に答えます。"""

import datetime
import json
import re
from urllib.parse import quote_plus
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

from functions.location import get_location_details


_WEATHER_GEOCODE_ALIASES = {
    "東京": ["東京都", "Tokyo"],
    "大阪": ["大阪市", "Osaka"],
    "札幌": ["札幌市", "Sapporo"],
    "福岡": ["福岡市", "Fukuoka"],
    "京都": ["京都市", "Kyoto"],
    "名古屋": ["名古屋市", "Nagoya"],
    "横浜": ["横浜市", "Yokohama"],
    "神戸": ["神戸市", "Kobe"],
}

_WMO_WEATHER_CODE_TEXTS = {
    0: "快晴",
    1: "晴れ",
    2: "晴れ時々くもり",
    3: "くもり",
    45: "霧",
    48: "着氷性の霧",
    51: "弱い霧雨",
    53: "霧雨",
    55: "強い霧雨",
    56: "弱い着氷性の霧雨",
    57: "強い着氷性の霧雨",
    61: "弱い雨",
    63: "雨",
    65: "強い雨",
    66: "弱い着氷性の雨",
    67: "強い着氷性の雨",
    71: "弱い雪",
    73: "雪",
    75: "強い雪",
    77: "雪粒",
    80: "弱いにわか雨",
    81: "にわか雨",
    82: "激しいにわか雨",
    85: "弱いにわか雪",
    86: "激しいにわか雪",
    95: "雷雨",
    96: "弱いひょうを伴う雷雨",
    99: "強いひょうを伴う雷雨",
}


def _weather_code_to_text(code):
    try:
        normalized_code = int(code)
    except (TypeError, ValueError):
        normalized_code = code

    if normalized_code in _WMO_WEATHER_CODE_TEXTS:
        return _WMO_WEATHER_CODE_TEXTS[normalized_code]

    return f"未対応の天気コード（コード: {normalized_code}）"


def _major_event_text(today):
    import calendar

    known = {
        (1, 1): "元日",
        (1, 7): "七草の節句",
        (1, 9): "成人の日",
        (2, 3): "節分",
        (2, 11): "建国記念の日",
        (2, 14): "バレンタインデー",
        (3, 3): "ひな祭り",
        (3, 14): "ホワイトデー",
        (3, 20): "春分の日",
        (4, 1): "エイプリルフール",
        (4, 29): "昭和の日",
        (5, 3): "憲法記念日",
        (5, 4): "みどりの日",
        (5, 5): "こどもの日",
        (6, 21): "夏至",
        (7, 7): "七夕",
        (7, 15): "海の日",
        (8, 11): "山の日",
        (8, 13): "お盆（迎え火の時期）",
        (8, 15): "終戦記念日",
        (9, 23): "秋分の日",
        (10, 31): "ハロウィン",
        (11, 3): "文化の日",
        (11, 23): "勤労感謝の日",
        (12, 21): "冬至",
        (12, 24): "クリスマスイブ",
        (12, 25): "クリスマス",
        (12, 31): "大晦日",
    }

    event = known.get((today.month, today.day))
    if event:
        return f"今日は{event}です。"

    return ""


def parse_weather_query(query: str):
    text = (query or "").strip()
    if not text:
        return {
            "date_kind": "today",
            "offset": 0,
            "location": None,
            "query_text": "",
            "target_date": datetime.date.today(),
        }

    normalized = text.replace("？", "?").replace("！", "!")
    normalized = normalized.replace("の天気は", "の天気")
    normalized = normalized.replace("の天候は", "の天候")
    normalized = normalized.replace("天気は", "天気")
    normalized = normalized.replace("天候は", "天候")
    normalized = normalized.replace("　", " ")
    normalized = re.sub(r"\s+", " ", normalized).strip()

    for date_token in ["明後日", "あさって", "明日", "あした", "今日", "きょう", "本日", "昨日", "きのう", "一昨日", "おととい"]:
        normalized = normalized.replace(date_token, "")
    normalized = re.sub(r"\d+\s*日後", "", normalized)
    normalized = re.sub(r"(明後日|あさって|明日|あした|今日|きょう|本日|昨日|きのう|一昨日|おととい)", "", normalized)
    normalized = re.sub(r"([A-Za-zぁ-んァ-ン一-龯ー])の(?=(?:天気|天候|$|[A-Za-zぁ-んァ-ン一-龯ー]))", r"\1", normalized)

    if re.search(r"(明後日|あさって)", text):
        date_kind = "day_after_tomorrow"
        offset = 2
    elif re.search(r"(明日|あした)", text):
        date_kind = "tomorrow"
        offset = 1
    elif re.search(r"(今日|きょう|本日)", text):
        date_kind = "today"
        offset = 0
    elif re.search(r"(昨日|きのう)", text):
        date_kind = "yesterday"
        offset = -1
    elif m := re.search(r"(\d+)\s*日後", text):
        date_kind = "days_after"
        offset = int(m.group(1))
    else:
        date_kind = "today"
        offset = 0

    location = None
    match = re.search(r"(?P<location>[A-Za-zぁ-んァ-ン一-龯ー]+?)(?:の天気|の天候|天気|天候)", normalized)
    if match:
        location = re.sub(r"^の+", "", match.group("location").strip())
    else:
        for pattern in [
            r"(?:[A-Za-zぁ-んァ-ン一-龯ー]+(?:市|県|府|都|区|町|村))",
            r"(?:[A-Za-zぁ-んァ-ン一-龯ー]+)",
        ]:
            candidate = re.search(pattern, normalized)
            if candidate:
                candidate_text = candidate.group(0).strip()
                if candidate_text not in {"今日", "明日", "明後日", "天気", "天候"}:
                    location = candidate_text
                    break

    if not location and "東京" in normalized:
        location = "東京"
    if not location and "大阪" in normalized:
        location = "大阪"
    if not location and "札幌" in normalized:
        location = "札幌"

    query_text = f"{location}の天気" if location else ""
    return {
        "date_kind": date_kind,
        "offset": offset,
        "location": location,
        "query_text": query_text,
        "target_date": datetime.date.today() + datetime.timedelta(days=offset),
    }


def _geocode_weather_location(location_name: str | None):
    if not location_name:
        return None

    query = location_name.strip()
    if not query:
        return None

    candidates = [query]
    for alias in _WEATHER_GEOCODE_ALIASES.get(query, []):
        if alias not in candidates:
            candidates.append(alias)

    for candidate in candidates:
        url = "https://geocoding-api.open-meteo.com/v1/search?" + "&".join([
            f"name={quote_plus(candidate)}",
            "count=1",
            "language=ja",
            "format=json",
        ])

        request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urlopen(request, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
            results = payload.get("results") or []
        except (HTTPError, URLError, Exception):
            continue

        if not results:
            continue

        result = results[0]
        return {
            "location_name": result.get("name") or query,
            "latitude": result.get("latitude"),
            "longitude": result.get("longitude"),
            "country": result.get("country") or "",
            "admin1": result.get("admin1") or "",
            "admin2": result.get("admin2") or "",
        }

    return None


def _format_weather_location_label(details, location_name: str | None):
    if location_name:
        return location_name
    if not details:
        return "現在地"

    parts = [part for part in [details.get("city"), details.get("region"), details.get("country")] if part]
    return " / ".join(parts) if parts else "現在地"


def _coerce_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_temperature(value):
    temp = _coerce_float(value)
    if temp is None:
        return None
    return f"{round(temp)}度"


def _fmt_percent(value):
    temp = _coerce_float(value)
    if temp is None:
        return None
    return f"{int(round(temp))}%"


def _fmt_precipitation(value):
    temp = _coerce_float(value)
    if temp is None:
        return None
    return f"{temp:.1f}mm"


def _fmt_wind_speed(value):
    temp = _coerce_float(value)
    if temp is None:
        return None
    return f"{temp:.1f}m/s"


def _fmt_wind_direction(value):
    temp = _coerce_float(value)
    if temp is None:
        return None
    degree = int(round(temp)) % 360
    labels = ["北", "北北東", "北東", "東北東", "東", "東南東", "南東", "南南東", "南", "南南西", "南西", "西南西", "西", "西北西", "北西", "北北西"]
    index = int((degree + 11.25) // 22.5) % 16
    return f"{labels[index]} ({degree}°)"


def _fmt_time(value):
    if value in (None, ""):
        return None
    try:
        dt = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.strftime("%H:%M")
    except ValueError:
        return None


def _daily_value(daily_payload, key, index):
    values = daily_payload.get(key)
    if values is None:
        return None
    if not isinstance(values, list):
        return values
    if index >= len(values):
        return None
    return values[index]


def _build_weather_response(details, location_label, target_date, weather_code, temperature, daily_max, daily_min, date_kind, request_url, current=None, daily=None, timezone_name=None, local_time_iso=None):
    weather_text = _weather_code_to_text(weather_code)
    date_label = {
        "today": "今日",
        "tomorrow": "明日",
        "day_after_tomorrow": "明後日",
        "yesterday": "昨日",
        "days_after": f"{(target_date - datetime.date.today()).days}日後",
    }.get(date_kind, "該当日")

    latitude = details.get("latitude") if isinstance(details, dict) else None
    longitude = details.get("longitude") if isinstance(details, dict) else None
    target_iso = target_date.isoformat()
    current_payload = current or {}
    daily_payload = daily or {}
    wind_direction = _coerce_float(current_payload.get("wind_direction_10m"))

    date_index = 0
    if date_kind != "today":
        times = daily_payload.get("time") or []
        if target_iso in times:
            date_index = times.index(target_iso)

    if date_kind == "today":
        current_temperature = _coerce_float(current_payload.get("temperature_2m"))
        current_humidity = _coerce_float(current_payload.get("relative_humidity_2m"))
        current_wind_speed = _coerce_float(current_payload.get("wind_speed_10m"))
        apparent = _coerce_float(current_payload.get("apparent_temperature"))
        precipitation_probability = _coerce_float(_daily_value(daily_payload, "precipitation_probability_max", 0))
        precipitation_sum = _coerce_float(_daily_value(daily_payload, "precipitation_sum", 0))
        humidity_value = current_humidity
        wind_speed = current_wind_speed
        wind_speed_label = "現在風速"
        if wind_speed is None:
            wind_speed = _coerce_float(_daily_value(daily_payload, "wind_speed_10m_max", 0))
            wind_speed_label = "予想最大風速"
        humidity_label = "現在湿度"
        sunrise = _daily_value(daily_payload, "sunrise", 0)
        sunset = _daily_value(daily_payload, "sunset", 0)
    else:
        current_temperature = None
        apparent = None
        precipitation_probability = _coerce_float(_daily_value(daily_payload, "precipitation_probability_max", date_index))
        precipitation_sum = _coerce_float(_daily_value(daily_payload, "precipitation_sum", date_index))
        humidity_value = _coerce_float(_daily_value(daily_payload, "relative_humidity_2m_max", date_index))
        wind_speed = _coerce_float(_daily_value(daily_payload, "wind_speed_10m_max", date_index))
        humidity_label = "予想最大湿度"
        wind_speed_label = "予想最大風速"
        sunrise = _daily_value(daily_payload, "sunrise", date_index)
        sunset = _daily_value(daily_payload, "sunset", date_index)

    lines = [f"{location_label}の{date_label}の天気は{weather_text}です。"]
    if current_temperature is not None and temperature is None:
        lines.append(f"現在気温：{_fmt_temperature(current_temperature)}")
    elif temperature is not None:
        lines.append(f"現在気温：{_fmt_temperature(temperature)}")
    if daily_max is not None:
        lines.append(f"最高気温：{_fmt_temperature(daily_max)}")
    if daily_min is not None:
        lines.append(f"最低気温：{_fmt_temperature(daily_min)}")
    if precipitation_probability is not None:
        lines.append(f"最大降水確率：{_fmt_percent(precipitation_probability)}")
    if precipitation_sum is not None:
        lines.append(f"予想降水量：{_fmt_precipitation(precipitation_sum)}")
    if humidity_value is not None:
        lines.append(f"{humidity_label}：{_fmt_percent(humidity_value)}")
    if wind_speed is not None:
        lines.append(f"{wind_speed_label}：{_fmt_wind_speed(wind_speed)}")
    wind_direction_text = _fmt_wind_direction(wind_direction)
    if wind_direction_text:
        lines.append(f"風向：{wind_direction_text}")
    if apparent is not None:
        lines.append(f"体感温度：{_fmt_temperature(apparent)}")
    if sunrise is not None:
        lines.append(f"日の出：{_fmt_time(sunrise)}")
    if sunset is not None:
        lines.append(f"日の入り：{_fmt_time(sunset)}")

    retrieval_time = datetime.datetime.now().strftime("%Y年%m月%d日 %H:%M")
    lines.append("")
    lines.append(f"情報源：Open-Meteo")
    if isinstance(details, dict) and details.get("provider"):
        lines.append(f"位置情報プロバイダー：{details.get('provider')}（IPベースの概算）")
        lines.append("地点が異なる場合は『大阪の天気』のように地域名を明示してください。")
    if latitude is not None and longitude is not None:
        lines.append(f"対象地点：{location_label}（緯度{latitude}、経度{longitude}）")
    else:
        lines.append(f"対象地点：{location_label}")
    if timezone_name:
        lines.append(f"タイムゾーン：{timezone_name}")
    if local_time_iso:
        lines.append(f"現地時刻：{_fmt_time(local_time_iso) or local_time_iso}")
    lines.append(f"予報対象日：{target_date.strftime('%Y年%m月%d日')}")
    lines.append(f"取得日時：{retrieval_time}")
    lines.append(f"参照URL：{request_url}")

    return "\n".join(lines)


def get_weather(query: str | None = None, current_location_details: dict | None = None):
    parsed = parse_weather_query(query)
    location_name = parsed.get("location")
    target_date = parsed.get("target_date") or datetime.date.today()
    date_kind = parsed.get("date_kind", "today")

    today = datetime.date.today()
    if date_kind == "yesterday":
        return "昨日の天気は予報APIでは取得できません。今日・明日・明後日・3日後〜15日後の範囲で指定してください。"

    if date_kind == "days_after":
        offset = int(parsed.get("offset") or 0)
        if offset > 15:
            return f"{location_name or '指定地域'}の{offset}日後は取得範囲外です。Open-Meteo では 16日以内の予報のみ対応しています。"

    if location_name:
        details = _geocode_weather_location(location_name)
        if not details:
            return "地域を特定できませんでした。地域名を再入力してください。"
        location_label = location_name
    else:
        details = current_location_details if isinstance(current_location_details, dict) else get_location_details()
        location_label = _format_weather_location_label(details, None)

    if details and details.get("latitude") is not None and details.get("longitude") is not None:
        latitude = details["latitude"]
        longitude = details["longitude"]
    else:
        return "地域を特定できませんでした。地域名を再入力してください。"

    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={latitude}&longitude={longitude}"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,relative_humidity_2m_max,wind_speed_10m_max,sunrise,sunset"
        "&current=temperature_2m,weather_code,relative_humidity_2m,apparent_temperature,wind_speed_10m,wind_direction_10m"
        "&temperature_unit=celsius"
        "&precipitation_unit=mm"
        "&wind_speed_unit=ms"
        "&timezone=auto"
        "&forecast_days=16"
    )

    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))

        current = payload.get("current", {})
        daily = payload.get("daily", {})
        timezone_name = payload.get("timezone")
        local_time_iso = current.get("time")
        weather_code = current.get("weather_code")
        temperature = current.get("temperature_2m")
        daily_max = daily.get("temperature_2m_max", [None])[0]
        daily_min = daily.get("temperature_2m_min", [None])[0]

        if date_kind != "today":
            day_values = daily.get("time", [])
            if day_values:
                target_iso = target_date.isoformat()
                if target_iso not in day_values:
                    return f"{location_label}の{target_date.isoformat()}は予報範囲外です。Open-Meteo では 16日以内の予報のみ取得できます。"
                index = day_values.index(target_iso)
                weather_code = (daily.get("weather_code") or [None])[index]
                daily_max = (daily.get("temperature_2m_max") or [None])[index]
                daily_min = (daily.get("temperature_2m_min") or [None])[index]
                temperature = None

        return _build_weather_response(
            details,
            location_label,
            target_date,
            weather_code,
            temperature,
            daily_max,
            daily_min,
            date_kind,
            url,
            current=current,
            daily=daily,
            timezone_name=timezone_name,
            local_time_iso=local_time_iso,
        )

    except (HTTPError, URLError, Exception):
        date_label = {
            "today": "今日",
            "tomorrow": "明日",
            "day_after_tomorrow": "明後日",
            "yesterday": "昨日",
            "days_after": f"{(target_date - datetime.date.today()).days}日後",
        }.get(date_kind, "該当日")
        base = f"{location_label}の{date_label}の天気は取得できませんでした。"
        footer = (
            f"\n\n情報源：Open-Meteo\n"
            f"対象地点：{location_label}（緯度{latitude}、経度{longitude}）\n"
            f"予報対象日：{target_date.strftime('%Y年%m月%d日')}\n"
            f"取得日時：{datetime.datetime.now().strftime('%Y年%m月%d日 %H:%M')}\n"
            f"参照URL：{url}"
        )
        return f"{base}{footer}"
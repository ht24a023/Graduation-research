import datetime
import json
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

from functions.location import get_current_location, get_location_details


def _weather_code_to_text(code):

    table = {
        0: "快晴",
        1: "ほぼ晴れ",
        2: "晴れ時々くもり",
        3: "くもり",
        45: "霧",
        48: "着氷性の霧",
        51: "弱い霧雨",
        53: "霧雨",
        55: "強い霧雨",
        61: "弱い雨",
        63: "雨",
        65: "強い雨",
        71: "弱い雪",
        73: "雪",
        75: "強い雪",
        77: "霰",
        80: "にわか雨",
        81: "強いにわか雨",
        82: "激しいにわか雨",
        95: "雷雨",
    }

    return table.get(code, "不明")


def _major_event_text(today):
    import calendar

    # Minimal mapping: only the specified well-known dates.
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


def get_weather():

    details = get_location_details()
    location_text = get_current_location()

    if not details or details.get("latitude") is None or details.get("longitude") is None:
        return f"{location_text}。本日の天候は取得できませんでした。"

    latitude = details["latitude"]
    longitude = details["longitude"]

    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={latitude}&longitude={longitude}"
        "&current=temperature_2m,weather_code"
        "&daily=temperature_2m_max,temperature_2m_min"
        "&timezone=auto"
    )

    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})

    try:

        with urlopen(request, timeout=8) as response:

            payload = json.loads(response.read().decode("utf-8"))

        current = payload.get("current", {})
        daily = payload.get("daily", {})

        temperature = current.get("temperature_2m")
        weather_code = current.get("weather_code")
        daily_max = daily.get("temperature_2m_max", [None])[0]
        daily_min = daily.get("temperature_2m_min", [None])[0]

        weather_text = _weather_code_to_text(weather_code)
        event_text = _major_event_text(datetime.date.today())

        parts = [f"{location_text}。", f"本日の天候は{weather_text}です。"]

        if temperature is not None:
            parts.append(f"現在気温は{round(float(temperature))}度です。")

        if daily_max is not None and daily_min is not None:
            parts.append(f"予想最高・最低気温は{round(float(daily_max))}度・{round(float(daily_min))}度です。")

        if event_text:
            parts.append(event_text)

        parts.append("これはローカル側で取得した天気のプロトタイプ応答です。")
        return "".join(parts)

    except (HTTPError, URLError, Exception):

        event_text = _major_event_text(datetime.date.today())
        base = f"{location_text}。本日の天候は取得できませんでした。"
        if event_text:
            return f"{base}{event_text}"

        return base
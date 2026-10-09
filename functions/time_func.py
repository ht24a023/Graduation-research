"""現在時刻や曜日を返す関数群で、日付・時間の質問に即答します。"""

import datetime
from functions.weather import _major_event_text


_WEEKDAY_NAMES = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日"]


def _format_weekday(offset_days: int, prefix: str) -> str:
    target_date = datetime.date.today() + datetime.timedelta(days=offset_days)
    weekday_name = _WEEKDAY_NAMES[target_date.weekday()]
    return f"{prefix}{weekday_name}です。"


def get_weekday():
    return _format_weekday(0, "今日は")


def get_weekday_from_text(text: str):
    normalized = (text or "").strip()

    if any(keyword in normalized for keyword in ["明後日", "あさって"]):
        return _format_weekday(2, "明後日は")

    if any(keyword in normalized for keyword in ["明日", "あした"]):
        return _format_weekday(1, "明日は")

    if any(keyword in normalized for keyword in ["昨日", "きのう"]):
        return _format_weekday(-1, "昨日は")

    if any(keyword in normalized for keyword in ["一昨日", "おととい"]):
        return _format_weekday(-2, "一昨日は")

    return get_weekday()


def get_time():
    now = datetime.datetime.now()
    weekday_name = _WEEKDAY_NAMES[now.weekday()]

    year = now.year
    month = now.month
    day = now.day
    hour = now.hour
    minute = now.minute

    # Base time string
    base = f"{year}年{month}月{day}日（{weekday_name}）、現在時刻は{hour}時{minute:02d}分です。"

    # Append today's event text if available (e.g., "今日は〇〇です。")
    try:
        event_text = _major_event_text(datetime.date(year, month, day))
    except Exception:
        event_text = ""

    if event_text:
        return f"{base}{event_text}"

    return base
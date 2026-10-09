"""入力文の意図を分類するモデルで、処理ルーティングを適切な機能へ振り分けます。"""

import re

from functions.weather import parse_weather_query
from models.text_normalizer import normalize_asr_text


_CALC_KEYWORDS = ["計算", "かける", "掛ける", "割る", "わる", "足す", "足して", "たす", "たして", "引く", "引いて", "ひく", "ひいて", "足し算", "掛け算", "割り算"]
_MATH_EXPR = re.compile(r"[0-9０-９]+\s*[+\-×xX*÷/／]\s*[0-9０-９]+")
_SAVE_CONTEXT_KEYWORDS = ["保存", "文書", "文章", "自己PR", "ES", "ガクチカ"]

# ナビ・経路（Google Maps / Yahoo乗換案内）
_NAVIGATION_KEYWORDS = [
    "ここから",
    "行き方", "行くには", "行くの", "行きたい", "行けます",
    "経路", "ルート", "ナビ", "案内",
    "乗換", "乗り換え", "乗り換える",
    "電車で", "バスで", "地下鉄で",
    "何分かかる", "どのくらいかかる", "どれくらい",
]
_NAVIGATION_PATTERN = re.compile(
    r"(?:ここから|現在地から|.+から).+?(?:まで|へ|に行)|.+?まで(?:何分|どのくらい|電車|バス|歩い|乗換|行き方|ルート|案内)?$"
)

# Web検索（Google検索に直接渡すべき事実確認系クエリ）
_SEARCH_KEYWORDS = [
    "とは", "ってなに", "って何", "について", "の意味",
    "調べて", "検索して", "検索", "調べ", "教えて", "何ですか", "なんですか",
    "最新", "ニュース", "いくら", "値段", "価格",
    "誰が", "誰は", "いつ", "どこで",
    "年収", "給与", "給料", "月収", "年俸", "平均年収",
    "英語の情報", "英語で", "英語を",
]

_MULTILINGUAL_SEARCH_PATTERNS = [
    r"\bsearch\b",
    r"search the web",
    r"summari[sz]e",
    r"请搜索",
    r"搜索并",
    r"搜索",
    r"总结",
    r"搜尋",
    r"検索して",
    r"調べて",
    r"검색",
    r"요약",
    r"区别",
    r"有什么区别",
    r"差异",
    r"장점과 단점",
]


def classify_intent(text: str) -> str:

    text = normalize_asr_text(text)
    parsed_weather = parse_weather_query(text)
    has_relative_day = bool(re.search(r"(明後日|あさって|明日|あした|今日|きょう|本日|昨日|きのう|一昨日|おととい|\d+\s*日後)", text))
    has_time_keyword = any(keyword in text for keyword in ["時間", "時刻", "何時", "曜日", "何日"])

    if any(keyword in text for keyword in ["明後日", "あさって", "明日", "あした", "昨日", "きのう", "一昨日", "おととい"]):
        if "曜日" in text or "何日" in text or "今日" in text:
            return "relative_weekday"

    if "曜日" in text:
        return "weekday"

    # ナビ・乗換案内（location より先に判定）
    if any(kw in text for kw in _NAVIGATION_KEYWORDS) or _NAVIGATION_PATTERN.search(text):
        return "navigation"

    if any(keyword in text for keyword in ["現在地", "どこ", "いる場所", "場所"]):
        return "location"

    in_save_context = any(k in text for k in _SAVE_CONTEXT_KEYWORDS)
    if _MATH_EXPR.search(text):
        return "calculate"
    if any(keyword in text for keyword in _CALC_KEYWORDS) and not in_save_context:
        return "calculate"

    if any(keyword in text for keyword in ["天気", "電気", "てんき"]):
        return "weather"

    if parsed_weather.get("location") and has_relative_day and not has_time_keyword:
        return "weather"

    # time-related queries: 時間 / 何時 / 今日 / 何日
    if any(k in text for k in ["時間", "何時", "今日", "何日"]):
        return "time"

    if re.search(r"(?:英語.*検索|検索.*英語|検索して|調べて|調査して)", text):
        return "search"

    lowered = text.lower()
    if any(re.search(pattern, lowered) for pattern in _MULTILINGUAL_SEARCH_PATTERNS):
        return "search"

    # Google Web検索に直接渡す事実確認系クエリ
    if any(kw in text for kw in _SEARCH_KEYWORDS):
        return "search"

    return "cloud"
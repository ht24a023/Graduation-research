import re

from models.text_normalizer import normalize_asr_text


_CALC_KEYWORDS = ["計算", "かける", "掛ける", "割る", "わる", "足す", "たす", "引く", "ひく", "足し算", "掛け算", "割り算"]
_MATH_EXPR = re.compile(r"[0-9０-９]+\s*[+\-×xX*÷/／]\s*[0-9０-９]+")
_SAVE_CONTEXT_KEYWORDS = ["保存", "文書", "文章", "自己PR", "ES", "ガクチカ"]

# ナビ・経路（Google Maps / Yahoo乗換案内）
_NAVIGATION_KEYWORDS = [
    "行き方", "行くには", "行くの", "行きたい", "行けます",
    "経路", "ルート", "ナビ", "案内",
    "乗換", "乗り換え", "乗り換える",
    "電車で", "バスで", "地下鉄で",
    "何分かかる", "どのくらいかかる", "どれくらい",
]
_NAVIGATION_PATTERN = re.compile(
    r"から.+?(?:まで|へ|に行)|.+?まで(?:何分|どのくらい|電車|バス|歩い|乗換)"
)

# Web検索（Google検索に直接渡すべき事実確認系クエリ）
_SEARCH_KEYWORDS = [
    "とは", "ってなに", "って何", "について", "の意味",
    "調べて", "検索して", "教えて", "何ですか", "なんですか",
    "最新", "ニュース", "いくら", "値段", "価格",
    "誰が", "誰は", "いつ", "どこで",
    "年収", "給与", "給料", "月収", "年俸", "平均年収",
]


def classify_intent(text: str) -> str:

    text = normalize_asr_text(text)

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

    # time-related queries: 時間 / 何時 / 今日 / 何日
    if any(k in text for k in ["時間", "何時", "今日", "何日"]):
        return "time"

    if any(keyword in text for keyword in ["天気", "電気", "てんき"]):
        return "weather"

    # Google Web検索に直接渡す事実確認系クエリ
    if any(kw in text for kw in _SEARCH_KEYWORDS):
        return "search"

    return "cloud"
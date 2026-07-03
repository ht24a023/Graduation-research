from functions.time_func import get_time, get_weekday, get_weekday_from_text
from functions.calculator import calculate
from functions.location import get_current_location
from functions.weather import get_weather
from functions.google_workspace import search_google_web
from functions.transit import resolve_navigation

from cloud.local_llm import ask_local_llm
from cloud.local_prompt import build_local_prompt
from models.text_normalizer import normalize_asr_text
import re


_GREETING_KEYWORDS = ["おはよう", "こんにちは", "こんばんは", "やあ", "元気", "調子"]
_THANKS_KEYWORDS = ["ありがとう", "助かった", "感謝"]

# パターンベースでローカル処理対象を判定する
_TIME_PATTERN = re.compile(r"時間|何時")
_WEEKDAY_PATTERN = re.compile(r"曜日")
_RELATIVE_DAY_PATTERN = re.compile(r"明後日|あさって|明日|あした|昨日|きのう|一昨日|おととい")
_WEATHER_PATTERN = re.compile(r"天気|てんき|天候")
_LOCATION_PATTERN = re.compile(r"現在地|どこ|場所|ここ")
_CALC_KEYWORDS = re.compile(r"計算|かける|掛ける|割る|わる|足す|たす|引く|ひく|足し算|掛け算|割り算")
_NAVIGATION_KEYWORDS = re.compile(r"行き方|行くには|経路|ルート|ナビ|乗換|乗り換え|電車で|バスで|何分かかる|どのくらいかかる")
_NAVIGATION_FROM_TO = re.compile(r"から.+?(?:まで|へ|に行)|.+?まで(?:何分|どのくらい|電車|バス|歩い|乗換)")
_SEARCH_KEYWORDS = re.compile(r"とは|ってなに|って何|について|の意味|調べて|検索して|最新|ニュース|いくら|値段|価格|誰が|誰は")

# 数式検出（数字と演算子の組み合わせ）
_MATH_EXPR = re.compile(r"[0-9０-９]+.*[+\-×xX*÷/／]")


def is_local_only_request(text: str) -> bool:

    normalized = normalize_asr_text(text)

    if not normalized:
        return True

    if _TIME_PATTERN.search(normalized):
        return True

    if _WEEKDAY_PATTERN.search(normalized):
        return True

    if _RELATIVE_DAY_PATTERN.search(normalized):
        return True

    if _WEATHER_PATTERN.search(normalized):
        return True

    if _LOCATION_PATTERN.search(normalized):
        return True

    if _CALC_KEYWORDS.search(normalized) or _MATH_EXPR.search(normalized):
        return True

    # ナビ・乗換は外部API必須なのでローカルオンリーから除外
    if _NAVIGATION_KEYWORDS.search(normalized) or _NAVIGATION_FROM_TO.search(normalized):
        return False

    # 検索系クエリも外部検索が最適なのでローカルオンリーから除外
    if _SEARCH_KEYWORDS.search(normalized):
        return False

    if any(keyword in normalized for keyword in _GREETING_KEYWORDS):
        return True

    if any(keyword in normalized for keyword in _THANKS_KEYWORDS):
        return True

    if len(normalized) <= 18 and ("?" in normalized or "？" in normalized):
        return True

    return False


def respond_local_only(text: str, conversation_history=None):

    normalized = normalize_asr_text(text)

    if _TIME_PATTERN.search(normalized):
        return get_time()

    if _WEEKDAY_PATTERN.search(normalized):
        return get_weekday()

    if _RELATIVE_DAY_PATTERN.search(normalized):
        return get_weekday_from_text(normalized)

    if _CALC_KEYWORDS.search(normalized) or _MATH_EXPR.search(normalized):
        return calculate(normalized)

    if _NAVIGATION_KEYWORDS.search(normalized) or _NAVIGATION_FROM_TO.search(normalized):
        return resolve_navigation(normalized)

    if _SEARCH_KEYWORDS.search(normalized):
        result = search_google_web(normalized)
        if result and not result.startswith("検索結果を抽出できませんでした"):
            return result
        # 検索失敗時はLLMへフォールバック
        prompt = build_local_prompt(normalized, conversation_history=conversation_history)
        return ask_local_llm(prompt)

    if _WEATHER_PATTERN.search(normalized):
        return get_weather()

    if _LOCATION_PATTERN.search(normalized):
        return get_current_location()

    if any(keyword in normalized for keyword in ["おはよう", "こんにちは", "こんばんは", "やあ"]):
        import datetime

        hour = datetime.datetime.now().hour

        if 5 <= hour < 12:
            return "おはようございます。"

        if 12 <= hour < 18:
            return "こんにちは。"

        return "こんばんは。"

    if any(keyword in normalized for keyword in _THANKS_KEYWORDS):
        return "どういたしまして。"

    prompt = build_local_prompt(normalized, conversation_history=conversation_history)
    response = ask_local_llm(prompt)

    if response.startswith("（Ollama") or response.startswith("（ローカルLLM") or response.startswith("（ローカルLLMエラー"):
        google_response = search_google_web(normalized)
        if google_response.startswith("Google 検索結果:"):
            return google_response

        return "ローカルAIは起動していますが、今はうまく返答できません。"

    return response
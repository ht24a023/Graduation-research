"""入力テキストの表記ゆれを整えるモデルで、後段の判定や抽出を安定させます。"""

import re


_REPLACEMENTS = {
    "今日の電気": "今日の天気",
    "明日の電気": "明日の天気",
    "電気は": "天気は",
    "電気": "天気",
}

# ASR に出がちなノイズフレーズ（不要なので除去）
_NOISE_PHRASES = [
    "ご視聴ありがとうございました",
]


def normalize_asr_text(text: str) -> str:

    normalized = (text or "").strip()

    for src, dst in _REPLACEMENTS.items():
        normalized = normalized.replace(src, dst)

    # remove known noise phrases entirely
    for p in _NOISE_PHRASES:
        normalized = normalized.replace(p, "")

    # remove obviously repeated short tokens from unstable partial/final ASR output
    normalized = re.sub(r"(私は[、,]?){3,}", "私は、", normalized)
    # remove immediate exact repeats of longer phrases (e.g. "ありがとうありがとう")
    # collapse repeated contiguous groups of length 6..100
    normalized = re.sub(r"(.{6,100}?)\1+", r"\1", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    return normalized
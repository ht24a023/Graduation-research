"""クラウドAIを使う時だけ接続を準備し、ローカル起動を妨げない。"""
from functools import lru_cache

from openai import OpenAI

from config import OPENAI_API_KEY
from models.execution_trace import traced_stage


@lru_cache(maxsize=1)
def _get_client(api_key):
    # 同じキーでは接続を再利用する。起動・画面表示時には作らない。
    return OpenAI(api_key=api_key)


@traced_stage('cloud_llm')
def ask_cloud_ai(text):
    api_key = (OPENAI_API_KEY or '').strip()
    if not api_key:
        raise RuntimeError(
            'クラウドAIのAPIキーが未設定です。.env の OPENAI_API_KEY を設定して再起動してください。'
        )

    response = _get_client(api_key).chat.completions.create(
        model='gpt-4.1-mini',
        messages=[{'role': 'user', 'content': text}],
    )
    return response.choices[0].message.content

"""クラウドAIを使う時だけ接続を準備し、ローカル起動を妨げない。"""
from functools import lru_cache
import time
from models.api_usage import api_usage
from models.request_control import RequestCancelled

from openai import OpenAI, AsyncOpenAI

from config import OPENAI_API_KEY
from cloud import model_catalog

CLOUD_MODEL = 'gpt-4.1-mini'
from models.execution_trace import traced_stage
from models.request_control import current_signal, run_cancellable


@lru_cache(maxsize=1)
def _get_client(api_key):
    # 同じキーでは接続を再利用する。起動・画面表示時には作らない。
    return OpenAI(api_key=api_key, timeout=60, max_retries=0)


@lru_cache(maxsize=8)
def _get_provider_client(api_key, base_url, timeout=60):
    return OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0)


def _ask_one(text):
    choice = model_catalog.current()
    provider = choice['provider']
    model_catalog.set_outcome({'choice':choice['id'],'provider':provider,'model':choice['model'],'free':choice['free'],'local':provider=='ollama_local','cloud_attempted':False})
    model = choice['model']
    api_key = ((model_catalog.read(model_catalog.CREDENTIALS).get('openai') or OPENAI_API_KEY or model_catalog.key(provider)) if provider=='openai' else model_catalog.key(provider)).strip()
    if provider=='ollama_local':
        from urllib.parse import urlparse
        if urlparse(__import__('config').OLLAMA_HOST).hostname not in ('localhost','127.0.0.1','::1'):
            raise RuntimeError('端末内Ollamaはlocalhostの接続先だけ利用できます。')
    base_url = {'openrouter':'https://openrouter.ai/api/v1', 'groq':'https://api.groq.com/openai/v1', 'ollama_local':__import__('config').OLLAMA_HOST.rstrip('/')+'/v1'}.get(provider)
    client_options = {'api_key':api_key, 'timeout':20 if choice['free'] and provider!='ollama_local' else 60, 'max_retries':0}
    if base_url:client_options['base_url']=base_url
    if provider=='groq' and not model_catalog.free_confirmed(provider):
        raise RuntimeError('Groq無料プラン専用アカウントの確認が必要です。モデル変更から設定してください。')
    if not api_key:
        raise RuntimeError(
            ('クラウドAIのAPIキーが未設定です。チャット右の「モデル変更」で'+({'openrouter':'OpenRouter','groq':'Groq'}.get(provider,'OpenAI'))+'のAPIキーを設定してください。')
        )

    call = None
    response = None
    status = 'error'
    started = time.monotonic()
    try:
        try: call = api_usage.begin(model, provider=provider, free=choice['free'], model_choice=choice['id'])
        except Exception: pass
        model_catalog.set_outcome({**model_catalog.outcome(),'cloud_attempted':True})
        if current_signal() is not None:
            async def request():
                nonlocal response
                async with AsyncOpenAI(**client_options) as client:
                    response = await client.chat.completions.create(
                        model=model, messages=[{'role': 'user', 'content': text}])
                    return _answer_text(response)
            answer = run_cancellable(request)
        else:
            client = _get_provider_client(api_key, base_url, client_options['timeout']) if base_url else _get_client(api_key)
            response = client.chat.completions.create(
                model=model, messages=[{'role': 'user', 'content': text}])
            answer = _answer_text(response)
        status = 'success'
        model_catalog.set_outcome({'choice':choice['id'],'provider':provider,'model':getattr(response,'model',model) if isinstance(getattr(response,'model',None),str) else model,'free':choice['free'],'local':provider=='ollama_local','cloud_attempted':True})
        return answer
    except RequestCancelled:
        status = 'cancelled'
        raise
    except Exception:
        status = 'invalid_response' if response is not None else 'error'
        raise
    finally:
        if call:
            try: api_usage.finish(call, response, status, time.monotonic()-started)
            except Exception: pass


def _answer_text(response):
    text = response.choices[0].message.content if response.choices else None
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError('クラウドAIが空の回答を返しました。')
    return text.strip()


@traced_stage('cloud_llm')
def ask_cloud_ai(text):
    model_catalog.clear_outcome()
    choice=model_catalog.current()
    if choice['provider']=='free_auto' or choice['free'] and choice['provider']!='ollama_local':
        from cloud.free_pool import generate
        return generate(text,_ask_one,preferred=None if choice['provider']=='free_auto' else choice['id'])
    return _ask_one(text)

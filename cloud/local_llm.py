"""ローカルLLMへの問い合わせをまとめる層で、外部通信を隠蔽して応答取得を簡単にします。"""

import json
import socket
import httpx
from collections.abc import Iterator
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

from config import OLLAMA_HOST, OLLAMA_MODEL, OLLAMA_TIMEOUT
from models.execution_trace import traced_stage
from models.request_control import current_signal, run_cancellable, RequestCancelled


def _build_request(prompt: str, temperature: float, stream: bool, response_format: str | None = None) -> Request:
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": stream,
        "options": {
            "temperature": temperature,
        },
    }

    if response_format:
        payload["format"] = response_format

    return Request(
        f"{OLLAMA_HOST.rstrip('/')}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )


async def _read_cancellable(request, timeout):
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(request.full_url, content=request.data,
                                     headers=dict(request.header_items()))
        response.raise_for_status()
        return response.json()


def _read_response(request, timeout):
    if current_signal() is not None:
        return run_cancellable(lambda: _read_cancellable(request, timeout))
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode('utf-8'))


@traced_stage('local_llm')
def ask_local_llm(prompt: str, temperature: float = 0.7, timeout: float | None = None) -> str:
    """Send a prompt to Ollama and return the assistant response.

    The caller can pass a prebuilt prompt string. If Ollama is unavailable,
    a readable error message is returned so the app can fall back gracefully.
    """

    request = _build_request(prompt, temperature=temperature, stream=False)
    effective_timeout = OLLAMA_TIMEOUT if timeout is None else timeout

    try:

        data = _read_response(request, effective_timeout)

        answer = data.get("response", "")
        if answer:
            return answer.strip()

        return "（ローカルLLM応答は空でした）"

    except RequestCancelled:
        raise
    except httpx.HTTPStatusError as error:
        return f"（Ollama HTTPエラー: {error.response.status_code}）"
    except httpx.TimeoutException as error:
        return f"（Ollamaタイムアウト: {error}）"
    except HTTPError as error:
        return f"（Ollama HTTPエラー: {error.code}）"

    except URLError as error:
        return f"（Ollama接続失敗: {error.reason}）"

    except TimeoutError as error:
        return f"（Ollamaタイムアウト: {error}）"

    except socket.timeout as error:
        return f"（Ollamaタイムアウト: {error}）"

    except Exception as error:
        return f"（ローカルLLMエラー: {error}）"


@traced_stage('local_llm')
def ask_local_llm_json(prompt: str, timeout: float | None = None) -> dict | None:
    request = _build_request(prompt, temperature=0.0, stream=False, response_format="json")
    effective_timeout = OLLAMA_TIMEOUT if timeout is None else timeout

    try:
        data = _read_response(request, effective_timeout)

        answer = str(data.get("response", "") or "").strip()
        if not answer:
            return None

        parsed = json.loads(answer)
        return parsed if isinstance(parsed, dict) else None
    except RequestCancelled:
        raise
    except Exception:
        return None


def stream_local_llm(prompt: str, temperature: float = 0.7, timeout: float | None = None) -> Iterator[str]:
    """Yield streamed text chunks from Ollama.

    This raises on transport errors so callers can classify retryable failures.
    """

    request = _build_request(prompt, temperature=temperature, stream=True)
    effective_timeout = OLLAMA_TIMEOUT if timeout is None else timeout

    if current_signal() is not None:
        import queue
        import threading
        from models.request_control import request_scope, check_cancelled
        signal = current_signal()
        values = queue.Queue(maxsize=64)
        def put(value):
            while True:
                check_cancelled()
                try:
                    values.put(value, timeout=0.025)
                    return
                except queue.Full:
                    pass
        async def read():
            async with httpx.AsyncClient(timeout=effective_timeout) as client:
                async with client.stream('POST', request.full_url, content=request.data,
                                         headers=dict(request.header_items())) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        data = json.loads(line)
                        if data.get('response'):
                            put(data['response'])
                        if data.get('done'):
                            break
        def worker():
            try:
                with request_scope(signal):
                    run_cancellable(read)
            except Exception as error:
                try:
                    values.put_nowait(error)
                except queue.Full:
                    pass
            finally:
                # Consumer can have gone away; do not wait on a full queue.
                try:
                    values.put_nowait(None)
                except queue.Full:
                    pass
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        try:
            while True:
                check_cancelled()
                try:
                    value = values.get(timeout=0.05)
                except queue.Empty:
                    if not thread.is_alive():
                        break
                    continue
                if value is None:
                    break
                if isinstance(value, Exception):
                    raise value
                yield value
        finally:
            if thread.is_alive():
                signal.set()
                thread.join(timeout=2)
        return
    with urlopen(request, timeout=effective_timeout) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue

            data = json.loads(line)
            chunk = data.get("response", "")
            if chunk:
                yield chunk

            if data.get("done"):
                break

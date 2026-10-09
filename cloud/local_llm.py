"""ローカルLLMへの問い合わせをまとめる層で、外部通信を隠蔽して応答取得を簡単にします。"""

import json
import socket
from collections.abc import Iterator
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

from config import OLLAMA_HOST, OLLAMA_MODEL, OLLAMA_TIMEOUT


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


def ask_local_llm(prompt: str, temperature: float = 0.7, timeout: float | None = None) -> str:
    """Send a prompt to Ollama and return the assistant response.

    The caller can pass a prebuilt prompt string. If Ollama is unavailable,
    a readable error message is returned so the app can fall back gracefully.
    """

    request = _build_request(prompt, temperature=temperature, stream=False)
    effective_timeout = OLLAMA_TIMEOUT if timeout is None else timeout

    try:

        with urlopen(request, timeout=effective_timeout) as response:
            data = json.loads(response.read().decode("utf-8"))

        answer = data.get("response", "")
        if answer:
            return answer.strip()

        return "（ローカルLLM応答は空でした）"

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


def ask_local_llm_json(prompt: str, timeout: float | None = None) -> dict | None:
    request = _build_request(prompt, temperature=0.0, stream=False, response_format="json")
    effective_timeout = OLLAMA_TIMEOUT if timeout is None else timeout

    try:
        with urlopen(request, timeout=effective_timeout) as response:
            data = json.loads(response.read().decode("utf-8"))

        answer = str(data.get("response", "") or "").strip()
        if not answer:
            return None

        parsed = json.loads(answer)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def stream_local_llm(prompt: str, temperature: float = 0.7, timeout: float | None = None) -> Iterator[str]:
    """Yield streamed text chunks from Ollama.

    This raises on transport errors so callers can classify retryable failures.
    """

    request = _build_request(prompt, temperature=temperature, stream=True)
    effective_timeout = OLLAMA_TIMEOUT if timeout is None else timeout

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

from pathlib import Path
p=Path('cloud/local_llm.py');s=p.read_text(encoding='utf-8');s=s.replace('import socket','import socket\nimport httpx',1);s=s.replace('from models.execution_trace import traced_stage', 'from models.execution_trace import traced_stage\nfrom models.request_control import current_signal, run_cancellable, RequestCancelled',1)
anchor="@traced_stage('local_llm')"
helper='''async def _read_cancellable(request, timeout):
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


'''
s=s.replace(anchor,helper+anchor,1)
s=s.replace('        with urlopen(request, timeout=effective_timeout) as response:\n            data = json.loads(response.read().decode("utf-8"))','        data = _read_response(request, effective_timeout)')
s=s.replace('    except HTTPError as error:', '    except RequestCancelled:\n        raise\n    except httpx.HTTPStatusError as error:\n        return f"（Ollama HTTPエラー: {error.response.status_code}）"\n    except httpx.TimeoutException as error:\n        return f"（Ollamaタイムアウト: {error}）"\n    except HTTPError as error:',1)
# JSON helper must never swallow cancellation.
start=s.index('def ask_local_llm_json');end=s.index('def stream_local_llm',start);part=s[start:end].replace('    except Exception:', '    except RequestCancelled:\n        raise\n    except Exception:');s=s[:start]+part+s[end:]
# Streaming uses a reader thread so the synchronous iterator yields each incoming chunk.
anchor='    with urlopen(request, timeout=effective_timeout) as response:\n        for raw_line in response:'
replacement='''    if current_signal() is not None:
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
                values.put(error)
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
        for raw_line in response:'''
assert anchor in s;s=s.replace(anchor,replacement,1);p.write_text(s,encoding='utf-8')
p=Path('cloud/openai_client.py');s=p.read_text(encoding='utf-8').replace('from openai import OpenAI','from openai import OpenAI, AsyncOpenAI',1).replace('from models.execution_trace import traced_stage','from models.execution_trace import traced_stage\nfrom models.request_control import current_signal, run_cancellable',1)
anchor="    response = _get_client(api_key).chat.completions.create("
branch='''    if current_signal() is not None:
        async def request():
            # Per-request client: cancellation never closes another chat's connection.
            async with AsyncOpenAI(api_key=api_key, max_retries=0) as client:
                response = await client.chat.completions.create(
                    model='gpt-4.1-mini', messages=[{'role': 'user', 'content': text}])
                return response.choices[0].message.content
        return run_cancellable(request)

'''
assert anchor in s;s=s.replace(anchor,branch+anchor,1);p.write_text(s,encoding='utf-8')
p=Path('requirements.txt');s=p.read_text(encoding='utf-8');s+='\nhttpx>=0.27,<1\n' if 'httpx' not in s else '';p.write_text(s,encoding='utf-8')

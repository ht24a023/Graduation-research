"""名前；真ん中: request-scoped cancellation of asynchronous HTTP transports."""
from contextlib import contextmanager, suppress
import asyncio
import threading

_state = threading.local()


class RequestCancelled(Exception):
    pass


def current_signal():
    return getattr(_state, 'signal', None)


def check_cancelled():
    signal = current_signal()
    if signal is not None and signal.is_set():
        raise RequestCancelled('要求は停止されました')


@contextmanager
def request_scope(signal):
    previous = current_signal()
    _state.signal = signal
    try:
        check_cancelled()
        yield
    finally:
        _state.signal = previous


def run_cancellable(factory):
    """Cancel the actual async task, await transport cleanup, then return to sync code."""
    signal = current_signal()
    check_cancelled()
    async def run():
        task = asyncio.create_task(factory())
        try:
            while not task.done():
                await asyncio.wait({task}, timeout=0.025)
                if signal is not None and signal.is_set():
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
                    raise RequestCancelled('推論通信を中断しました')
            if signal is not None and signal.is_set():
                raise RequestCancelled('要求は停止されました')
            return await task
        finally:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
    return asyncio.run(run())

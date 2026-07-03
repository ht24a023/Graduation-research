import asyncio
import time
from dataclasses import dataclass
from collections import deque
from scipy.signal import resample

import numpy as np
import sounddevice as sd
import re

from audio.transcriber import transcribe_buffer, transcribe_chunk
from audio.vad import SileroVADGate
from audio.speaker import is_speaking
from config import SAMPLERATE as DEFAULT_SAMPLE_RATE


@dataclass
class StreamConfig:
    sample_rate: int = DEFAULT_SAMPLE_RATE
    # chunk_size in samples (default ~32ms)
    # increase default chunk size to reduce callback frequency and avoid input overflow
    chunk_size: int = max(1024, int(DEFAULT_SAMPLE_RATE * 0.032))
    channels: int = 1
    dtype: str = "float32"


@dataclass
class UtteranceState:
    stable_text: str = ""
    partial_tail: str = ""
    stable_hits: int = 0
    speech_active: bool = False
    silence_chunks: int = 0
    voice_chunks: int = 0
    last_partial_candidate: str = ""

    def display_text(self):
        return f"{self.stable_text}{self.partial_tail}"

    def reset(self):
        self.stable_text = ""
        self.partial_tail = ""
        self.stable_hits = 0
        self.speech_active = False
        self.silence_chunks = 0
        self.voice_chunks = 0
        self.last_partial_candidate = ""

    def begin_speech(self):
        self.speech_active = True
        self.silence_chunks = 0

    def add_voice_chunk(self, chunk):
        self.voice_chunks += 1

    def add_silence_chunk(self):
        self.silence_chunks += 1

    def update_partial(self, candidate_text, max_tail_len=40):
        candidate_text = _normalize_text(candidate_text)

        if not candidate_text:
            return False

        if candidate_text == self.last_partial_candidate:
            self.stable_hits += 1
        else:
            self.stable_hits = 1

        self.last_partial_candidate = candidate_text

        prefix = _common_prefix(self.display_text(), candidate_text)
        stable_prefix = prefix.rstrip()
        tail = candidate_text[len(prefix):].lstrip()

        # limit tail length for stable display
        if len(tail) > max_tail_len:
            tail = tail[: max_tail_len - 1].rstrip() + "…"

        changed = (stable_prefix != self.stable_text) or (tail != self.partial_tail)

        self.stable_text = stable_prefix
        self.partial_tail = tail

        # If candidate has been stable for a few hits and tail is short, commit it
        if self.stable_hits >= 2 and len(self.partial_tail) <= 6:
            self.stable_text = _normalize_text(candidate_text)
            self.partial_tail = ""

        return changed

    def can_finalize(self, min_voice_chunks, min_stable_hits, end_silence_chunks):
        return (
            self.speech_active
            and self.voice_chunks >= min_voice_chunks
            and self.silence_chunks >= end_silence_chunks
            and self.stable_hits >= min_stable_hits
        )

    def finalize(self):
        final_text = _normalize_text(self.display_text())
        self.reset()
        return final_text


def _normalize_text(text):
    return " ".join(str(text).split()).strip()


def _common_prefix(left, right):
    limit = min(len(left), len(right))
    index = 0

    while index < limit and left[index] == right[index]:
        index += 1

    return left[:index]


class AudioStream:
    def __init__(self, config=None, loop=None):
        self.config = config or StreamConfig()
        self.loop = loop
        # limit queue size to avoid unbounded memory growth; drop incoming chunks when full
        self.queue = asyncio.Queue(maxsize=64)
        self.stream = None
        self.running = False
        self._dropped_chunks = 0

    def _callback(self, indata, frames, time, status):
        if status:
            print(status)

        chunk = np.array(indata, copy=True)

        if chunk.ndim == 2 and chunk.shape[1] > 1:
            chunk = chunk.mean(axis=1)
        else:
            chunk = chunk.reshape(-1)

        if self.loop is None:
            return

        # avoid blocking in callback; drop chunk if queue is full
        try:
            def _put_chunk():
                try:
                    self.queue.put_nowait(chunk.astype(np.float32, copy=False))
                except asyncio.QueueFull:
                    self._dropped_chunks += 1

            self.loop.call_soon_threadsafe(_put_chunk)
        except Exception:
            # best-effort: ignore callback errors
            pass

    async def start(self):
        if self.loop is None:
            self.loop = asyncio.get_running_loop()

        if self.running:
            return self

        self.stream = sd.InputStream(
            samplerate=self.config.sample_rate,
            channels=self.config.channels,
            blocksize=self.config.chunk_size,
            dtype=self.config.dtype,
            callback=self._callback,
        )
        self.stream.start()
        self.running = True
        return self

    async def stop(self):
        self.running = False

        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        if self._dropped_chunks > 0:
            print(f"[WARN] Dropped audio chunks during session: {self._dropped_chunks}")

    async def chunks(self):
        while self.running:
            chunk = await self.queue.get()
            yield chunk


class RealtimeSpeechPipeline:
    def __init__(
        self,
        config=None,
        speech_threshold=0.5,
        partial_window_seconds=1.5,
        end_silence_chunks=8,
        min_voice_chunks=6,
        min_stable_hits=2,
        partial_emit_min_chars=3,
        partial_tail_max_len=40,
        start_threshold=0.6,
        end_threshold=0.4,
        debug=False,
        energy_threshold=0.002,
        force_transcribe=False,
        partial_min_interval_sec=0.7,
    ):
        self.config = config or StreamConfig()
        self.audio_stream = AudioStream(self.config)
        # internal processing rate for VAD and ASR
        self.process_rate = 16000
        self.vad_gate = SileroVADGate(sample_rate=self.process_rate, threshold=speech_threshold)
        # smoothing buffer for VAD score to implement hysteresis
        self.score_buffer = deque(maxlen=8)
        self.start_threshold = start_threshold
        self.end_threshold = end_threshold

        # number of processed (resampled) chunks that make up the partial window
        # processed chunk length (samples) after resampling from config.sample_rate -> process_rate
        proc_chunk_len = max(1, int(self.config.chunk_size * self.process_rate / max(1, self.config.sample_rate)))
        self.partial_window_chunks = max(1, int((partial_window_seconds * self.process_rate) / proc_chunk_len))
        self.end_silence_chunks = end_silence_chunks
        self.min_voice_chunks = min_voice_chunks
        self.min_stable_hits = min_stable_hits
        self.partial_emit_min_chars = partial_emit_min_chars
        self.partial_tail_max_len = partial_tail_max_len
        self.current_chunks = []
        self.state = UtteranceState()
        self._last_emitted_display = ""
        self.debug = debug
        self.energy_threshold = energy_threshold
        self._using_energy_vad = False
        self._last_speech_decision = False
        self._last_using_energy_vad = False
        self.force_transcribe = force_transcribe
        self.partial_min_interval_sec = partial_min_interval_sec
        # max chunks to keep in memory when force_transcribe is enabled
        self._max_buffer_chunks = max(100, int(10 * (self.process_rate / max(1, self.config.chunk_size))))
        self._partial_task = None
        self._last_partial_started_at = 0.0

    async def start(self):
        await self.audio_stream.start()
        self.vad_gate.reset()
        self.state.reset()
        self.current_chunks = []
        return self

    async def stop(self):
        await self.audio_stream.stop()

    async def run(self, on_partial=None, on_final=None):
        await self.start()

        try:
            async for chunk in self.audio_stream.chunks():

                # Ignore microphone input while local TTS is speaking to reduce echo-loop ASR.
                if is_speaking():
                    self.current_chunks = []
                    self.state.reset()
                    self._last_emitted_display = ""
                    continue

                # resample to processing rate for VAD/ASR
                if self.config.sample_rate != self.process_rate:
                    new_len = int(len(chunk) * self.process_rate / self.config.sample_rate)
                    if new_len <= 0:
                        continue
                    chunk_proc = resample(chunk, new_len)
                else:
                    chunk_proc = chunk

                speech, score = self.vad_gate.detect(chunk_proc)

                # compute simple RMS for debug / fallback (use processed chunk)
                rms = float(np.sqrt(np.mean(np.asarray(chunk_proc, dtype=np.float32) ** 2))) if np.asarray(chunk_proc).size > 0 else 0.0

                # maintain score buffer and use averaged score for hysteresis
                if score is not None:
                    self.score_buffer.append(score)
                avg_score = float(np.mean(self.score_buffer)) if len(self.score_buffer) > 0 else 0.0

                # If model gives essentially zero score repeatedly, fall back to simple RMS-based VAD
                if avg_score <= 1e-6:
                    # use energy threshold
                    speech_decision = rms > self.energy_threshold
                    if speech_decision:
                        self._using_energy_vad = True
                else:
                    # decide speech based on smoothed score and thresholds
                    if avg_score >= self.start_threshold:
                        speech_decision = True
                    elif avg_score < self.end_threshold:
                        speech_decision = False
                    else:
                        speech_decision = speech

                # Only print VAD mode switches or speech state transitions to avoid noisy per-chunk logs
                if self.debug:
                    if self._using_energy_vad and not self._last_using_energy_vad:
                        print("[DEBUG] Using energy-based VAD (rms threshold)")
                    if speech_decision != self._last_speech_decision:
                        print(f"[DEBUG] speech_state change: {speech_decision} rms={rms:.5f} avg={avg_score:.3f}")
                    self._last_using_energy_vad = self._using_energy_vad
                    self._last_speech_decision = speech_decision

                # Append chunks when speech detected; when force_transcribe is enabled append always
                if speech_decision or self.force_transcribe:
                    if not self.state.speech_active:
                        self.state.begin_speech()

                    # store processed chunks for ASR (at process_rate)
                    self.state.add_voice_chunk(chunk_proc)
                    self.current_chunks.append(chunk_proc)
                    # cap buffer size to avoid unbounded growth
                    if len(self.current_chunks) > self._max_buffer_chunks:
                        self.current_chunks = self.current_chunks[-self._max_buffer_chunks:]

                    # Periodic partial emission based on sliding window
                    if len(self.current_chunks) >= self.partial_window_chunks:
                        now = time.monotonic()
                        can_start_partial = (
                            self._partial_task is None or self._partial_task.done()
                        ) and (
                            (now - self._last_partial_started_at) >= self.partial_min_interval_sec
                        )

                        if can_start_partial:
                            partial_audio = np.concatenate(self.current_chunks[-self.partial_window_chunks:])
                            self._last_partial_started_at = now

                            if self.force_transcribe:
                                await self._emit_partial_from_audio(partial_audio, on_partial)
                            else:
                                self._partial_task = asyncio.create_task(
                                    self._emit_partial_from_audio(partial_audio, on_partial)
                                )

                elif self.state.speech_active:
                    self.state.add_silence_chunk()

                    if self.state.can_finalize(
                        self.min_voice_chunks,
                        self.min_stable_hits,
                        self.end_silence_chunks,
                    ):
                        # cancel stale partial task before finalizing to avoid late/out-of-order updates
                        if self._partial_task is not None and not self._partial_task.done():
                            self._partial_task.cancel()
                            try:
                                await self._partial_task
                            except Exception:
                                pass
                            self._partial_task = None

                        await self._emit_final_from_chunks(self.current_chunks, on_final)

                        self.current_chunks = []
                        self.state.reset()
                        self._last_emitted_display = ""

        finally:
            await self.stop()

    async def _emit_partial_from_audio(self, audio, on_partial):
        try:
            result = await asyncio.to_thread(transcribe_chunk, audio, self.process_rate)
            # transcribe_chunk now returns (text, confidence)
            if isinstance(result, tuple) and len(result) == 2:
                text, conf = result
            else:
                text = result
                conf = None
        except Exception as e:
            if self.debug:
                print(f"[DEBUG] partial transcribe error: {e}")
            return

        if not text:
            return

        if self.state.update_partial(text, max_tail_len=self.partial_tail_max_len):
            display = self.state.display_text()
            diff = _emit_difference(self._last_emitted_display, display)
            if diff >= self.partial_emit_min_chars:
                self._last_emitted_display = display

                if on_partial is not None:
                    try:
                        asyncio.create_task(on_partial(display))
                    except Exception:
                        try:
                            on_partial(display)
                        except Exception:
                            pass

    async def _emit_final_from_chunks(self, chunks, on_final):
        try:
            result = await asyncio.to_thread(transcribe_buffer, chunks, self.process_rate)
            if isinstance(result, tuple) and len(result) == 2:
                final_text, conf = result
            else:
                final_text = result
                conf = None
        except Exception as e:
            if self.debug:
                print(f"[DEBUG] final transcribe error: {e}")
            return

        final_text = _normalize_text(final_text)
        if final_text:
                if on_final is not None:
                    try:
                        # pass text, confidence and raw chunks to handler for possible re-transcription
                        asyncio.create_task(on_final(final_text, conf, chunks))
                    except Exception:
                        try:
                            on_final(final_text, conf, chunks)
                        except Exception:
                            pass


async def _maybe_await(result):
    if asyncio.iscoroutine(result):
        await result


def _emit_difference(prev, curr):
    """Return a simple measure of difference between two strings (number of differing chars)."""
    if prev == curr:
        return 0

    # measure by longest common prefix and suffix
    lp = _common_prefix(prev, curr)
    # suffix
    prev_rev = prev[::-1]
    curr_rev = curr[::-1]
    ls = _common_prefix(prev_rev, curr_rev)

    diff = max(len(curr) - len(lp) - len(ls), 0)
    return diff

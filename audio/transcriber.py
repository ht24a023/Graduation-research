import os

import numpy as np
from faster_whisper import WhisperModel

from config import MODEL_SIZE


model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")


def _to_float32_mono(audio_chunk):
    audio = np.asarray(audio_chunk)

    if audio.ndim == 2:
        audio = audio.mean(axis=1)

    return audio.astype(np.float32, copy=False).reshape(-1)


def _segments_to_text(segments):
    return "".join(segment.text for segment in segments).strip()


def _compute_confidence_from_segments(segments, audio_dur):
    """Try to compute a confidence score [0..1] from segments when available.
    Falls back to heuristic based on text length and audio duration.
    """
    segments_list = list(segments)

    if not segments_list:
        return 0.0

    # try to use avg_logprob if the segments have it
    probs = []
    for seg in segments_list:
        v = getattr(seg, "avg_logprob", None)
        if v is not None:
            probs.append(v)

    if probs:
        # avg_logprob typically negative; map to [0,1] via logistic-ish transform
        avg = float(sum(probs) / len(probs))
        # clamp
        score = 1 / (1 + pow(2.7182818, - (avg + 5.0) / 2.0))
        return float(max(0.0, min(1.0, score)))

    # fallback heuristic: ratio of characters to audio seconds (chars per second)
    text = _segments_to_text(segments_list)
    chars = len(text)
    if audio_dur <= 0:
        return 0.0

    cps = chars / audio_dur
    # expect reasonable speech yields ~5-15 cps; map 0..15 -> 0..1
    score = max(0.0, min(1.0, (cps - 1.0) / 14.0))
    return float(score)


def transcribe_audio(path=None):
    """Transcribe `data/input_vad.wav` if available, otherwise use given path."""
    if path is None:
        cand = "data/input_vad.wav"
        path = cand if os.path.exists(cand) else "data/input.wav"

    try:
        segments, info = model.transcribe(
            path,
            beam_size=5,
            condition_on_previous_text=False,
            vad_filter=False,
            language="ja",
            task="transcribe",
        )
    except Exception:
        return ("", 0.0)

    segments = list(segments)
    text = _segments_to_text(segments)
    # attempt to determine audio duration from info if present, otherwise 0
    audio_dur = float(getattr(info, "duration", 0.0) if info is not None else 0.0)
    confidence = _compute_confidence_from_segments(segments, audio_dur)
    if not text:
        return ("", confidence)

    return (text, confidence)


def transcribe_chunk(audio_chunk, sample_rate=16000, beam_size=5):
    """Transcribe a short numpy chunk captured from the microphone."""
    audio = _to_float32_mono(audio_chunk)

    if audio.size == 0:
        return ""

    try:
        segments, info = model.transcribe(
            audio,
            beam_size=beam_size,
            condition_on_previous_text=False,
            vad_filter=False,
            language="ja",
            task="transcribe",
        )
    except Exception:
        dur = float(audio.size) / float(max(1, sample_rate))
        return ("", 0.0)

    segments = list(segments)
    text = _segments_to_text(segments)
    audio_dur = float(audio.size) / float(max(1, sample_rate))
    confidence = _compute_confidence_from_segments(segments, audio_dur)
    if not text:
        return ("", confidence)

    # If confidence is low for a short utterance, retry with larger beam
    if confidence < 0.35 and len(text) <= 40:
        try:
            segments2, info2 = model.transcribe(
                audio,
                beam_size=7,
                condition_on_previous_text=False,
                vad_filter=False,
                language="ja",
                task="transcribe",
            )
            segments2 = list(segments2)
            text2 = _segments_to_text(segments2)
            if text2 and len(text2) >= len(text):
                audio_dur = float(audio.size) / float(max(1, sample_rate))
                confidence2 = _compute_confidence_from_segments(segments2, audio_dur)
                return (text2, confidence2)
        except Exception:
            pass

    return (text, confidence)


def transcribe_buffer(audio_chunks, sample_rate=16000):
    """Transcribe a list of chunks by concatenating them first."""
    if not audio_chunks:
        return ""

    valid_chunks = [_to_float32_mono(chunk) for chunk in audio_chunks if np.asarray(chunk).size > 0]

    if not valid_chunks:
        return ""

    audio = np.concatenate(valid_chunks)

    if audio.size == 0:
        return ""

    try:
        segments, info = model.transcribe(
            audio,
            beam_size=5,
            condition_on_previous_text=False,
            vad_filter=False,
            language="ja",
            task="transcribe",
        )
    except Exception:
        total_samples = sum(a.size for a in valid_chunks)
        dur = float(total_samples) / float(max(1, sample_rate))
        return ("", 0.0)

    segments = list(segments)
    text = _segments_to_text(segments)
    total_samples = sum(a.size for a in valid_chunks)
    dur = float(total_samples) / float(max(1, sample_rate))
    confidence = _compute_confidence_from_segments(segments, dur)
    if not text:
        return ("", confidence)

    # Low-confidence fallback: retry with larger beam for short audios
    if confidence < 0.35 and len(text) <= 120:
        try:
            segments2, info2 = model.transcribe(
                audio,
                beam_size=7,
                condition_on_previous_text=False,
                vad_filter=False,
                language="ja",
                task="transcribe",
            )
            segments2 = list(segments2)
            text2 = _segments_to_text(segments2)
            if text2 and len(text2) >= len(text):
                total_samples = sum(a.size for a in valid_chunks) if 'valid_chunks' in locals() else audio.size
                dur = float(total_samples) / float(max(1, sample_rate))
                confidence2 = _compute_confidence_from_segments(segments2, dur)
                return (text2, confidence2)
        except Exception:
            pass

    return (text, confidence)


def transcribe_with_beam(audio, sample_rate=16000, beam=7):
    """Transcribe raw numpy audio with a specified beam size."""
    try:
        segments, info = model.transcribe(
            audio,
            beam_size=beam,
            condition_on_previous_text=False,
            vad_filter=False,
            language="ja",
            task="transcribe",
        )
    except Exception:
        return ("", 0.0)

    segments = list(segments)
    text = _segments_to_text(segments)
    dur = float(audio.size) / float(max(1, sample_rate))
    confidence = _compute_confidence_from_segments(segments, dur)
    return (text, confidence)

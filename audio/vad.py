import numpy as np
from scipy.io import wavfile
import os


def _to_mono_float32(audio_chunk):
    audio = np.asarray(audio_chunk)

    if audio.ndim == 2:
        audio = audio.mean(axis=1)

    return audio.astype(np.float32, copy=False).reshape(-1)


def _load_torch():
    try:
        import torch
    except ModuleNotFoundError:
        return None

    return torch


class SileroVADGate:
    def __init__(self, sample_rate=16000, threshold=0.5, device=None):
        self.sample_rate = sample_rate
        self.threshold = threshold
        self.device = device
        self.torch = _load_torch()
        self.model = None

        if self.torch is None:
            self.available = False
            return

        self.device = self.device or ("cuda" if self.torch.cuda.is_available() else "cpu")

        try:
            self.model, _utils = self.torch.hub.load(
                "snakers4/silero-vad",
                "silero_vad",
                force_reload=False,
            )
        except Exception:
            self.available = False
            return

        self.model = self.model.to(self.device)
        self.model.eval()
        self.available = True

    def reset(self):
        if self.available and hasattr(self.model, "reset_states"):
            self.model.reset_states()

    def detect(self, audio_chunk):
        if not self.available:
            audio = _to_mono_float32(audio_chunk)
            return bool(np.abs(audio).mean() > 0.01), 0.0

        audio = _to_mono_float32(audio_chunk)

        if audio.size == 0:
            return False, 0.0

        # Silero VAD requires a minimum input length; enforce by padding if needed.
        min_len = int(self.sample_rate / 31.25)
        if audio.size < min_len:
            padded = np.zeros(min_len, dtype=np.float32)
            padded[: audio.size] = audio
            audio_in = padded
        else:
            audio_in = audio

        tensor = self.torch.from_numpy(audio_in.astype(np.float32)).to(self.device)

        try:
            with self.torch.no_grad():
                speech_probability = float(self.model(tensor, self.sample_rate).item())
        except Exception:
            # If model still fails, fallback to simple energy-based detection
            energy = float(np.abs(audio).mean())
            return (energy > 0.01), 0.0

        return speech_probability >= self.threshold, speech_probability


def apply_vad(input_path, output_path, sampling_rate=16000, device=None):
    """Run Silero VAD on input_path and write voiced-only audio to output_path.

    Returns True if voiced segments were found and written, False otherwise.
    """
    torch = _load_torch()
    if torch is None:
        print("torch が見つからないため VAD をスキップします。")
        return False

    device = device or ("cuda" if torch.cuda.is_available() else "cpu")

    try:
        model, utils = torch.hub.load("snakers4/silero-vad", "silero_vad", force_reload=False)
    except Exception as e:
        raise RuntimeError("Failed to load Silero VAD model: %s" % e)

    # utils usually contains (get_speech_timestamps, save_audio, read_audio, _, collect_chunks)
    try:
        get_speech_timestamps, save_audio, read_audio, _, collect_chunks = utils
    except Exception:
        # fallback: try indexing
        get_speech_timestamps = utils[0]
        read_audio = utils[2]
        collect_chunks = utils[-1]

    # read and resample audio to target sampling_rate using the provided helper
    wav = read_audio(input_path, sampling_rate=sampling_rate)

    # get speech timestamps
    speech_timestamps = get_speech_timestamps(wav, model, sampling_rate=sampling_rate)

    if not speech_timestamps:
        return False

    chunks = collect_chunks(wav, speech_timestamps)

    if not chunks:
        return False

    concatenated = np.concatenate(chunks)

    # ensure float32 in -1..1
    if concatenated.dtype.kind == "f":
        scaled = (concatenated * 32767).astype(np.int16)
    else:
        scaled = concatenated.astype(np.int16)

    # ensure output folder exists
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    wavfile.write(output_path, sampling_rate, scaled)

    return True

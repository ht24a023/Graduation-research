import sounddevice as sd
from scipy.io.wavfile import write

from config import RECORD_SECONDS, SAMPLERATE
from audio.vad import apply_vad

def record_audio():

    print("録音中...")

    audio = sd.rec(
        int(RECORD_SECONDS * SAMPLERATE),
        samplerate=SAMPLERATE,
        channels=1
    )

    sd.wait()

    write("data/input.wav", SAMPLERATE, audio)

    print("録音終了")

    # Apply VAD to create a trimmed file at 16 kHz for downstream processing
    try:
        vad_out = "data/input_vad.wav"
        ok = apply_vad("data/input.wav", vad_out, sampling_rate=16000)
        if ok:
            print("VADで無音を削除しました: %s" % vad_out)
        else:
            print("VADで有音が検出されませんでした。元ファイルを使用します。")
    except Exception as e:
        print("VAD適用中にエラーが発生しました:", e)
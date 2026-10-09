"""アプリ全体の接続先・モデル名・実行設定をまとめる設定ファイルで、各モジュールの動作条件を統一します。"""

from dotenv import load_dotenv
import os

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Use base by default for better Japanese recognition quality.
# Override with MODEL_SIZE=tiny when latency is more important.
MODEL_SIZE = os.getenv("MODEL_SIZE", "base")

RECORD_SECONDS = 5

SAMPLERATE = 16000

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "60"))

# Confidence thresholds for routing
LOCAL_LLM_CONF_THRESHOLD = 0.55  # >= -> use local LLM
CLOUD_CONF_THRESHOLD = 0.35      # < -> use cloud LLM

# テキスト専用運用では未使用だが、過去設定との互換性のため残している音声フラグ
TTS_ENABLED = os.getenv("TTS_ENABLED", "false").lower() == "true"
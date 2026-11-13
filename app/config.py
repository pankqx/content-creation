"""Settings for Clipzer. Values come from a .env file in the project folder, or the environment."""
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
DATA = ROOT / "data"
JOBS = DATA / "jobs"
FONTS = ROOT / "assets" / "fonts"
PREFS = DATA / "prefs.json"

APP_NAME = "Clipzer"
OWNER = "K S Pankaj"
VERSION = "2.0"


def load_env() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()
JOBS.mkdir(parents=True, exist_ok=True)


def get(name: str, default: str = "") -> str:
    return os.environ.get(name, default) or default


# AI writer and judge. OpenRouter is used when a key is set; otherwise a local Ollama model if one is running.
OPENROUTER_API_KEY = get("OPENROUTER_API_KEY")
OPENROUTER_MODEL = get("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
OLLAMA_URL = get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = get("OLLAMA_MODEL", "gemma3:4b")

# Speech to text. "small" fits a 4 GB GPU such as the GTX 1650.
WHISPER_MODEL = get("WHISPER_MODEL", "small")
WHISPER_DEVICE = get("WHISPER_DEVICE", "auto")  # auto / cuda / cpu

# Fallback font for scripts the bundled fonts do not cover (Kannada, Hindi). Install with: sudo apt install fonts-noto
KANNADA_FONT = get("KANNADA_FONT", "Noto Sans Kannada")
HINDI_FONT = get("HINDI_FONT", "Noto Sans Devanagari")

MAX_UPLOAD_MB = int(get("MAX_UPLOAD_MB", "4096"))
MAX_SOURCE_MINUTES = int(get("MAX_SOURCE_MINUTES", "180"))

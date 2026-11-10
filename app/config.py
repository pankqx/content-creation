"""Settings for Clipzer. Values come from a .env file next to this project, or the environment."""
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
JOBS = ROOT / "data" / "jobs"

APP_NAME = "Clipzer"
OWNER = "K S Pankaj"


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
    return os.environ.get(name, default)


OPENROUTER_API_KEY = get("OPENROUTER_API_KEY")
# Any model id from openrouter.ai/models works. Ids ending in ":free" cost nothing.
OPENROUTER_MODEL = get("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
# tiny / base / small / medium. "small" fits a 4 GB GPU such as the GTX 1650.
WHISPER_MODEL = get("WHISPER_MODEL", "small")
WHISPER_DEVICE = get("WHISPER_DEVICE", "auto")  # auto / cuda / cpu
CAPTION_FONT = get("CAPTION_FONT", "Noto Sans")
MAX_UPLOAD_MB = int(get("MAX_UPLOAD_MB", "4096"))

"""Speech to text with word-level timestamps, using faster-whisper on the local machine."""
from __future__ import annotations

from typing import Callable, Optional

from . import config

_models: dict = {}


def available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def _load(device: str):
    from faster_whisper import WhisperModel

    if device not in _models:
        compute = "int8_float16" if device == "cuda" else "int8"
        _models[device] = WhisperModel(config.WHISPER_MODEL, device=device, compute_type=compute)
    return _models[device]


def _run(path: str, device: str, language: Optional[str], progress: Callable[[float], None]):
    model = _load(device)
    segments, info = model.transcribe(
        path, language=language or None, word_timestamps=True, vad_filter=True
    )
    total = max(info.duration or 1.0, 1.0)
    out = []
    for seg in segments:
        words = [
            {"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word.strip()}
            for w in (seg.words or [])
            if w.word.strip()
        ]
        out.append(
            {"start": round(seg.start, 3), "end": round(seg.end, 3), "text": seg.text.strip(), "words": words}
        )
        progress(min(seg.end / total, 1.0))
    return {"language": info.language, "duration": total, "segments": out}


def transcribe(path: str, language: Optional[str] = None, progress: Callable[[float], None] = lambda p: None):
    """Returns {"language", "duration", "segments": [{start, end, text, words: [{start, end, word}]}]}.

    Tries the GPU first and quietly falls back to the CPU if CUDA is missing or runs out of memory.
    """
    wanted = config.WHISPER_DEVICE
    devices = ["cuda", "cpu"] if wanted == "auto" else [wanted]
    last_error: Optional[Exception] = None
    for device in devices:
        try:
            return _run(path, device, language, progress)
        except Exception as error:  # CUDA libraries missing, out of memory, etc.
            last_error = error
            _models.pop(device, None)
    raise RuntimeError(f"Transcription failed: {last_error}")

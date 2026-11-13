"""One small door to a language model: OpenRouter if a key is set, else a local Ollama model, else nothing.

Every caller has a non-AI fallback, so the app works with neither.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Optional, Tuple

import requests

from . import config

_ollama_seen = {"ok": None, "at": 0.0}


def ollama_ready() -> bool:
    """Checks (at most every 30 s) whether Ollama is running with the configured model pulled."""
    now = time.time()
    if _ollama_seen["ok"] is not None and now - _ollama_seen["at"] < 30:
        return bool(_ollama_seen["ok"])
    ok = False
    try:
        tags = requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=1.5).json()
        names = {m.get("name", "") for m in tags.get("models", [])}
        want = config.OLLAMA_MODEL
        ok = want in names or f"{want}:latest" in names or any(n.split(":")[0] == want for n in names)
    except Exception:
        ok = False
    _ollama_seen.update(ok=ok, at=now)
    return ok


def engine() -> str:
    if config.OPENROUTER_API_KEY:
        return "openrouter"
    if ollama_ready():
        return "ollama"
    return "none"


def label() -> str:
    return {"openrouter": f"OpenRouter · {config.OPENROUTER_MODEL}", "ollama": f"Ollama · {config.OLLAMA_MODEL}"}.get(
        engine(), "Built-in"
    )


def chat(prompt: str, timeout: int = 150) -> Tuple[Optional[str], str]:
    """Returns (reply text or None, engine name). Never raises."""
    which = engine()
    try:
        if which == "openrouter":
            r = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}", "X-Title": config.APP_NAME},
                json={"model": config.OPENROUTER_MODEL, "temperature": 0.4,
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=timeout,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"], which
        if which == "ollama":
            r = requests.post(
                f"{config.OLLAMA_URL}/api/chat",
                json={"model": config.OLLAMA_MODEL, "stream": False, "options": {"temperature": 0.4},
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=timeout,
            )
            r.raise_for_status()
            return r.json()["message"]["content"], which
    except Exception:
        return None, which
    return None, "none"


def json_from(text: Optional[str]) -> Any:
    """Pulls the first JSON array or object out of a model reply."""
    if not text:
        return None
    text = re.sub(r"```(?:json)?", "", text)
    for pattern in (r"\[.*\]", r"\{.*\}"):
        match = re.search(pattern, text, re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                continue
    return None

"""Pick the moments worth clipping.

With an OpenRouter key, a language model reads the timestamped transcript and scores moments.
Without one (or if the call fails), a built-in scorer picks moments from hook words and pacing,
so the app always produces clips.
"""
from __future__ import annotations

import json
import re
from typing import List, Optional

import requests

from . import config

HOOK_WORDS = {
    "secret", "truth", "mistake", "never", "always", "nobody", "everyone", "why", "how", "money",
    "rich", "million", "billion", "crore", "lakh", "fail", "failed", "success", "lesson", "learned",
    "biggest", "worst", "best", "crazy", "insane", "story", "imagine", "problem", "reason", "rule",
    "first", "honestly", "actually", "remember", "important", "simple", "hard", "fear", "love",
    "hate", "quit", "fired", "started", "built", "sold", "lost", "won", "funny", "laugh",
}

PROMPT = """You are a short-form video editor. Below is a transcript split into numbered lines with timestamps.
Pick the {n} best moments to turn into vertical short clips of {lo}-{hi} seconds each.

A great clip:
- opens with a hook in its first 3 seconds (a bold claim, a question, tension, a punchline setup)
- is complete on its own: a viewer with no context understands it
- ends on a payoff (the insight, the punchline, the twist), not mid-thought

Reply with ONLY a JSON array. Each item:
{{"start_line": <int>, "end_line": <int>, "title": "<max 60 chars, curiosity-driven, no clickbait lies>",
"hook": "<the opening line of the clip>", "score": <0-100 viral potential>, "reason": "<one short sentence>"}}

Write title and reason in the same language as the transcript.

Transcript:
{lines}"""


def _fmt(t: float) -> str:
    return f"{int(t // 60):02d}:{int(t % 60):02d}"


def _ask_model(segments: List[dict], n: int, lo: int, hi: int) -> List[dict]:
    picks: List[dict] = []
    chunk, size, chunks = [], 0, []
    for i, seg in enumerate(segments):
        chunk.append((i, seg))
        size += len(seg["text"])
        if size > 24000:
            chunks.append(chunk)
            chunk, size = [], 0
    if chunk:
        chunks.append(chunk)
    per_chunk = max(2, -(-n * 2 // len(chunks)))  # ask for extra so the best can be kept
    for chunk in chunks:
        lines = "\n".join(f"[{i}] ({_fmt(s['start'])}-{_fmt(s['end'])}) {s['text']}" for i, s in chunk)
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}", "X-Title": config.APP_NAME},
            json={
                "model": config.OPENROUTER_MODEL,
                "temperature": 0.3,
                "messages": [{"role": "user", "content": PROMPT.format(n=per_chunk, lo=lo, hi=hi, lines=lines)}],
            },
            timeout=120,
        )
        response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"]
        match = re.search(r"\[.*\]", text, re.S)
        if not match:
            continue
        for item in json.loads(match.group(0)):
            try:
                a, b = int(item["start_line"]), int(item["end_line"])
            except (KeyError, TypeError, ValueError):
                continue
            if 0 <= a <= b < len(segments):
                picks.append(
                    {
                        "a": a, "b": b,
                        "title": str(item.get("title", "")).strip()[:80],
                        "hook": str(item.get("hook", "")).strip()[:160],
                        "score": max(0, min(100, int(float(item.get("score", 50) or 50)))),
                        "reason": str(item.get("reason", "")).strip()[:200],
                    }
                )
    return picks


def _score_text(text: str, duration: float) -> int:
    words = re.findall(r"\w+", text.lower())
    if not words:
        return 0
    hooks = sum(1 for w in words if w in HOOK_WORDS)
    first = " ".join(words[:12])
    score = 35
    score += min(25, hooks * 4)
    score += 10 if "?" in text[:160] else 0
    score += 8 if re.search(r"\d", text) else 0
    score += 8 if any(w in first.split() for w in HOOK_WORDS) else 0
    pace = len(words) / max(duration, 1)  # words per second; lively speech is about 2.5-3.5
    score += 10 if 2.2 <= pace <= 4.0 else 0
    score += 4 if text.rstrip().endswith((".", "!", "?")) else 0
    return max(0, min(100, score))


def _built_in(segments: List[dict], n: int, lo: int, hi: int) -> List[dict]:
    target = (lo + hi) / 2
    picks = []
    for a in range(len(segments)):
        b = a
        while b + 1 < len(segments) and segments[b]["end"] - segments[a]["start"] < target:
            b += 1
        duration = segments[b]["end"] - segments[a]["start"]
        if duration < lo * 0.6:
            continue
        text = " ".join(s["text"] for s in segments[a : b + 1])
        first = re.split(r"(?<=[.!?])\s", segments[a]["text"].strip())[0]
        picks.append(
            {
                "a": a, "b": b, "title": first[:60], "hook": first[:160],
                "score": _score_text(text, duration),
                "reason": "Picked by the built-in scorer (hook words, pacing, a clean ending).",
            }
        )
    return picks


def _fit(pick: dict, segments: List[dict], lo: int, hi: int, total: float) -> Optional[dict]:
    a, b = pick["a"], pick["b"]
    while segments[b]["end"] - segments[a]["start"] < lo and b + 1 < len(segments):
        b += 1
    while segments[b]["end"] - segments[a]["start"] < lo and a > 0:
        a -= 1
    while segments[b]["end"] - segments[a]["start"] > hi and b > a:
        b -= 1
    start = max(0.0, segments[a]["start"] - 0.15)
    end = min(total, segments[b]["end"] + 0.25)
    if end - start > hi:
        end = start + hi
    if end - start < 5:
        return None
    return {**pick, "a": a, "b": b, "start": round(start, 2), "end": round(end, 2)}


def find(transcript: dict, n: int = 6, lo: int = 25, hi: int = 50) -> dict:
    """Returns {"engine": "ai" | "built-in", "note": str, "clips": [...]} sorted best first."""
    segments = transcript["segments"]
    total = transcript.get("duration") or (segments[-1]["end"] if segments else 0)
    if not segments:
        return {"engine": "built-in", "note": "No speech was found in this video.", "clips": []}

    engine, note, picks = "built-in", "", []
    if config.OPENROUTER_API_KEY:
        try:
            picks = _ask_model(segments, n, lo, hi)
            engine = "ai"
        except Exception as error:
            note = f"AI picker failed ({str(error)[:120]}); used the built-in scorer."
    else:
        note = "No OpenRouter key set; used the built-in scorer."
    if not picks:
        engine = "built-in"
        picks = _built_in(segments, n, lo, hi)

    chosen: List[dict] = []
    for pick in sorted(picks, key=lambda p: -p["score"]):
        clip = _fit(pick, segments, lo, hi, total)
        if not clip:
            continue
        overlaps = any(min(clip["end"], c["end"]) - max(clip["start"], c["start"]) > 2 for c in chosen)
        if not overlaps:
            chosen.append(clip)
        if len(chosen) >= n:
            break
    return {"engine": engine, "note": note, "clips": chosen}

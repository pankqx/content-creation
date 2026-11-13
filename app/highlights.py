"""Finding the moments worth clipping, with a score you can read.

Every candidate is a run of whole sentences. It gets seven 0-100 scores, each with the evidence behind it:
hook, clarity, pacing, novelty, emotion, visuals and relevance. A genre preset weights them, your
thumbs-up / thumbs-down history nudges the weights, and if an AI model is available it re-reads the
shortlist and contributes 30% of the final score plus a better title.
"""
from __future__ import annotations

import json
import re
from typing import Dict, List, Optional

import numpy as np

from . import config, llm

DIMENSIONS = ["hook", "clarity", "pacing", "novelty", "emotion", "visual", "relevance"]
LABELS = {
    "hook": "Hook", "clarity": "Stands alone", "pacing": "Pacing", "novelty": "Novelty",
    "emotion": "Emotion", "visual": "Visual energy", "relevance": "Matches your focus",
}

GENRES: Dict[str, dict] = {
    "auto": {"label": "Auto", "weights": dict(hook=1.3, clarity=1.2, pacing=1.0, novelty=1.0, emotion=1.0, visual=0.6, relevance=1.0), "words": []},
    "podcast": {"label": "Podcast / interview", "weights": dict(hook=1.4, clarity=1.4, pacing=0.9, novelty=1.1, emotion=1.0, visual=0.3, relevance=1.0),
                "words": ["advice", "lesson", "learned", "truth", "realised", "realized", "mistake", "believe"]},
    "business": {"label": "Founders & business", "weights": dict(hook=1.4, clarity=1.3, pacing=0.9, novelty=1.3, emotion=0.8, visual=0.3, relevance=1.1),
                 "words": ["startup", "company", "revenue", "customers", "funding", "investor", "crore", "lakh", "million", "billion", "profit", "hire", "founder", "business", "market", "sales", "product"]},
    "comedy": {"label": "Comedy / stand-up", "weights": dict(hook=1.1, clarity=0.9, pacing=1.2, novelty=0.8, emotion=1.6, visual=0.7, relevance=0.9),
               "words": ["funny", "joke", "laugh", "crazy", "bro", "mom", "dad", "literally", "imagine", "wait"]},
    "education": {"label": "Education / explainer", "weights": dict(hook=1.2, clarity=1.5, pacing=1.0, novelty=1.3, emotion=0.6, visual=0.5, relevance=1.1),
                  "words": ["because", "means", "reason", "how", "why", "works", "example", "simple", "actually", "step"]},
    "motivation": {"label": "Motivation", "weights": dict(hook=1.4, clarity=1.1, pacing=1.0, novelty=0.8, emotion=1.5, visual=0.5, relevance=1.0),
                   "words": ["dream", "never", "quit", "discipline", "fear", "believe", "work", "life", "pain", "win", "success"]},
    "entertainment": {"label": "Entertainment / challenge", "weights": dict(hook=1.3, clarity=0.8, pacing=1.2, novelty=1.0, emotion=1.3, visual=1.3, relevance=0.9),
                      "words": ["win", "last", "challenge", "money", "dollars", "prize", "insane", "crazy", "seconds", "eliminated"]},
    "gaming": {"label": "Gaming", "weights": dict(hook=1.1, clarity=0.7, pacing=1.3, novelty=0.9, emotion=1.4, visual=1.4, relevance=0.9),
               "words": ["clutch", "kill", "win", "boss", "insane", "no way", "bro", "gg", "lets go", "what"]},
}

HOOK_WORDS = {
    "secret", "truth", "mistake", "never", "nobody", "everyone", "why", "how", "money", "rich", "million",
    "billion", "crore", "lakh", "fail", "failed", "success", "lesson", "biggest", "worst", "best", "crazy",
    "insane", "story", "imagine", "problem", "reason", "rule", "honestly", "actually", "stop", "wrong",
    "warning", "real", "first", "only", "hard", "fear", "quit", "fired", "lost", "won",
}
EMOTION_WORDS = {
    "love", "hate", "scared", "afraid", "cried", "cry", "angry", "shocked", "amazing", "terrible", "insane",
    "crazy", "unbelievable", "incredible", "hurt", "happy", "sad", "proud", "embarrassing", "wow", "omg",
    "damn", "hell", "literally", "absolutely", "never", "always", "worst", "best",
}
FILLER_START = {"so", "and", "but", "um", "uh", "like", "yeah", "okay", "ok", "right", "well", "also", "because"}
DANGLING_START = {"it", "that", "this", "he", "she", "they", "them", "those", "which", "there"}
STOP = set("""a an the of to in on for at by with from is are was were be been am i you we he she it they me my our your
their his her its this that these those and or but so if then than as not no do does did have has had can could would
should will just very really about into out up down over more most some any all what when where who how why which there
here get got go going gonna like know think yeah okay ok um uh one two""".split())


# ---------------------------------------------------------------- helpers

def _words(text: str) -> List[str]:
    return re.findall(r"[\w']+", text.lower(), flags=re.U)


def _sentences(segments: List[dict]) -> List[dict]:
    """Re-splits whisper segments into sentences using word timings, so windows start and end cleanly."""
    sentences, current = [], []
    for seg in segments:
        for w in seg.get("words") or []:
            current.append(w)
            if w["word"][-1:] in ".?!" and len(current) >= 3:
                sentences.append(current)
                current = []
    if current:
        sentences.append(current)
    if not sentences:  # transcript without word timings
        return [{"start": s["start"], "end": s["end"], "text": s["text"], "words": []} for s in segments]
    return [
        {"start": s[0]["start"], "end": s[-1]["end"], "text": " ".join(w["word"] for w in s), "words": s}
        for s in sentences
    ]


def _clamp(x: float) -> int:
    return int(max(0, min(100, round(x))))


def load_prefs() -> dict:
    try:
        return json.loads(config.PREFS.read_text(encoding="utf-8"))
    except Exception:
        return {"nudges": {d: 1.0 for d in DIMENSIONS}, "votes": 0}


def record_feedback(breakdown: dict, value: int) -> dict:
    """A thumbs-up moves weight toward the dimensions that clip was strong in; a thumbs-down away. Capped at ±30%."""
    prefs = load_prefs()
    nudges = prefs.setdefault("nudges", {d: 1.0 for d in DIMENSIONS})
    for d in DIMENSIONS:
        strength = (breakdown.get(d, {}).get("score", 50) - 50) / 50  # -1 .. 1
        nudges[d] = float(min(1.3, max(0.7, nudges.get(d, 1.0) + 0.04 * value * strength)))
    prefs["votes"] = prefs.get("votes", 0) + 1
    config.PREFS.parent.mkdir(parents=True, exist_ok=True)
    config.PREFS.write_text(json.dumps(prefs, indent=1), encoding="utf-8")
    return prefs


# ---------------------------------------------------------------- scoring

def _score(window: dict, ctx: dict) -> dict:
    text = window["text"]
    words = _words(text)
    n = max(len(words), 1)
    dur = max(window["end"] - window["start"], 1.0)
    first = words[:14]
    out: Dict[str, dict] = {}

    # Hook: does the opening create a question or tension?
    s, why = 40.0, []
    hooks = [w for w in first if w in HOOK_WORDS]
    if hooks:
        s += min(30, 12 * len(hooks)); why.append(f"opens with “{hooks[0]}”")
    if "?" in " ".join(w["word"] for w in window["words"][:16]) or (first and first[0] in {"why", "how", "what", "who"}):
        s += 15; why.append("opens with a question")
    if any(ch.isdigit() for ch in " ".join(first)):
        s += 10; why.append("a number up front")
    if first and first[0] in {"you", "your"} or "you" in first[:5]:
        s += 8; why.append("speaks to the viewer")
    if first and first[0] in FILLER_START:
        s -= 18; why.append(f"starts on a filler word (“{first[0]}”)")
    out["hook"] = {"score": _clamp(s), "why": why or ["plain opening"]}

    # Clarity: whole sentences, no missing context.
    s, why = 60.0, []
    if text.rstrip()[-1:] in ".?!":
        s += 15; why.append("ends on a complete sentence")
    else:
        s -= 15; why.append("ends mid-sentence")
    if first and first[0] in DANGLING_START:
        s -= 20; why.append(f"starts with “{first[0]}”, which needs earlier context")
    if ctx["sentences_in"] >= 2:
        s += 8
    if n < 25:
        s -= 15; why.append("very little speech")
    out["clarity"] = {"score": _clamp(s), "why": why or ["self-contained"]}

    # Pacing: lively speech, few dead gaps.
    wps = n / dur
    gaps = sum(1 for a, b in zip(window["words"], window["words"][1:]) if b["start"] - a["end"] > 0.8)
    s = 100 - abs(wps - 3.0) * 28 - gaps * 7
    out["pacing"] = {"score": _clamp(s), "why": [f"{wps:.1f} words a second", f"{gaps} long pause{'s' if gaps != 1 else ''}"]}

    # Novelty: specifics like numbers and less common words.
    content = [w for w in words if w not in STOP and len(w) > 2]
    rare = [w for w in content if ctx["df"].get(w, 0) <= 2 and len(w) >= 6]
    numbers = re.findall(r"\d[\d,.]*", text)
    s = 35 + min(30, len(rare) * 3) + min(25, len(numbers) * 8)
    why = []
    if numbers: why.append(f"specific numbers ({', '.join(numbers[:3])})")
    if rare: why.append(f"distinct words: {', '.join(rare[:3])}")
    out["novelty"] = {"score": _clamp(s), "why": why or ["general talk"]}

    # Emotion: emotional language, exclamations, loud peaks, laughter/applause bursts.
    s, why = 35.0, []
    emo = [w for w in words if w in EMOTION_WORDS]
    if emo:
        s += min(25, len(emo) * 6); why.append(f"emotional words ({', '.join(sorted(set(emo))[:3])})")
    if "!" in text:
        s += 8; why.append("exclamations")
    peak, bursts = ctx["audio"](window["start"], window["end"])
    if peak is not None:
        s += max(-10, min(20, peak * 4))
        if peak > 2: why.append("louder than the rest of the video")
    if bursts:
        s += min(20, bursts * 5); why.append("laughter or applause-like bursts")
    out["emotion"] = {"score": _clamp(s), "why": why or ["calm delivery"]}

    # Visual energy: cuts in the picture.
    cuts = sum(1 for t in ctx["cuts"] if window["start"] <= t <= window["end"])
    per_min = cuts / dur * 60
    s = 45 + min(40, per_min * 4) if ctx["has_cuts"] else 50
    out["visual"] = {"score": _clamp(s), "why": [f"{cuts} camera cut{'s' if cuts != 1 else ''}"] if ctx["has_cuts"] else ["single-camera video"]}

    # Relevance: your focus request and the genre's vocabulary.
    focus = ctx["focus_words"]
    hits = [w for w in words if w in focus] if focus else []
    genre_hits = [w for w in words if w in ctx["genre_words"]]
    s = 50 + min(35, len(set(hits)) * 12) + min(15, len(genre_hits) * 3)
    why = []
    if hits: why.append(f"mentions {', '.join(sorted(set(hits))[:3])}")
    if genre_hits: why.append(f"{ctx['genre_label'].lower()} vocabulary")
    out["relevance"] = {"score": _clamp(s), "why": why or ["no focus given" if not focus else "doesn't mention your focus"]}
    return out


def _total(breakdown: dict, weights: dict) -> int:
    num = sum(breakdown[d]["score"] * weights[d] for d in DIMENSIONS)
    mean = num / sum(weights[d] for d in DIMENSIONS)
    return _clamp(50 + (mean - 50) * 1.6)


def _overlap(a: dict, b: dict) -> float:
    inter = min(a["end"], b["end"]) - max(a["start"], b["start"])
    return max(0.0, inter) / max(1e-6, min(a["end"] - a["start"], b["end"] - b["start"]))


# ---------------------------------------------------------------- AI pass

AI_PROMPT = """You are a senior short-form video editor. Rate each candidate clip below for how well it works
as a standalone vertical short: a hook in the first 3 seconds, understandable with no context, and a payoff at the end.
{focus}
Reply with ONLY a JSON array, one object per candidate, in this shape:
[{{"id": <number>, "score": <0-100>, "title": "<curiosity-driven title, max 60 characters, no false claims>", "reason": "<one short sentence>"}}]
Write title and reason in the same language as the clip.

Candidates:
{items}"""


def _ai_pass(shortlist: List[dict], focus: str) -> str:
    if not shortlist or llm.engine() == "none":
        return "none"
    items = "\n\n".join(f"[{i}] ({c['end'] - c['start']:.0f}s) {c['text'][:1200]}" for i, c in enumerate(shortlist))
    focus_line = f'The creator asked for: "{focus}". Prefer clips that match it.' if focus else ""
    reply, engine = llm.chat(AI_PROMPT.format(items=items, focus=focus_line))
    data = llm.json_from(reply)
    if not isinstance(data, list):
        return "failed"
    for item in data:
        try:
            c = shortlist[int(item["id"])]
            c["ai_score"] = _clamp(float(item.get("score", 50)))
            title = str(item.get("title", "")).strip().strip('"')
            if title:
                c["title"] = title[:80]
            if item.get("reason"):
                c["ai_reason"] = str(item["reason"]).strip()[:200]
        except Exception:
            continue
    return engine


# ---------------------------------------------------------------- main entry

def find(transcript: dict, n: int = 6, lo: int = 25, hi: int = 50, genre: str = "auto", focus: str = "",
         audio_info: Optional[dict] = None, cuts: Optional[list] = None) -> dict:
    """Returns {"engine", "note", "clips": [...]} sorted best first.

    Each clip: start, end, title, hook, score, reason, breakdown {dimension: {score, why}}.
    """
    segments = transcript.get("segments") or []
    total_dur = transcript.get("duration") or (segments[-1]["end"] if segments else 0)
    if not segments:
        return {"engine": "built-in", "note": "No speech was found in this video.", "clips": []}

    sentences = _sentences(segments)
    df: Dict[str, int] = {}
    for s in sentences:
        for w in set(_words(s["text"])):
            df[w] = df.get(w, 0) + 1

    db = np.array((audio_info or {}).get("db") or [], dtype=np.float32)
    burst = np.array((audio_info or {}).get("burst") or [], dtype=bool)
    median = float(np.median(db)) if len(db) else 0.0
    rate = (audio_info or {}).get("rate", 10)

    def audio_at(start: float, end: float):
        if not len(db):
            return None, 0
        a, b = int(start * rate), max(int(end * rate), int(start * rate) + 1)
        part = db[a:b]
        if not len(part):
            return None, 0
        peak = float(np.percentile(part, 90) - median) / 3.0
        bursts = int(np.sum(np.diff(burst[a:b].astype(int)) == 1)) if len(burst) else 0
        return peak, bursts

    g = GENRES.get(genre, GENRES["auto"])
    nudges = load_prefs().get("nudges", {})
    weights = {d: g["weights"][d] * float(nudges.get(d, 1.0)) for d in DIMENSIONS}
    focus_words = {w for w in _words(focus) if w not in STOP and len(w) > 2}
    if focus_words:
        weights["relevance"] *= 2.2
    ctx = {"df": df, "audio": audio_at, "cuts": cuts or [], "has_cuts": bool(cuts), "focus_words": focus_words,
           "genre_words": set(g["words"]), "genre_label": g["label"], "sentences_in": 0}

    # Candidate windows made of whole sentences.
    candidates = []
    for a in range(len(sentences)):
        for b in range(a, len(sentences)):
            dur = sentences[b]["end"] - sentences[a]["start"]
            if dur > hi:
                break
            if dur < lo:
                continue
            words = [w for s in sentences[a: b + 1] for w in s["words"]]
            window = {"start": sentences[a]["start"], "end": sentences[b]["end"],
                      "text": " ".join(s["text"] for s in sentences[a: b + 1]), "words": words}
            ctx["sentences_in"] = b - a + 1
            window["breakdown"] = _score(window, ctx)
            window["score"] = _total(window["breakdown"], weights)
            candidates.append(window)
    if not candidates:  # speech too sparse for the length asked: fall back to the longest stretches
        for a in range(len(sentences)):
            b = a
            while b + 1 < len(sentences) and sentences[b + 1]["end"] - sentences[a]["start"] <= hi:
                b += 1
            words = [w for s in sentences[a: b + 1] for w in s["words"]]
            window = {"start": sentences[a]["start"], "end": sentences[b]["end"],
                      "text": " ".join(s["text"] for s in sentences[a: b + 1]), "words": words}
            ctx["sentences_in"] = b - a + 1
            window["breakdown"] = _score(window, ctx)
            window["score"] = _total(window["breakdown"], weights)
            if window["end"] - window["start"] >= 5:
                candidates.append(window)

    # Keep the best non-overlapping shortlist.
    shortlist: List[dict] = []
    for c in sorted(candidates, key=lambda c: -c["score"]):
        if all(_overlap(c, s) < 0.3 for s in shortlist):
            shortlist.append(c)
        if len(shortlist) >= max(n * 2, n + 3):
            break

    for c in shortlist:
        first = re.split(r"(?<=[.!?])\s", c["text"].strip())[0]
        c["title"] = first[:70]
        c["hook"] = first[:160]

    engine = _ai_pass(shortlist, focus)
    note = ""
    if engine == "failed":
        note = "The AI judge did not answer, so clips were ranked by the built-in scorer."
    elif engine == "none":
        note = "No AI model connected: ranked by the built-in scorer. Add an OpenRouter key or run Ollama for AI titles."
    for c in shortlist:
        if "ai_score" in c:
            c["score"] = _clamp(0.7 * c["score"] + 0.3 * c["ai_score"])

    picked = sorted(shortlist, key=lambda c: -c["score"])[:n]
    clips = []
    for c in picked:
        best = sorted(DIMENSIONS, key=lambda d: -c["breakdown"][d]["score"] * weights[d])[:2]
        reason = c.get("ai_reason") or "Strong " + " and ".join(LABELS[d].lower() for d in best) + "."
        start = max(0.0, c["start"] - 0.12)
        end = min(total_dur or c["end"] + 0.3, c["end"] + 0.3)
        clips.append({
            "start": round(start, 2), "end": round(end, 2), "title": c["title"], "hook": c["hook"],
            "score": c["score"], "ai_score": c.get("ai_score"), "reason": reason, "breakdown": c["breakdown"],
        })
    used = engine if engine in ("openrouter", "ollama") else "built-in"
    return {"engine": used, "note": note, "clips": clips}

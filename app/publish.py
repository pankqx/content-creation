"""Ready-to-paste titles, descriptions and hashtags for each platform."""
from __future__ import annotations

import re
from collections import Counter

from . import llm
from .highlights import EMOTION_WORDS, HOOK_WORDS, STOP

HOOKY = HOOK_WORDS | EMOTION_WORDS

PLATFORMS = {
    "youtube": {"label": "YouTube Shorts", "title_max": 100, "tags": 3},
    "instagram": {"label": "Instagram Reels", "title_max": 0, "tags": 8},
    "x": {"label": "X", "title_max": 0, "tags": 2},
    "linkedin": {"label": "LinkedIn", "title_max": 0, "tags": 3},
}
TONES = ["curious", "bold", "friendly", "professional", "funny", "calm"]

PROMPT = """Write social copy for a short vertical video clip. Tone: {tone}. Language: same as the transcript.
Do not invent facts that are not in the transcript. {credit}
Return ONLY JSON in exactly this shape:
{{"youtube": {{"title": "<max 90 chars>", "description": "<2-3 lines>", "hashtags": ["#a", "#b", "#c"]}},
 "instagram": {{"caption": "<hook line, 2-4 short lines, a question to drive comments>", "hashtags": ["#a", "... 6-8 tags"]}},
 "x": {{"post": "<max 240 chars>", "hashtags": ["#a", "#b"]}},
 "linkedin": {{"post": "<3-5 short lines, one takeaway>", "hashtags": ["#a", "#b", "#c"]}},
 "pinned_comment": "<a comment to pin that invites replies>"}}

Clip title: {title}
Transcript:
{text}"""


def _keywords(text: str, k: int) -> list:
    words = [w for w in re.findall(r"[\w']+", text.lower(), flags=re.U) if w not in STOP and len(w) > 3 and not w.isdigit() and not w.endswith("ly") and w not in HOOKY]
    return [w for w, _ in Counter(words).most_common(k)]


def _tag(word: str) -> str:
    return "#" + re.sub(r"[^\w]", "", word, flags=re.U)


def template(title: str, text: str, credit: str = "") -> dict:
    keys = _keywords(text, 8)
    tags = [_tag(k) for k in keys]
    first = re.split(r"(?<=[.!?])\s", text.strip())[0][:180]
    credit_line = f"\n\n{credit}" if credit else ""
    return {
        "youtube": {"title": f"{title[:90]} #shorts", "description": f"{first}{credit_line}", "hashtags": ["#shorts"] + tags[:2]},
        "instagram": {"caption": f"{title}\n\n{first}\n\nWhat do you think?{credit_line}", "hashtags": tags[:8] or ["#reels"]},
        "x": {"post": f"{title}"[:240], "hashtags": tags[:2]},
        "linkedin": {"post": f"{title}\n\n{first}{credit_line}", "hashtags": tags[:3]},
        "pinned_comment": "Agree or disagree? Tell me below.",
    }


def generate(title: str, text: str, tone: str = "curious", credit: str = "") -> dict:
    """Returns {"engine", "tone", "copy": {...}}. Falls back to a template when no model answers."""
    tone = tone if tone in TONES else "curious"
    credit_rule = f'End the YouTube description and Instagram caption with this credit line exactly: "{credit}".' if credit else ""
    reply, engine = llm.chat(PROMPT.format(tone=tone, title=title, text=text[:3000], credit=credit_rule))
    data = llm.json_from(reply)
    base = template(title, text, credit)
    if isinstance(data, dict):
        for key in base:
            if isinstance(data.get(key), type(base[key])):
                if isinstance(base[key], dict):
                    base[key].update({k: v for k, v in data[key].items() if v})
                else:
                    base[key] = data[key]
        for key in ("youtube", "instagram", "x", "linkedin"):
            tags = base[key].get("hashtags") or []
            base[key]["hashtags"] = [t if str(t).startswith("#") else f"#{t}" for t in tags if str(t).strip()][:10]
        return {"engine": engine, "tone": tone, "copy": base}
    return {"engine": "template", "tone": tone, "copy": base}

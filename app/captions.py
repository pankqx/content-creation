"""Word-by-word animated captions, written as an .ass subtitle file that ffmpeg burns into the clip."""
from __future__ import annotations

from typing import List

from . import config

# Colours are ASS format: &HBBGGRR&
STYLES = {
    "pop": {"label": "Pop yellow", "text": "&H00FFFFFF", "active": "&H0000E6FF", "outline": "&H00000000", "upper": True},
    "ember": {"label": "Ember orange", "text": "&H00FFFFFF", "active": "&H002A7BFF", "outline": "&H00141018", "upper": True},
    "mint": {"label": "Mint", "text": "&H00FFFFFF", "active": "&H00B4F06E", "outline": "&H00000000", "upper": False},
    "clean": {"label": "Clean white", "text": "&H00E8E8E8", "active": "&H00FFFFFF", "outline": "&H00000000", "upper": False},
}


def _ts(t: float) -> str:
    t = max(t, 0.0)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _clean(word: str) -> str:
    return word.replace("\\", "").replace("{", "(").replace("}", ")").strip()


def _chunks(words: List[dict]) -> List[List[dict]]:
    """Groups words into short on-screen phrases: at most 3 words, split on pauses and punctuation."""
    groups, current = [], []
    for word in words:
        if current:
            gap = word["start"] - current[-1]["end"]
            length = sum(len(w["word"]) for w in current) + len(word["word"])
            if len(current) >= 3 or length > 18 or gap > 0.6 or current[-1]["word"][-1:] in ".?!,;:":
                groups.append(current)
                current = []
        current.append(word)
    if current:
        groups.append(current)
    return groups


def build(words: List[dict], clip_start: float, clip_end: float, style: str = "pop", title: str = "") -> str:
    """words use source-video times; the output is timed from the start of the clip."""
    look = STYLES.get(style, STYLES["pop"])
    font = config.CAPTION_FONT
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},96,{look['text']},&H000000FF,{look['outline']},&H96000000,-1,0,0,0,100,100,0,0,1,8,3,2,90,90,540,1
Style: Title,{font},54,&H00FFFFFF,&H000000FF,&H00231A14,&H00231A14,-1,0,0,0,100,100,0,0,3,16,0,8,110,110,210,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    duration = clip_end - clip_start
    if title:
        lines.append(f"Dialogue: 1,{_ts(0)},{_ts(min(4.0, duration))},Title,,0,0,0,,{{\\fad(150,300)}}{_clean(title)}")

    inside = [
        {"start": w["start"] - clip_start, "end": w["end"] - clip_start, "word": _clean(w["word"])}
        for w in words
        if w["start"] >= clip_start - 0.05 and w["end"] <= clip_end + 0.05 and _clean(w["word"])
    ]
    groups = _chunks(inside)
    for gi, group in enumerate(groups):
        group_end = group[-1]["end"] + 0.2
        if gi + 1 < len(groups):
            group_end = min(group_end, groups[gi + 1][0]["start"])
        for wi, word in enumerate(group):
            start = word["start"]
            end = group[wi + 1]["start"] if wi + 1 < len(group) else group_end
            if end <= start:
                end = start + 0.08
            parts = []
            for wj, other in enumerate(group):
                text = other["word"].upper() if look["upper"] else other["word"]
                if wj == wi:
                    parts.append(f"{{\\c{look['active']}&\\fscx112\\fscy112}}{text}{{\\r}}")
                else:
                    parts.append(text)
            lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Cap,,0,0,0,,{' '.join(parts)}")
    return header + "\n".join(lines) + "\n"

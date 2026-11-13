"""Caption presets, word-by-word animated captions (.ass, burned in by ffmpeg) and .srt export.

Sizes are written for a 1080-px-wide frame and scaled to the output size.
"""
from __future__ import annotations

import re
from typing import Callable, List, Optional

from . import config

PRESETS = {
    "bold": {"label": "Bold Creator", "font": "Anton", "size": 104, "text": "#FFFFFF", "active": "#FFE14D",
             "outline": 7, "shadow": 3, "upper": True, "words": 3, "anim": "pop", "pos": 0.70},
    "clean": {"label": "Clean Minimal", "font": "Poppins SemiBold", "size": 64, "text": "#FFFFFF", "active": "#FFFFFF",
              "outline": 0, "shadow": 0, "box": True, "upper": False, "words": 5, "anim": "none", "pos": 0.74},
    "karaoke": {"label": "Karaoke Fill", "font": "Poppins ExtraBold", "size": 82, "text": "#FFFFFF", "active": "#7CFFB2",
                "outline": 6, "shadow": 2, "upper": True, "words": 4, "anim": "karaoke", "pos": 0.70},
    "gaming": {"label": "Gaming Energy", "font": "Bangers", "size": 118, "text": "#FFFFFF", "active": "#00F0FF",
               "outline": 8, "shadow": 4, "upper": True, "words": 2, "anim": "pop", "pos": 0.66},
    "podcast": {"label": "Podcast Lower Third", "font": "Poppins Medium", "size": 58, "text": "#F2F2F2", "active": "#FFB238",
                "outline": 3, "shadow": 0, "upper": False, "words": 6, "anim": "color", "pos": 0.82},
    "cinema": {"label": "Cinematic", "font": "Bebas Neue", "size": 92, "text": "#F4F1EA", "active": "#F4F1EA",
               "outline": 0, "shadow": 3, "upper": True, "words": 4, "anim": "fade", "pos": 0.80, "spacing": 4},
}
ASPECTS = {"9:16": (1080, 1920), "1:1": (1080, 1080), "4:5": (1080, 1350), "16:9": (1920, 1080)}
EMPHASIS = re.compile(r"\d|^(never|always|secret|truth|mistake|money|million|billion|crore|lakh|biggest|worst|best|free|now|stop|why|how)$", re.I)


def _ass_color(hex_color: str, alpha: int = 0) -> str:
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _ts(t: float) -> str:
    t = max(t, 0.0)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    cs = int(round((s - int(s)) * 100))
    if cs == 100:
        s, cs = int(s) + 1, 0
    return f"{int(h)}:{int(m):02d}:{int(s):02d}.{cs:02d}"


def _srt_ts(t: float) -> str:
    t = max(t, 0.0)
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _clean(word: str) -> str:
    return word.replace("\\", "").replace("{", "(").replace("}", ")").strip()


def font_for(language: str, preset_font: str) -> str:
    """Bundled display fonts only cover Latin script, so Kannada and Hindi switch to a Noto font."""
    if language == "kn":
        return config.KANNADA_FONT
    if language == "hi":
        return config.HINDI_FONT
    return preset_font


def clip_words(words: List[dict], start: float, end: float, text_override: Optional[str] = None) -> List[dict]:
    """Words inside [start, end] in source time. With edited caption text, the new words are laid over the
    same spoken timing: one-to-one when the word count matches, otherwise spread evenly over the speech."""
    inside = [dict(w) for w in words if w["start"] >= start - 0.05 and w["end"] <= end + 0.05 and _clean(w["word"])]
    if text_override is None or not text_override.strip():
        return inside
    new = [t for t in text_override.split() if _clean(t)]
    if not new:
        return []
    if not inside:
        span = (end - start) / len(new)
        return [{"start": start + i * span, "end": start + (i + 1) * span - 0.02, "word": t} for i, t in enumerate(new)]
    if len(new) == len(inside):
        return [{**w, "word": t} for w, t in zip(inside, new)]
    a, b = inside[0]["start"], inside[-1]["end"]
    span = (b - a) / len(new)
    return [{"start": a + i * span, "end": a + (i + 1) * span - 0.02, "word": t} for i, t in enumerate(new)]


def _chunks(words: List[dict], limit: int) -> List[List[dict]]:
    groups, current = [], []
    for word in words:
        if current:
            gap = word["start"] - current[-1]["end"]
            length = sum(len(w["word"]) for w in current) + len(word["word"])
            if len(current) >= limit or length > limit * 7 or gap > 0.6 or current[-1]["word"][-1:] in ".?!,;:":
                groups.append(current)
                current = []
        current.append(word)
    if current:
        groups.append(current)
    return groups


def build_ass(words: List[dict], to_out: Callable[[float], float], duration: float, preset: str, size: tuple,
              title: str = "", language: str = "", show_captions: bool = True, watermark: str = "") -> str:
    """`words` are in source time; `to_out` maps a source time to output time (it accounts for cut silences)."""
    p = PRESETS.get(preset, PRESETS["bold"])
    w, h = size
    k = w / 1080
    font = font_for(language, p["font"])
    upper = p["upper"] and language not in ("kn", "hi")
    box = p.get("box")
    border_style = 3 if box else 1
    outline = 14 if box else p["outline"]
    back = _ass_color("#000000", 0x70) if box else _ass_color("#000000", 0x80)
    out_col = _ass_color("#000000", 0x60) if box else _ass_color("#000000")
    margin_v = int(h * (1 - p["pos"]))
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{int(p['size'] * k)},{_ass_color(p['text'])},{_ass_color(p['active'])},{out_col},{back},0,0,0,0,100,100,{p.get('spacing', 0)},0,{border_style},{int(outline * k)},{int(p['shadow'] * k)},2,{int(80 * k)},{int(80 * k)},{margin_v},1
Style: Title,Poppins ExtraBold,{int(50 * k)},&H00111111,&H000000FF,&H00FFFFFF,&H00FFFFFF,0,0,0,0,100,100,0,0,3,{int(18 * k)},0,8,{int(110 * k)},{int(110 * k)},{int(h * 0.09)},1
Style: Mark,Poppins Medium,{int(30 * k)},&H50FFFFFF,&H000000FF,&H80000000,&H00000000,0,0,0,0,100,100,1,0,1,{max(1, int(2 * k))},0,9,{int(40 * k)},{int(40 * k)},{int(40 * k)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    if title:
        lines.append(f"Dialogue: 2,{_ts(0)},{_ts(min(3.5, duration))},Title,,0,0,0,,{{\\fad(120,300)}}{_clean(title)}")
    if watermark:
        lines.append(f"Dialogue: 1,{_ts(0)},{_ts(duration)},Mark,,0,0,0,,{_clean(watermark)}")
    if not show_captions:
        return header + "\n".join(lines) + "\n"

    timed = []
    for word in words:
        a, b = to_out(word["start"]), to_out(word["end"])
        if b is None or a is None or b <= 0 or a >= duration:
            continue
        text = _clean(word["word"])
        timed.append({"start": max(a, 0), "end": min(max(b, a + 0.06), duration), "word": text.upper() if upper else text})

    active = _ass_color(p["active"])
    groups = _chunks(timed, p["words"])
    for gi, group in enumerate(groups):
        g_end = group[-1]["end"] + 0.25
        if gi + 1 < len(groups):
            g_end = min(g_end, groups[gi + 1][0]["start"])
        if p["anim"] == "karaoke":
            parts, cursor = [], group[0]["start"]
            for word in group:
                fill_cs = max(5, int(round((word["end"] - cursor) * 100)))
                parts.append(f"{{\\kf{fill_cs}}}{word['word']}")
                cursor = word["end"]
            # \kf sweeps from SecondaryColour to PrimaryColour, so the line swaps them.
            lines.append(
                f"Dialogue: 0,{_ts(group[0]['start'])},{_ts(g_end)},Cap,,0,0,0,,"
                f"{{\\1c{active}&\\2c{_ass_color(p['text'])}&}}{' '.join(parts)}"
            )
            continue
        if p["anim"] == "fade":
            text = " ".join(x["word"] for x in group)
            lines.append(f"Dialogue: 0,{_ts(group[0]['start'])},{_ts(g_end)},Cap,,0,0,0,,{{\\fad(120,120)}}{text}")
            continue
        for wi, word in enumerate(group):
            start = word["start"]
            end = group[wi + 1]["start"] if wi + 1 < len(group) else g_end
            if end <= start:
                end = start + 0.08
            parts = []
            for wj, other in enumerate(group):
                emph = bool(EMPHASIS.search(other["word"]))
                if wj == wi:
                    if p["anim"] == "pop":
                        parts.append(f"{{\\c{active}&\\fscx88\\fscy88\\t(0,90,\\fscx114\\fscy114)\\t(90,160,\\fscx106\\fscy106)}}{other['word']}{{\\r}}")
                    else:
                        parts.append(f"{{\\c{active}&}}{other['word']}{{\\r}}")
                elif emph and p["anim"] == "pop":
                    parts.append(f"{{\\c{active}&\\alpha&H40&}}{other['word']}{{\\r}}")
                else:
                    parts.append(other["word"])
            lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Cap,,0,0,0,,{' '.join(parts)}")
    return header + "\n".join(lines) + "\n"


def build_srt(words: List[dict], to_out: Callable[[float], float], duration: float, per_line: int = 7) -> str:
    timed = []
    for word in words:
        a, b = to_out(word["start"]), to_out(word["end"])
        if a is None or b is None or b <= 0 or a >= duration:
            continue
        timed.append({"start": max(a, 0), "end": min(b, duration), "word": _clean(word["word"])})
    out = []
    for i, group in enumerate(_chunks(timed, per_line), 1):
        out.append(f"{i}\n{_srt_ts(group[0]['start'])} --> {_srt_ts(group[-1]['end'] + 0.2)}\n{' '.join(w['word'] for w in group)}\n")
    return "\n".join(out)

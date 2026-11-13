"""The two jobs Clipzer runs: generate (whole video -> ranked clips) and render (one clip after an edit)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Optional

from . import analyze, captions, highlights, publish, render, transcribe

DEFAULT_EDITS = {
    "style": "bold", "aspect": "9:16", "framing": "face", "manual_x": 0.5, "show_title": True, "title_text": "",
    "captions_on": True, "caption_text": None, "remove_silence": False, "normalize": True, "fades": True, "watermark": "",
}


class Cancelled(Exception):
    pass


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def source_of(job_dir: Path) -> Path:
    files = [f for f in job_dir.glob("source.*") if f.suffix not in (".part", ".ytdl", ".txt")]
    if not files:
        raise RuntimeError("The source video is missing from this project.")
    return files[0]


def all_words(transcript: dict) -> list:
    return [w for seg in transcript.get("segments", []) for w in seg.get("words") or []]


def clip_text(transcript: dict, start: float, end: float) -> str:
    return " ".join(w["word"] for w in all_words(transcript) if start - 0.05 <= w["start"] and w["end"] <= end + 0.05)


def render_clip(job_dir: Path, job: dict, clip: dict, transcript: dict) -> None:
    """Renders one clip from its current edits. Updates clip in place (file, thumb, version, duration...)."""
    source = source_of(job_dir)
    info = job["info"]
    e = {**DEFAULT_EDITS, **clip.get("edits", {})}
    size = captions.ASPECTS.get(e["aspect"], captions.ASPECTS["9:16"])
    words = all_words(transcript)
    start, end = float(clip["start"]), float(clip["end"])

    cache = clip.setdefault("face_cache", {})
    key = f"{start:.2f}-{end:.2f}"
    if e["framing"] == "face" and key not in cache:
        cache[key] = render.face_center(source, start, end, info["width"])
    vf, used = render.reframe_filter(info, size, e["framing"], cache.get(key), float(e["manual_x"]))

    spans = render.keep_intervals(words, start, end, bool(e["remove_silence"]))
    to_out, total = render.time_mapper(spans)
    cap_words = captions.clip_words(words, start, end, e["caption_text"])
    title = (e["title_text"] or clip["title"]) if e["show_title"] else ""
    ass = captions.build_ass(cap_words, to_out, total, e["style"], size, title=title,
                             language=job.get("language", ""), show_captions=bool(e["captions_on"]),
                             watermark=e["watermark"])
    version = int(clip.get("version", 0)) + 1
    name = f"{clip['id']}-v{version}"
    render.render(source, job_dir, name, spans, vf, ass, info["audio"], fades=bool(e["fades"]), normalize=bool(e["normalize"]))
    (job_dir / f"{name}.srt").write_text(captions.build_srt(cap_words, to_out, total), encoding="utf-8")
    for old in job_dir.glob(f"{clip['id']}-v*"):
        if not old.name.startswith(f"{name}."):
            old.unlink(missing_ok=True)
    clip.update(file=f"{name}.mp4", thumb=f"{name}.jpg", srt=f"{name}.srt", version=version,
                duration=round(total, 1), framing_used=used, cuts=len(spans) - 1, size=list(size))


def generate(job_dir: Path, job: dict, update: Callable[..., None], transcript: Optional[dict] = None) -> None:
    """Everything after import. `update(**fields)` saves progress and raises Cancelled when the job is cancelled.
    `transcript` can be passed in to skip speech-to-text (the tests do this)."""
    o = job["options"]
    source = source_of(job_dir)
    info = render.probe(source)
    if not info["width"]:
        raise RuntimeError("This file has no video track.")
    update(info=info)

    cached = read_json(job_dir / "transcript.json")
    if transcript is None and cached:
        transcript = cached
    if transcript is None:
        update(stage="transcribe", progress=0, message="Listening to every word")
        transcript = transcribe.transcribe(
            str(source), o.get("language") or None,
            lambda p: update(stage="transcribe", progress=int(p * 100), message="Listening to every word"),
        )
    (job_dir / "transcript.json").write_text(json.dumps(transcript, ensure_ascii=False), encoding="utf-8")
    language = o.get("language") or transcript.get("language", "")
    update(language=language, stage="analyze", progress=10, message="Measuring energy and camera cuts")

    audio = analyze.audio(source) if info["audio"] else {"rate": 10, "db": [], "burst": []}
    update(progress=50)
    cuts = analyze.scene_cuts(source)
    update(progress=100, energy=analyze.energy_curve(audio), scene_cuts=cuts)

    update(stage="moments", progress=20, message="Scoring every possible moment")
    found = highlights.find(transcript, n=int(o["num_clips"]), lo=int(o["min_len"]), hi=int(o["max_len"]),
                            genre=o.get("genre", "auto"), focus=o.get("focus", ""), audio_info=audio, cuts=cuts)
    if not found["clips"]:
        raise RuntimeError(found["note"] or "No clip-worthy moments were found.")
    edits = {k: o[k] for k in DEFAULT_EDITS if k in o}
    clips = []
    for i, c in enumerate(found["clips"], 1):
        clips.append({
            "id": f"c{i:02d}", "n": i, **c, "orig_start": c["start"], "orig_end": c["end"],
            "edits": {**DEFAULT_EDITS, **edits}, "version": 0, "render": {"status": "queued", "error": ""},
            "publish": None, "feedback": 0,
        })
    update(clips=clips, engine=found["engine"], note=found["note"], progress=100, message="Moments picked")

    for i, clip in enumerate(clips, 1):
        update(stage="render", progress=int((i - 1) / len(clips) * 100), message=f"Cutting clip {i} of {len(clips)}")
        clip["render"] = {"status": "rendering", "error": ""}
        update(clips=clips)
        try:
            render_clip(job_dir, job, clip, transcript)
            clip["render"] = {"status": "ready", "error": ""}
        except Cancelled:
            raise
        except Exception as error:
            clip["render"] = {"status": "failed", "error": str(error)[:300]}
        update(clips=clips, progress=int(i / len(clips) * 100))

    update(stage="write", progress=0, message="Writing titles and hashtags")
    for i, clip in enumerate(clips, 1):
        text = clip_text(transcript, clip["start"], clip["end"])
        clip["publish"] = publish.generate(clip["title"], text, o.get("tone", "curious"), o.get("credit", ""))
        update(clips=clips, progress=int(i / len(clips) * 100), message=f"Wrote copy for clip {i} of {len(clips)}")


def slug(text: str, fallback: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text, flags=re.U).strip().replace(" ", "-")
    return (text[:48] or fallback).lower()

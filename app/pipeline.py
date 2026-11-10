"""The job pipeline: import -> transcribe -> find moments -> cut, reframe and caption."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Optional

from . import captions, highlights, render, transcribe

STAGES = ["import", "transcribe", "moments", "render"]


def download(url: str, out_dir: Path, progress: Callable[[float], None]) -> Path:
    try:
        import yt_dlp
    except Exception as error:
        raise RuntimeError("Link import needs yt-dlp. Run: pip install yt-dlp") from error

    def hook(d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total:
                progress(d.get("downloaded_bytes", 0) / total)

    options = {
        "format": "bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_output_format": "mp4",
        "outtmpl": str(out_dir / "source.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [hook],
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
    files = sorted(out_dir.glob("source.*"))
    if not files:
        raise RuntimeError("The download finished but no video file was saved.")
    (out_dir / "source_title.txt").write_text(info.get("title", ""), encoding="utf-8")
    return files[0]


def slug(text: str, fallback: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text, flags=re.U).strip().replace(" ", "-")
    return (text[:48] or fallback).lower()


def process(
    job_dir: Path,
    source: Path,
    options: dict,
    update: Callable[..., None],
    transcript: Optional[dict] = None,
) -> list:
    """Runs everything after import. `update(stage=, progress=, message=)` reports progress.

    `transcript` can be passed in to skip speech-to-text (used by the tests).
    """
    info = render.probe(source)
    if not info["width"]:
        raise RuntimeError("This file has no video track.")

    if transcript is None:
        update(stage="transcribe", progress=0, message="Listening to the video")
        transcript = transcribe.transcribe(
            str(source), options.get("language") or None,
            lambda p: update(stage="transcribe", progress=int(p * 100), message="Listening to the video"),
        )
    (job_dir / "transcript.json").write_text(json.dumps(transcript, ensure_ascii=False), encoding="utf-8")

    update(stage="moments", progress=10, message="Finding the best moments")
    found = highlights.find(
        transcript, n=int(options.get("num_clips", 6)),
        lo=int(options.get("min_len", 25)), hi=int(options.get("max_len", 50)),
    )
    picks = found["clips"]
    if not picks:
        raise RuntimeError(found["note"] or "No clip-worthy moments were found.")
    update(stage="moments", progress=100, message=found["note"] or "Moments picked", engine=found["engine"])

    words = [w for seg in transcript["segments"] for w in seg["words"]]
    clips = []
    for i, pick in enumerate(picks, 1):
        update(stage="render", progress=int((i - 1) / len(picks) * 100), message=f"Cutting clip {i} of {len(picks)}")
        name = f"clip-{i:02d}-{slug(pick['title'], 'moment')}"
        vf, framing = render.video_filter(source, info, pick["start"], pick["end"], options.get("framing", "face"))
        ass = captions.build(
            words, pick["start"], pick["end"], options.get("style", "pop"),
            pick["title"] if options.get("show_title", True) else "",
        )
        render.cut(source, job_dir, name, pick["start"], pick["end"], vf, ass)
        clips.append(
            {
                "file": f"{name}.mp4", "thumb": f"{name}.jpg", "title": pick["title"], "hook": pick["hook"],
                "score": pick["score"], "reason": pick["reason"], "start": pick["start"], "end": pick["end"],
                "duration": round(pick["end"] - pick["start"], 1), "framing": framing,
            }
        )
        update(stage="render", progress=int(i / len(picks) * 100), message=f"Clip {i} of {len(picks)} ready", clips=clips)
    return clips

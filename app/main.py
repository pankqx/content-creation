"""Clipzer web server.  Run:  python -m uvicorn app.main:app --port 8000

Built, developed and owned by K S Pankaj.
"""
from __future__ import annotations

import json
import queue
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import captions, config, highlights, ingest, llm, pipeline, publish, render, transcribe

app = FastAPI(title=config.APP_NAME, version=config.VERSION)
jobs: dict = {}
work: "queue.Queue[tuple]" = queue.Queue()
lock = threading.RLock()
VIDEO_TYPES = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
EDIT_KEYS = set(pipeline.DEFAULT_EDITS)


# ---------------------------------------------------------------- job store

def job_dir(job_id: str) -> Path:
    return config.JOBS / job_id


def save(job: dict) -> None:
    (job_dir(job["id"]) / "job.json").write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")


def update(job_id: str, **changes) -> None:
    with lock:
        job = jobs[job_id]
        job.update(changes)
        save(job)
        if job.get("cancel"):
            raise pipeline.Cancelled()


def find_clip(job: dict, clip_id: str) -> dict:
    for clip in job.get("clips", []):
        if clip["id"] == clip_id:
            return clip
    raise HTTPException(404, "Clip not found")


def load_saved() -> None:
    for file in config.JOBS.glob("*/job.json"):
        job = pipeline.read_json(file)
        if not job:
            continue
        if job.get("status") in ("queued", "running"):
            job.update(status="failed", error="Clipzer was closed before this finished. Delete it and start again.")
        for clip in job.get("clips", []):
            if clip.get("render", {}).get("status") in ("queued", "rendering"):
                clip["render"] = {"status": "ready" if clip.get("file") else "failed", "error": ""}
        jobs[job["id"]] = job


# ---------------------------------------------------------------- worker

def run_generate(job_id: str) -> None:
    job = jobs[job_id]
    folder = job_dir(job_id)
    try:
        update(job_id, status="running", stage="import", progress=0, message="Bringing the video in")
        if job["url"] and not any(f for f in folder.glob("source.*") if f.suffix not in (".part", ".ytdl")):
            _, title = ingest.download(job["url"], folder, lambda p: update(job_id, progress=int(p * 100), message="Downloading the video"))
            if title:
                update(job_id, name=title)
        update(job_id, progress=100)
        pipeline.generate(folder, job, lambda **c: update(job_id, **c))
        update(job_id, status="done", stage="done", progress=100, message="All clips are ready")
    except pipeline.Cancelled:
        with lock:
            job.update(status="cancelled", message="Cancelled", cancel=False)
            save(job)
    except Exception as error:
        with lock:
            job.update(status="failed", error=str(error)[:400])
            save(job)


def run_render(job_id: str, clip_id: str) -> None:
    job = jobs[job_id]
    clip = find_clip(job, clip_id)
    try:
        with lock:
            clip["render"] = {"status": "rendering", "error": ""}
            save(job)
        transcript = pipeline.read_json(job_dir(job_id) / "transcript.json", {"segments": []})
        pipeline.render_clip(job_dir(job_id), job, clip, transcript)
        with lock:
            clip["render"] = {"status": "ready", "error": ""}
            save(job)
    except Exception as error:
        with lock:
            clip["render"] = {"status": "failed", "error": str(error)[:300]}
            save(job)


def run_publish(job_id: str, clip_id: str, tone: str) -> None:
    job = jobs[job_id]
    clip = find_clip(job, clip_id)
    transcript = pipeline.read_json(job_dir(job_id) / "transcript.json", {"segments": []})
    text = pipeline.clip_text(transcript, clip["start"], clip["end"])
    result = publish.generate(clip.get("edits", {}).get("title_text") or clip["title"], text, tone, job["options"].get("credit", ""))
    with lock:
        clip["publish"] = result
        clip["publish_busy"] = False
        save(job)


def worker() -> None:
    while True:
        task = work.get()
        try:
            if task[0] == "generate":
                run_generate(task[1])
            elif task[0] == "render":
                run_render(task[1], task[2])
            elif task[0] == "publish":
                run_publish(task[1], task[2], task[3])
        except Exception:
            pass


@app.on_event("startup")
def startup() -> None:
    load_saved()
    threading.Thread(target=worker, daemon=True).start()


# ---------------------------------------------------------------- info

def has_font(name: str) -> bool:
    try:
        out = subprocess.run(["fc-list", ":", "family"], capture_output=True, text=True, timeout=5).stdout
        return name.lower() in out.lower()
    except Exception:
        return False


@app.get("/api/health")
def health():
    ffmpeg = shutil.which("ffmpeg") is not None
    return {
        "app": config.APP_NAME, "version": config.VERSION, "owner": config.OWNER,
        "ffmpeg": ffmpeg, "encoder": render.encoder() if ffmpeg else None,
        "whisper": transcribe.available(), "whisper_model": config.WHISPER_MODEL,
        "ytdlp": _has_ytdlp(), "ai": llm.engine(), "ai_label": llm.label(),
        "kannada_font": has_font(config.KANNADA_FONT),
        "presets": {k: {"label": v["label"], "font": v["font"], "text": v["text"], "active": v["active"], "upper": v["upper"]} for k, v in captions.PRESETS.items()},
        "genres": {k: v["label"] for k, v in highlights.GENRES.items()},
        "aspects": list(captions.ASPECTS), "tones": publish.TONES,
        "dimensions": highlights.LABELS, "platforms": {k: v["label"] for k, v in publish.PLATFORMS.items()},
        "prefs": highlights.load_prefs(),
    }


def _has_ytdlp() -> bool:
    try:
        import yt_dlp  # noqa: F401
        return True
    except Exception:
        return False


@app.post("/api/check")
def check_link(payload: dict = Body(...)):
    url = str(payload.get("url", "")).strip()
    if not url.lower().startswith(("http://", "https://")):
        raise HTTPException(400, "The link must start with http:// or https://")
    return ingest.check(url)


# ---------------------------------------------------------------- projects

@app.get("/api/jobs")
def list_jobs():
    with lock:
        return [
            {k: j.get(k) for k in ("id", "name", "created", "status", "stage", "progress", "error")}
            | {"clips": len(j.get("clips", [])), "thumb": next((c.get("thumb") for c in j.get("clips", []) if c.get("thumb")), None)}
            for j in sorted(jobs.values(), key=lambda j: -j["created"])
        ]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "Project not found")
    with lock:
        return jobs[job_id]


@app.get("/api/jobs/{job_id}/transcript")
def get_transcript(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "Project not found")
    return pipeline.read_json(job_dir(job_id) / "transcript.json", {"segments": []})


@app.post("/api/jobs")
async def create_job(
    rights: bool = Form(False), url: str = Form(""), file: Optional[UploadFile] = File(None),
    num_clips: int = Form(6), min_len: int = Form(25), max_len: int = Form(50),
    style: str = Form("bold"), framing: str = Form("face"), aspect: str = Form("9:16"),
    language: str = Form(""), show_title: bool = Form(True), genre: str = Form("auto"), focus: str = Form(""),
    remove_silence: bool = Form(False), normalize: bool = Form(True), tone: str = Form("curious"),
    watermark: str = Form(""), credit: str = Form(""),
):
    if not rights:
        raise HTTPException(400, "Confirm that you have the right to clip this video.")
    url = url.strip()
    if not url and (file is None or not file.filename):
        raise HTTPException(400, "Paste a link or choose a video file.")
    if url and not url.lower().startswith(("http://", "https://")):
        raise HTTPException(400, "The link must start with http:// or https://")
    if not 5 <= min_len < max_len <= 180:
        raise HTTPException(400, "Clip length must be between 5 and 180 seconds, with the shortest below the longest.")

    job_id = uuid.uuid4().hex[:10]
    folder = job_dir(job_id)
    folder.mkdir(parents=True)
    name = url
    if not url:
        suffix = Path(file.filename).suffix.lower()
        if suffix not in VIDEO_TYPES:
            shutil.rmtree(folder)
            raise HTTPException(400, "Use an mp4, mov, mkv, webm, m4v or avi file.")
        size = 0
        with open(folder / f"source{suffix}", "wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > config.MAX_UPLOAD_MB * 1024 * 1024:
                    out.close()
                    shutil.rmtree(folder)
                    raise HTTPException(400, f"The file is larger than {config.MAX_UPLOAD_MB} MB.")
                out.write(chunk)
        name = Path(file.filename).stem[:120]

    job = {
        "id": job_id, "name": name, "url": url, "created": time.time(), "status": "queued", "stage": "import",
        "progress": 0, "message": "Waiting in the queue", "error": "", "engine": "", "note": "", "cancel": False,
        "info": {}, "language": "", "energy": [], "scene_cuts": [], "clips": [],
        "options": {
            "num_clips": max(1, min(num_clips, 15)), "min_len": min_len, "max_len": max_len,
            "style": style if style in captions.PRESETS else "bold",
            "framing": framing if framing in ("face", "center", "blur") else "face",
            "aspect": aspect if aspect in captions.ASPECTS else "9:16",
            "language": language if language in ("en", "hi", "kn") else "", "show_title": show_title,
            "genre": genre if genre in highlights.GENRES else "auto", "focus": focus.strip()[:200],
            "remove_silence": remove_silence, "normalize": normalize,
            "tone": tone if tone in publish.TONES else "curious",
            "watermark": watermark.strip()[:40], "credit": credit.strip()[:160],
        },
    }
    with lock:
        jobs[job_id] = job
        save(job)
    work.put(("generate", job_id))
    return job


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Project not found")
    with lock:
        if job["status"] == "queued":
            job.update(status="cancelled", message="Cancelled")
        elif job["status"] == "running":
            job["cancel"] = True
            job["message"] = "Stopping after the current step"
        save(job)
    return job


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Project not found")
    if job["status"] == "running" or any(c.get("render", {}).get("status") in ("queued", "rendering") for c in job.get("clips", [])):
        raise HTTPException(409, "Wait for this project to finish (or cancel it) before deleting it.")
    with lock:
        jobs.pop(job_id, None)
    shutil.rmtree(job_dir(job_id), ignore_errors=True)
    return {"deleted": job_id}


# ---------------------------------------------------------------- clips

@app.patch("/api/jobs/{job_id}/clips/{clip_id}")
def edit_clip(job_id: str, clip_id: str, payload: dict = Body(...)):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Project not found")
    clip = find_clip(job, clip_id)
    if clip.get("render", {}).get("status") in ("queued", "rendering"):
        raise HTTPException(409, "This clip is already rendering.")
    duration = float(job.get("info", {}).get("duration") or 0)
    with lock:
        if "start" in payload or "end" in payload:
            start = float(payload.get("start", clip["start"]))
            end = float(payload.get("end", clip["end"]))
            start, end = max(0.0, start), min(duration or end, end)
            if not 3 <= end - start <= 180:
                raise HTTPException(400, "A clip must be between 3 and 180 seconds long.")
            clip["start"], clip["end"] = round(start, 2), round(end, 2)
        edits = payload.get("edits") or {}
        for key, value in edits.items():
            if key not in EDIT_KEYS:
                continue
            if key == "style" and value not in captions.PRESETS:
                continue
            if key == "aspect" and value not in captions.ASPECTS:
                continue
            if key == "framing" and value not in ("face", "center", "blur", "manual"):
                continue
            if key == "manual_x":
                value = max(0.0, min(1.0, float(value)))
            if key in ("title_text", "watermark") and value is not None:
                value = str(value)[:120]
            if key == "caption_text" and value is not None:
                value = str(value)[:6000]
            clip["edits"][key] = value
        clip["render"] = {"status": "queued", "error": ""}
        save(job)
    work.put(("render", job_id, clip_id))
    return clip


@app.post("/api/jobs/{job_id}/clips/{clip_id}/reset")
def reset_clip(job_id: str, clip_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Project not found")
    clip = find_clip(job, clip_id)
    return edit_clip(job_id, clip_id, {"start": clip["orig_start"], "end": clip["orig_end"],
                                        "edits": {"caption_text": None, "title_text": ""}})


@app.post("/api/jobs/{job_id}/clips/{clip_id}/publish")
def regenerate_copy(job_id: str, clip_id: str, payload: dict = Body(default={})):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Project not found")
    clip = find_clip(job, clip_id)
    with lock:
        clip["publish_busy"] = True
        save(job)
    work.put(("publish", job_id, clip_id, str(payload.get("tone", "curious"))))
    return clip


@app.post("/api/jobs/{job_id}/clips/{clip_id}/feedback")
def feedback(job_id: str, clip_id: str, payload: dict = Body(...)):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Project not found")
    clip = find_clip(job, clip_id)
    value = int(payload.get("value", 0))
    if value not in (-1, 0, 1):
        raise HTTPException(400, "Feedback must be -1, 0 or 1.")
    previous = clip.get("feedback", 0)
    if value != previous:
        if previous:
            highlights.record_feedback(clip.get("breakdown", {}), -previous)
        if value:
            highlights.record_feedback(clip.get("breakdown", {}), value)
    with lock:
        clip["feedback"] = value
        save(job)
    return {"feedback": value, "prefs": highlights.load_prefs()}


@app.get("/api/jobs/{job_id}/clips/{clip_id}/download")
def download(job_id: str, clip_id: str, kind: str = "mp4"):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Project not found")
    clip = find_clip(job, clip_id)
    name = clip.get("srt" if kind == "srt" else "file")
    if not name or not (job_dir(job_id) / name).exists():
        raise HTTPException(404, "This clip has no rendered file yet.")
    nice = f"{clip['n']:02d}-{pipeline.slug(clip.get('edits', {}).get('title_text') or clip['title'], 'clip')}.{'srt' if kind == 'srt' else 'mp4'}"
    return FileResponse(job_dir(job_id) / name, filename=nice)


app.mount("/media", StaticFiles(directory=config.JOBS), name="media")
app.mount("/fonts", StaticFiles(directory=config.FONTS), name="fonts")
app.mount("/", StaticFiles(directory=config.WEB, html=True), name="web")

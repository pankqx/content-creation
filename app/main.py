"""Clipzer web server. Run with:  python -m uvicorn app.main:app --port 8000"""
from __future__ import annotations

import json
import queue
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles

from . import captions, config, pipeline, render, transcribe

app = FastAPI(title=config.APP_NAME)
jobs: dict = {}
work: "queue.Queue[str]" = queue.Queue()
lock = threading.Lock()
VIDEO_TYPES = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}


def save(job: dict) -> None:
    path = config.JOBS / job["id"] / "job.json"
    path.write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")


def update(job_id: str, **changes) -> None:
    with lock:
        job = jobs[job_id]
        job.update(changes)
        save(job)


def load_saved() -> None:
    for file in config.JOBS.glob("*/job.json"):
        try:
            job = json.loads(file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if job.get("status") in ("queued", "running"):
            job.update(status="failed", error="The app was closed before this job finished.")
        jobs[job["id"]] = job


def worker() -> None:
    while True:
        job_id = work.get()
        job = jobs.get(job_id)
        if not job:
            continue
        job_dir = config.JOBS / job_id
        try:
            update(job_id, status="running", stage="import", progress=0, message="Importing the video")
            if job["url"]:
                source = pipeline.download(
                    job["url"], job_dir,
                    lambda p: update(job_id, progress=int(p * 100), message="Downloading the video"),
                )
                title_file = job_dir / "source_title.txt"
                if title_file.exists() and title_file.read_text(encoding="utf-8").strip():
                    update(job_id, name=title_file.read_text(encoding="utf-8").strip()[:90])
            else:
                source = next(job_dir.glob("source.*"))
            update(job_id, progress=100)
            clips = pipeline.process(job_dir, source, job["options"], lambda **c: update(job_id, **c))
            update(job_id, status="done", stage="done", progress=100, message="All clips are ready", clips=clips)
        except Exception as error:
            update(job_id, status="failed", error=str(error)[:400])


@app.on_event("startup")
def startup() -> None:
    load_saved()
    threading.Thread(target=worker, daemon=True).start()


@app.get("/api/health")
def health():
    return {
        "app": config.APP_NAME,
        "owner": config.OWNER,
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "encoder": render.encoder() if shutil.which("ffmpeg") else None,
        "whisper": transcribe.available(),
        "whisper_model": config.WHISPER_MODEL,
        "ai_picker": bool(config.OPENROUTER_API_KEY),
        "styles": {key: value["label"] for key, value in captions.STYLES.items()},
    }


@app.get("/api/jobs")
def list_jobs():
    return sorted(jobs.values(), key=lambda j: -j["created"])


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    return jobs[job_id]


@app.post("/api/jobs")
async def create_job(
    rights: bool = Form(False),
    url: str = Form(""),
    file: Optional[UploadFile] = File(None),
    num_clips: int = Form(6),
    min_len: int = Form(25),
    max_len: int = Form(50),
    style: str = Form("pop"),
    framing: str = Form("face"),
    language: str = Form(""),
    show_title: bool = Form(True),
):
    if not rights:
        raise HTTPException(400, "Confirm that you have the right to clip this video.")
    url = url.strip()
    if not url and (file is None or not file.filename):
        raise HTTPException(400, "Paste a link or choose a video file.")
    if url and not url.lower().startswith(("http://", "https://")):
        raise HTTPException(400, "The link must start with http:// or https://")
    if not 5 <= min_len < max_len <= 180:
        raise HTTPException(400, "Clip length must be between 5 and 180 seconds, with min below max.")

    job_id = uuid.uuid4().hex[:10]
    job_dir = config.JOBS / job_id
    job_dir.mkdir(parents=True)
    name = url
    if not url:
        suffix = Path(file.filename).suffix.lower()
        if suffix not in VIDEO_TYPES:
            shutil.rmtree(job_dir)
            raise HTTPException(400, "Use an mp4, mov, mkv, webm, m4v or avi file.")
        size = 0
        with open(job_dir / f"source{suffix}", "wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > config.MAX_UPLOAD_MB * 1024 * 1024:
                    out.close()
                    shutil.rmtree(job_dir)
                    raise HTTPException(400, f"The file is larger than {config.MAX_UPLOAD_MB} MB.")
                out.write(chunk)
        name = Path(file.filename).stem[:90]

    job = {
        "id": job_id, "name": name, "url": url, "created": time.time(), "status": "queued",
        "stage": "import", "progress": 0, "message": "Waiting in the queue", "error": "", "engine": "",
        "clips": [],
        "options": {
            "num_clips": max(1, min(num_clips, 15)), "min_len": min_len, "max_len": max_len,
            "style": style if style in captions.STYLES else "pop",
            "framing": framing if framing in ("face", "blur") else "face",
            "language": language if language in ("en", "hi", "kn") else "", "show_title": show_title,
        },
    }
    with lock:
        jobs[job_id] = job
        save(job)
    work.put(job_id)
    return job


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job["status"] in ("queued", "running"):
        raise HTTPException(409, "Wait for this job to finish before deleting it.")
    with lock:
        jobs.pop(job_id, None)
    shutil.rmtree(config.JOBS / job_id, ignore_errors=True)
    return {"deleted": job_id}


app.mount("/media", StaticFiles(directory=config.JOBS), name="media")
app.mount("/", StaticFiles(directory=config.WEB, html=True), name="web")

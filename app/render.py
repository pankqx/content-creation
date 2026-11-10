"""Cutting, vertical reframing and encoding with ffmpeg. Face position comes from OpenCV."""
from __future__ import annotations

import json
import statistics
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Optional

W, H = 1080, 1920


def run(cmd: list, cwd: Optional[Path] = None) -> None:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "ffmpeg failed")


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:format=duration", "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise RuntimeError("This file could not be read as a video.")
    data = json.loads(out.stdout)
    stream = (data.get("streams") or [{}])[0]
    return {
        "width": int(stream.get("width", 0)),
        "height": int(stream.get("height", 0)),
        "duration": float(data.get("format", {}).get("duration", 0) or 0),
    }


@lru_cache(maxsize=1)
def encoder() -> str:
    """Uses the Nvidia encoder when it works on this machine, otherwise x264 on the CPU."""
    test = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=black:s=256x256:d=0.2",
         "-c:v", "h264_nvenc", "-f", "null", "-"],
        capture_output=True,
    )
    return "h264_nvenc" if test.returncode == 0 else "libx264"


def _face_center(path: Path, start: float, end: float, width: int) -> Optional[float]:
    """Median horizontal centre of the largest face across sampled frames, or None if no face."""
    try:
        import cv2

        model = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        if not model.exists():
            return None
        detector = cv2.CascadeClassifier(str(model))
        if detector.empty():
            return None
        video = cv2.VideoCapture(str(path))
        centers = []
        samples = 12
        for i in range(samples):
            video.set(cv2.CAP_PROP_POS_MSEC, (start + (end - start) * (i + 0.5) / samples) * 1000)
            ok, frame = video.read()
            if not ok:
                continue
            scale = 640 / frame.shape[1]
            small = cv2.cvtColor(cv2.resize(frame, None, fx=scale, fy=scale), cv2.COLOR_BGR2GRAY)
            faces = detector.detectMultiScale(small, scaleFactor=1.15, minNeighbors=6, minSize=(48, 48))
            if len(faces):
                x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
                centers.append((x + w / 2) / scale)
        video.release()
    except Exception:  # OpenCV missing or without its face model: fall back to a centre crop
        return None
    if len(centers) < 3:
        return None
    return min(max(statistics.median(centers), 0), width)


def video_filter(path: Path, info: dict, start: float, end: float, mode: str) -> tuple[str, str]:
    """Returns (filter text, framing actually used)."""
    w, h = info["width"], info["height"]
    if h >= w:  # already vertical or square
        return (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1", "vertical")
    if mode == "face":
        crop_w = int(h * 9 / 16) // 2 * 2
        center = _face_center(path, start, end, w)
        used = "face" if center is not None else "center"
        x = int(min(max((center if center is not None else w / 2) - crop_w / 2, 0), w - crop_w))
        return (f"crop={crop_w}:{h}:{x}:0,scale={W}:{H},setsar=1", used)
    blur = (
        f"split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=24:2[bg];"
        f"[b]scale={W}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1"
    )
    return (blur, "blur")


def cut(source: Path, out_dir: Path, name: str, start: float, end: float, vf: str, ass_text: str) -> None:
    """Writes <name>.mp4 and <name>.jpg into out_dir."""
    (out_dir / f"{name}.ass").write_text(ass_text, encoding="utf-8")
    codec = encoder()
    quality = ["-preset", "p5", "-cq", "23", "-b:v", "0"] if codec == "h264_nvenc" else ["-preset", "veryfast", "-crf", "20"]
    run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}", "-t", f"{end - start:.2f}", "-i", str(source),
         "-filter_complex", f"[0:v]{vf},subtitles={name}.ass[v]", "-map", "[v]", "-map", "0:a?",
         "-c:v", codec, *quality, "-pix_fmt", "yuv420p", "-r", "30",
         "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", f"{name}.mp4"],
        cwd=out_dir,
    )
    run(["ffmpeg", "-y", "-v", "error", "-ss", "1", "-i", f"{name}.mp4", "-frames:v", "1", "-vf", "scale=360:-2", f"{name}.jpg"], cwd=out_dir)

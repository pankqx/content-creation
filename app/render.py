"""Cutting, reframing, silence removal, captions, fades and loudness, all in one ffmpeg pass per clip."""
from __future__ import annotations

import json
import statistics
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Tuple

from . import config


def run(cmd: list, cwd: Optional[Path] = None) -> None:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        lines = [l for l in result.stderr.strip().splitlines() if l.strip()]
        raise RuntimeError(lines[-1] if lines else "ffmpeg failed")


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height:format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        raise RuntimeError("This file could not be read as a video.")
    data = json.loads(out.stdout)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    return {
        "width": int(video.get("width", 0) or 0),
        "height": int(video.get("height", 0) or 0),
        "duration": float(data.get("format", {}).get("duration", 0) or 0),
        "audio": any(s.get("codec_type") == "audio" for s in data.get("streams", [])),
    }


@lru_cache(maxsize=1)
def encoder() -> str:
    """The Nvidia encoder when it works on this machine, otherwise x264 on the CPU."""
    test = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=black:s=256x256:d=0.2",
         "-c:v", "h264_nvenc", "-f", "null", "-"],
        capture_output=True,
    )
    return "h264_nvenc" if test.returncode == 0 else "libx264"


def face_center(path: Path, start: float, end: float, width: int) -> Optional[float]:
    """Median horizontal centre (pixels) of the largest face over sampled frames, or None."""
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
        samples = 14
        for i in range(samples):
            video.set(cv2.CAP_PROP_POS_MSEC, (start + (end - start) * (i + 0.5) / samples) * 1000)
            ok, frame = video.read()
            if not ok:
                continue
            scale = 640 / frame.shape[1]
            small = cv2.cvtColor(cv2.resize(frame, None, fx=scale, fy=scale), cv2.COLOR_BGR2GRAY)
            faces = detector.detectMultiScale(small, scaleFactor=1.15, minNeighbors=6, minSize=(40, 40))
            if len(faces):
                x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
                centers.append((x + w / 2) / scale)
        video.release()
    except Exception:
        return None
    if len(centers) < 3:
        return None
    return min(max(statistics.median(centers), 0), width)


def keep_intervals(words: List[dict], start: float, end: float, remove_silence: bool) -> List[Tuple[float, float]]:
    """Stretches of the clip to keep. With silence removal, gaps over 0.6 s between words are cut out."""
    if not remove_silence:
        return [(start, end)]
    inside = [w for w in words if w["start"] >= start - 0.05 and w["end"] <= end + 0.05]
    if len(inside) < 2:
        return [(start, end)]
    spans = []
    a = start
    for prev, nxt in zip(inside, inside[1:]):
        if nxt["start"] - prev["end"] > 0.6:
            spans.append((a, min(prev["end"] + 0.18, end)))
            a = max(nxt["start"] - 0.12, start)
    spans.append((a, end))
    return [(round(x, 3), round(y, 3)) for x, y in spans if y - x > 0.15]


def time_mapper(spans: List[Tuple[float, float]]):
    """Maps a source time to output time after the cuts. Times inside a removed gap snap to the next kept span."""
    offsets, total = [], 0.0
    for a, b in spans:
        offsets.append(total)
        total += b - a

    def to_out(t: float) -> Optional[float]:
        for (a, b), off in zip(spans, offsets):
            if t < a:
                return off
            if t <= b:
                return off + (t - a)
        return total

    return to_out, total


def reframe_filter(info: dict, size: Tuple[int, int], framing: str, center_x: Optional[float], manual_x: float) -> Tuple[str, str]:
    """Filter text (applied to the joined clip) and the framing actually used."""
    sw, sh = info["width"], info["height"]
    tw, th = size
    target = tw / th
    source = sw / sh
    if abs(source - target) < 0.02:
        return f"scale={tw}:{th},setsar=1", "full"
    if framing == "blur":
        return (
            f"split[bga][fga];[bga]scale={tw}:{th}:force_original_aspect_ratio=increase,crop={tw}:{th},"
            f"boxblur=26:2,eq=brightness=-0.06[bg];[fga]scale={tw}:{th}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1",
            "blur",
        )
    if source > target:  # source is wider: choose a horizontal window
        crop_w = int(sh * target) // 2 * 2
        if framing == "manual":
            cx, used = manual_x * sw, "manual"
        elif framing == "face" and center_x is not None:
            cx, used = center_x, "face"
        else:
            cx, used = sw / 2, "center"
        x = int(min(max(cx - crop_w / 2, 0), sw - crop_w))
        return f"crop={crop_w}:{sh}:{x}:0,scale={tw}:{th},setsar=1", used
    crop_h = int(sw / target) // 2 * 2  # source is taller: keep the upper-middle band where faces usually are
    y = int(max(0, min((sh - crop_h) * 0.35, sh - crop_h)))
    return f"crop={sw}:{crop_h}:0:{y},scale={tw}:{th},setsar=1", "center"


def render(source: Path, out_dir: Path, name: str, spans: List[Tuple[float, float]], vf: str, ass_text: str,
           has_audio: bool, fades: bool = True, normalize: bool = True) -> None:
    """Writes <name>.mp4 and <name>.jpg into out_dir."""
    (out_dir / f"{name}.ass").write_text(ass_text, encoding="utf-8")
    first, last = spans[0][0], spans[-1][1]
    pre = max(0.0, first - 1.0)  # seek a little early, then trim exactly
    total = sum(b - a for a, b in spans)
    parts, labels = [], []
    for i, (a, b) in enumerate(spans):
        a2, b2 = a - pre, b - pre
        parts.append(f"[0:v]trim=start={a2:.3f}:end={b2:.3f},setpts=PTS-STARTPTS[v{i}]")
        if has_audio:
            parts.append(f"[0:a]atrim=start={a2:.3f}:end={b2:.3f},asetpts=PTS-STARTPTS[a{i}]")
            labels.append(f"[v{i}][a{i}]")
        else:
            labels.append(f"[v{i}]")
    if len(spans) > 1:
        audio_out = "[aj]" if has_audio else ""
        parts.append(f"{''.join(labels)}concat=n={len(spans)}:v=1:a={1 if has_audio else 0}[vj]{audio_out}")
        vj, aj = "[vj]", "[aj]"
    else:
        vj, aj = "[v0]", "[a0]"
    fonts = str(config.FONTS).replace("\\", "/").replace(":", "\\:")
    vchain = f"{vj}{vf},subtitles={name}.ass:fontsdir='{fonts}'"
    if fades:
        vchain += f",fade=t=in:st=0:d=0.2,fade=t=out:st={max(total - 0.3, 0):.2f}:d=0.3"
    parts.append(vchain + "[vout]")
    maps = ["-map", "[vout]"]
    if has_audio:
        filters = []
        if normalize:
            filters.append("loudnorm=I=-14:TP=-1.5:LRA=11")
        if fades:
            filters += ["afade=t=in:st=0:d=0.15", f"afade=t=out:st={max(total - 0.3, 0):.2f}:d=0.3"]
        filters.append("aresample=48000")
        parts.append(aj + ",".join(filters) + "[aout]")
        maps += ["-map", "[aout]"]

    codec = encoder()
    quality = ["-preset", "p5", "-cq", "23", "-b:v", "0"] if codec == "h264_nvenc" else ["-preset", "veryfast", "-crf", "20"]
    run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{pre:.3f}", "-t", f"{last - pre + 0.1:.3f}", "-i", str(source),
         "-filter_complex", ";".join(parts), *maps,
         "-c:v", codec, *quality, "-pix_fmt", "yuv420p", "-r", "30",
         *(["-c:a", "aac", "-b:a", "160k"] if has_audio else []), "-movflags", "+faststart", f"{name}.mp4"],
        cwd=out_dir,
    )
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{min(1.0, total / 3):.2f}", "-i", f"{name}.mp4", "-frames:v", "1",
         "-vf", "scale=360:-2", f"{name}.jpg"], cwd=out_dir)

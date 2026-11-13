"""Signals beyond the words: how loud each moment is, noisy bursts (laughter or applause), and camera cuts."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import numpy as np

RATE = 10  # audio frames per second


def audio(path: Path) -> dict:
    """Loudness (dB) and a 'burst' flag at 10 frames a second. Empty lists if the file has no audio."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
        capture_output=True,
    )
    raw = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    size = 8000 // RATE
    count = len(raw) // size
    if count < 2:
        return {"rate": RATE, "db": [], "burst": []}
    frames = raw[: count * size].reshape(count, size)
    rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(rms + 1e-9)
    # Laughter and applause are loud and noise-like: many zero crossings and high level.
    crossings = np.mean(np.abs(np.diff(np.sign(frames), axis=1)) > 0, axis=1)
    loud = db > (np.median(db) + 6)
    burst = loud & (crossings > 0.18)
    return {"rate": RATE, "db": [round(float(v), 1) for v in db], "burst": [bool(v) for v in burst]}


def scene_cuts(path: Path, threshold: float = 0.32) -> list:
    """Times (seconds) where the picture changes sharply. Runs on a small, low-frame-rate copy for speed."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "info", "-hide_banner", "-i", str(path), "-an", "-sn",
         "-vf", f"fps=3,scale=160:-2,select='gt(scene,{threshold})',showinfo", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    return [round(float(t), 2) for t in re.findall(r"pts_time:([0-9.]+)", proc.stderr)]


def energy_curve(audio_info: dict, per_second: int = 2) -> list:
    """Downsampled loudness for the editor timeline, scaled 0-100."""
    db = audio_info.get("db") or []
    if not db:
        return []
    step = max(1, RATE // per_second)
    values = np.array(db, dtype=np.float32)
    trimmed = values[: len(values) // step * step].reshape(-1, step).max(axis=1)
    low, high = np.percentile(trimmed, 5), np.percentile(trimmed, 99)
    scaled = np.clip((trimmed - low) / max(high - low, 1e-3), 0, 1) * 100
    return [int(v) for v in scaled]

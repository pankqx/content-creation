"""Getting a video in: checking a link, downloading it, or accepting an upload."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from . import config


def _ydl(extra: dict):
    try:
        import yt_dlp
    except Exception as error:
        raise RuntimeError("Link import needs yt-dlp. Run: .venv/bin/pip install yt-dlp") from error
    options = {"quiet": True, "no_warnings": True, "noplaylist": True}
    options.update(extra)
    return yt_dlp.YoutubeDL(options)


def check(url: str) -> dict:
    """Reads a link without downloading: title, channel, length. Says why when it can't be imported."""
    try:
        with _ydl({"skip_download": True}) as ydl:
            info = ydl.extract_info(url, download=False)
    except RuntimeError as error:
        return {"ok": False, "reason": str(error)}
    except Exception as error:
        text = str(error)
        reason = "This link could not be read."
        lowered = text.lower()
        if "unable to connect" in lowered or "timed out" in lowered or "network is unreachable" in lowered:
            reason = "Couldn't reach the site. Check your internet connection and try again."
        elif "private" in lowered:
            reason = "This video is private."
        elif "members" in lowered:
            reason = "This video is for channel members only."
        elif "sign in" in lowered or "bot" in lowered:
            reason = "The site asked for a sign-in. Download the video yourself and upload the file."
        elif "unsupported url" in lowered:
            reason = "This site is not supported. Upload the file instead."
        return {"ok": False, "reason": reason, "detail": text[:300]}
    if info.get("_type") == "playlist":
        return {"ok": False, "reason": "That is a playlist or channel. Paste the link of one video."}
    if info.get("is_live"):
        return {"ok": False, "reason": "Live streams can't be clipped until they end."}
    duration = float(info.get("duration") or 0)
    if duration and duration > config.MAX_SOURCE_MINUTES * 60:
        return {"ok": False, "reason": f"This video is longer than {config.MAX_SOURCE_MINUTES} minutes."}
    return {
        "ok": True,
        "title": info.get("title") or "Untitled video",
        "channel": info.get("channel") or info.get("uploader") or "",
        "duration": duration,
        "thumbnail": info.get("thumbnail") or "",
        "site": info.get("extractor_key") or "",
        "license": info.get("license") or "",
    }


def download(url: str, out_dir: Path, progress: Callable[[float], None]) -> tuple[Path, str]:
    def hook(d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total:
                progress(d.get("downloaded_bytes", 0) / total)

    options = {
        "format": "bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_output_format": "mp4",
        "outtmpl": str(out_dir / "source.%(ext)s"),
        "progress_hooks": [hook],
    }
    with _ydl(options) as ydl:
        info = ydl.extract_info(url, download=True)
    files = [f for f in sorted(out_dir.glob("source.*")) if f.suffix not in (".part", ".ytdl")]
    if not files:
        raise RuntimeError("The download finished but no video file was saved.")
    return files[0], (info.get("title") or "")[:120]

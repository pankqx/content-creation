"""End-to-end check of everything after speech-to-text, on a generated test video.

Run from the project folder:  python tests/smoke_test.py
It needs ffmpeg but not Whisper, a GPU or an internet connection.
"""
import pathlib
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app import pipeline, render  # noqa: E402

SCRIPT = (
    "Nobody tells you the real reason most startups fail. It is not money. It is not the idea. "
    "Honestly the biggest mistake I made was hiring too fast. We went from five people to fifty in one year. "
    "And then the story changed. Why did we lose everything? Because we stopped talking to customers. "
    "Here is the simple rule I learned. Talk to ten customers every single week. Never skip it. "
    "That one habit built a company worth ten million dollars. Imagine starting again with that lesson. "
    "ನಮಸ್ಕಾರ ಇದು ಕನ್ನಡ ಪರೀಕ್ಷೆ. So remember this before you quit your job and start building."
)


def fake_transcript(duration: float) -> dict:
    sentences = [s.strip() for s in SCRIPT.replace("?", "?|").replace(".", ".|").split("|") if s.strip()]
    total_words = sum(len(s.split()) for s in sentences)
    step = duration / total_words
    t, segments = 0.0, []
    for sentence in sentences:
        words = []
        for word in sentence.split():
            words.append({"start": round(t, 2), "end": round(t + step * 0.85, 2), "word": word})
            t += step
        segments.append({"start": words[0]["start"], "end": words[-1]["end"], "text": sentence, "words": words})
    return {"language": "en", "duration": duration, "segments": segments}


def main() -> None:
    work = pathlib.Path(tempfile.mkdtemp(prefix="clipzer-test-"))
    source = work / "source.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=70",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=70", "-c:v", "libx264", "-preset", "ultrafast",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source)],
        check=True,
    )
    for framing in ("face", "blur"):
        out = work / framing
        out.mkdir()
        log = []
        clips = pipeline.process(
            out, source,
            {"num_clips": 2, "min_len": 15, "max_len": 25, "style": "pop", "framing": framing, "show_title": True},
            lambda **c: log.append(c), transcript=fake_transcript(70),
        )
        assert clips, "no clips were produced"
        for clip in clips:
            info = render.probe(out / clip["file"])
            assert (info["width"], info["height"]) == (1080, 1920), info
            assert 14 <= info["duration"] <= 26, info
            assert (out / clip["thumb"]).exists()
            print(f"ok  {framing:5} {clip['file']}  {info['duration']:.1f}s  score {clip['score']}  framing {clip['framing']}")
    keep = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if keep:
        shutil.copytree(work, keep, dirs_exist_ok=True)
    shutil.rmtree(work)
    print("All checks passed.")


if __name__ == "__main__":
    main()

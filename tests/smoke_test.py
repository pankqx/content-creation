"""End-to-end check of everything after speech-to-text, on a generated test video.

Run from the project folder:  python tests/smoke_test.py
Needs ffmpeg, but not Whisper, a GPU, an AI model or the internet.
"""
import pathlib
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app import captions, pipeline, render  # noqa: E402

SCRIPT = (
    "Nobody tells you the real reason most startups fail. It is not money. It is not the idea. "
    "Honestly the biggest mistake I made was hiring too fast! We went from 5 people to 50 in one year. "
    "And then the story changed. Why did we lose everything? Because we stopped talking to customers. "
    "Here is the simple rule I learned. Talk to 10 customers every single week. Never skip it. "
    "That one habit built a company worth 10 million dollars. Imagine starting again with that lesson. "
    "Your first hire matters more than your first investor. Hire slow and fire fast, that is the truth. "
    "So remember this before you quit your job and start building."
)


def fake_transcript(duration: float) -> dict:
    """Word timings with deliberate pauses so silence removal has something to cut."""
    sentences = [s.strip() for s in SCRIPT.replace("?", "?|").replace(".", ".|").replace("!", "!|").split("|") if s.strip()]
    total_words = sum(len(s.split()) for s in sentences)
    step = (duration - len(sentences) * 0.9) / total_words
    t, segments = 0.3, []
    for sentence in sentences:
        words = []
        for word in sentence.split():
            words.append({"start": round(t, 2), "end": round(t + step * 0.85, 2), "word": word})
            t += step
        t += 0.9  # a pause between sentences
        segments.append({"start": words[0]["start"], "end": words[-1]["end"], "text": sentence, "words": words})
    return {"language": "en", "duration": duration, "segments": segments}


def main() -> None:
    work = pathlib.Path(tempfile.mkdtemp(prefix="clipzer-test-"))
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=90",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=90", "-c:v", "libx264", "-preset", "ultrafast",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(work / "source.mp4")],
        check=True,
    )
    job = {"id": "test", "options": {"num_clips": 3, "min_len": 15, "max_len": 30, "style": "bold", "framing": "face",
                                    "aspect": "9:16", "show_title": True, "genre": "business", "focus": "customers hiring",
                                    "remove_silence": False, "normalize": True, "tone": "curious"}}
    log = []

    def update(**c):
        job.update(c)
        log.append(c.get("stage"))

    pipeline.generate(work, job, update, transcript=fake_transcript(90))
    assert job["clips"], "no clips were produced"
    for clip in job["clips"]:
        assert clip["render"]["status"] == "ready", clip["render"]
        info = render.probe(work / clip["file"])
        assert (info["width"], info["height"]) == (1080, 1920), info
        assert 14 <= info["duration"] <= 31, info
        assert clip["publish"]["copy"]["youtube"]["title"]
        assert set(clip["breakdown"]) == {"hook", "clarity", "pacing", "novelty", "emotion", "visual", "relevance"}
        print(f"ok  generate  {clip['id']}  {info['duration']:.1f}s  score {clip['score']}  {clip['title'][:40]!r}")

    transcript = pipeline.read_json(work / "transcript.json")
    clip = job["clips"][0]
    for style in captions.PRESETS:
        for aspect, framing, silence in (("1:1", "blur", False), ("4:5", "manual", True), ("16:9", "center", False)):
            clip["edits"].update(style=style, aspect=aspect, framing=framing, manual_x=0.2, remove_silence=silence,
                                 caption_text=None, title_text="Edited title")
            before = clip["duration"]
            pipeline.render_clip(work, job, clip, transcript)
            info = render.probe(work / clip["file"])
            assert (info["width"], info["height"]) == tuple(captions.ASPECTS[aspect]), (aspect, info)
            if silence:
                assert clip["cuts"] > 0 and info["duration"] < before + 0.5, ("silence not removed", clip["cuts"])
        print(f"ok  re-render style {style:8} in 1:1, 4:5 (silences cut: {clip['cuts']}) and 16:9")

    clip["edits"].update(aspect="9:16", framing="face", remove_silence=False, caption_text="totally new caption words here")
    pipeline.render_clip(work, job, clip, transcript)
    assert "totally" in (work / clip["srt"]).read_text().lower()
    print("ok  caption text edit shows up in the SRT")

    keep = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if keep:
        shutil.copytree(work, keep, dirs_exist_ok=True)
    shutil.rmtree(work)
    print("All checks passed.")


if __name__ == "__main__":
    main()

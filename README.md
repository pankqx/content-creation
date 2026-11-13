# Clipzer

Turn one long video into a stack of captioned vertical shorts, on your own Ubuntu laptop, for free.

**Built, developed and owned by K S Pankaj.**

Clipzer listens to the whole video, scores every possible moment on seven signals, explains why it
picked each one, cuts the best into 9:16 (or 1:1, 4:5, 16:9), keeps the speaker's face in frame, burns
in word-by-word animated captions, and writes titles, descriptions and hashtags for each platform.

## Install on Ubuntu (one time)

```bash
git clone https://github.com/pankqx/content-creation.git
cd content-creation
./desktop/install.sh
```

The installer adds any missing system packages (ffmpeg, python3-venv, Noto fonts for Kannada and Hindi)
and puts **Clipzer** in your app menu and on the desktop. Open it like any other app: press the Super key
and type *Clipzer*. It opens in its own window and stops its server when you close the window. The
first start installs the Python packages, so give it a few minutes.

You can also run it from a terminal with `./run.sh` and open <http://localhost:8000>.

### Use the GTX 1650

Speech-to-text runs on the GPU when the CUDA libraries are present, and falls back to the CPU otherwise:

```bash
.venv/bin/pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12>=9,<10"
```

Video encoding uses the GPU encoder (NVENC) automatically when the Nvidia driver supports it. The chips at
the top of the app show what is active.

### Optional: an AI judge and copywriter

Without one, Clipzer ranks clips with its built-in scorer and writes copy from templates. With one, the AI
re-reads the shortlist (30% of the final score), writes better titles, and writes per-platform copy.
Add either option to the `.env` file:

- **OpenRouter** (online, free models): put a key from <https://openrouter.ai/keys> in `OPENROUTER_API_KEY`.
- **Ollama** (fully offline): install from <https://ollama.com>, then run `ollama pull gemma3:4b`. On a
  4 GB GPU, `gemma3:4b` may be slow; `gemma3:1b` is lighter (set `OLLAMA_MODEL`).

## Features

- **Input:** paste a link (YouTube and the other sites yt-dlp supports). It is checked before download,
  showing the title, channel and length, or the reason it can't be imported. You can also drag in a file.
- **Seven-signal scoring:** hook, stands alone, pacing, novelty, emotion (including loud peaks and
  laughter-like bursts), visual energy (camera cuts) and match to your focus. Every score lists its evidence.
- **AI director:** pick the kind of video (podcast, founders and business, comedy, education, motivation,
  entertainment, gaming) and say what to look for, such as "money lessons" or "the funniest bits".
- **Six caption styles:** Bold Creator, Clean Minimal, Karaoke Fill, Gaming Energy, Podcast Lower Third and
  Cinematic. The fonts are bundled. Kannada and Hindi captions switch to Noto fonts automatically.
- **Framing:** follow the face, centre, blurred fill, or a manual crop position.
- **Editor:** trim on a loudness timeline with handles that snap to words, fix misheard caption words,
  change title, style, aspect and framing, cut long pauses, even out loudness, add fades and a corner
  watermark, then re-render. Download the MP4 or an SRT file.
- **Publish:** titles, descriptions, hashtags and a pinned comment for YouTube Shorts, Instagram Reels,
  X and LinkedIn, in six tones, each with a copy button.
- **Learns your taste:** the up and down arrows on a clip shift future scoring toward what you like.
- Projects are saved, can be cancelled while running, and can be reopened later.

## Check that it works

```bash
.venv/bin/python tests/smoke_test.py
```

This generates a test video and runs scoring, all six caption styles, every aspect ratio, pause
cutting and caption editing. It needs ffmpeg only.

## Which videos to clip

Clip videos you own, videos licensed for reuse, or videos from clipping campaigns that invite clips.
The app asks you to confirm this for every project. Re-uploading other people's videos without permission
can get a channel removed, and it does not qualify for YouTube ad revenue.

## Honest limits

- Scores estimate how well a moment stands alone. They are not view predictions.
- Face tracking uses OpenCV's classic detector: fast, but weaker on side profiles and dark scenes. The
  crop is set once per clip, so it doesn't follow someone walking across the frame.
- The editor preview shows the last render. Changes appear after **Render changes** finishes.
- Emoji can't be burned into video, so they stay in the publishing text.

## Project layout

```
app/main.py        web server, job queue, API
app/pipeline.py    generate (whole video) and render (one clip)
app/ingest.py      link checking and download (yt-dlp)
app/transcribe.py  speech to text with word timings (faster-whisper)
app/analyze.py     loudness, laughter-like bursts, camera cuts
app/highlights.py  seven-signal scoring, genres, AI pass, feedback
app/captions.py    caption styles, .ass and .srt
app/render.py      reframing, pause cutting, loudness, fades, encode
app/publish.py     per-platform titles, descriptions, hashtags
app/llm.py         OpenRouter or Ollama, with fallbacks
web/               the interface (globe, stage, controls, editor)
desktop/           Ubuntu installer and launcher
assets/fonts/      caption fonts (SIL Open Font License, see OFL.txt)
```

Feature ideas were inspired by the open-source HypeSift AI project (MIT). The code here is Clipzer's own.

© K S Pankaj. All rights reserved.

# Clipzer

Turn one long video into a stack of vertical shorts. Clipzer listens to the whole video, picks the
moments worth clipping, crops them to 9:16 and burns in word-by-word captions. It runs on your own
computer, so there is nothing to pay for.

**Built, developed and owned by K S Pankaj.**

## What it does

1. **Import** a video from a link or a file.
2. **Listen**: Whisper turns speech into text with a timestamp for every word (English, Hindi, Kannada and more).
3. **Find moments**: an AI model scores the transcript for hooks, payoffs and punchlines. With no API key, a built-in scorer does the job.
4. **Cut and caption**: ffmpeg crops to 1080x1920, keeps the speaker's face in frame, and burns in animated captions and a title card.
5. **Review**: preview every clip in the browser, then download the ones you like.

## Set up (one time)

You need Python 3.10+ and ffmpeg.

| | Linux (Ubuntu) | Windows |
|---|---|---|
| ffmpeg | `sudo apt install ffmpeg` | `winget install Gyan.FFmpeg` |
| Start | `./run.sh` | double-click `run.bat` |

The first start creates a virtual environment and installs everything. Then open
<http://localhost:8000>.

Optional, in the `.env` file that appears after the first start:

- `OPENROUTER_API_KEY`: a free key from <https://openrouter.ai/keys> switches on the AI moment picker.
  Free model ids change over time. If the picker reports an error, choose another `:free` model on
  <https://openrouter.ai/models> and put its id in `OPENROUTER_MODEL`.
- `WHISPER_MODEL`: `small` is the right size for a 4 GB GPU such as the GTX 1650. Use `base` if it is slow.
- `CAPTION_FONT`: for Kannada captions, install the *Noto Sans Kannada* font and put its name here.

### Using the Nvidia GPU

Speech-to-text uses the GPU when the CUDA libraries are present, and falls back to the CPU when they
are not. To enable the GPU after the first start:

```
.venv/bin/pip install nvidia-cublas-cu12 nvidia-cudnn-cu12        # Linux
.venv\Scripts\pip install nvidia-cublas-cu12 nvidia-cudnn-cu12    # Windows
```

The status chips at the top of the page show whether ffmpeg, Whisper and the AI picker are ready.

## Check that it works

```
python tests/smoke_test.py
```

This builds a test video and runs the cutting, cropping and caption steps. It needs ffmpeg only.

## Which videos to clip

Clip videos you own, videos with a licence that allows it, or videos from a clipping campaign whose
owner invites clips. The app asks you to confirm this for every job. Re-uploading other people's
videos without permission can get a channel removed and does not qualify for ad revenue.

## Project layout

```
app/main.py        web server and job queue
app/pipeline.py    the four stages, in order
app/transcribe.py  speech to text (faster-whisper)
app/highlights.py  moment picking (OpenRouter, with a built-in fallback)
app/render.py      face-centred crop and encoding (ffmpeg, OpenCV)
app/captions.py    animated caption styles
web/               the interface
```

## Not built yet

- Upload straight to YouTube (needs a Google API project).
- Editing a clip's start and end by hand.
- Tracking a speaker who moves around during one clip. The crop is set once per clip.

© K S Pankaj. All rights reserved.

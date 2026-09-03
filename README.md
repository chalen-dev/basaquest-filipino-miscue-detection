# BasaQuest — Reading Proficiency Pipeline Prototype

A minimal, runnable proof of the BasaQuest Reading Proficiency Module's core
loop: a pupil reads a passage aloud into the browser, a scorer flags
word-level miscues, and a teacher reviews the flagged words against the
original recording before the result is marked validated.

This is a prototype, not the full system described in the capstone
manuscript — no database, no grade-level scaling, and Azure AI Speech's real
pronunciation assessment is still a stub (a local Whisper-based scorer fills
in for it). The goal is to prove the pipeline shape end to end behind an
interface clean enough that a real pronunciation API can be swapped in later
without touching the rest of the app.

See [ROADMAP.md](ROADMAP.md) for what's known-imperfect and what's planned
next — this file covers what exists and how to run it.

## How it works

1. **Reading screen** (`client/src/ReadingScreen.jsx`) — a language toggle
   (Filipino or English) plus a passage picker (`client/src/passage.js`'s
   `PASSAGE_VARIANTS`) for Filipino, which currently offers the original
   Datu Bago passage, a version with 5 words deliberately misspelled (an
   accuracy test — see `gop/test_recordings/deliberate_errors.json`), and two
   shorter grade-level passages. The pupil either records themselves reading
   the selected passage aloud via the browser `MediaRecorder` API (with a
   running timer), or uploads an existing recording (`.m4a`, `.mp3`, `.wav`,
   `.webm`, `.ogg`, `.aac`) instead of recording live.
2. **Scoring** (`server/src/scorers/`) — the recording and reference passage
   are POSTed to the backend, which runs them through whichever scorer is
   active behind a common interface (see below) and returns a per-word
   verdict: `correct`, `mispronounced`, `omitted`, or `inserted`.
3. **Teacher review screen** (`client/src/TeacherReviewScreen.jsx`) — plays
   back the recording, shows the passage with flagged words highlighted, and
   lets the teacher confirm or override each flagged word. Only after every
   flagged word has been reviewed can the teacher mark the session
   **validated**. Each flagged word also gets a "▶ Play Xs–Ys" button that
   plays just that word's chunk of the recording (with a small padding for
   audibility) and automatically stops at the end of it, so the teacher
   doesn't have to scrub the whole clip — except omitted words, which were
   never said and so have no audio moment to jump to (shown as "no audio
   (omitted)" instead).

## Swappable scorer

`server/src/scorers/scorerInterface.js` documents the contract every scorer
implementation must satisfy: given `{ passageText, audioFilePath }`, return
`{ words, durationSeconds, engine }`.

- `mockScorer.js` — the default. Ignores the actual audio and returns
  plausible-but-fake per-word results, so the rest of the pipeline can be
  built and demoed without any real speech processing.
- `whisperScorer.js` — a real, fully local implementation using OpenAI's
  Whisper model (via `@huggingface/transformers`, no cloud calls after the
  model is first downloaded). This is the manuscript's "on-device, lower
  confidence" fallback for when the cloud pronunciation service is
  unreachable. Whisper only transcribes audio to text — it has no notion of
  pronunciation accuracy — so word-level flags come from aligning its
  transcript against the known passage text (`wordAlignment.js`, the same
  edit-distance technique behind Word Error Rate), not from a real
  pronunciation/phoneme score. A word Whisper's language model "autocorrects"
  to the expected word will read as correct even if it was mispronounced —
  a real accuracy gap versus a purpose-built pronunciation API, and the
  reason this is a fallback rather than the default.
- `gopScorer.js` — runs the real, calibrated phoneme-level model from `gop/`
  (Phase 4's Goodness-of-Pronunciation scorer) by shelling out to
  `gop/score_recording.py` as a separate process per request. This is the
  only scorer that does real acoustic pronunciation scoring instead of
  transcript comparison — see "GOP scorer" below.
- `azureScorer.js` — still a stub, with notes on what a real Azure AI Speech
  pronunciation-assessment integration (the manuscript's preferred, cloud
  default path) would do in its place.
- `scorers/index.js` — the single switch point. Set the `SCORER_ENGINE` env
  var (`mock`, `whisper`, `gop`, or `azure`) and every route keeps working
  unchanged.

To use the real local Whisper scorer: `SCORER_ENGINE=whisper npm run dev`.
It also shells out to a bundled `ffmpeg` binary (`ffmpeg-static`) to convert
the browser's recording to the 16kHz mono PCM Whisper expects, so no separate
ffmpeg install is required. Swapping to `azure` will currently throw, since
`azureScorer.js` is still a stub.

### GOP scorer

`SCORER_ENGINE=gop` makes the website score recordings with the real trained
model (`gopScorer.js` calling `gop/score_recording.py`) instead of Whisper or
the mock. This is Filipino-only — submitting an English passage under this
engine throws a clear error rather than silently scoring nonsense, since the
model's CTC head was built from the Filipino phoneme inventory only.

Requirements, matching `gop/HOW TO RUN.txt`:

- `gop/.venv` must exist with its dependencies installed (see `gop/README.md`
  / `HOW TO RUN.txt` for the one-time `pip install` steps).
- A model directory (e.g. `models/final-model-child-augmented-v1`) and a
  calibration file for that same model (e.g.
  `gop/calibration-child-augmented.json`, produced by `calibrate.py`) must
  exist on disk. Reusing a calibration file from a different model gives
  meaningless thresholds — see `gop/README.md`.

By default `gopScorer.js` points at `gop/.venv/Scripts/python.exe`,
`models/final-model-child-augmented-v1`, and
`gop/calibration-child-augmented.json` — the exact setup this prototype has
been tested against. Override any of the three with env vars if your setup
differs:

```bash
# PowerShell
$env:SCORER_ENGINE = "gop"
$env:GOP_PYTHON = "D:\path\to\gop\.venv\Scripts\python.exe"   # optional override
$env:GOP_MODEL_DIR = "D:\path\to\models\some-other-model"      # optional override
$env:GOP_CALIBRATION = "D:\path\to\gop\some-other-calibration.json"  # optional override
npm run dev
```

Each request spawns a fresh Python process, and loading the model alone takes
~15-20s — a real, user-visible delay (a 40s recording takes roughly 30-40s
total to score), not a bug. A persistent Python worker process would remove
that cost but wasn't built here; if the delay becomes a problem, that's the
next thing to build.

### One shared model, two languages

The reading screen has an English/Filipino toggle (`client/src/passage.js`
holds a passage per language); whichever is selected is sent along as
`language`, and `whisperScorer.js` uses it only to tell the same model which
language to decode in (the `language` generation option — `"english"` or
`"tagalog"`, Whisper's own names from `openai/whisper`'s tokenizer LANGUAGES
table) rather than choosing a different underlying model.

The model is `Xenova/whisper-small` — the multilingual checkpoint (no `.en`
suffix), not an English-only one. This wasn't the first design: a dedicated
`whisper-small.en` for English plus the multilingual `whisper-small` for
Filipino was tried first, but running both loaded at once measured ~4.5-5GB
combined — too much for the 6-8GB, often Celeron/Pentium/i3-class laptops
this is meant to run on. Whisper's multilingual checkpoints are trained on
English too (it was the majority language in Whisper's original training
data), so multilingual `whisper-small` is already strong on English, not just
"acceptable" — the `.en`-only checkpoints have a small accuracy edge on
English specifically per OpenAI's own published benchmarks, but the gap is
modest, and it's a reasonable trade for roughly halving steady-state memory
on the actual target hardware. (Separately, `distil-whisper/distil-small.en`
was tried even before that for a speed win on the English-only path, but
distilled models have fewer decoder layers than a full Whisper model, and
this app's word-level timestamps need to index into per-layer cross-attention
weights to align words to audio — on distil-small.en that indexing goes out
of bounds and throws.)

The model is downloaded once (internet required only the first time, for
either language) and cached — `q8` (8-bit quantized) weights are requested
explicitly, since transformers.js's Node/CPU backend otherwise defaults to
full fp32 weights, several times larger and slower to both download and run
for no real accuracy benefit here.

The Filipino path has only been verified structurally (model loads, runs,
returns properly-shaped word-level output with timestamps) using
English-voice TTS reading Filipino text — that's real enough to prove the
plumbing, but says nothing about transcription accuracy on genuine Filipino
speech, which needs testing with an actual Filipino speaker.

No Whisper size or language closes the gap to a real pronunciation-assessment
API entirely, since this is still transcript-alignment, not phoneme-level
scoring.

`npm audit` reports a high-severity advisory in `adm-zip`, pulled in
transitively by `onnxruntime-node` (a `@huggingface/transformers`
dependency) for extracting its own bundled native binary at install time —
not something reachable from user-supplied data in this app's request path.

### Word-level audio timestamps

Both scorers attach an optional `startTime`/`endTime` (seconds) to each
`WordResult` (see `scorerInterface.js`) so the review screen can seek the
recording to the exact moment a flagged word was heard, instead of the
teacher scrubbing through the whole clip:

- `whisperScorer.js` gets these for real, from Whisper's word-level
  timestamps (`return_timestamps: 'word'`).
- `mockScorer.js` fakes them by spacing words evenly across the (also fake)
  estimated duration, so the seek feature is testable without waiting on a
  real model load.
- Omitted words never get a timestamp in either scorer — there's no audio
  position for a word that was never said.

### Microphone noise handling

`ReadingScreen.jsx` requests the mic with `noiseSuppression`,
`echoCancellation`, and `autoGainControl` enabled — the browser/OS's
built-in audio processing, applied for free before recording starts. This
is the "cheap" tier; a Discord/Krisp-level neural denoiser (e.g. RNNoise,
client- or server-side) would go further but isn't wired up here.

### Audio quality pre-filter

`server/src/audioQualityCheck.js` runs a free, local check (recording
duration and average volume via `ffmpeg`'s `volumedetect`) before any scorer
runs — rejecting a recording under 5 seconds or one that's effectively
silent with a 422 and a clear message, instead of spending money on a paid
scoring API (once `azure` is real) or compute time on the local Whisper
fallback for an obviously-bad take. `ReadingScreen.jsx` mirrors the duration
check client-side for instant feedback, but the server is what actually
enforces it.

## Running locally

Requires Node.js 18+. Two servers, run in separate terminals.

**Backend** (port 4000):
```bash
cd server
npm install
npm run dev
```

**Frontend** (port 5173, proxies `/api` and `/uploads` to the backend):
```bash
cd client
npm install
npm run dev
```

Open the printed `http://localhost:5173` URL, allow microphone access when
prompted, and walk through: record → submit for scoring → review flagged
words → validate.

## Notes on this prototype vs. the full design

- No database — sessions live in memory (`server/src/sessionsStore.js`) and
  are lost on server restart.
- No de-identification, retention/deletion policy, or auth — the manuscript's
  data-privacy handling (session IDs instead of names, 7-day retention caps,
  etc.) is out of scope for this pipeline proof.
- Two hardcoded passages (English, Filipino), no grade-level scaling. The
  Filipino passage is a placeholder translation for testing the pipeline's
  language plumbing — not reviewed for grade-level appropriateness or
  curriculum fit.
- No persistence of teacher overrides beyond the in-memory session.

## Project structure

```
server/
  src/
    index.js              Express app entry point
    sessionsStore.js       In-memory session storage
    audioQualityCheck.js   Rejects too-short/silent recordings before scoring
    routes/assessment.js   POST/GET/PATCH session endpoints
    scorers/
      scorerInterface.js   Documents the scorer contract
      mockScorer.js        Default mock implementation
      whisperScorer.js     Real local implementation (Whisper + alignment)
      wordAlignment.js     Edit-distance alignment: transcript -> word flags
      gopScorer.js          Shells out to gop/score_recording.py (real model)
      azureScorer.js       Stub for a future cloud implementation
      index.js             Picks the active scorer via SCORER_ENGINE
  uploads/                 Recorded/uploaded audio files (created at runtime)

client/
  src/
    passage.js               Reference passages: PASSAGES (en/fil) + PASSAGE_VARIANTS (fil picker)
    api.js                  Fetch wrappers for the backend
    ReadingScreen.jsx        Passage picker + recorder/upload + timer
    TeacherReviewScreen.jsx  Playback + flag review + validation
    App.jsx                  Switches between the two screens

gop/                        Standalone Python GOP scorer — see gop/README.md
  score_recording.py         CLI entry point, also called by server/src/scorers/gopScorer.js
  calibrate.py                Measures real GOP thresholds for a given model
```

"""HTTP front for the Filipino pronunciation scorer, for hosting on a Hugging Face Space.

The scorer itself is gop/basaquest_gop (Phase 4): the Phase 3 wav2vec2 phoneme
model plus Goodness-of-Pronunciation scoring. Run from the command line it
loads the 1.2 GB model on every call (15-20 s); this keeps one copy loaded for
the life of the process, so a request costs only the scoring itself.

One endpoint does the work:

    POST /score?words=<JSON list of the passage's words, as shown on screen>
         header  x-api-key: <GOP_API_KEY>
         body    the raw recording (anything ffmpeg can read)

and answers {"words": [...], "durationSeconds": n, "engine": "gop-local"}, one
entry per word in the same order as `words`, each with a status of "correct",
"mispronounced" or "omitted" (see gop/basaquest_gop/scorer.py for the rest).

Nothing is stored: the recording is written to a temporary file for the length
of the request and deleted after it.

Environment:
    GOP_API_KEY   required. Callers must send it in x-api-key. Set it as a
                  Space secret; without it every request is refused.
    GOP_MODEL_DIR where the model is (default: models/final-model-v2 beside this file)
"""

from __future__ import annotations

import hmac
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "gop"))

from basaquest_gop import PhonemeAcousticModel, load_thresholds, score_passage  # noqa: E402

MODEL_DIR = Path(os.environ.get("GOP_MODEL_DIR", ROOT / "models" / "final-model-v2"))
MAX_AUDIO_BYTES = 15 * 1024 * 1024
MAX_WORDS = 300

app = FastAPI(title="BasaQuest Filipino scorer")

# Loaded once, at startup. A request that arrives while it is loading simply
# waits for the server to come up.
MODEL = PhonemeAcousticModel(MODEL_DIR)
THRESHOLDS = load_thresholds()
# The model uses every CPU core for one request; two at once would only make
# both slower, so they take turns.
_SCORING_LOCK = threading.Lock()


def _check_key(provided: str | None) -> None:
    expected = os.environ.get("GOP_API_KEY", "")
    if not expected:
        raise HTTPException(status_code=500, detail="Server has no GOP_API_KEY configured.")
    if not provided or not hmac.compare_digest(provided.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Invalid API key.")


def _score(words: list[str], audio: bytes) -> dict:
    with tempfile.TemporaryDirectory(prefix="gop-") as tmp:
        path = Path(tmp) / "recording"
        path.write_bytes(audio)
        with _SCORING_LOCK:
            result = score_passage(" ".join(words), path, MODEL, thresholds=THRESHOLDS)
    # Only what the caller needs: leaves out the per-phoneme detail.
    return {
        "durationSeconds": result["durationSeconds"],
        "engine": result["engine"],
        "calibrated": result["calibration"]["calibrated"],
        "words": [
            {
                "index": w["index"],
                "word": w["word"],
                "status": w["status"],
                "confidence": w.get("confidence", 0.0),
                "unscorable": bool(w.get("unscorable", False)),
            }
            for w in result["words"]
        ],
    }


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "model": MODEL_DIR.name, "calibrated": THRESHOLDS.calibrated}


@app.post("/score")
async def score(request: Request, words: str, x_api_key: str | None = Header(default=None)) -> dict:
    _check_key(x_api_key)
    try:
        parsed = json.loads(words)
    except json.JSONDecodeError:
        parsed = None
    if (
        not isinstance(parsed, list)
        or not parsed
        or len(parsed) > MAX_WORDS
        or not all(isinstance(w, str) for w in parsed)
    ):
        raise HTTPException(status_code=400, detail="Missing or invalid words.")

    audio = await request.body()
    if not audio:
        raise HTTPException(status_code=400, detail="Missing audio body.")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Recording is too large.")

    try:
        return await run_in_threadpool(_score, parsed, audio)
    except ValueError as err:
        # e.g. no pronounceable words, or a recording too short to align.
        raise HTTPException(status_code=422, detail=str(err)) from err
    except Exception as err:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Scoring failed: {err}") from err

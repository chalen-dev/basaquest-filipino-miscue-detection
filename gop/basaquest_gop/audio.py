"""Audio loading: whatever the browser recorded -> 16kHz mono float32.

Everything goes through ffmpeg rather than a Python audio library. The
recordings this scorer receives come from the browser's MediaRecorder, which
produces webm/opus - not something libsndfile reads - and the sample rates
vary by device (the one real recording checked in under server/uploads is
22.05kHz, while the model requires exactly 16kHz). ffmpeg handles the decode
and the resample in one pass, and the Node server already ships it as a
dependency, so this adds nothing new to install.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import numpy as np

from .config import SAMPLE_RATE

_REPO_ROOT = Path(__file__).resolve().parents[2]
# The Node server depends on ffmpeg-static, so a working checkout already has
# a binary here even when ffmpeg isn't installed system-wide.
_BUNDLED_FFMPEG = _REPO_ROOT / "server" / "node_modules" / "ffmpeg-static" / "ffmpeg.exe"


def find_ffmpeg() -> str:
    """Resolves an ffmpeg binary, preferring an explicit override."""
    override = os.environ.get("BASAQUEST_FFMPEG")
    if override:
        if not Path(override).exists():
            raise FileNotFoundError(f"BASAQUEST_FFMPEG points at a missing file: {override}")
        return override

    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path

    if _BUNDLED_FFMPEG.exists():
        return str(_BUNDLED_FFMPEG)

    raise FileNotFoundError(
        "No ffmpeg found. Install it, or set BASAQUEST_FFMPEG to a binary. "
        f"(Also looked for the server's bundled copy at {_BUNDLED_FFMPEG}.)"
    )


def load_audio(path: Path | str) -> np.ndarray:
    """Decodes any ffmpeg-readable file to a mono float32 array at 16kHz.

    Raw f32le is piped through stdout rather than written to a temp file -
    one less thing to clean up, and these clips are small enough (a 60s
    passage is ~4MB as float32) that buffering them is not a concern.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"audio file not found: {path}")

    result = subprocess.run(
        [
            find_ffmpeg(),
            "-nostdin",
            "-loglevel", "error",
            "-i", str(path),
            "-ac", "1",
            "-ar", str(SAMPLE_RATE),
            "-f", "f32le",
            "-",
        ],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"ffmpeg failed to decode {path.name}: {stderr}")

    waveform = np.frombuffer(result.stdout, dtype=np.float32)
    if waveform.size == 0:
        raise ValueError(f"{path.name} decoded to zero samples")
    # frombuffer returns a read-only view over the subprocess bytes; the
    # feature extractor normalizes in place, so hand back a writable copy.
    return waveform.copy()


def load_wav_bytes(data: bytes) -> np.ndarray:
    """Same as load_audio but for in-memory audio - used by calibrate.py,
    which reads WAV bytes straight out of the Phase 2 parquet shards."""
    result = subprocess.run(
        [
            find_ffmpeg(),
            "-nostdin",
            "-loglevel", "error",
            "-i", "pipe:0",
            "-ac", "1",
            "-ar", str(SAMPLE_RATE),
            "-f", "f32le",
            "-",
        ],
        input=data,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"ffmpeg failed to decode in-memory audio: {stderr}")
    return np.frombuffer(result.stdout, dtype=np.float32).copy()

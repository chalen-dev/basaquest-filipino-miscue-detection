"""Loads the Phase 3 fine-tuned model and turns audio into frame posteriors.

Long recordings are processed in overlapping windows rather than one pass.
Two independent reasons, both of which matter here:

- **Memory.** Wav2Vec2's self-attention is quadratic in frame count. A 47s
  recording is ~2,350 frames, and the deployment target (ROADMAP's
  "Deployment architecture") is a 2-4GB VPS or a school lab desktop, not a
  workstation. Windowing bounds the peak regardless of how long a pupil reads.
- **Distribution.** 93.7% of the Phase 2 training rows are single-word clips
  and the Phase 3 run capped duration at 6.0s, so this model has effectively
  never seen a continuous 47-second input. Feeding it one is far outside what
  it was fine-tuned on; 20-second windows are still outside it, but much less
  so.

Stitching happens on the *frame posteriors*, not on any decoded output, and
windows start on exact multiples of the convolutional stride so a window's
local frame f maps to global frame `f + start_sample // stride` with no
rounding. Each window contributes only its centre - the overlap margins,
where a frame has less real audio context on one side, are discarded from
whichever window sees them at its edge.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import SAMPLE_RATE
from .g2p_bridge import phoneme_inventory

# Windowing defaults. Chosen for the memory bound described above rather than
# measured against accuracy - see gop/README.md's "What has and hasn't been
# measured". Set window_seconds=None to force a single pass.
DEFAULT_WINDOW_SECONDS = 20.0
DEFAULT_OVERLAP_SECONDS = 4.0


def conv_output_length(input_length: int, kernels, strides) -> int:
    """Frames the convolutional feature encoder emits for a given sample
    count. Reimplemented from the conv config rather than calling the model's
    private `_get_feat_extract_output_lengths`, so the window arithmetic below
    is a pure function that can be tested without loading a 1.2GB model."""
    for kernel, stride in zip(kernels, strides):
        input_length = (input_length - kernel) // stride + 1
    return input_length


@dataclass
class Window:
    start_sample: int
    end_sample: int
    keep_start_frame: int  # global, inclusive
    keep_end_frame: int    # global, exclusive


def plan_windows(
    n_samples: int, window_samples: int, hop_samples: int, stride: int, feat_len
) -> list[Window]:
    """Splits `n_samples` into overlapping windows plus the global frame range
    each one is responsible for. Kept ranges are contiguous, non-overlapping,
    and together cover every frame exactly once."""
    total_frames = feat_len(n_samples)
    if n_samples <= window_samples:
        return [Window(0, n_samples, 0, total_frames)]

    window_frames = feat_len(window_samples)
    hop_frames = hop_samples // stride
    overlap_frames = window_frames - hop_frames
    if overlap_frames <= 0:
        raise ValueError("window must be longer than hop, otherwise frames are dropped")
    # Split the overlap between the two windows that share it. right_margin
    # takes the remainder so left + right == overlap exactly, which is what
    # makes consecutive kept ranges meet without a gap.
    right_margin = overlap_frames - overlap_frames // 2

    windows: list[Window] = []
    start = 0
    keep_start = 0
    while True:
        end = min(start + window_samples, n_samples)
        offset = start // stride
        is_last = end >= n_samples
        if is_last:
            # Clamp rather than trusting that feat_len distributes exactly over
            # the split: the per-layer floor divisions can disagree by a frame.
            keep_end = min(total_frames, offset + feat_len(end - start))
        else:
            keep_end = offset + window_frames - right_margin
        windows.append(Window(start, end, keep_start, keep_end))
        if is_last:
            break
        keep_start = keep_end
        start += hop_samples
    return windows


class PhonemeAcousticModel:
    """The Phase 3 wav2vec2 CTC model, wrapped for inference only."""

    def __init__(self, model_dir: Path | str, device: str = "cpu"):
        # Imported lazily so the pure-Python parts of this package (and their
        # tests) don't need torch installed.
        import torch
        from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

        self._torch = torch
        model_dir = Path(model_dir)
        if not model_dir.exists():
            raise FileNotFoundError(
                f"model directory not found: {model_dir}\n"
                "Phase 3 saved the model to Google Drive at "
                "'My Drive/BasaQuest/final-model-v2'; it has to be downloaded "
                "locally before this scorer can run."
            )

        self.processor = Wav2Vec2Processor.from_pretrained(str(model_dir))
        self.model = Wav2Vec2ForCTC.from_pretrained(str(model_dir)).to(device).eval()
        self.device = device

        # CTC blank is the tokenizer's pad id - this is the convention
        # Wav2Vec2ForCTC's own loss uses, not an assumption.
        self.blank_id = self.model.config.pad_token_id
        self.vocab: dict[str, int] = self.processor.tokenizer.get_vocab()
        self.id_to_token: dict[int, str] = {i: t for t, i in self.vocab.items()}

        self._kernels = list(self.model.config.conv_kernel)
        self._strides = list(self.model.config.conv_stride)
        self.total_stride = int(np.prod(self._strides))
        self.seconds_per_frame = self.total_stride / SAMPLE_RATE

        # Competitors are the real phonemes only - see g2p_bridge's
        # `phoneme_inventory` for why this is derived from the G2P inventory
        # rather than from the model's own (larger) output vocabulary.
        inventory = phoneme_inventory()
        missing = [p for p in inventory if p not in self.vocab]
        if missing:
            raise KeyError(
                f"model vocabulary is missing G2P phonemes {missing} - the loaded "
                f"model at {model_dir} was not trained on this G2P inventory."
            )
        self.competitor_ids = np.array(
            sorted(self.vocab[p] for p in inventory), dtype=np.int64
        )

    def feat_len(self, n_samples: int) -> int:
        return conv_output_length(n_samples, self._kernels, self._strides)

    def encode_phonemes(self, phonemes: list[str]) -> list[int]:
        """Maps G2P output to token ids. Raises on an unknown symbol rather
        than substituting <unk>: the tokenizer's vocabulary was built from
        `filipino_g2p.full_vocabulary()`, so anything missing means the G2P and
        the model have drifted apart - a bug to fix, not to score around."""
        unknown = sorted({p for p in phonemes if p not in self.vocab})
        if unknown:
            raise KeyError(
                f"phonemes missing from the model vocabulary: {unknown}. "
                "The G2P and the trained model must share an inventory."
            )
        return [self.vocab[p] for p in phonemes]

    def log_probs(
        self,
        waveform: np.ndarray,
        window_seconds: float | None = DEFAULT_WINDOW_SECONDS,
        overlap_seconds: float = DEFAULT_OVERLAP_SECONDS,
    ) -> np.ndarray:
        """Returns (T, C) log-softmax frame posteriors for the whole waveform."""
        torch = self._torch

        # Normalize over the full utterance *before* splitting. The feature
        # extractor does zero-mean/unit-variance scaling, and running it
        # per-window would give each window its own scale - making frames
        # incomparable across a boundary, which is exactly what the stitched
        # matrix relies on.
        values = self.processor.feature_extractor(
            waveform, sampling_rate=SAMPLE_RATE
        ).input_values[0]
        values = np.asarray(values, dtype=np.float32)

        if window_seconds is None:
            windows = [Window(0, len(values), 0, self.feat_len(len(values)))]
        else:
            window_samples = int(window_seconds * SAMPLE_RATE) // self.total_stride * self.total_stride
            hop_samples = (
                int((window_seconds - overlap_seconds) * SAMPLE_RATE)
                // self.total_stride
                * self.total_stride
            )
            if hop_samples <= 0:
                raise ValueError("overlap_seconds must be smaller than window_seconds")
            windows = plan_windows(
                len(values), window_samples, hop_samples, self.total_stride, self.feat_len
            )

        pieces: list[np.ndarray] = []
        with torch.no_grad():
            for window in windows:
                chunk = values[window.start_sample : window.end_sample]
                tensor = torch.from_numpy(chunk).unsqueeze(0).to(self.device)
                logits = self.model(tensor).logits[0]
                frame_log_probs = torch.log_softmax(logits, dim=-1).cpu().numpy()

                offset = window.start_sample // self.total_stride
                local_start = window.keep_start_frame - offset
                local_end = min(window.keep_end_frame - offset, frame_log_probs.shape[0])
                pieces.append(frame_log_probs[local_start:local_end])

        return np.concatenate(pieces, axis=0).astype(np.float64)

"""Phase 4 of the Filipino Local Mispronunciation Detector: GOP scoring.

Turns the Phase 3 phoneme recognizer into a mispronunciation detector by
force-aligning the expected phoneme sequence (from Phase 1's G2P) to a
pupil's recording and scoring each expected phoneme against the best
competing phoneme. See ../ROADMAP.md and gop/README.md.
"""

from .acoustic import PhonemeAcousticModel
from .config import PLACEHOLDER_THRESHOLDS, Thresholds, load_thresholds
from .ctc_align import AlignmentError, ctc_forced_align, minimum_frames
from .gop import PhonemeScore, median_shift, score_phonemes
from .scorer import score_passage

__all__ = [
    "PhonemeAcousticModel",
    "PhonemeScore",
    "Thresholds",
    "AlignmentError",
    "ctc_forced_align",
    "minimum_frames",
    "score_phonemes",
    "median_shift",
    "score_passage",
    "load_thresholds",
    "PLACEHOLDER_THRESHOLDS",
]

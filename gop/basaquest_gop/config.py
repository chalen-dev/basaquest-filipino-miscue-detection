"""Tunable constants for GOP scoring, kept in one place.

The thresholds here decide whether a word is reported as mispronounced, so
they are the single biggest lever on how this scorer behaves - and, unlike
the model weights, they are cheap to change. They are deliberately *not*
hardcoded as if they were known-good: `calibrate.py` measures the real GOP
distribution on known-correct speech and writes `calibration.json`, which
overrides the placeholders below. `ScoreResult.calibration` reports which of
the two was actually used, so a result produced with uncalibrated thresholds
can never be quietly mistaken for a tuned one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

SAMPLE_RATE = 16000

# Package-relative default location written by calibrate.py.
DEFAULT_CALIBRATION_PATH = Path(__file__).resolve().parent.parent / "calibration.json"


@dataclass(frozen=True)
class Thresholds:
    """GOP cutoffs, in log-posterior-ratio units (see gop.py for the
    definition). Higher is better; 0.0 means the expected phoneme was exactly
    as likely as its strongest competitor over its aligned frames."""

    # A word is flagged when its average phoneme is weak...
    mispronounced_mean_gop: float
    # ...or when any single phoneme in it is badly wrong, which is what an
    # isolated substituted sound (the common real case) actually looks like.
    mispronounced_min_gop: float

    # Omission is inferred, not observed: forced alignment must consume every
    # expected phoneme somewhere, so a word the pupil never said gets squeezed
    # into a narrow stretch of audio belonging to its neighbours. Both
    # conditions must hold, since either alone also describes a fast-but-
    # correct word or a badly mispronounced one.
    #
    # The measure is the word's *extent* - last phoneme's end minus the first
    # phoneme's start - divided by its phoneme count, NOT the summed length of
    # the aligned spans. That distinction matters: CTC alignments are peaky,
    # so nearly every phoneme occupies one or two frames whether or not it was
    # actually spoken, and summed span length is therefore near-constant and
    # useless as an omission signal. Extent still works, because a genuinely
    # spoken word spreads its phoneme spikes across the word's real duration
    # while a skipped word has them crammed into a few adjacent frames.
    omission_gop: float
    omission_max_extent_per_phoneme: float

    # Maps distance-from-threshold to the 0-1 `confidence` field of a
    # WordResult. Larger = confidence grows more slowly with distance.
    confidence_scale: float

    calibrated: bool
    provenance: str

    def to_dict(self) -> dict:
        return asdict(self)


# Placeholders, used only until calibrate.py has been run. GOP is a log
# ratio, so 0.0 is the natural "as likely as its best competitor" boundary
# and these sit around it - a defensible starting point, but a guess about
# where correct and mispronounced speech actually separate, not a measurement.
PLACEHOLDER_THRESHOLDS = Thresholds(
    mispronounced_mean_gop=0.0,
    mispronounced_min_gop=-2.0,
    omission_gop=-4.0,
    # ~1.5 frames per phoneme is 30ms at this model's 20ms frame rate - far
    # below any real articulation rate, so a word packed this tightly was
    # almost certainly not spoken. Still a guess at the boundary until
    # calibrate.py measures the distribution on speech known to be complete.
    omission_max_extent_per_phoneme=1.5,
    confidence_scale=3.0,
    calibrated=False,
    provenance="placeholder defaults - calibrate.py has not been run",
)


def load_thresholds(path: Path | str | None = None) -> Thresholds:
    """Loads calibrated thresholds, falling back to the placeholders when no
    calibration file exists yet."""
    path = Path(path) if path is not None else DEFAULT_CALIBRATION_PATH
    if not path.exists():
        return PLACEHOLDER_THRESHOLDS
    data = json.loads(path.read_text(encoding="utf-8"))
    fields = {f: data[f] for f in Thresholds.__dataclass_fields__ if f in data}
    fields["calibrated"] = True
    return Thresholds(**fields)

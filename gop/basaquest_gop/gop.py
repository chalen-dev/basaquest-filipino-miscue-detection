"""Goodness of Pronunciation scoring on top of CTC frame posteriors.

The measure implemented here is the log posterior ratio (LPR) form of GOP,
which is the standard adaptation of Witt & Young's original GOP to a
neural/CTC acoustic model:

    LPP(p)  = mean over p's aligned frames of  log P(p | frame)
    GOP(p)  = LPP(p) - max over competitors q != p of LPP(q)

Read plainly: "how much more likely was the phoneme the pupil was *supposed*
to produce than the single most plausible thing they could have produced
instead." Positive means the expected phoneme won; negative means some other
phoneme fit the audio better, which is exactly the signal a mispronunciation
detector wants.

This is the property the whisper scorer structurally cannot have. Whisper
reports what it thinks was said; if its language model tidies a mispronounced
word back into the expected one, the error vanishes. GOP asks the acoustic
model directly and never consults a language model at all.

Two known distortions, both real and neither hidden:

- **CTC peakiness.** CTC models emit a phoneme on one or two frames and blank
  everywhere else, so aligned spans are short and the surrounding audio is
  attributed to no phoneme. GOP is therefore computed over the few frames the
  model was most confident about, which sharpens the measure but makes it
  noisier per-phoneme than a frame-dense HMM alignment would be.
- **Blank is excluded from the competitor set.** Blank absorbs most of the
  probability mass in a CTC model and is not a phoneme anyone can mispronounce
  into, so including it would drive every GOP negative and flag everything.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class PhonemeScore:
    """One expected phoneme, with where it landed and how well it scored."""

    phoneme: str
    gop: float
    log_posterior: float          # LPP of the expected phoneme
    best_competitor: str          # the phoneme that fit the audio best instead
    best_competitor_score: float
    start_frame: int
    end_frame: int                # exclusive

    @property
    def frame_count(self) -> int:
        return self.end_frame - self.start_frame


def score_phonemes(
    log_probs: np.ndarray,
    spans: list[tuple[int, int]],
    target_ids: list[int],
    id_to_token: dict[int, str],
    competitor_ids: np.ndarray,
) -> list[PhonemeScore]:
    """Computes GOP for every aligned phoneme.

    log_probs:      (T, C) log-softmax frame posteriors.
    spans:          per-phoneme (start, end_exclusive) from ctc_forced_align.
    target_ids:     the expected phoneme ids, parallel to `spans`.
    competitor_ids: real phoneme ids only - blank, <unk> and the word
                    delimiter must already be excluded (see the module
                    docstring on why blank in particular).
    """
    if len(spans) != len(target_ids):
        raise ValueError("spans and target_ids must be the same length")

    scores: list[PhonemeScore] = []
    for (start, end), target_id in zip(spans, target_ids):
        # Mean log-posterior of every phoneme over this phoneme's frames.
        lpp = log_probs[start:end].mean(axis=0)

        # The competitor set is the real phonemes minus the expected one; a
        # phoneme cannot compete with itself, and leaving it in would make
        # every GOP exactly 0.
        competitors = competitor_ids[competitor_ids != target_id]
        competitor_scores = lpp[competitors]
        best = int(competitors[np.argmax(competitor_scores)])

        own = float(lpp[target_id])
        rival = float(lpp[best])
        scores.append(
            PhonemeScore(
                phoneme=id_to_token[target_id],
                gop=own - rival,
                log_posterior=own,
                best_competitor=id_to_token[best],
                best_competitor_score=rival,
                start_frame=start,
                end_frame=end,
            )
        )
    return scores


def median_shift(scores: list[PhonemeScore], reference_median: float) -> list[PhonemeScore]:
    """Recentres one utterance's GOP values so their median matches
    `reference_median`, the median measured on the calibration speakers.

    This exists for a specific, anticipated failure: the model heard only
    adult speech, but the users are Grade 1-6 pupils, whose shorter vocal
    tracts put the formants higher. The likely symptom is not random noise
    but a *uniform downward shift* of every GOP for a given speaker - the
    model is systematically less sure about a voice unlike anything it was
    trained on, including on the words the pupil said perfectly. A fixed
    threshold then flags that child's whole passage.

    Subtracting the utterance's own median cancels exactly that kind of
    speaker-level offset while leaving the within-utterance contrasts - which
    is where the actual mispronunciation signal lives - untouched.

    It is off by default, because it is only the right correction if the shift
    really is uniform, and that has to be *measured* on real child recordings
    (Phase 5) rather than assumed. It also has a real cost: a pupil who
    mispronounces most of the passage has their errors recentred toward
    "normal for them," so genuinely poor readings get compressed toward
    correct. Do not enable it as a way to make results look better.
    """
    if not scores:
        return scores
    observed = float(np.median([s.gop for s in scores]))
    delta = reference_median - observed
    for s in scores:
        s.gop += delta
    return scores

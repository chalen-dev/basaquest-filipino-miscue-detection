"""Phase 4 top level: passage text + a recording -> the ScoreResult shape.

The output matches `server/src/scorers/scorerInterface.js` field for field, so
Phase 6 can wrap this behind the same `scorePassage({ passageText,
audioFilePath, language })` contract as mock/whisper/azure with no caller
changes. Two additive extensions the interface doesn't specify - `phonemes`
on each word, and a top-level `calibration` block - carry the detail Phase 5
needs to judge whether a flag was right; consumers that only know the
documented fields ignore them.

**What this scorer structurally cannot report: `inserted`.** Forced alignment
answers "where in this audio does each expected phoneme go," and it answers it
for every expected phoneme, always. There is no state in the alignment for
"the pupil said an extra word here." The whisper scorer gets insertions for
free precisely because it does the opposite thing - transcribe first, then
diff - and pays for it in the false mispronunciations described in the
ROADMAP. This is a genuine gap in coverage, not an oversight, and it is one
of the concrete things the Phase 5 head-to-head should weigh.

The related and more serious limitation is that forced alignment *assumes the
pupil read the whole passage in order*. Skip a line, repeat a sentence, or
read the wrong text entirely, and the aligner will still dutifully distribute
every expected phoneme across the audio - producing confident nonsense rather
than an error. That is what the ROADMAP's Backlog #2 content pre-filter is
for, and this scorer is a second, independent reason to build it.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .acoustic import DEFAULT_OVERLAP_SECONDS, DEFAULT_WINDOW_SECONDS, PhonemeAcousticModel
from .audio import load_audio
from .config import SAMPLE_RATE, Thresholds, load_thresholds
from .ctc_align import ctc_forced_align
from .g2p_bridge import text_to_phonemes
from .gop import PhonemeScore, median_shift, score_phonemes


def _round(value: float, places: int = 2) -> float:
    return float(np.round(value, places))


def _confidence(distance: float, scale: float) -> float:
    """Turns "how far past the threshold was this decision" into the 0-1
    `confidence` field. 0.5 means the word sat exactly on the boundary and the
    verdict could have gone either way; it approaches 1.0 as the evidence gets
    less ambiguous. It is a monotone squash of the GOP margin, not a
    calibrated probability that the verdict is correct."""
    return _round(0.5 + 0.5 * float(np.tanh(max(distance, 0.0) / scale)))


def score_passage(
    passage_text: str,
    audio_file_path: Path | str,
    model: PhonemeAcousticModel,
    language: str = "fil",
    thresholds: Thresholds | None = None,
    window_seconds: float | None = DEFAULT_WINDOW_SECONDS,
    overlap_seconds: float = DEFAULT_OVERLAP_SECONDS,
    normalize_median_to: float | None = None,
) -> dict:
    """Scores one recording against one passage.

    `normalize_median_to`, when set, recentres this utterance's GOP median to
    the given reference value before thresholding - the child-speech
    correction described in gop.py's `median_shift`. Off by default and it
    should stay off until Phase 5 measures whether the shift it assumes is
    real.
    """
    if language != "fil":
        raise ValueError(
            f"this scorer is Filipino-only, got language={language!r}. Its CTC head "
            "was built from filipino_g2p's inventory, so English phonemes are "
            "structurally unproducible - English needs its own model (see "
            "ROADMAP's 'Deployment architecture')."
        )

    thresholds = thresholds or load_thresholds()

    waveform = load_audio(audio_file_path)
    duration_seconds = len(waveform) / SAMPLE_RATE

    # Whitespace split, matching how whisperScorer builds `referenceWords` -
    # the `index` field has to mean the same position in both scorers for the
    # teacher review screen and the Phase 5 comparison to line up.
    tokens = text_to_phonemes(passage_text)

    # Tokens with no phonemic content (a stray punctuation-only token) can't
    # be aligned or scored; they keep their index so numbering stays intact.
    scorable = [(i, t) for i, t in enumerate(tokens) if t["phonemes"]]
    if not scorable:
        raise ValueError("passage contains no pronounceable words")

    target_phonemes: list[str] = []
    phoneme_to_word: list[int] = []  # index into `scorable`
    for position, (_, token) in enumerate(scorable):
        for phoneme in token["phonemes"]:
            target_phonemes.append(phoneme)
            phoneme_to_word.append(position)

    target_ids = model.encode_phonemes(target_phonemes)
    log_probs = model.log_probs(
        waveform, window_seconds=window_seconds, overlap_seconds=overlap_seconds
    )
    spans = ctc_forced_align(log_probs, target_ids, blank=model.blank_id)
    scores = score_phonemes(
        log_probs, spans, target_ids, model.id_to_token, model.competitor_ids
    )
    if normalize_median_to is not None:
        scores = median_shift(scores, normalize_median_to)

    by_word: dict[int, list[PhonemeScore]] = {}
    for position, score in zip(phoneme_to_word, scores):
        by_word.setdefault(position, []).append(score)

    token_to_position = {token_index: p for p, (token_index, _) in enumerate(scorable)}

    spf = model.seconds_per_frame
    words = []
    for token_index, token in enumerate(tokens):
        position = token_to_position.get(token_index)
        if position is None:
            # Unscorable token: reported so indices stay contiguous, but never
            # flagged - a punctuation mark isn't something a pupil got wrong.
            words.append(
                {
                    "index": token_index,
                    "word": token["word"],
                    "status": "correct",
                    "confidence": 0.0,
                    "unscorable": True,
                }
            )
            continue

        word_scores = by_word[position]
        gops = [s.gop for s in word_scores]
        mean_gop = float(np.mean(gops))
        min_gop = float(np.min(gops))
        # Extent, not summed span length - see config.Thresholds on why CTC
        # peakiness makes the latter useless for detecting an omission.
        extent = word_scores[-1].end_frame - word_scores[0].start_frame
        extent_per_phoneme = extent / len(word_scores)

        if (
            min_gop < thresholds.omission_gop
            and extent_per_phoneme <= thresholds.omission_max_extent_per_phoneme
        ):
            status = "omitted"
            distance = thresholds.omission_gop - min_gop
        elif (
            mean_gop < thresholds.mispronounced_mean_gop
            or min_gop < thresholds.mispronounced_min_gop
        ):
            status = "mispronounced"
            distance = max(
                thresholds.mispronounced_mean_gop - mean_gop,
                thresholds.mispronounced_min_gop - min_gop,
            )
        else:
            status = "correct"
            distance = min(
                mean_gop - thresholds.mispronounced_mean_gop,
                min_gop - thresholds.mispronounced_min_gop,
            )

        result = {
            "index": token_index,
            "word": token["word"],
            "status": status,
            "confidence": _confidence(distance, thresholds.confidence_scale),
            "meanGop": _round(mean_gop),
            "minGop": _round(min_gop),
            "extentPerPhoneme": _round(extent_per_phoneme),
            "phonemes": [
                {
                    "phoneme": s.phoneme,
                    "gop": _round(s.gop),
                    # What the acoustic model thought fit best instead. This is
                    # the single most useful field for Phase 5: it turns "this
                    # word was flagged" into "the model heard /d/ where /r/ was
                    # expected," which a teacher can actually check by ear.
                    "heard": s.best_competitor,
                    "startTime": _round(s.start_frame * spf, 3),
                    "endTime": _round(s.end_frame * spf, 3),
                }
                for s in word_scores
            ],
        }

        # An omitted word was never spoken, so there is no audio position to
        # seek to - the interface says callers treat a missing startTime as
        # "can't seek to this word". The alignment does hand us a span, but
        # it's the aligner being forced to put the phonemes somewhere, not a
        # moment the word was actually heard.
        if status != "omitted":
            result["startTime"] = _round(word_scores[0].start_frame * spf, 3)
            result["endTime"] = _round(word_scores[-1].end_frame * spf, 3)

        words.append(result)

    return {
        "words": words,
        "durationSeconds": round(duration_seconds),
        "engine": "gop-local",
        "calibration": {
            "calibrated": thresholds.calibrated,
            "provenance": thresholds.provenance,
            "thresholds": thresholds.to_dict(),
        },
    }

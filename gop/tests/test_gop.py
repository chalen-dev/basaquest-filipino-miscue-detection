"""Tests for the GOP measure itself.

The point of these is that GOP must be *directional*: a correctly produced
phoneme scores positive, a phoneme the model heard as something else scores
negative. Getting the sign or the competitor set wrong would still produce
plausible-looking numbers, and the whole scorer would then flag confidently
in the wrong direction - so the direction is asserted explicitly.
"""

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from basaquest_gop.gop import median_shift, score_phonemes

# A miniature stand-in for the real inventory: 4 phonemes + blank at index 4,
# mirroring the real model where blank is the last id rather than 0.
ID_TO_TOKEN = {0: "b", 1: "a", 2: "d", 3: "t", 4: "<pad>"}
COMPETITORS = np.array([0, 1, 2, 3])
BLANK = 4


def log_probs_from_weights(rows):
    """rows: per-frame unnormalised weights over the 5-token vocabulary."""
    logits = np.array(rows, dtype=np.float64)
    shifted = logits - logits.max(axis=1, keepdims=True)
    return shifted - np.log(np.exp(shifted).sum(axis=1, keepdims=True))


class TestScorePhonemes(unittest.TestCase):
    def test_expected_phoneme_dominating_gives_positive_gop(self):
        # One frame, overwhelmingly "b" (id 0), and "b" is what was expected.
        log_probs = log_probs_from_weights([[9.0, 0.0, 0.0, 0.0, 0.0]])
        scores = score_phonemes(log_probs, [(0, 1)], [0], ID_TO_TOKEN, COMPETITORS)

        self.assertEqual(len(scores), 1)
        self.assertGreater(scores[0].gop, 0.0)
        self.assertEqual(scores[0].phoneme, "b")

    def test_wrong_phoneme_dominating_gives_negative_gop(self):
        # Audio looks like "d" (id 2) but "b" (id 0) was expected - the exact
        # situation this scorer exists to catch.
        log_probs = log_probs_from_weights([[0.0, 0.0, 9.0, 0.0, 0.0]])
        scores = score_phonemes(log_probs, [(0, 1)], [0], ID_TO_TOKEN, COMPETITORS)

        self.assertLess(scores[0].gop, 0.0)
        self.assertEqual(scores[0].best_competitor, "d")

    def test_blank_is_never_the_best_competitor(self):
        """Blank carries most of the mass in a CTC model. If it were allowed
        to compete, every phoneme would score negative and every word would be
        flagged - so it must be excluded by the competitor set, not by luck."""
        log_probs = log_probs_from_weights([[1.0, 0.0, 0.0, 0.0, 20.0]])
        scores = score_phonemes(log_probs, [(0, 1)], [0], ID_TO_TOKEN, COMPETITORS)

        self.assertNotEqual(scores[0].best_competitor, "<pad>")
        self.assertGreater(scores[0].gop, 0.0, "blank leaking in would flip this negative")

    def test_gop_is_averaged_over_the_whole_span(self):
        # Two frames: one strongly right, one strongly wrong. The average
        # should land between what either frame alone would give.
        log_probs = log_probs_from_weights(
            [[9.0, 0.0, 0.0, 0.0, 0.0], [0.0, 0.0, 9.0, 0.0, 0.0]]
        )
        both = score_phonemes(log_probs, [(0, 2)], [0], ID_TO_TOKEN, COMPETITORS)[0]
        good = score_phonemes(log_probs[:1], [(0, 1)], [0], ID_TO_TOKEN, COMPETITORS)[0]
        bad = score_phonemes(log_probs[1:], [(0, 1)], [0], ID_TO_TOKEN, COMPETITORS)[0]

        self.assertLess(both.gop, good.gop)
        self.assertGreater(both.gop, bad.gop)

    def test_span_boundaries_are_carried_through(self):
        log_probs = log_probs_from_weights([[1.0, 0, 0, 0, 0]] * 10)
        scores = score_phonemes(
            log_probs, [(2, 5), (7, 9)], [0, 1], ID_TO_TOKEN, COMPETITORS
        )
        self.assertEqual((scores[0].start_frame, scores[0].end_frame), (2, 5))
        self.assertEqual(scores[0].frame_count, 3)
        self.assertEqual((scores[1].start_frame, scores[1].end_frame), (7, 9))

    def test_rejects_mismatched_lengths(self):
        log_probs = log_probs_from_weights([[1.0, 0, 0, 0, 0]] * 4)
        with self.assertRaises(ValueError):
            score_phonemes(log_probs, [(0, 2)], [0, 1], ID_TO_TOKEN, COMPETITORS)


class TestMedianShift(unittest.TestCase):
    def make_scores(self, gops):
        log_probs = log_probs_from_weights([[1.0, 0, 0, 0, 0]] * len(gops))
        scores = score_phonemes(
            log_probs,
            [(i, i + 1) for i in range(len(gops))],
            [0] * len(gops),
            ID_TO_TOKEN,
            COMPETITORS,
        )
        for score, gop in zip(scores, gops):
            score.gop = gop
        return scores

    def test_recentres_the_median(self):
        scores = self.make_scores([-5.0, -4.0, -3.0])
        median_shift(scores, reference_median=2.0)
        self.assertAlmostEqual(float(np.median([s.gop for s in scores])), 2.0)

    def test_preserves_within_utterance_contrast(self):
        """The correction targets a uniform speaker-level offset. The relative
        ordering and spacing of phonemes - where the mispronunciation signal
        actually is - must survive it untouched."""
        original = [-5.0, -4.0, 1.0]
        scores = self.make_scores(list(original))
        median_shift(scores, reference_median=2.0)
        shifted = [s.gop for s in scores]

        for a, b in zip(original, shifted):
            self.assertAlmostEqual(b - shifted[0], a - original[0])

    def test_empty_is_a_no_op(self):
        self.assertEqual(median_shift([], reference_median=1.0), [])


if __name__ == "__main__":
    unittest.main()

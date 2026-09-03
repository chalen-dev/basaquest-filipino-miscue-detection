"""Tests for the vendored CTC forced aligner.

Everything downstream - every GOP value, every word flag, every timestamp -
is computed from the frame spans this produces, so it gets checked against
hand-worked cases and invariant/property tests rather than only against
itself. When torchaudio happens to be installed, its (deprecated)
implementation is used as an independent oracle.
"""

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from basaquest_gop.ctc_align import AlignmentError, ctc_forced_align, minimum_frames


def log_probs_from_preference(preferences: list[int], vocab_size: int, strength=8.0):
    """Builds (T, C) log-probs where frame t strongly prefers preferences[t]."""
    logits = np.zeros((len(preferences), vocab_size))
    for t, token in enumerate(preferences):
        logits[t, token] = strength
    # log-softmax
    shifted = logits - logits.max(axis=1, keepdims=True)
    return shifted - np.log(np.exp(shifted).sum(axis=1, keepdims=True))


class TestMinimumFrames(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(minimum_frames([]), 0)

    def test_distinct_tokens_need_one_frame_each(self):
        self.assertEqual(minimum_frames([1, 2, 3]), 3)

    def test_repeated_tokens_need_a_separating_blank(self):
        # "a a" cannot be emitted as two adjacent frames of 'a' - CTC would
        # collapse them to a single 'a'. A blank must sit between them.
        self.assertEqual(minimum_frames([1, 1]), 3)
        self.assertEqual(minimum_frames([1, 1, 1]), 5)
        self.assertEqual(minimum_frames([1, 1, 2]), 4)


class TestForcedAlign(unittest.TestCase):
    def test_single_token_lands_on_its_frame(self):
        # blank, token 1, blank -> the middle frame is the only one preferring 1
        log_probs = log_probs_from_preference([0, 1, 0], vocab_size=3)
        self.assertEqual(ctc_forced_align(log_probs, [1], blank=0), [(1, 2)])

    def test_two_tokens_in_order(self):
        log_probs = log_probs_from_preference([0, 1, 1, 0, 2, 0], vocab_size=3)
        spans = ctc_forced_align(log_probs, [1, 2], blank=0)
        self.assertEqual(spans, [(1, 3), (4, 5)])

    def test_repeated_token_is_split_by_a_blank(self):
        log_probs = log_probs_from_preference([1, 0, 1], vocab_size=3)
        spans = ctc_forced_align(log_probs, [1, 1], blank=0)
        self.assertEqual(spans, [(0, 1), (2, 3)])

    def test_nonzero_blank_index(self):
        # The real model's blank is the <pad> id (35), not 0. Verify the
        # aligner doesn't quietly assume the torchaudio convention.
        blank = 35
        log_probs = log_probs_from_preference([blank, 7, blank, 12, blank], vocab_size=38)
        spans = ctc_forced_align(log_probs, [7, 12], blank=blank)
        self.assertEqual(spans, [(1, 2), (3, 4)])

    def test_every_frame_is_used_or_is_blank(self):
        log_probs = log_probs_from_preference([0, 1, 1, 1, 0, 0, 2, 0], vocab_size=3)
        spans = ctc_forced_align(log_probs, [1, 2], blank=0)
        self.assertEqual(spans, [(1, 4), (6, 7)])

    def test_raises_when_audio_is_too_short_for_the_passage(self):
        log_probs = log_probs_from_preference([0, 1], vocab_size=4)
        with self.assertRaises(AlignmentError):
            ctc_forced_align(log_probs, [1, 2, 3], blank=0)

    def test_rejects_blank_in_targets(self):
        log_probs = log_probs_from_preference([0, 1, 0], vocab_size=3)
        with self.assertRaises(ValueError):
            ctc_forced_align(log_probs, [1, 0], blank=0)

    def test_rejects_out_of_range_target(self):
        log_probs = log_probs_from_preference([0, 1, 0], vocab_size=3)
        with self.assertRaises(ValueError):
            ctc_forced_align(log_probs, [99], blank=0)

    def test_empty_targets(self):
        log_probs = log_probs_from_preference([0, 0], vocab_size=3)
        self.assertEqual(ctc_forced_align(log_probs, [], blank=0), [])

    def test_passage_length_sequence(self):
        """Regression: the backtrack accumulator must not inherit the uint8
        dtype of the backpointer table.

        A real Filipino passage is ~450 phonemes, giving ~900 extended states.
        With NumPy 2 promotion, subtracting a uint8 backpointer from a Python
        int produced a uint8 and wrapped past 255 - so every short test passed
        while any actual passage raised OverflowError. Found by running the
        real 46.7s recording, not by a unit test, which is why this one now
        uses a realistic length.
        """
        blank = 35
        vocab_size = 38
        targets = [(i % 30) + 1 for i in range(500)]
        # Alternate blank/token frames so the sequence is comfortably alignable.
        preferences = []
        for token in targets:
            preferences.extend([blank, token, blank])

        log_probs = log_probs_from_preference(preferences, vocab_size=vocab_size)
        spans = ctc_forced_align(log_probs, targets, blank=blank)

        self.assertEqual(len(spans), len(targets))
        previous_end = 0
        for start, end in spans:
            self.assertGreater(end, start)
            self.assertGreaterEqual(start, previous_end)
            previous_end = end


class TestAlignmentInvariants(unittest.TestCase):
    """Properties that must hold for *any* input, checked over random cases.

    These are the guarantees scorer.py relies on: it slices `log_probs` by
    these spans and assumes each phoneme got at least one frame, so a
    zero-width or out-of-order span would produce a silent NaN rather than an
    error.
    """

    def test_invariants_over_random_inputs(self):
        rng = np.random.default_rng(20260722)
        vocab_size = 38
        blank = 35
        phoneme_ids = [i for i in range(vocab_size) if i != blank]

        for trial in range(200):
            n_targets = int(rng.integers(1, 12))
            targets = [int(rng.choice(phoneme_ids)) for _ in range(n_targets)]
            n_frames = int(rng.integers(minimum_frames(targets), minimum_frames(targets) + 40))
            log_probs = np.log(rng.dirichlet(np.ones(vocab_size), size=n_frames))

            spans = ctc_forced_align(log_probs, targets, blank=blank)

            with self.subTest(trial=trial, targets=targets, frames=n_frames):
                self.assertEqual(len(spans), len(targets))
                previous_end = 0
                for start, end in spans:
                    self.assertGreater(end, start, "span must cover >= 1 frame")
                    self.assertGreaterEqual(start, previous_end, "spans must not overlap")
                    self.assertLessEqual(end, n_frames, "span must stay in range")
                    previous_end = end

    def test_optimal_path_beats_a_plausible_alternative(self):
        """The returned alignment should be the highest-scoring one, not merely
        a valid one. Checks the Viterbi score against an exhaustive search over
        all valid alignments for a small case."""
        rng = np.random.default_rng(7)
        vocab_size = 5
        blank = 0
        n_frames = 8
        # [1, 1, 2] exercises the repeated-label rule: the first two must be
        # separated by a blank, so fewer alignments are legal than for [1,2,3].
        for targets in ([1, 2, 3], [1, 1, 2]):
            with self.subTest(targets=targets):
                log_probs = np.log(rng.dirichlet(np.ones(vocab_size), size=n_frames))

                spans = ctc_forced_align(log_probs, targets, blank=blank)
                achieved = self._path_score(log_probs, spans, targets, blank, n_frames)

                best = max(
                    self._path_score(log_probs, candidate, targets, blank, n_frames)
                    for candidate in self._all_alignments(n_frames, targets)
                )
                self.assertAlmostEqual(achieved, best, places=9)

    @staticmethod
    def _path_score(log_probs, spans, targets, blank, n_frames):
        total = 0.0
        covered = np.zeros(n_frames, dtype=bool)
        for (start, end), target in zip(spans, targets):
            total += log_probs[start:end, target].sum()
            covered[start:end] = True
        total += log_probs[~covered, blank].sum()
        return total

    @staticmethod
    def _all_alignments(n_frames, targets):
        """Every valid CTC alignment of `targets` into `n_frames`, as spans.

        Brute force over non-decreasing boundaries - only viable for tiny
        cases, which is the point of using it as an oracle. Two rules make
        this the real CTC constraint set rather than a naive one:

        - Consecutive spans may *touch* (end == next start). Two different
          adjacent labels need no blank between them, and forbidding that was
          a bug in the first version of this test - it made the oracle miss
          the genuinely optimal path the aligner had correctly found.
        - Identical adjacent labels must have a gap of >= 1 blank frame,
          otherwise CTC's collapse rule would merge them into one label.
        """
        from itertools import combinations_with_replacement

        n_targets = len(targets)
        for boundaries in combinations_with_replacement(range(n_frames + 1), 2 * n_targets):
            spans = [(boundaries[2 * i], boundaries[2 * i + 1]) for i in range(n_targets)]
            if any(end <= start for start, end in spans):
                continue
            valid = True
            for i in range(n_targets - 1):
                gap = spans[i + 1][0] - spans[i][1]
                if gap < 0 or (gap == 0 and targets[i] == targets[i + 1]):
                    valid = False
                    break
            if valid:
                yield spans


class TestAgainstTorchaudio(unittest.TestCase):
    """Cross-check against torchaudio's implementation where available.

    Skipped rather than required: torchaudio's `forced_align` is deprecated
    with removal announced for 2.9, which is precisely why this project
    vendors its own. It is still a useful independent oracle when present.
    """

    def test_matches_torchaudio(self):
        try:
            import torch
            import torchaudio.functional as F
        except ImportError:
            self.skipTest("torchaudio not installed (expected - see ctc_align.py)")

        rng = np.random.default_rng(99)
        vocab_size = 12
        blank = 0
        for _ in range(20):
            targets = [int(rng.integers(1, vocab_size)) for _ in range(5)]
            n_frames = 30
            log_probs = np.log(rng.dirichlet(np.ones(vocab_size), size=n_frames))

            ours = ctc_forced_align(log_probs, targets, blank=blank)

            labels, _ = F.forced_align(
                torch.tensor(log_probs, dtype=torch.float32).unsqueeze(0),
                torch.tensor([targets], dtype=torch.int32),
                blank=blank,
            )
            theirs = self._spans_from_labels(labels[0].numpy(), targets, blank)
            self.assertEqual(ours, theirs)

    @staticmethod
    def _spans_from_labels(labels, targets, blank):
        spans = []
        index = 0
        start = None
        for t, label in enumerate(labels):
            if index < len(targets) and label == targets[index] and label != blank:
                if start is None:
                    start = t
            elif start is not None:
                spans.append((start, t))
                start = None
                index += 1
        if start is not None:
            spans.append((start, len(labels)))
        return spans


if __name__ == "__main__":
    unittest.main()

"""Tests for the frame arithmetic behind windowed inference.

These cover the pure functions only - no model is loaded, so they run without
the 1.2GB checkpoint being present. The stitching index math is exactly the
kind of thing that fails silently (a one-frame drift shifts every timestamp
after it and quietly corrupts the alignment), so it is checked directly
rather than inferred from the final output looking plausible.
"""

import sys
import unittest
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from basaquest_gop.acoustic import conv_output_length, plan_windows

# facebook/wav2vec2-xls-r-300m's feature encoder, which the Phase 3 model
# inherits unchanged (the CNN encoder was frozen during fine-tuning).
KERNELS = [10, 3, 3, 3, 3, 2, 2]
STRIDES = [5, 2, 2, 2, 2, 2, 2]
TOTAL_STRIDE = 320
feat_len = partial(conv_output_length, kernels=KERNELS, strides=STRIDES)


class TestConvOutputLength(unittest.TestCase):
    def test_one_second_gives_49_frames(self):
        # 320-sample total stride at 16kHz = 20ms per frame, minus the frames
        # lost to the receptive field at the edges. The Phase 3 notebook's
        # "duration * 50fps" filter was using this same ~50Hz figure.
        self.assertEqual(feat_len(16000), 49)

    def test_scales_roughly_linearly(self):
        self.assertEqual(feat_len(160000), 499)

    def test_monotonic_and_never_negative_for_short_input(self):
        previous = -1
        for n in range(0, 2000, 37):
            length = feat_len(n)
            self.assertGreaterEqual(length, previous)
            previous = length


class TestPlanWindows(unittest.TestCase):
    def plan(self, n_samples, window_seconds=20.0, overlap_seconds=4.0):
        window_samples = int(window_seconds * 16000) // TOTAL_STRIDE * TOTAL_STRIDE
        hop_samples = (
            int((window_seconds - overlap_seconds) * 16000) // TOTAL_STRIDE * TOTAL_STRIDE
        )
        return plan_windows(n_samples, window_samples, hop_samples, TOTAL_STRIDE, feat_len)

    def test_short_audio_is_a_single_window(self):
        windows = self.plan(16000 * 5)
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0].keep_start_frame, 0)
        self.assertEqual(windows[0].keep_end_frame, feat_len(16000 * 5))

    def test_long_audio_is_split(self):
        windows = self.plan(int(16000 * 46.73))
        self.assertGreater(len(windows), 1)

    def test_kept_ranges_tile_the_whole_output_exactly_once(self):
        """The stitched matrix must have every frame present, once, in order -
        this is what makes a windowed run interchangeable with a single pass."""
        for duration in (7.0, 20.0, 21.0, 46.73, 90.0, 180.0):
            with self.subTest(duration=duration):
                n_samples = int(16000 * duration)
                windows = self.plan(n_samples)

                self.assertEqual(windows[0].keep_start_frame, 0)
                for previous, current in zip(windows, windows[1:]):
                    self.assertEqual(
                        previous.keep_end_frame,
                        current.keep_start_frame,
                        "kept ranges must be contiguous - no gap, no overlap",
                    )
                total = sum(w.keep_end_frame - w.keep_start_frame for w in windows)
                self.assertEqual(total, windows[-1].keep_end_frame)
                # Within one frame of a single pass over the whole input: the
                # per-layer floor divisions don't distribute perfectly over a
                # split, which is why the last window clamps rather than trusts.
                self.assertLessEqual(abs(windows[-1].keep_end_frame - feat_len(n_samples)), 1)

    def test_local_slice_indices_stay_inside_each_window(self):
        """scorer/acoustic slice each window's output by (keep - offset). Those
        indices must be in range, or numpy would silently return a short array
        and shift every later frame."""
        for duration in (7.0, 21.0, 46.73, 120.0):
            with self.subTest(duration=duration):
                n_samples = int(16000 * duration)
                for window in self.plan(n_samples):
                    frames_here = feat_len(window.end_sample - window.start_sample)
                    offset = window.start_sample // TOTAL_STRIDE
                    local_start = window.keep_start_frame - offset
                    local_end = window.keep_end_frame - offset
                    self.assertGreaterEqual(local_start, 0)
                    self.assertLess(local_start, local_end)
                    self.assertLessEqual(local_end, frames_here)

    def test_window_starts_are_stride_aligned(self):
        """A window starting off a stride boundary would make the local->global
        frame mapping inexact, drifting every timestamp downstream."""
        for window in self.plan(int(16000 * 60)):
            self.assertEqual(window.start_sample % TOTAL_STRIDE, 0)

    def test_rejects_hop_longer_than_window(self):
        with self.assertRaises(ValueError):
            plan_windows(16000 * 60, 16000, 32000, TOTAL_STRIDE, feat_len)


if __name__ == "__main__":
    unittest.main()

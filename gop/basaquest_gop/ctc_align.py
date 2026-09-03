"""CTC forced alignment (Viterbi over the standard blank-extended sequence).

Why this is implemented here rather than imported from torchaudio: the plan
for Phase 4 assumed `torchaudio.functional.forced_align`, but that function
carries a deprecation notice announcing removal in torchaudio 2.9 (the
library moved into maintenance mode - pytorch/audio#3902). Depending on it
would either pin this project to torchaudio <=2.8 forever or leave a known
expiry date in the one piece of Phase 4 that everything else is built on.

The algorithm is ~60 lines and completely standard, so vendoring it costs
little and removes both the deprecation risk and a second heavyweight
dependency (torch alone is enough). It also sidesteps torchaudio's
`batch_size == 1` restriction and its blank-index conventions - this
project's CTC blank is the tokenizer's <pad> id (35), not 0.

`test_ctc_align.py` checks this against hand-computed cases, and against
torchaudio's implementation when torchaudio happens to be installed.
"""

from __future__ import annotations

import numpy as np

# Not -np.inf: an all-(-inf) column would make argmax meaningless and produce
# NaN when added to an emission score. A large finite negative behaves the
# same for path selection while staying arithmetically well-defined.
NEG_INF = -1e30


class AlignmentError(ValueError):
    """Raised when the target sequence cannot fit in the available frames."""


def minimum_frames(targets: list[int]) -> int:
    """Frames a CTC path needs to emit `targets`: one per token, plus one
    separating blank between each pair of *identical* adjacent tokens."""
    if not targets:
        return 0
    repeats = sum(1 for a, b in zip(targets, targets[1:]) if a == b)
    return len(targets) + repeats


def ctc_forced_align(
    log_probs: np.ndarray, targets: list[int], blank: int
) -> list[tuple[int, int]]:
    """Align `targets` to `log_probs` and return one frame span per target.

    log_probs: (T, C) log-softmax'd frame posteriors.
    targets:   token ids, none of which may be `blank`.
    returns:   [(start_frame, end_frame_exclusive), ...], one per target,
               covering only the frames the Viterbi path actually spent on
               that token - blank frames belong to no target and are excluded.

    Spans are contiguous and non-overlapping, in order, and every target is
    guaranteed at least one frame: the path advances through the extended
    sequence monotonically in steps of 0/1/2, and a step of 2 only ever jumps
    over a blank, never over a label.
    """
    if log_probs.ndim != 2:
        raise ValueError(f"log_probs must be (T, C), got shape {log_probs.shape}")
    T, C = log_probs.shape
    if not targets:
        return []
    if blank in targets:
        raise ValueError("targets must not contain the blank id")
    if max(targets) >= C or min(targets) < 0:
        raise ValueError(f"target id out of range for vocabulary size {C}")

    need = minimum_frames(targets)
    if T < need:
        raise AlignmentError(
            f"{T} frames is too few to align {len(targets)} phonemes "
            f"(needs at least {need}). The recording is too short for the passage."
        )

    # Extended sequence: blank, y1, blank, y2, ..., yL, blank. Labels sit on
    # odd indices, so label i (0-based) lives at s = 2i + 1.
    L = len(targets)
    S = 2 * L + 1
    ext = np.full(S, blank, dtype=np.int64)
    ext[1::2] = targets

    # A 2-step jump lands on a label and skips the blank before it. That is
    # only legal when the two labels differ - identical adjacent tokens must
    # be separated by a blank or CTC would collapse them into one.
    skip_ok = np.zeros(S, dtype=bool)
    if L > 1:
        odd = np.arange(3, S, 2)
        skip_ok[odd] = ext[odd] != ext[odd - 2]

    emissions = log_probs[:, ext]  # (T, S), gathered once

    alpha = np.full(S, NEG_INF, dtype=np.float64)
    alpha[0] = emissions[0, 0]
    alpha[1] = emissions[0, 1]
    backpointers = np.zeros((T, S), dtype=np.uint8)

    for t in range(1, T):
        prev1 = np.empty(S)
        prev1[0] = NEG_INF
        prev1[1:] = alpha[:-1]

        prev2 = np.empty(S)
        prev2[:2] = NEG_INF
        prev2[2:] = alpha[:-2]
        np.putmask(prev2, ~skip_ok, NEG_INF)

        stacked = np.stack((alpha, prev1, prev2))  # (3, S): stay / +1 / +2
        choice = np.argmax(stacked, axis=0)
        alpha = stacked[choice, np.arange(S)] + emissions[t]
        backpointers[t] = choice

    # A valid path ends on the final label or the trailing blank.
    end_state = S - 1 if alpha[S - 1] >= alpha[S - 2] else S - 2
    if alpha[end_state] <= NEG_INF / 2:
        raise AlignmentError("no valid CTC path exists for this target sequence")

    path = np.empty(T, dtype=np.int64)
    state = end_state
    for t in range(T - 1, 0, -1):
        path[t] = state
        # int() is load-bearing: backpointers is uint8, and under NumPy 2's
        # promotion rules `python_int - np.uint8` yields a uint8, which wraps
        # around silently once the extended sequence passes 255 states. A real
        # passage is ~450 phonemes (S ~ 900), so this only ever showed up on
        # full-length input - never in a small unit test.
        state -= int(backpointers[t][state])
    path[0] = state

    spans: list[tuple[int, int]] = []
    for i in range(L):
        frames = np.flatnonzero(path == 2 * i + 1)
        # Guaranteed non-empty by the step-of-2-never-skips-a-label argument
        # above; assert rather than silently emitting a degenerate span.
        assert frames.size > 0, f"phoneme {i} received no frames"
        spans.append((int(frames[0]), int(frames[-1]) + 1))
    return spans

"""Measures whether GOP can tell a correct phoneme from a wrong one.

This is the evaluation Phase 4 needed and PER could not provide. PER measures
free decoding; GOP never free-decodes - forced alignment constrains the output
to exactly the expected phonemes. A model can have poor PER (because it
hallucinates extra phonemes when left to decode freely) while still assigning
sensibly higher posteriors to phonemes that were genuinely produced, which is
all GOP requires. Judging Phase 4 by PER understates it substantially, as
measuring both on the same recording showed.

**Method.** The corpus has no mispronunciation labels (ROADMAP is explicit
about this), so substitutions are injected synthetically: take audio believed
to be a correct reading, corrupt a fraction of the expected phoneme sequence,
re-run GOP, and compare scores at corrupted positions against untouched ones.
The summary statistic is AUC - the probability that a genuinely-spoken phoneme
outscores a substituted one. 0.5 is a coin flip; 1.0 is perfect separation.

**Two substitution modes, and the difference matters.** `random` picks any
other phoneme, which is often acoustically obvious and flatters the scorer.
`confusable` picks a plausible neighbour - /i/ for /e/, /b/ for /p/, or the
stressed/unstressed pair of the same vowel - which is what a real reader
actually does. Trust the `confusable` number; treat `random` as an upper bound.

Even `confusable` is a synthetic proxy: it substitutes a phoneme cleanly,
whereas a real mispronunciation is often a partial or intermediate sound. This
tool answers "is the signal there at all," not "how well does it work on
children," which only real recordings and a listening teacher can answer.

    python evaluate_discrimination.py --model-dir ../models/final-model-v2 \
        --audio ../server/uploads/<file>.wav --passage builtin:fil
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np

GOP_DIR = Path(__file__).resolve().parent
REPO_ROOT = GOP_DIR.parent
sys.path.insert(0, str(GOP_DIR))

from basaquest_gop import PhonemeAcousticModel, ctc_forced_align, score_phonemes
from basaquest_gop.audio import load_audio, load_wav_bytes
from basaquest_gop.ctc_align import AlignmentError
from basaquest_gop.g2p_bridge import phoneme_inventory, text_to_phonemes

# Phonemes a real Filipino reader plausibly confuses. Vowel quality pairs and
# the stressed/unstressed distinction dominate, because the G2P's penultimate
# -stress default (see g2p/README) makes stress placement the single most
# likely place for the *label* to be wrong as well as the pupil.
CONFUSABLE_GROUPS = [
    {"a", "a1"}, {"e", "e1"}, {"i", "i1"}, {"o", "o1"}, {"u", "u1"},
    {"e", "i"}, {"e1", "i1"}, {"o", "u"}, {"o1", "u1"}, {"a", "e"}, {"a1", "e1"},
    {"p", "b"}, {"t", "d"}, {"k", "g"}, {"p", "t", "k"}, {"b", "d", "g"},
    {"m", "n", "ng"}, {"l", "r"}, {"s", "sh", "z"}, {"f", "p", "v"},
    {"h", "q"}, {"y", "i"}, {"w", "u"}, {"ch", "sh"}, {"j", "d"},
]


def confusable_alternatives(phoneme: str, inventory: set[str]) -> list[str]:
    options: set[str] = set()
    for group in CONFUSABLE_GROUPS:
        if phoneme in group:
            options |= group - {phoneme}
    return sorted(o for o in options if o in inventory)


def auc(correct: list[float], corrupted: list[float]) -> float:
    """Probability a correct phoneme outscores a corrupted one (Mann-Whitney)."""
    correct_arr, corrupted_arr = np.asarray(correct), np.asarray(corrupted)
    if correct_arr.size == 0 or corrupted_arr.size == 0:
        return float("nan")
    combined = np.concatenate([correct_arr, corrupted_arr])
    order = combined.argsort()
    ranks = np.empty(len(combined))
    ranks[order] = np.arange(1, len(combined) + 1)
    rank_sum = ranks[: correct_arr.size].sum()
    n_pos = correct_arr.size
    return float((rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * corrupted_arr.size))


class Corruptor:
    def __init__(self, mode: str, rate: float, seed: int):
        self.mode = mode
        self.rate = rate
        self.rng = np.random.default_rng(seed)
        self.inventory = phoneme_inventory()
        self.inventory_set = set(self.inventory)

    def __call__(self, sequence: list[str]) -> tuple[list[str], set[int]]:
        out, changed = list(sequence), set()
        for i, phoneme in enumerate(out):
            if self.rng.random() >= self.rate:
                continue
            if self.mode == "random":
                alternative = phoneme
                while alternative == phoneme:
                    alternative = self.inventory[self.rng.integers(len(self.inventory))]
            else:
                options = confusable_alternatives(phoneme, self.inventory_set)
                if not options:
                    continue
                alternative = options[self.rng.integers(len(options))]
            out[i] = alternative
            changed.add(i)
        return out, changed


def gop_values(model, log_probs, phonemes):
    ids = model.encode_phonemes(phonemes)
    spans = ctc_forced_align(log_probs, ids, blank=model.blank_id)
    return score_phonemes(log_probs, spans, ids, model.id_to_token, model.competitor_ids)


def split_scores(model, log_probs, sequence, corruptor):
    corrupted_seq, changed = corruptor(sequence)
    if not changed:
        return [], []
    scores = gop_values(model, log_probs, corrupted_seq)
    kept = [s.gop for i, s in enumerate(scores) if i not in changed]
    hit = [s.gop for i, s in enumerate(scores) if i in changed]
    return kept, hit


def report(label, correct, corrupted):
    value = auc(correct, corrupted)
    print(
        f"  {label:<30} AUC {value:.3f}   correct med {np.median(correct):>6.2f} | "
        f"corrupted med {np.median(corrupted):>6.2f}   (n={len(corrupted)})"
    )
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--audio", help="a real recording to evaluate")
    parser.add_argument("--passage", default="builtin:fil", help="passage for --audio")
    parser.add_argument(
        "--corpus-baseline",
        action="store_true",
        help="also measure on corpus val clips - the in-domain ceiling, and the "
        "reference any deployment number should be read against",
    )
    parser.add_argument("--split-dir", type=Path, default=REPO_ROOT / "training" / "processed" / "val")
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--rate", type=float, default=0.30, help="fraction of phonemes to corrupt")
    parser.add_argument("--repeats", type=int, default=5, help="corruption draws to average over")
    parser.add_argument("--seed", type=int, default=11)
    args = parser.parse_args()

    model = PhonemeAcousticModel(args.model_dir)

    if args.corpus_baseline:
        import pyarrow.parquet as pq

        shards = sorted(glob.glob(str(args.split_dir / "*.parquet")))
        rows = pq.read_table(shards[0]).to_pylist()
        print("\n=== in-domain ceiling: corpus val clips ===")
        groups = [
            ("short (1-2 words)", [r for r in rows if r["num_words"] <= 2][: args.limit * 3]),
            (f"multi-word (>=8)", [r for r in rows if r["num_words"] >= 8][: args.limit]),
        ]
        for label, selected in groups:
            for mode in ("random", "confusable"):
                corruptor = Corruptor(mode, args.rate, args.seed)
                correct, corrupted = [], []
                for row in selected:
                    try:
                        log_probs = model.log_probs(
                            load_wav_bytes(row["audio"]["bytes"]), window_seconds=None
                        )
                        kept, hit = split_scores(
                            model, log_probs, list(row["phoneme_sequence"]), corruptor
                        )
                    except (AlignmentError, KeyError, RuntimeError, ValueError):
                        continue
                    correct += kept
                    corrupted += hit
                if corrupted:
                    report(f"{label} / {mode}", correct, corrupted)

    if args.audio:
        from score_recording import resolve_passage

        passage = resolve_passage(argparse.Namespace(passage=args.passage))
        tokens = [t for t in text_to_phonemes(passage) if t["phonemes"]]
        sequence = [p for t in tokens for p in t["phonemes"]]

        waveform = load_audio(args.audio)
        log_probs = model.log_probs(waveform)
        print(f"\n=== deployment: {Path(args.audio).name} "
              f"({len(waveform) / 16000:.1f}s, {len(sequence)} phonemes) ===")
        for mode in ("random", "confusable"):
            correct, corrupted = [], []
            for repeat in range(args.repeats):
                corruptor = Corruptor(mode, args.rate, args.seed + repeat)
                kept, hit = split_scores(model, log_probs, sequence, corruptor)
                correct += kept
                corrupted += hit
            if corrupted:
                report(mode, correct, corrupted)

    if not args.audio and not args.corpus_baseline:
        parser.error("nothing to do: pass --audio and/or --corpus-baseline")

    print(
        "\nRead the `confusable` rows, not `random`. AUC 0.5 is a coin flip.\n"
        "A deployment number well below the in-domain ceiling means the gap is\n"
        "the recording conditions, not the GOP method."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

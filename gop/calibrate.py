"""Measures the GOP distribution on known-correct speech and writes thresholds.

Without this, the cutoffs in `basaquest_gop/config.py` are guesses about where
"correct" stops and "mispronounced" starts, and every flag the scorer produces
inherits that guess. This script replaces the guess with a measurement: run
GOP over speech that is believed correct, look at where the scores actually
fall, and set the thresholds so that only a chosen small fraction of
known-correct phonemes would be flagged.

Two things this leans on, both stated rather than buried:

- **It assumes the corpus is correctly pronounced.** It isn't labelled - the
  ROADMAP is explicit that no labelled mispronunciation data exists for this
  project. Real errors in the corpus sit in the low tail and pull the
  thresholds *down*, making the scorer more permissive than intended. That is
  the safer direction to be wrong in for a classroom tool (a missed flag
  costs less than falsely telling a Grade 1 pupil they said a word wrong),
  but it is a bias, not neutrality.

- **It calibrates on adults reading, for a tool used by children reading.**
  The ROADMAP flags the adult/child acoustic mismatch; on top of that, 93.7%
  of the corpus is single-word clips, so `--min-words` defaults to 3 to select
  the connected speech that resembles passage reading. Even so, this produces
  *adult* thresholds. Phase 5 has to check them against real pupils, and
  `--group-by` exists to make that check easy once child recordings exist.

    python calibrate.py --model-dir ../models/final-model-v2 --limit 300

The written calibration.json also carries `reference_median_gop`, which is not
a threshold: it is the value to pass to `score_recording.py
--normalize-median-to` if the child-speech offset correction in gop.py ever
turns out to be warranted.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

GOP_DIR = Path(__file__).resolve().parent
REPO_ROOT = GOP_DIR.parent
sys.path.insert(0, str(GOP_DIR))

from basaquest_gop import PhonemeAcousticModel, ctc_forced_align, score_phonemes
from basaquest_gop.audio import load_audio, load_wav_bytes
from basaquest_gop.ctc_align import AlignmentError
from basaquest_gop.g2p_bridge import text_to_phonemes

DEFAULT_SPLIT = REPO_ROOT / "training" / "processed" / "val"
DEFAULT_OUTPUT = GOP_DIR / "calibration.json"


def load_rows(split_dir: Path, limit: int, min_words: int, max_seconds: float):
    """Reads Phase 2 output. The *val* split is the right one to calibrate on:
    it is speaker-disjoint from training (Phase 2 split by speaker on purpose),
    so these GOP values reflect voices the model never fitted to - which is the
    situation every real pupil will be in."""
    import pyarrow.parquet as pq

    shards = sorted(split_dir.glob("*.parquet"))
    if not shards:
        raise FileNotFoundError(f"no parquet shards in {split_dir}")

    rows = []
    for shard in shards:
        table = pq.read_table(shard)
        for row in table.to_pylist():
            if row["num_words"] < min_words or row["duration"] > max_seconds:
                continue
            rows.append(row)
            if len(rows) >= limit:
                return rows
    return rows


def load_recordings(paths: list[str], passage_spec: str):
    """Turns real recordings into the same row shape `load_rows` produces, so
    the rest of calibration is identical whichever source is used.

    Only pass recordings of a passage read *correctly*: the thresholds are
    derived from where correct speech scores, so a mispronunciation in here
    drags the cutoffs down and quietly makes the scorer more permissive.
    """
    from score_recording import resolve_passage
    import argparse as _argparse

    passage = resolve_passage(_argparse.Namespace(passage=passage_spec))
    tokens = [t for t in text_to_phonemes(passage) if t["phonemes"]]
    word_phonemes = json.dumps([{"word": t["word"], "phonemes": t["phonemes"]} for t in tokens])
    sequence = [p for t in tokens for p in t["phonemes"]]

    rows = []
    for path in paths:
        rows.append(
            {
                "_path": Path(path),
                "phoneme_sequence": sequence,
                "word_phonemes": word_phonemes,
                "num_words": len(tokens),
            }
        )
    return rows


def percentile_report(name: str, values: np.ndarray) -> None:
    if values.size == 0:
        print(f"{name}: no data")
        return
    points = [1, 5, 10, 25, 50, 75, 95]
    cells = "  ".join(f"p{p}={np.percentile(values, p):>7.2f}" for p in points)
    print(f"{name:<24} n={values.size:<7} {cells}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--split-dir", type=Path, default=DEFAULT_SPLIT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=300, help="utterances to score")
    parser.add_argument(
        "--min-words",
        type=int,
        default=3,
        help="skip clips shorter than this many words - the corpus is 93.7%% "
        "single words, which do not resemble passage reading (default 3)",
    )
    parser.add_argument("--max-seconds", type=float, default=20.0)
    parser.add_argument(
        "--false-positive-rate",
        type=float,
        default=5.0,
        help="percent of known-correct phonemes the thresholds may flag (default 5)",
    )
    parser.add_argument(
        "--group-by",
        help="also report the distribution split by this metadata column "
        "(e.g. speaker_id, gender, speech_type) - use it to see whether a "
        "group the model handles worse would be systematically over-flagged",
    )
    parser.add_argument(
        "--audio",
        action="append",
        default=[],
        metavar="PATH",
        help="calibrate on real recordings of a passage read CORRECTLY, instead "
        "of the corpus. Repeatable. This is the better source when such "
        "recordings exist: the corpus is isolated adult words in clean "
        "conditions, while these are the actual task, the actual microphone "
        "and the actual reading style the thresholds have to work on.",
    )
    parser.add_argument(
        "--audio-passage",
        default="builtin:fil",
        help="passage the --audio recordings read (default: the app's Filipino passage)",
    )
    parser.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    args = parser.parse_args()

    print(f"loading model from {args.model_dir} ...")
    model = PhonemeAcousticModel(args.model_dir)

    if args.audio:
        rows = load_recordings(args.audio, args.audio_passage)
        source = f"{len(rows)} recording(s) of a correctly-read passage"
    else:
        rows = load_rows(args.split_dir, args.limit, args.min_words, args.max_seconds)
        source = f"{len(rows)} corpus utterances (>= {args.min_words} words) from {args.split_dir.name}"
    print(f"scoring {source}\n")

    phoneme_gops: list[float] = []
    word_means: list[float] = []
    word_mins: list[float] = []
    word_extents: list[float] = []
    grouped: dict[str, list[float]] = defaultdict(list)
    skipped = 0

    for index, row in enumerate(rows, 1):
        try:
            waveform = (
                load_audio(row["_path"]) if "_path" in row else load_wav_bytes(row["audio"]["bytes"])
            )
            target_ids = model.encode_phonemes(list(row["phoneme_sequence"]))
            log_probs = model.log_probs(waveform)
            spans = ctc_forced_align(log_probs, target_ids, blank=model.blank_id)
            scores = score_phonemes(
                log_probs, spans, target_ids, model.id_to_token, model.competitor_ids
            )
        except (AlignmentError, KeyError, RuntimeError, ValueError) as error:
            # A clip too short for its own phoneme count is the known case
            # here - the same mismatch that crashed Phase 3's ctc_loss.
            skipped += 1
            if skipped <= 3:
                print(f"  skipped row {index}: {type(error).__name__}: {error}")
            continue

        phoneme_gops.extend(s.gop for s in scores)
        if args.group_by:
            grouped[str(row.get(args.group_by))].extend(s.gop for s in scores)

        # Re-split the flat scores back into words so the word-level thresholds
        # are measured on the same unit the scorer actually thresholds.
        offset = 0
        for word in json.loads(row["word_phonemes"]):
            count = len(word["phonemes"])
            if count == 0:
                continue
            word_scores = scores[offset : offset + count]
            offset += count
            if not word_scores:
                continue
            gops = [s.gop for s in word_scores]
            word_means.append(float(np.mean(gops)))
            word_mins.append(float(np.min(gops)))
            extent = word_scores[-1].end_frame - word_scores[0].start_frame
            word_extents.append(extent / count)

        if index % 25 == 0:
            print(f"  {index}/{len(rows)} ...")

    if not phoneme_gops:
        print("\nNo utterances scored successfully - cannot calibrate.")
        return 1

    phoneme_gops_arr = np.array(phoneme_gops)
    word_means_arr = np.array(word_means)
    word_mins_arr = np.array(word_mins)
    word_extents_arr = np.array(word_extents)

    print(f"\nscored {len(rows) - skipped} utterances, skipped {skipped}\n")
    print("GOP distribution on speech assumed correct:")
    percentile_report("per-phoneme gop", phoneme_gops_arr)
    percentile_report("per-word mean gop", word_means_arr)
    percentile_report("per-word min gop", word_mins_arr)
    percentile_report("extent frames/phoneme", word_extents_arr)

    if args.group_by:
        print(f"\nper-phoneme gop by {args.group_by}:")
        for key in sorted(grouped, key=lambda k: float(np.median(grouped[k]))):
            percentile_report(f"  {key}", np.array(grouped[key]))

    rate = args.false_positive_rate

    # The scorer flags a word when EITHER the mean or the min cutoff trips, so
    # setting each at the `rate`-th percentile independently overshoots badly -
    # the two tails only partly overlap, and the combined rate came out near
    # double the target on the first real run. Search for the single percentile
    # `q` at which the OR of both rules flags `rate` percent of known-correct
    # words, which is the quantity actually being promised.
    def combined_rate(q: float) -> float:
        mean_cut = np.percentile(word_means_arr, q)
        min_cut = np.percentile(word_mins_arr, q)
        flagged = (word_means_arr < mean_cut) | (word_mins_arr < min_cut)
        return 100.0 * flagged.mean()

    low, high = 0.01, rate
    for _ in range(40):
        mid = (low + high) / 2
        if combined_rate(mid) > rate:
            high = mid
        else:
            low = mid
    q = (low + high) / 2
    print(
        f"\nusing the {q:.2f}th percentile for both word cutoffs -> combined "
        f"flag rate {combined_rate(q):.1f}% (target {rate}%)"
    )

    thresholds = {
        # Two cutoffs because they catch different shapes of error: a uniformly
        # weak word, versus one bad sound in an otherwise fine word. Both sit
        # at percentile `q`, chosen above so their OR hits the target rate.
        "mispronounced_mean_gop": float(np.percentile(word_means_arr, q)),
        "mispronounced_min_gop": float(np.percentile(word_mins_arr, q)),
        # Omission is a stronger claim than mispronunciation, so it uses a
        # stricter tail - a fifth of the flagging rate.
        "omission_gop": float(np.percentile(word_mins_arr, rate / 5)),
        "omission_max_extent_per_phoneme": float(np.percentile(word_extents_arr, rate / 5)),
        "confidence_scale": float(
            # Scale confidence to the spread of the data rather than a
            # hardcoded constant, so "far past the threshold" means far
            # relative to how variable correct speech actually is.
            max(np.percentile(word_means_arr, 75) - np.percentile(word_means_arr, 25), 0.5)
        ),
        "reference_median_gop": float(np.median(phoneme_gops_arr)),
        "provenance": (
            (
                f"calibrate.py on {len(rows) - skipped} real recording(s) of the "
                f"'{args.audio_passage}' passage read correctly "
                f"({', '.join(Path(p).name for p in args.audio)}), adult speaker"
                if args.audio
                else f"calibrate.py on {len(rows) - skipped} {args.split_dir.name} corpus "
                f"utterances (>= {args.min_words} words, adult 20-27 read speech)"
            )
            + f", false-positive rate {rate}%"
        ),
    }

    print("\nderived thresholds:")
    for key, value in thresholds.items():
        print(f"  {key:<34} {value if isinstance(value, str) else f'{value:.3f}'}")

    print(
        f"\nAt these cutoffs, ~{rate}% of correctly-read words would still be "
        f"flagged.\nThat floor is a property of the model, not a bug to tune away."
    )

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    args.output.write_text(json.dumps(thresholds, indent=2), encoding="utf-8")
    print(f"\nwrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

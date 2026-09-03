"""
Phase 2 of the "Filipino Local Mispronunciation Detector" project (see the
root ROADMAP.md): turns the raw downloaded Filipino Speech Corpus parquet
shards into filtered, phoneme-labeled train/val/test parquet shards ready
for Phase 3 (Colab fine-tuning).

Usage:
    python preprocess_corpus.py
    python preprocess_corpus.py --limit-shards 2   # quick smoke test

Run from anywhere; paths default to the standard locations of this repo
(../data/filipino-speech-corpus-backup -> ./processed) but can be
overridden. See README.md for what gets filtered out and why.
"""
import argparse
import hashlib
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "g2p"))
from filipino_g2p import text_to_phonemes  # noqa: E402

CORPUS_COLUMNS = [
    "audio", "sentence", "duration", "num_words", "speaker_id",
    "gender", "age_group", "speech_type", "source_file",
]

DEFAULT_CORPUS_DIR = Path(__file__).resolve().parent.parent / "data" / "filipino-speech-corpus-backup"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "processed"

# --- Junk-sentence detection -------------------------------------------
#
# Found by sampling the actual corpus, not guessed: a "nonfsc" sentinel
# marks rows the corpus's own creators flagged as not real corpus content
# (~2% of rows); bracket-only sentences ("[]", "[cough]", "[noise]",
# "[swallow]") mark non-speech events; "NOISE" is used the same way outside
# brackets in a few rows; some rows are pure punctuation ("...", ".").
#
# Curly-brace annotations ("{guspo} gusto ko...") mark a spontaneous-speech
# disfluency/self-correction - real, interesting signal (the roadmap notes
# there's no labeled mispronunciation data for calibration, and this is
# exactly that), but the exact annotation convention isn't documented
# anywhere the corpus ships, so rows containing it are excluded here rather
# than guessed at. Worth a dedicated follow-up, not silently mishandled.

_BRACKET_ONLY_RE = re.compile(r"^\s*\[[^\[\]]*\]\s*$")
_HAS_CURLY_ANNOTATION_RE = re.compile(r"[{}]")
_HAS_ANY_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)
_JUNK_SENTINELS = {"nonfsc", "noise"}


def is_junk_sentence(sentence) -> bool:
    if sentence is None:
        return True
    s = str(sentence).strip()
    if not s:
        return True
    if s.lower() in _JUNK_SENTINELS:
        return True
    if _BRACKET_ONLY_RE.match(s):
        return True
    if _HAS_CURLY_ANNOTATION_RE.search(s):
        return True
    if not _HAS_ANY_LETTER_RE.search(s):
        return True  # pure punctuation/digits, e.g. "...", "123"
    return False


def rejection_reason(row: dict) -> str | None:
    """None if the row should be kept; otherwise a short machine-readable
    reason, used for the summary report."""
    if row.get("speech_type") == "machine":
        return "machine_speech"
    duration = row.get("duration")
    if duration is None or duration <= 0:
        return "nonpositive_duration"
    if is_junk_sentence(row.get("sentence")):
        return "junk_sentence"
    return None


# --- Phoneme target computation -----------------------------------------

def compute_phoneme_fields(sentence: str) -> dict:
    words = text_to_phonemes(sentence)
    flat = [p for w in words for p in w["phonemes"]]
    return {"word_phonemes": words, "phoneme_sequence": flat, "phoneme_count": len(flat)}


# --- Train/val split ------------------------------------------------------
#
# Speaker-disjoint, not a random per-utterance split: BasaQuest needs to
# generalize to pupils it's never heard, so validation should measure
# accuracy on unseen speakers, not just unseen utterances from speakers the
# model already saw in training. Deterministic via hashing speaker_id, so
# each shard can be processed independently without a coordinating first
# pass over the whole corpus.

def assign_split(speaker_id, val_fraction: float) -> str:
    digest = hashlib.md5(str(speaker_id).encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) % 10000
    return "val" if bucket < val_fraction * 10000 else "train"


# --- Shard processing -----------------------------------------------------

def new_stats() -> dict:
    return {"total": 0, "rejected": defaultdict(int), "kept": defaultdict(int)}


def _process_rows(df: pd.DataFrame, stats: dict) -> list[dict]:
    kept = []
    for row in df.to_dict("records"):
        stats["total"] += 1
        reason = rejection_reason(row)
        fields = None
        if reason is None:
            fields = compute_phoneme_fields(row["sentence"])
            if fields["phoneme_count"] == 0:
                reason = "no_phonemes_produced"
        if reason:
            stats["rejected"][reason] += 1
            continue
        record = dict(row)
        record["word_phonemes"] = json.dumps(fields["word_phonemes"], ensure_ascii=False)
        record["phoneme_sequence"] = fields["phoneme_sequence"]
        record["phoneme_count"] = fields["phoneme_count"]
        kept.append(record)
    return kept


def process_train_shard(path, val_fraction: float, stats: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = pd.read_parquet(path, columns=CORPUS_COLUMNS)
    records = _process_rows(df, stats)
    train_records, val_records = [], []
    for r in records:
        split = assign_split(r["speaker_id"], val_fraction)
        stats["kept"][split] += 1
        (val_records if split == "val" else train_records).append(r)
    return pd.DataFrame(train_records), pd.DataFrame(val_records)


def process_test_shard(path, stats: dict) -> pd.DataFrame:
    df = pd.read_parquet(path, columns=CORPUS_COLUMNS)
    records = _process_rows(df, stats)
    stats["kept"]["test"] += len(records)
    return pd.DataFrame(records)


def _write_chunked(df: pd.DataFrame, out_dir: Path, prefix: str, chunk_rows: int) -> None:
    if df.empty:
        return
    n_chunks = max(1, math.ceil(len(df) / chunk_rows))
    for i in range(n_chunks):
        chunk = df.iloc[i * chunk_rows: (i + 1) * chunk_rows]
        chunk.to_parquet(out_dir / f"{prefix}-{i:05d}-of-{n_chunks:05d}.parquet", index=False)


def print_report(stats: dict) -> None:
    total = stats["total"]
    print()
    print("=== Phase 2 preprocessing report ===")
    print(f"total rows read: {total}")
    print("rejected:")
    for reason, count in sorted(stats["rejected"].items(), key=lambda kv: -kv[1]):
        pct = 100 * count / total if total else 0
        print(f"  {reason}: {count} ({pct:.1f}%)")
    print("kept:")
    for split, count in stats["kept"].items():
        pct = 100 * count / total if total else 0
        print(f"  {split}: {count} ({pct:.1f}%)")


# --- CLI --------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", default=str(DEFAULT_CORPUS_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument(
        "--val-fraction", type=float, default=0.10,
        help=(
            "target fraction of SPEAKERS (not rows) held out for validation. "
            "Default chosen empirically against this corpus's actual speaker "
            "count (124 total): with a pool this small, the hash-based split "
            "has high variance at low fractions (5%% landed only 3 "
            "speakers in one run); 10%% reliably lands ~10, still a small "
            "but workable held-out set. See README.md."
        ),
    )
    parser.add_argument(
        "--limit-shards", type=int, default=None,
        help="process only the first N shards of each split (train/test) - for a quick smoke test",
    )
    args = parser.parse_args()

    corpus_dir = Path(args.corpus_dir)
    output_dir = Path(args.output_dir)
    for sub in ("train", "val", "test"):
        (output_dir / sub).mkdir(parents=True, exist_ok=True)

    train_shards = sorted((corpus_dir / "data").glob("train-*.parquet"))
    test_shards = sorted((corpus_dir / "data").glob("test-*.parquet"))
    if args.limit_shards:
        train_shards = train_shards[: args.limit_shards]
        test_shards = test_shards[: args.limit_shards]

    stats = new_stats()
    val_accumulator = []

    print(f"Processing {len(train_shards)} train shard(s)...")
    for shard_path in train_shards:
        train_df, val_df = process_train_shard(shard_path, args.val_fraction, stats)
        if not train_df.empty:
            train_df.to_parquet(output_dir / "train" / shard_path.name, index=False)
        if not val_df.empty:
            val_accumulator.append(val_df)
        print(f"  {shard_path.name}: {len(train_df)} train, {len(val_df)} val")

    if val_accumulator:
        val_df_all = pd.concat(val_accumulator, ignore_index=True)
        _write_chunked(val_df_all, output_dir / "val", "val", chunk_rows=20000)

    print(f"Processing {len(test_shards)} test shard(s)...")
    for shard_path in test_shards:
        test_df = process_test_shard(shard_path, stats)
        if not test_df.empty:
            test_df.to_parquet(output_dir / "test" / shard_path.name, index=False)
        print(f"  {shard_path.name}: {len(test_df)} test")

    print_report(stats)


if __name__ == "__main__":
    main()

"""CLI: score one recording against one passage and print the result.

This is the Phase 4 deliverable's front door, and the tool Phase 5's
head-to-head comparison drives. It deliberately prints a human-readable
table alongside the JSON, because the Phase 5 question - "are these flags
actually right?" - is answered by a person listening to the audio while
reading the flags, not by a metric.

    python score_recording.py \
        --audio ../server/uploads/<recording>.wav \
        --passage builtin:fil \
        --model-dir ../models/final-model-v2
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from basaquest_gop import PhonemeAcousticModel, load_thresholds, score_passage
from basaquest_gop.acoustic import DEFAULT_OVERLAP_SECONDS, DEFAULT_WINDOW_SECONDS

REPO_ROOT = Path(__file__).resolve().parents[1]
PASSAGE_MODULE = REPO_ROOT / "client" / "src" / "passage.js"

STATUS_MARK = {
    "correct": "  ",
    "mispronounced": "!!",
    "omitted": "--",
    "inserted": "++",
}


def read_builtin_passage(language: str) -> str:
    """Pulls a passage out of the app's own passage.js by executing it in
    Node, rather than re-typing it here or parsing JS with a regex. The
    passage the pupil actually read is the one on screen; a second copy in
    this repo would eventually drift from it and silently invalidate every
    comparison run against it."""
    if not PASSAGE_MODULE.exists():
        raise FileNotFoundError(f"passage module not found at {PASSAGE_MODULE}")
    # as_uri(), not a plain path: Node's ESM loader rejects a Windows absolute
    # path ("protocol 'd:'") and requires a file:// URL.
    script = (
        f"import {{ PASSAGES }} from {json.dumps(PASSAGE_MODULE.as_uri())};"
        f"process.stdout.write(PASSAGES[{json.dumps(language)}].text)"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"could not read the built-in passage: {result.stderr.strip()}")
    return result.stdout


def resolve_passage(args) -> str:
    if args.passage.startswith("builtin:"):
        return read_builtin_passage(args.passage.split(":", 1)[1])
    path = Path(args.passage)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return args.passage


def print_report(result: dict, show_all: bool) -> None:
    words = result["words"]
    flagged = [w for w in words if w["status"] != "correct"]
    scorable = [w for w in words if not w.get("unscorable")]

    print()
    print(f"engine            {result['engine']}")
    print(f"duration          {result['durationSeconds']}s")
    print(f"words             {len(scorable)} scorable, {len(flagged)} flagged")

    calibration = result["calibration"]
    if not calibration["calibrated"]:
        # Loud on purpose. Reading these flags as meaningful before the
        # thresholds have been measured is the single easiest way to draw a
        # wrong conclusion from this tool.
        print()
        print("  !! THRESHOLDS ARE NOT CALIBRATED")
        print(f"     {calibration['provenance']}")
        print("     Which words get flagged is therefore arbitrary. Run")
        print("     calibrate.py before drawing conclusions from these flags.")

    shown = words if show_all else flagged
    if not shown:
        print("\nNothing flagged.")
        return

    print()
    print(f"{'#':>4}  {'':2} {'word':<18} {'status':<14} {'conf':>5} {'mean':>7} {'min':>7}")
    print("-" * 70)
    for word in shown:
        if word.get("unscorable"):
            continue
        print(
            f"{word['index']:>4}  {STATUS_MARK.get(word['status'], '??')} "
            f"{word['word']:<18} {word['status']:<14} "
            f"{word['confidence']:>5.2f} {word['meanGop']:>7.2f} {word['minGop']:>7.2f}"
        )
        if word["status"] != "correct":
            worst = min(word["phonemes"], key=lambda p: p["gop"])
            when = f"{worst['startTime']:.2f}s"
            print(
                f"          expected /{worst['phoneme']}/ but heard /{worst['heard']}/ "
                f"at {when} (gop {worst['gop']:.2f})"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--audio", required=True, help="recording to score")
    parser.add_argument(
        "--passage",
        required=True,
        help="passage text, a path to a .txt file, or 'builtin:fil' to read "
        "the app's own Filipino passage from client/src/passage.js",
    )
    parser.add_argument(
        "--model-dir",
        required=True,
        help="local copy of the Phase 3 model (Drive: 'My Drive/BasaQuest/final-model-v2')",
    )
    parser.add_argument("--json", help="also write the full result to this path")
    parser.add_argument("--show-all", action="store_true", help="list every word, not just flags")
    parser.add_argument(
        "--window-seconds",
        type=float,
        default=DEFAULT_WINDOW_SECONDS,
        help=f"inference window length (default {DEFAULT_WINDOW_SECONDS})",
    )
    parser.add_argument("--overlap-seconds", type=float, default=DEFAULT_OVERLAP_SECONDS)
    parser.add_argument(
        "--no-window",
        action="store_true",
        help="process the whole recording in one pass (more memory; see acoustic.py)",
    )
    parser.add_argument(
        "--normalize-median-to",
        type=float,
        help="recentre this utterance's GOP median to this value - the "
        "speaker-offset correction for child speech. Off unless given, and it "
        "should stay off until Phase 5 shows the offset is real.",
    )
    parser.add_argument("--calibration", help="path to a calibration.json")
    args = parser.parse_args()

    passage = resolve_passage(args)
    thresholds = load_thresholds(args.calibration)

    started = time.perf_counter()
    model = PhonemeAcousticModel(args.model_dir)
    loaded = time.perf_counter()

    result = score_passage(
        passage,
        args.audio,
        model,
        thresholds=thresholds,
        window_seconds=None if args.no_window else args.window_seconds,
        overlap_seconds=args.overlap_seconds,
        normalize_median_to=args.normalize_median_to,
    )
    finished = time.perf_counter()

    print_report(result, args.show_all)
    print()
    print(
        f"model load {loaded - started:.1f}s | scoring {finished - loaded:.1f}s "
        f"({(finished - loaded) / max(result['durationSeconds'], 1):.2f}x realtime)"
    )

    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

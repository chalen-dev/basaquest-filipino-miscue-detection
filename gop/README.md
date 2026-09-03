# Phase 4 — GOP (Goodness of Pronunciation) scoring

Turns the Phase 3 phoneme recognizer into an actual mispronunciation
detector. Phase 3 could tell you what phonemes it heard; it could not tell
you whether they were the *right* ones. This does.

See the root [ROADMAP.md](../ROADMAP.md) for where this sits in the plan.

## How it works

1. **Expected phonemes** — Phase 1's G2P (`g2p/filipino_g2p`) converts the
   passage text to a phoneme sequence, per word.
2. **Forced alignment** — the expected sequence is aligned to the pupil's
   audio with a CTC Viterbi alignment, giving each expected phoneme the frame
   span where it should have been produced.
3. **Scoring** — for each expected phoneme, compare how likely *it* was over
   those frames against the single most likely competing phoneme:

   ```
   LPP(p) = mean over p's frames of  log P(p | frame)
   GOP(p) = LPP(p) − max over q ≠ p of LPP(q)
   ```

   Positive means the expected phoneme won. Negative means something else fit
   the audio better — a mispronunciation.
4. **Aggregate and threshold** — per-phoneme GOPs are combined per word and
   compared against thresholds to produce `correct` / `mispronounced` /
   `omitted`.
5. **Emit** — the same `ScoreResult` shape as every other scorer
   (`server/src/scorers/scorerInterface.js`).

### Why this beats transcript-diffing, structurally

The `whisper` scorer transcribes and diffs against the passage. It cannot
distinguish "Whisper mis-transcribed a correctly-read word" from "the pupil
mispronounced it" — and worse, Whisper's language model actively *repairs*
mispronounced words back into the expected ones, erasing the very signal
being looked for.

GOP never consults a language model. It asks the acoustic model directly
whether the sound produced matches the sound expected. That is the right
question, and it is why the ROADMAP treats "beat whisper on Filipino" as a
low bar rather than a moonshot.

## Setup

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv/Scripts/python.exe -m pip install -r gop/requirements.txt
```

Then download the Phase 3 model from Google Drive
(`My Drive/BasaQuest/final-model-v2`, ~1.2GB) to `models/final-model-v2/`.
`models/` is gitignored.

## Usage

Score one recording:

```bash
python score_recording.py --audio ../server/uploads/<file>.wav --passage builtin:fil --model-dir ../models/final-model-v2
```

`--passage builtin:fil` reads the app's own passage out of
`client/src/passage.js` by executing it in Node, so it can never drift from
what the pupil actually saw on screen. `--passage` also accepts a `.txt` path
or literal text.

Calibrate the thresholds (**do this before trusting any flag** — see below):

```bash
python calibrate.py --model-dir ../models/final-model-v2 --limit 300 --dry-run
```

Drop `--dry-run` to write `calibration.json`, which the scorer picks up
automatically.

Run the tests — no model or GPU needed:

```bash
python -m unittest discover -s tests -t .
```

## Thresholds are a measurement, not a constant

Where the cutoff between "correct" and "mispronounced" sits determines every
flag this scorer produces. Until `calibrate.py` has run, the values in
`basaquest_gop/config.py` are *guesses* — and both the CLI output and the
`calibration` block of every JSON result say so, loudly and by default.

`calibrate.py` replaces the guess by running GOP over held-out speech assumed
to be correct and setting the cutoffs so only a chosen small fraction (5% by
default) of known-correct words would be flagged. Two honest caveats, both
also stated in the script itself:

- The corpus has **no mispronunciation labels** — real errors in it sit in the
  low tail and pull thresholds *down*, making the scorer more permissive than
  intended. For a Grade 1-6 classroom tool that is the safer direction to err,
  but it is a bias, not neutrality.
- It calibrates on **adults**. See the mismatch section below.

## What this scorer cannot do

- **It cannot report `inserted` words.** Forced alignment asks "where does
  each expected phoneme go," and always answers for all of them. There is no
  state for "the pupil said something extra." The whisper scorer gets
  insertions for free because it does the opposite (transcribe, then diff) and
  pays for it in false mispronunciations.
- **It assumes the pupil read the whole passage, in order.** Skip a line,
  repeat a sentence, or read the wrong text, and alignment will still
  distribute every expected phoneme across the audio — producing confident
  nonsense rather than an error. This is a second, independent reason to build
  the ROADMAP's Backlog #2 content pre-filter, which would catch gross
  deviation before GOP ever runs.
- **`omitted` is inferred, not observed.** It is a heuristic: very low scores
  *and* the word's phonemes crammed into implausibly little audio.

## Two domain mismatches to keep in view

Both are properties of the training data, not bugs in this code, and both
were confirmed by inspecting the Phase 2 output directly:

1. **Adult model, child users.** The corpus is speakers aged 20-27; BasaQuest's
   users are Grade 1-6 pupils. Shorter vocal tracts put formants higher, so
   GOP may be depressed across the board on child audio and flag correctly
   -spoken words. `median_shift` in `gop.py` (exposed as
   `--normalize-median-to`) is a targeted correction for exactly that — it
   cancels a uniform per-speaker offset while preserving within-utterance
   contrast. **It is off by default and should stay off** until Phase 5
   measures whether the offset is actually uniform. It has a real cost: a
   pupil who mispronounces most of a passage gets recentred toward "normal for
   them."

2. **Isolated words, connected reading.** 93.7% of the Phase 2 training rows
   are single-word clips (median 0.61s), and Phase 3 capped duration at 6.0s —
   which kept 99.8% of rows. So the model has effectively never seen
   continuous read speech, while this scorer's input is a 40-60s passage. This
   is why `calibrate.py` defaults to `--min-words 3`: calibrating on 0.6s
   isolated words would set thresholds far too strict for passage reading.

## What has and hasn't been verified

Verified:

- The aligner produces the **optimal** alignment, checked against exhaustive
  search over every valid CTC alignment for small cases, with both distinct
  and repeated adjacent phonemes (`test_ctc_align.py`).
- Windowed inference produces **exactly** the same frame count as a single
  pass, with per-frame log-probs agreeing to <0.05 (`test_pipeline_smoke.py`,
  and confirmed on the real 46.7s recording in `server/uploads/`).
- The full pipeline runs end to end on a real passage-length input and emits
  JSON-serializable output matching the scorer interface.
- 51 tests pass without the real model or a GPU.

Not verified, and not verifiable without more real recordings:

- **Whether the flags are correct on real pupils.** Whether this beats
  `whisperScorer.js` is Phase 5, decided by a person listening.
- The 20s window default was chosen for the memory bound, not tuned against
  accuracy.
- No latency or memory measurement on real target hardware yet.

## Measured results (2026-07-22, real Phase 3 model)

**Do not evaluate this scorer with PER.** PER measures free decoding; GOP
never free-decodes — forced alignment constrains the output to exactly the
expected phonemes, so the edge hallucination that inflates PER cannot occur.
Measuring both on the same recording, PER read 0.74 while the scorer was in
fact discriminating usefully. Use `evaluate_discrimination.py`.

That tool corrupts a fraction of the expected phonemes and asks whether GOP
scores genuinely-spoken phonemes above substituted ones (AUC; 0.5 = coin
flip). `confusable` substitutions — /i/ for /e/, /b/ for /p/, stressed vs
unstressed — are the honest number; `random` is an upper bound.

| condition | random | confusable |
|---|---|---|
| corpus val, 1-2 words | 0.995 | 0.999 |
| corpus val, ≥8 words | 0.967 | 0.942 |
| **real 46.7s passage recording** | **0.764** | **0.717** |

- **The method works.** 0.94-0.99 in-domain says the alignment, the GOP
  measure and the competitor set are all correct.
- **There is a real deployment gap**, and it is *not* caused by connected
  speech — corpus multi-word clips reach 0.942. The remaining suspects are
  recording channel (browser mic with AGC and noise suppression, versus clean
  corpus audio), speaker, and reading style.
- Raw input length is **not** the cause either: padding a corpus clip with
  silence out to 60s barely moved its score.
- **Per-word scoring via Whisper timestamps was tested and rejected**: AUC
  0.776 versus 0.761 for whole-recording alignment, which does not justify the
  complexity or the added dependency.

### Update: the 0.717 was one defective recording

Three further recordings of the same passage (`test_recordings/`, audio in
`server/uploads/`) settled it:

| recording | confusable AUC |
|---|---|
| corpus in-domain ceiling | 0.942 |
| recording1 — browser mic, read correctly | **0.935** |
| recording2 — phone mic, read correctly | **0.925** |
| the original `7de69795-*.wav` | 0.717 |

The old file had a DC offset of +0.018 and peaked at 0.987 (near clipping);
the new ones sit at ~0 DC and peak 0.72/0.21. **There is no deployment gap** —
the scorer performs at essentially its in-domain ceiling on real recordings,
and browser versus phone makes no difference, so the channel hypothesis is
dead. This is what one bad sample costs: several hours chasing a gap that did
not exist.

## Detection on real, deliberately-mispronounced speech

`recording3.weba` reads the passage with five known errors
(`test_recordings/deliberate_errors.json`). Paired against the same speaker
reading it correctly:

| word | error | change in score |
|---|---|---|
| mangangalakal | l → r | **−7.75**, reported as `/l/ → /r/` exactly |
| ipinagtanggol | o → u | **−4.13** |
| malawak | a → e | −1.19 (weak) |
| nagngangalang | dropped /g/ | +1.84 **missed** |
| naaalala | dropped syllable | +0.13 **missed** |

Mean change: −2.22 for the five wrong words versus +0.33 for the 71 unchanged
ones. The signal is real and correctly localised.

**Substitutions are detected; deletions are not.** A dropped sound gets
absorbed by forced alignment into a neighbouring phoneme that still scores
acceptably. This is a known weakness of GOP and the obvious next improvement —
`extentPerPhoneme` is already computed and is the natural place to start.

## Versus whisperScorer.js

| | Whisper | GOP |
|---|---|---|
| false flags on a **correctly read** passage | **17 of 76** | **9 of 76** |
| of 5 deliberate errors, how many changed status vs the correct reading | **1 of 5** | **3 of 5** |

Whisper flagged four of the five target words in *both* recordings — it flags
the same hard words whether or not they were mispronounced, so its flags carry
little information about pronunciation. GOP also reports what it heard
instead, which Whisper structurally cannot.

## A tested idea that did not work

Correcting for per-phoneme bias. On correctly-read speech, per-sound median
scores span −3.1 (/e/, /v/, /ny/) to +6.8 (/s/, /k/), so words appeared to be
penalised for which sounds they contain. Subtracting each phoneme's corpus
baseline made separation slightly **worse** (0.806 vs 0.859), so it is not
implemented. The apparent bias is partly real signal.

## Threshold calibration

`calibration.json` is derived from `recording2.m4a` only, with `recording1`
held out. Sweeping strictness against the labelled errors:

| percentile | false alarms (correct read) | deliberate errors flagged |
|---|---|---|
| p1 | 4 of 76 | 1 |
| **p2-p3** | **6-10 of 76** | **3** |
| p8 | 12 of 76 | 3 |
| p18 | 22 of 76 | 3 |
| p25 | 27 of 76 | 3 |

Past p3, false alarms climb steadily while detection stays flat, so there is
nothing to buy by loosening. The shipped setting is `--false-positive-rate 6`.

**Two honest caveats.** The target rate is measured on the calibration
recording; on held-out audio the actual flag rate came out roughly double it,
so calibration does not fully transfer even between two recordings of the same
speaker. And all of this is **one adult speaker reading one passage** — treat
the numbers as provisional and recalibrate as real recordings accumulate.

## Module layout

- `basaquest_gop/ctc_align.py` — CTC Viterbi forced alignment. Vendored rather
  than imported from torchaudio, whose `forced_align` is deprecated with
  removal announced for 2.9 (pytorch/audio#3902).
- `basaquest_gop/acoustic.py` — model loading, windowed frame posteriors.
- `basaquest_gop/gop.py` — the GOP measure and the child-speech median shift.
- `basaquest_gop/scorer.py` — orchestration; emits the `ScoreResult` shape.
- `basaquest_gop/config.py` — thresholds and their provenance.
- `basaquest_gop/audio.py` — ffmpeg-based decode to 16kHz mono.
- `basaquest_gop/g2p_bridge.py` — access to Phase 1's G2P and phoneme inventory.
- `score_recording.py` — CLI for a single recording.
- `calibrate.py` — measures the GOP distribution, writes `calibration.json`.

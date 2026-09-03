# Corpus preprocessing

Phase 2 of the "Filipino Local Mispronunciation Detector" project (see the
root [ROADMAP.md](../ROADMAP.md)). Turns the raw downloaded Filipino Speech
Corpus (`data/filipino-speech-corpus-backup/`) into filtered,
phoneme-labeled train/val/test parquet shards, ready to upload to Google
Drive for Phase 3 (Colab fine-tuning).

Runs locally — this is CPU-bound data wrangling, not training, so it
doesn't need Colab's GPU. On the actual corpus (305,246 rows, 155 shards)
it takes well under a minute on an ordinary laptop.

## Phase 3 (Colab fine-tuning) — ✅ DONE 2026-07-22

`colab_finetune_phoneme_model.ipynb` — upload to Colab, along with this
project's `g2p/` folder and this script's `processed/` output to Google
Drive. Full instructions and a status block are in the notebook's first cell.
Fine-tunes `facebook/wav2vec2-xls-r-300m` via CTC over Phase 1's phoneme
inventory, with checkpoint/resume to Drive built in.

**Result: full-val PER 0.2968** (complete 8,831-row validation set). The
trained model lives in Google Drive at `My Drive/BasaQuest/final-model-v2`
and is what Phase 4 (GOP scoring) loads. Training has converged at this
configuration — more epochs won't help; see the notebook's status block and
the root `ROADMAP.md` for the three levers that would.

Two traps worth knowing before touching that notebook again:

- **Always re-run the Config cell first** when continuing training. It
  regenerates the timestamped `SESSION_DIR`; skipping it reuses the previous
  session folder and, because the step counter restarts at 0, resurrects the
  checkpoint-rotation bug that silently deletes new progress.
- **Early stopping must key on `eval_loss`, not `per`.** PER is computed on a
  2k-row subset and is too noisy to steer a stopping rule.

`colab_claude_code_setup.sh` — installs Claude Code inside a Colab VM
terminal, for iterating on Phase 3+ code from inside Colab itself instead
of the write-locally/run-in-Colab manual bridge. Needs a real interactive
terminal to run in (Colab Pro's built-in Terminal, `colab-xterm`, or SSH) —
a plain notebook code cell won't work, since Claude Code's REPL needs a
TTY. Not an official Anthropic/Google integration, just standard tools
wired together.

## Usage

```bash
cd training
pip install -r requirements.txt
python preprocess_corpus.py                # full corpus -> ./processed/
python preprocess_corpus.py --limit-shards 2   # quick smoke test on 2 shards
```

Output layout:

```
processed/
  train/   one output parquet per input train shard (same filename)
  val/     held-out speakers, chunked into ~20k-row files
  test/    one output parquet per input test shard (same filename)
```

## What gets filtered out, and why

Beyond the roadmap's explicit instruction to drop `speech_type == "machine"`
(synthetic/TTS-generated speech — training a mispronunciation detector on
fake speech would teach it the wrong thing), sampling the actual corpus
turned up more junk that isn't machine speech but also isn't real content:

- **`"nonfsc"`** — a literal sentinel the corpus's own creators used to mark
  a row as not real corpus content. ~2% of rows. Not documented anywhere in
  the dataset card; found by sampling.
- **Bracket-only non-speech event tags** — `"[]"`, `"[cough]"`, `"[noise]"`,
  `"[swallow]"`. A `sentence` that's *entirely* a bracketed tag like this
  gets dropped.
- **`"NOISE"`** (bare, no brackets) — used the same way in a few rows.
- **Pure punctuation** — `"."`, `"..."`, empty/whitespace-only strings.

**Not yet handled — a real, interesting gap, not an oversight:** some
spontaneous-speech rows carry a curly-brace annotation embedded in otherwise
real content, e.g. `"{guspo} gusto ko pa rin yung pilipinas..."` — this
looks like a disfluency/self-correction marker (the speaker started to say
something, self-corrected to "gusto"). That's potentially exactly the kind
of labeled mispronunciation signal the roadmap notes this project doesn't
otherwise have for calibration. But the annotation convention isn't
documented anywhere the corpus ships, and guessing at it risks silently
corrupting phoneme targets. Rows containing `{`/`}` are excluded for now
(~0.1% of rows) rather than half-interpreted. Worth a dedicated follow-up:
sample these rows, work out the convention by inspection, and decide if
they're usable.

Full measured breakdown from the actual corpus (305,246 rows total):

| | count | % of total |
|---|---|---|
| rejected: machine speech | 174,926 | 57.3% |
| rejected: junk sentence (above) | 2,685 | 0.9% |
| kept: train | 105,882 | 34.7% |
| kept: val | 8,926 | 2.9% |
| kept: test | 12,827 | 4.2% |

A final safety net (`no_phonemes_produced`, not hit on the real corpus but
exercised in tests) drops any row where the G2P produces zero phonemes for
every word — catches anything a name-based junk filter didn't anticipate.

## Train/val split is speaker-disjoint, not random

BasaQuest needs to generalize to pupils it's never heard read before, so
validation should measure accuracy on *unseen speakers*, not just unseen
utterances from speakers already seen in training. The split assigns whole
speakers to train or val (deterministically, via hashing `speaker_id`), so
no speaker appears in both — verified directly (`training/tests` +
a manual check against the real output: zero speaker overlap).

The corpus has only **124 total speakers**, which matters for picking a
val fraction: `--val-fraction` targets a fraction of *speakers*, not rows,
and with a pool this small the hash-based split has real variance at low
fractions — an earlier run at 5% landed only 3 speakers in val by chance.
The default is `0.10`, empirically chosen against this corpus to reliably
land ~10 speakers (the actual run above got 9). This is a small held-out
set, adequate for monitoring during Phase 3 fine-tuning (loss curves, early
stopping) — it is *not* a substitute for Phase 5's real evaluation
(human judgment on real recordings), which is the actual test of whether
this whole approach worked.

## Output schema

Same columns as the source corpus (see the corpus's own `README.md` in
`data/filipino-speech-corpus-backup/`), plus:

| Field | Type | Description |
|---|---|---|
| `word_phonemes` | `str` (JSON) | Per-word G2P output: `[{"word": ..., "phonemes": [...]}, ...]` — JSON-encoded because parquet doesn't cleanly round-trip a list-of-structs-of-lists through pandas; `json.loads()` it back. |
| `phoneme_sequence` | `list<str>` | Flattened phonemes across the whole sentence, in order — the direct CTC training target for Phase 3. |
| `phoneme_count` | `int` | `len(phoneme_sequence)`, kept for quick filtering (e.g. by sequence length) without re-parsing JSON. |

## Tests

```bash
cd training
python -m unittest discover -s tests -t . -v
```

24 tests against synthetic fixtures (no dependency on the real corpus being
downloaded) covering the junk-sentence rules, rejection logic, phoneme
field computation, split determinism/distribution, and shard I/O.

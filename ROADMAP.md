# Technical Roadmap

Living list of what's built, what's known-imperfect, and what's next for the
reading proficiency pipeline. README.md documents what exists and how to run
it; this is about what's missing and why, so context doesn't get lost between
sessions.

## Implemented

- Core loop: record → score → teacher review (with per-word audio seek) →
  validate. See README's "How it works".
- Three scorers behind one interface: `mock` (default), `whisper` (real,
  local, see README's Whisper section for the model choice history), `azure`
  (stub only — see Backlog).
- Whisper path: one shared multilingual `Xenova/whisper-small` model for
  English + Filipino, `q8` quantized, `chunk_length_s: 30` / `stride_length_s:
  5` for audio longer than Whisper's native 30s window.
- Word-level timestamps, with bounded "play this word's chunk" seek in the
  teacher review screen (start/end padding, auto-stop).
- Microphone noise suppression (`noiseSuppression`/`echoCancellation`/
  `autoGainControl` on `getUserMedia` — the free browser-native tier, not a
  neural denoiser).
- Audio quality pre-filter (`server/src/audioQualityCheck.js`): rejects
  recordings under 5s or effectively silent, before any scorer (paid or
  local) runs on them. Client mirrors the duration check for instant feedback.

## Intended pipeline: online vs. offline

The two paths share the same shape but differ in who does the real scoring.
✅ = built today, 🔲 = not built yet.

**Online (Azure available):**
1. 🔲 Pupil chooses language — ✅ built, but only as a passage-language toggle;
   no separate pre-assessment step (see next line).
2. 🔲 Baseline pre-assessment passage, distinct from the main proficiency
   test — manuscript calls for both; this prototype only has the one reading
   screen today, no separate baseline step.
3. ✅ Recording submitted → cheap technical filter (`audioQualityCheck.js`:
   duration + silence via ffmpeg, no ASR involved).
4. 🔲 **Local Whisper as a content pre-filter**, before the paid Azure call —
   a second, smarter filter tier that the technical one can't cover: does the
   transcript roughly match the expected passage/language at all, or did the
   pupil read something else entirely, speak the wrong language, or record
   nonsense? Catching that locally means a wasted Azure call (however cheap
   per-call) never happens for input that was never going to score
   meaningfully anyway. Not built — no such content-level check exists yet;
   today's filter is duration/silence only.
5. 🔲 If the content filter passes, send to **Azure** for real evaluation —
   not built (`azureScorer.js` is a stub).
6. ✅ Teacher validation (confirm/override each flagged word) — built, engine
   -agnostic, already works with whatever scorer ran.
7. 🔲 Insights + recommendations — not built (see Backlog #5-6).

**Offline (no connectivity):**
1. 🔲 / ✅ Same as online steps 1-2.
2. ✅ Recording submitted → same technical filter.
3. 🔲 Local Whisper filters *and* scores — same model doing double duty: no
   Azure to hand off to, so if the content filter would reject the input
   online, offline it's the same rejection ("doesn't look like the passage,
   please re-record"); if it passes, Whisper's own output *is* the result,
   not just a pre-filter for something else. Today the whisper scorer always
   scores whatever it's given — it doesn't yet distinguish "filter" from
   "evaluate," since that distinction has no reason to exist until Azure is
   real (step 5 above).
4. ✅ Teacher validation — same as online, already engine-agnostic.
5. 🔲 Insights + recommendations — same as online, not built, presumably the
   same code path regardless of which engine produced the flags.

The practical takeaway: the current `whisper` scorer already *is* both
"offline evaluator" and (with the addition of a content check) would become
"online pre-filter" — same model, two different jobs depending on whether
Azure is reachable. Worth designing the content-filter logic once, reused in
both roles, rather than building it twice.

## Known limitations / residual issues

Found during testing, not (yet) fixed:

- **Chunk-boundary duplication.** The 30s chunking fix (above) solved the
  major bug — real speech being dropped past the 30s mark — but introduced a
  smaller one: in the ~10s overlap window between chunks, a short run of
  words can get transcribed twice, showing up as spurious `inserted` flags
  right around the 20-30s mark of any recording. Not yet fixed; would need
  post-processing to detect and collapse near-duplicate repeated word runs
  in the hypothesis.
- **Cascading misalignment.** `wordAlignment.js` does one global edit-distance
  alignment across the whole passage. A single early Whisper mistake can
  shift the alignment out of sync from that point forward, causing correctly
  -read words downstream to get misflagged too. The real fix is
  **anchor-based alignment**: find solid matching stretches first, then only
  run edit-distance alignment in the small gaps between anchors, so one
  mistake can't drag the rest of the passage with it. Discussed, not built.
- **No prompt-hinting yet.** Whisper's decoding can be biased toward expected
  vocabulary via an initial prompt — and unlike general transcription, this
  app always knows the exact reference text. Agreed as a next step, but got
  sidetracked into diagnosing the chunking bug and was never actually wired
  up. Free to try (no new dependencies), should help most with proper nouns
  ("Datu Bago") and Filipino-specific words.
- **ASR-transcript-alignment is not real pronunciation scoring**, full stop —
  this is the fundamental ceiling of the whisper path, not a bug. A word
  Whisper mis-transcribes reads as a false mispronunciation with no way to
  tell "the model erred" from "the pupil erred." Only a true phoneme-level
  scorer (Azure, or a local GOP/forced-alignment pipeline — see Backlog)
  removes this class of error entirely.
- **Filipino accuracy is only lightly verified.** Confirmed working
  structurally and on one real recording (post chunking-fix), but no
  rigorous accuracy evaluation across multiple speakers/passages has been
  done.
- **No recording time limit.** Recommended (guards against an accidentally
  long recording — forgotten mic, background noise — inflating both cost on
  a future paid path and local compute time on chunked Whisper), but not
  built. A generous cap (~2-3 min) with a visible warning as it approaches
  would cover this without constraining normal use.

## Filipino Local Mispronunciation Detector (active project)

**Goal**: a real, local, phoneme-level Filipino mispronunciation detector —
not transcript-diffing like the current whisper scorer. Filipino is a core,
non-negotiable feature (not something to scope out), and Azure doesn't cover
it (confirmed directly from Azure's own locale table — 33 locales, no
`fil-PH` — see "Known limitations" note on the ceiling of transcript-diffing).

**Explicit target, agreed with the user**: this does **not** need to match
Azure's accuracy. It needs to beat the current `whisper` scorer's accuracy on
Filipino specifically. That's a genuinely achievable bar, not a moonshot —
see "Confidence" below.

### Data source

- **Official academic lineage**: UP Diliman's DSP Laboratory (EEE Institute)
  built the original Filipino Speech Corpus (FSC, 2002, 100+ hours, 100
  speakers), catalogued with ELRA (`ELRA-U-S0229`) — a real, established
  licensing channel. A newer, larger corpus from the same group, the
  **Philippine Languages Database (PLD)**, covers Filipino + 8 other
  Philippine languages, ~454 hours across news/medical/education/tourism/
  spontaneous domains, and its own paper lists "phoneme transcriber" as an
  already-demonstrated application — directly relevant to this project.
  Precedent exists: the FSC has been "widely cited and used in research" by
  other teams already.
  - **Official contact for real access**: Dr. Rowena Cristina L. Guevara,
    DSP Laboratory, UP Diliman EEE Institute — `rowena.guevara@eee.upd.edu.ph`.
    Worth reaching out directly (normal, welcomed academic practice) and/or
    checking ELRA's current terms for the FSC. Do this for anything meant to
    be formally cited or relied on beyond prototyping.
- **Fast path being used right now**: [`sapinsapin/filipinospeechcorpus`](https://huggingface.co/datasets/sapinsapin/filipinospeechcorpus)
  on Hugging Face — 305,246 samples, ~6.94GB, tagged MIT license. This is a
  **third-party repackaging** of the same corpus lineage (references the
  "Development of a Filipino Speech Corpus" paper) — the underlying speech
  data is almost certainly legitimate, but the MIT tag is self-applied by the
  repackager; the linked processing repo (`sapinsapin/halohalo`) documents no
  chain of permission back to the original rights-holder. **Fine for fast
  prototyping/experimentation (what we're doing now); do not treat as
  cleared for anything formally cited or shipped** without going through the
  official channel above first.
  - A full local backup copy is being downloaded to
    `BasaQuest Prototype/data/filipino-speech-corpus-backup/` via:
    `hf download sapinsapin/filipinospeechcorpus --repo-type dataset --local-dir data/filipino-speech-corpus-backup`
    (root `.gitignore` already excludes `data/` — never gets committed).

### Known gaps in the data

- **Adult speakers vs. child target users.** The corpus is adult speech (16+);
  BasaQuest's actual users are Grade 1-6 pupils. Children's voices are
  acoustically different (pitch, formants, articulation) — a real, documented
  hard problem in speech tech, not unique to this project. Mitigation: the
  manuscript's own planned pilot (recording real pupils, teacher-validated)
  doubles as exactly the deployment-matched data needed to check/adapt for
  this gap later — don't need to solve it before starting.
- **No phoneme-level alignment yet** — the corpus has word/sentence-level text
  only; phoneme alignment needs to be derived (Phase 1-2 below), not
  collected separately.
- **No labeled mispronunciation examples for calibration** — the corpus is
  mostly fluent/correct speech. No clean fix; real evaluation (Phase 5) will
  lean on informal listening rather than a formal labeled test set.

### The phased plan

1. ✅ **Filipino G2P (grapheme-to-phoneme)** — built in `g2p/` (Python, no
   external dependencies, no GPU) — see `g2p/README.md` for usage and its
   documented limitations. Rule-based: letter-to-phoneme mapping (including
   digraphs `ng`/`ñ`/plain-`ny`, loanword letters c/f/j/q/v/x/z), a
   syllabifier, the automatic word-initial-vowel glottal stop rule, and
   tuldik accent-mark handling (´ `` ^) that resolves stress/glottal-stop
   placement when a word is written with one. 29 unit tests
   (`g2p/tests/test_g2p.py`), plus a manual run over the app's actual
   Filipino passage (`client/src/passage.js`) with no crashes or empty
   outputs. Honestly documented, not swept under the rug: without an accent
   mark, stress defaults to penultimate-syllable (Filipino's most common
   pattern, but wrong for some real words) and word-medial/final glottal
   stops aren't recovered at all — both are genuine ambiguities in plain
   Filipino spelling, not bugs. An `EXCEPTIONS` dict in `g2p/filipino_g2p/
   g2p.py` is the escape hatch for hardcoding specific words as they're
   found (seeded with "mga"/"ng", the two textbook wholesale-exception
   words). Built in Python (not JS, unlike the rest of this repo) since
   Phase 2 and Phase 3 below are Python/PyTorch and will import this module
   directly, avoiding a rewrite or a cross-language bridge.
2. ✅ **Corpus preprocessing** — built in `training/` (`preprocess_corpus.py`,
   Python, pandas+pyarrow) — see `training/README.md` for full detail. Runs
   locally (CPU-bound data wrangling, no GPU needed), ~40s over the whole
   corpus. Filters out `speech_type == "machine"` (57.3% of rows) as
   planned, plus real junk found by sampling the actual data that isn't
   documented anywhere in the dataset card: a literal `"nonfsc"` reject
   sentinel (~2%), bracket-only non-speech tags (`"[cough]"`, `"[noise]"`,
   `"[]"`), and pure-punctuation rows (~0.9% combined). Left deliberately
   unhandled: curly-brace disfluency annotations in spontaneous speech
   (e.g. `"{guspo} gusto ko..."`, ~0.1% of rows) — plausibly exactly the
   labeled-mispronunciation signal this project otherwise lacks for
   calibration, but the annotation convention isn't documented anywhere, so
   guessing at it risked silently corrupting targets; excluded for now,
   flagged as a real follow-up rather than guessed at. Splits train/val by
   *speaker* (not utterance), hash-based on `speaker_id`, verified to have
   zero speaker overlap — matters because BasaQuest needs to generalize to
   pupils it's never heard, and because the corpus only has 124 total
   speakers, which the default `--val-fraction=0.10` was empirically tuned
   against (5% landed only 3 speakers by chance in an earlier run — too
   thin to be useful). Converts each row's `sentence` to phoneme targets via
   Phase 1's G2P, both per-word (`word_phonemes`) and as a flat CTC-ready
   sequence (`phoneme_sequence`). Output: 105,882 train / 8,926 val / 12,827
   test rows (~2.8GB total, `training/processed/`, gitignored — not
   committed), ready to upload to Google Drive for Phase 3. 24 unit tests
   against synthetic fixtures (`training/tests/`), plus the real full-corpus
   run itself as an end-to-end validation (schema, phoneme fields, and the
   zero-speaker-overlap split all checked directly against the real
   output).
3. ✅ **Fine-tune a pretrained multilingual acoustic model** — DONE
   2026-07-22. `training/colab_finetune_phoneme_model.ipynb`, run for real on
   Colab Pro (T4). Fine-tuned `facebook/wav2vec2-xls-r-300m` via CTC over
   Phase 1's phoneme inventory, using `Wav2Vec2PhonemeCTCTokenizer` (each
   phoneme is one token, not character-split) with `do_phonemize=False` (we
   already have phonemes; the tokenizer's own espeak phonemizer would
   double-process them). CNN feature encoder frozen, full fine-tuning of the
   transformer + CTC head; LoRA never became necessary.
   - **Result: full-val PER 0.2968**, measured on the complete 8,831-row
     validation set. Model lives in Google Drive at
     `My Drive/BasaQuest/final-model-v2` — this is what Phase 4 loads. An
     earlier save (`final-model`, PER 0.3015) is superseded.
   - **It has converged at this configuration.** Validation loss bottomed at
     0.2454 and failed to improve across 3,000 further steps; PER sat in a
     0.2915-0.3017 band with no trend. More epochs on this setup are wasted
     effort — the remaining gains are elsewhere (see the three levers under
     "Confidence / expectations" below).
   - **Six real bugs were found and fixed by actually running it**, all
     documented in the notebook's own cell comments so they don't recur:
     Drive FUSE dropping mid-extraction (fixed by unpacking to local
     `/content`, not the Drive mount); a CUDA OOM from long clips (fixed with
     a 6.0s duration cap plus a smaller batch); a `ctc_loss` crash from clips
     too *short* for their own phoneme count, which had been silently
     producing `Validation Loss: inf` since the very first run (fixed by
     requiring `duration*50 >= phoneme_count*2`); Drive quota filling because
     the API's "delete" only moves to Trash (fixed with an automatic
     `emptyTrash` callback on every save); a mysterious eval-schedule bug
     inherited through `resume_from_checkpoint` (worked around by loading
     weights into a fresh `Trainer` instead of resuming); and — the expensive
     one — **checkpoint rotation silently deleting new progress**, because
     each restart resets the step counter to 0 and `save_total_limit` deletes
     the numerically-smallest folder, so brand-new `checkpoint-500` was being
     destroyed while a stale `checkpoint-36000` survived. Fixed by giving
     every launch its own timestamped `session-<ts>/` output dir and resuming
     by *modification time* rather than by step number. Hours of training
     were lost to that one before it was caught.
   - **Also learned:** early stopping must key on `eval_loss`, not `per` —
     PER is computed on a 2k-row eval subset and is too noisy to steer a
     stopping rule; it killed one run at step 5500 while validation loss was
     still setting new lows at every single eval.
4. 🟡 **GOP (Goodness-of-Pronunciation) scoring** on top of the fine-tuned
   model — built in `gop/` (see `gop/README.md`), 51 tests passing, but **not
   yet run against the real Phase 3 model**, which is still only in Drive.
   Uses the log-posterior-ratio form of GOP: force-align Phase 1's expected
   phoneme sequence to the pupil's audio, then score each expected phoneme
   against its single best competing phoneme, aggregate per word, threshold,
   and emit the existing `ScoreResult` shape. Runs on CPU (one forward pass
   over a short clip); a `.venv` with CPU-only torch is the whole environment.
   - **The CTC aligner is vendored, not torchaudio's.** The plan assumed
     `torchaudio.functional.forced_align`, but it carries a deprecation
     notice announcing removal in 2.9 (torchaudio is in maintenance —
     pytorch/audio#3902). Reimplementing the Viterbi alignment took ~60 lines,
     removed a dependency with a known expiry date from the foundation of
     Phase 4, and handles this project's non-zero blank index (the `<pad>` id,
     35) natively. It's verified *optimal* against exhaustive search over all
     valid CTC alignments, not merely verified to run.
   - **Thresholds are treated as a measurement, not a constant.**
     `gop/calibrate.py` runs GOP over held-out speech assumed correct and sets
     cutoffs so only ~5% of known-correct words would be flagged. Until it's
     run, the placeholders are declared as uncalibrated in every result and in
     the CLI output — a flag list can't be quietly mistaken for a tuned one.
   - **Structural limits, documented rather than papered over:** it cannot
     report `inserted` (forced alignment has no state for an extra word), and
     it assumes the pupil read the whole passage in order — a skipped line
     produces confident nonsense, not an error. That's a second, independent
     argument for Backlog #2's content pre-filter.
   - **Two real findings from inspecting the Phase 2 output**, both affecting
     how this must be calibrated: 93.7% of training rows are single-word clips
     (median 0.61s) and the 6.0s cap kept 99.8% of them, so the model has
     effectively never seen connected read speech — while Phase 4's input is a
     40-60s passage. Calibrating on isolated words would set thresholds far
     too strict, hence `--min-words 3`. Separately, the corpus is entirely
     ages 20-27, so there is no age gradient in it to measure the child-speech
     risk against ahead of real pupil recordings.
   - **Anticipated child-speech correction is built but disabled.**
     `median_shift` cancels a uniform per-speaker GOP offset (the expected
     symptom of the adult/child formant mismatch) while preserving
     within-utterance contrast. Off by default: it's only the right fix if the
     shift really is uniform, which Phase 5 has to measure, and it dulls
     genuinely poor readings if applied blindly.
   - **Measured on the real model 2026-07-22 — and PER is the wrong metric.**
     PER measures free decoding, which GOP never does (forced alignment pins
     the output to the expected phonemes), so PER badly understates it: the
     real recording read PER 0.74 while discriminating usefully.
     `gop/evaluate_discrimination.py` measures the thing that matters — can
     GOP rank a genuinely-spoken phoneme above a substituted one (AUC). On
     realistic "confusable" substitutions: **0.999 / 0.942 on corpus clips
     (1-2 words / ≥8 words), 0.717 on the real 46.7s passage recording.**
     The method is sound; there is a real deployment gap. It is *not* caused
     by connected speech (corpus multi-word hits 0.942) nor by raw input
     length (silence-padding a clip to 60s barely moved it) — the open
     suspects are recording channel (browser mic, AGC, noise suppression vs
     clean corpus audio), speaker, and reading style. Per-word scoring via
     Whisper timestamps was tested and **rejected**: 0.776 vs 0.761, not worth
     the complexity. All deployment numbers rest on **one** recording; more
     real recordings are the next input needed, not more code.
5. **Evaluation** — the part that can't be automated away: listen to real
   recordings, judge whether flagged mispronunciations are actually right.
   The concrete success test: run the **same real recordings through both
   the current `whisper` scorer and the new model side by side**, and have a
   human judge which one's flags are more correct. This is how we'll *know*,
   not just hope.
6. **Integration** — wrap the trained model + GOP scorer as a fourth scorer
   implementing the existing `scorePassage({ passageText, audioFilePath,
   language })` contract (`scorerInterface.js`), same pattern as
   `mock`/`whisper`/`azure`. Since the model is PyTorch, this needs a small
   Python-side service the Node backend calls (not something transformers.js
   can run) — a real, new piece of architecture, not a drop-in file.

### Deployment architecture (discussed 2026-07-22, not yet built)

Where the trained model actually runs, once Phase 4/5 prove it works. Decided
by working backwards from real target hardware rather than assuming.

- **Target hardware is two different tiers, not one.** DepEd "Standard Learner
  Tablets" spec (per user-supplied reference): quad-core 1.3GHz, **2GB RAM**,
  32GB storage, Android 9 minimum. Computer labs are the 6-8GB Celeron/
  Pentium/i3 tier this app's local path was already designed around. These are
  not interchangeable, and the 2GB tablet is the binding constraint.
- **Model memory math** (~300M params, both the Filipino fine-tune and any
  English equivalent): ~1.2GB each at FP32, ~600MB at FP16, ~300MB int8-
  quantized. Two models resident ≈ 600MB quantized. Comfortable on a lab
  desktop; unrealistic on a 2GB Android tablet once the OS and browser
  baseline are accounted for.
- **Conclusion: don't plan on-device inference for the 2GB tablets.** Labs can
  plausibly run it locally (same size class as the `whisper-small` already
  running there, once ONNX-converted + quantized — that conversion is unbuilt
  work, and no real latency benchmark has been taken on that hardware yet).
  Tablets should offload instead.
- **Agreed shape: online server + optional local-network school server.** The
  tablet records audio and posts to whichever scorer service is reachable:
  the school's own LAN server first (lowest latency, works with no internet —
  this is the "offline" tier that actually matters for Philippine schools),
  falling back to an internet-hosted server. Both run the *same* Phase 6
  Python service, just deployed twice — not two implementations. This slots
  into the existing online/offline branching rather than replacing it.
  - Open sub-problem: **service discovery** on the school Wi-Fi. Either mDNS/
    zeroconf, or (simpler, probably sufficient) school IT configures a fixed
    local IP/hostname once at setup.
  - Open sub-problem: **store-and-forward sync** if a local server accumulates
    results while the internet is down. Doesn't exist; ties into Backlog #7
    (database persistence — sessions are still in-memory today).
- **Cloud sizing is not the hard part.** A small VPS (2-4GB RAM, no GPU —
  inference is a single forward pass over one short clip, unlike training)
  holds both quantized models fine. The real variable is concurrent request
  volume, which depends on a pilot scale that hasn't been decided.
- **English needs a separate model; this one will not "switch".** Two
  independent reasons: (1) the CTC head is built from `filipino_g2p`'s
  vocabulary, so English-only phonemes are structurally unproducible; (2)
  full fine-tuning over many epochs pulls the base model's multilingual
  representations toward Filipino (catastrophic forgetting) — the same risk
  Backlog #4 already flags. Natural candidate if English phoneme scoring is
  ever wanted: `facebook/wav2vec2-lv-60-espeak-cv-ft` (already referenced in
  the Phase 3 notebook's PER-metric cell), feeding the same GOP code. Note
  English has a real cloud fallback (Azure) that Filipino doesn't, so the
  pressure to go local for English is much weaker.
- **PWA/offline asset caching solves connectivity, not memory.** A service
  worker can cache game assets and model weights so the app loads with no
  network (same pattern `transformers.js` already uses for Whisper). It does
  **not** reduce RAM once loaded, and an installed PWA uses the same browser
  engine — with the same few-hundred-MB baseline — as a normal tab. Worth
  doing for the offline content; not a lever on the tablet RAM ceiling.

### Training logistics (Google Colab)

- **Free tier**: T4 GPU (not guaranteed), ~12h session cap, and separately
  can disconnect after ~90 min if the *browser tab* looks idle — even while
  the GPU is actively computing. This is a deliberate Google anti-abuse
  policy, not a training-process limitation.
- **Colab Pro ($11.99/mo)**: guaranteed T4 (A100 available when capacity
  allows, not guaranteed), longer sessions, ~100 compute units/month.
  **Does NOT include background execution** — closing the browser tab does
  not keep training alive. An earlier version of this doc claimed it did;
  that was wrong, was acted on, and cost real money. Corrected 2026-07-22
  against Google's current pricing page. Keep-alive scripts are not a fix
  either (they work against Google's own anti-abuse policy and aren't
  reliable — not recommended). Unit burn rates: T4 ≈ 1.76 units/hr,
  A100 ≈ 15 units/hr — so on Pro's ~100 units, A100 is roughly 6-7 hours of
  total monthly budget. Use A100 for short, early-stopped runs, not for
  long unattended grinds.
- **Colab Pro+ ($49.99/mo)**: 500 compute units/month, priority access, and
  **background execution** — this tier, not Pro, is the one where training
  survives a closed tab (and even there, users report it being imperfect).
- Session length is a **per-session** cap, not a strict daily reset — once a
  session ends you can generally start another, though Google applies an
  unpublished, fuzzy "fair use" throttle on top for heavy continuous usage.
- **Recommendation**: Colab Pro is a reasonable cost for the GPU access and
  longer sessions, but be clear about what it does *not* buy: it does not
  remove babysitting, because background execution is Pro+-only. The
  practical mitigation on Pro is not a better plan — it's making
  interruptions cheap: frequent checkpoints to Drive, a resume path that
  reliably finds the newest checkpoint, and early stopping so runs are short
  enough to finish in one sitting. That's what the Phase 3 notebook now
  does (see its Train cell).
- No official "Claude Code for Colab" integration is available in this
  environment (checked the MCP registry directly, found nothing) — even
  though Google shipped a real MCP server for this in the wider ecosystem
  (April 2026). Workflow for now: write code here, run it in Colab, bring
  results/errors back to iterate — same loop as everything else, just with a
  manual bridge instead of Claude driving Colab directly.

### Confidence / expectations

Not a guarantee — real execution risk exists (first build, no labeled
calibration data, needs real ML fine-tuning work). But genuine, reasoned
confidence: the bar is "beat whisper-transcript-diffing on Filipino," which
is architecturally a *low* bar — that approach can't distinguish "Whisper
mis-transcribed a correct word" from "the pupil actually mispronounced it,"
by construction. A GOP-style scorer, even an imperfect first attempt, is
aimed at the right thing in a way transcript-diffing fundamentally isn't, and
will be trained on far more Filipino-specific data than Whisper-small ever
saw. Verify with the head-to-head test in Phase 5, don't just assume it
worked.

## Backlog

Bigger items, roughly in the order they'd matter most:

1. **Real Azure Pronunciation Assessment integration** (`azureScorer.js` is
   still a stub that throws). This is the manuscript's preferred cloud path
   and solves the transcript-alignment ceiling entirely — real phoneme-level
   AccuracyScore/FluencyScore/CompletenessScore per word, not inferred from a
   text diff. Cost is genuinely small at pilot scale (~$1.32/hr of audio ≈
   ₱81.5/hr; a full-semester 20-pupil pilot with weekly sessions comes out to
   roughly ₱244 total, not per week). Need to confirm Filipino locale support
   specifically before assuming it covers both languages.
2. **Whisper-as-content-filter for the online path** (see "Intended pipeline"
   above) — before a recording is sent to Azure, run it through local Whisper
   first and check the transcript is plausibly the right passage/language,
   not just non-silent. Needs a "good enough" similarity threshold (e.g.
   rough word-overlap against the reference passage) — same alignment
   machinery already in `wordAlignment.js` could likely be reused for this
   rather than needing new logic. Depends on #1 existing to matter (no point
   filtering for a call that doesn't happen yet).
3. **Local phoneme-level scoring (GOP / forced alignment) for Filipino** —
   see the dedicated "Filipino Local Mispronunciation Detector" section below.
   This is now an active project, not just a backlog idea.
4. **Fine-tuned Filipino Whisper model** (`LWobole/whisper-small-tagalog`,
   16.66% WER on FLEURS Tagalog) as a cheaper lever specifically for Filipino
   accuracy, short of full phoneme scoring. Two blockers checked and
   confirmed: no ONNX weights published (would need conversion via HF's
   `optimum` tooling), and unknown whether English capability survived the
   fine-tune (if not, using it means reintroducing a two-model memory cost we
   deliberately consolidated away from).
5. **Insights generation** (manuscript: "diagnostic summary of dominant
   reading weaknesses"). Recommended as rule-based/templated from the
   scorer's already-structured per-word miscue data — no LLM needed, free,
   instant, reliable. Not yet built.
6. **Remediation content generation** (practice passages/drills/flashcards).
   Needs real text generation, unlike insights. Recommended as a cloud LLM
   path mirroring the manuscript's own essay-grading precedent (cloud-only,
   queued if offline) rather than a local LLM — stacking a text-generation
   model on top of an already-loaded Whisper session risks exceeding the
   6-8GB / Celeron-Pentium-i3 hardware ceiling this whole local path was
   designed around. Not yet built, no interface defined.
7. **Database persistence** — sessions currently live in memory
   (`sessionsStore.js`) and are lost on server restart.
8. **Data privacy handling** — the manuscript's de-identification, real-time
   (non-logged) processing, and 7-day retention/deletion policy
   (`Data Handling for Cloud-Processed Audio`) isn't implemented; this
   prototype has no auth and no retention policy at all.
9. **Grade-level passage scaling** — one passage per language today, no
   Grade 1-6 difficulty differentiation.

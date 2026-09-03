# Filipino G2P (grapheme-to-phoneme)

Phase 1 of the "Filipino Local Mispronunciation Detector" project (see the
root [ROADMAP.md](../ROADMAP.md)). Rule-based, deterministic, no GPU, no
external dependencies (pure Python 3.10+ standard library).

Converts Filipino text to a phoneme sequence per word — the target
representation that Phase 2 (corpus preprocessing) and Phase 4 (GOP
scoring) build on.

## Usage

```python
from filipino_g2p import word_to_phonemes, text_to_phonemes

word_to_phonemes("bahay")          # -> ['b', 'a1', 'h', 'a', 'y']
word_to_phonemes("aso")            # -> ['q', 'a1', 's', 'o']  (q = glottal stop /ʔ/)
word_to_phonemes("kanya")          # -> ['k', 'a1', 'ny', 'a']

text_to_phonemes("Ang bata ay masaya.")
# -> [{'word': 'Ang', 'phonemes': [...]}, {'word': 'bata', 'phonemes': [...]}, ...]
```

`1` marks the stressed vowel (e.g. `a1`); `q` is the ASCII stand-in for the
glottal stop /ʔ/. See `filipino_g2p/phonemes.py` for the full symbol table
and `full_vocabulary()` for a CTC-vocab-ready symbol list.

## Running the tests

No dependencies beyond the standard library:

```bash
cd g2p
python -m unittest discover -s tests -t . -v
```

## What this does and doesn't get right

Tagalog/Filipino spelling is mostly phonemic, but two real ambiguities
can't be resolved from plain spelling alone (see the root ROADMAP.md's
"Filipino Local Mispronunciation Detector" section for the full context):

- **Stress placement.** Without an explicit tuldik accent mark (´ acute, `
  grave, ^ circumflex — see `g2p.py`), a penultimate-stress default is
  applied. This is the single most common pattern, but it's wrong for some
  real words (e.g. "biglá", "buô"). `EXCEPTIONS` in `g2p.py` is an escape
  hatch for hardcoding specific words as they're discovered — currently
  seeded with "mga" and "ng", the two textbook examples of Filipino
  orthographic irregularity that letter-by-letter rules can't handle at
  all (they're not stress exceptions, they're wholesale exceptions).
- **Word-medial/final glottal stops.** Only recovered when a tuldik mark is
  present. Plain spelling can't distinguish "bata" (child) from "batà"
  (young).

Both are called out explicitly, rather than silently guessed at, because
getting them wrong silently would be worse than not resolving them at all
for a mispronunciation detector.

Also approximate, each documented at its source in `grapheme_map.py`:
loanword letters 'c' (s before e/i, else k), 'j' (always /dʒ/, even for
older Spanish-origin words that historically use /h/), and 'x' (always
/ks/).

## Module layout

- `phonemes.py` — the ASCII phoneme symbol inventory.
- `grapheme_map.py` — letter(s) -> phoneme(s) for a single cleaned word.
- `syllabify.py` — groups a phoneme list into syllables (needed only to
  place the stress marker).
- `stress.py` — the default penultimate-stress rule.
- `g2p.py` — top-level API: accent-mark handling, the word-initial
  automatic-glottal-stop rule, `EXCEPTIONS`, `word_to_phonemes`,
  `text_to_phonemes`.

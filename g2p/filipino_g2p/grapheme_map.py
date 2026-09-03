"""
Letter(s) -> phoneme mapping for a single already-lowercased,
accent-stripped Filipino word. Longest-match tokenization: multi-letter
graphemes (ng, qu, loanword digraphs) are checked before falling back to
single letters.

Some of these are fixed heuristics, not universal truths - documented so
they're not mistaken for settled linguistics:
- 'c' -> 's' before e/i, else 'k' (Spanish/English loanword convention).
- 'j' -> the /dʒ/ affricate, matching contemporary loanwords ("jeep",
  "jacket"). Older Spanish-origin words ("Jose", "trabajo") historically
  use /h/ instead - not distinguishable from spelling alone.
- 'qu' -> 'k' (the 'u' is silent, as in Spanish-derived spelling).
- 'x' -> 'k' + 's' (two phonemes; matches "taxi" -> t a k s i).
- plain 'ny' before a vowel -> the same palatal nasal /ɲ/ as 'ñ' (matches
  common words like "kanya", "ganyan", "pinya" - real Filipino words are
  spelled with plain 'ny' for this sound at least as often as with 'ñ').
  Not applied when 'ny' isn't followed by a vowel, since then it isn't
  functioning as a single onset cluster.
"""

# Ordered longest-match first. Each entry: (grapheme, phonemes-tuple).
_MULTI_LETTER = (
    ("ng", ("ng",)),
    ("ñ", ("ny",)),  # ñ
    ("qu", ("k",)),
    ("sh", ("sh",)),
    ("ch", ("ch",)),
)

_SINGLE_LETTER = {
    "a": ("a",), "e": ("e",), "i": ("i",), "o": ("o",), "u": ("u",),
    "b": ("b",), "d": ("d",), "f": ("f",), "g": ("g",), "h": ("h",),
    "k": ("k",), "l": ("l",), "m": ("m",), "n": ("n",), "p": ("p",),
    "r": ("r",), "s": ("s",), "t": ("t",), "v": ("v",), "w": ("w",),
    "y": ("y",), "z": ("z",),
    "j": ("j",),
    "x": ("k", "s"),
    "q": ("k",),  # bare 'q' outside 'qu' - rare, treat like k
}

_C_BEFORE_FRONT_VOWEL = ("e", "i")
_VOWEL_LETTERS = ("a", "e", "i", "o", "u")

# Characters with no sound of their own that can still appear inside a
# cleaned word - skipped rather than guessed at.
_SILENT = ("'", "-")


def word_to_raw_phonemes(word: str) -> list[str]:
    """word must already be lowercase with diacritics stripped. Does not
    handle stress or the automatic word-initial glottal stop - see g2p.py.
    """
    phonemes: list[str] = []
    i = 0
    n = len(word)
    while i < n:
        if word.startswith("ny", i) and i + 2 < n and word[i + 2] in _VOWEL_LETTERS:
            phonemes.append("ny")
            i += 2
            continue

        matched = False
        for grapheme, phones in _MULTI_LETTER:
            if word.startswith(grapheme, i):
                phonemes.extend(phones)
                i += len(grapheme)
                matched = True
                break
        if matched:
            continue

        ch = word[i]
        if ch == "c":
            nxt = word[i + 1] if i + 1 < n else ""
            phonemes.append("s" if nxt in _C_BEFORE_FRONT_VOWEL else "k")
            i += 1
            continue
        if ch in _SINGLE_LETTER:
            phonemes.extend(_SINGLE_LETTER[ch])
            i += 1
            continue
        if ch in _SILENT:
            i += 1
            continue
        # Unknown character (digit, stray punctuation) - skip rather than
        # crash; text_to_phonemes callers see it as producing no phoneme.
        i += 1

    return phonemes

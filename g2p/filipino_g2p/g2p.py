"""
Filipino grapheme-to-phoneme (G2P) conversion.

Public API:
- word_to_phonemes(word) -> list[str]
- text_to_phonemes(text) -> list[dict]  (per-word, in passage order, keeping
  the original token text - shaped so a caller can key results by word the
  same way scorerInterface.js's WordResult does)

Known, documented limitations (see ROADMAP.md's "Filipino Local
Mispronunciation Detector" section - these are real orthographic
ambiguities, not bugs to be fixed later):
- Stress is only correctly resolved when the word carries an explicit
  tuldik accent mark, or is listed in EXCEPTIONS below. Otherwise a
  penultimate-stress default is applied (see stress.py), which is wrong for
  some real words (e.g. "biglá", "buô").
- Word-medial/final glottal stops are only recovered from an explicit
  paiwà/pakupyâ accent mark on the final vowel. Plain spelling alone can't
  distinguish e.g. "bata" (child) from "batà" (young).
- 'c', 'j', 'x' loanword letters each use a single fixed heuristic; a
  specific loanword's real pronunciation can differ (see grapheme_map.py).
"""
import re
import unicodedata

from .grapheme_map import word_to_raw_phonemes
from .phonemes import GLOTTAL_STOP, VOWELS
from .stress import apply_stress, default_stress_syllable_index
from .syllabify import syllabify

# Combining marks (NFD form) for the three tuldik accent types.
_ACCENT_TYPES = {
    "́": "acute",       # pahilis: stress on the final syllable
    "̀": "grave",       # paiwa: (default) penult stress + final glottal
    "̂": "circumflex",  # pakupya: final stress + final glottal
}


def _build_accented_vowel_table() -> dict[str, tuple[str, str]]:
    """Maps a precomposed accented vowel (e.g. 'á') to (base_vowel,
    accent_type), built from vowel + combining-mark so no literal accented
    character needs to appear in source. Built via NFC so it only ever
    matches an actual vowel+accent combination - crucially, this leaves
    'ñ' (and any other letter that happens to use a combining mark, e.g. if
    NFD input is passed in) completely untouched, since 'ñ' carries a
    combining tilde, not one of the three stress marks above.
    """
    table = {}
    for vowel in "aeiou":
        for mark, accent_type in _ACCENT_TYPES.items():
            composed = unicodedata.normalize("NFC", vowel + mark)
            table[composed] = (vowel, accent_type)
    return table


_ACCENTED_VOWELS = _build_accented_vowel_table()

# Known irregular words where letter-by-letter rules would misfire.
# word (lowercase) -> full phoneme list, already stressed. These are two of
# the textbook examples of Filipino orthographic irregularity, not edge
# cases invented for this codebase.
EXCEPTIONS: dict[str, list[str]] = {
    "mga": ["m", "a", "ng", "a1"],  # plural marker, pronounced "ma-nga"
    "ng": ["n", "a1", "ng"],        # linker/possessive, pronounced "nang"
}

_STRIP_RE = re.compile(r"^[^\w'-]+|[^\w'-]+$", re.UNICODE)
_WORD_RE = re.compile(r"\S+", re.UNICODE)


def _strip_accents(word: str) -> tuple[str, str | None]:
    """Returns (plain_word, accent_type) where accent_type is one of
    'acute'/'grave'/'circumflex'/None. Per the standard tuldik convention,
    the accent (when written) sits on the word's final vowel, so only the
    mark's presence/type matters here, not its exact position. Normalizes
    to NFC first so both a precomposed accented vowel and a decomposed
    base+combining-mark sequence are recognized the same way - and, just as
    importantly, so a letter like 'ñ' that also uses a combining mark is
    left alone rather than mistaken for a stress accent (see the table
    builder's docstring above for why this matters)."""
    composed = unicodedata.normalize("NFC", word)
    plain_chars = []
    accent_type = None
    for ch in composed:
        if ch in _ACCENTED_VOWELS:
            base, accent_type = _ACCENTED_VOWELS[ch]
            plain_chars.append(base)
        else:
            plain_chars.append(ch)
    return "".join(plain_chars), accent_type


def word_to_phonemes(word: str) -> list[str]:
    """word may include surrounding punctuation; it's stripped first.
    Returns [] for a token with no phonemic content (pure punctuation,
    digits, empty string)."""
    # NFC-compose before stripping punctuation: a decomposed accent mark
    # (base letter + combining mark, e.g. from NFD-normalized input) isn't
    # matched by \w on its own and would otherwise get deleted here as if
    # it were trailing punctuation, silently losing the accent.
    composed = unicodedata.normalize("NFC", word.strip().lower())
    cleaned = _STRIP_RE.sub("", composed)
    if not cleaned:
        return []

    if cleaned in EXCEPTIONS:
        return list(EXCEPTIONS[cleaned])

    plain, accent_type = _strip_accents(cleaned)
    phonemes = word_to_raw_phonemes(plain)
    if not phonemes:
        return []

    # Predictable rule, not an approximation: Filipino words don't start
    # with a bare vowel sound - an onset glottal stop is automatic.
    if phonemes[0] in VOWELS:
        phonemes = [GLOTTAL_STOP] + phonemes

    syllables = syllabify(phonemes)
    if not syllables:
        return phonemes

    if accent_type == "acute":
        stress_idx = len(syllables) - 1
        final_glottal = False
    elif accent_type == "grave":
        stress_idx = default_stress_syllable_index(len(syllables))
        final_glottal = True
    elif accent_type == "circumflex":
        stress_idx = len(syllables) - 1
        final_glottal = True
    else:
        stress_idx = default_stress_syllable_index(len(syllables))
        final_glottal = False

    phonemes = apply_stress(phonemes, syllables, stress_idx)
    if final_glottal and phonemes[-1] != GLOTTAL_STOP:
        phonemes.append(GLOTTAL_STOP)

    return phonemes


def text_to_phonemes(text: str) -> list[dict]:
    """Splits text on whitespace and converts each token to phonemes, in
    order. Each entry keeps the original token text (with punctuation) so
    callers can display/align it against the source passage."""
    return [{"word": token, "phonemes": word_to_phonemes(token)} for token in _WORD_RE.findall(text)]

"""
Filipino phoneme inventory for the local mispronunciation detector's G2P.

ASCII tokens are used instead of raw IPA so they can double as CTC
vocabulary symbols later (Phase 3 fine-tuning, Phase 4 GOP scoring - see
ROADMAP.md's "Filipino Local Mispronunciation Detector" section). Each
symbol's IPA equivalent is noted alongside it below.
"""

VOWELS = ("a", "e", "i", "o", "u")  # IPA: a, ɛ, i, ɔ, u

# Consonants that map from a single Filipino alphabet letter or the native
# "ng" digraph.
CONSONANTS = (
    "p", "t", "k", "b", "d", "g",  # stops
    "m", "n",                      # nasals
    "ng",                           # /ŋ/ - digraph, one phoneme
    "ny",                           # /ɲ/ - from letter ñ
    "s", "h",                       # fricatives
    "w", "l", "r", "y",             # approximants/liquids (r = flap /ɾ/)
)

# Only appear via loanword letters/digraphs (c, f, j, q, v, x, z). Included
# because modern Filipino text, including BasaQuest's own passages, routinely
# contains loanwords.
LOAN_CONSONANTS = (
    "f", "v", "z",    # /f/, /v/, /z/
    "sh", "ch", "j",  # /ʃ/, /tʃ/, /dʒ/
)

GLOTTAL_STOP = "q"  # /ʔ/ - ASCII stand-in; 'q' is otherwise fully absorbed
                     # into 'k' by grapheme_map.py, so it's free to reuse.

STRESS_MARK = "1"

ALL_BASE_PHONEMES = frozenset(VOWELS + CONSONANTS + LOAN_CONSONANTS + (GLOTTAL_STOP,))


def is_vowel(phoneme: str) -> bool:
    """True for both stressed ('a1') and unstressed ('a') vowel tokens."""
    base = phoneme[:-1] if phoneme.endswith(STRESS_MARK) else phoneme
    return base in VOWELS


def full_vocabulary() -> list[str]:
    """Every symbol that can appear in G2P output, including stressed vowel
    variants (e.g. 'a1'). Meant for building a CTC tokenizer vocab in Phase 3.
    """
    consonantish = sorted(ALL_BASE_PHONEMES - set(VOWELS))
    vowels_plain = sorted(VOWELS)
    vowels_stressed = sorted(v + STRESS_MARK for v in VOWELS)
    return consonantish + vowels_plain + vowels_stressed

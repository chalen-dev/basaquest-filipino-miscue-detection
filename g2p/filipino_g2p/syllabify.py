"""
Rough syllabifier over a phoneme list. Used only to locate syllable
boundaries for stress-marker placement (see stress.py), not intended as a
general phonological parser.

Filipino syllables are predominantly (C)(C)V(C). Between two vowel nuclei,
consonants are split with a maximal-onset heuristic: a single consonant
between two vowels always becomes the onset of the following syllable
(V.CV). With two or more consonants between vowels, the last one or two
become the onset of the following syllable - two only if they form one of a
small set of legal loanword onset clusters (stop/fricative + liquid/glide,
e.g. "tr", "pl", "kw") - and anything further left stays as the coda of the
preceding syllable. This matches the dominant CV / CVC pattern of native
Filipino words while still doing something reasonable with loanword
clusters.
"""
from .phonemes import is_vowel

_LEGAL_ONSET_CLUSTERS = frozenset((
    "pl", "bl", "kl", "gl", "fl",
    "pr", "br", "tr", "dr", "kr", "gr", "fr",
    "kw", "sw", "ts", "dy",
))


class Syllable:
    __slots__ = ("onset", "nucleus_index", "coda")

    def __init__(self, onset, nucleus_index, coda):
        self.onset = onset
        self.nucleus_index = nucleus_index
        self.coda = coda


def syllabify(phonemes: list[str]) -> list[Syllable]:
    nucleus_indices = [i for i, p in enumerate(phonemes) if is_vowel(p)]
    if not nucleus_indices:
        return []

    syllables = []
    cursor = 0  # index of the first not-yet-assigned phoneme

    for k, nucleus_i in enumerate(nucleus_indices):
        onset = list(range(cursor, nucleus_i))
        is_last = k == len(nucleus_indices) - 1

        if is_last:
            coda = list(range(nucleus_i + 1, len(phonemes)))
            cursor = len(phonemes)
        else:
            next_nucleus_i = nucleus_indices[k + 1]
            between = list(range(nucleus_i + 1, next_nucleus_i))
            coda_len = _coda_length(phonemes, between)
            coda = between[:coda_len]
            cursor = nucleus_i + 1 + coda_len

        syllables.append(Syllable(onset=onset, nucleus_index=nucleus_i, coda=coda))

    return syllables


def _coda_length(phonemes: list[str], between_indices: list[int]) -> int:
    """Of the consonants between two vowel nuclei, how many belong to the
    coda of the FIRST syllable (the rest become the onset of the second)."""
    n = len(between_indices)
    if n == 0:
        return 0
    if n == 1:
        return 0  # single consonant -> onset of the following syllable
    last_two = "".join(phonemes[i] for i in between_indices[-2:])
    if last_two in _LEGAL_ONSET_CLUSTERS:
        return n - 2
    return n - 1  # default: only the final consonant becomes the onset

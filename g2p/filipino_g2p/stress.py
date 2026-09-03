"""
Default stress assignment for words with no explicit tuldik (accent mark).

The honest limitation (see ROADMAP.md's "Filipino Local Mispronunciation
Detector" section): Filipino stress is phonemic and not fully recoverable
from plain spelling. Penultimate stress is the single most common pattern
and is used here as the default for any word without an explicit accent
mark or a listed exception - it will be wrong for some real words (e.g.
final-stressed words like "biglá"). Add an entry to EXCEPTIONS in g2p.py,
or write the word with its accent mark, to override this default.
"""
from .phonemes import STRESS_MARK


def default_stress_syllable_index(num_syllables: int) -> int:
    """Index (0-based) of the syllable that gets default stress."""
    if num_syllables <= 1:
        return 0
    return num_syllables - 2  # penultimate


def apply_stress(phonemes: list[str], syllables, stress_syllable_index: int) -> list[str]:
    result = list(phonemes)
    syll = syllables[stress_syllable_index]
    result[syll.nucleus_index] = result[syll.nucleus_index] + STRESS_MARK
    return result

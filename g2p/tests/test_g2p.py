import unittest

from filipino_g2p import full_vocabulary, text_to_phonemes, word_to_phonemes

# Combining diacritics (NFD form), spelled out explicitly rather than as
# literal precomposed characters so the intent is unambiguous in source.
_ACUTE = "́"
_GRAVE = "̀"
_CIRCUMFLEX = "̂"


def _plain(phonemes):
    """Strips stress digits, for tests that only care about segmentation."""
    return [p.rstrip("1") for p in phonemes]


class BasicWordsTest(unittest.TestCase):
    """Words where the penultimate-stress default is uncontroversially the
    real pronunciation, so both segmentation and stress are asserted."""

    def test_bahay(self):
        self.assertEqual(word_to_phonemes("bahay"), ["b", "a1", "h", "a", "y"])

    def test_puso(self):
        self.assertEqual(word_to_phonemes("puso"), ["p", "u1", "s", "o"])

    def test_kumusta_three_syllables(self):
        # ku-MUS-ta: penultimate of 3 syllables is "mus".
        self.assertEqual(word_to_phonemes("kumusta"), ["k", "u", "m", "u1", "s", "t", "a"])


class InitialGlottalStopTest(unittest.TestCase):
    """Word-initial vowel -> automatic glottal onset is a predictable rule,
    not an approximation, so it's tested for exact output."""

    def test_aso(self):
        self.assertEqual(word_to_phonemes("aso"), ["q", "a1", "s", "o"])

    def test_no_glottal_when_word_starts_with_consonant(self):
        self.assertNotIn("q", word_to_phonemes("bahay"))


class DigraphsAndLoanLettersTest(unittest.TestCase):
    def test_ng_digraph_segmentation(self):
        # "buong" -> b, u, o, ng (the digraph is one phoneme, not n + g).
        self.assertEqual(_plain(word_to_phonemes("buong")), ["b", "u", "o", "ng"])

    def test_eng_ye_digraph(self):
        self.assertEqual(_plain(word_to_phonemes("nino")), ["n", "i", "n", "o"])
        self.assertIn("ny", _plain(word_to_phonemes("niño")))  # niño

    def test_plain_ny_before_vowel_is_palatal_nasal(self):
        # "kanya" (his/hers) - real pronunciation is ka-NYA, not kan-ya.
        self.assertEqual(_plain(word_to_phonemes("kanya")), ["k", "a", "ny", "a"])

    def test_plain_ny_not_merged_when_not_followed_by_vowel(self):
        # word-final "ny" isn't functioning as an onset cluster.
        self.assertEqual(_plain(word_to_phonemes("puny")), ["p", "u", "n", "y"])

    def test_c_before_front_vowel_is_s(self):
        self.assertIn("s", _plain(word_to_phonemes("cinema")))

    def test_c_elsewhere_is_k(self):
        self.assertEqual(_plain(word_to_phonemes("cotse"))[0], "k")

    def test_j_is_dzh(self):
        self.assertIn("j", _plain(word_to_phonemes("jeep")))

    def test_x_is_ks(self):
        self.assertEqual(_plain(word_to_phonemes("taxi")), ["t", "a", "k", "s", "i"])

    def test_loan_consonants_f_v_z(self):
        self.assertIn("f", _plain(word_to_phonemes("filipino")))
        self.assertIn("v", _plain(word_to_phonemes("verde")))
        self.assertIn("z", _plain(word_to_phonemes("zoo")))


class ExceptionsTest(unittest.TestCase):
    """The two textbook examples of Filipino orthographic irregularity that
    letter-by-letter rules can't handle."""

    def test_mga(self):
        self.assertEqual(word_to_phonemes("mga"), ["m", "a", "ng", "a1"])

    def test_ng_word(self):
        self.assertEqual(word_to_phonemes("ng"), ["n", "a1", "ng"])

    def test_exceptions_are_case_insensitive(self):
        self.assertEqual(word_to_phonemes("MGA"), word_to_phonemes("mga"))


class DiacriticsTest(unittest.TestCase):
    """Explicit tuldik accent marks resolve the stress/glottal-stop
    ambiguity that plain spelling leaves undetermined."""

    def test_acute_moves_stress_to_final_syllable(self):
        # "bigla" (2 syllables): plain default would stress the first
        # syllable; an acute on the final vowel overrides that to final
        # stress, with no glottal stop added.
        plain_default = word_to_phonemes("bigla")
        self.assertTrue(plain_default[1].endswith("1"))  # first syllable nucleus

        accented = word_to_phonemes("bigl" + "a" + _ACUTE)
        self.assertTrue(accented[-1].endswith("1"))
        self.assertNotEqual(accented[-1], "q")

    def test_grave_adds_final_glottal_keeps_penult_stress(self):
        accented = word_to_phonemes("bat" + "a" + _GRAVE)
        self.assertEqual(accented[-1], "q")  # final glottal stop appended
        self.assertTrue(accented[1].endswith("1"))  # still penult-stressed

    def test_circumflex_final_stress_and_glottal(self):
        accented = word_to_phonemes("samp" + "u" + _CIRCUMFLEX)
        self.assertEqual(accented[-1], "q")
        stressed = [p for p in accented if p.endswith("1")]
        self.assertEqual(len(stressed), 1)
        # the stressed vowel should be the one immediately before the
        # appended glottal stop, i.e. the final syllable's nucleus.
        self.assertTrue(accented[-2].endswith("1"))


class TextToPhonemesTest(unittest.TestCase):
    def test_preserves_word_order_and_original_text(self):
        result = text_to_phonemes("Ang bata ay masaya.")
        self.assertEqual([r["word"] for r in result], ["Ang", "bata", "ay", "masaya."])
        self.assertTrue(all("phonemes" in r for r in result))

    def test_punctuation_only_token_yields_no_phonemes(self):
        result = text_to_phonemes("bahay --")
        self.assertEqual(result[1]["phonemes"], [])

    def test_empty_string(self):
        self.assertEqual(text_to_phonemes(""), [])


class MalformedInputTest(unittest.TestCase):
    def test_digit_only_token(self):
        self.assertEqual(word_to_phonemes("123"), [])

    def test_empty_word(self):
        self.assertEqual(word_to_phonemes(""), [])

    def test_whitespace_only(self):
        self.assertEqual(word_to_phonemes("   "), [])


class VocabularyTest(unittest.TestCase):
    def test_full_vocabulary_has_no_duplicates(self):
        vocab = full_vocabulary()
        self.assertEqual(len(vocab), len(set(vocab)))

    def test_full_vocabulary_includes_stressed_and_unstressed_vowels(self):
        vocab = set(full_vocabulary())
        self.assertIn("a", vocab)
        self.assertIn("a1", vocab)

    def test_full_vocabulary_includes_glottal_stop(self):
        self.assertIn("q", full_vocabulary())


if __name__ == "__main__":
    unittest.main()

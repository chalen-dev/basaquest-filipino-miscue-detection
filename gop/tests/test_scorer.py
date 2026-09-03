"""End-to-end tests for score_passage, using a stand-in acoustic model.

The real Phase 3 checkpoint is 1.2GB and lives in Google Drive, so these
tests substitute a fake that emits a chosen frame-posterior pattern. That is
not a compromise for these particular assertions: everything being checked
here - G2P integration, word-level aggregation, the status decision, the
output shape the Node server consumes - is logic this package owns. What the
fake cannot tell us is whether the *model* scores real speech sensibly, which
is Phase 5's job and cannot be unit tested.

The audio path is real: a synthetic WAV is written to disk and decoded
through ffmpeg exactly as a pupil's recording would be.
"""

import json
import sys
import unittest
import wave
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from basaquest_gop.config import PLACEHOLDER_THRESHOLDS
from basaquest_gop.g2p_bridge import phoneme_inventory, text_to_phonemes
from basaquest_gop.scorer import score_passage

SAMPLE_RATE = 16000


def build_vocab():
    """The Phase 3 vocabulary, including the two tokens the tokenizer adds on
    top of vocab.json - so the fake reproduces the real id layout, blank at 35
    and untrained <s>/</s> at 36-37."""
    inventory = phoneme_inventory()
    vocab = {p: i for i, p in enumerate(inventory)}
    vocab["|"] = len(vocab)
    vocab["<unk>"] = len(vocab)
    vocab["<pad>"] = len(vocab)
    vocab["<s>"] = len(vocab)
    vocab["</s>"] = len(vocab)
    return vocab


class FakeModel:
    """Emits a caller-specified per-frame preference sequence.

    Duck-types only what scorer.score_passage actually touches, so it stays
    honest about the coupling between the two.
    """

    def __init__(self, preferences, vocab=None, strength=10.0):
        self.vocab = vocab or build_vocab()
        self.id_to_token = {i: t for t, i in self.vocab.items()}
        self.blank_id = self.vocab["<pad>"]
        self.competitor_ids = np.array(
            sorted(self.vocab[p] for p in phoneme_inventory()), dtype=np.int64
        )
        self.seconds_per_frame = 0.02
        self._preferences = preferences
        self._strength = strength

    def encode_phonemes(self, phonemes):
        missing = sorted({p for p in phonemes if p not in self.vocab})
        if missing:
            raise KeyError(f"unknown phonemes: {missing}")
        return [self.vocab[p] for p in phonemes]

    def log_probs(self, waveform, window_seconds=None, overlap_seconds=0.0):
        logits = np.zeros((len(self._preferences), len(self.vocab)))
        for t, token_id in enumerate(self._preferences):
            logits[t, token_id] = self._strength
        shifted = logits - logits.max(axis=1, keepdims=True)
        return shifted - np.log(np.exp(shifted).sum(axis=1, keepdims=True))


def write_wav(path, seconds=2.0):
    """A real WAV on disk, so load_audio/ffmpeg are exercised rather than
    stubbed. Contents are irrelevant - the fake model ignores the waveform -
    but the duration flows through to durationSeconds."""
    n = int(SAMPLE_RATE * seconds)
    samples = (np.sin(np.arange(n) * 0.01) * 8000).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(samples.tobytes())
    return path


def phoneme_ids_for(passage, vocab):
    """The flat expected phoneme id sequence, and the per-word split."""
    tokens = [t for t in text_to_phonemes(passage) if t["phonemes"]]
    per_word = [[vocab[p] for p in t["phonemes"]] for t in tokens]
    return [i for word in per_word for i in word], per_word


def spread_preferences(target_ids, blank_id, gap=2):
    """A frame pattern where each expected phoneme is clearly produced, spaced
    out like real speech: blank padding, then the phoneme, then blanks."""
    preferences = [blank_id]
    for token_id in target_ids:
        preferences.append(token_id)
        preferences.extend([blank_id] * gap)
    return preferences


class TestScorePassageHappyPath(unittest.TestCase):
    PASSAGE = "Ang bata ay masaya"

    def setUp(self):
        self.dir = TemporaryDirectory()
        self.audio = write_wav(Path(self.dir.name) / "clip.wav", seconds=3.0)
        self.vocab = build_vocab()
        self.target_ids, _ = phoneme_ids_for(self.PASSAGE, self.vocab)

    def tearDown(self):
        self.dir.cleanup()

    def score(self, preferences, **kwargs):
        model = FakeModel(preferences, self.vocab)
        return score_passage(self.PASSAGE, self.audio, model, **kwargs)

    def test_well_produced_speech_is_all_correct(self):
        result = self.score(spread_preferences(self.target_ids, self.vocab["<pad>"]))

        self.assertEqual(len(result["words"]), 4)
        for word in result["words"]:
            self.assertEqual(word["status"], "correct", word)
            self.assertGreater(word["meanGop"], 0.0)

    def test_output_matches_the_scorer_interface_shape(self):
        result = self.score(spread_preferences(self.target_ids, self.vocab["<pad>"]))

        self.assertEqual(result["engine"], "gop-local")
        self.assertEqual(result["durationSeconds"], 3)
        self.assertIsInstance(result["durationSeconds"], int)

        for index, word in enumerate(result["words"]):
            self.assertEqual(word["index"], index)
            self.assertIn(
                word["status"], {"correct", "mispronounced", "omitted", "inserted"}
            )
            self.assertGreaterEqual(word["confidence"], 0.0)
            self.assertLessEqual(word["confidence"], 1.0)
            self.assertLessEqual(word["startTime"], word["endTime"])

        # Must survive the trip to the Node server as JSON.
        json.dumps(result)

    def test_words_keep_their_passage_text_and_order(self):
        result = self.score(spread_preferences(self.target_ids, self.vocab["<pad>"]))
        self.assertEqual(
            [w["word"] for w in result["words"]], ["Ang", "bata", "ay", "masaya"]
        )

    def test_timestamps_increase_across_the_passage(self):
        result = self.score(spread_preferences(self.target_ids, self.vocab["<pad>"]))
        starts = [w["startTime"] for w in result["words"]]
        self.assertEqual(starts, sorted(starts))

    def test_per_phoneme_detail_is_reported(self):
        result = self.score(spread_preferences(self.target_ids, self.vocab["<pad>"]))
        bata = result["words"][1]
        self.assertEqual([p["phoneme"] for p in bata["phonemes"]], ["b", "a1", "t", "a"])
        for phoneme in bata["phonemes"]:
            self.assertIn("heard", phoneme)
            self.assertNotEqual(phoneme["heard"], "<pad>")
            self.assertNotIn(phoneme["heard"], {"<s>", "</s>", "|", "<unk>"})

    def test_uncalibrated_thresholds_are_declared_in_the_result(self):
        """A result produced with placeholder thresholds must say so - this is
        the guard against a tuned-looking number being trusted before
        calibrate.py has ever run."""
        result = self.score(
            spread_preferences(self.target_ids, self.vocab["<pad>"]),
            thresholds=PLACEHOLDER_THRESHOLDS,
        )
        self.assertFalse(result["calibration"]["calibrated"])
        self.assertIn("placeholder", result["calibration"]["provenance"])


class TestMispronunciationDetection(unittest.TestCase):
    PASSAGE = "Ang bata ay masaya"

    def setUp(self):
        self.dir = TemporaryDirectory()
        self.audio = write_wav(Path(self.dir.name) / "clip.wav", seconds=3.0)
        self.vocab = build_vocab()
        self.blank = self.vocab["<pad>"]
        self.target_ids, self.per_word = phoneme_ids_for(self.PASSAGE, self.vocab)

    def tearDown(self):
        self.dir.cleanup()

    def test_a_substituted_phoneme_flags_only_its_own_word(self):
        """'bata' is produced with /d/ where /b/ was expected. That word should
        be flagged and, just as importantly, its neighbours should not be."""
        substituted = list(self.target_ids)
        first_phoneme_of_bata = len(self.per_word[0])
        self.assertEqual(
            self.vocab["b"], substituted[first_phoneme_of_bata], "test fixture drifted"
        )
        substituted[first_phoneme_of_bata] = self.vocab["d"]

        model = FakeModel(spread_preferences(substituted, self.blank), self.vocab)
        result = score_passage(self.PASSAGE, self.audio, model, thresholds=PLACEHOLDER_THRESHOLDS)

        statuses = {w["word"]: w["status"] for w in result["words"]}
        self.assertEqual(statuses["bata"], "mispronounced")
        self.assertEqual(statuses["Ang"], "correct")
        self.assertEqual(statuses["ay"], "correct")
        self.assertEqual(statuses["masaya"], "correct")

    def test_the_flagged_phoneme_reports_what_was_heard_instead(self):
        substituted = list(self.target_ids)
        substituted[len(self.per_word[0])] = self.vocab["d"]

        model = FakeModel(spread_preferences(substituted, self.blank), self.vocab)
        result = score_passage(self.PASSAGE, self.audio, model, thresholds=PLACEHOLDER_THRESHOLDS)

        bata = next(w for w in result["words"] if w["word"] == "bata")
        b_phoneme = bata["phonemes"][0]
        self.assertEqual(b_phoneme["phoneme"], "b")
        self.assertEqual(b_phoneme["heard"], "d")
        self.assertLess(b_phoneme["gop"], 0.0)

    def test_a_crammed_word_is_reported_as_omitted(self):
        """A word the pupil skipped has nowhere to go: the aligner squeezes its
        phonemes into a few adjacent frames of a neighbour's audio. That
        cramming - not the low score alone - is what separates omitted from
        mispronounced."""
        blank = self.blank
        preferences = [blank]
        offset = 0
        for word_index, word_ids in enumerate(self.per_word):
            if word_index == 1:
                # 'bata' never spoken: no frames of its own, and what audio is
                # there looks like something else entirely.
                preferences.extend([self.vocab["s"]] * 2)
            else:
                for token_id in word_ids:
                    preferences.append(token_id)
                    preferences.extend([blank] * 3)
            offset += len(word_ids)

        model = FakeModel(preferences, self.vocab)
        result = score_passage(self.PASSAGE, self.audio, model, thresholds=PLACEHOLDER_THRESHOLDS)

        bata = next(w for w in result["words"] if w["word"] == "bata")
        self.assertEqual(bata["status"], "omitted")
        self.assertNotIn(
            "startTime", bata, "an omitted word has no audio position to seek to"
        )
        self.assertLessEqual(bata["extentPerPhoneme"], 1.5)


class TestScorePassageValidation(unittest.TestCase):
    def setUp(self):
        self.dir = TemporaryDirectory()
        self.audio = write_wav(Path(self.dir.name) / "clip.wav")

    def tearDown(self):
        self.dir.cleanup()

    def test_english_is_rejected_with_an_explanation(self):
        vocab = build_vocab()
        target_ids, _ = phoneme_ids_for("Ang bata", vocab)
        model = FakeModel(spread_preferences(target_ids, vocab["<pad>"]), vocab)

        with self.assertRaises(ValueError) as caught:
            score_passage("The quick brown fox", self.audio, model, language="en")
        self.assertIn("Filipino-only", str(caught.exception))

    def test_passage_with_no_pronounceable_words_is_rejected(self):
        vocab = build_vocab()
        model = FakeModel([vocab["<pad>"]] * 5, vocab)
        with self.assertRaises(ValueError):
            score_passage("... --- ...", self.audio, model)

    def test_punctuation_only_token_is_kept_but_never_flagged(self):
        """Index numbering has to stay aligned with the Node side's whitespace
        split, so an unscorable token still occupies its position."""
        passage = "Ang bata — masaya"
        vocab = build_vocab()
        target_ids, _ = phoneme_ids_for(passage, vocab)
        model = FakeModel(spread_preferences(target_ids, vocab["<pad>"]), vocab)

        result = score_passage(passage, self.audio, model, thresholds=PLACEHOLDER_THRESHOLDS)

        self.assertEqual(len(result["words"]), 4)
        dash = result["words"][2]
        self.assertEqual(dash["word"], "—")
        self.assertTrue(dash["unscorable"])
        self.assertEqual(dash["status"], "correct")
        self.assertEqual([w["index"] for w in result["words"]], [0, 1, 2, 3])


if __name__ == "__main__":
    unittest.main()

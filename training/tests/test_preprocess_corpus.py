import tempfile
import unittest
from pathlib import Path

import pandas as pd

import preprocess_corpus as pc


def _fake_audio():
    return {"bytes": b"\x00\x01\x02\x03", "path": "fake.wav"}


def _row(sentence="bahay", speech_type="read", duration=0.7, speaker_id="01", **overrides):
    row = {
        "audio": _fake_audio(),
        "sentence": sentence,
        "duration": duration,
        "num_words": len(sentence.split()),
        "speaker_id": speaker_id,
        "gender": "male",
        "age_group": "20-27",
        "speech_type": speech_type,
        "source_file": "fake_source",
    }
    row.update(overrides)
    return row


class IsJunkSentenceTest(unittest.TestCase):
    def test_real_sentence_is_not_junk(self):
        self.assertFalse(pc.is_junk_sentence("Ang bata ay masaya."))

    def test_nonfsc_sentinel_is_junk(self):
        self.assertTrue(pc.is_junk_sentence("nonfsc"))
        self.assertTrue(pc.is_junk_sentence("NONFSC"))  # case-insensitive

    def test_noise_sentinel_is_junk(self):
        self.assertTrue(pc.is_junk_sentence("NOISE"))

    def test_bracket_only_non_speech_events_are_junk(self):
        for s in ("[]", "[cough]", "[noise]", "[swallow]", "[ NOISE ]"):
            self.assertTrue(pc.is_junk_sentence(s), s)

    def test_curly_brace_disfluency_annotation_is_junk(self):
        self.assertTrue(pc.is_junk_sentence("{guspo} gusto ko pa rin"))

    def test_pure_punctuation_is_junk(self):
        for s in (".", "...", "  ", ""):
            self.assertTrue(pc.is_junk_sentence(s), s)

    def test_none_is_junk(self):
        self.assertTrue(pc.is_junk_sentence(None))

    def test_single_word_is_not_junk(self):
        self.assertFalse(pc.is_junk_sentence("q"))  # plausible letter-naming content


class RejectionReasonTest(unittest.TestCase):
    def test_machine_speech_rejected(self):
        self.assertEqual(pc.rejection_reason(_row(speech_type="machine")), "machine_speech")

    def test_nonpositive_duration_rejected(self):
        self.assertEqual(pc.rejection_reason(_row(duration=0)), "nonpositive_duration")
        self.assertEqual(pc.rejection_reason(_row(duration=-1)), "nonpositive_duration")

    def test_junk_sentence_rejected(self):
        self.assertEqual(pc.rejection_reason(_row(sentence="nonfsc")), "junk_sentence")

    def test_good_row_kept(self):
        self.assertIsNone(pc.rejection_reason(_row()))


class ComputePhonemeFieldsTest(unittest.TestCase):
    def test_basic_sentence(self):
        fields = pc.compute_phoneme_fields("Ang bata ay masaya.")
        self.assertEqual(len(fields["word_phonemes"]), 4)
        self.assertGreater(fields["phoneme_count"], 0)
        self.assertEqual(len(fields["phoneme_sequence"]), fields["phoneme_count"])

    def test_flat_sequence_matches_word_concatenation(self):
        fields = pc.compute_phoneme_fields("bahay aso")
        expected = [p for w in fields["word_phonemes"] for p in w["phonemes"]]
        self.assertEqual(fields["phoneme_sequence"], expected)


class AssignSplitTest(unittest.TestCase):
    def test_deterministic(self):
        for _ in range(5):
            self.assertEqual(pc.assign_split("speaker42", 0.05), pc.assign_split("speaker42", 0.05))

    def test_zero_fraction_never_val(self):
        for i in range(200):
            self.assertEqual(pc.assign_split(f"speaker{i}", 0.0), "train")

    def test_full_fraction_always_val(self):
        for i in range(200):
            self.assertEqual(pc.assign_split(f"speaker{i}", 1.0), "val")

    def test_roughly_matches_requested_fraction(self):
        val_count = sum(1 for i in range(5000) if pc.assign_split(f"speaker{i}", 0.05) == "val")
        # statistical, not exact - generous tolerance
        self.assertTrue(200 < val_count < 350, val_count)


class ShardProcessingTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_shard(self, rows, name="shard.parquet"):
        path = self.tmp_path / name
        pd.DataFrame(rows).to_parquet(path, index=False)
        return path

    def test_train_shard_filters_and_splits(self):
        rows = [
            _row(sentence="bahay", speaker_id="alpha"),
            _row(sentence="nonfsc", speaker_id="alpha"),          # junk -> rejected
            _row(sentence="unahan", speech_type="machine", speaker_id="beta"),  # machine -> rejected
            _row(sentence="aso", duration=0, speaker_id="gamma"),  # bad duration -> rejected
            _row(sentence="puso", speaker_id="delta"),
        ]
        path = self._write_shard(rows)
        stats = pc.new_stats()
        train_df, val_df = pc.process_train_shard(path, val_fraction=0.0, stats=stats)

        self.assertEqual(stats["total"], 5)
        self.assertEqual(stats["rejected"]["junk_sentence"], 1)
        self.assertEqual(stats["rejected"]["machine_speech"], 1)
        self.assertEqual(stats["rejected"]["nonpositive_duration"], 1)
        # 2 good rows, val_fraction=0.0 -> all go to train
        self.assertEqual(len(train_df) + len(val_df), 2)
        self.assertEqual(len(val_df), 0)
        self.assertIn("phoneme_sequence", train_df.columns)
        self.assertIn("word_phonemes", train_df.columns)
        self.assertIn("phoneme_count", train_df.columns)

    def test_train_shard_all_val(self):
        rows = [_row(sentence="bahay", speaker_id="x"), _row(sentence="aso", speaker_id="y")]
        path = self._write_shard(rows)
        stats = pc.new_stats()
        train_df, val_df = pc.process_train_shard(path, val_fraction=1.0, stats=stats)
        self.assertEqual(len(train_df), 0)
        self.assertEqual(len(val_df), 2)

    def test_test_shard(self):
        rows = [_row(sentence="bahay"), _row(sentence="[noise]")]
        path = self._write_shard(rows)
        stats = pc.new_stats()
        test_df = pc.process_test_shard(path, stats)
        self.assertEqual(len(test_df), 1)
        self.assertEqual(stats["kept"]["test"], 1)
        self.assertEqual(stats["rejected"]["junk_sentence"], 1)

    def test_shard_with_no_surviving_rows_is_empty_but_not_an_error(self):
        rows = [_row(sentence="nonfsc"), _row(sentence="[]")]
        path = self._write_shard(rows)
        stats = pc.new_stats()
        train_df, val_df = pc.process_train_shard(path, val_fraction=0.05, stats=stats)
        self.assertTrue(train_df.empty)
        self.assertTrue(val_df.empty)


class WriteChunkedTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_chunks_respect_row_limit(self):
        df = pd.DataFrame({"x": range(25)})
        pc._write_chunked(df, self.tmp_path, "val", chunk_rows=10)
        written = sorted(self.tmp_path.glob("val-*.parquet"))
        self.assertEqual(len(written), 3)
        total_rows = sum(len(pd.read_parquet(p)) for p in written)
        self.assertEqual(total_rows, 25)

    def test_empty_dataframe_writes_nothing(self):
        df = pd.DataFrame({"x": []})
        pc._write_chunked(df, self.tmp_path, "val", chunk_rows=10)
        self.assertEqual(list(self.tmp_path.glob("val-*.parquet")), [])


if __name__ == "__main__":
    unittest.main()

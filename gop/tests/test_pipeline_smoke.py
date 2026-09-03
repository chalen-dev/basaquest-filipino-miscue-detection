"""End-to-end smoke test over a real (but tiny, randomly-initialised) model.

The other test files stub the acoustic model out, which keeps them fast and
focused but leaves `acoustic.py` - model loading, the feature extractor,
windowed inference - entirely unexercised. This file closes that gap by
building a real `Wav2Vec2ForCTC` with the genuine vocabulary layout (38 CTC
outputs, blank at 35, the tokenizer's `<s>`/`</s>` at 36-37) at a fraction of
the size, then running the whole pipeline through torch.

**The weights are random, so every GOP value here is meaningless.** This
asserts that the pipeline *runs and stays self-consistent*, never that it
scores speech correctly - that question needs the real Phase 3 checkpoint and
real recordings, and is Phase 5's job.

It earns its keep: it caught a uint8 overflow in the aligner's backtrack that
every unit test missed, because the bug only appears past 255 extended states
and a real passage is ~450 phonemes. See test_ctc_align's
`test_passage_length_sequence`.
"""

import sys
import unittest
import wave
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from basaquest_gop.config import PLACEHOLDER_THRESHOLDS
from basaquest_gop.g2p_bridge import phoneme_inventory

try:
    import torch  # noqa: F401

    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

# Long enough to force several windows at the 20s/4s default.
AUDIO_SECONDS = 47.0
SAMPLE_RATE = 16000

# Roughly the length of the app's real Filipino passage, so the aligner is
# exercised at a realistic state count rather than a toy one.
PASSAGE = (
    "Noong unang panahon, sa lupaing tinatawag ngayong Davao, may isang matapang "
    "na pinuno na nagngangalang Datu Bago na mahusay na namuno sa kanyang mga tao. "
    "Tinanggap niya ang mga mangangalakal na dumating sa pamamagitan ng bangka at "
    "tinulungan ang kanyang komunidad na lumago."
)


def build_tiny_model(directory: Path) -> Path:
    """A 2-layer wav2vec2 with the real vocab and the real conv strides."""
    import json

    from transformers import (
        Wav2Vec2Config,
        Wav2Vec2FeatureExtractor,
        Wav2Vec2ForCTC,
        Wav2Vec2PhonemeCTCTokenizer,
        Wav2Vec2Processor,
    )

    model_dir = directory / "tiny-model"
    model_dir.mkdir(parents=True)

    vocab = {p: i for i, p in enumerate(phoneme_inventory())}
    vocab["|"] = len(vocab)
    vocab["<unk>"] = len(vocab)
    vocab["<pad>"] = len(vocab)
    (model_dir / "vocab.json").write_text(json.dumps(vocab), encoding="utf-8")

    tokenizer = Wav2Vec2PhonemeCTCTokenizer(
        str(model_dir / "vocab.json"),
        unk_token="<unk>",
        pad_token="<pad>",
        word_delimiter_token="|",
        do_phonemize=False,
    )
    feature_extractor = Wav2Vec2FeatureExtractor(
        feature_size=1,
        sampling_rate=SAMPLE_RATE,
        padding_value=0.0,
        do_normalize=True,
        return_attention_mask=True,
    )
    processor = Wav2Vec2Processor(feature_extractor=feature_extractor, tokenizer=tokenizer)

    config = Wav2Vec2Config(
        # len(tokenizer), not len(vocab) - this reproduces exactly what Phase 3
        # did, including the two extra special tokens it pulled into the head.
        vocab_size=len(tokenizer),
        hidden_size=64,
        num_hidden_layers=2,
        num_attention_heads=2,
        intermediate_size=128,
        conv_dim=(64,) * 7,
        conv_kernel=(10, 3, 3, 3, 3, 2, 2),
        conv_stride=(5, 2, 2, 2, 2, 2, 2),
        pad_token_id=tokenizer.pad_token_id,
        ctc_loss_reduction="mean",
    )
    Wav2Vec2ForCTC(config).save_pretrained(model_dir)
    processor.save_pretrained(model_dir)
    return model_dir


def write_wav(path: Path, seconds: float) -> Path:
    n = int(SAMPLE_RATE * seconds)
    rng = np.random.default_rng(0)
    samples = (rng.normal(0, 2000, n)).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(samples.tobytes())
    return path


@unittest.skipUnless(TORCH_AVAILABLE, "torch not installed")
class TestPipelineSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from basaquest_gop import PhonemeAcousticModel

        cls.dir = TemporaryDirectory()
        root = Path(cls.dir.name)
        cls.model_dir = build_tiny_model(root)
        cls.audio = write_wav(root / "clip.wav", AUDIO_SECONDS)
        cls.model = PhonemeAcousticModel(cls.model_dir)

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def test_vocabulary_wiring_matches_phase_3(self):
        self.assertEqual(self.model.blank_id, 35)
        self.assertEqual(len(self.model.competitor_ids), 33)
        # The two tokens the tokenizer appends were never trained on any
        # target, so they must not be able to win as a "best competitor".
        self.assertNotIn(36, self.model.competitor_ids)
        self.assertNotIn(37, self.model.competitor_ids)
        self.assertNotIn(self.model.blank_id, self.model.competitor_ids)

    def test_frame_rate_is_50hz(self):
        self.assertAlmostEqual(self.model.seconds_per_frame, 0.02)

    def test_windowed_inference_matches_a_single_pass(self):
        """The claim windowing rests on: splitting the input must not move a
        single frame. Frame *counts* must match exactly - a drift here would
        silently shift every timestamp and corrupt the alignment.

        The per-frame values are only near-equal, not identical, and that is
        inherent rather than a defect: a frame near a window edge sees less
        audio context through self-attention than it would in a single pass.
        """
        from basaquest_gop.audio import load_audio

        waveform = load_audio(self.audio)
        single = self.model.log_probs(waveform, window_seconds=None)
        windowed = self.model.log_probs(waveform, window_seconds=20.0, overlap_seconds=4.0)

        self.assertEqual(single.shape, windowed.shape)
        self.assertGreater(single.shape[0], 2000, "47s should give ~2350 frames")
        self.assertLess(float(np.abs(single - windowed).max()), 0.5)

    def test_scores_a_full_length_passage(self):
        """The case that broke: ~450 phonemes over ~2350 frames."""
        from basaquest_gop import score_passage

        result = score_passage(
            PASSAGE, self.audio, self.model, thresholds=PLACEHOLDER_THRESHOLDS
        )

        expected_words = len(PASSAGE.split())
        self.assertEqual(len(result["words"]), expected_words)
        self.assertEqual(result["engine"], "gop-local")
        self.assertEqual(result["durationSeconds"], round(AUDIO_SECONDS))
        self.assertFalse(result["calibration"]["calibrated"])

        for word in result["words"]:
            if word.get("unscorable"):
                continue
            self.assertIn(word["status"], {"correct", "mispronounced", "omitted"})
            for phoneme in word["phonemes"]:
                self.assertTrue(np.isfinite(phoneme["gop"]), "GOP must never be NaN")

    def test_timestamps_stay_ordered_and_inside_the_recording(self):
        from basaquest_gop import score_passage

        result = score_passage(
            PASSAGE, self.audio, self.model, thresholds=PLACEHOLDER_THRESHOLDS
        )
        timed = [w for w in result["words"] if "startTime" in w]

        previous = -1.0
        for word in timed:
            self.assertGreaterEqual(word["startTime"], previous)
            self.assertLessEqual(word["endTime"], AUDIO_SECONDS + 1)
            previous = word["startTime"]


if __name__ == "__main__":
    unittest.main()

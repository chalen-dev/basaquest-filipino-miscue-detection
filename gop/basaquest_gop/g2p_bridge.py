"""Access to Phase 1's G2P, which lives in a sibling top-level package.

`g2p/filipino_g2p` isn't installed into the environment - the Phase 3
notebook reaches it by path manipulation too (its `G2P_DIR`). Centralising
that here keeps the sys.path poke in one place instead of in every module
that needs a phoneme.
"""

from __future__ import annotations

import sys
from pathlib import Path

_G2P_DIR = Path(__file__).resolve().parents[2] / "g2p"


def _ensure_importable() -> None:
    if str(_G2P_DIR) not in sys.path:
        if not _G2P_DIR.exists():
            raise FileNotFoundError(f"Phase 1 G2P package not found at {_G2P_DIR}")
        sys.path.insert(0, str(_G2P_DIR))


def text_to_phonemes(text: str):
    _ensure_importable()
    from filipino_g2p import text_to_phonemes as _impl

    return _impl(text)


def phoneme_inventory() -> list[str]:
    """The 33 symbols G2P can actually emit.

    This is the authoritative list of "things a pupil could have pronounced,"
    and it is deliberately *not* the same as the model's output vocabulary.
    Phase 3 built the CTC head with `vocab_size=len(processor.tokenizer)`, and
    `Wav2Vec2PhonemeCTCTokenizer` quietly appends `<s>` and `</s>` on top of
    the 36 entries written to vocab.json - so the head has 38 outputs, two of
    which are special tokens that never appeared in any training target. Left
    in the competitor set they would be untrained logits competing to explain
    a pupil's speech, which is meaningless. Deriving the set from the G2P
    inventory excludes them by construction, along with blank, <unk> and the
    word delimiter.
    """
    _ensure_importable()
    from filipino_g2p import full_vocabulary

    return list(full_vocabulary())

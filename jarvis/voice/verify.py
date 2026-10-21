"""
Speaker verification using resemblyzer.
Enroll once with `jarvis enroll`, then every captured audio is checked
before being sent to Claude.
"""
from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Optional

import numpy as np

log = logging.getLogger("jarvis.verify")

_PROFILE_PATH = Path.home() / ".local" / "share" / "jarvis" / "voiceprint.pkl"
_SAMPLE_RATE  = 16000
_THRESHOLD    = 0.75   # cosine similarity — tune if needed


def _encoder():
    from resemblyzer import VoiceEncoder
    return VoiceEncoder()


def enroll(wav: np.ndarray, profile_path: Path = _PROFILE_PATH) -> None:
    """Save a voiceprint from a numpy audio array (float32, 16kHz mono)."""
    enc = _encoder()
    embedding = enc.embed_utterance(wav)
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    with open(profile_path, "wb") as f:
        pickle.dump(embedding, f)
    log.info("Voiceprint saved to %s", profile_path)


def load_voiceprint(profile_path: Path = _PROFILE_PATH) -> Optional[np.ndarray]:
    if not profile_path.exists():
        return None
    with open(profile_path, "rb") as f:
        return pickle.load(f)


def verify(wav: np.ndarray, profile_path: Path = _PROFILE_PATH) -> tuple[bool, float]:
    """
    Returns (is_owner, similarity_score).
    If no voiceprint is enrolled, always returns (True, 1.0) — open access.
    """
    voiceprint = load_voiceprint(profile_path)
    if voiceprint is None:
        return True, 1.0

    enc = _encoder()
    embedding = enc.embed_utterance(wav)

    # cosine similarity
    similarity = float(
        np.dot(voiceprint, embedding)
        / (np.linalg.norm(voiceprint) * np.linalg.norm(embedding) + 1e-9)
    )
    accepted = similarity >= _THRESHOLD
    log.debug("Speaker similarity=%.3f threshold=%.3f accepted=%s",
              similarity, _THRESHOLD, accepted)
    return accepted, similarity

"""
Speaker verification — lightweight MFCC cosine similarity.
No heavy deps (no torch, no webrtcvad). Works on Python 3.14.

Enroll once with `jarvis enroll`, then every captured audio is verified.
If no voiceprint enrolled, all voices are accepted.
"""
from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Optional

import numpy as np

log = logging.getLogger("jarvis.verify")

_PROFILE_PATH = Path.home() / ".local" / "share" / "jarvis" / "voiceprint.pkl"
_THRESHOLD    = 0.82   # cosine similarity; tune after enrolling
_N_MFCC       = 20
_FRAME_SIZE   = 512
_HOP_SIZE     = 256
_SAMPLE_RATE  = 16000


def _mfcc_embedding(wav: np.ndarray) -> np.ndarray:
    """Compute a compact voice embedding via DCT on log mel filterbank."""
    # Pre-emphasis
    pre = np.append(wav[0], wav[1:] - 0.97 * wav[:-1])

    # Frame the signal
    frames = []
    for i in range(0, len(pre) - _FRAME_SIZE, _HOP_SIZE):
        frames.append(pre[i:i + _FRAME_SIZE] * np.hamming(_FRAME_SIZE))
    if not frames:
        return np.zeros(_N_MFCC)

    frames = np.array(frames)  # (n_frames, frame_size)

    # Power spectrum
    mag = np.abs(np.fft.rfft(frames, n=_FRAME_SIZE)) ** 2

    # Mel filterbank (26 filters)
    n_filters = 26
    n_fft = _FRAME_SIZE // 2 + 1
    low_hz, high_hz = 80, min(8000, _SAMPLE_RATE // 2)

    def hz_to_mel(h): return 2595 * np.log10(1 + h / 700)
    def mel_to_hz(m): return 700 * (10 ** (m / 2595) - 1)

    mel_pts = np.linspace(hz_to_mel(low_hz), hz_to_mel(high_hz), n_filters + 2)
    hz_pts  = mel_to_hz(mel_pts)
    bins    = np.floor(hz_pts / (_SAMPLE_RATE / _FRAME_SIZE)).astype(int)
    bins    = np.clip(bins, 0, n_fft - 1)

    fbank = np.zeros((n_filters, n_fft))
    for m in range(1, n_filters + 1):
        lo, center, hi = bins[m-1], bins[m], bins[m+1]
        for k in range(lo, center):
            if center != lo:
                fbank[m-1, k] = (k - lo) / (center - lo)
        for k in range(center, hi):
            if hi != center:
                fbank[m-1, k] = (hi - k) / (hi - center)

    log_fbank = np.log(mag @ fbank.T + 1e-9)  # (n_frames, n_filters)

    # DCT to get MFCCs
    n = np.arange(_N_MFCC)
    lift = 1 + (_N_MFCC / 2) * np.sin(np.pi * n / _N_MFCC)
    mfcc = np.zeros((len(log_fbank), _N_MFCC))
    for i in range(_N_MFCC):
        mfcc[:, i] = np.sum(log_fbank * np.cos(np.pi * i / n_filters *
                            (np.arange(n_filters) + 0.5)), axis=1)
    mfcc *= lift

    # Mean + std over time → fixed-size embedding
    return np.concatenate([mfcc.mean(axis=0), mfcc.std(axis=0)])


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def enroll(wav: np.ndarray, profile_path: Path = _PROFILE_PATH) -> None:
    embedding = _mfcc_embedding(wav)
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
    """Returns (is_owner, similarity). No voiceprint → always True."""
    voiceprint = load_voiceprint(profile_path)
    if voiceprint is None:
        return True, 1.0
    embedding   = _mfcc_embedding(wav)
    similarity  = _cosine(voiceprint, embedding)
    accepted    = similarity >= _THRESHOLD
    log.debug("Speaker similarity=%.3f accepted=%s", similarity, accepted)
    return accepted, similarity

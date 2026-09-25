"""Shared fixtures: ffmpeg detection + tiny test-tone generator."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FFMPEG = shutil.which("ffmpeg")

needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not on PATH")


def make_tone(path: Path, volume_db: float = 0.0, duration: float = 0.5) -> Path:
    """Generate a short 440 Hz sine WAV at a known peak level.

    `aevalsrc` produces a full-scale sine (peak ~= 0 dBFS), so `volume_db`
    shifts the peak predictably (e.g. volume_db=-12 -> peak == -12 dBFS).
    """
    assert FFMPEG is not None, "ffmpeg is required to generate test tones"
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        FFMPEG, "-y",
        "-f", "lavfi", "-i",
        f"aevalsrc=sin(2*PI*440*t):s=44100:d={duration}",
        "-af", f"volume={volume_db}dB",
        "-c:a", "pcm_s16le",
        str(path),
    ]
    subprocess.run(cmd, capture_output=True, check=True, timeout=60)
    return path

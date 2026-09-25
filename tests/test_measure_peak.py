"""Peak measurement tests (real ffmpeg via generated tones)."""
from __future__ import annotations

from pathlib import Path

import pytest

from normalizer import get_stream_info, measure_peak_db

from .conftest import make_tone, needs_ffmpeg


@needs_ffmpeg
def test_measure_peak_of_generated_tone(tmp_path: Path):
    tone = make_tone(tmp_path / "tone.wav", volume_db=-12.0)
    peak = measure_peak_db(tone)
    assert peak is not None
    assert peak == pytest.approx(-12.0, abs=0.3)


@needs_ffmpeg
def test_measure_peak_full_scale_tone(tmp_path: Path):
    tone = make_tone(tmp_path / "loud.wav", volume_db=0.0)
    peak = measure_peak_db(tone)
    assert peak is not None
    assert peak == pytest.approx(0.0, abs=0.3)


def test_measure_peak_missing_file_returns_none(tmp_path: Path):
    assert measure_peak_db(tmp_path / "nope.wav") is None


def test_measure_peak_non_audio_returns_none(tmp_path: Path):
    text = tmp_path / "notes.txt"
    text.write_text("hello")
    assert measure_peak_db(text) is None


@needs_ffmpeg
def test_get_stream_info_of_tone(tmp_path: Path):
    tone = make_tone(tmp_path / "tone.wav")
    stream = get_stream_info(tone)
    assert stream is not None
    assert stream.get("codec_type") == "audio"
    assert stream.get("codec_name") == "pcm_s16le"


def test_get_stream_info_missing_returns_none(tmp_path: Path):
    assert get_stream_info(tmp_path / "nope.wav") is None

"""End-to-end normalize_file tests with generated tones (real ffmpeg)."""
from __future__ import annotations

from pathlib import Path

import pytest

from normalizer import SKIP_SUFFIX, measure_peak_db, normalize_file

from .conftest import make_tone, needs_ffmpeg


def test_missing_input_fails(tmp_path: Path):
    result = normalize_file(tmp_path / "ghost.wav")
    assert result.success is False
    assert "not found" in (result.error or "").lower()


def test_already_suffixed_file_skipped(tmp_path: Path):
    src = tmp_path / f"clip{SKIP_SUFFIX}.wav"
    src.write_bytes(b"x")
    result = normalize_file(src)
    assert result.success is True
    assert result.action == "skipped_suffix"
    assert result.output_path is None


def test_unsupported_file_fails(tmp_path: Path):
    text = tmp_path / "notes.txt"
    text.write_text("hello")
    result = normalize_file(text)
    assert result.success is False
    assert result.error


@needs_ffmpeg
def test_quiet_tone_gets_normalized_to_target(tmp_path: Path):
    src = make_tone(tmp_path / "quiet.wav", volume_db=-12.0)
    result = normalize_file(src, target_db=-1.0, tolerance_db=0.5)
    assert result.success is True
    assert result.action == "normalized"
    assert result.gain_db == pytest.approx(11.0, abs=0.3)
    assert result.output_path is not None
    assert result.output_path.exists()
    assert result.output_path.name == f"quiet{SKIP_SUFFIX}.wav"
    # Source is kept in copy mode.
    assert src.exists()
    # Output peak lands on the target.
    assert measure_peak_db(result.output_path) == pytest.approx(-1.0, abs=0.3)


@needs_ffmpeg
def test_tone_within_tolerance_is_skipped(tmp_path: Path):
    src = make_tone(tmp_path / "close.wav", volume_db=-1.2)
    result = normalize_file(src, target_db=-1.0, tolerance_db=0.5)
    assert result.success is True
    assert result.action == "skipped_range"
    assert result.output_path is None
    # No output file was written.
    assert list(tmp_path.glob(f"*{SKIP_SUFFIX}.wav")) == []


@needs_ffmpeg
def test_tone_just_outside_tolerance_gets_normalized(tmp_path: Path):
    # gain ~= 1.0 dB > tolerance 0.5 -> normalized, not skipped.
    src = make_tone(tmp_path / "outside.wav", volume_db=-2.0)
    result = normalize_file(src, target_db=-1.0, tolerance_db=0.5)
    assert result.success is True
    assert result.action == "normalized"
    assert result.gain_db == pytest.approx(1.0, abs=0.3)


@needs_ffmpeg
def test_output_dir_and_replace_mode(tmp_path: Path):
    src = make_tone(tmp_path / "work" / "take.wav", volume_db=-10.0)
    out = tmp_path / "out"
    result = normalize_file(src, target_db=-1.0, output_dir=out)
    assert result.success is True
    assert result.output_path == out / f"take{SKIP_SUFFIX}.wav"
    assert result.output_path.exists()

    # Replace mode next to the source deletes the original.
    src2 = make_tone(tmp_path / "work2" / "take.wav", volume_db=-10.0)
    result2 = normalize_file(src2, target_db=-1.0, mode="replace")
    assert result2.success is True
    assert result2.output_path is not None and result2.output_path.exists()
    assert not src2.exists()


@needs_ffmpeg
def test_loud_tone_gets_turned_down(tmp_path: Path):
    src = make_tone(tmp_path / "loud.wav", volume_db=0.0)
    result = normalize_file(src, target_db=-3.0, tolerance_db=0.1)
    assert result.success is True
    assert result.gain_db == pytest.approx(-3.0, abs=0.3)
    assert measure_peak_db(result.output_path) == pytest.approx(-3.0, abs=0.3)

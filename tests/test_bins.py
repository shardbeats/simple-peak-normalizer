"""Tests for binary resolution and NormalizeResult defaults."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

import normalizer
from normalizer import (
    NormalizeResult,
    build_normalize_cmd,
    check_ffmpeg,
    ffmpeg_bin,
    ffprobe_bin,
)

from .conftest import needs_ffmpeg


def test_result_defaults():
    result = NormalizeResult(True, Path("a.wav"))
    assert result.success is True
    assert result.output_path is None
    assert result.gain_db == 0.0
    assert result.action == "normalized"
    assert result.error is None


def test_bins_fall_back_to_path(monkeypatch):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert ffmpeg_bin() == "ffmpeg"
    assert ffprobe_bin() == "ffprobe"


def test_bins_use_bundled_when_present(tmp_path: Path, monkeypatch):
    bundled = tmp_path / "ffmpeg.exe"
    bundled.write_bytes(b"x")
    (tmp_path / "ffprobe.exe").write_bytes(b"x")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert ffmpeg_bin() == str(bundled)
    assert ffprobe_bin() == str(tmp_path / "ffprobe.exe")


def test_bins_ignore_empty_bundle_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert ffmpeg_bin() == "ffmpeg"


def test_check_ffmpeg_false_when_binary_missing(monkeypatch):
    monkeypatch.setattr(normalizer, "ffmpeg_bin", lambda: "definitely-not-a-real-binary")
    assert check_ffmpeg() is False


@needs_ffmpeg
def test_check_ffmpeg_true_with_real_binary():
    assert check_ffmpeg() is True


def test_build_normalize_cmd_structure(tmp_path: Path):
    src = tmp_path / "in.wav"
    dst = tmp_path / "in_N.wav"
    cmd = build_normalize_cmd(src, dst, 3.5, ["-c:a", "pcm_s16le"])
    assert cmd[0] == ffmpeg_bin()
    assert "-y" in cmd
    assert cmd[cmd.index("-i") + 1] == str(src)
    assert cmd[cmd.index("-af") + 1] == "volume=3.500dB"
    assert cmd[-1] == str(dst)
    # Sample rate is intentionally not forced (preserved from source).
    assert "-ar" not in cmd

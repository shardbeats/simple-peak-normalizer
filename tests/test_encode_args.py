"""Tests for encode_args: codec/bit-depth preservation matrix (no ffmpeg needed)."""
from __future__ import annotations

import pytest

from normalizer import encode_args


@pytest.mark.parametrize("codec,ext,expected", [
    ("pcm_s16le", ".wav", (".wav", ["-c:a", "pcm_s16le"])),
    ("pcm_s16be", ".aiff", (".aiff", ["-c:a", "pcm_s16be"])),
    ("pcm_s16le", ".aiff", (".aiff", ["-c:a", "pcm_s16be"])),
    ("pcm_s24le", ".wav", (".wav", ["-c:a", "pcm_s24le"])),
    ("pcm_s24be", ".aif", (".aiff", ["-c:a", "pcm_s24be"])),
    ("pcm_s32le", ".wav", (".wav", ["-c:a", "pcm_s32le"])),
    ("pcm_s32be", ".wav", (".wav", ["-c:a", "pcm_s32le"])),
    ("pcm_f32le", ".wav", (".wav", ["-c:a", "pcm_f32le"])),
    ("pcm_f64le", ".wav", (".wav", ["-c:a", "pcm_f64le"])),
])
def test_lossless_pcm_preserved(codec, ext, expected):
    assert encode_args({"codec_name": codec}, ext) == expected


def test_flac_16bit_and_24bit():
    assert encode_args({"codec_name": "flac", "bits_per_raw_sample": 16}, ".flac") == (
        ".flac", ["-c:a", "flac", "-sample_fmt", "s16"])
    assert encode_args({"codec_name": "flac", "bits_per_raw_sample": 24}, ".flac") == (
        ".flac", ["-c:a", "flac", "-sample_fmt", "s32"])
    # Unknown depth defaults to 16-bit.
    assert encode_args({"codec_name": "flac"}, ".flac") == (
        ".flac", ["-c:a", "flac", "-sample_fmt", "s16"])


@pytest.mark.parametrize("codec", ["mp3", "aac", "vorbis", "opus", "", "unknown-codec"])
def test_lossy_or_unknown_falls_back_to_wav(codec):
    assert encode_args({"codec_name": codec}, ".mp3") == (
        ".wav", ["-c:a", "pcm_s16le"])

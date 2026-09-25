"""Tests for output-path resolution (pure logic, no ffmpeg needed)."""
from __future__ import annotations

from pathlib import Path

from normalizer import SKIP_SUFFIX, compute_output_path, resolve_output_base


def test_default_writes_next_to_source(tmp_path: Path):
    src = tmp_path / "pack" / "clip.wav"
    assert resolve_output_base(src) == src.parent


def test_output_dir_flat(tmp_path: Path):
    src = tmp_path / "pack" / "clip.wav"
    out = tmp_path / "out"
    assert resolve_output_base(src, output_dir=out) == out
    final = compute_output_path(src, output_dir=out, ext=".wav")
    assert final == out / f"clip{SKIP_SUFFIX}.wav"


def test_preserve_structure_with_output_dir(tmp_path: Path):
    root = tmp_path / "pack"
    src = root / "sub" / "clip.wav"
    out = tmp_path / "out"
    base = resolve_output_base(src, output_dir=out, source_root=root, preserve_structure=True)
    assert base == out / f"pack{SKIP_SUFFIX}"
    final = compute_output_path(src, output_dir=out, source_root=root,
                                preserve_structure=True, ext=".wav")
    assert final == out / f"pack{SKIP_SUFFIX}" / "sub" / f"clip{SKIP_SUFFIX}.wav"


def test_preserve_structure_next_to_source(tmp_path: Path):
    root = tmp_path / "pack"
    src = root / "sub" / "clip.wav"
    base = resolve_output_base(src, source_root=root, preserve_structure=True)
    assert base == tmp_path / f"pack{SKIP_SUFFIX}"
    final = compute_output_path(src, source_root=root, preserve_structure=True, ext=".flac")
    assert final == tmp_path / f"pack{SKIP_SUFFIX}" / "sub" / f"clip{SKIP_SUFFIX}.flac"


def test_preserve_structure_without_root_falls_back(tmp_path: Path):
    src = tmp_path / "clip.wav"
    assert resolve_output_base(src, preserve_structure=True) == src.parent
    final = compute_output_path(src, preserve_structure=True, ext=".wav")
    assert final == tmp_path / f"clip{SKIP_SUFFIX}.wav"


def test_file_outside_root_keeps_flat_name(tmp_path: Path):
    root = tmp_path / "pack"
    elsewhere = tmp_path / "other" / "clip.wav"
    final = compute_output_path(elsewhere, source_root=root,
                                preserve_structure=True, ext=".wav")
    assert final == root.parent / f"pack{SKIP_SUFFIX}" / f"clip{SKIP_SUFFIX}.wav"


def test_custom_suffix_and_ext(tmp_path: Path):
    src = tmp_path / "clip.wav"
    final = compute_output_path(src, suffix="_TEST", ext=".mp3")
    assert final == tmp_path / "clip_TEST.mp3"

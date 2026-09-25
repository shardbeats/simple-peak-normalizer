"""Tests for audio file discovery (no ffmpeg needed)."""
from __future__ import annotations

from pathlib import Path

from normalizer import SUPPORTED_EXTENSIONS, find_audio_files


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return path


def test_finds_supported_recursively(tmp_path: Path):
    _touch(tmp_path / "a.wav")
    _touch(tmp_path / "sub" / "b.mp3")
    _touch(tmp_path / "sub" / "deep" / "c.flac")
    found = find_audio_files(tmp_path)
    assert len(found) == 3
    assert found == sorted(found)


def test_uppercase_extensions_found(tmp_path: Path):
    _touch(tmp_path / "CLIP.WAV")
    _touch(tmp_path / "song.MP3")
    assert len(find_audio_files(tmp_path)) == 2


def test_unsupported_ignored(tmp_path: Path):
    _touch(tmp_path / "notes.txt")
    _touch(tmp_path / "cover.jpg")
    _touch(tmp_path / "clip.wav")
    found = find_audio_files(tmp_path)
    assert found == [tmp_path / "clip.wav"]


def test_non_recursive_only_top_level(tmp_path: Path):
    _touch(tmp_path / "top.wav")
    _touch(tmp_path / "sub" / "nested.wav")
    found = find_audio_files(tmp_path, recursive=False)
    assert found == [tmp_path / "top.wav"]


def test_empty_folder(tmp_path: Path):
    assert find_audio_files(tmp_path) == []


def test_supported_set_covers_readme_formats():
    for ext in (".wav", ".mp3", ".flac", ".aiff", ".ogg", ".m4a"):
        assert ext in SUPPORTED_EXTENSIONS

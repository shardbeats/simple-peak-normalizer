"""Peak Normalizer

- FFmpeg/ffprobe helpers (ffmpeg_bin / ffprobe_bin / check_ffmpeg)
- Audio file discovery (find_audio_files)
- Peak normalization logic (measure_peak_db / normalize_file)

Every audio clip is normalized to its own peak level: we measure the peak
of the file, compute the linear gain needed to bring that peak to the
target level, and apply it with a plain volume filter (no dynamic
compression, so dynamics stay untouched).

The sample rate and bit depth of the source are preserved whenever the
source is a lossless PCM/FLAC format. Lossy sources (mp3, ogg, ...) are
re-encoded to WAV to avoid a second generation loss.
"""

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Hide ffmpeg/ffprobe console window on Windows (no visible cmd window).
NO_WINDOW_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

# Files that already carry this suffix are considered processed and skipped.
SKIP_SUFFIX = "_N"

# Files quieter than this (dBFS) are treated as silent and not normalized.
SILENCE_FLOOR_DB = -90.0

SUPPORTED_EXTENSIONS = {
    ".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac",
    ".aiff", ".aif", ".wma", ".opus", ".webm",
}


@dataclass
class NormalizeResult:
    success: bool
    input_path: Path
    output_path: Optional[Path] = None
    gain_db: float = 0.0
    action: str = "normalized"  # normalized | skipped_suffix | skipped_range | failed
    error: Optional[str] = None


def ffmpeg_bin() -> str:
    """Path to the ffmpeg binary.

    In a PyInstaller build the binaries are bundled via --add-binary and
    extracted next to the app (sys._MEIPASS); otherwise fall back to PATH.
    """
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidate = Path(base) / "ffmpeg.exe"
        if candidate.exists():
            return str(candidate)
    return "ffmpeg"


def ffprobe_bin() -> str:
    """Path to the ffprobe binary (same logic as ffmpeg_bin)."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidate = Path(base) / "ffprobe.exe"
        if candidate.exists():
            return str(candidate)
    return "ffprobe"


def check_ffmpeg() -> bool:
    """Verify ffmpeg is available (bundled or in PATH)."""
    try:
        subprocess.run([ffmpeg_bin(), "-version"], capture_output=True, check=True,
                       creationflags=NO_WINDOW_FLAGS)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def find_audio_files(folder: Path, recursive: bool = True) -> list[Path]:
    """Find all supported audio files in a folder."""
    pattern = "**/*" if recursive else "*"
    files = []
    for ext in SUPPORTED_EXTENSIONS:
        files.extend(folder.glob(f"{pattern}{ext}"))
        files.extend(folder.glob(f"{pattern}{ext.upper()}"))
    return sorted(set(files))


def _null_output() -> str:
    """ffmpeg null output name (NUL on Windows, /dev/null elsewhere)."""
    return "NUL" if os.name == "nt" else "/dev/null"


def get_stream_info(file_path: Path) -> Optional[dict]:
    """Extract the audio stream metadata from ffprobe (raw dict)."""
    cmd = [
        ffprobe_bin(), "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        str(file_path),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=True,
            creationflags=NO_WINDOW_FLAGS,
        )
        data = json.loads(result.stdout)
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "audio":
                return stream
    except Exception:
        pass
    return None


def measure_peak_db(file_path: Path) -> Optional[float]:
    """Measure the peak level (dBFS) of a file using ffmpeg volumedetect.

    Returns None when the file can't be analyzed (missing, unsupported,
    silent, or ffmpeg error).
    """
    cmd = [
        ffmpeg_bin(), "-i", str(file_path),
        "-af", "volumedetect",
        "-f", "null", _null_output(),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300,
            creationflags=NO_WINDOW_FLAGS,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None

    match = re.search(r"max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", result.stderr)
    if not match:
        return None
    peak = float(match.group(1))
    if peak < SILENCE_FLOOR_DB:
        return None
    return peak


def encode_args(stream: dict, ext: str) -> tuple[str, list[str]]:
    """Choose (output_extension, ffmpeg codec args) to preserve quality.

    Lossless sources keep their codec and bit depth; lossy sources are
    decoded to 16-bit PCM WAV so there is no extra lossy generation.
    """
    codec = stream.get("codec_name", "")
    bits_raw = stream.get("bits_per_raw_sample")
    is_aiff = ext in (".aif", ".aiff")

    if codec in ("pcm_s16le", "pcm_s16be"):
        if is_aiff:
            return ".aiff", ["-c:a", "pcm_s16be"]
        return ".wav", ["-c:a", "pcm_s16le"]

    if codec in ("pcm_s24le", "pcm_s24be"):
        if is_aiff:
            return ".aiff", ["-c:a", "pcm_s24be"]
        return ".wav", ["-c:a", "pcm_s24le"]

    if codec in ("pcm_s32le", "pcm_s32be"):
        return ".wav", ["-c:a", "pcm_s32le"]

    if codec in ("pcm_f32le", "pcm_f32be"):
        return ".wav", ["-c:a", "pcm_f32le"]

    if codec in ("pcm_f64le", "pcm_f64be"):
        return ".wav", ["-c:a", "pcm_f64le"]

    if codec == "flac":
        bit_depth = int(bits_raw) if bits_raw else 16
        sample_fmt = "s32" if bit_depth >= 24 else "s16"
        return ".flac", ["-c:a", "flac", "-sample_fmt", sample_fmt]

    # Lossy or unknown -> WAV to avoid a second lossy generation.
    return ".wav", ["-c:a", "pcm_s16le"]


def resolve_output_base(
    input_path: Path,
    output_dir: Optional[Path] = None,
    source_root: Optional[Path] = None,
    preserve_structure: bool = False,
) -> Path:
    """Base folder where the normalized file is placed.

    - With an output folder + "preserve structure": the whole source pack is
      mirrored inside the output as <pack>_N (output/<pack>_N/<subfolders>/...).
    - With an output folder only: every file goes flat into the output folder.
    - Without an output folder + "preserve structure": a <pack>_N mirror is
      created next to the source folder.
    - Default: files are written next to their source.
    """
    if output_dir is not None:
        if preserve_structure and source_root is not None:
            return output_dir / f"{source_root.name}{SKIP_SUFFIX}"
        return output_dir
    if preserve_structure and source_root is not None:
        return source_root.parent / f"{source_root.name}{SKIP_SUFFIX}"
    return input_path.parent


def compute_output_path(
    input_path: Path,
    output_dir: Optional[Path] = None,
    source_root: Optional[Path] = None,
    preserve_structure: bool = False,
    suffix: str = SKIP_SUFFIX,
    ext: str = ".wav",
) -> Path:
    """Final output path, keeping the source-relative structure when enabled.

    When preserve_structure is True and a source_root is known, the relative
    folder structure of the source file (inside source_root) is kept within
    the output base folder.
    """
    base = resolve_output_base(input_path, output_dir, source_root, preserve_structure)
    rel = Path(".")
    if preserve_structure and source_root is not None:
        try:
            rel = input_path.parent.relative_to(source_root)
        except ValueError:
            rel = Path(".")
    return base / rel / f"{input_path.stem}{suffix}{ext}"


def build_normalize_cmd(
    input_path: Path, output_path: Path, gain_db: float, codec_args: list[str],
) -> list[str]:
    """ffmpeg command that applies a pure linear gain (no dynamics change).

    The sample rate is intentionally NOT passed, so it is preserved.
    """
    return [
        ffmpeg_bin(), "-y",
        "-i", str(input_path),
        "-af", f"volume={gain_db:.3f}dB",
        *codec_args,
        str(output_path),
    ]


def normalize_file(
    input_path: Path,
    mode: str = "copy",  # "copy" keeps the original, "replace" deletes it
    target_db: float = -1.0,
    tolerance_db: float = 0.5,
    output_dir: Optional[Path] = None,
    source_root: Optional[Path] = None,
    preserve_structure: bool = False,
) -> NormalizeResult:
    """Normalize a single file to its own peak level.

    - Files ending in <SKIP_SUFFIX> are skipped (already processed).
    - Files whose peak is already within tolerance of the target are
      skipped (no output written, no extra copy made).
    - output_dir / source_root / preserve_structure control where the
      normalized file lands (see resolve_output_base). "Replace" only
      deletes the original when writing next to it (in place).
    """
    if not input_path.exists():
        return NormalizeResult(False, input_path, error="Input file not found")

    if input_path.stem.lower().endswith(SKIP_SUFFIX.lower()):
        return NormalizeResult(True, input_path, action="skipped_suffix")

    peak = measure_peak_db(input_path)
    if peak is None:
        return NormalizeResult(
            False, input_path,
            error="Could not analyze audio (silent or unsupported file?)",
        )

    gain_db = target_db - peak

    # Already within the acceptable range -> nothing to do.
    if abs(gain_db) <= tolerance_db:
        return NormalizeResult(
            True, input_path, gain_db=gain_db, action="skipped_range",
        )

    stream = get_stream_info(input_path)
    ext = input_path.suffix.lower()
    if stream:
        out_ext, codec_args = encode_args(stream, ext)
    else:
        out_ext, codec_args = ".wav", ["-c:a", "pcm_s16le"]

    output_path = compute_output_path(
        input_path, output_dir, source_root, preserve_structure,
        SKIP_SUFFIX, out_ext,
    )
    if output_path == input_path:
        # The source is the processed name; nothing to do.
        return NormalizeResult(True, input_path, action="skipped_suffix")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = build_normalize_cmd(input_path, output_path, gain_db, codec_args)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300,
            creationflags=NO_WINDOW_FLAGS,
        )
    except subprocess.TimeoutExpired:
        return NormalizeResult(False, input_path, error="Conversion timeout")
    except Exception as exc:  # pragma: no cover
        return NormalizeResult(False, input_path, error=str(exc))

    if result.returncode != 0 or not output_path.exists():
        return NormalizeResult(
            False, input_path,
            error=(result.stderr or "Unknown ffmpeg error").strip(),
        )

    # Replace mode: remove the original once the normalized copy exists.
    # Only meaningful when writing next to the source (in place).
    base = resolve_output_base(input_path, output_dir, source_root, preserve_structure)
    in_place = base == input_path.parent
    if mode == "replace" and in_place and input_path.exists():
        try:
            input_path.unlink()
        except OSError as exc:
            return NormalizeResult(
                False, input_path, output_path=output_path, gain_db=gain_db,
                error=f"Normalized ok but could not delete original: {exc}",
            )

    return NormalizeResult(
        True, input_path, output_path=output_path, gain_db=gain_db,
        action="normalized",
    )
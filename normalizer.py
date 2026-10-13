"""Simple Peak Normalizer

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

Hardened against CPU / disk abuse:
- every ffprobe/ffmpeg call is bounded by a timeout and cancellable
- ffmpeg runs capped in threads and output duration, never reads stdin
- oversized inputs are rejected before any full decode
- partial outputs are cleaned up; replace mode verifies the output
  before deleting the original
- directory scans are capped and never follow symlinks
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable, Optional, Union

# Hide ffmpeg/ffprobe console window on Windows (no visible cmd window).
NO_WINDOW_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

# Files that already carry this suffix are considered processed and skipped.
SKIP_SUFFIX = "_N"

# Files quieter than this (dBFS) are treated as silent and not normalized.
SILENCE_FLOOR_DB = -90.0

# --- Safety limits -----------------------------------------------------------
FFPROBE_TIMEOUT = 20      # s max per metadata probe (prevents hung workers)
MEASURE_TIMEOUT = 300     # s max per volumedetect pass (full decode)
CONVERT_TIMEOUT = 300     # s max per normalization encode
CHECK_TIMEOUT = 10        # s max for `ffmpeg -version` checks
MAX_FILE_BYTES = 250 * 1024 * 1024  # 250 MB input cap (decompression-bomb guard)
MAX_DURATION_SEC = 1800.0           # 30 min audio cap (bounds both ffmpeg passes)
MAX_FILES_PER_SCAN = 2000           # cap per folder scan
MAX_QUEUE_SIZE = 2000               # cap for the GUI queue
FFMPEG_THREADS = 2                  # cap ffmpeg CPU usage (x2 workers = bounded load)
MAX_GAIN_DB = 60.0                  # gains above this mean near-silence; refuse
MIN_OUTPUT_BYTES = 1024             # sanity floor for a written output file

SUPPORTED_EXTENSIONS = {
    ".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac",
    ".aiff", ".aif", ".wma", ".opus", ".webm",
}

CancelLike = Union[Event, Callable[[], bool], None]


def _is_cancelled(cancel_event: CancelLike) -> bool:
    """Accept threading.Event, callable, or None."""
    if cancel_event is None:
        return False
    try:
        if isinstance(cancel_event, Event):
            return cancel_event.is_set()
        if callable(cancel_event):
            return bool(cancel_event())
    except Exception:
        return False
    return False


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


def check_ffmpeg(timeout: int = CHECK_TIMEOUT) -> bool:
    """Verify ffmpeg is available (bundled or in PATH)."""
    try:
        subprocess.run([ffmpeg_bin(), "-version"], capture_output=True, check=True,
                       timeout=timeout, creationflags=NO_WINDOW_FLAGS)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError,
            subprocess.TimeoutExpired, OSError):
        return False
    except Exception:
        return False


def find_audio_files(
    folder: Path, recursive: bool = True, max_files: int = MAX_FILES_PER_SCAN
) -> list[Path]:
    """Find all supported audio files in a folder.

    Bounded (max_files), never follows symlinks (loop/junction guard),
    single-pass case-insensitive extension check.
    """
    try:
        base = Path(folder)
        if not base.is_dir():
            return []
    except OSError:
        return []
    try:
        if base.is_symlink():
            return []
    except OSError:
        return []

    files: list[Path] = []
    try:
        if not recursive:
            try:
                with os.scandir(base) as it:
                    for entry in it:
                        if len(files) >= max_files:
                            break
                        try:
                            if entry.is_symlink():
                                continue
                            if not entry.is_file(follow_symlinks=False):
                                continue
                            if Path(entry.name).suffix.lower() in SUPPORTED_EXTENSIONS:
                                files.append(Path(entry.path))
                        except OSError:
                            continue
            except OSError:
                return []
            return sorted(set(files))

        base_str = str(base)
        for root, dirs, filenames in os.walk(base_str, topdown=True, followlinks=False):
            # Never descend into symlinked dirs (junction/loop guard) + depth cap.
            try:
                root_depth = len(Path(root).relative_to(base).parts)
            except ValueError:
                root_depth = 0
            if root_depth > 25:
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs
                       if not (Path(root, d).is_symlink()) and not d.startswith("$")]
            for name in filenames:
                if len(files) >= max_files:
                    return sorted(set(files))
                if Path(name).suffix.lower() not in SUPPORTED_EXTENSIONS:
                    continue
                full = Path(root) / name
                try:
                    if full.is_symlink():
                        continue
                except OSError:
                    continue
                files.append(full)
    except OSError:
        pass
    return sorted(set(files))


def _null_output() -> str:
    """ffmpeg null output name (NUL on Windows, /dev/null elsewhere)."""
    return "NUL" if os.name == "nt" else "/dev/null"


def _is_oversized(file_path: Path) -> bool:
    """True when the input exceeds the pre-decode size guard."""
    try:
        return file_path.stat().st_size > MAX_FILE_BYTES
    except OSError:
        return False


def get_stream_info(file_path: Path, timeout: int = FFPROBE_TIMEOUT) -> Optional[dict]:
    """Extract the audio stream metadata from ffprobe (always time-bounded)."""
    try:
        if not Path(file_path).is_file():
            return None
    except OSError:
        return None
    cmd = [
        ffprobe_bin(), "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        str(file_path),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=True,
            timeout=timeout, creationflags=NO_WINDOW_FLAGS,
        )
        data = json.loads(result.stdout)
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "audio":
                return stream
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError,
            FileNotFoundError, OSError):
        pass
    except Exception:
        pass
    return None


def _run_bounded(cmd: list[str], timeout: int,
                 cancel_event: CancelLike = None) -> tuple[Optional[int], str]:
    """Run a subprocess with timeout + cancellation.

    Returns (returncode or None on timeout/cancel, stderr text).
    stdout is discarded (volumedetect/normalize logs go to stderr).
    """
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=NO_WINDOW_FLAGS,
        )
    except FileNotFoundError:
        return -1, "ffmpeg not found"
    except Exception as exc:
        return -1, str(exc)

    deadline = time.monotonic() + max(1, int(timeout))
    timed_out = False
    try:
        while True:
            try:
                returncode = proc.wait(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                if _is_cancelled(cancel_event):
                    proc.kill()
                    try:
                        proc.wait(timeout=5)
                    except Exception:
                        pass
                    try:
                        _, stderr = proc.communicate(timeout=5)
                    except Exception:
                        stderr = ""
                    return None, (stderr or "")
                if time.monotonic() > deadline:
                    timed_out = True
                    proc.kill()
                    try:
                        proc.wait(timeout=5)
                    except Exception:
                        pass
                    break
                continue
        try:
            _, stderr = proc.communicate(timeout=5)
        except Exception:
            stderr = ""
        if timed_out:
            return None, (stderr or "")
        return returncode, (stderr or "")
    except Exception as exc:
        try:
            proc.kill()
        except Exception:
            pass
        return -1, str(exc)


def measure_peak_db(
    file_path: Path,
    timeout: int = MEASURE_TIMEOUT,
    cancel_event: CancelLike = None,
) -> Optional[float]:
    """Measure the peak level (dBFS) of a file using ffmpeg volumedetect.

    Returns None when the file can't be analyzed (missing, oversized,
    unsupported, silent, cancelled, or ffmpeg error/timeout).
    """
    try:
        p = Path(file_path)
        if not p.is_file():
            return None
    except OSError:
        return None
    if _is_oversized(p):
        return None
    if _is_cancelled(cancel_event):
        return None
    cmd = [
        ffmpeg_bin(),
        "-nostdin", "-hide_banner",
        "-i", str(file_path),
        "-vn", "-threads", str(FFMPEG_THREADS),
        "-t", str(int(MAX_DURATION_SEC)),
        "-af", "volumedetect",
        "-f", "null", _null_output(),
    ]
    returncode, stderr = _run_bounded(cmd, timeout, cancel_event)
    if returncode != 0:
        return None

    match = re.search(r"max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", stderr)
    if not match:
        return None
    try:
        peak = float(match.group(1))
    except (TypeError, ValueError):
        return None
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
        try:
            bit_depth = int(bits_raw) if bits_raw else 16
        except (TypeError, ValueError):
            bit_depth = 16
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
    Bounded: capped threads and output duration, never reads from stdin.
    """
    try:
        gain = float(gain_db)
    except (TypeError, ValueError):
        gain = 0.0
    gain = max(-MAX_GAIN_DB, min(MAX_GAIN_DB, gain))
    return [
        ffmpeg_bin(),
        "-nostdin", "-hide_banner", "-loglevel", "error",
        "-y",
        "-i", str(input_path),
        "-vn",
        "-af", f"volume={gain:.3f}dB",
        *codec_args,
        "-threads", str(FFMPEG_THREADS),
        "-t", str(int(MAX_DURATION_SEC)),
        str(output_path),
    ]


def _cleanup_partial(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def _clamp_target(value: float, lo: float, hi: float, default: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def _output_looks_valid(path: Path) -> bool:
    """Cheap sanity check before replace mode deletes the original."""
    try:
        if not path.is_file():
            return False
        if path.stat().st_size < MIN_OUTPUT_BYTES:
            return False
    except OSError:
        return False
    return get_stream_info(path) is not None


def normalize_file(
    input_path: Path,
    mode: str = "copy",  # "copy" keeps the original, "replace" deletes it
    target_db: float = -1.0,
    tolerance_db: float = 0.5,
    output_dir: Optional[Path] = None,
    source_root: Optional[Path] = None,
    preserve_structure: bool = False,
    timeout: int = CONVERT_TIMEOUT,
    cancel_event: CancelLike = None,
) -> NormalizeResult:
    """Normalize a single file to its own peak level.

    - Files ending in <SKIP_SUFFIX> are skipped (already processed).
    - Files whose peak is already within tolerance of the target are
      skipped (no output written, no extra copy made).
    - output_dir / source_root / preserve_structure control where the
      normalized file lands (see resolve_output_base). "Replace" only
      deletes the original when writing next to it (in place), and only
      after the output passes a sanity check (original is never lost
      to a truncated write).
    """
    if _is_cancelled(cancel_event):
        return NormalizeResult(False, input_path, error="Cancelled")
    try:
        if not input_path.is_file():
            return NormalizeResult(False, input_path, error="Input file not found")
    except OSError:
        return NormalizeResult(False, input_path, error="Input file not found")

    if _is_oversized(input_path):
        mb = MAX_FILE_BYTES // (1024 * 1024)
        return NormalizeResult(False, input_path, error=f"File too large (>{mb} MB), skipped")

    if input_path.stem.lower().endswith(SKIP_SUFFIX.lower()):
        return NormalizeResult(True, input_path, action="skipped_suffix")

    # Clamp user-facing parameters (GUI bounds them, API callers may not).
    target_db = _clamp_target(target_db, -60.0, 0.0, -1.0)
    tolerance_db = _clamp_target(tolerance_db, 0.0, 12.0, 0.5)

    peak = measure_peak_db(input_path, cancel_event=cancel_event)
    if peak is None:
        if _is_cancelled(cancel_event):
            return NormalizeResult(False, input_path, error="Cancelled")
        return NormalizeResult(
            False, input_path,
            error="Could not analyze audio (silent or unsupported file?)",
        )

    gain_db = target_db - peak
    if gain_db > MAX_GAIN_DB:
        return NormalizeResult(False, input_path, error="File too quiet, skipped")

    # Already within the acceptable range -> nothing to do.
    if abs(gain_db) <= tolerance_db:
        return NormalizeResult(
            True, input_path, gain_db=gain_db, action="skipped_range",
        )

    stream = get_stream_info(input_path)
    ext = input_path.suffix.lower()
    if stream:
        try:
            if float(stream.get("duration", 0) or 0) > MAX_DURATION_SEC:
                return NormalizeResult(False, input_path, error="Audio too long, skipped")
        except (TypeError, ValueError):
            pass
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

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return NormalizeResult(False, input_path, error=f"Cannot create output folder: {exc}")

    if _is_cancelled(cancel_event):
        return NormalizeResult(False, input_path, error="Cancelled")

    cmd = build_normalize_cmd(input_path, output_path, gain_db, codec_args)
    returncode, stderr = _run_bounded(cmd, timeout, cancel_event)

    if returncode is None:
        _cleanup_partial(output_path)
        if _is_cancelled(cancel_event):
            return NormalizeResult(False, input_path, error="Cancelled")
        return NormalizeResult(False, input_path, error="Conversion timeout")

    if returncode != 0 or not output_path.exists():
        _cleanup_partial(output_path)
        err = (stderr or "").strip().splitlines()
        err = err[-1][:500] if err else "Unknown ffmpeg error"
        return NormalizeResult(False, input_path, error=err)

    # Replace mode: remove the original once the normalized copy exists
    # AND passes a sanity check. Only meaningful when writing next to
    # the source (in place).
    base = resolve_output_base(input_path, output_dir, source_root, preserve_structure)
    in_place = base == input_path.parent
    if mode == "replace" and in_place and input_path.exists():
        if not _output_looks_valid(output_path):
            _cleanup_partial(output_path)
            return NormalizeResult(
                False, input_path, gain_db=gain_db,
                error="Output verification failed, original kept",
            )
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

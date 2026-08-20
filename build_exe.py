"""Build a portable .exe of Peak Normalizer with PyInstaller.

Bundles the FFmpeg binaries (ffmpeg.exe / ffprobe.exe) and styles.qss
inside the one-file executable. Run from the project folder:

    python build_exe.py
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

FFMPEG_CANDIDATES = [
    Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
    / "Gyan.FFmpeg.Essentials_Microsoft.Winget.Source_8wekyb3d8bbwe"
    / "ffmpeg-8.1.1-essentials_build" / "bin",
]


def find_binary(name: str) -> Path | None:
    exe = shutil.which(name)
    if exe:
        return Path(exe)
    for folder in FFMPEG_CANDIDATES:
        candidate = folder / f"{name}.exe"
        if candidate.exists():
            return candidate
    return None


def main() -> int:
    ffmpeg = find_binary("ffmpeg")
    ffprobe = find_binary("ffprobe")
    if ffmpeg is None or ffprobe is None:
        print("ERROR: ffmpeg.exe / ffprobe.exe not found (add FFmpeg to PATH).")
        return 1

    icon = ROOT / "icon.ico"
    icon_args = ["--icon", str(icon)] if icon.exists() else []

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile", "--windowed",
        *icon_args,
        "--name", "SimplePeakNormalizer",
        "--add-data", f"{ROOT / 'styles.qss'};.",
        "--add-binary", f"{ffmpeg};.",
        "--add-binary", f"{ffprobe};.",
        str(ROOT / "main.py"),
    ]

    print("Running:", " ".join(cmd))
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
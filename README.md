# Simple Peak Normalizer

Batch audio peak normalization tool with a PySide6 GUI. Every clip is normalized to its **own peak level** using linear gain while preserving sample rate and bit depth.

## Features

- Per-file peak normalization (target in dB, -1.0 dB by default).
- Skips clips already within a tolerance of the target (0.5 dB by default).
- Parallel processing (2 threads).
- Drag-and-drop files or folders, or add folders with a button.
- `_N` suffix on processed files (they are never reprocessed).
- Folder structure: recreates the source structure inside the output folder (or in a `<source>_N` folder next to it).
- Replace-original option (only applies when saving next to the source).
- Formats: WAV, MP3, FLAC, AIFF, OGG, M4A.
- Portable: build into a single `.exe` with FFmpeg bundled.

## Requirements

- Windows
- Python 3.x (tested with 3.14)
- FFmpeg on PATH (to run from source). The compiled `.exe` includes it.

## Run from source

### Option A: double-click

Run `start.bat` (creates the virtual environment and installs dependencies on first run).

### Option B: manual

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe main.py
```

## Usage

1. Drag files or folders into the list (or use **Add folder**).
2. Configure:
   - **Target peak**: target peak level (dB).
   - **Skip if within**: tolerance to skip clips already normalized.
   - **Replace original files**: deletes the original after normalizing (only when saving next to the source).
   - **Browse**: output folder (empty = save next to the source).
   - **Preserve source folder structure**: recreates the source folder structure.
3. Press **START**.
4. Processed files are saved with the `_N` suffix at the output location.

## Build the `.exe`

```
python build_exe.py
```

To regenerate the app icon:

```
python make_icon.py
```

Place `icon.ico` next to `build_exe.py` to have it included in the next build.

## Project structure

```
peak_normalizer/
├── main.py          # Entry point
├── gui.py           # GUI
├── normalizer.py    # Engine: peak analysis, normalization, folder mirroring
├── styles.qss       # Dark theme
├── build_exe.py     # PyInstaller build script
├── requirements.txt
├── start.bat        # Setup + launch
```

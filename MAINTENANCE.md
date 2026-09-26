# Maintenance guide — Simple Peak Normalizer

Practical guide to keep this application running for years.

## 1. Project map (what touches what)

```
peak_normalizer/
├── main.py            Entry point. Calls gui.main().
├── gui.py             PySide6 window + drag&drop + queue with overall progress.
├── normalizer.py      EVERYTHING that talks to FFmpeg:
│                      │  - ffmpeg_bin()/ffprobe_bin() (bundled via sys._MEIPASS or PATH)
│                      │  - get_stream_info() (metadata via ffprobe)
│                      │  - measure_peak_db() (dBFS peak via volumedetect)
│                      │  - encode_args() (which codec/bit depth per source)
│                      │  - resolve_output_base()/compute_output_path() (paths + _N suffix)
│                      │  - build_normalize_cmd() (linear gain, dynamics untouched)
│                      │  - normalize_file() (measure → tolerance check → apply)
│                      │  - find_audio_files() (extension-based discovery)
├── styles.qss         Dark theme (editable without touching code).
├── build_exe.py       Portable recipe (PyInstaller one-file + bundled FFmpeg).
├── make_icon.py       Regenerates icon.ico / icon.png.
├── start.bat          One-click setup + launch (creates .venv, installs, launches).
└── requirements.txt   Runtime dependencies.
```

**Golden rule:** the GUI (`gui.py`) never calls FFmpeg directly;
always through `normalizer.py` functions. Respect that and changes
won't break each other.

## 2. Suggested maintenance calendar

| When | Task | Where to look |
|---|---|---|
| Every 6–12 months | Update dependencies (`pip install -U ...`, see §3) | `requirements.txt` |
| Every 12 months | Test against the latest stable FFmpeg | https://ffmpeg.org/download.html |
| After every change | Run the suite (`python -m pytest tests -q`) | `tests/` + CI in `.github/workflows/` |
| After every change | Rebuild the exe and test it in a clean folder | `build_exe.py` |
| Always | Never commit `.venv/`, `build/`, `dist/`, `*.log` | Already covered by `.gitignore` |

## 3. Updating dependencies without breaking anything

1. Create a scratch venv and record what's installed: `pip freeze > before.txt`
2. Update in groups (never everything at once): first `PySide6`, then the rest.
3. After each group: run the tests and try the app (1 quiet tone → normalizes,
   1 tone already at target → skipped).
4. If something breaks: go back to `requirements.txt` and pin the upper bound.
5. Only then update the ranges in `requirements.txt`.

**Historically sensitive spots:**
- **PySide6 6.x → 7.x (whenever it lands):** review drag&drop and GUI signals.
- **Python:** tested with 3.14. Before bumping minor versions,
  rebuild the exe: PyInstaller is version-sensitive.

## 4. FFmpeg (what breaks most often over the years)

- All coupling lives in `normalizer.py`. If `volumedetect` changes its
  output format (`max_volume: ... dB`), the first place to check is
  `measure_peak_db()` — the test `test_measure_peak_of_generated_tone`
  catches it immediately.
- The app bundles FFmpeg **inside** the exe (full portability).
  `build_exe.py` looks for it on PATH (falling back to the winget path in
  `FFMPEG_CANDIDATES`); when missing it **fails** instead of producing a
  non-portable exe. If you switch PCs or reinstall FFmpeg another way,
  update that list.
- Measurement has a silence floor (`SILENCE_FLOOR_DB = -90.0`):
  anything below counts as silence and is not normalized. Conscious
  constant, not a bug.

## 5. Rebuilding the portable exe

```powershell
python build_exe.py   # builds dist\SimplePeakNormalizer.exe
```

- `icon.ico` is used when present; otherwise the exe gets the default icon
  (regenerate with `python make_icon.py`).
- Quick check: 1 quiet file (−12 dB) → comes out `*_N` at target;
  passing the same file again → skipped by suffix.

## 6. Release checklist

1. `git status` free of artifacts (`build/`, `dist/`, `.venv/`, `*.log`).
2. `python -m pytest tests -q` green (and green CI on GitHub).
3. README up to date (formats = `SUPPORTED_EXTENSIONS`, default
   target/tolerance = `normalize_file`).
4. Test the exe on a clean PC/folder: normalizes, honors tolerance,
   replace mode only deletes the original when writing next to the source.
5. Upload the exe to GitHub Releases (never committed: `dist/` is ignored).

## 7. Decided behaviors (not bugs)

- **Each clip is normalized to its OWN peak.** Not loudness (LUFS) and not
  batch normalization to a common level: linear per-file gain.
- **Tolerance avoids rewrites.** When the peak is already within
  `tolerance_db` of the target, the file is skipped without writing
  anything (`skipped_range`).
- **The suffix is `_N`** and files already carrying it are skipped
  (`skipped_suffix`): passing the same folder twice is safe.
- **Lossy sources → WAV.** MP3/OGG/etc. decode to 16-bit PCM so a second
  lossy generation never accumulates.
- **Replace is in-place only.** Replace mode deletes the original solely
  when writing next to the source; with an output folder it deletes nothing.
- **Stateless.** The app stores no settings or history; there is nothing
  to migrate or back up beyond the code (GitHub).

## 8. Tests

```
pip install -r requirements-dev.txt
python -m pytest tests -q
```

50 tests: path resolution, codec matrix, file discovery, binaries, peak
measurement and end-to-end normalization with on-the-fly generated tones
(no audio fixtures in the repo). Integration tests skip automatically
when ffmpeg is not on PATH. The GUI is not tested
(manual check with §6 instead).

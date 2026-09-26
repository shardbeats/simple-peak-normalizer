# Guía de mantenimiento — Simple Peak Normalizer

Guía práctica para mantener esta aplicación funcionando durante años.
Idioma del documento: español (el código y la UI están en inglés).

## 1. Mapa del proyecto (qué toca qué)

```
peak_normalizer/
├── main.py            Entrada. Llama a gui.main().
├── gui.py             Ventana PySide6 + drag&drop + cola con progreso global.
├── normalizer.py      TODO lo que habla con FFmpeg:
│                      │  - ffmpeg_bin()/ffprobe_bin() (bundled vía sys._MEIPASS o PATH)
│                      │  - get_stream_info() (metadata vía ffprobe)
│                      │  - measure_peak_db() (pico dBFS vía volumedetect)
│                      │  - encode_args() (qué codec/bit depth usar por fuente)
│                      │  - resolve_output_base()/compute_output_path() (rutas + sufijo _N)
│                      │  - build_normalize_cmd() (ganancia lineal, sin tocar dinámica)
│                      │  - normalize_file() (medir → comparar tolerancia → aplicar)
│                      │  - find_audio_files() (descubrimiento por extensiones)
├── styles.qss         Tema oscuro (se edita sin tocar código).
├── build_exe.py       Receta del portable (PyInstaller one-file + FFmpeg bundled).
├── make_icon.py       Regenera icon.ico / icon.png.
├── start.bat          Setup + arranque en un clic (crea .venv, instala, lanza).
└── requirements.txt   Dependencias de runtime.
```

**Regla de oro:** la GUI (`gui.py`) nunca invoca a FFmpeg directamente;
siempre a través de las funciones de `normalizer.py`. Si respetas eso,
los cambios no se rompen entre sí.

## 2. Calendario de mantenimiento sugerido

| Cuándo | Tarea | Dónde mirar |
|---|---|---|
| Cada 6–12 meses | Actualizar dependencias (`pip install -U ...`, ver §3) | `requirements.txt` |
| Cada 12 meses | Probar con el FFmpeg estable más reciente | https://ffmpeg.org/download.html |
| Tras cada cambio | Correr la suite (`python -m pytest tests -q`) | `tests/` + CI en `.github/workflows/` |
| Tras cada cambio | Recompilar el exe y probarlo en una carpeta limpia | `build_exe.py` |
| Siempre | Nunca commitear `.venv/`, `build/`, `dist/`, `*.log` | `.gitignore` ya los cubre |

## 3. Actualizar dependencias sin romper nada

1. Crea un venv de prueba y anota lo instalado: `pip freeze > antes.txt`
2. Actualiza por grupos (nunca todo a la vez): primero `PySide6`, luego el resto.
3. Tras cada grupo: corre los tests y prueba la app (1 tono quedo → normaliza,
   1 tono ya a target → se salta).
4. Si algo falla: vuelve a `requirements.txt` y fija el tope del rango.
5. Solo entonces actualiza los rangos en `requirements.txt`.

**Puntos históricamente sensibles:**
- **PySide6 6.x → 7.x (cuando salga):** revisar drag&drop y señales de la GUI.
- **Python:** probado con 3.14. Antes de subir de versión menor,
  recompila el exe: PyInstaller es sensible a la versión.

## 4. FFmpeg (lo que más se rompe con los años)

- Todo el acoplamiento está en `normalizer.py`. Si `volumedetect` cambia su
  formato de salida (`max_volume: ... dB`), el primer sitio a revisar es
  `measure_peak_db()` — el test `test_measure_peak_of_generated_tone`
  lo detecta al instante.
- La app empaqueta FFmpeg **dentro** del exe (portabilidad total).
  `build_exe.py` lo busca en el PATH (con fallback a la ruta de winget
  en `FFMPEG_CANDIDATES`); si no lo encuentra, **falla** en vez de
  producir un exe no portable. Si cambias de PC o reinstalas FFmpeg por
  otro método, actualiza esa lista.
- La medición tiene un piso de silencio (`SILENCE_FLOOR_DB = -90.0`):
  por debajo se considera silencio y no se normaliza. Es una constante
  consciente, no un bug.

## 5. Recompilar el portable

```powershell
python build_exe.py   # compila dist\SimplePeakNormalizer.exe
```

- `icon.ico` se usa si existe; si no, el exe sale con icono por defecto
  (regenéralo con `python make_icon.py`).
- Verificación rápida: 1 archivo quedo (−12 dB) → sale `*_N` al target;
  el mismo archivo pasado de nuevo → se salta por sufijo.

## 6. Checklist de release

1. `git status` limpio de artefactos (`build/`, `dist/`, `.venv/`, `*.log`).
2. `python -m pytest tests -q` en verde (y CI verde en GitHub).
3. README al día (formatos = `SUPPORTED_EXTENSIONS`, target/tolerancia
   por defecto = `normalize_file`).
4. Probar el exe en PC/carpeta limpio: normaliza, respeta tolerancia,
   modo replace borra el original solo al escribir junto a la fuente.
5. Subir el exe a GitHub Releases (nunca commiteado: `dist/` está ignorado).

## 7. Comportamientos decididos (no son bugs)

- **Cada clip se normaliza a SU propio pico.** No es loudness (LUFS) ni
  normalización por lote a un nivel común: ganancia lineal por archivo.
- **La tolerancia evita re-escrituras.** Si el pico ya está dentro de
  `tolerance_db` del target, se salta sin escribir nada (`skipped_range`).
- **El sufijo es `_N`** y los archivos que ya lo llevan se saltan
  (`skipped_suffix`): pasar dos veces la misma carpeta es seguro.
- **Fuentes con pérdida → WAV.** MP3/OGG/etc. se decodifican a PCM 16-bit
  para no acumular una segunda generación con pérdida.
- **Replace solo in-place.** El modo replace borra el original únicamente
  cuando se escribe junto a la fuente; con carpeta de salida no borra nada.
- **Sin estado local.** La app no guarda ajustes ni historial; no hay nada
  que migrar ni respaldar más allá del código (GitHub).

## 8. Tests

```
pip install -r requirements-dev.txt
python -m pytest tests -q
```

50 tests: resolución de rutas, matriz de codecs, descubrimiento de
archivos, binarios, medición de pico y normalización end-to-end con tonos
generados al vuelo (sin fixtures de audio en el repo). Los tests de
integración se saltan solos si no hay FFmpeg en el PATH. La GUI no se
testea (verificación manual con el checklist del punto 6).

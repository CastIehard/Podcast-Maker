# Podcast-Maker (Windows EXE Build)

This repository contains a small GUI tool to assemble a podcast episode from a fixed set of audio files, normalize loudness, and export a final MP3. It also includes a GitHub Actions workflow to build a Windows `.exe` and publish it as a GitHub Release asset.

## What the app does

### Input expectation (Episode folder)

You select an **episode folder** containing exactly these files:

* `intro.mp3`
* `vorab.mp3`
* `kapitel.mp3`
* `outro.mp3`
* `jingle_vorne.mp3`
* `jingle_hinten.mp3`

The app validates whether all required files exist.

### Processing steps

When you click **Exportieren**, the tool:

1. **Finds ffmpeg**

   * It first looks for a bundled ffmpeg under `bin/ffmpeg.exe` (when packaged).
   * If not found, it falls back to `ffmpeg` available in the system `PATH`.

2. **Measures baseline loudness**

   * It measures the integrated loudness (`input_i`) of `jingle_vorne.mp3` using:

     * `ffmpeg` filter `loudnorm` with JSON output (`print_format=json`).

3. **Normalizes all files**

   * It normalizes each unique source file (intro/vorab/kapitel/outro/jingles) to the baseline loudness from `jingle_vorne`.
   * Normalized files are written as temporary **48kHz stereo WAV** in a temp directory.

4. **Concatenates in a fixed order**
   The output order is:

   1. `jingle_vorne`
   2. `intro`
   3. `jingle_hinten`
   4. `vorab`
   5. `kapitel`
   6. `jingle_vorne` (re-used)
   7. `outro`
   8. `jingle_hinten` (re-used)

5. **Exports MP3**

   * Output filename: `Kapitel <chapter_number>.mp3`
   * MP3 encoding via `libmp3lame`, VBR quality `-q:a 2`

### GUI

* Minimal PySide6 GUI
* Select **Episode folder**
* Select optional **Output folder** (defaults to episode folder)
* Choose **Kapitel number**
* Click **Exportieren**

## Requirements (for running from source)

* Python 3.11+
* `ffmpeg` available either:

  * bundled (Windows EXE build uses `bin/ffmpeg.exe`), or
  * installed and available in PATH (for running locally)

Install Python dependencies:

```bash
pip install -r requirements.txt
```

Run:

```bash
python app.py
```

## Building the Windows EXE via GitHub Actions

### Repository layout (important)

This is expected:

```
.
├── app.py
├── requirements.txt
├── bin
│   ├── ffmpeg.exe
│   └── ffprobe.exe
└── .github
    └── workflows
        └── build-windows.yml
```

### What the workflow does

* Runs on a Windows runner
* Installs Python dependencies from `requirements.txt` + PyInstaller
* Builds a single-file GUI EXE using PyInstaller
* Uploads the EXE as:

  * an Actions artifact (optional)
  * a GitHub Release asset (only when triggered by a tag `v*`)

## Releases: How to publish a direct download link

### Key rule

**A normal push to `main` does NOT create a release.**
A Release build happens only when you push a tag matching `v*` (e.g. `v1.0.0`).

### Create a Release (from macOS / Linux)

From your local repo:

```bash
git tag v1.0.0
git push origin v1.0.0
```

This triggers the workflow. When it finishes, GitHub will create a Release and attach:

* `Podcast-Maker.exe`

### Where to get the download link

Go to:

* GitHub → **Releases** → select `v1.0.0` → download the attached `Podcast-Maker.exe`

That Release page URL is the shareable link.

## Workflow manual runs vs. Releases

### Manual run (workflow_dispatch)

If you click “Run workflow” in GitHub Actions:

* you will get an **Artifact** (zip) under the Actions run
* **Artifacts can expire** and sometimes are less convenient to share

### Tagged run (v*)

If you push a tag like `v1.2.3`:

* you get a **GitHub Release** with a stable downloadable `.exe`

## Notes / Limitations

* Current implementation concatenates files without crossfades.
* Loudness normalization is done per-file using `ffmpeg loudnorm`.
* Output is MP3 only.

---

If you want, I can also provide:

* a workflow variant that **downloads ffmpeg automatically** during CI (so you don’t commit `bin/*.exe`)
* a variant that adds **crossfades** between segments (your current code concatenates only)

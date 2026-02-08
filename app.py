import os
import re
import sys
import json
import shutil
import tempfile
import subprocess
from typing import Optional, List, Tuple

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QMessageBox, QGridLayout, QFrame, QGroupBox,
    QSpinBox
)


# ----------------------------- Config -----------------------------

# Expected files in episode folder
EPISODE_FILES = ["intro.mp3", "vorab.mp3", "kapitel.mp3", "outro.mp3", "jingle_vorne.mp3", "jingle_hinten.mp3"]

# Order for concatenation:
# jingle_vorne → intro → jingle_hinten → vorab → kapitel → jingle_vorne → outro → jingle_hinten
CONCAT_ORDER = [
    "jingle_vorne",
    "intro",
    "jingle_hinten",
    "vorab",
    "kapitel",
    "jingle_vorne",  # used again
    "outro",
    "jingle_hinten",  # used again
]


# ----------------------------- ffmpeg helpers -----------------------------

def _resource_path(relative: str) -> str:
    """When bundled with PyInstaller, sys._MEIPASS points to temp extraction dir."""
    base = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base, relative)


def _which_or_bundled(name: str) -> Optional[str]:
    """Find ffmpeg/ffprobe either in PATH or next to the exe (bundled)."""
    candidate = _resource_path(os.path.join("bin", name))
    if os.path.exists(candidate):
        return candidate
    return shutil.which(name)


def run_cmd(cmd: List[str]) -> Tuple[int, str, str]:
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = p.communicate()
    return p.returncode, out, err


def measure_integrated_loudness(ffmpeg_path: str, infile: str) -> float:
    """Measure integrated loudness (I) using loudnorm filter."""
    cmd = [
        ffmpeg_path, "-hide_banner", "-nostdin",
        "-i", infile,
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
        "-f", "null", "-"
    ]
    rc, out, err = run_cmd(cmd)
    if rc != 0:
        raise RuntimeError(f"ffmpeg loudness analysis failed for {infile}:\n{err}")

    m = re.findall(r"\{[\s\S]*?\}", err)
    if not m:
        raise RuntimeError(f"Could not parse loudnorm JSON for {infile}.\nffmpeg stderr:\n{err}")
    j = json.loads(m[-1])
    input_i = j.get("input_i", None)
    if input_i is None or str(input_i).lower() == "nan":
        raise RuntimeError(f"Invalid loudness (input_i) for {infile}.")
    return float(input_i)


def normalize_to_target_i(ffmpeg_path: str, infile: str, outfile_wav: str, target_i: float,
                          true_peak: float = -1.5, lra: float = 11.0,
                          sample_rate: int = 48000, channels: int = 2) -> None:
    """Normalize audio to target integrated loudness."""
    af = f"loudnorm=I={target_i:.2f}:TP={true_peak:.1f}:LRA={lra:.0f}"
    cmd = [
        ffmpeg_path, "-hide_banner", "-nostdin", "-y",
        "-i", infile,
        "-vn",
        "-af", af,
        "-ar", str(sample_rate),
        "-ac", str(channels),
        outfile_wav
    ]
    rc, out, err = run_cmd(cmd)
    if rc != 0:
        raise RuntimeError(f"ffmpeg normalize failed for {infile}:\n{err}")


def concatenate_audio(ffmpeg_path: str, input_files: List[str], output_path: str,
                      mp3_quality: int = 2) -> None:
    """Concatenate audio files without crossfade."""
    # Build filter for concatenation
    n = len(input_files)
    filter_inputs = "".join(f"[{i}:a]" for i in range(n))
    filter_complex = f"{filter_inputs}concat=n={n}:v=0:a=1[out]"
    
    cmd = [ffmpeg_path, "-hide_banner", "-nostdin", "-y"]
    for f in input_files:
        cmd += ["-i", f]
    
    cmd += [
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-c:a", "libmp3lame",
        "-q:a", str(mp3_quality),
        output_path
    ]
    
    rc, out, err = run_cmd(cmd)
    if rc != 0:
        raise RuntimeError(f"ffmpeg concatenation failed:\n{err}")


def process_episode(
    episode_folder: str,
    chapter_number: int,
    output_folder: str,
    status_callback=None,
) -> str:
    """Process episode: normalize and concatenate."""
    
    ffmpeg = _which_or_bundled("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if not ffmpeg:
        raise RuntimeError(
            "ffmpeg nicht gefunden.\n"
            "Installiere ffmpeg oder bundle es mit der .exe."
        )
    
    # Build file paths
    files = {
        "intro": os.path.join(episode_folder, "intro.mp3"),
        "vorab": os.path.join(episode_folder, "vorab.mp3"),
        "kapitel": os.path.join(episode_folder, "kapitel.mp3"),
        "outro": os.path.join(episode_folder, "outro.mp3"),
        "jingle_vorne": os.path.join(episode_folder, "jingle_vorne.mp3"),
        "jingle_hinten": os.path.join(episode_folder, "jingle_hinten.mp3"),
    }
    
    # Validate all files exist
    missing = []
    for name, path in files.items():
        if not path or not os.path.exists(path):
            missing.append(f"{name}.mp3")
    
    if missing:
        raise RuntimeError(f"Fehlende Dateien:\n" + "\n".join(f"  - {m}" for m in missing))
    
    if status_callback:
        status_callback("Messe Baseline-Lautstärke (jingle_vorne)…")
    
    # Get baseline loudness from jingle_vorne
    baseline_i = measure_integrated_loudness(ffmpeg, files["jingle_vorne"])
    
    with tempfile.TemporaryDirectory(prefix="podcast_") as td:
        # Normalize all unique files
        unique_files = {
            "intro": files["intro"],
            "vorab": files["vorab"],
            "kapitel": files["kapitel"],
            "outro": files["outro"],
            "jingle_vorne": files["jingle_vorne"],
            "jingle_hinten": files["jingle_hinten"],
        }
        
        normalized = {}
        for name, path in unique_files.items():
            if status_callback:
                status_callback(f"Normalisiere {name}…")
            outwav = os.path.join(td, f"{name}_norm.wav")
            normalize_to_target_i(ffmpeg, path, outwav, baseline_i)
            normalized[name] = outwav
        
        # Build concatenation order
        concat_files = [normalized[name] for name in CONCAT_ORDER]
        
        # Output path
        output_path = os.path.join(output_folder, f"Kapitel {chapter_number}.mp3")
        
        if status_callback:
            status_callback("Füge Audio zusammen…")
        
        concatenate_audio(ffmpeg, concat_files, output_path)
        
        return output_path


# ----------------------------- GUI widgets -----------------------------

class DropLineEdit(QLineEdit):
    def __init__(self, placeholder: str = ""):
        super().__init__()
        self.setAcceptDrops(True)
        self.setPlaceholderText(placeholder)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path:
                self.setText(path)
        event.acceptProposedAction()


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Quotenschwabe Podcast - Audio Joiner")
        self.setMinimumWidth(700)
        self.setMinimumHeight(400)

        root = QVBoxLayout(self)
        root.setSpacing(12)

        # Title
        title = QLabel("Quotenschwabe Podcast - Episode zusammenfügen")
        title.setStyleSheet("font-weight: 600; font-size: 16px;")
        root.addWidget(title)

        # Chapter number
        chapter_group = QGroupBox("Kapitel")
        chapter_layout = QHBoxLayout(chapter_group)
        chapter_layout.addWidget(QLabel("Kapitel-Nummer:"))
        self.chapter_spin = QSpinBox()
        self.chapter_spin.setRange(1, 9999)
        self.chapter_spin.setValue(1)
        self.chapter_spin.setFixedWidth(100)
        chapter_layout.addWidget(self.chapter_spin)
        chapter_layout.addStretch()
        root.addWidget(chapter_group)

        # Episode folder
        episode_group = QGroupBox("Episode-Ordner (alle 6 Dateien: intro, vorab, kapitel, outro, jingle_vorne, jingle_hinten)")
        episode_layout = QHBoxLayout(episode_group)
        self.episode_folder_edit = DropLineEdit("Ordner hierher ziehen oder auswählen…")
        self.episode_folder_btn = QPushButton("Ordner wählen…")
        self.episode_folder_btn.clicked.connect(self.pick_episode_folder)
        episode_layout.addWidget(self.episode_folder_edit, 1)
        episode_layout.addWidget(self.episode_folder_btn)
        root.addWidget(episode_group)

        # Output folder
        output_group = QGroupBox("Ausgabe-Ordner")
        output_layout = QHBoxLayout(output_group)
        self.output_folder_edit = DropLineEdit("Ausgabe-Ordner (Standard: Episode-Ordner)")
        self.output_folder_btn = QPushButton("Ordner wählen…")
        self.output_folder_btn.clicked.connect(self.pick_output_folder)
        output_layout.addWidget(self.output_folder_edit, 1)
        output_layout.addWidget(self.output_folder_btn)
        root.addWidget(output_group)

        # File status
        self.file_status = QLabel("")
        self.file_status.setWordWrap(True)
        self.file_status.setStyleSheet("color: #666;")
        root.addWidget(self.file_status)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        root.addWidget(sep)

        # Export button
        self.export_btn = QPushButton("Exportieren")
        self.export_btn.setFixedHeight(50)
        self.export_btn.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.export_btn.clicked.connect(self.on_export)
        root.addWidget(self.export_btn)

        # Status
        self.status = QLabel("")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        # Connect folder change to validation
        self.episode_folder_edit.textChanged.connect(self.validate_files)

    def pick_episode_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Episode-Ordner auswählen")
        if folder:
            self.episode_folder_edit.setText(folder)

    def pick_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Ausgabe-Ordner auswählen")
        if folder:
            self.output_folder_edit.setText(folder)

    def validate_files(self):
        """Check if all required files exist in the episode folder"""
        folder = self.episode_folder_edit.text().strip()
        if not folder or not os.path.isdir(folder):
            self.file_status.setText("")
            self.file_status.setStyleSheet("color: #666;")
            return
        
        found = []
        missing = []
        
        for fname in EPISODE_FILES:
            path = os.path.join(folder, fname)
            if os.path.exists(path):
                found.append(f"✓ {fname}")
            else:
                missing.append(f"✗ {fname}")
        
        if missing:
            self.file_status.setText("Fehlende Dateien: " + ", ".join(missing))
            self.file_status.setStyleSheet("color: #c00;")
        else:
            self.file_status.setText("Alle Dateien gefunden: " + ", ".join(found))
            self.file_status.setStyleSheet("color: #0a0;")

    def set_status(self, msg: str):
        self.status.setText(msg)
        QApplication.processEvents()

    def on_export(self):
        episode_folder = self.episode_folder_edit.text().strip()
        output_folder = self.output_folder_edit.text().strip()
        chapter = self.chapter_spin.value()
        
        # Validate episode folder
        if not episode_folder or not os.path.isdir(episode_folder):
            QMessageBox.critical(self, "Fehler", "Bitte wähle einen gültigen Episode-Ordner.")
            return
        
        # Check episode files
        missing = []
        for fname in EPISODE_FILES:
            if not os.path.exists(os.path.join(episode_folder, fname)):
                missing.append(fname)
        
        if missing:
            QMessageBox.critical(
                self, "Fehler",
                "Fehlende Dateien im Episode-Ordner:\n" + "\n".join(f"  - {m}" for m in missing)
            )
            return
        
        # Default output folder to episode folder
        if not output_folder:
            output_folder = episode_folder
        
        try:
            self.export_btn.setEnabled(False)
            output_path = process_episode(
                episode_folder,
                chapter,
                output_folder,
                status_callback=self.set_status
            )
            self.set_status(f"Fertig: {output_path}")
            QMessageBox.information(self, "Erfolg", f"Export erstellt:\n{output_path}")
        except Exception as e:
            QMessageBox.critical(self, "Fehler", str(e))
            self.set_status(f"Fehler: {e}")
        finally:
            self.export_btn.setEnabled(True)


def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

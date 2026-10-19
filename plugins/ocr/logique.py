# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Partie sans interface de l'extension OCR : trouver Tesseract et lui faire lire une image (sur son entrée standard,
donc sans fichier temporaire : une image de fiche verrouillée n'est jamais écrite en clair sur le disque)."""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

DELAI = 180          # secondes par image
TEXTE_MAX = 200_000  # caractères conservés par image
CHEMINS_USUELS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    "/opt/homebrew/bin/tesseract",
    "/usr/local/bin/tesseract",
    "/usr/bin/tesseract",
)


def trouver(chemin: str = "") -> str | None:
    """Programme tesseract : chemin donné dans les réglages, sinon le PATH, sinon les emplacements usuels."""
    if chemin and Path(chemin).is_file():
        return chemin
    p = shutil.which("tesseract")
    if p:
        return p
    return next((c for c in CHEMINS_USUELS if Path(c).is_file()), None)


def _options() -> dict:
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def langues(exe: str) -> set:
    """Langues installées (codes comme « fra », « eng »)."""
    r = subprocess.run([exe, "--list-langs"], capture_output=True, timeout=30, **_options())
    lignes = r.stdout.decode("utf-8", "replace").splitlines()[1:]      # la 1re ligne est un titre
    return {ligne.strip() for ligne in lignes if ligne.strip()}


def langues_manquantes(exe: str, langue: str) -> list:
    """Parmi « fra+eng », celles qui ne sont pas installées."""
    voulues = [x for x in langue.split("+") if x]
    presentes = langues(exe)
    return [x for x in voulues if x not in presentes]


def nettoyer(texte: str) -> str:
    texte = texte.replace("\x0c", "\n")
    texte = "\n".join(ligne.rstrip() for ligne in texte.splitlines())
    return re.sub(r"\n{3,}", "\n\n", texte).strip()[:TEXTE_MAX]


def reconnaitre(exe: str, donnees: bytes, langue: str = "fra") -> str:
    """Texte lu dans une image (PNG/JPEG). RuntimeError avec le message de Tesseract en cas d'échec."""
    r = subprocess.run([exe, "stdin", "stdout", "-l", langue or "fra"], input=donnees, capture_output=True,
                       timeout=DELAI, **_options())
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", "replace").strip()[:400] or f"tesseract a échoué (code {r.returncode})")
    return nettoyer(r.stdout.decode("utf-8", "replace"))


def aide_installation() -> str:
    if sys.platform.startswith("win"):
        return ("Windows : installez Tesseract (installateur de l'université de Mannheim, lien sur la page "
                "github.com/tesseract-ocr/tesseract), en cochant la langue « French », puis indiquez le chemin de "
                "tesseract.exe dans les réglages de l'extension.")
    if sys.platform == "darwin":
        return "macOS : brew install tesseract tesseract-lang"
    return "Linux (Debian/Ubuntu) : sudo apt install tesseract-ocr tesseract-ocr-fra"

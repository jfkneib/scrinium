# -*- mode: python ; coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
#
# RECETTE PYINSTALLER : comment transformer Scrinium (un programme Python) en un dossier qui marche sur un Windows
# où Python n'est PAS installé.
#
# Idée : PyInstaller examine le programme, repère tout ce qu'il utilise (Python lui-même, Qt, les bibliothèques de
# chiffrement…) et range le tout dans un dossier avec un `scrinium.exe`. On le lance depuis la racine du dépôt :
#
#     pyinstaller packaging/windows/scrinium.spec --noconfirm
#
# IMPORTANT : Scrinium doit être INSTALLÉ (`pip install .`) avant de lancer PyInstaller, pas seulement présent dans src/ :
# c'est l'installation qui fabrique les traductions (.mo) et copie les extensions dans le paquet.
#
# Résultat : dist/scrinium/  (à copier tel quel, ou à emballer dans un installateur : voir scrinium.nsi).
#
# Ce fichier est du Python ordinaire ; PyInstaller y injecte quelques noms (Analysis, PYZ, EXE, COLLECT, SPECPATH).
import ast
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

RACINE = Path(SPECPATH).resolve().parent.parent          # SPECPATH = dossier de ce fichier ; on remonte à la racine du dépôt
ICONE = Path(SPECPATH) / "scrinium.ico"                  # fabriquée par faire_icone.py (peut manquer : alors icône par défaut)

# ---------------------------------------------------------------------------------------------------------------------
# 1. Les fichiers qui ne sont pas du code Python « importé » mais dont Scrinium a besoin
# ---------------------------------------------------------------------------------------------------------------------
# - scrinium/icons/*.svg       : les icônes de l'interface
# - scrinium/locale/*/….mo     : les traductions (fabriquées à l'installation du paquet par setup.py)
# - scrinium/plugins_officiels : les extensions livrées avec Scrinium. Scrinium les LIT comme des dossiers (plugin.json
#   puis __init__.py chargé à la demande) : ce ne sont pas des modules importés normalement. Il faut donc embarquer
#   leurs fichiers .py TELS QUELS (include_py_files=True), sinon la liste des extensions serait vide.
datas = collect_data_files("scrinium", include_py_files=True)
# collect_data_files(include_py_files=True) ajoute aussi tout le code de Scrinium en double (déjà compilé par ailleurs) :
# on ne garde les .py que pour les extensions.
datas = [(src, dest) for src, dest in datas if not src.endswith(".py") or "plugins_officiels" in dest.replace("\\", "/")]

# ---------------------------------------------------------------------------------------------------------------------
# 2. Les modules que PyInstaller ne peut pas deviner
# ---------------------------------------------------------------------------------------------------------------------
# PyInstaller ne suit que les « import » qu'il voit dans le programme. Or les extensions sont chargées dynamiquement :
# leurs propres « import » (smtplib pour le courriel, PyQt6.QtSvg, uuid pour l'agenda…) lui échappent. On lit donc le code
# de chaque extension, on relève ce qu'elle importe, et on le déclare « hiddenimports » (importations cachées).
hiddenimports = collect_submodules("scrinium")           # tout Scrinium, y compris ce qui n'est chargé qu'à la demande


def imports_des_extensions() -> set:
    trouves = set()
    for fichier in (RACINE / "plugins").glob("*/*.py"):
        if fichier.parent.name == "hello":               # l'extension d'exemple n'est pas livrée
            continue
        for noeud in ast.walk(ast.parse(fichier.read_text(encoding="utf-8"))):
            if isinstance(noeud, ast.Import):
                trouves.update(a.name for a in noeud.names)
            elif isinstance(noeud, ast.ImportFrom) and noeud.module and noeud.level == 0:   # level 0 = pas un import relatif
                trouves.add(noeud.module)
    return trouves


hiddenimports += sorted(m for m in imports_des_extensions() if not m.startswith("scrinium"))

# ---------------------------------------------------------------------------------------------------------------------
# 3. Analyse : PyInstaller examine le script d'entrée et rassemble tout ce qu'il faut
# ---------------------------------------------------------------------------------------------------------------------
a = Analysis(
    [str(Path(SPECPATH) / "lanceur.py")],                # le script à lancer (voir lanceur.py)
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "unittest", "pydoc"],           # inutiles ici : le programme est plus léger sans eux
)
pyz = PYZ(a.pure)                                        # l'archive qui contient tout le code Python compilé

# ---------------------------------------------------------------------------------------------------------------------
# 4. Deux programmes qui partagent les mêmes fichiers
# ---------------------------------------------------------------------------------------------------------------------
# - scrinium.exe     : le programme graphique (console=False : aucune fenêtre noire ne s'ouvre derrière).
# - scrinium-cli.exe : le même code, MAIS avec une console : indispensable pour `scrinium ajouter`, `scrinium rescue`,
#   `--version`, `--help`, dont le résultat s'affiche dans le terminal (un programme « sans console » n'affiche rien).
exe_gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name="scrinium", console=False,
              icon=str(ICONE) if ICONE.exists() else None)
exe_cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name="scrinium-cli", console=True,
              icon=str(ICONE) if ICONE.exists() else None)

# COLLECT range les deux programmes et leurs fichiers dans UN dossier : dist/scrinium/
coll = COLLECT(exe_gui, exe_cli, a.binaries, a.datas, strip=False, upx=False, name="scrinium")

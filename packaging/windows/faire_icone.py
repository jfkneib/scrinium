# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Fabrique `scrinium.ico` (l'icône du programme Windows) à partir de l'icône vectorielle du projet.

Windows veut une icône au format .ico ; le projet n'a qu'un fichier .svg. Qt sait dessiner un SVG et enregistrer en .ico :
on s'en sert. Si ça échoue, la construction continue sans icône personnalisée (le .exe aura l'icône par défaut).
Usage : python faire_icone.py <fichier.svg> <sortie.ico>"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")      # pas d'écran sur la machine de construction

from PyQt6.QtGui import QGuiApplication, QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer


def main(svg: str, ico: str) -> int:
    app = QGuiApplication(sys.argv[:1])                    # Qt exige une application avant de dessiner
    rendu = QSvgRenderer(svg)
    if not rendu.isValid():
        print("SVG illisible :", svg)
        return 1
    image = QImage(256, 256, QImage.Format.Format_ARGB32)  # 256 px : taille maximale d'une icône Windows
    image.fill(0)                                          # fond transparent
    p = QPainter(image)
    rendu.render(p)
    p.end()
    ok = image.save(ico, "ICO")
    print("icône écrite :" if ok else "échec d'écriture de l'icône :", ico)
    del app
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2]))

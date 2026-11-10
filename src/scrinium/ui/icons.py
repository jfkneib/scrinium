# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Icônes : thème du système d'abord (KDE/GNOME), sinon jeu embarqué (Breeze, LGPL) recoloré selon le thème clair/sombre."""
from pathlib import Path

from PyQt6.QtCore import QByteArray, QPointF, Qt
from PyQt6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

DOSSIER = Path(__file__).resolve().parent.parent / "icons"
_cache: dict = {}


def _depuis_svg(nom: str) -> QIcon:
    f = DOSSIER / f"{nom}.svg"
    if not f.exists():
        return QIcon()
    couleur = QGuiApplication.palette().color(QGuiApplication.palette().ColorRole.WindowText).name()
    svg = f.read_text(encoding="utf-8").replace("#232629", couleur)
    rend = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    icone = QIcon()
    for taille in (16, 22, 32, 48):
        pm = QPixmap(taille * 2, taille * 2)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        rend.render(p)
        p.end()
        pm.setDevicePixelRatio(2)
        icone.addPixmap(pm)
    return icone


def icone(nom: str) -> QIcon:
    if nom in _cache:
        return _cache[nom]
    ic = QIcon.fromTheme(nom)
    if ic.isNull():
        ic = _depuis_svg(nom)
    _cache[nom] = ic
    return ic


def icone_appli() -> QIcon:
    return QIcon(str(DOSSIER / "scrinium.svg"))


def avec_epingle(nom: str = "") -> QIcon:
    """Icône `nom` (ou aucune, si vide) marquée d'une punaise en bas à droite : thème ou fiche épinglé."""
    cle = ("epingle", nom)
    if cle in _cache:
        return _cache[cle]
    punaise = icone("epingle")
    base = icone(nom) if nom else QIcon()
    res = QIcon()
    for taille in (16, 22, 32, 48):
        pm = QPixmap(taille * 2, taille * 2)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        if not base.isNull():
            p.drawPixmap(0, 0, base.pixmap(taille * 2, taille * 2))
            cote = int(taille * 2 * 0.62)
            p.drawPixmap(taille * 2 - cote, taille * 2 - cote, punaise.pixmap(cote, cote))
        else:
            p.drawPixmap(0, 0, punaise.pixmap(taille * 2, taille * 2))
        p.end()
        pm.setDevicePixelRatio(2)
        res.addPixmap(pm)
    _cache[cle] = res
    return res


def avec_pastille(nom: str = "", epingle: bool = False) -> QIcon:
    """Icône `nom` (ou la punaise seule si épinglée sans icône) avec une pastille rouge en haut à droite : « il y a quelque chose à faire »."""
    cle = ("pastille", nom, epingle)
    if cle in _cache:
        return _cache[cle]
    base = avec_epingle(nom) if epingle else (icone(nom) if nom else QIcon())
    res = QIcon()
    for taille in (16, 22, 32, 48):
        pm = QPixmap(taille * 2, taille * 2)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not base.isNull():
            p.drawPixmap(0, 0, base.pixmap(taille * 2, taille * 2))
        r = taille * 2 * 0.26
        c = taille * 2 - r - 1
        p.setBrush(QColor("#ffffff"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(c, r + 1), r + 1.5, r + 1.5)
        p.setBrush(QColor("#e53935"))
        p.drawEllipse(QPointF(c, r + 1), r, r)
        p.end()
        pm.setDevicePixelRatio(2)
        res.addPixmap(pm)
    _cache[cle] = res
    return res

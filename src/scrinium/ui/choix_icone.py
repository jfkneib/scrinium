# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Choix de l'icône d'un thème : liste déroulante (avec un aperçu de chaque icône) et aperçu agrandi de l'icône choisie."""
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QVBoxLayout

from ..i18n import _
from .icons import DOSSIER, icone

# Noms courants du thème d'icônes du système ; ceux qui n'existent pas sur la machine ne sont pas proposés.
COURANTES = ("folder-documents", "folder", "folder-open", "folder-download", "folder-pictures", "folder-music", "folder-video",
             "phone", "network-wired", "network-server", "applications-development", "applications-games", "applications-internet",
             "applications-multimedia", "applications-office", "applications-system", "applications-utilities", "system-help",
             "preferences-system", "utilities-terminal", "accessories-calculator", "accessories-text-editor", "mail-send",
             "x-office-address-book", "x-office-calendar", "emblem-favorite", "emblem-important", "dialog-information", "user-home",
             "view-pim-notes", "view-pim-tasks", "document-edit", "audio-headphones", "camera-photo", "media-optical", "drive-harddisk",
             "computer", "printer", "security-high", "object-locked", "applications-science", "applications-education")


def icones_proposees(actuelle: str = "") -> list:
    """Noms d'icônes affichables : jeu embarqué, noms courants du système, et l'icône actuelle (même inconnue)."""
    noms = [f.stem for f in sorted(DOSSIER.glob("*.svg")) if f.stem != "scrinium"]
    noms += [n for n in COURANTES if n not in noms]
    noms = [n for n in noms if not icone(n).isNull()]
    if actuelle and actuelle not in noms:
        noms.insert(0, actuelle)
    return noms


class DialogueIcone(QDialog):
    def __init__(self, parent, theme_nom: str, actuelle: str):
        super().__init__(parent)
        self.setWindowTitle(_("Icône du thème"))
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(_("Icône de « %s » :") % theme_nom))
        ligne = QHBoxLayout()
        self.choix = QComboBox()
        self.choix.setEditable(True)           # on peut taper un autre nom du thème d'icônes du système
        self.choix.setIconSize(QSize(20, 20))
        for n in icones_proposees(actuelle):
            self.choix.addItem(icone(n), n)
        self.choix.setCurrentText(actuelle)
        self.apercu = QLabel()
        self.apercu.setFixedSize(52, 52)
        self.apercu.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.apercu.setFrameShape(QLabel.Shape.StyledPanel)
        ligne.addWidget(self.choix, 1)
        ligne.addWidget(self.apercu)
        lay.addLayout(ligne)
        lay.addWidget(QLabel(_("Vous pouvez aussi taper le nom d'une icône du thème d'icônes de votre système.")))
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok = b.button(QDialogButtonBox.StandardButton.Ok)
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        lay.addWidget(b)
        self.choix.currentTextChanged.connect(self._maj)
        self._maj(actuelle)

    def _maj(self, nom: str):
        ic = icone(nom.strip()) if nom.strip() else None
        valide = ic is not None and not ic.isNull()
        if valide:
            self.apercu.setPixmap(ic.pixmap(40, 40))
        else:
            self.apercu.clear()
            self.apercu.setText("?")
        self.ok.setEnabled(valide)

    def nom(self) -> str:
        return self.choix.currentText().strip()

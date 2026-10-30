# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Fenêtre de validation d'un lien `scrinium://ajouter` : l'utilisateur voit et peut corriger ce qui sera ajouté. Rien n'est écrit avant."""
from PyQt6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout)

from ..i18n import _


class DialogueAjoutLien(QDialog):
    def __init__(self, parent, demande: dict, themes: list, theme_defaut: str):
        super().__init__(parent)
        self.setWindowTitle(_("Ajouter une fiche depuis un lien"))
        self.resize(520, 420)
        lay = QVBoxLayout(self)
        avert = QLabel(_("Un lien (navigateur, autre programme) demande d'ajouter la fiche ci-dessous. Vérifiez-la : rien n'est "
                         "enregistré tant que vous n'avez pas cliqué sur « Ajouter »."))
        avert.setWordWrap(True)
        lay.addWidget(avert)
        form = QFormLayout()
        self.theme = QComboBox()
        self.theme.setEditable(True)                          # un nom nouveau crée le thème
        self.theme.addItems(themes)
        self.theme.setCurrentText(demande.get("theme") or theme_defaut)
        self.titre = QLineEdit(demande.get("titre", ""))
        self.titre.setPlaceholderText(_("(première ligne du texte)"))
        form.addRow(_("Thème :"), self.theme)
        form.addRow(_("Titre :"), self.titre)
        lay.addLayout(form)
        self.texte = QPlainTextEdit(demande.get("texte", ""))      # du texte brut : jamais interprété comme du HTML
        lay.addWidget(self.texte, 1)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.ajouter = b.addButton(_("Ajouter"), QDialogButtonBox.ButtonRole.AcceptRole)
        b.accepted.connect(self._valider)
        b.rejected.connect(self.reject)
        b.button(QDialogButtonBox.StandardButton.Cancel).setDefault(True)     # Entrée n'ajoute pas : il faut cliquer sur « Ajouter »
        self.ajouter.setAutoDefault(False)
        lay.addWidget(b)

    def _valider(self):
        if self.titre.text().strip() or self.texte.toPlainText().strip():
            self.accept()

    def resultat(self) -> tuple[str, str, str]:
        return self.theme.currentText().strip(), self.titre.text().strip(), self.texte.toPlainText()

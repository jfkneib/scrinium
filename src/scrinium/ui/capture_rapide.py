# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Capture rapide : petite fenêtre « note rapide » qui ajoute du texte à une fiche sans ouvrir la fenêtre principale.

Appelée par `scrinium --rapide` (à lier à un raccourci clavier du bureau), le menu Fichier ou la zone de notification.
Ctrl+Entrée enregistre, Échap annule. Une fiche verrouillée fermée n'est jamais écrite (refus avec message)."""
import time

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                             QVBoxLayout)

from ..i18n import N_, _

THEME_DEFAUT = N_("Sous le coude")    # thème proposé même s'il n'existe pas encore (créé à l'enregistrement)
TITRE_DEFAUT = N_("Notes rapides")      # titre de la fiche de destination tant qu'on n'en a pas choisi une autre


class CaptureRapide(QDialog):
    def __init__(self, fenetre):
        super().__init__(None)                       # sans parent : la fenêtre principale (peut-être cachée) ne s'affiche pas
        self.f = fenetre
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle(_("Capture rapide"))
        self.resize(480, 300)
        lay = QVBoxLayout(self)
        self.texte = QPlainTextEdit()
        self.texte.setPlaceholderText(_("Tapez ou collez ; Ctrl+Entrée pour enregistrer, Échap pour annuler."))
        lay.addWidget(self.texte, 1)
        form = QFormLayout()
        self.theme = QComboBox()
        self.theme.setEditable(True)
        self.theme.setToolTip(_("Thème existant, ou tapez un nom pour le créer."))
        noms = [t.nom for t in fenetre.store.themes]
        self.theme.addItems(noms + ([] if _(THEME_DEFAUT) in noms else [_(THEME_DEFAUT)]))
        self.fiche = QComboBox()
        self.fiche.setEditable(True)
        self.fiche.setToolTip(_("Fiche existante, ou tapez un titre pour en créer une."))
        form.addRow(_("Thème"), self.theme)
        form.addRow(_("Fiche"), self.fiche)
        lay.addLayout(form)
        self.horodate = QCheckBox(_("Ajouter la date et l'heure"))
        self.horodate.setChecked(bool(fenetre.store.reglages().get("capture_rapide", {}).get("horodate", True)))
        lay.addWidget(self.horodate)
        self.erreur = QLabel("")
        self.erreur.setStyleSheet("color: #b00020;")
        self.erreur.setWordWrap(True)
        lay.addWidget(self.erreur)
        rang = QHBoxLayout()
        rang.addStretch()
        annuler = QPushButton(_("Annuler"))
        annuler.clicked.connect(self.close)
        self.b_ok = QPushButton(_("Enregistrer"))
        self.b_ok.setDefault(False)
        self.b_ok.clicked.connect(self.enregistrer)
        rang.addWidget(annuler)
        rang.addWidget(self.b_ok)
        lay.addLayout(rang)
        pref = fenetre.store.reglages().get("capture_rapide", {})
        i = self.theme.findText(pref.get("theme", ""))
        self.theme.setCurrentIndex(i if i >= 0 else self.theme.count() - 1 if _(THEME_DEFAUT) not in noms else 0)
        self.theme.editTextChanged.connect(self._remplir_fiches)
        self._remplir_fiches(self.theme.currentText(), pref.get("fiche", _(TITRE_DEFAUT)))
        self.texte.setFocus()

    def _theme_existant(self, nom: str):
        nom = nom.strip().lower()
        return next((t for t in self.f.store.themes if t.nom.lower() == nom), None)

    def _remplir_fiches(self, theme: str, choix: str | None = None):
        th = self._theme_existant(theme)
        self.fiche.clear()
        if th is not None:
            self.fiche.addItems([x.titre for x in th.fiches if not x.verrou])      # jamais de fiche verrouillée proposée
        self.fiche.setEditText(choix if choix is not None else _(TITRE_DEFAUT))

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.enregistrer()
        else:
            super().keyPressEvent(ev)

    def enregistrer(self) -> bool:
        texte = self.texte.toPlainText().strip()
        if not texte:
            self.erreur.setText(_("Rien à enregistrer."))
            return False
        entete = f"### {time.strftime('%Y-%m-%d %H:%M')}\n" if self.horodate.isChecked() else ""
        nom = self.theme.currentText().strip()
        if not nom:
            self.erreur.setText(_("Choisissez ou tapez un thème."))
            return False
        if not self.fiche.currentText().strip():
            self.erreur.setText(_("Choisissez ou tapez un titre de fiche."))
            return False
        th = self._theme_existant(nom)
        if th is None:                                    # nom tapé qui n'existe pas : le thème est créé
            try:
                th = self.f.store.nouveau_theme(nom)
            except OSError as ex:
                self.erreur.setText(str(ex))
                return False
        erreur = self.f.ajouter_depuis_cli({"theme": th.nom, "fiche": self.fiche.currentText(),
                                            "texte": entete + texte, "brut": True})
        if erreur:
            self.erreur.setText(erreur)
            return False
        self.f.store.sauver_reglages(capture_rapide={"theme": th.nom, "fiche": self.fiche.currentText().strip(),
                                                      "horodate": self.horodate.isChecked()})
        self.close()
        return True

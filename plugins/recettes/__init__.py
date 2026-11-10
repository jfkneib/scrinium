# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « Recettes » : ingrédients, étapes, temps, étiquettes, note ; quantités recalculées pour N personnes (voir `logique.py`).
Type non exécutable : la fiche ne lance rien."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QSplitter, QVBoxLayout, QWidget

from scrinium.core.plugins import Plugin
from scrinium.i18n import _
from scrinium.ui.icons import icone

from . import logique


class VueRecettes(QWidget):
    modifie = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.actif = True
        self._remplit = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        haut = QHBoxLayout()
        self.base = QSpinBox()
        self.base.setRange(1, logique.MAX_PERSONNES)
        self.base.setSuffix(_(" personne(s)"))
        self.temps = QLineEdit()
        self.temps.setPlaceholderText(_("40 min"))
        self.temps.setMaximumWidth(110)
        self.etiquettes = QLineEdit()
        self.etiquettes.setPlaceholderText(_("dessert, rapide"))
        self.note = QComboBox()
        self.note.addItem(_("sans note"), 0)
        for n in range(1, 6):
            self.note.addItem(logique.etoiles(n), n)
        for libelle, w in ((_("Recette prévue pour"), self.base), (_("Temps"), self.temps), (_("Étiquettes"), self.etiquettes), (_("Note"), self.note)):
            haut.addWidget(QLabel(libelle))
            haut.addWidget(w, 1 if w is self.etiquettes else 0)
        lay.addLayout(haut)
        cadre = QSplitter(Qt.Orientation.Horizontal)
        self.ingredients = QPlainTextEdit()
        self.ingredients.setPlaceholderText(_("Un ingrédient par ligne, la quantité d'abord :\n200 g de farine\n3 œufs\n1/2 litre de lait"))
        self.etapes = QPlainTextEdit()
        self.etapes.setPlaceholderText(_("Une étape par ligne."))
        for titre, w in ((_("Ingrédients"), self.ingredients), (_("Étapes"), self.etapes)):
            bloc = QWidget()
            v = QVBoxLayout(bloc)
            v.setContentsMargins(0, 0, 0, 0)
            v.addWidget(QLabel("<b>%s</b>" % titre))
            v.addWidget(w)
            cadre.addWidget(bloc)
        lay.addWidget(cadre, 3)
        bas = QHBoxLayout()
        bas.addWidget(QLabel("<b>%s</b>" % _("Pour")))
        self.pour = QSpinBox()
        self.pour.setRange(1, logique.MAX_PERSONNES)
        self.pour.setSuffix(_(" personne(s)"))
        self.pour.valueChanged.connect(lambda *_a: self._courses())
        bas.addWidget(self.pour)
        self.b_copier = QPushButton(icone("edit-copy"), _("Copier la liste de courses"))
        self.b_copier.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.courses.toPlainText()))
        bas.addWidget(self.b_copier)
        bas.addStretch(1)
        lay.addLayout(bas)
        self.courses = QPlainTextEdit()
        self.courses.setReadOnly(True)
        self.courses.setMaximumHeight(130)
        lay.addWidget(self.courses)
        for w in (self.temps, self.etiquettes):
            w.textChanged.connect(self._change)
        for w in (self.ingredients, self.etapes):
            w.textChanged.connect(self._change)
        self.base.valueChanged.connect(self._change)
        self.note.currentIndexChanged.connect(self._change)

    def _recette(self) -> logique.Recette:
        return logique.lire(logique.ecrire(logique.Recette(
            self.base.value(), self.temps.text(), [e for e in self.etiquettes.text().split(",")], self.note.currentData() or 0,
            self.ingredients.toPlainText().splitlines(), self.etapes.toPlainText().splitlines())))

    def charger(self, texte: str):
        r = logique.lire(texte)
        self._remplit = True
        try:
            self.base.setValue(r.personnes)
            self.pour.setValue(r.personnes)
            self.temps.setText(r.temps)
            self.etiquettes.setText(", ".join(r.etiquettes))
            self.note.setCurrentIndex(max(0, self.note.findData(r.note)))
            self.ingredients.setPlainText("\n".join(r.ingredients))
            self.etapes.setPlainText("\n".join(r.etapes))
        finally:
            self._remplit = False
        self._courses()

    def _change(self, *_a):
        if self._remplit:
            return
        self.modifie.emit(logique.ecrire(self._recette()))
        self._courses()

    def _courses(self):
        r = self._recette()
        self.courses.setPlainText("\n".join("- " + i for i in logique.pour(r, self.pour.value())))


class RecettesPlugin(Plugin):
    api = 1

    def activer(self, ctx):
        ctx.ajouter_doc(_("Extension Recettes"), DOC)
        for theme, titre, texte in logique.exemples():
            ctx.ajouter_exemple(theme, titre, texte, "folder-cookbook")
        if ctx.ui is not None:
            ctx.ui.enregistrer_type(logique.TYPE, VueRecettes())


DOC = _(
    "Une recette par fiche : ingrédients, étapes, temps, étiquettes et note.\n"
    "\n"
    "• Nouvelle fiche > « Recette » : indiquez pour combien de personnes elle est prévue, écrivez un ingrédient par ligne (la quantité d'abord : "
    "« 200 g de farine », « 1/2 litre de lait », « 1,5 kg ») et une étape par ligne.\n"
    "• En bas : « Pour N personnes » recalcule toutes les quantités (une ligne sans quantité au début, comme « sel », reste telle quelle) et "
    "« Copier la liste de courses » met la liste recalculée dans le presse-papiers. Les mots ne sont pas accordés (« 1 œuf » devient « 2 œuf »).\n"
    "• Le texte reste un document Markdown lisible, cherchable et partageable ; rien n'est exécuté.")

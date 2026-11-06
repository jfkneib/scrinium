# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « Calculatrice » : une mini calculatrice flottante (voir `logique.py` pour le calcul, sûr : aucun code n'est exécuté).

Bouton « Mini calculatrice » (icône de la barre d'outils) ou menu Extensions : pavé de touches et clavier ; « Insérer le résultat » au curseur de
la fiche affichée. La sélection de la fiche (par exemple « 12*8 ») est reprise à l'ouverture. Pour suivre des données, voir « Calc » (listes)
et « Tableur » (cellules et formules)."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from scrinium.core.plugins import Plugin
from scrinium.i18n import _
from scrinium.ui.icons import icone

from . import logique


def _evaluer(expr: str):
    """(texte du résultat, None) ou (None, message d'erreur traduit)."""
    try:
        return logique.calcul_texte(expr), None
    except logique.ErreurCalcul as ex:
        return None, _(str(ex))


TOUCHES = [["C", "(", ")", "÷"], ["7", "8", "9", "×"], ["4", "5", "6", "−"], ["1", "2", "3", "+"], ["0", ".", "%", "="]]


class MiniCalculatrice(QDialog):
    """Petite calculatrice flottante (non modale) : pavé, saisie au clavier, « Insérer le résultat » au curseur de la fiche."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle(_("Calculatrice"))
        self.setWindowFlag(Qt.WindowType.Tool, True)
        lay = QVBoxLayout(self)
        self.saisie = QLineEdit()
        self.saisie.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.saisie.returnPressed.connect(self.egal)
        self.saisie.textChanged.connect(self._apercu)
        lay.addWidget(self.saisie)
        self.resultat = QLabel(" ")
        self.resultat.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.resultat.setStyleSheet("font-size: 20px;")
        self.resultat.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.resultat)
        grille = QGridLayout()
        for r, ligne in enumerate(TOUCHES):
            for c, t in enumerate(ligne):
                b = QPushButton(t)
                b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                b.clicked.connect(lambda *_a, t=t: self.touche(t))
                grille.addWidget(b, r, c)
        lay.addLayout(grille)
        bas = QHBoxLayout()
        self.b_inserer = QPushButton(icone("edit-paste"), _("Insérer le résultat"))
        self.b_inserer.clicked.connect(self.inserer)
        self.b_copier = QPushButton(icone("edit-copy"), _("Copier"))
        self.b_copier.clicked.connect(self.copier)
        bas.addWidget(self.b_inserer)
        bas.addWidget(self.b_copier)
        lay.addLayout(bas)
        self.statut = QLabel()
        lay.addWidget(self.statut)

    def ouvrir(self):
        """Affiche la calculatrice ; reprend la sélection de la fiche si elle ressemble à un calcul."""
        sel = self.ctx.ui.texte_selectionne().strip() if self.ctx.ui is not None else ""
        if sel and "\n" not in sel and logique_ok(sel):
            self.saisie.setText(sel)
        self.show()
        self.raise_()
        self.activateWindow()
        self.saisie.setFocus()

    def touche(self, t: str):
        if t == "C":
            self.saisie.clear()
        elif t == "=":
            self.egal()
        else:
            self.saisie.insert(t)

    def _apercu(self, expr: str):
        self.statut.clear()
        res, err = _evaluer(expr) if expr.strip() else (None, None)
        self.resultat.setText(("= " + res) if res is not None else " ")

    def egal(self):
        res, err = _evaluer(self.saisie.text())
        if err is not None:
            self.resultat.setText(err)
        else:
            self.saisie.setText(res)               # on peut enchaîner avec le résultat

    def valeur(self):
        """Résultat courant (texte) ou None."""
        return _evaluer(self.saisie.text())[0]

    def inserer(self):
        res = self.valeur()
        if res is None:
            self.statut.setText(_("Rien à insérer."))
        elif self.ctx.ui.inserer_texte(res):
            self.statut.setText(_("Résultat inséré dans la fiche."))
        else:
            self.statut.setText(_("Aucune fiche modifiable : ouvrez une fiche, puis cliquez dans sa note."))

    def copier(self):
        res = self.valeur()
        if res is not None:
            QApplication.clipboard().setText(res)
            self.statut.setText(_("Copié dans le presse-papiers."))


DOC = _(
    "Une mini calculatrice flottante pour un calcul rapide, sans quitter votre fiche.\n"
    "\n"
    "• Bouton « Mini calculatrice » (icône de la barre d'outils) ou menu Extensions. Pavé de touches ou clavier ; Entrée donne le résultat, "
    "qu'on peut enchaîner.\n"
    "• Si du texte comme « 12*8 » est sélectionné dans la fiche, il est repris à l'ouverture. « Insérer le résultat » le place au curseur de "
    "la fiche ; « Copier » le met dans le presse-papiers.\n"
    "\n"
    "Calculs permis : + − × ÷, ^ (puissance), %, parenthèses, pi, e et sqrt, abs, round, min, max, sin, cos, tan, ln, log, exp, floor, "
    "ceil. « 200*20% » donne 40. La virgule décimale est acceptée (1,5). Rien n'est exécuté : seules ces opérations sont comprises.\n"
    "• Pour suivre des données : extensions Calc (listes avec totaux) et Tableur (cellules et formules).")


def logique_ok(expr: str) -> bool:
    return _evaluer(expr)[1] is None


class CalculatricePlugin(Plugin):
    api = 1

    def activer(self, ctx):
        self.ctx = ctx
        self.mini = None
        if ctx.ui is None:
            return
        ctx.ui.ajouter_bouton(_("Mini calculatrice"), self.ouvrir_mini, "accessories-calculator")
        ctx.ui.ajouter_action(_("Mini calculatrice"), self.ouvrir_mini, "accessories-calculator")
        ctx.ajouter_doc(_("Extension Calculatrice"), DOC)

    def ouvrir_mini(self):
        if self.mini is None:
            self.mini = MiniCalculatrice(self.ctx, QApplication.activeWindow())
        self.mini.ouvrir()

    def desactiver(self):
        if getattr(self, "mini", None) is not None:
            self.mini.close()
            self.mini = None

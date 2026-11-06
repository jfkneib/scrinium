# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « Calculatrice » (voir `logique.py` pour le calcul, sûr : aucun code n'est exécuté).

- Une fiche d'un nouveau type, `calculatrice` (`#scrinium-calculatrice`) : on tape un calcul, Entrée donne le résultat, et la ligne
  « calcul = résultat » est ajoutée à la fiche. Un double-clic sur une ligne de l'historique remet le calcul dans la zone de saisie.
  « Nouvelle fiche » (flèche du bouton « Fiche ») → « Calculatrice ».
- Une mini calculatrice flottante (bouton « Calc » de la barre d'outils, ou menu Extensions) : pavé de touches, « Insérer le résultat »
  au curseur de la fiche affichée. La sélection de la fiche (par exemple « 12*8 ») y est reprise à l'ouverture."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QApplication, QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
                             QVBoxLayout, QWidget)

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


class VueCalculatrice(QWidget):
    """Vue du type « calculatrice » : saisie, résultat et historique (stocké dans le texte de la fiche)."""
    modifie = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.texte = ""
        self.actif = True                       # type non exécutable : toujours utilisable
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.saisie = QLineEdit()
        self.saisie.setPlaceholderText(_("Tapez un calcul, par exemple 2+3*4 ou sqrt(16), puis Entrée"))
        self.saisie.returnPressed.connect(self.valider)
        self.saisie.textChanged.connect(self._apercu)
        lay.addWidget(self.saisie)
        self.resultat = QLabel()
        self.resultat.setStyleSheet("font-size: 20px;")
        self.resultat.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.resultat)
        self.liste = QListWidget()
        self.liste.itemActivated.connect(self._reprendre)
        self.liste.itemDoubleClicked.connect(self._reprendre)
        lay.addWidget(self.liste, 1)
        bas = QHBoxLayout()
        self.b_effacer = QPushButton(icone("edit-clear-history"), _("Effacer l'historique"))
        self.b_effacer.clicked.connect(self.effacer)
        bas.addStretch(1)
        bas.addWidget(self.b_effacer)
        lay.addLayout(bas)

    def charger(self, texte: str):
        self.texte = texte or ""
        self.saisie.clear()
        self.resultat.clear()
        self.liste.clear()
        for calcul, res in logique.historique(self.texte):
            it = QListWidgetItem(f"{calcul} = {res}")
            it.setData(Qt.ItemDataRole.UserRole, calcul)
            self.liste.addItem(it)
        self.liste.scrollToBottom()

    def _apercu(self, expr: str):
        if not expr.strip():
            self.resultat.clear()
            return
        res, err = _evaluer(expr)
        self.resultat.setText("= " + res if err is None else "")

    def valider(self):
        expr = self.saisie.text()
        res, err = _evaluer(expr)
        if err is not None:
            self.resultat.setText(err)
            return
        self.texte = logique.ajouter(self.texte, expr, res)
        self.modifie.emit(self.texte)
        self.charger(self.texte)
        self.resultat.setText("= " + res)

    def _reprendre(self, it):
        self.saisie.setText(it.data(Qt.ItemDataRole.UserRole))
        self.saisie.setFocus()

    def effacer(self):
        self.texte = logique.MARQUE + "\n"
        self.modifie.emit(self.texte)
        self.charger(self.texte)


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
    "Deux outils, une extension (Extensions > Gérer les extensions…).\n"
    "\n"
    "• Fiche « Calculatrice » : flèche du bouton « Fiche » > « Nouvelle fiche » > Calculatrice. Tapez un calcul, Entrée : la ligne "
    "« calcul = résultat » est ajoutée à la fiche (c'est l'historique, cherchable et partageable). Double-clic sur une ligne pour "
    "la reprendre.\n"
    "• Mini calculatrice : bouton « Calc » de la barre d'outils (ou menu Extensions). Pavé de touches ou clavier. Si du texte "
    "comme « 12*8 » est sélectionné dans la fiche, il est repris. « Insérer le résultat » le place au curseur de la fiche ; "
    "« Copier » le met dans le presse-papiers.\n"
    "\n"
    "Calculs permis : + − × ÷, ^ (puissance), %, parenthèses, pi, e et sqrt, abs, round, min, max, sin, cos, tan, ln, log, exp, floor, "
    "ceil. « 200*20% » donne 40. La virgule décimale est acceptée (1,5). Rien n'est exécuté : seules ces opérations sont comprises.")


def logique_ok(expr: str) -> bool:
    return _evaluer(expr)[1] is None


class CalculatricePlugin(Plugin):
    api = 1

    def activer(self, ctx):
        self.ctx = ctx
        self.mini = None
        if ctx.ui is None:
            return
        ctx.ui.enregistrer_type(logique.TYPE, VueCalculatrice())
        ctx.ui.ajouter_bouton(_("Calc"), self.ouvrir_mini, "accessories-calculator")
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

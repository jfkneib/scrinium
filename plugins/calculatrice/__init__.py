# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « Calculatrice » : une mini calculatrice flottante (voir `logique.py` pour le calcul, sûr : aucun code n'est exécuté).

Bouton « Mini calculatrice » (icône de la barre d'outils) ou menu Extensions : pavé de touches et clavier ; « Insérer le résultat » au curseur de
la fiche affichée. La sélection de la fiche (par exemple « 12*8 ») est reprise à l'ouverture. Pour suivre des données, voir « Calc » (listes)
et « Tableur » (cellules et formules)."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from scrinium.core.plugins import Plugin
from scrinium.i18n import _
from scrinium.ui.icons import icone

from . import logique


def _evaluer(expr: str, degres: bool = True):
    """(texte du résultat, None) ou (None, message d'erreur traduit)."""
    try:
        return logique.calcul_texte(expr, degres), None
    except logique.ErreurCalcul as ex:
        return None, _(str(ex))


# Touches du mode scientifique : (étiquette, texte inséré). Les angles suivent le bouton Deg / Rad.
SCIENTIFIQUES = [[("sin", "sin("), ("cos", "cos("), ("tan", "tan("), ("π", "pi"), ("e", "e")],
                 [("asin", "asin("), ("acos", "acos("), ("atan", "atan("), ("n!", "!"), ("|x|", "abs(")],
                 [("ln", "ln("), ("log", "log("), ("eˣ", "exp("), ("x²", "^2"), ("xʸ", "^")],
                 [("√", "sqrt("), ("∛", "cbrt("), ("1/x", "1/("), ("sinh", "sinh("), ("cosh", "cosh(")]]
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
        mode = QHBoxLayout()
        self.b_scientifique = QPushButton(_("Scientifique"))
        self.b_scientifique.setCheckable(True)
        self.b_scientifique.setChecked(bool(ctx.reglages.get("scientifique", False)))
        self.b_scientifique.toggled.connect(self._basculer_scientifique)
        self.b_angle = QPushButton()
        self.b_angle.setCheckable(True)
        self.b_angle.setChecked(bool(ctx.reglages.get("degres", True)))
        self.b_angle.setToolTip(_("Unité des angles pour sin, cos, tan, asin, acos, atan : degrés ou radians"))
        self.b_angle.toggled.connect(self._basculer_angle)
        mode.addWidget(self.b_scientifique)
        mode.addWidget(self.b_angle)
        lay.addLayout(mode)
        self.zone_sci = QWidget()
        grille_sci = QGridLayout(self.zone_sci)
        grille_sci.setContentsMargins(0, 0, 0, 0)
        for r, ligne in enumerate(SCIENTIFIQUES):
            for c, (nom, texte) in enumerate(ligne):
                b = QPushButton(nom)
                b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                b.clicked.connect(lambda *_a, texte=texte: self.touche(texte))
                grille_sci.addWidget(b, r, c)
        lay.addWidget(self.zone_sci)
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
        self._basculer_angle(self.b_angle.isChecked())
        self.zone_sci.setVisible(self.b_scientifique.isChecked())

    @property
    def degres(self) -> bool:
        return self.b_angle.isChecked()

    def _basculer_scientifique(self, on: bool):
        self.zone_sci.setVisible(on)
        self.ctx.reglages.set("scientifique", on)
        self.adjustSize()

    def _basculer_angle(self, deg: bool):
        self.b_angle.setText(_("Deg") if deg else _("Rad"))
        self.ctx.reglages.set("degres", deg)
        self._apercu(self.saisie.text())

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
        res, err = _evaluer(expr, self.degres) if expr.strip() else (None, None)
        self.resultat.setText(("= " + res) if res is not None else " ")

    def egal(self):
        res, err = _evaluer(self.saisie.text(), self.degres)
        if err is not None:
            self.resultat.setText(err)
        else:
            self.saisie.setText(res)               # on peut enchaîner avec le résultat

    def valeur(self):
        """Résultat courant (texte) ou None."""
        return _evaluer(self.saisie.text(), self.degres)[0]

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
    "• Bouton « Scientifique » : ajoute les fonctions sin, cos, tan, asin, acos, atan, ln, log, exp, racines, puissances, factorielle (n!), "
    "π et e. Le bouton « Deg / Rad » choisit l'unité des angles (degrés ou radians) ; le choix est retenu.\n"
    "• Si du texte comme « 12*8 » est sélectionné dans la fiche, il est repris à l'ouverture. « Insérer le résultat » le place au curseur de "
    "la fiche ; « Copier » le met dans le presse-papiers.\n"
    "\n"
    "On peut aussi taper : + − × ÷, ^ (puissance), %, parenthèses, pi, e, sqrt, cbrt, abs, round, min, max, sin, cos, tan, asin, acos, atan, "
    "sinh, cosh, tanh, ln, log (base 10), log2, exp, floor, ceil, rad, deg, 5! (factorielle). « 200*20% » donne 40, « sin(30) » donne 0,5 "
    "en degrés. La virgule décimale est acceptée (1,5). Rien n'est exécuté : seules ces opérations sont comprises.\n"
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

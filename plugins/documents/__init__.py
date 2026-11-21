# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « Documents » : une fiche = un fichier (texte, tableur, PDF…) gardé en pièce jointe, avec une description (voir `logique.py`).
La fiche reste une fiche : recherche, verrouillage (le fichier est chiffré avec elle), partage, synchronisation, corbeille. Type non exécutable :
l'extension n'ouvre aucun fichier d'elle-même."""
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from scrinium.core.plugins import Plugin
from scrinium.i18n import _

from . import logique

DOC = _(
    "Pour garder un fichier (lettre, tableur, PDF…) comme une fiche, avec une description.\n"
    "\n"
    "• Nouvelle fiche > « Fiche-document » : écrivez une description, puis « Ajouter le fichier… ». Le fichier garde son format d'origine.\n"
    "• La fiche s'utilise comme les autres : recherche dans le titre et la description, verrouillage (le fichier est alors chiffré avec la fiche), "
    "partage, synchronisation, corbeille.\n"
    "• « Remplacer le fichier… » garde l'ancienne version dans la corbeille. « Enregistrer sous… » en fait une copie (en clair).\n"
    "• Rien n'est ouvert ni lancé de lui-même : le type est inerte.")


class VueDocument(QWidget):
    """Vue du type `objet` : description (le texte de la fiche) et fichier joint. Contrat des vues de type : `charger`, `modifie`, `actif`."""
    modifie = pyqtSignal(str)

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.actif = True
        self._charge = False
        lay = QVBoxLayout(self)
        self.etat = QLabel("")
        self.etat.setWordWrap(True)
        lay.addWidget(self.etat)
        boutons = QHBoxLayout()
        self.b_ajout = QPushButton(_("Ajouter le fichier…"))
        self.b_ajout.clicked.connect(self.choisir)
        self.b_sous = QPushButton(_("Enregistrer sous…"))
        self.b_sous.clicked.connect(self.enregistrer_sous)
        boutons.addWidget(self.b_ajout)
        boutons.addWidget(self.b_sous)
        boutons.addStretch(1)
        lay.addLayout(boutons)
        self.desc = QPlainTextEdit()
        self.desc.setPlaceholderText(_("Description (facultative)"))
        self.desc.textChanged.connect(self._edite)
        lay.addWidget(self.desc, 1)

    # ----- contrat des vues -----
    def charger(self, texte: str) -> None:
        self._charge = True
        self.desc.setPlainText(logique.description(texte))
        self._charge = False
        self.rafraichir()

    def _edite(self) -> None:
        if not self._charge:
            self.modifie.emit(logique.texte_de(self.desc.toPlainText()))

    # ----- fichier joint -----
    def _piece(self):
        vue = self.ctx.fiche_courante()
        if vue is None:
            return None, None
        try:
            pieces = self.ctx.pieces(vue)
        except ValueError:
            return vue, None
        return vue, (pieces[0] if pieces else None)

    def rafraichir(self) -> None:
        vue, piece = self._piece()
        if piece is None:
            self.etat.setText(_("Aucun fichier joint."))
        else:
            unite, nombre = logique.taille_lisible(piece.taille)
            taille = (_("%s Ko") if unite == "ko" else _("%s Mo")) % nombre
            self.etat.setText(_("Fichier : %(nom)s (%(taille)s, %(type)s)") % {"nom": piece.nom, "taille": taille, "type": piece.type})
        self.b_ajout.setText(_("Ajouter le fichier…") if piece is None else _("Remplacer le fichier…"))
        self.b_sous.setEnabled(piece is not None)

    def choisir(self) -> None:
        vue, piece = self._piece()
        if vue is None:
            return
        chemin, _f = QFileDialog.getOpenFileName(self, _("Choisir le fichier"))
        if not chemin:
            return
        src = Path(chemin)
        try:
            if src.stat().st_size > logique.SOURCE_MAX:
                raise ValueError(_("Fichier trop volumineux."))
            donnees = src.read_bytes()
            type_ = logique.type_mime(src.name)
            if piece is None:
                self.ctx.ajouter_piece(vue, src.name, type_, donnees)
            else:
                self.ctx.remplacer_piece(vue, piece, type_, donnees)
        except (ValueError, OSError) as ex:
            QMessageBox.warning(self, _("Fiche-document"), str(ex))
        self.rafraichir()

    def enregistrer_sous(self) -> None:
        vue, piece = self._piece()
        if piece is None:
            return
        if vue.verrou and QMessageBox.question(
                self, _("Enregistrer sous"),
                _("La fiche est verrouillée : la copie sera enregistrée EN CLAIR. Continuer ?")) != QMessageBox.StandardButton.Yes:
            return
        chemin, _f = QFileDialog.getSaveFileName(self, _("Enregistrer le fichier"), Path(piece.nom).name or "document")
        if chemin:
            try:
                Path(chemin).write_bytes(self.ctx.lire_piece(vue, piece))
            except (ValueError, OSError) as ex:
                QMessageBox.warning(self, _("Fiche-document"), str(ex))


class DocumentsPlugin(Plugin):
    api = 1

    def activer(self, ctx):
        ctx.ajouter_doc(_("Extension Documents"), DOC)
        if ctx.ui is not None:
            vue = VueDocument(ctx)
            ctx.ui.enregistrer_type(logique.TYPE, vue)
            for evt in ("piece_jointe_ajoutee", "piece_jointe_modifiee", "piece_jointe_supprimee"):
                ctx.on(evt, lambda **_kw: vue.rafraichir())

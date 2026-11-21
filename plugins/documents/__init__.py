# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « Documents » : une fiche = un fichier (texte, tableur, PDF…) gardé en pièce jointe, avec une description (voir `logique.py`).
La fiche reste une fiche : recherche, verrouillage (le fichier est chiffré avec elle), partage, synchronisation, corbeille. Type non exécutable :
l'extension n'ouvre aucun fichier d'elle-même."""
import time
from pathlib import Path

from PyQt6.QtCore import QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
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
    "• Glissez des fichiers depuis votre gestionnaire de fichiers sur la fenêtre : chacun devient une fiche-document du thème affiché, titrée d'après le nom du fichier "
    "(une image déposée dans le texte d'une fiche reste, elle, jointe à cette fiche).\n"
    "• « Remplacer le fichier… » garde l'ancienne version dans la corbeille. « Enregistrer sous… » en fait une copie (en clair).\n"
    "• « Ouvrir avec l'application associée » ouvre une copie de travail dans LibreOffice, un tableur, une visionneuse… ; chaque enregistrement fait là-bas est repris dans la fiche "
    "(l'ancienne version va à la corbeille). « Terminer l'édition » arrête la surveillance et supprime la copie de travail, qui est en clair même si la fiche est verrouillée.\n"
    "• Rien n'est ouvert ni lancé de lui-même : le type est inerte.")


class VueDocument(QWidget):
    """Vue du type `objet` : description (le texte de la fiche) et fichier joint. Contrat des vues de type : `charger`, `modifie`, `actif`."""
    modifie = pyqtSignal(str)

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.actif = True
        self._charge = False
        self._edition = None                    # {"vue", "piece", "chemin", "veille"} pendant l'édition dans une autre application
        self._minuteur = QTimer(self, interval=2000)
        self._minuteur.timeout.connect(self._sonder)
        lay = QVBoxLayout(self)
        self.etat = QLabel("")
        self.etat.setWordWrap(True)
        lay.addWidget(self.etat)
        boutons = QHBoxLayout()
        self.b_ajout = QPushButton(_("Ajouter le fichier…"))
        self.b_ajout.clicked.connect(self.choisir)
        self.b_sous = QPushButton(_("Enregistrer sous…"))
        self.b_sous.clicked.connect(self.enregistrer_sous)
        self.b_ouvrir = QPushButton(_("Ouvrir avec l'application associée"))
        self.b_ouvrir.clicked.connect(self.ouvrir_externe)
        self.b_fin = QPushButton(_("Terminer l'édition"))
        self.b_fin.clicked.connect(lambda: self.terminer())
        self.b_fin.hide()
        boutons.addWidget(self.b_ajout)
        boutons.addWidget(self.b_ouvrir)
        boutons.addWidget(self.b_fin)
        boutons.addWidget(self.b_sous)
        boutons.addStretch(1)
        lay.addLayout(boutons)
        self.edition_etat = QLabel("")
        self.edition_etat.setWordWrap(True)
        self.edition_etat.hide()
        lay.addWidget(self.edition_etat)
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
        self.b_ouvrir.setEnabled(piece is not None and self._edition is None)

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


    # ----- édition dans l'application associée -----
    def ouvrir_externe(self) -> None:
        """Ouvre une copie de travail avec l'application associée et reprend dans la fiche chaque enregistrement qui y est fait."""
        vue, piece = self._piece()
        if piece is None or self._edition is not None:
            return
        if vue.verrou and QMessageBox.question(
                self, _("Ouvrir avec l'application associée"),
                _("La fiche est verrouillée : une copie EN CLAIR sera créée le temps de l'édition. Continuer ?")) != QMessageBox.StandardButton.Yes:
            return
        try:
            chemin = logique.copie_de_travail(self.ctx.dossier_donnees, piece.nom, self.ctx.lire_piece(vue, piece))
        except (ValueError, OSError) as ex:
            QMessageBox.warning(self, _("Fiche-document"), str(ex))
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(chemin))):
            logique.purger(chemin)
            QMessageBox.warning(self, _("Fiche-document"), _("Aucune application n'a pu ouvrir ce fichier."))
            return
        self._edition = {"vue": vue, "piece": piece, "chemin": chemin, "veille": logique.Surveillance(chemin)}
        self.edition_etat.setText(_("Édition en cours : les enregistrements faits dans l'application sont repris dans la fiche. "
                                    "Cliquez sur « Terminer l'édition » quand vous avez fini."))
        self.edition_etat.show()
        self.b_fin.show()
        self.b_ouvrir.setEnabled(False)
        self._minuteur.start()

    def _sonder(self) -> None:
        e = self._edition
        if e is not None and e["veille"].sonder():
            self._reprendre()

    def _reprendre(self) -> bool:
        """Remplace la pièce par le contenu de la copie de travail. Vrai si c'est fait ; une erreur est signalée une seule fois."""
        e = self._edition
        try:
            if e["chemin"].stat().st_size > logique.SOURCE_MAX:
                raise ValueError(_("Fichier trop volumineux."))
            donnees = e["chemin"].read_bytes()
        except OSError:
            return False                                          # encore en cours d'écriture : on réessaie à l'interrogation suivante
        except ValueError as ex:
            e["veille"].acquitter()
            self.edition_etat.setText(str(ex))
            return False
        try:
            e["piece"] = self.ctx.remplacer_piece(e["vue"], e["piece"], e["piece"].type, donnees)
        except ValueError as ex:
            e["veille"].acquitter()                               # (limites dépassées, fiche fermée…) : pas de boucle d'erreurs
            QMessageBox.warning(self, _("Fiche-document"), str(ex))
            return False
        e["veille"].acquitter()
        self.edition_etat.setText(_("Repris dans la fiche à %s. L'édition continue.") % time.strftime("%H:%M"))
        return True

    def terminer(self, silencieux: bool = False) -> None:
        """Dernière reprise éventuelle, puis arrêt de la surveillance et suppression de la copie de travail."""
        e, self._edition = self._edition, None
        self._minuteur.stop()
        if e is not None:
            self._edition = e
            try:
                if e["veille"].a_change():
                    self._reprendre()
            finally:
                self._edition = None
            logique.purger(e["chemin"])
        self.b_fin.hide()
        self.edition_etat.hide()
        if not silencieux:
            self.rafraichir()


class DocumentsPlugin(Plugin):
    api = 1

    def activer(self, ctx):
        self.ctx, self.vue = ctx, None
        ctx.ajouter_doc(_("Extension Documents"), DOC)
        logique.purger_tout(ctx.dossier_donnees)              # copies de travail restées d'une session interrompue
        if ctx.ui is not None:
            vue = self.vue = VueDocument(ctx)
            ctx.ui.enregistrer_type(logique.TYPE, vue)
            ctx.ui.ajouter_depot(self.deposer)
            for evt in ("piece_jointe_ajoutee", "piece_jointe_modifiee", "piece_jointe_supprimee"):
                ctx.on(evt, lambda **_kw: vue.rafraichir())

    def deposer(self, chemins, theme):
        """Fichiers glissés sur la fenêtre : une fiche-document par fichier, dans le thème affiché (ou « Documents »)."""
        ctx, pris, derniere = self.ctx, [], None
        theme = theme or _("Documents")
        for c in chemins:
            pris.append(c)                                     # pris en charge, même en cas d'erreur (signalée ci-dessous)
            try:
                if c.stat().st_size > logique.SOURCE_MAX:
                    raise ValueError(_("Fichier trop volumineux."))
                donnees = c.read_bytes()
            except (OSError, ValueError) as ex:
                ctx.ui.notifier(_("Fiche-document"), f"{c.name} : {ex}")
                continue
            vue = derniere = ctx.creer_fiche(theme, logique.titre_de(c.name), logique.texte_de(""))
            try:
                ctx.ajouter_piece(vue, c.name, logique.type_mime(c.name), donnees)
            except ValueError as ex:
                ctx.ui.notifier(_("Fiche-document"), f"{c.name} : {ex}")
        if derniere is not None:
            ctx.ui.actualiser()
            ctx.ui.afficher_fiche(derniere)
        return pris

    def desactiver(self):
        if self.vue is not None:
            try:
                self.vue.terminer(silencieux=True)            # reprend la dernière modification et supprime la copie en clair
            except RuntimeError:                              # la vue est déjà détruite : on supprime au moins la copie
                logique.purger_tout(self.ctx.dossier_donnees)

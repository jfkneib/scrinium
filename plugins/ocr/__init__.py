# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « OCR » : extrait le texte des images jointes à une fiche avec Tesseract.

- Menu Extensions : extraire le texte des images de la fiche affichée, voir/corriger le texte, réglages.
- Tout est local (Tesseract est un programme installé sur la machine). L'image est donnée à Tesseract sur son entrée
  standard : aucun fichier temporaire, même pour une fiche verrouillée ouverte.
- Le texte est enregistré avec l'image (`ctx.maj_piece`) : chiffré avec elle si la fiche est verrouillée, et cherché par
  la recherche de la fenêtre.
- Option « automatique à l'ajout d'une image » (désactivée par défaut).
"""
import threading

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import (QApplication, QCheckBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                             QListWidget, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QDialogButtonBox)

from scrinium.core.plugins import Plugin
from scrinium.i18n import _

from . import logique

MOTEUR = "tesseract"


def _parent():
    return QApplication.activeWindow()


class _Pont(QObject):
    """Ramène dans le fil de l'interface le résultat d'une reconnaissance (le magasin de fiches n'est pas thread-safe)."""
    resultat = pyqtSignal(object, int, str, str)      # (vue de la fiche, id de la pièce, texte, erreur)


class DialogueReglages(QDialog):
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.p = plugin
        r = plugin.ctx.reglages
        self.setWindowTitle(_("Réglages de l'OCR"))
        f = QFormLayout(self)
        self.exe = QLineEdit(r.get("exe", ""))
        self.exe.setPlaceholderText(logique.trouver() or _("(tesseract introuvable)"))
        parcourir = QPushButton(_("Parcourir…"))
        parcourir.clicked.connect(self._parcourir)
        ligne = QHBoxLayout()
        ligne.addWidget(self.exe, 1)
        ligne.addWidget(parcourir)
        f.addRow(_("Programme tesseract :"), ligne)
        self.langue = QLineEdit(r.get("langue", "fra"))
        self.langue.setToolTip(_("Code(s) de langue installés, séparés par « + » : fra, fra+eng…"))
        f.addRow(_("Langue(s) :"), self.langue)
        self.auto = QCheckBox(_("Extraire automatiquement le texte à l'ajout d'une image"))
        self.auto.setChecked(bool(r.get("auto", False)))
        f.addRow(self.auto)
        self.etat = QLabel("")
        self.etat.setWordWrap(True)
        f.addRow(self.etat)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        test = b.addButton(_("Tester"), QDialogButtonBox.ButtonRole.ActionRole)
        test.clicked.connect(self._tester)
        b.accepted.connect(self._valider)
        b.rejected.connect(self.reject)
        f.addRow(b)

    def _parcourir(self):
        chemin, _f = QFileDialog.getOpenFileName(self, _("Programme tesseract"))
        if chemin:
            self.exe.setText(chemin)

    def _tester(self):
        exe = logique.trouver(self.exe.text().strip())
        if not exe:
            self.etat.setText("⚠ " + _("Tesseract introuvable.") + "\n" + logique.aide_installation())
            return
        try:
            manque = logique.langues_manquantes(exe, self.langue.text().strip() or "fra")
        except Exception as ex:
            self.etat.setText(f"⚠ {type(ex).__name__}: {ex}")
            return
        self.etat.setText("⚠ " + _("Langue(s) non installée(s) : %s") % ", ".join(manque) + "\n" + logique.aide_installation()
                          if manque else _("✔ Tesseract trouvé : %s") % exe)

    def _valider(self):
        r = self.p.ctx.reglages
        r.set("exe", self.exe.text().strip())
        r.set("langue", self.langue.text().strip() or "fra")
        r.set("auto", self.auto.isChecked())
        self.accept()


class DialogueTextes(QDialog):
    """Texte extrait de chaque image de la fiche : lecture, correction, relance."""

    def __init__(self, plugin, vue, parent=None):
        super().__init__(parent)
        self.p, self.vue = plugin, vue
        self.setWindowTitle(_("Texte extrait des images"))
        self.resize(720, 460)
        lay = QHBoxLayout(self)
        self.liste = QListWidget()
        self.liste.setMaximumWidth(220)
        gauche = QVBoxLayout()
        gauche.addWidget(self.liste, 1)
        lay.addLayout(gauche)
        droite = QVBoxLayout()
        self.texte = QPlainTextEdit()
        self.texte.setPlaceholderText(_("(aucun texte extrait : « Extraire »)"))
        droite.addWidget(self.texte, 1)
        bas = QHBoxLayout()
        self.b_extraire = QPushButton(_("Extraire"))
        self.b_enreg = QPushButton(_("Enregistrer la correction"))
        self.b_copier = QPushButton(_("Copier"))
        fermer = QPushButton(_("Fermer"))
        self.b_extraire.clicked.connect(self._extraire)
        self.b_enreg.clicked.connect(self._enregistrer)
        self.b_copier.clicked.connect(lambda: QApplication.clipboard().setText(self.texte.toPlainText()))
        fermer.clicked.connect(self.accept)
        for b in (self.b_extraire, self.b_enreg, self.b_copier):
            bas.addWidget(b)
        bas.addStretch()
        bas.addWidget(fermer)
        droite.addLayout(bas)
        lay.addLayout(droite, 1)
        self.pieces = plugin.ctx.pieces(vue)
        self._remplir()
        self.liste.currentRowChanged.connect(self._choisir)
        plugin.dialogue = self
        if self.pieces:
            self.liste.setCurrentRow(0)

    def done(self, r):
        self.p.dialogue = None
        super().done(r)

    def _remplir(self):
        row = self.liste.currentRow()
        self.liste.blockSignals(True)
        self.liste.clear()
        for p in self.pieces:
            self.liste.addItem(("✔ " if p.ocr else "· ") + p.nom)
        self.liste.setCurrentRow(row if 0 <= row < len(self.pieces) else -1)
        self.liste.blockSignals(False)

    def _choisir(self, row):
        ok = 0 <= row < len(self.pieces)
        self.texte.setPlainText(self.pieces[row].ocr if ok else "")
        for b in (self.b_extraire, self.b_enreg, self.b_copier):
            b.setEnabled(ok)

    def rafraichir(self):
        row = self.liste.currentRow()
        self.pieces = self.p.ctx.pieces(self.vue)
        self._remplir()
        if 0 <= row < len(self.pieces):
            self.liste.setCurrentRow(row)
            self._choisir(row)

    def _extraire(self):
        row = self.liste.currentRow()
        if 0 <= row < len(self.pieces):
            self.p.extraire(self.vue, [self.pieces[row]])

    def _enregistrer(self):
        row = self.liste.currentRow()
        if 0 <= row < len(self.pieces):
            p = self.pieces[row]
            texte = self.texte.toPlainText().strip()
            moteur = p.ocr_moteur if p.ocr_moteur and texte == p.ocr.strip() else (MOTEUR + "+manuel" if texte else "")
            self.p.ctx.maj_piece(self.vue, p, ocr=texte, ocr_moteur=moteur)
            self.rafraichir()


class OcrPlugin(Plugin):
    api = 1

    def activer(self, ctx):
        self.ctx = ctx
        self.dialogue = None
        self.en_cours = set()
        if ctx.ui is None:
            return
        self.pont = _Pont()
        self.pont.resultat.connect(self._resultat)
        ctx.ui.ajouter_action(_("Extraire le texte des images de la fiche"), self.extraire_fiche, "edit-find")
        ctx.ui.ajouter_action(_("Texte extrait des images…"), self.voir, "view-pim-notes")
        ctx.ui.ajouter_action(_("Réglages de l'OCR…"), self.reglages, "configure")
        ctx.on("piece_jointe_ajoutee", self._ajoutee)

    # ---------- moteur ----------
    def _moteur(self):
        """(programme, langue) prêts à servir, sinon None après avoir expliqué quoi faire."""
        r = self.ctx.reglages
        exe = logique.trouver(r.get("exe", ""))
        langue = r.get("langue", "fra")
        if not exe:
            QMessageBox.warning(_parent(), _("OCR"), _("Tesseract est introuvable.") + "\n\n" + logique.aide_installation())
            return None
        try:
            manque = logique.langues_manquantes(exe, langue)
        except Exception as ex:
            QMessageBox.warning(_parent(), _("OCR"), f"{type(ex).__name__}: {ex}")
            return None
        if manque:
            QMessageBox.warning(_parent(), _("OCR"), _("Langue(s) non installée(s) : %s") % ", ".join(manque)
                                + "\n\n" + logique.aide_installation())
            return None
        return exe, langue

    # ---------- extraction ----------
    def extraire_fiche(self):
        vue = self.ctx.fiche_courante()
        if vue is None:
            self.ctx.ui.notifier(_("OCR"), _("Ouvrez d'abord une fiche."))
            return
        if vue.fermee:
            QMessageBox.warning(_parent(), _("OCR"), _("Fiche verrouillée : déverrouillez-la d'abord."))
            return
        pieces = self.ctx.pieces(vue)
        if not pieces:
            self.ctx.ui.notifier(_("OCR"), _("Cette fiche n'a pas d'image."))
            return
        self.extraire(vue, pieces)

    def extraire(self, vue, pieces, silencieux=False):
        """Lance la reconnaissance des `pieces` (en arrière-plan, une par une)."""
        travail = [p for p in pieces if (vue.id, p.id) not in self.en_cours]
        if not travail:
            return
        moteur = self._moteur() if not silencieux else self._moteur_silencieux()
        if moteur is None:
            return
        exe, langue = moteur
        lots = []
        for p in travail:
            try:
                lots.append((p.id, self.ctx.lire_piece(vue, p)))
            except ValueError as ex:
                self.ctx.ui.notifier(_("OCR"), str(ex))
                return
            self.en_cours.add((vue.id, p.id))
        self.ctx.ui.notifier(_("OCR"), _("Extraction du texte de %d image(s)…") % len(lots))
        threading.Thread(target=self._travailler, args=(vue, exe, langue, lots), daemon=True).start()

    def _moteur_silencieux(self):
        r = self.ctx.reglages
        exe = logique.trouver(r.get("exe", ""))
        return (exe, r.get("langue", "fra")) if exe else None

    def _travailler(self, vue, exe, langue, lots):
        for pid, donnees in lots:
            try:
                self.pont.resultat.emit(vue, pid, logique.reconnaitre(exe, donnees, langue), "")
            except Exception as ex:
                self.pont.resultat.emit(vue, pid, "", f"{type(ex).__name__}: {ex}")

    def _resultat(self, vue, pid, texte, erreur):
        self.en_cours.discard((vue.id, pid))
        if erreur:
            self.ctx.ui.notifier(_("OCR"), _("Échec : %s") % erreur)
            return
        try:
            self.ctx.maj_piece(vue, pid, ocr=texte, ocr_moteur=MOTEUR)
        except ValueError as ex:                      # fiche refermée entre-temps, image supprimée…
            self.ctx.ui.notifier(_("OCR"), str(ex))
            return
        if not self.en_cours:
            self.ctx.ui.notifier(_("OCR"), _("Texte extrait."))
        if self.dialogue is not None:
            self.dialogue.rafraichir()

    def _ajoutee(self, fiche, piece, **kw):
        if self.ctx.reglages.get("auto", False):
            self.extraire(fiche, [piece], silencieux=True)

    # ---------- fenêtres ----------
    def voir(self):
        vue = self.ctx.fiche_courante()
        if vue is None or vue.fermee:
            self.ctx.ui.notifier(_("OCR"), _("Ouvrez d'abord une fiche (déverrouillée)."))
            return
        DialogueTextes(self, vue, _parent()).exec()

    def reglages(self):
        DialogueReglages(self, _parent()).exec()

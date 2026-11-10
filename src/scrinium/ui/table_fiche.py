# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Vue générique d'une fiche « liste » (inventaire, collection, mots de passe…) : tableau, recherche, tri, ajout/modification par formulaire,
résumé en haut. Le texte est géré par `core/table_fiche.py` ; chaque extension ne fournit qu'une `Spec` (colonnes, résumé, couleurs)."""
from dataclasses import dataclass
from typing import Callable

from PyQt6.QtCore import QDate, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QGuiApplication
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView,
                             QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..core import table_fiche as tf
from ..i18n import _
from .icons import icone

MASQUE = "••••••••"


@dataclass
class Spec:
    marque: str                                         # « #scrinium-inventaire »
    colonnes: list                                      # [core.table_fiche.Colonne]
    ajouter: str                                        # texte du bouton (déjà marqué N_, traduit à l'affichage)
    aide: str = ""
    nom_obligatoire: str = ""                           # clé de la colonne qui ne peut pas être vide (la 1re par défaut)
    reglages: tuple = ()                                # ((clé, titre), …) réglages de la fiche, ex. ((« devise », N_(« Devise »)),)
    resume: Callable | None = None                      # (lignes, réglages) -> HTML court
    couleur: Callable | None = None                     # ligne -> « #rrggbb » (fond) ou None
    avertissement: str = ""                             # bandeau en haut (déjà traduit à l'affichage)
    generer: Callable | None = None                     # () -> mot de passe : bouton « Générer » à côté d'un champ secret
    copier: tuple = ()                                  # colonnes « secret » : action « Copier » (presse-papiers vidé après 20 s)

    def cle_nom(self) -> str:
        return self.nom_obligatoire or self.colonnes[0].cle


class DialogueLigne(QDialog):
    """Formulaire d'une ligne, construit d'après les colonnes."""

    def __init__(self, spec: Spec, ligne: dict | None, parent=None):
        super().__init__(parent)
        self.spec = spec
        self.setWindowTitle(_("Modifier") if ligne else _(spec.ajouter).rstrip("…"))
        self.resize(460, 120 + 34 * len(spec.colonnes))
        f = QFormLayout(self)
        self.champs = {}
        for c in spec.colonnes:
            v = (ligne or {}).get(c.cle, "")
            if c.genre == "date":
                w = QDateEdit(QDate.fromString(v, "yyyy-MM-dd") if v else QDate(1900, 1, 1))
                w.setMinimumDate(QDate(1900, 1, 1))
                w.setSpecialValueText(" ")                  # 1900-01-01 = « pas de date »
                w.setCalendarPopup(True)
            elif c.genre == "case":
                w = QCheckBox()
                w.setChecked(v == "oui")
            elif c.genre == "choix":
                w = QComboBox()
                w.addItem("", "")
                for x in c.choix:
                    w.addItem(_(x), x)
                w.setCurrentIndex(max(0, w.findData(v)))
            else:
                w = QLineEdit(v)
                if c.genre == "secret":
                    w.setEchoMode(QLineEdit.EchoMode.Password)
            self.champs[c.cle] = w
            if c.genre == "secret" and spec.generer:
                rang = QHBoxLayout()
                rang.addWidget(w, 1)
                b = QPushButton(_("Générer"))
                b.clicked.connect(lambda _c=False, w=w: (w.setText(spec.generer()), w.setEchoMode(QLineEdit.EchoMode.Normal)))
                rang.addWidget(b)
                f.addRow(_(c.titre) + " :", rang)
            else:
                f.addRow(_(c.titre) + " :", w)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        b.accepted.connect(self._valider)
        b.rejected.connect(self.reject)
        f.addRow(b)

    def _valeur(self, c: tf.Colonne) -> str:
        w = self.champs[c.cle]
        if c.genre == "date":
            return "" if w.date() <= QDate(1900, 1, 1) else w.date().toString("yyyy-MM-dd")
        if c.genre == "case":
            return "oui" if w.isChecked() else ""
        if c.genre == "choix":
            return w.currentData() or ""
        return w.text()

    def resultat(self) -> dict:
        return tf.normaliser(self.spec.colonnes, {c.cle: self._valeur(c) for c in self.spec.colonnes})

    def _valider(self):
        if self.resultat().get(self.spec.cle_nom()):
            self.accept()
        else:
            next(iter(self.champs.values())).setFocus()
            QMessageBox.warning(self, self.windowTitle(), _("Le nom est vide : saisissez-le avant de valider."))


class VueTable(QWidget):
    """Vue d'une fiche liste. Interface commune aux vues de types : `charger(texte)`, signal `modifie(str)`, attribut `actif`."""
    modifie = pyqtSignal(str)

    def __init__(self, spec: Spec, parent=None):
        super().__init__(parent)
        self.spec = spec
        self.actif = True
        self.doc = tf.Document()
        self._ordre: list = []
        self._tri = (0, True)
        self._montrer = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        if spec.avertissement:
            av = QLabel(_(spec.avertissement))
            av.setWordWrap(True)
            av.setStyleSheet("background:#fff3cd;color:#5c4400;padding:4px;border-radius:3px;")
            lay.addWidget(av)
        self.l_resume = QLabel()
        self.l_resume.setWordWrap(True)
        self.l_resume.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.l_resume)
        haut = QHBoxLayout()
        self.b_ajouter = QPushButton(icone("list-add"), _(spec.ajouter))
        self.b_ajouter.clicked.connect(self._ajouter)
        haut.addWidget(self.b_ajouter)
        self.recherche = QLineEdit()
        self.recherche.setPlaceholderText(_("Rechercher…"))
        self.recherche.setClearButtonEnabled(True)
        self.recherche.textChanged.connect(lambda *_a: self._afficher())
        haut.addWidget(self.recherche, 1)
        self.reglages = {}
        for cle, titre in spec.reglages:
            haut.addWidget(QLabel(_(titre)))
            e = QLineEdit()
            e.setFixedWidth(60)
            e.editingFinished.connect(lambda cle=cle, e=e: self._reglage(cle, e.text()))
            self.reglages[cle] = e
            haut.addWidget(e)
        if any(c.genre == "secret" for c in spec.colonnes):
            self.c_montrer = QCheckBox(_("Afficher les secrets"))
            self.c_montrer.toggled.connect(self._montrer_secrets)
            haut.addWidget(self.c_montrer)
        lay.addLayout(haut)
        n = len(spec.colonnes)
        self.table = QTableWidget(0, n)
        self.table.setHorizontalHeaderLabels([_(c.titre) for c in spec.colonnes])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(n - 1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionsClickable(True)
        self.table.horizontalHeader().sectionClicked.connect(self._trier)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.doubleClicked.connect(lambda idx: self._modifier(idx.row()))
        lay.addWidget(self.table, 1)
        aide = QLabel(_(spec.aide) if spec.aide else _("Double-clic ou clic droit : modifier ou supprimer. Cliquez sur un titre de colonne pour trier."))
        aide.setWordWrap(True)
        lay.addWidget(aide)

    def showEvent(self, ev):
        super().showEvent(ev)
        self._afficher()

    # ---------- données ----------
    def charger(self, texte: str):
        self.doc = tf.lire(texte, self.spec.marque, self.spec.colonnes, tuple(c for c, _t in self.spec.reglages))
        self._afficher()

    def _enregistrer(self):
        titres = [_(c.titre) for c in self.spec.colonnes]
        self.modifie.emit(tf.ecrire(self.doc, self.spec.marque, self.spec.colonnes, titres))
        self._afficher()

    def _reglage(self, cle, valeur):
        valeur = valeur.strip()[:8]
        if valeur != self.doc.reglages.get(cle, ""):
            self.doc.reglages[cle] = valeur
            self._enregistrer()

    def _ajouter(self):
        d = DialogueLigne(self.spec, None, self)
        if d.exec() and len(self.doc.lignes) < tf.MAX_LIGNES:
            self.doc.lignes.append(d.resultat())
            self._enregistrer()

    def _modifier(self, ligne: int):
        if 0 <= ligne < len(self._ordre):
            cible = self._ordre[ligne]
            d = DialogueLigne(self.spec, cible, self)
            if d.exec():
                i = next(k for k, x in enumerate(self.doc.lignes) if x is cible)
                self.doc.lignes[i] = d.resultat()
                self._enregistrer()

    def _supprimer(self, ligne: int):
        if 0 <= ligne < len(self._ordre):
            cible = self._ordre[ligne]
            self.doc.lignes = [x for x in self.doc.lignes if x is not cible]
            self._enregistrer()

    def _copier(self, ligne: int, cle: str):
        """Copie un secret dans le presse-papiers, qui est vidé après 20 secondes (s'il contient toujours ce secret)."""
        if 0 <= ligne < len(self._ordre):
            valeur = self._ordre[ligne].get(cle, "")
            cp = QGuiApplication.clipboard()
            cp.setText(valeur)
            QTimer.singleShot(20000, lambda: cp.clear() if cp.text() == valeur else None)

    def _menu(self, pos):
        i = self.table.rowAt(pos.y())
        m = QMenu(self)
        m.addAction(icone("list-add"), _(self.spec.ajouter), self._ajouter)
        if i >= 0:
            for cle in self.spec.copier:
                titre = next(_(c.titre) for c in self.spec.colonnes if c.cle == cle)
                m.addAction(icone("edit-copy"), _("Copier : %s (effacé après 20 s)") % titre, lambda cle=cle: self._copier(i, cle))
            m.addAction(icone("document-edit"), _("Modifier…"), lambda: self._modifier(i))
            m.addAction(icone("edit-delete"), _("Supprimer"), lambda: self._supprimer(i))
        m.exec(self.table.viewport().mapToGlobal(pos))

    def _montrer_secrets(self, on: bool):
        self._montrer = on
        self._afficher()

    def _trier(self, col: int):
        self._tri = (col, not self._tri[1]) if self._tri[0] == col else (col, True)
        self._afficher()

    # ---------- affichage ----------
    def _cle_tri(self, ligne: dict):
        c = self.spec.colonnes[self._tri[0]]
        v = ligne.get(c.cle, "")
        if c.genre == "nombre":
            return (v == "", float(v) if v else 0.0)
        return (v == "", v.casefold())

    def _afficher(self):
        q = self.recherche.text().strip().casefold()
        lignes = [d for d in self.doc.lignes if not q or any(q in str(v).casefold() for k, v in d.items()
                                                              if not any(c.cle == k and c.genre == "secret" for c in self.spec.colonnes))]
        self._ordre = sorted(lignes, key=self._cle_tri, reverse=not self._tri[1])
        for cle, e in self.reglages.items():
            if not e.hasFocus():
                e.setText(self.doc.reglages.get(cle, ""))
        self.table.setRowCount(len(self._ordre))
        for i, d in enumerate(self._ordre):
            fond = self.spec.couleur(d) if self.spec.couleur else None
            for k, c in enumerate(self.spec.colonnes):
                v = d.get(c.cle, "")
                if c.genre == "secret" and v:
                    v = v if self._montrer else MASQUE
                elif c.genre == "date" and v:
                    v = QDate.fromString(v, "yyyy-MM-dd").toString("dd/MM/yyyy")
                elif c.genre == "case":
                    v = "✔" if v else ""
                elif c.genre == "choix" and v:
                    v = _(v)
                it = QTableWidgetItem(v)
                if c.genre == "nombre":
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if fond:
                    it.setBackground(QBrush(QColor(fond)))
                    it.setForeground(QBrush(QColor("#1b1b1b")))
                self.table.setItem(i, k, it)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(len(self.spec.colonnes) - 1, QHeaderView.ResizeMode.Stretch)
        self.l_resume.setText(self.spec.resume(self.doc.lignes, self.doc.reglages) if self.spec.resume and self.doc.lignes else
                              _("Ajoutez une première ligne avec le bouton ci-dessus."))

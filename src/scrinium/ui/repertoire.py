# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Affichage d'une fiche « répertoire » : barre de lettres A-Z, liste des entrées de la lettre, formulaire de l'entrée choisie.

Le tableau lui-même (`core.repertoire.Tableau`) est du texte CSV ; ce widget le lit, l'édite et signale chaque changement par
`modifie(texte)` — la fenêtre l'enregistre comme n'importe quelle fiche."""
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel,
                             QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QRadioButton,
                             QScrollArea, QVBoxLayout, QWidget)

from ..core.repertoire import LETTRES, MAX_COLONNES, Tableau
from ..i18n import _
from .icons import icone


class DialogueColonnes(QDialog):
    """Colonnes du tableau : ajouter, renommer, supprimer, réordonner, choisir celle qui donne la lettre (A-Z)."""

    def __init__(self, tableau: Tableau, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Colonnes du répertoire"))
        self.resize(420, 420)
        self.colonnes = [[nom, k] for k, nom in enumerate(tableau.colonnes)]       # [nom, ancien numéro ou None]
        self.index = tableau.index
        self._t = tableau
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(_("Les colonnes de votre tableau. Ce qui est saisi suit sa colonne quand vous la déplacez.")))
        self.liste = QListWidget()
        lay.addWidget(self.liste, 1)
        ligne = QHBoxLayout()
        for texte, slot in ((_("Ajouter…"), self._ajouter), (_("Renommer…"), self._renommer), (_("Supprimer"), self._supprimer),
                            (_("Monter"), lambda: self._deplacer(-1)), (_("Descendre"), lambda: self._deplacer(1))):
            b = QPushButton(texte)
            b.clicked.connect(lambda *_a, s=slot: s())
            ligne.addWidget(b)
        lay.addLayout(ligne)
        self.radio = QRadioButton(_("Classer A-Z d'après la colonne sélectionnée"))
        self.radio.setChecked(False)
        lay.addWidget(self.radio)
        self.radio.clicked.connect(self._index)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        lay.addWidget(b)
        self.liste.currentRowChanged.connect(lambda *_a: self.radio.setChecked(self.liste.currentRow() == self.index))
        self._remplir(self.index)

    def _remplir(self, ligne: int):
        self.liste.blockSignals(True)
        self.liste.clear()
        for k, (nom, _old) in enumerate(self.colonnes):
            self.liste.addItem(QListWidgetItem(icone("view-pim-notes") if k == self.index else icone(""),
                                               nom + ("   ← " + _("classement A-Z") if k == self.index else "")))
        self.liste.blockSignals(False)
        self.liste.setCurrentRow(max(0, min(ligne, len(self.colonnes) - 1)))
        self.radio.setChecked(self.liste.currentRow() == self.index)

    def _index(self):
        self.index = max(0, self.liste.currentRow())
        self._remplir(self.index)

    def _ajouter(self):
        if len(self.colonnes) >= MAX_COLONNES:
            return
        nom, ok = QInputDialog.getText(self, _("Nouvelle colonne"), _("Nom de la colonne :"))
        if ok and nom.strip():
            self.colonnes.append([nom.strip(), None])
            self._remplir(len(self.colonnes) - 1)

    def _renommer(self):
        k = self.liste.currentRow()
        if k < 0:
            return
        nom, ok = QInputDialog.getText(self, _("Renommer la colonne"), _("Nom de la colonne :"), text=self.colonnes[k][0])
        if ok and nom.strip():
            self.colonnes[k][0] = nom.strip()
            self._remplir(k)

    def _supprimer(self):
        k = self.liste.currentRow()
        if k < 0 or len(self.colonnes) <= 1:
            return
        old = self.colonnes[k][1]
        if old is not None and any(l[old] for l in self._t.lignes) and QMessageBox.question(
                self, _("Supprimer la colonne"),
                _("La colonne « %s » contient des données : elles seront perdues à la validation. Continuer ?") % self.colonnes[k][0]
        ) != QMessageBox.StandardButton.Yes:
            return
        del self.colonnes[k]
        self.index = 0 if k == self.index else (self.index - 1 if k < self.index else self.index)
        self._remplir(min(k, len(self.colonnes) - 1))

    def _deplacer(self, delta: int):
        k = self.liste.currentRow()
        j = k + delta
        if k < 0 or not 0 <= j < len(self.colonnes):
            return
        self.colonnes[k], self.colonnes[j] = self.colonnes[j], self.colonnes[k]
        self.index = j if self.index == k else (k if self.index == j else self.index)
        self._remplir(j)

    def resultat(self) -> tuple[list, int]:
        return [(nom, old) for nom, old in self.colonnes], self.index


class VueRepertoire(QWidget):
    modifie = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tableau = Tableau(["Nom"])
        self._courante = -1             # numéro de la ligne affichée dans le formulaire
        self._groupes: dict = {}
        self._champs: list = []
        self._remplissage = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        barre = QHBoxLayout()
        self.b_ajouter = QPushButton(icone("list-add"), _("Ajouter"))
        self.b_ajouter.clicked.connect(self.ajouter)
        self.b_supprimer = QPushButton(icone("edit-delete"), _("Supprimer"))
        self.b_supprimer.clicked.connect(self.supprimer)
        self.b_colonnes = QPushButton(icone("view-pim-notes"), _("Colonnes…"))
        self.b_colonnes.clicked.connect(self.colonnes)
        self.b_importer = QPushButton(_("Importer un CSV…"))
        self.b_importer.clicked.connect(self.importer)
        self.b_exporter = QPushButton(icone("document-save"), _("Exporter en CSV…"))
        self.b_exporter.clicked.connect(self.exporter)
        for b in (self.b_ajouter, self.b_supprimer, self.b_colonnes, self.b_importer, self.b_exporter):
            barre.addWidget(b)
        barre.addStretch()
        self.filtre = QLineEdit()
        self.filtre.setPlaceholderText(_("Filtrer…"))
        self.filtre.setClearButtonEnabled(True)
        self.filtre.setMaximumWidth(180)
        self.filtre.textChanged.connect(lambda *_a: self._rafraichir())
        barre.addWidget(self.filtre)
        lay.addLayout(barre)
        corps = QHBoxLayout()
        self.lettres = QListWidget()
        self.lettres.setFixedWidth(46)
        self.lettres.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for l in LETTRES:
            it = QListWidgetItem(l)
            it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.lettres.addItem(it)
        self.lettres.currentRowChanged.connect(lambda *_a: self._rafraichir())
        self.entrees = QListWidget()
        self.entrees.setMaximumWidth(220)
        self.entrees.currentRowChanged.connect(self._choisir)
        self.formulaire = QWidget()
        self.form = QFormLayout(self.formulaire)
        zone = QScrollArea()
        zone.setWidgetResizable(True)
        zone.setWidget(self.formulaire)
        corps.addWidget(self.lettres)
        corps.addWidget(self.entrees)
        corps.addWidget(zone, 1)
        lay.addLayout(corps, 1)

    # ---------- chargement ----------
    def charger(self, texte: str):
        self.tableau = Tableau.depuis_texte(texte)
        self._courante = -1
        self.filtre.clear()
        self._construire_formulaire()
        premiere = next((l for l in LETTRES if l in self.tableau.par_lettre()), LETTRES[0])
        self.lettres.blockSignals(True)
        self.lettres.setCurrentRow(LETTRES.index(premiere))
        self.lettres.blockSignals(False)
        self._rafraichir()

    def _construire_formulaire(self):
        while self.form.rowCount():
            self.form.removeRow(0)
        self._champs = []
        for k, nom in enumerate(self.tableau.colonnes):
            e = QPlainTextEdit()
            e.setTabChangesFocus(True)
            e.setFixedHeight(34 if k == self.tableau.index else 62)
            e.textChanged.connect(lambda k=k, e=e: self._edite(k, e))
            self.form.addRow(QLabel(nom + (" ★" if k == self.tableau.index else "")), e)
            self._champs.append(e)

    # ---------- listes ----------
    def _rafraichir(self, garder: int | None = None):
        """Relit les lettres et les entrées. `garder` : numéro de la ligne à resélectionner (même si elle a changé de lettre)."""
        t = self.tableau
        groupes = t.par_lettre()
        self._groupes = groupes
        texte = self.filtre.text().strip().lower()
        gras = QFont()
        gras.setBold(True)
        self.lettres.blockSignals(True)
        for i, l in enumerate(LETTRES):
            it = self.lettres.item(i)
            it.setFont(gras if l in groupes else QFont())
            it.setForeground(self.palette().text() if l in groupes else self.palette().placeholderText())
        if garder is not None and 0 <= garder < len(t.lignes) and not texte:
            self.lettres.setCurrentRow(LETTRES.index(t.lettre(garder)))
        self.lettres.blockSignals(False)
        if texte:
            numeros = [i for i in sorted(range(len(t.lignes)), key=t.cle) if texte in " ".join(t.lignes[i]).lower()]
        else:
            numeros = groupes.get(LETTRES[max(0, self.lettres.currentRow())], [])
        self.entrees.blockSignals(True)
        self.entrees.clear()
        self._numeros = numeros
        sel = numeros.index(garder) if garder in numeros else (numeros.index(self._courante) if self._courante in numeros else -1)
        for i in numeros:
            self.entrees.addItem(t.libelle(i))
        self.entrees.setCurrentRow(sel)
        self.entrees.blockSignals(False)
        if sel >= 0:
            self._afficher(numeros[sel])
        elif numeros:
            self.entrees.setCurrentRow(0)
        else:
            self._afficher(-1)

    def _choisir(self, row: int):
        self._afficher(self._numeros[row] if 0 <= row < len(self._numeros) else -1)

    def _afficher(self, i: int):
        self._courante = i
        self._remplissage = True
        for k, e in enumerate(self._champs):
            e.setPlainText(self.tableau.lignes[i][k] if 0 <= i < len(self.tableau.lignes) else "")
            e.setEnabled(0 <= i < len(self.tableau.lignes))
        self._remplissage = False
        self.b_supprimer.setEnabled(0 <= i < len(self.tableau.lignes))

    # ---------- édition ----------
    def _edite(self, k: int, champ: QPlainTextEdit):
        i = self._courante
        if self._remplissage or not 0 <= i < len(self.tableau.lignes):
            return
        valeur = champ.toPlainText().strip()
        if self.tableau.lignes[i][k] == valeur:
            return
        self.tableau.lignes[i][k] = valeur
        self._signaler()
        self._rafraichir(garder=i)

    def _signaler(self):
        self.modifie.emit(self.tableau.en_texte())

    def ajouter(self):
        self.filtre.clear()
        self.tableau.lignes.append(self.tableau.ligne_vide())
        i = len(self.tableau.lignes) - 1
        self._signaler()
        self._rafraichir(garder=i)
        self._champs[self.tableau.index].setFocus()

    def supprimer(self):
        i = self._courante
        if not 0 <= i < len(self.tableau.lignes):
            return
        if any(self.tableau.lignes[i]) and QMessageBox.question(
                self, _("Supprimer l'entrée"), _("Supprimer « %s » du répertoire ?") % self.tableau.libelle(i)
        ) != QMessageBox.StandardButton.Yes:
            return
        del self.tableau.lignes[i]
        self._courante = -1
        self._signaler()
        self._rafraichir()

    def colonnes(self):
        d = DialogueColonnes(self.tableau, self)
        if not d.exec():
            return
        cols, index = d.resultat()
        self.tableau.changer_colonnes(cols, index)
        self._courante = -1
        self._construire_formulaire()
        self._signaler()
        self._rafraichir()

    def importer(self):
        chemin, _f = QFileDialog.getOpenFileName(self, _("Importer un CSV"), str(Path.home()), _("Fichiers CSV (*.csv *.txt);;Tous (*)"))
        if not chemin:
            return
        try:
            octets = Path(chemin).read_bytes()
        except OSError as ex:
            QMessageBox.critical(self, _("Importer un CSV"), _("Lecture impossible : %s") % ex)
            return
        ajoutees, creees = self.tableau.importer(octets)
        if creees:
            self._construire_formulaire()
        self._signaler()
        self._rafraichir()
        msg = _("%d entrée(s) ajoutée(s).") % ajoutees
        if creees:
            msg += "\n" + _("Colonnes ajoutées : %s") % ", ".join(creees)
        QMessageBox.information(self, _("Importer un CSV"), msg)

    def exporter(self):
        virgule, pointvirgule = _("CSV, séparateur virgule (*.csv)"), _("CSV, séparateur point-virgule — Excel en français (*.csv)")
        chemin, filtre = QFileDialog.getSaveFileName(self, _("Exporter en CSV"), str(Path.home() / "repertoire.csv"),
                                                     f"{virgule};;{pointvirgule}")
        if not chemin:
            return
        if not chemin.lower().endswith(".csv"):
            chemin += ".csv"
        try:
            Path(chemin).write_bytes(self.tableau.exporter_csv(";" if filtre == pointvirgule else ","))
        except OSError as ex:
            QMessageBox.critical(self, _("Exporter en CSV"), _("Écriture impossible : %s") % ex)

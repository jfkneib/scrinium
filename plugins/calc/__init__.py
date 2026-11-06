# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « Calc » : un petit éditeur de listes avec de petits calculs, pour suivre des données (relevés, dépenses, poids…).
Voir `logique.py` pour le format. Pour des formules cellule par cellule, voir l'extension « Tableur ».

- Nouvelle fiche > « Calc » : une liste (première ligne = en-têtes). Double-clic ou F2 : on modifie une cellule.
- « Ajouter une ligne » : si la première colonne s'appelle « Date », elle reçoit la date du jour.
- Ligne grisée du bas : un TOTAL par colonne (somme, moyenne, minimum, maximum, nombre) ; clic droit dessus pour choisir.
- « Exporter en CSV… » / « Importer un CSV… ». Clic droit : insérer ou supprimer lignes et colonnes. Ctrl+C / Ctrl+V : copier, coller."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QKeySequence
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QFileDialog, QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton,
                             QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from scrinium.core.plugins import Plugin
from scrinium.i18n import _
from scrinium.ui.icons import icone

from . import logique


def _noms_totaux() -> dict:
    return {"": _("Aucun total"), "somme": _("Somme"), "moyenne": _("Moyenne"), "min": _("Minimum"), "max": _("Maximum"), "nb": _("Nombre")}


class VueCalc(QWidget):
    """Vue du type « calc » : la liste, et en bas la ligne grisée des totaux."""
    modifie = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.actif = True                       # type non exécutable : toujours utilisable
        self.lignes: list = []
        self.totaux: list = []
        self.notes = ""
        self._remplit = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        haut = QHBoxLayout()
        self.b_ligne = QPushButton(icone("list-add"), _("Ajouter une ligne"))
        self.b_ligne.clicked.connect(lambda *_a: self.ajouter_ligne())
        self.b_colonne = QPushButton(icone("list-add"), _("Ajouter une colonne"))
        self.b_colonne.clicked.connect(lambda *_a: self.ajouter_colonne())
        self.b_export = QPushButton(icone("document-export"), _("Exporter en CSV…"))
        self.b_export.clicked.connect(lambda *_a: self.exporter_csv())
        self.b_import = QPushButton(icone("document-import"), _("Importer un CSV…"))
        self.b_import.clicked.connect(lambda *_a: self.importer_csv())
        for b in (self.b_ligne, self.b_colonne, self.b_export, self.b_import):
            haut.addWidget(b)
        haut.addStretch(1)
        lay.addLayout(haut)
        self.table = QTableWidget()
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.itemChanged.connect(self._modifie)
        self.table.keyPressEvent = self._touche
        lay.addWidget(self.table, 1)
        self.etat = QLabel()
        lay.addWidget(self.etat)

    # ---------- affichage ----------
    def charger(self, texte: str):
        lignes, totaux, self.notes = logique.lire(texte)
        self.lignes = lignes or logique.vide()
        self.totaux = (totaux + [""] * len(self.lignes[0]))[:len(self.lignes[0])] if lignes else ["", "somme"]
        self._afficher()

    def _afficher(self):
        self._remplit = True
        n_l, n_c = len(self.lignes), len(self.lignes[0])
        self.table.clear()
        self.table.setRowCount(n_l + 1)                           # + la ligne des totaux
        self.table.setColumnCount(n_c)
        self.table.setHorizontalHeaderLabels([""] * n_c)
        self.table.horizontalHeader().setVisible(False)
        self.table.setVerticalHeaderLabels([str(i) if i else "" for i in range(n_l)] + ["Σ"])
        gras = QFont(self.table.font())
        gras.setBold(True)
        gris = QBrush(QColor(128, 128, 128, 40))
        for l in range(n_l):
            for c in range(n_c):
                it = QTableWidgetItem(self.lignes[l][c])
                if l == 0:
                    it.setFont(gras)
                elif logique.nombre(self.lignes[l][c]) is not None:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(l, c, it)
        noms = _noms_totaux()
        for c in range(n_c):
            t = logique.total(self.lignes, c, self.totaux[c])
            it = QTableWidgetItem((noms[self.totaux[c]] + " : " + t) if self.totaux[c] and t != "" else "")
            it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            it.setFont(gras)
            it.setBackground(gris)
            it.setToolTip(_("Clic droit : choisir le total de cette colonne"))
            it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(n_l, c, it)
        self.table.resizeColumnsToContents()
        for c in range(n_c):
            self.table.setColumnWidth(c, max(110, self.table.columnWidth(c)))
        self.etat.setText(_("%(l)d lignes, %(c)d colonnes. La ligne grisée du bas donne un total par colonne (clic droit pour le choisir).")
                          % {"l": n_l - 1, "c": n_c})
        self._remplit = False

    def _enregistrer(self):
        self.modifie.emit(logique.ecrire(self.lignes, self.totaux, self.notes))
        self._afficher()

    # ---------- modifications ----------
    def _modifie(self, it):
        if not self._remplit and it.row() < len(self.lignes):
            self.modifier_cellule(it.row(), it.column(), it.text())

    def modifier_cellule(self, l: int, c: int, texte: str):
        if 0 <= l < len(self.lignes) and 0 <= c < len(self.lignes[0]) and self.lignes[l][c] != texte:
            self.lignes[l][c] = texte.replace("\n", " ")
            self._enregistrer()

    def ajouter_ligne(self):
        self.lignes = logique.ajouter_ligne(self.lignes)
        self._enregistrer()
        self.table.scrollToBottom()

    def ajouter_colonne(self):
        for r in self.lignes:
            r.append("")
        self.totaux.append("")
        self._enregistrer()

    def choisir_total(self, colonne: int, fonction: str):
        self.totaux[colonne] = fonction
        self._enregistrer()

    def inserer_ligne(self, indice: int):
        self.lignes.insert(max(1, min(indice, len(self.lignes))), [""] * len(self.lignes[0]))
        self._enregistrer()

    def supprimer_lignes(self, indices):
        for i in sorted(set(indices), reverse=True):
            if 0 < i < len(self.lignes):                           # l'en-tête reste
                del self.lignes[i]
        self._enregistrer()

    def inserer_colonne(self, indice: int):
        indice = max(0, min(indice, len(self.lignes[0])))
        for r in self.lignes:
            r.insert(indice, "")
        self.totaux.insert(indice, "")
        self._enregistrer()

    def supprimer_colonnes(self, indices):
        for i in sorted(set(indices), reverse=True):
            if len(self.lignes[0]) > 1 and 0 <= i < len(self.lignes[0]):
                for r in self.lignes:
                    del r[i]
                del self.totaux[i]
        self._enregistrer()

    def vider(self, cellules):
        for l, c in cellules:
            if l < len(self.lignes):
                self.lignes[l][c] = ""
        self._enregistrer()

    def _cellules(self) -> list:
        return sorted({(i.row(), i.column()) for i in self.table.selectedIndexes() if i.row() < len(self.lignes)})

    def copier(self):
        sel = self._cellules()
        if sel:
            l0, l1 = sel[0][0], max(l for l, _c in sel)
            c0, c1 = min(c for _l, c in sel), max(c for _l, c in sel)
            QApplication.clipboard().setText("\n".join("\t".join(self.lignes[l][c] for c in range(c0, c1 + 1)) for l in range(l0, l1 + 1)))

    def coller(self):
        texte, sel = QApplication.clipboard().text(), self._cellules()
        if not texte or not sel:
            return
        l0, c0 = sel[0][0], min(c for _l, c in sel)
        for dl, ligne in enumerate(texte.rstrip("\n").split("\n")):
            for dc, v in enumerate(ligne.split("\t")):
                while l0 + dl >= len(self.lignes):
                    self.lignes.append([""] * len(self.lignes[0]))
                while c0 + dc >= len(self.lignes[0]) and len(self.lignes[0]) < logique.MAX_COLONNES:
                    for r in self.lignes:
                        r.append("")
                    self.totaux.append("")
                if c0 + dc < len(self.lignes[0]):
                    self.lignes[l0 + dl][c0 + dc] = v.strip()
        self._enregistrer()

    def _touche(self, ev):
        if ev.matches(QKeySequence.StandardKey.Copy):
            self.copier()
        elif ev.matches(QKeySequence.StandardKey.Paste):
            self.coller()
        elif ev.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.table.state() != QAbstractItemView.State.EditingState:
            self.vider(self._cellules())
        else:
            QTableWidget.keyPressEvent(self.table, ev)

    def _menu(self, pos):
        it = self.table.itemAt(pos)
        l, c = (it.row(), it.column()) if it is not None else (len(self.lignes), len(self.lignes[0]) - 1)
        m = QMenu(self.table)
        if l >= len(self.lignes):                                  # ligne des totaux
            for code, nom in _noms_totaux().items():
                a = m.addAction(nom, lambda code=code: self.choisir_total(c, code))
                a.setCheckable(True)
                a.setChecked(self.totaux[c] == code)
        else:
            sel = self._cellules() or [(l, c)]
            m.addAction(icone("edit-copy"), _("Copier"), self.copier)
            m.addAction(icone("edit-paste"), _("Coller"), self.coller)
            m.addSeparator()
            m.addAction(_("Insérer une ligne au-dessus"), lambda: self.inserer_ligne(l))
            m.addAction(_("Insérer une ligne en dessous"), lambda: self.inserer_ligne(l + 1))
            m.addAction(icone("edit-delete"), _("Supprimer la ligne"), lambda: self.supprimer_lignes([x for x, _c in sel]))
            m.addSeparator()
            m.addAction(_("Insérer une colonne à gauche"), lambda: self.inserer_colonne(c))
            m.addAction(_("Insérer une colonne à droite"), lambda: self.inserer_colonne(c + 1))
            m.addAction(icone("edit-delete"), _("Supprimer la colonne"), lambda: self.supprimer_colonnes([y for _l, y in sel]))
        m.exec(self.table.viewport().mapToGlobal(pos))

    # ---------- CSV ----------
    def exporter_csv(self):
        chemin, _filtre = QFileDialog.getSaveFileName(self, _("Exporter en CSV"), "liste.csv", _("Fichiers CSV (*.csv)"))
        if chemin:
            with open(chemin, "w", encoding="utf-8-sig", newline="") as f:
                f.write(logique.vers_csv(self.lignes))
            self.etat.setText(_("Exporté : %s") % chemin)

    def importer_csv(self):
        chemin, _filtre = QFileDialog.getOpenFileName(self, _("Importer un CSV"), "", _("Fichiers CSV (*.csv *.txt);;Tous les fichiers (*)"))
        if not chemin:
            return
        try:
            with open(chemin, encoding="utf-8-sig", errors="replace") as f:
                lignes = logique.depuis_csv(f.read())
        except OSError as ex:
            QMessageBox.warning(self, _("Importer un CSV"), str(ex))
            return
        if not lignes:
            QMessageBox.information(self, _("Importer un CSV"), _("Ce fichier ne contient aucun tableau."))
            return
        if any(c.strip() for r in self.lignes[1:] for c in r) and QMessageBox.question(
                self, _("Importer un CSV"), _("Remplacer le contenu actuel de la fiche par ce fichier ?")) != QMessageBox.StandardButton.Yes:
            return
        self.lignes, self.totaux = lignes, [""] * len(lignes[0])
        self._enregistrer()


class CalcPlugin(Plugin):
    api = 1

    def activer(self, ctx):
        self.ctx = ctx
        ctx.ajouter_doc(_("Extension Calc"), DOC)
        if ctx.ui is not None:
            ctx.ui.enregistrer_type(logique.TYPE, VueCalc())


DOC = _(
    "Un petit éditeur de listes avec de petits calculs, pour suivre des données : relevés de compteur, poids, dépenses…\n"
    "\n"
    "• Nouvelle fiche > « Calc » : une liste avec les colonnes « Date » et « Valeur ». La première ligne est l'en-tête : renommez-la, ajoutez des colonnes.\n"
    "• Double-clic (ou F2) sur une cellule pour la modifier. Un nombre s'écrit avec une virgule ou un point.\n"
    "• « Ajouter une ligne » : si la première colonne s'appelle « Date », elle reçoit la date du jour.\n"
    "• La ligne grisée du bas donne un total par colonne : clic droit dessus pour choisir (somme, moyenne, minimum, maximum, nombre, ou aucun). "
    "Les totaux se recalculent à chaque modification.\n"
    "• « Exporter en CSV… » écrit la liste dans un fichier (séparateur « ; », que LibreOffice et Excel ouvrent directement) ; « Importer un "
    "CSV… » remplace la liste par un fichier.\n"
    "• Clic droit : insérer ou supprimer des lignes et des colonnes. Suppr vide les cellules. Ctrl+C et Ctrl+V : copier, coller (on peut "
    "coller depuis un autre tableur).\n"
    "• Le texte de la fiche est un tableau Markdown : lisible partout, cherchable, partageable, verrouillable. Rien n'est exécuté.\n"
    "• Besoin de formules cellule par cellule (=B2*C2, =SOMME(B2:B10)) ? Utilisez l'extension Tableur.")

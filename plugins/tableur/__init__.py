# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « Tableur » : une fiche d'un nouveau type, `tableur` (`#scrinium-tableur`) : un mini tableur pour suivre des données, par
exemple des relevés (voir `logique.py` : format, formules, calcul sûr).

- La fiche montre une grille vide (colonnes A, B… ; lignes 1, 2… ; la première cellule est A1). Au-dessus, une BARRE DE FORMULE montre le contenu
  brut de la cellule choisie ; on le modifie là (Entrée) ou dans la cellule (double-clic, F2). Une cellule qui commence par « = » est une formule
  (=A1*B1, =SOMME(B1:B10), =MOYENNE(B1:B10)…) : la grille montre le résultat, la barre la formule.
- « Ajouter une ligne » : si A1 s'appelle « Date », la colonne A reçoit la date du jour. « Totaux » : une ligne de somme, moyenne, minimum ou
  maximum sous les données. Clic droit : insérer ou supprimer des lignes et des colonnes. Suppr : vide les cellules. Ctrl+C / Ctrl+V : copier,
  coller (tabulations : on peut coller depuis un autre tableur). Export et import CSV.
- Le texte de la fiche reste un tableau Markdown lisible partout ; type non exécutable : la fiche ne lance rien."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QKeySequence
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QStyledItemDelegate,
                             QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget)

from scrinium.core.plugins import Plugin
from scrinium.i18n import _
from scrinium.ui.icons import icone

from . import logique

BRUT = Qt.ItemDataRole.UserRole


class _Delegue(QStyledItemDelegate):
    """On édite le texte BRUT (la formule), pas le résultat affiché."""

    def __init__(self, vue):
        super().__init__(vue.table)
        self.vue = vue

    def setEditorData(self, editeur, index):
        editeur.setText(index.data(BRUT) or "")

    def setModelData(self, editeur, modele, index):
        self.vue.modifier_cellule(index.row(), index.column(), editeur.text())


class VueTableur(QWidget):
    """Vue du type « tableur » : la grille, ses boutons ; le texte de la fiche est le tableau Markdown."""
    modifie = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.actif = True                       # type non exécutable : toujours utilisable
        self.lignes: list = []
        self.notes = ""
        self._remplit = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        haut = QHBoxLayout()
        self.b_ligne = QPushButton(icone("list-add"), _("Ajouter une ligne"))
        self.b_ligne.clicked.connect(lambda *_a: self.ajouter_ligne())
        self.b_colonne = QPushButton(icone("list-add"), _("Ajouter une colonne"))
        self.b_colonne.clicked.connect(lambda *_a: self.ajouter_colonne())
        self.b_totaux = QToolButton()
        self.b_totaux.setText(_("Totaux"))
        self.b_totaux.setIcon(icone("accessories-calculator"))
        self.b_totaux.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.b_totaux.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        m = QMenu(self.b_totaux)
        for fn, nom in (("SOMME", _("Somme")), ("MOYENNE", _("Moyenne")), ("MIN", _("Minimum")), ("MAX", _("Maximum"))):
            m.addAction(nom, lambda fn=fn, nom=nom: self.totaux(fn, nom))
        self.b_totaux.setMenu(m)
        self.b_export = QPushButton(icone("document-export"), _("Exporter en CSV…"))
        self.b_export.clicked.connect(lambda *_a: self.exporter_csv())
        self.b_import = QPushButton(icone("document-import"), _("Importer un CSV…"))
        self.b_import.clicked.connect(lambda *_a: self.importer_csv())
        for b in (self.b_ligne, self.b_colonne, self.b_totaux, self.b_export, self.b_import):
            haut.addWidget(b)
        haut.addStretch(1)
        lay.addLayout(haut)
        barre = QHBoxLayout()                    # barre de formule : nom de la cellule courante + son contenu brut
        self.nom_cellule = QLabel("A1")
        self.nom_cellule.setMinimumWidth(40)
        self.nom_cellule.setStyleSheet("font-weight: bold;")
        self.barre = QLineEdit()
        self.barre.setPlaceholderText(_("Contenu de la cellule : un nombre, du texte, ou une formule comme =SOMME(A1:A5)"))
        self.barre.returnPressed.connect(self._valider_barre)
        barre.addWidget(self.nom_cellule)
        barre.addWidget(self.barre, 1)
        lay.addLayout(barre)
        self.table = QTableWidget()
        self.table.currentCellChanged.connect(lambda *_a: self._maj_barre())
        self.table.setItemDelegate(_Delegue(self))
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.keyPressEvent = self._touche
        lay.addWidget(self.table, 1)
        self.etat = QLabel()
        lay.addWidget(self.etat)

    # ---------- affichage ----------
    def charger(self, texte: str):
        lignes, self.notes = logique.lire(texte)
        self.lignes = lignes or logique.vide()
        self._afficher()

    def _maj_barre(self):
        l, c = self.table.currentRow(), self.table.currentColumn()
        ok = 0 <= l < len(self.lignes) and 0 <= c < len(self.lignes[0])
        self.nom_cellule.setText(logique.nom_cellule(l, c) if ok else "")
        self.barre.setText(self.lignes[l][c] if ok else "")
        self.barre.setEnabled(ok)

    def _valider_barre(self):
        l, c = self.table.currentRow(), self.table.currentColumn()
        if 0 <= l < len(self.lignes) and 0 <= c < len(self.lignes[0]):
            self.modifier_cellule(l, c, self.barre.text())
            self.table.setCurrentCell(min(l + 1, len(self.lignes) - 1), c)
            self.table.setFocus()

    def _afficher(self):
        courante = (self.table.currentRow(), self.table.currentColumn())
        self._remplit = True
        n_l, n_c = len(self.lignes), len(self.lignes[0])
        self.table.clear()
        self.table.setRowCount(n_l)
        self.table.setColumnCount(n_c)
        self.table.setHorizontalHeaderLabels([logique.nom_colonne(c) for c in range(n_c)])
        self.table.setVerticalHeaderLabels([str(i + 1) for i in range(n_l)])
        feuille = logique.Feuille(self.lignes)
        for l in range(n_l):
            for c in range(n_c):
                brut = self.lignes[l][c]
                it = QTableWidgetItem(feuille.affichage(l, c))
                it.setData(BRUT, brut)
                if brut.strip().startswith("="):
                    it.setToolTip(brut)
                    if feuille.est_erreur(l, c):
                        it.setForeground(QBrush(QColor("#c0392b")))
                if logique.nombre(brut) is not None or brut.strip().startswith("="):
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(l, c, it)
        self.table.resizeColumnsToContents()
        for c in range(n_c):
            self.table.setColumnWidth(c, max(90, self.table.columnWidth(c)))
        self.etat.setText(_("%(l)d lignes, %(c)d colonnes. Pour une formule : cliquez une cellule, tapez = puis la formule, par exemple =SOMME(A1:A5) ou =A1*B1, et Entrée.")
                          % {"l": n_l, "c": n_c})
        self._remplit = False
        self.table.setCurrentCell(max(0, courante[0]), max(0, courante[1]))
        self._maj_barre()

    def _enregistrer(self):
        self.modifie.emit(logique.ecrire(self.lignes, self.notes))
        self._afficher()

    # ---------- modifications ----------
    def modifier_cellule(self, l: int, c: int, texte: str):
        if (0 <= l < len(self.lignes) and 0 <= c < len(self.lignes[0])) and self.lignes[l][c] != texte:
            self.lignes[l][c] = texte.replace("\n", " ")
            self._enregistrer()

    def ajouter_ligne(self):
        self.lignes = logique.ajouter_ligne(self.lignes)
        self._enregistrer()
        self.table.scrollToBottom()

    def ajouter_colonne(self):
        for i, r in enumerate(self.lignes):
            r.append("")
        self._enregistrer()

    def totaux(self, fonction: str, libelle: str):
        self.lignes = logique.ligne_de_totaux(self.lignes, fonction, libelle)
        self._enregistrer()

    def exporter_csv(self):
        """Écrit les résultats (pas les formules) dans un fichier CSV choisi par l'utilisateur."""
        chemin, _filtre = QFileDialog.getSaveFileName(self, _("Exporter en CSV"), "tableau.csv", _("Fichiers CSV (*.csv)"))
        if chemin:
            with open(chemin, "w", encoding="utf-8-sig", newline="") as f:
                f.write(logique.vers_csv(self.lignes))
            self.etat.setText(_("Exporté : %s") % chemin)

    def importer_csv(self):
        """Remplace le tableau par le contenu d'un fichier CSV (après accord si le tableau n'est pas vide)."""
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
        self.lignes = lignes
        self._enregistrer()

    def inserer_ligne(self, indice: int):
        self.lignes.insert(max(1, min(indice, len(self.lignes))), [""] * len(self.lignes[0]))
        self._enregistrer()

    def supprimer_lignes(self, indices):
        for i in sorted(set(indices), reverse=True):
            if i > 0 and len(self.lignes) > 1:                     # l'en-tête reste
                del self.lignes[i]
        self._enregistrer()

    def inserer_colonne(self, indice: int):
        for r in self.lignes:
            r.insert(max(0, min(indice, len(r))), "")
        self._enregistrer()

    def supprimer_colonnes(self, indices):
        for i in sorted(set(indices), reverse=True):
            if len(self.lignes[0]) > 1:
                for r in self.lignes:
                    del r[i]
        self._enregistrer()

    def vider(self, cellules):
        for l, c in cellules:
            self.lignes[l][c] = ""
        self._enregistrer()

    def _cellules(self) -> list:
        return sorted({(i.row(), i.column()) for i in self.table.selectedIndexes()})

    def copier(self):
        sel = self._cellules()
        if not sel:
            return
        l0, l1 = sel[0][0], max(l for l, _c in sel)
        c0, c1 = min(c for _l, c in sel), max(c for _l, c in sel)
        QApplication.clipboard().setText("\n".join("\t".join(self.lignes[l][c] for c in range(c0, c1 + 1)) for l in range(l0, l1 + 1)))

    def coller(self):
        texte = QApplication.clipboard().text()
        sel = self._cellules()
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
        l, c = (it.row(), it.column()) if it is not None else (len(self.lignes) - 1, len(self.lignes[0]) - 1)
        sel = self._cellules() or [(l, c)]
        m = QMenu(self.table)
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


class TableurPlugin(Plugin):
    api = 1

    def activer(self, ctx):
        self.ctx = ctx
        ctx.ajouter_doc(_("Extension Tableur"), DOC)
        if ctx.ui is None:
            return
        ctx.ui.enregistrer_type(logique.TYPE, VueTableur())


DOC = _(
    "Un tableur pour des cellules et des formules, par exemple pour suivre des relevés (compteur, poids, dépenses…).\n"
    "\n"
    "• Nouvelle fiche > « Tableur » : une grille vide. Les colonnes sont A, B, C… et les lignes 1, 2, 3… : la première cellule est A1.\n"
    "• Cliquez une cellule et tapez : un nombre (virgule ou point), du texte, ou une FORMULE. Une formule commence par « = ». La barre au-dessus "
    "de la grille montre le contenu de la cellule choisie (la formule, pas son résultat) : on peut aussi la modifier là, puis Entrée. "
    "Double-clic ou F2 : modifier dans la cellule.\n"
    "• Exemples de formules : =A1*B1, =B3-B2, =SOMME(B1:B10), =MOYENNE(B1:B10), =MAX(B1:B10)-MIN(B1:B10), =ARRONDI(A1/3;2). "
    "Fonctions : SOMME, MOYENNE, MIN, MAX, NB, ABS, ARRONDI, RACINE, ENT. Opérations : + - * / ^ %. Les erreurs s'affichent dans la cellule "
    "(#DIV/0!, #REF!, #CYCLE!…).\n"
    "• Si la première colonne s'appelle « Date » (cellule A1), « Ajouter une ligne » y met la date du jour. « Totaux » ajoute une ligne de somme, "
    "moyenne, minimum ou maximum sous les données.\n"
    "• Clic droit : insérer ou supprimer des lignes et des colonnes. Suppr vide les cellules. Ctrl+C et Ctrl+V : copier, coller (on peut "
    "coller depuis un autre tableur).\n"
    "• « Exporter en CSV… » écrit les résultats dans un fichier (séparateur « ; », que LibreOffice et Excel ouvrent directement) ; « Importer "
    "un CSV… » remplace le tableau par un fichier.\n"
    "• Le texte de la fiche est un tableau Markdown : lisible partout, cherchable, partageable, verrouillable. Rien n'est exécuté : seules "
    "ces opérations sont comprises. L'impression et l'export PDF montrent les résultats.\n"
    "• Pour une simple liste avec des totaux par colonne, voyez l'extension Calc.")

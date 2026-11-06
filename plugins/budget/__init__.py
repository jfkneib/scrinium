# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « Budget » : de petits comptes (courses, argent de poche des enfants…), pas de la comptabilité (voir `logique.py`).

- Une fiche « Budget » = un budget. Un ONGLET par mois (avec un titre libre : « Rentrée », « Vacances »…) et un onglet « Bilan ».
- Saisie rapide : date, libellé, catégorie, montant, puis « Débit » ou « Crédit » (le bouton met le montant dans la bonne colonne). Les
  cellules du tableau se modifient directement ; clic droit : supprimer la ligne. Le solde est recalculé.
- « Budget mensuel » (facultatif) : le bilan dit ce qu'il en reste. « Solde de départ » (facultatif).
- Une fiche « Budget — résultat » totalise TOUS les budgets (un mois au choix, ou tous). Les budgets verrouillés fermés n'y sont pas comptés.
- Export CSV. Le texte reste un tableau Markdown ; type non exécutable : la fiche ne lance rien."""
from datetime import date

from PyQt6.QtCore import QLocale, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QPushButton,
                             QStackedWidget, QTabBar, QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget)

from scrinium.core.plugins import Plugin
from scrinium.i18n import _
from scrinium.ui.icons import icone

from . import logique

ROUGE = QBrush(QColor("#c0392b"))


def nom_mois(m: str) -> str:
    """« 2026-11 » -> « Novembre 2026 » (dans la langue de l'interface)."""
    n = QLocale().monthName(int(m[5:7]), QLocale.FormatType.LongFormat)
    return f"{n[:1].upper()}{n[1:]} {m[:4]}"


def _item(texte="", droite=False, editable=True, rouge=False, gras=False) -> QTableWidgetItem:
    it = QTableWidgetItem(texte)
    if droite:
        it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    if not editable:
        it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    if rouge:
        it.setForeground(ROUGE)
    if gras:
        f = it.font()
        f.setBold(True)
        it.setFont(f)
    return it


def _table(colonnes: list, hauteur_min: int = 0, extensible: int = 0) -> QTableWidget:
    """Tableau sans numéros de ligne ; la colonne `extensible` prend la place restante."""
    t = QTableWidget(0, len(colonnes))
    t.setHorizontalHeaderLabels(colonnes)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setSectionResizeMode(extensible, QHeaderView.ResizeMode.Stretch)
    t.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    if hauteur_min:
        t.setMinimumHeight(hauteur_min)
    return t


class VueBudget(QWidget):
    """Vue du type « budget » : onglets par mois, saisie rapide, tableau des opérations, bilan."""
    modifie = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.actif = True                        # type non exécutable : toujours utilisable
        self.b = logique.Budget()
        self.mois: list = []
        self.courant: str | None = None          # mois affiché ; None = onglet « Bilan »
        self._remplit = False
        self._indices: list = []                 # indice dans b.operations de chaque ligne du tableau
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        haut = QHBoxLayout()
        haut.addWidget(QLabel(_("Budget mensuel")))
        self.e_mensuel = QLineEdit()
        self.e_mensuel.setFixedWidth(90)
        self.e_mensuel.setPlaceholderText(_("aucun"))
        self.e_mensuel.editingFinished.connect(self._reglages)
        haut.addWidget(self.e_mensuel)
        haut.addWidget(QLabel(_("Solde de départ")))
        self.e_depart = QLineEdit()
        self.e_depart.setFixedWidth(90)
        self.e_depart.setPlaceholderText("0")
        self.e_depart.editingFinished.connect(self._reglages)
        haut.addWidget(self.e_depart)
        haut.addStretch(1)
        self.b_mois = QToolButton()
        self.b_mois.setText(_("Nouveau mois"))
        self.b_mois.setIcon(icone("list-add"))
        self.b_mois.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.b_mois.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu_mois = QMenu(self.b_mois)
        menu_mois.aboutToShow.connect(lambda: self._remplir_menu_mois(menu_mois))
        self.b_mois.setMenu(menu_mois)
        self.b_export = QPushButton(icone("document-export"), _("Exporter en CSV…"))
        self.b_export.clicked.connect(lambda *_a: self.exporter_csv())
        haut.addWidget(self.b_mois)
        haut.addWidget(self.b_export)
        lay.addLayout(haut)
        self.onglets = QTabBar()
        self.onglets.setExpanding(False)
        self.onglets.setUsesScrollButtons(True)
        self.onglets.currentChanged.connect(self._onglet)
        lay.addWidget(self.onglets)
        self.pile = QStackedWidget()
        lay.addWidget(self.pile, 1)
        self.statut = QLabel()
        lay.addWidget(self.statut)
        self._page_mois()
        self._page_bilan()

    # ---------- construction ----------
    def _page_mois(self):
        p = QWidget()
        lay = QVBoxLayout(p)
        lay.setContentsMargins(0, 4, 0, 0)
        ligne = QHBoxLayout()
        ligne.addWidget(QLabel(_("Titre de ce mois")))
        self.e_titre = QLineEdit()
        self.e_titre.setPlaceholderText(_("facultatif : Rentrée, Vacances…"))
        self.e_titre.editingFinished.connect(self._titre)
        ligne.addWidget(self.e_titre, 1)
        lay.addLayout(ligne)
        saisie = QHBoxLayout()
        self.e_date = QLineEdit()
        self.e_date.setFixedWidth(95)
        self.e_date.setPlaceholderText(_("AAAA-MM-JJ"))
        self.e_libelle = QLineEdit()
        self.e_libelle.setPlaceholderText(_("Libellé"))
        self.c_categorie = QComboBox()
        self.c_categorie.setEditable(True)
        self.c_categorie.setMinimumWidth(120)
        self.c_categorie.lineEdit().setPlaceholderText(_("Catégorie"))
        self.e_montant = QLineEdit()
        self.e_montant.setFixedWidth(90)
        self.e_montant.setPlaceholderText(_("Montant"))
        self.e_montant.returnPressed.connect(lambda: self.ajouter("debit"))
        self.e_libelle.returnPressed.connect(self.e_montant.setFocus)
        self.b_debit = QPushButton(_("Débit"))
        self.b_debit.setToolTip(_("Une dépense : le montant va dans la colonne Débit"))
        self.b_debit.clicked.connect(lambda *_a: self.ajouter("debit"))
        self.b_credit = QPushButton(_("Crédit"))
        self.b_credit.setToolTip(_("Une entrée d'argent : le montant va dans la colonne Crédit"))
        self.b_credit.clicked.connect(lambda *_a: self.ajouter("credit"))
        for w, etirement in ((self.e_date, 0), (self.e_libelle, 1), (self.c_categorie, 0), (self.e_montant, 0), (self.b_debit, 0), (self.b_credit, 0)):
            saisie.addWidget(w, etirement)
        lay.addLayout(saisie)
        self.table = _table([_("Date"), _("Libellé"), _("Catégorie"), _("Débit"), _("Crédit"), _("Solde")], extensible=1)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.itemChanged.connect(self._cellule)
        lay.addWidget(self.table, 1)
        self.totaux = QLabel()
        self.totaux.setWordWrap(True)
        lay.addWidget(self.totaux)
        self.pile.addWidget(p)

    def _page_bilan(self):
        p = QWidget()
        lay = QVBoxLayout(p)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.addWidget(QLabel(_("Mois par mois")))
        self.t_mois = _table([_("Mois"), _("Titre"), _("Débits"), _("Crédits"), _("Solde du mois"), _("Solde de fin")], 120, 1)
        lay.addWidget(self.t_mois, 1)
        lay.addWidget(QLabel(_("Dépenses par catégorie (tous les mois)")))
        self.t_cat = _table([_("Catégorie"), _("Débits"), _("Part")], 120, 2)
        lay.addWidget(self.t_cat, 1)
        self.pile.addWidget(p)

    # ---------- affichage ----------
    def charger(self, texte: str):
        self.b = logique.lire(texte)
        self.mois = logique.mois_presents(self.b)
        if self.courant not in self.mois and self.courant is not None:
            self.courant = None
        if self.courant is None and not getattr(self, "_bilan_voulu", False):
            self.courant = logique.mois_courant() if logique.mois_courant() in self.mois else self.mois[-1]
        self._tout_afficher()

    def _tout_afficher(self):
        self._remplit = True
        self.e_mensuel.setText(logique.formater(self.b.mensuel, False) if self.b.mensuel else "")
        self.e_depart.setText(logique.formater(self.b.depart, False) if self.b.depart else "")
        self.onglets.blockSignals(True)
        while self.onglets.count():
            self.onglets.removeTab(self.onglets.count() - 1)
        for m in self.mois:
            t = self.b.titres.get(m, "")
            self.onglets.addTab(nom_mois(m) + (f" — {t}" if t else ""))
        self.onglets.addTab(_("Bilan"))
        self.onglets.setCurrentIndex(self.mois.index(self.courant) if self.courant in self.mois else len(self.mois))
        self.onglets.blockSignals(False)
        cats = logique.categories(self.b)
        courante = self.c_categorie.currentText()
        self.c_categorie.clear()
        self.c_categorie.addItems([""] + cats)
        self.c_categorie.setCurrentText(courante)
        if self.courant in self.mois:
            self.pile.setCurrentIndex(0)
            self._afficher_mois()
        else:
            self.pile.setCurrentIndex(1)
            self._afficher_bilan()
        self._remplit = False

    def _afficher_mois(self):
        m = self.courant
        self.e_titre.setText(self.b.titres.get(m, ""))
        if not self.e_date.text().strip() or logique.mois_de(self.e_date.text()) != m:
            aujourdhui = date.today().isoformat()
            self.e_date.setText(aujourdhui if logique.mois_de(aujourdhui) == m else m + "-01")
        ops = logique.operations_du_mois(self.b, m)
        self._indices = [i for i, _o in ops]
        self.table.setRowCount(len(ops))
        solde = logique.solde_avant(self.b, m)
        for r, (_i, o) in enumerate(ops):
            solde += o.credit - o.debit
            vals = [o.date, o.libelle, o.categorie, logique.formater(o.debit) if o.debit else "", logique.formater(o.credit) if o.credit else ""]
            for c, v in enumerate(vals):
                self.table.setItem(r, c, _item(v, droite=c >= 3))
            self.table.setItem(r, 5, _item(logique.formater(solde), droite=True, editable=False, rouge=solde < 0, gras=True))
        self.table.resizeColumnsToContents()
        t = logique.totaux(self.b, m)
        txt = _("Débits %(d)s · Crédits %(c)s · Solde du mois %(s)s · Solde de fin de mois %(f)s") % {
            "d": logique.formater(t["debit"]), "c": logique.formater(t["credit"]),
            "s": logique.formater(t["solde_mois"]), "f": logique.formater(t["solde_fin"])}
        if t["reste"] is not None:
            txt += " · " + (_("Reste sur le budget : %s") % logique.formater(t["reste"]) if t["reste"] >= 0
                            else _("Budget dépassé de %s") % logique.formater(-t["reste"]))
        self.totaux.setText(txt)

    def _afficher_bilan(self):
        lignes = logique.resume_par_mois(self.b)
        self.t_mois.setRowCount(len(lignes) + 1)
        for r, (m, titre, t) in enumerate(lignes):
            vals = [nom_mois(m), titre, t["debit"], t["credit"], t["solde_mois"], t["solde_fin"]]
            for c, v in enumerate(vals):
                if c >= 2:
                    self.t_mois.setItem(r, c, _item(logique.formater(v), droite=True, editable=False, rouge=c >= 4 and v < 0))
                else:
                    self.t_mois.setItem(r, c, _item(v, editable=False))
        g = logique.totaux(self.b)
        r = len(lignes)
        for c, v in enumerate([_("Total"), "", logique.formater(g["debit"]), logique.formater(g["credit"]), logique.formater(g["solde_mois"]),
                               logique.formater(g["solde_fin"])]):
            self.t_mois.setItem(r, c, _item(v, droite=c >= 2, editable=False, gras=True, rouge=c >= 4 and (g["solde_mois"] if c == 4 else g["solde_fin"]) < 0))
        self.t_mois.resizeColumnsToContents()
        cats = logique.par_categorie(self.b)
        somme = sum(v for _c, v in cats) or 1
        self.t_cat.setRowCount(len(cats))
        for r, (cat, v) in enumerate(cats):
            part = v / somme
            self.t_cat.setItem(r, 0, _item(cat or _("(sans catégorie)"), editable=False))
            self.t_cat.setItem(r, 1, _item(logique.formater(v), droite=True, editable=False))
            self.t_cat.setItem(r, 2, _item("█" * max(1, round(part * 20)) + f" {part * 100:.0f} %", editable=False))
        self.t_cat.resizeColumnsToContents()

    def _onglet(self, i: int):
        if self._remplit:
            return
        self._bilan_voulu = i >= len(self.mois)
        self.courant = self.mois[i] if i < len(self.mois) else None
        self._tout_afficher()

    # ---------- modifications ----------
    def _enregistrer(self, texte_statut: str = ""):
        self.mois = logique.mois_presents(self.b)
        self.modifie.emit(logique.ecrire(self.b))
        self._tout_afficher()
        self.statut.setText(texte_statut)

    def _reglages(self):
        if self._remplit:
            return
        m, d = logique.centimes(self.e_mensuel.text()), logique.centimes(self.e_depart.text())
        nouveau_m = m if m and m > 0 else None
        if nouveau_m != self.b.mensuel or (d or 0) != self.b.depart:
            self.b.mensuel, self.b.depart = nouveau_m, d or 0
            self._enregistrer()

    def _titre(self):
        if self._remplit or self.courant not in self.mois:
            return
        t = self.e_titre.text().strip()
        if t != self.b.titres.get(self.courant, ""):
            if t or not any(logique.mois_de(o.date) == self.courant for o in self.b.operations):
                self.b.titres[self.courant] = t                 # un mois sans opération reste (onglet) même sans titre
            else:
                self.b.titres.pop(self.courant, None)
            self._enregistrer()

    def _remplir_menu_mois(self, menu):
        menu.clear()
        avant, apres = logique.mois_precedent(self.mois[0]), logique.mois_suivant(self.mois[-1])
        menu.addAction(_("Mois suivant : %s") % nom_mois(apres), lambda: self.nouveau_mois(apres))
        menu.addAction(_("Mois précédent : %s") % nom_mois(avant), lambda: self.nouveau_mois(avant))

    def nouveau_mois(self, mois: str | None = None):
        """Ajoute l'onglet d'un mois (par défaut le suivant le dernier ; `logique.mois_precedent` pour un mois déjà passé). Un mois sans
        opération existe par une ligne « mois AAAA-MM: » (titre vide)."""
        m = mois or logique.mois_suivant(self.mois[-1])
        self.b.titres.setdefault(m, "")
        self.courant, self._bilan_voulu = m, False
        self._enregistrer()
        self.e_titre.setFocus()

    def ajouter(self, sens: str):
        """Ajoute une opération (`sens` : « debit » ou « credit ») avec les champs de saisie."""
        d = self.e_date.text().strip()
        montant = logique.centimes(self.e_montant.text())
        if not logique.date_valide(d):
            self.statut.setText(_("Date invalide : écrivez AAAA-MM-JJ, par exemple 2026-11-06."))
            return
        if not montant or montant <= 0:
            self.statut.setText(_("Montant invalide : écrivez un nombre positif, par exemple 45,30."))
            return
        o = logique.Operation(d, self.e_libelle.text().strip(), self.c_categorie.currentText().strip())
        setattr(o, sens, montant)
        self.b.operations.append(o)
        self.courant, self._bilan_voulu = logique.mois_de(d), False
        self.e_libelle.clear()
        self.e_montant.clear()
        self._enregistrer(_("Ajouté : %s") % logique.formater(montant))
        self.e_libelle.setFocus()

    def _cellule(self, it):
        if self._remplit or not 0 <= it.row() < len(self._indices) or it.column() > 4:
            return
        o = self.b.operations[self._indices[it.row()]]
        t, c = it.text().strip(), it.column()
        if c == 0:
            if not logique.date_valide(t):
                self.statut.setText(_("Date invalide : écrivez AAAA-MM-JJ, par exemple 2026-11-06."))
                return self._tout_afficher()
            o.date = t
        elif c == 1:
            o.libelle = t
        elif c == 2:
            o.categorie = t
        else:
            v = logique.centimes(t) if t else 0
            if v is None or v < 0:
                self.statut.setText(_("Montant invalide : écrivez un nombre positif, par exemple 45,30."))
                return self._tout_afficher()
            setattr(o, "debit" if c == 3 else "credit", v)
        self.courant = logique.mois_de(o.date)
        self._enregistrer()

    def supprimer_lignes(self, lignes):
        for i in sorted({self._indices[r] for r in lignes if 0 <= r < len(self._indices)}, reverse=True):
            del self.b.operations[i]
        self._enregistrer()

    def _menu(self, pos):
        lignes = sorted({i.row() for i in self.table.selectedIndexes()})
        it = self.table.itemAt(pos)
        if it is not None and it.row() not in lignes:
            lignes = [it.row()]
        if not lignes:
            return
        m = QMenu(self.table)
        m.addAction(icone("edit-delete"), _("Supprimer la ligne"), lambda: self.supprimer_lignes(lignes))
        m.exec(self.table.viewport().mapToGlobal(pos))

    def exporter_csv(self):
        chemin, _filtre = QFileDialog.getSaveFileName(self, _("Exporter en CSV"), "budget.csv", _("Fichiers CSV (*.csv)"))
        if chemin:
            with open(chemin, "w", encoding="utf-8-sig", newline="") as f:
                f.write(logique.vers_csv(self.b))
            self.statut.setText(_("Exporté : %s") % chemin)


class VueResultat(QWidget):
    """Vue du type « budget-resultat » : les totaux de TOUS les budgets (fiches de type budget), pour un mois ou pour l'ensemble."""
    modifie = pyqtSignal(str)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.actif = True
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        haut = QHBoxLayout()
        haut.addWidget(QLabel(_("Budgets")))
        self.c_portee = QComboBox()
        self.c_portee.addItem(_("Ceux de ce thème"), "theme")
        self.c_portee.addItem(_("Tous les thèmes"), "tous")
        self.c_portee.currentIndexChanged.connect(self._portee_choisie)
        haut.addWidget(self.c_portee)
        haut.addWidget(QLabel(_("Période")))
        self.c_mois = QComboBox()
        self.c_mois.currentIndexChanged.connect(lambda *_a: self._afficher())
        haut.addWidget(self.c_mois)
        self.b_maj = QPushButton(icone("view-refresh"), _("Actualiser"))
        self.b_maj.clicked.connect(lambda *_a: self.charger(""))
        haut.addWidget(self.b_maj)
        haut.addStretch(1)
        lay.addLayout(haut)
        self.table = _table([_("Budget"), _("Débits"), _("Crédits"), _("Solde"), _("Reste sur le budget")], extensible=0)
        lay.addWidget(self.table, 1)
        self.note = QLabel()
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        self._budgets: list = []
        self._texte = ""

    def _portee_choisie(self):
        if not self._remplit:
            self.modifie.emit(logique.texte_resultat(self.c_portee.currentData(), self._texte))
            self.charger(logique.texte_resultat(self.c_portee.currentData(), self._texte))

    _remplit = False

    def charger(self, texte: str):
        self._texte = texte or ""
        self._remplit = True
        self.c_portee.setCurrentIndex(self.c_portee.findData(logique.portee_de(texte)))
        self._remplit = False
        courante = self.ctx.fiche_courante() if self.ctx else None
        theme = courante.theme if courante is not None else None
        fiches = self.ctx.fiches() if self.ctx else []
        if self.c_portee.currentData() == "theme" and theme is not None:
            fiches = [f for f in fiches if f.theme == theme]
        tous = self.c_portee.currentData() == "tous" or theme is None
        self._budgets = [(f"{f.titre}  ({f.theme})" if tous else f.titre, logique.lire(f.texte))
                         for f in fiches if f.texte is not None and logique.est_budget(f.texte)]
        self._fermes = sum(1 for f in fiches if f.texte is None and f.verrou)
        courant = self.c_mois.currentData()
        self.c_mois.blockSignals(True)
        self.c_mois.clear()
        self.c_mois.addItem(_("Tous les mois"), None)
        for m in reversed(logique.mois_de_tous(self._budgets)):
            self.c_mois.addItem(nom_mois(m), m)
        i = self.c_mois.findData(courant)
        self.c_mois.setCurrentIndex(i if i >= 0 else (1 if self.c_mois.count() > 1 else 0))
        self.c_mois.blockSignals(False)
        self._afficher()

    def _afficher(self):
        mois = self.c_mois.currentData()
        r = logique.resultat(self._budgets, mois)
        self.table.setRowCount(len(r["lignes"]) + 1)
        for i, (nom, t) in enumerate(r["lignes"]):
            self.table.setItem(i, 0, _item(nom, editable=False))
            for c, v in enumerate([t["debit"], t["credit"], t["solde_mois"] if mois else t["solde_fin"]], 1):
                self.table.setItem(i, c, _item(logique.formater(v), droite=True, editable=False, rouge=c == 3 and v < 0))
            self.table.setItem(i, 4, _item("" if t["reste"] is None else logique.formater(t["reste"]), droite=True, editable=False,
                                           rouge=bool(t["reste"] is not None and t["reste"] < 0)))
        t, n = r["total"], len(r["lignes"])
        solde = t["solde_mois"] if mois else t["solde_fin"]
        for c, v in enumerate([_("Total"), logique.formater(t["debit"]), logique.formater(t["credit"]), logique.formater(solde),
                               "" if t["reste"] is None else logique.formater(t["reste"])]):
            self.table.setItem(n, c, _item(v, droite=c > 0, editable=False, gras=True, rouge=c == 3 and solde < 0))
        self.table.resizeColumnsToContents()
        texte = (_("%d budget(s) comptés.") % len(self._budgets)) if self._budgets else _(
            "Aucun budget ici : créez une fiche « Budget » dans ce thème, ou choisissez « Tous les thèmes ».")
        texte += " " + _("Pour un mois, le « Solde » est celui du mois ; pour « Tous les mois », c'est le solde actuel (solde de départ compris).")
        if self._fermes:
            texte += " " + _("%d fiche(s) verrouillée(s) fermée(s) ne peuvent pas être lues : si l'une est un budget, ouvrez-la puis actualisez.") % self._fermes
        self.note.setText(texte)


class BudgetPlugin(Plugin):
    api = 1

    def activer(self, ctx):
        self.ctx = ctx
        ctx.ajouter_doc(_("Extension Budget"), DOC)
        for theme, titre, texte in logique.exemples():
            ctx.ajouter_exemple(theme, titre, texte, "wallet-open")
        if ctx.ui is not None:
            ctx.ui.enregistrer_type(logique.TYPE, VueBudget())
            ctx.ui.enregistrer_type(logique.TYPE_RESULTAT, VueResultat(ctx))


DOC = _(
    "De petits comptes, pas de la comptabilité : le budget des courses, l'argent de poche d'un enfant…\n"
    "\n"
    "• Nouvelle fiche > « Budget » : une fiche = un budget (« Courses », « Enfant 1 »…). Un onglet par mois, avec un titre libre (« Rentrée », "
    "« Vacances »…) à renseigner en haut de l'onglet, et un onglet « Bilan ».\n"
    "• Saisie rapide : date (celle du jour), libellé, catégorie (celles déjà utilisées sont proposées), montant, puis le bouton « Débit » (une "
    "dépense) ou « Crédit » (une entrée d'argent). Entrée dans le montant = Débit. Les cellules du tableau se modifient directement ; "
    "clic droit : supprimer la ligne. Le solde est recalculé tout seul.\n"
    "• « Budget mensuel » (facultatif) : l'onglet du mois dit ce qu'il en reste, ou de combien il est dépassé. « Solde de départ » (facultatif).\n"
    "• « Nouveau mois » : ajoute l'onglet du mois suivant, ou d'un mois déjà passé (« Mois précédent »). On peut aussi saisir une opération à une "
    "date plus ancienne : l'onglet de ce mois apparaît tout seul. Les montants s'écrivent avec une virgule ou un point.\n"
    "• Bilan : mois par mois (débits, crédits, solde) et dépenses par catégorie.\n"
    "• Nouvelle fiche > « Budget — résultat » : une fiche qui totalise vos budgets, pour un mois au choix ou pour l'ensemble. Par défaut, elle "
    "totalise les budgets du MÊME THÈME qu'elle (rangez-la avec eux) ; « Tous les thèmes » en haut totalise tous vos budgets. Elle se met à "
    "jour quand on l'ouvre ou qu'on clique sur « Actualiser ». Un budget verrouillé et fermé ne peut pas être lu : ouvrez-le d'abord.\n"
    "• « Exporter en CSV… » : Date, Libellé, Catégorie, Débit, Crédit, Solde (séparateur « ; », que LibreOffice et Excel ouvrent directement).\n"
    "• Un budget est un tableau Markdown : lisible partout, cherchable, partageable (extension Partage) et verrouillable (conseillé pour des "
    "comptes). Rien n'est exécuté.")

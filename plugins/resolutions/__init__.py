# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « Résolutions » : suivre ses bonnes résolutions, avec une note automatique et des encouragements (voir `logique.py`).

- Une fiche « Résolutions » = une liste de résolutions, « chaque jour » ou « N fois par semaine ». Une case à cocher par jour (le jour se
  choisit : on peut cocher hier), la série en cours, la plus belle série, le taux des 14 derniers jours et une bande des 14 derniers jours.
- En haut : la NOTE sur 100 (moyenne des taux), des étoiles, et un message d'encouragement qui suit la note, la tendance et les séries.
- Le texte reste lisible et modifiable à la main ; type non exécutable : la fiche ne lance rien."""
from datetime import date, timedelta

from PyQt6.QtCore import QDate, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                             QHeaderView, QLabel, QLineEdit, QMenu, QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from scrinium.core.plugins import Plugin
from scrinium.i18n import _
from scrinium.ui.icons import icone

from . import logique


def couleur_taux(t: float) -> QColor:
    """Taux de réussite -> rouge (0 %) , jaune (50 %), vert (100 %), en teinte claire."""
    return QColor.fromHsv(int(120 * min(max(t, 0.0), 1.0)), 110, 240)


class DialogueResolution(QDialog):
    """Créer ou modifier une résolution."""

    def __init__(self, r=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Résolution"))
        f = QFormLayout(self)
        self.nom = QLineEdit(r.nom if r else "")
        self.nom.setPlaceholderText(_("Marcher 30 minutes"))
        self.rythme = QComboBox()
        self.rythme.addItem(_("Chaque jour"), 0)
        self.rythme.addItem(_("Plusieurs fois par semaine"), 1)
        self.fois = QSpinBox()
        self.fois.setRange(1, 6)
        self.fois.setSuffix(_(" fois par semaine"))
        if r and r.par_semaine:
            self.rythme.setCurrentIndex(1)
            self.fois.setValue(r.par_semaine)
        else:
            self.fois.setValue(3)
        self.rythme.currentIndexChanged.connect(lambda *_a: self.fois.setEnabled(self.rythme.currentData() == 1))
        self.fois.setEnabled(self.rythme.currentData() == 1)
        self.debut = QDateEdit(QDate.fromString(r.debut, "yyyy-MM-dd") if r else QDate.currentDate())
        self.debut.setCalendarPopup(True)
        f.addRow(_("Résolution :"), self.nom)
        f.addRow(_("Rythme :"), self.rythme)
        f.addRow("", self.fois)
        f.addRow(_("Depuis le :"), self.debut)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        b.accepted.connect(self._valider)
        b.rejected.connect(self.reject)
        f.addRow(b)

    def _valider(self):
        if self.nom.text().strip():
            self.accept()
        else:
            self.nom.setFocus()
            QMessageBox.warning(self, self.windowTitle(), _("Le nom est vide : saisissez-le avant de valider."))

    def valeurs(self) -> tuple:
        return (" ".join(self.nom.text().split()), self.fois.value() if self.rythme.currentData() == 1 else 0,
                self.debut.date().toString("yyyy-MM-dd"))


class VueResolutions(QWidget):
    """Vue du type « résolutions » : note, encouragement, tableau des résolutions avec une case par jour."""
    modifie = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.actif = True                                  # type non exécutable : toujours utilisable
        self.rs: list = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.l_note = QLabel()
        self.l_note.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.l_note)
        self.l_encourage = QLabel()
        self.l_encourage.setWordWrap(True)
        lay.addWidget(self.l_encourage)
        haut = QHBoxLayout()
        haut.addWidget(QLabel(_("Jour")))
        self.e_jour = QDateEdit(QDate.currentDate())
        self.e_jour.setCalendarPopup(True)
        self.e_jour.setMaximumDate(QDate.currentDate())
        self.e_jour.dateChanged.connect(lambda *_a: self._afficher())
        haut.addWidget(self.e_jour)
        self.b_ajouter = QPushButton(icone("list-add"), _("Ajouter une résolution…"))
        self.b_ajouter.clicked.connect(self._ajouter)
        haut.addWidget(self.b_ajouter)
        haut.addStretch(1)
        lay.addLayout(haut)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([_("Fait"), _("Résolution"), _("Rythme"), _("Série"), _("Record"), _("14 derniers jours"), _("Taux")])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.table, 1)
        self.aide = QLabel(_("Cochez le jour choisi ; la note compte les 14 derniers jours. Clic droit : modifier ou supprimer."))
        self.aide.setWordWrap(True)
        lay.addWidget(self.aide)

    # ---------- données ----------
    def charger(self, texte: str):
        self.rs = logique.lire(texte)
        self._afficher()

    def _enregistrer(self):
        self.modifie.emit(logique.ecrire(self.rs))
        self._afficher()

    def _jour(self) -> date:
        return self.e_jour.date().toPyDate()

    def _cocher(self, i: int):
        if 0 <= i < len(self.rs):
            logique.basculer(self.rs[i], self._jour())
            self._enregistrer()

    def _ajouter(self):
        d = DialogueResolution(None, self)
        if d.exec():
            nom, fois, debut = d.valeurs()
            r = logique.normaliser(logique.Resolution(nom, fois, debut))
            if r and len(self.rs) < logique.MAX_RESOLUTIONS:
                self.rs.append(r)
                self._enregistrer()

    def _modifier(self, i: int):
        if 0 <= i < len(self.rs):
            d = DialogueResolution(self.rs[i], self)
            if d.exec():
                r = self.rs[i]
                r.nom, r.par_semaine, r.debut = d.valeurs()
                self.rs[i] = logique.normaliser(r) or r
                self._enregistrer()

    def _supprimer(self, i: int):
        if 0 <= i < len(self.rs):
            del self.rs[i]
            self._enregistrer()

    def _menu(self, pos):
        i = self.table.rowAt(pos.y())
        m = QMenu(self)
        m.addAction(icone("list-add"), _("Ajouter une résolution…"), self._ajouter)
        if i >= 0:
            m.addAction(icone("document-edit"), _("Modifier…"), lambda: self._modifier(i))
            m.addAction(icone("edit-delete"), _("Supprimer"), lambda: self._supprimer(i))
        m.exec(self.table.viewport().mapToGlobal(pos))

    # ---------- affichage ----------
    def _bande(self, r, auj: date) -> str:
        cases = []
        for k in range(logique.FENETRE - 1, -1, -1):
            d = auj - timedelta(days=k)
            if logique.est_fait(r, d):
                cases.append("<span style='color:#2e7d32'>■</span>")
            elif d.isoformat() >= r.debut and (not r.fin or d.isoformat() <= r.fin) and d != auj:
                cases.append("<span style='color:#c8c8c8'>■</span>")
            else:
                cases.append("<span style='color:#c8c8c8'>▫</span>")
        return "".join(cases)

    def _afficher(self):
        auj = date.today()
        jour = self._jour()
        note = logique.score(self.rs, auj)
        self.l_note.setText(("<span style='font-size:20pt'><b>%s</b></span> <span style='font-size:20pt;color:#e0a800'>%s</span>"
                             % ((_("Note : %d / 100") % note) if note is not None else _("Note : —"), logique.etoiles(note))))
        self.l_encourage.setText(" ".join(logique.encouragement(self.rs, auj)))
        self.table.setRowCount(len(self.rs))
        for i, r in enumerate(self.rs):
            case = QCheckBox()
            case.setChecked(logique.est_fait(r, jour))
            case.setEnabled(jour <= auj)
            case.toggled.connect(lambda _oui, i=i: self._cocher(i))
            conteneur = QWidget()
            lh = QHBoxLayout(conteneur)
            lh.setContentsMargins(0, 0, 0, 0)
            lh.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lh.addWidget(case)
            self.table.setCellWidget(i, 0, conteneur)
            s, rec, t = logique.serie(r, auj), logique.meilleure_serie(r, auj), logique.taux(r, auj)
            unite = _("sem.") if r.par_semaine else _("j")
            cases = [None, r.nom, _("Chaque jour") if not r.par_semaine else _("%d fois par semaine") % r.par_semaine,
                     f"{s} {unite}" if s else "–", f"{rec} {unite}" if rec else "–", None, f"{round(100 * t)} %" if t is not None else "–"]
            for c, texte in enumerate(cases):
                if texte is None:
                    continue
                it = QTableWidgetItem(texte)
                if c == 6 and t is not None:
                    it.setBackground(couleur_taux(t))
                    it.setForeground(QColor("#1b1b1b"))
                self.table.setItem(i, c, it)
            bande = QLabel(self._bande(r, auj))
            bande.setTextFormat(Qt.TextFormat.RichText)
            bande.setToolTip(_("Du plus ancien au plus récent ; le dernier carré est aujourd'hui."))
            self.table.setCellWidget(i, 5, bande)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)


class ResolutionsPlugin(Plugin):
    api = 1

    def activer(self, ctx):
        self.ctx = ctx
        ctx.ajouter_doc(_("Extension Résolutions"), DOC)
        for theme, titre, texte in logique.exemples():
            ctx.ajouter_exemple(theme, titre, texte, "task-complete")
        if ctx.ui is not None:
            ctx.ui.enregistrer_type(logique.TYPE, VueResolutions())


DOC = _(
    "Suivre ses bonnes résolutions, avec une note automatique et des encouragements.\n"
    "\n"
    "• Nouvelle fiche > « Résolutions » : « Ajouter une résolution… ». Chaque résolution est « chaque jour » (marcher, boire de l'eau…) ou « N fois par "
    "semaine » (lire, faire du sport…), depuis une date.\n"
    "• Une case à cocher par jour. Le jour se choisit en haut : on peut cocher hier. Le jour en cours, pas encore coché, n'est pas compté contre vous.\n"
    "• La série est le nombre de jours (ou de semaines) d'affilée réussis ; le record garde la plus belle. Un carré par jour pour les 14 derniers jours.\n"
    "• La note sur 100 est la moyenne des taux de réussite des 14 derniers jours, avec des étoiles. Le message d'encouragement suit la note, la tendance "
    "(par rapport aux 14 jours précédents) et vos séries.\n"
    "• Le texte reste lisible et modifiable à la main ; rien n'est exécuté. Un carnet pour se motiver, pas un jugement.")

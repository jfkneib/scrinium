# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « Échéances » : assurances, noms de domaine, certificats, contrôle technique, garanties, abonnements (voir `logique.py`).

- Une fiche « Échéances et abonnements » = un tableau trié par prochaine date, coloré selon l'urgence (rouge, orange, jaune, vert). Une échéance qui
  se répète (mensuelle, annuelle, tous les 2 ans…) passe d'elle-même à la date suivante. Chacune a un RAPPEL (nombre de jours avant la date).
- En haut : combien d'échéances sous 30 jours, combien en retard, ce qu'il y a à payer sous 30 jours et sur les 12 mois à venir.
- Notification (zone de notification du bureau) à l'approche de chaque échéance et pour un retard, une seule fois par date : au démarrage de
  l'extension, puis toutes les heures. Elle lit toutes vos fiches « Échéances » (une fiche verrouillée et fermée est ignorée).
- Le texte reste un tableau Markdown lisible ; type non exécutable : la fiche ne lance rien."""
from datetime import date

from PyQt6.QtCore import QDate, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (QAbstractItemView, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
                             QLineEdit, QMenu, QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from scrinium.core import types_fiche
from scrinium.core.plugins import Plugin
from scrinium.i18n import _
from scrinium.ui.icons import icone

from . import logique

COULEURS = {"retard": (0, 130), "urgent": (14, 120), "bientot": (45, 120), "ok": (120, 70)}          # teinte, saturation du fond (pastel)
INTERVALLE = 3600                                                                                        # secondes entre deux relectures pour les rappels


def libelle_statut(s: str) -> str:
    return {"retard": _("En retard"), "urgent": _("Urgent"), "bientot": _("Bientôt"), "ok": _("Plus tard")}[s]


def libelle_repetition(mois: int) -> str:
    return next(_(lib) for m, _mot, lib in logique.REPETITIONS if m == mois)


class DialogueEcheance(QDialog):
    """Créer ou modifier une échéance."""

    def __init__(self, e=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Échéance"))
        self.resize(420, 300)
        f = QFormLayout(self)
        self.nom = QLineEdit(e.nom if e else "")
        self.nom.setPlaceholderText(_("Assurance habitation"))
        self.date = QDateEdit(QDate.fromString(e.date, "yyyy-MM-dd") if e else QDate.currentDate().addDays(30))
        self.date.setCalendarPopup(True)
        self.rep = QComboBox()
        for mois, _mot, lib in logique.REPETITIONS:
            self.rep.addItem(_(lib), mois)
        if e:
            self.rep.setCurrentIndex(max(0, self.rep.findData(e.mois)))
        self.montant = QLineEdit("" if not e or e.montant is None else ("%.2f" % e.montant).rstrip("0").rstrip("."))
        self.montant.setPlaceholderText(_("facultatif"))
        self.rappel = QSpinBox()
        self.rappel.setRange(0, 365)
        self.rappel.setSuffix(_(" jours avant"))
        self.rappel.setValue(e.rappel if e else logique.RAPPEL_DEFAUT)
        self.note = QLineEdit(e.note if e else "")
        f.addRow(_("Échéance :"), self.nom)
        f.addRow(_("Date :"), self.date)
        f.addRow(_("Répétition :"), self.rep)
        f.addRow(_("Montant :"), self.montant)
        f.addRow(_("Rappel :"), self.rappel)
        f.addRow(_("Note :"), self.note)
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

    def resultat(self):
        return logique.normaliser(logique.Echeance(self.nom.text(), self.date.date().toString("yyyy-MM-dd"), self.rep.currentData(),
                                                   logique.lire_montant(self.montant.text()), self.rappel.value(), self.note.text()))


class VueEcheances(QWidget):
    """Vue du type « échéances » : résumé, tableau trié par prochaine date et coloré selon l'urgence."""
    modifie = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.actif = True                                  # type non exécutable : toujours utilisable
        self.doc = logique.Document()
        self._ordre: list = []                             # échéances dans l'ordre du tableau
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.l_resume = QLabel()
        self.l_resume.setWordWrap(True)
        self.l_resume.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.l_resume)
        haut = QHBoxLayout()
        self.b_ajouter = QPushButton(icone("list-add"), _("Ajouter une échéance…"))
        self.b_ajouter.clicked.connect(self._ajouter)
        haut.addWidget(self.b_ajouter)
        haut.addWidget(QLabel(_("Devise")))
        self.e_devise = QLineEdit()
        self.e_devise.setFixedWidth(50)
        self.e_devise.editingFinished.connect(self._devise)
        haut.addWidget(self.e_devise)
        haut.addStretch(1)
        lay.addLayout(haut)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([_("État"), _("Échéance"), _("Prochaine date"), _("Dans"), _("Répétition"), _("Montant"), _("Note")])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.doubleClicked.connect(lambda idx: self._modifier(idx.row()))
        lay.addWidget(self.table, 1)
        self.aide = QLabel(_("Une échéance qui se répète passe d'elle-même à la date suivante. Double-clic ou clic droit : modifier ou supprimer."))
        self.aide.setWordWrap(True)
        lay.addWidget(self.aide)

    def showEvent(self, ev):
        super().showEvent(ev)
        self._afficher()                                   # la date du jour a pu changer depuis la dernière fois

    # ---------- données ----------
    def charger(self, texte: str):
        self.doc = logique.lire(texte)
        self._afficher()

    def _enregistrer(self):
        self.modifie.emit(logique.ecrire(self.doc))
        self._afficher()

    def _devise(self):
        d = self.e_devise.text().strip()[:6]
        if d != self.doc.devise:
            self.doc.devise = d
            self._enregistrer()

    def _ajouter(self):
        d = DialogueEcheance(None, self)
        if d.exec() and d.resultat() and len(self.doc.echeances) < logique.MAX_ECHEANCES:
            self.doc.echeances.append(d.resultat())
            self._enregistrer()

    def _modifier(self, ligne: int):
        if 0 <= ligne < len(self._ordre):
            e = self._ordre[ligne]
            d = DialogueEcheance(e, self)
            if d.exec() and d.resultat():
                i = next(k for k, x in enumerate(self.doc.echeances) if x is e)
                self.doc.echeances[i] = d.resultat()
                self._enregistrer()

    def _supprimer(self, ligne: int):
        if 0 <= ligne < len(self._ordre):
            e = self._ordre[ligne]
            self.doc.echeances = [x for x in self.doc.echeances if x is not e]
            self._enregistrer()

    def _menu(self, pos):
        i = self.table.rowAt(pos.y())
        m = QMenu(self)
        m.addAction(icone("list-add"), _("Ajouter une échéance…"), self._ajouter)
        if i >= 0:
            m.addAction(icone("document-edit"), _("Modifier…"), lambda: self._modifier(i))
            m.addAction(icone("edit-delete"), _("Supprimer"), lambda: self._supprimer(i))
        m.exec(self.table.viewport().mapToGlobal(pos))

    # ---------- affichage ----------
    def _afficher(self):
        auj = date.today()
        dev = self.doc.devise
        if not self.e_devise.hasFocus():
            self.e_devise.setText(dev)
        self._ordre = logique.trier(self.doc.echeances, auj)
        self.table.setRowCount(len(self._ordre))
        for i, e in enumerate(self._ordre):
            s, j = logique.statut(e, auj), logique.jours_restants(e, auj)
            dans = _("aujourd'hui") if j == 0 else (_("%d j") % j if j > 0 else _("il y a %d j") % -j)
            cases = [libelle_statut(s), e.nom, logique.prochaine(e, auj).strftime("%d/%m/%Y"), dans, libelle_repetition(e.mois),
                     logique.formater_montant(e.montant, dev), e.note]
            teinte, sat = COULEURS[s]
            for c, texte in enumerate(cases):
                it = QTableWidgetItem(texte)
                if c in (0, 3):
                    it.setBackground(QBrush(QColor.fromHsv(teinte, sat, 240)))
                    it.setForeground(QBrush(QColor("#1b1b1b")))
                if c == 5:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(i, c, it)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        r = logique.resume(self.doc, auj)
        morceaux = [_("<b>%d</b> échéance(s) sous 30 jours") % r["sous30"]]
        if r["retards"]:
            morceaux.append("<span style='color:#c0392b'><b>%s</b></span>" % (_("%d en retard") % r["retards"]))
        if r["montant30"]:
            morceaux.append(_("à payer sous 30 jours : <b>%s</b>") % logique.formater_montant(r["montant30"], dev))
        if r["montant365"]:
            morceaux.append(_("sur 12 mois : <b>%s</b>") % logique.formater_montant(r["montant365"], dev))
        self.l_resume.setText(" · ".join(morceaux) if self.doc.echeances else _("Ajoutez une première échéance : assurance, domaine, garantie…"))


class EcheancesPlugin(Plugin):
    api = 1

    def activer(self, ctx):
        self.ctx = ctx
        ctx.ajouter_doc(_("Extension Échéances"), DOC)
        for theme, titre, texte in logique.exemples():
            ctx.ajouter_exemple(theme, titre, texte, "view-calendar-tasks")
        if ctx.ui is not None:
            ctx.ui.enregistrer_type(logique.TYPE, VueEcheances())
            ctx.ui.planifier(10, self.verifier)                            # une fois, peu après le démarrage
            ctx.ui.planifier(INTERVALLE, self.verifier, repeter=True)

    def a_signaler(self, aujourdhui: date | None = None) -> list:
        """Messages à notifier maintenant (et mémorisés pour ne pas les répéter) d'après toutes les fiches « Échéances » lisibles."""
        auj = aujourdhui or date.today()
        deja = dict(self.ctx.reglages.get("notifie", {}) or {})
        messages = []
        for f in self.ctx.fiches():
            if f.texte is None or types_fiche.marque(f.texte) != logique.TYPE.nom:
                continue
            doc = logique.lire(f.texte)
            for _cle, e, jours in logique.a_notifier(doc, auj, deja, f.identifiant or f.titre):
                messages.append((jours, logique.message(e, jours, auj, doc.devise)))
        self.ctx.reglages.set("notifie", deja)
        return [m for _j, m in sorted(messages)]

    def verifier(self):
        messages = self.a_signaler()
        if messages:
            suite = (_(" … et %d autre(s)") % (len(messages) - 5)) if len(messages) > 5 else ""
            self.ctx.ui.notifier(_("Échéances"), "\n".join(messages[:5]) + suite)


DOC = _(
    "Assurances, noms de domaine, certificats, contrôle technique, garanties, abonnements : ne plus rater une date.\n"
    "\n"
    "• Nouvelle fiche > « Échéances et abonnements » : « Ajouter une échéance… » (nom, date, répétition, montant, rappel, note). Le tableau est trié par "
    "prochaine date et coloré : rouge (en retard), orange (urgent, 7 jours ou moins), jaune (dans le rappel), vert (plus tard).\n"
    "• Répétition : une fois, chaque mois, trimestre, semestre, année ou tous les 2 ans. Une échéance qui se répète passe d'elle-même à la date suivante ; "
    "une échéance « une fois » dépassée reste « en retard » jusqu'à ce que vous la modifiiez ou la supprimiez.\n"
    "• Le rappel est le nombre de jours avant la date où Scrinium vous prévient. En haut : les échéances sous 30 jours, les retards, ce qu'il y a à payer "
    "sous 30 jours et sur les 12 mois à venir (la devise se règle à côté).\n"
    "• Notification du bureau à l'approche de chaque échéance et pour un retard, une seule fois par date : au démarrage de l'extension, puis toutes les heures. "
    "Elle lit toutes vos fiches « Échéances » (une fiche verrouillée et fermée est ignorée). Scrinium doit être ouvert.\n"
    "• Le texte reste un tableau Markdown lisible, cherchable et partageable ; rien n'est exécuté.")

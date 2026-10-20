# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « Agenda et rappels » : événements datés, liés ou non à une fiche, notifiés à l'heure dite.

- Fenêtre « Agenda » (menu Extensions et barre d'outils) : ajouter, modifier, supprimer, ouvrir la fiche liée.
- Vérification toutes les 30 secondes : une notification par événement (les événements manqués pendant que Scrinium
  était fermé sont annoncés au démarrage, marqués « en retard »).
- Aucun lien vers une fiche verrouillée (son titre resterait lisible dans les réglages).
- Les événements sont dans les réglages de l'extension (settings.json)."""
from datetime import datetime

from PyQt6.QtCore import QDateTime, Qt
from PyQt6.QtWidgets import (QApplication, QCheckBox, QDateTimeEdit, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                             QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout)

from scrinium.core.plugins import Plugin
from scrinium.i18n import _

from . import logique

INTERVALLE = 30      # secondes entre deux vérifications


def _parent():
    return QApplication.activeWindow()


class DialogueEvenement(QDialog):
    def __init__(self, parent, e=None, fiche=None):
        super().__init__(parent)
        self.setWindowTitle(_("Événement"))
        lay = QFormLayout(self)
        self.titre = QLineEdit((e or {}).get("titre", ""))
        self.quand = QDateTimeEdit(QDateTime.currentDateTime().addSecs(3600))
        self.quand.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.quand.setCalendarPopup(True)
        d = logique.en_date((e or {}).get("quand", ""))
        if d:
            self.quand.setDateTime(QDateTime(d))
        lay.addRow(_("Titre"), self.titre)
        lay.addRow(_("Date et heure"), self.quand)
        self.lier = None
        self._fiche = (e or {}).get("fiche") or fiche
        if self._fiche:
            self.lier = QCheckBox(_("Lier à la fiche « %(theme)s / %(titre)s »") % self._fiche)
            self.lier.setChecked(True)
            lay.addRow(self.lier)
        boutons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        boutons.accepted.connect(self._valider)
        boutons.rejected.connect(self.reject)
        lay.addRow(boutons)

    def _valider(self):
        if self.titre.text().strip():
            self.accept()
        else:
            self.titre.setFocus()

    def resultat(self) -> tuple:
        fiche = self._fiche if self.lier is not None and self.lier.isChecked() else None
        return self.titre.text(), self.quand.dateTime().toPyDateTime().replace(second=0, microsecond=0), fiche


class DialogueAgenda(QDialog):
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.p = plugin
        self.setWindowTitle(_("Agenda"))
        self.resize(560, 380)
        lay = QVBoxLayout(self)
        self.liste = QListWidget()
        self.liste.itemDoubleClicked.connect(lambda _i: self.ouvrir())
        lay.addWidget(self.liste)
        self.vide = QLabel(_("Aucun événement. « Ajouter » en crée un ; la fiche affichée peut y être liée."))
        self.vide.setWordWrap(True)
        lay.addWidget(self.vide)
        rang = QHBoxLayout()
        for texte, fn in ((_("Ajouter…"), self.ajouter), (_("Modifier…"), self.modifier), (_("Supprimer"), self.supprimer),
                          (_("Ouvrir la fiche"), self.ouvrir)):
            b = QPushButton(texte)
            b.clicked.connect(fn)
            rang.addWidget(b)
        rang.addStretch()
        fermer = QPushButton(_("Fermer"))
        fermer.clicked.connect(self.accept)
        rang.addWidget(fermer)
        lay.addLayout(rang)
        self.rafraichir()

    def rafraichir(self):
        self.liste.clear()
        maintenant = datetime.now()
        for e in self.p.evenements():
            d = logique.en_date(e["quand"])
            lien = f"   ·   {e['fiche']['theme']} / {e['fiche']['titre']}" if e["fiche"] else ""
            it = QListWidgetItem(f"{e['quand']}   ({logique.delai_texte(d, maintenant)})   {e['titre']}{lien}")
            it.setData(Qt.ItemDataRole.UserRole, e["id"])
            self.liste.addItem(it)
        self.vide.setVisible(self.liste.count() == 0)

    def _courant(self):
        it = self.liste.currentItem()
        return next((e for e in self.p.evenements() if it and e["id"] == it.data(Qt.ItemDataRole.UserRole)), None)

    def ajouter(self):
        d = DialogueEvenement(self, fiche=self.p.fiche_liable())
        if d.exec():
            self.p.ajouter(*d.resultat())
            self.rafraichir()

    def modifier(self):
        e = self._courant()
        if e is None:
            return
        d = DialogueEvenement(self, e)
        if d.exec():
            titre, quand, fiche = d.resultat()
            self.p.remplacer(e["id"], titre, quand, fiche)
            self.rafraichir()

    def supprimer(self):
        e = self._courant()
        if e is not None and QMessageBox.question(self, _("Supprimer"), _("Supprimer « %s » ?") % e["titre"]) \
                == QMessageBox.StandardButton.Yes:
            self.p.supprimer(e["id"])
            self.rafraichir()

    def ouvrir(self):
        e = self._courant()
        if e is not None and e["fiche"] and not self.p.ouvrir_fiche(e["fiche"]):
            QMessageBox.information(self, _("Agenda"), _("Cette fiche n'existe plus ou est verrouillée."))


class AgendaPlugin(Plugin):
    api = 1

    def activer(self, ctx):
        self.ctx = ctx
        if ctx.ui is None:
            return
        ctx.ui.ajouter_action(_("Agenda…"), self.afficher, "view-calendar")
        ctx.ui.ajouter_bouton(_("Agenda"), self.afficher, "view-calendar")
        ctx.ui.planifier(INTERVALLE, self.verifier, repeter=True)
        ctx.ui.planifier(2, self.verifier)           # événements manqués pendant que Scrinium était fermé

    # ---------- données ----------
    def evenements(self) -> list:
        return logique.charger(self.ctx.reglages.get("evenements", []))

    def _sauver(self, evenements: list):
        self.ctx.reglages.set("evenements", evenements)

    def ajouter(self, titre, quand, fiche=None):
        evs = self.evenements()
        logique.ajouter(evs, titre, quand, fiche)
        self._sauver(evs)

    def remplacer(self, id_, titre, quand, fiche=None):
        evs = [e for e in self.evenements() if e["id"] != id_]
        logique.ajouter(evs, titre, quand, fiche, id_)       # même identifiant ; « notifie » repart à zéro
        self._sauver(evs)

    def supprimer(self, id_):
        self._sauver([e for e in self.evenements() if e["id"] != id_])

    # ---------- fiches ----------
    def fiche_liable(self) -> dict | None:
        """Fiche affichée, sauf si elle est verrouillée."""
        v = self.ctx.fiche_courante()
        return {"theme": v.theme, "titre": v.titre} if v is not None and not v.verrou else None

    def ouvrir_fiche(self, lien: dict) -> bool:
        for v in self.ctx.fiches(lien["theme"]):
            if v.titre == lien["titre"] and not v.verrou:
                self.ctx.ui.afficher_fiche(v)
                return True
        return False

    # ---------- actions ----------
    def afficher(self):
        DialogueAgenda(self, _parent()).exec()

    def verifier(self):
        """Annonce les événements dont l'heure est venue (une seule fois chacun)."""
        maintenant = datetime.now()
        evs = self.evenements()
        dus = logique.a_notifier(evs, maintenant)
        for e in dus:
            d = logique.en_date(e["quand"])
            retard = maintenant - d
            suffixe = f" ({logique.delai_texte(d, maintenant)})" if retard.total_seconds() > 120 else ""
            self.ctx.ui.notifier(_("Rappel"), f"{e['titre']}{suffixe}")
            e["notifie"] = True
        if dus:
            self._sauver(evs)

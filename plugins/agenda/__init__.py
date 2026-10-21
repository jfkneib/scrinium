# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « Agenda et rappels » : événements datés, liés ou non à une fiche, notifiés à l'heure dite.

- Fenêtre « Agenda » (menu Extensions et barre d'outils) : ajouter, modifier, supprimer, ouvrir la fiche liée.
- Vérification toutes les 30 secondes : une notification par événement (les événements manqués pendant que Scrinium
  était fermé sont annoncés au démarrage, marqués « en retard »).
- Aucun lien vers une fiche verrouillée (son titre resterait lisible dans les réglages).
- Les événements sont dans les réglages de l'extension (settings.json)."""
from datetime import datetime, timedelta

from PyQt6.QtCore import QDate, QTime, Qt
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                             QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QTimeEdit, QVBoxLayout)

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
        self.date = QDateEdit()
        self.date.setDisplayFormat("yyyy-MM-dd")
        self.date.setCalendarPopup(True)
        self.heure = QTimeEdit()
        self.heure.setDisplayFormat("HH:mm")
        d = logique.en_date((e or {}).get("ancre") or (e or {}).get("quand", "")) or (datetime.now() + timedelta(hours=1))
        self.date.setDate(QDate(d.year, d.month, d.day))
        self.heure.setTime(QTime(d.hour, d.minute))
        lay.addRow(_("Titre"), self.titre)
        lay.addRow(_("Date"), self.date)
        lay.addRow(_("Heure (24 h, ex. 14:30)"), self.heure)
        rapide = QHBoxLayout()
        for texte, fn in ((_("+10 min"), lambda: self._dans(minutes=10)), (_("+1 h"), lambda: self._dans(hours=1)),
                          (_("Demain 9:00"), self._demain)):
            b = QPushButton(texte)
            b.clicked.connect(fn)
            rapide.addWidget(b)
        lay.addRow(rapide)
        self.repete = QComboBox()
        for cle, libelle in logique.REPETITIONS.items():
            self.repete.addItem(_(libelle), cle)
        self.repete.setCurrentIndex(max(0, self.repete.findData((e or {}).get("repete", ""))))
        self.repete.setToolTip(_("La date ci-dessus est celle de départ ; Scrinium annonce ensuite chaque occurrence."))
        lay.addRow(_("Répéter"), self.repete)
        self.son = QCheckBox(_("Jouer un son au rappel"))
        self.son.setChecked((e or {}).get("son", True))
        lay.addRow(self.son)
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

    def _fixer(self, d: datetime):
        self.date.setDate(QDate(d.year, d.month, d.day))
        self.heure.setTime(QTime(d.hour, d.minute))

    def _dans(self, **delai):
        self._fixer(datetime.now() + timedelta(**delai))

    def _demain(self):
        self._fixer((datetime.now() + timedelta(days=1)).replace(hour=9, minute=0))

    def _valider(self):
        if self.titre.text().strip():
            self.accept()
        else:
            self.titre.setFocus()

    def quand(self) -> datetime:
        d, t = self.date.date(), self.heure.time()
        return datetime(d.year(), d.month(), d.day(), t.hour(), t.minute())

    def resultat(self) -> tuple:
        fiche = self._fiche if self.lier is not None and self.lier.isChecked() else None
        return self.titre.text(), self.quand(), fiche, self.son.isChecked(), self.repete.currentData()


class RappelPopup(QDialog):
    """Fenêtre de rappel, non modale et au premier plan : ouvrir la fiche, repousser, ou marquer comme fait."""

    def __init__(self, plugin, e):
        super().__init__(None)
        self.p, self.e = plugin, e
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle(_("Rappel"))
        lay = QVBoxLayout(self)
        t = QLabel(f"<b>{e['titre'].replace('<', '&lt;')}</b>")
        t.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(t)
        lay.addWidget(QLabel(f"{e['quand']}   ({logique.delai_texte(logique.en_date(e['quand']), datetime.now())})"))
        rang = QHBoxLayout()
        if e["fiche"]:
            b = QPushButton(_("Ouvrir la fiche"))
            b.clicked.connect(self._ouvrir)
            rang.addWidget(b)
        for texte, fn in ((_("Repousser de 10 min"), self._repousser), (_("Fait"), self._fait)):
            b = QPushButton(texte)
            b.clicked.connect(fn)
            rang.addWidget(b)
        lay.addLayout(rang)

    def _ouvrir(self):
        if not self.p.ouvrir_fiche(self.e["fiche"]):
            QMessageBox.information(self, _("Agenda"), _("Cette fiche n'existe plus ou est verrouillée."))

    def _repousser(self):
        if self.e["repete"]:          # la série a déjà avancé : le report est un rappel isolé, la série n'est pas décalée
            self.p.ajouter(self.e["titre"], (datetime.now() + timedelta(minutes=10)).replace(second=0, microsecond=0),
                           self.e["fiche"], self.e["son"])
        else:
            self.p.repousser(self.e["id"], 10)
        self.close()

    def _fait(self):
        if not self.e["repete"]:      # une série n'est jamais « terminée » : son occurrence suivante est déjà programmée
            self.p.marquer_fait(self.e["id"])
        self.close()


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
            etat = "✓" if e["fait"] else logique.delai_texte(d, maintenant)
            serie = f"   ↻ {_(logique.REPETITIONS[e['repete']]).lower()}" if e["repete"] else ""
            it = QListWidgetItem(f"{e['quand']}   ({etat})   {e['titre']}{serie}{lien}")
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
            self.p.remplacer(e["id"], *d.resultat())
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
        self.popups = []
        ctx.ui.planifier(INTERVALLE, self.verifier, repeter=True)
        ctx.ui.planifier(2, self.verifier)           # événements manqués pendant que Scrinium était fermé

    # ---------- données ----------
    def evenements(self) -> list:
        return logique.charger(self.ctx.reglages.get("evenements", []))

    def _sauver(self, evenements: list):
        self.ctx.reglages.set("evenements", evenements)

    def ajouter(self, titre, quand, fiche=None, son=True, repete=""):
        evs = self.evenements()
        logique.ajouter(evs, titre, quand, fiche, son=son, repete=repete)
        self._sauver(evs)

    def remplacer(self, id_, titre, quand, fiche=None, son=True, repete=""):
        evs = [e for e in self.evenements() if e["id"] != id_]
        logique.ajouter(evs, titre, quand, fiche, id_, son, repete)       # même identifiant ; « notifie » repart à zéro
        self._sauver(evs)

    def _modifier(self, id_, fn):
        evs = self.evenements()
        for e in evs:
            if e["id"] == id_:
                fn(e)
        self._sauver(sorted(evs, key=lambda x: x["quand"]))

    def repousser(self, id_, minutes=10):
        self._modifier(id_, lambda e: logique.repousser(e, minutes, datetime.now()))

    def marquer_fait(self, id_):
        self._modifier(id_, lambda e: e.update(fait=True))

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

    def _popup(self, e):
        if QApplication.instance() is None:
            return
        try:
            p = RappelPopup(self, dict(e))
            self.popups = [x for x in self.popups if x.isVisible()] + [p]
            p.show()
        except Exception:            # une fenêtre de rappel ratée ne doit pas empêcher la notification ni le marquage
            pass

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
            if e["son"] and not logique.jouer_son() and QApplication.instance() is not None:
                QApplication.beep()
            self._popup(e)
            if e["repete"]:
                logique.avancer(e, maintenant)       # prochaine occurrence ; une série manquée longtemps = une seule alerte
            else:
                e["notifie"] = True
        if dus:
            self._sauver(evs)

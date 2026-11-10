# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « Sécurité » : y a-t-il quelqu'un dans ma machine, et qui ? (voir `logique.py`).

- La fiche lit l'état de CETTE machine (sessions, connexions récentes, ports ouverts, accès à distance, comptes, clés SSH, tâches planifiées) par des
  commandes de lecture du système : sans shell, sans droits d'administrateur, rien n'est modifié ni envoyé. Linux, Windows, macOS.
- « Tout accepter comme normal » enregistre l'état actuel dans la fiche (une section par machine) ; ensuite tout ce qui est NOUVEAU est signalé
  (« À vérifier » si c'est joignable depuis l'extérieur). Clic droit : « C'est normal » / « Ce n'est plus normal ».
- « Surveiller en arrière-plan » (décoché par défaut) : toutes les 10 minutes, notification pour ce qui est nouveau et pas encore signalé.
- Type EXÉCUTABLE : une fiche reçue de l'extérieur ne lit rien tant qu'elle n'est pas validée. Limite : vue depuis la machine, pas un antivirus."""
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QHBoxLayout, QHeaderView, QLabel, QMenu, QPushButton, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

from scrinium.core import types_fiche
from scrinium.core.plugins import Plugin
from scrinium.i18n import _
from scrinium.ui.icons import icone

from . import logique

COULEURS = {"a_verifier": 8, "nouveau": 45, "connu": 120}                      # teinte du fond (pastel)
ORDRE = {"a_verifier": 0, "nouveau": 1, "connu": 2}
INTERVALLE = 600                                                              # secondes entre deux analyses en arrière-plan


def libelle_statut(s: str) -> str:
    return {"a_verifier": _("À vérifier"), "nouveau": _("Nouveau"), "connu": _("Normal")}[s]


class VueSecurite(QWidget):
    """Vue du type « sécurité » : état de la machine, comparé à la liste « normale » enregistrée dans la fiche. Fiche non validée : rien n'est lu."""
    modifie = pyqtSignal(str)
    _recu = pyqtSignal(object)                                                # constats venus du fil de travail

    def __init__(self, plugin=None, parent=None):
        super().__init__(parent)
        self.p = plugin
        self.confiance: dict = {}                                             # machine -> clés « normales »
        self.constats: list = []
        self._affiches: list = []
        self._actif = True
        self._en_cours = False
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="securite")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.l_resume = QLabel()
        self.l_resume.setWordWrap(True)
        self.l_resume.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.l_resume)
        haut = QHBoxLayout()
        self.b_analyser = QPushButton(icone("view-refresh"), _("Analyser maintenant"))
        self.b_analyser.clicked.connect(self.analyser)
        self.b_accepter = QPushButton(icone("dialog-ok-apply"), _("Tout accepter comme normal"))
        self.b_accepter.clicked.connect(self._tout_accepter)
        self.c_fond = QCheckBox(_("Surveiller en arrière-plan"))
        self.c_fond.setToolTip(_("Toutes les 10 minutes, une notification pour ce qui est nouveau. Scrinium doit rester ouvert."))
        self.c_fond.setChecked(bool(plugin is not None and plugin.fond))
        self.c_fond.toggled.connect(lambda oui: plugin.regler_fond(oui) if plugin is not None else None)
        for w in (self.b_analyser, self.b_accepter, self.c_fond):
            haut.addWidget(w)
        haut.addStretch(1)
        lay.addLayout(haut)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([_("État"), _("Type"), _("Élément"), _("Détail")])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.table, 1)
        self.limite = QLabel(_("Vue depuis cette machine, lecture seule : ce n'est pas un antivirus, et quelqu'un qui a déjà les droits d'administrateur "
                               "peut cacher ses traces. Si quelque chose vous inquiète, déconnectez la machine du réseau et faites-vous aider."))
        self.limite.setWordWrap(True)
        self.limite.setStyleSheet("color: gray;")
        lay.addWidget(self.limite)
        self._recu.connect(self._arrive)
        self._afficher()

    @property
    def actif(self) -> bool:
        return self._actif

    @actif.setter
    def actif(self, oui: bool) -> None:
        self._actif = bool(oui)
        self.b_analyser.setEnabled(self._actif)
        self.b_accepter.setEnabled(self._actif)
        self._afficher()

    def showEvent(self, ev):
        super().showEvent(ev)
        if self._actif and not self.constats and not self._en_cours:
            self.analyser()

    # ---------- données ----------
    def charger(self, texte: str):
        self.confiance = logique.lire(texte)
        self._afficher()

    def _machine(self) -> str:
        return logique.nom_machine()

    def _enregistrer(self):
        self.modifie.emit(logique.ecrire(self.confiance))
        self._afficher()

    def analyser(self):
        """Lit l'état de la machine en arrière-plan. Sans effet pour une fiche non validée."""
        if not self._actif or self._en_cours:
            return
        self._en_cours = True
        self.b_analyser.setEnabled(False)
        self._pool.submit(self._travail)

    def _travail(self):
        try:
            constats = logique.analyser_machine()
        except Exception:                                                     # une analyse qui plante ne doit pas bloquer l'interface
            constats = []
        try:
            self._recu.emit(constats)
        except RuntimeError:
            pass

    def _arrive(self, constats: list):
        self._en_cours = False
        self.b_analyser.setEnabled(self._actif)
        self.constats = constats
        self._afficher()

    def _tout_accepter(self):
        if self._actif and self.constats:
            self.confiance[self._machine()] = {c.cle for c in self.constats if not c.auto_connu}
            self._enregistrer()

    def _accepter(self, cle: str, oui: bool):
        if not self._actif:
            return
        s = self.confiance.setdefault(self._machine(), set())
        s.add(cle) if oui else s.discard(cle)
        self._enregistrer()

    def _menu(self, pos):
        i = self.table.rowAt(pos.y())
        if not self._actif or not 0 <= i < len(self._affiches):
            return
        c = self._affiches[i]
        m = QMenu(self)
        if logique.statut(c, self.confiance.get(self._machine())) == "connu" and not c.auto_connu:
            m.addAction(icone("dialog-cancel"), _("Ce n'est plus normal"), lambda: self._accepter(c.cle, False))
        elif not c.auto_connu:
            m.addAction(icone("dialog-ok-apply"), _("C'est normal"), lambda: self._accepter(c.cle, True))
        m.addAction(icone("edit-copy"), _("Copier"), lambda: QApplication.clipboard().setText(f"{c.libelle} — {c.detail}"))
        m.exec(self.table.viewport().mapToGlobal(pos))

    # ---------- affichage ----------
    def _afficher(self):
        ref = self.confiance.get(self._machine())
        self._affiches = sorted(self.constats, key=lambda c: (ORDRE[logique.statut(c, ref)], c.categorie, c.libelle))
        self.table.setRowCount(len(self._affiches))
        for i, c in enumerate(self._affiches):
            s = logique.statut(c, ref)
            cases = [libelle_statut(s), _(logique.CATEGORIES[c.categorie]), c.libelle, c.detail]
            for col, texte in enumerate(cases):
                it = QTableWidgetItem(texte)
                if col == 0:
                    it.setBackground(QBrush(QColor.fromHsv(COULEURS[s], 120, 240)))
                    it.setForeground(QBrush(QColor("#1b1b1b")))
                self.table.setItem(i, col, it)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        nom = f"<b>{self._machine()}</b>"
        if not self._actif:
            self.l_resume.setText(_("Fiche non validée : rien n'est lu. Validez-la pour analyser %s.") % nom)
        elif not self.constats:
            self.l_resume.setText(_("Analyse de %s…") % nom if self._en_cours else _("Aucune analyse pour %s : cliquez sur « Analyser maintenant ».") % nom)
        elif ref is None:
            self.l_resume.setText(_("%(m)s : %(n)d éléments. Aucune référence : regardez la liste, puis « Tout accepter comme normal » ; "
                                    "ensuite, tout ce qui est nouveau sera signalé.") % {"m": nom, "n": len(self.constats)})
        else:
            nouv = logique.nouveautes(self.constats, ref)
            self.l_resume.setText((_("%(m)s : %(n)d éléments, <span style='color:#c0392b'><b>%(k)d nouveau(x)</b></span>.") if nouv else
                                   _("%(m)s : %(n)d éléments, rien de nouveau.")) % {"m": nom, "n": len(self.constats), "k": len(nouv)})


class _Pont(QObject):
    """Rapporte au fil de l'interface les constats lus en arrière-plan (fil de travail)."""
    arrive = pyqtSignal(object)


class SecuritePlugin(Plugin):
    api = 1

    def activer(self, ctx):
        self.ctx = ctx
        self.vue = None
        self.fond = bool(ctx.reglages.get("fond", False))
        self._pool = None
        ctx.ajouter_doc(_("Extension Sécurité"), DOC)
        if ctx.ui is not None:
            self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="securite-fond")
            self.pont = _Pont()
            self.pont.arrive.connect(self._recevoir)
            self.vue = VueSecurite(self)
            ctx.ui.enregistrer_type(logique.TYPE, self.vue)
            ctx.ui.planifier(INTERVALLE, self._tour, repeter=True)

    def desactiver(self):
        self.fond = False
        if self.vue is not None:
            self.vue._pool.shutdown(wait=False, cancel_futures=True)
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)

    def regler_fond(self, oui: bool):
        self.fond = bool(oui)
        self.ctx.reglages.set("fond", self.fond)

    # ---------- surveillance en arrière-plan ----------
    def reference(self):
        """Clés « normales » de cette machine d'après les fiches Sécurité VALIDÉES (réunies) ; None si aucune n'a de section pour elle."""
        machine, res = logique.nom_machine(), None
        for f in self.ctx.fiches():
            if f.texte is None or types_fiche.marque(f.texte) != logique.TYPE.nom or not self.ctx.fiche_active(f):
                continue
            cles = logique.lire(f.texte).get(machine)
            if cles is not None:
                res = (res or set()) | cles
        return res

    def _tour(self):
        if self.fond and self._pool is not None and self.reference() is not None:
            self._pool.submit(self._analyse_fond)

    def _analyse_fond(self):
        try:
            constats = logique.analyser_machine()
        except Exception:
            return
        try:
            self.pont.arrive.emit(constats)
        except RuntimeError:                                                  # extension désactivée entre-temps
            pass

    def _recevoir(self, constats: list):
        if self.fond:
            self.signaler(constats)

    def signaler(self, constats: list):
        """Notifie ce qui est nouveau et pas encore signalé (mémorisé : une seule fois par élément)."""
        ref = self.reference()
        deja = list(self.ctx.reglages.get("notifie", []) or [])
        neufs = [c for c in logique.nouveautes(constats, ref) if c.cle not in deja]
        if neufs:
            deja = (deja + [c.cle for c in neufs])[-500:]
            self.ctx.reglages.set("notifie", deja)
            suite = (_(" … et %d autre(s)") % (len(neufs) - 4)) if len(neufs) > 4 else ""
            self.ctx.ui.notifier(_("Sécurité"), _("Nouveau sur cette machine : ") + " ; ".join(f"{_(logique.CATEGORIES[c.categorie])} : {c.libelle}" for c in neufs[:4]) + suite)
        return neufs


DOC = _(
    "Y a-t-il quelqu'un dans ma machine, et qui ? Une fiche qui regarde ce qui est connecté et ce qui est ouvert.\n"
    "\n"
    "• Nouvelle fiche > « Sécurité » : l'analyse lit l'état de la machine (Linux, Windows ou macOS) : sessions ouvertes, connexions récentes depuis "
    "une autre adresse, ports ouverts sur le réseau, programmes d'accès à distance (SSH, TeamViewer, AnyDesk, VNC, Bureau à distance…), comptes, clés SSH autorisées et tâches planifiées.\n"
    "• Ce sont des commandes de lecture du système, sans shell et sans droits d'administrateur : rien n'est modifié ni envoyé.\n"
    "• Au premier essai, tout est « Nouveau » : regardez la liste, puis « Tout accepter comme normal ». L'état accepté est enregistré dans la fiche (une section par machine). "
    "Ensuite, ce qui est nouveau est signalé, « À vérifier » si c'est joignable depuis le réseau. Clic droit : « C'est normal » ou « Ce n'est plus normal ».\n"
    "• « Surveiller en arrière-plan » (décoché par défaut) : toutes les 10 minutes, une notification pour ce qui est nouveau, une seule fois par élément. Scrinium doit rester ouvert.\n"
    "• Type exécutable : une fiche reçue d'un autre ne lit rien tant que vous ne l'avez pas validée.\n"
    "• Limite : c'est une vue depuis la machine elle-même, pas un antivirus. Quelqu'un qui a déjà les droits d'administrateur peut cacher ses traces. "
    "Si quelque chose vous inquiète, déconnectez la machine du réseau et faites-vous aider.")

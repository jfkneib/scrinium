# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « Veille » : sources RSS / Atom, nouveautés non lues, pastille sur la fiche (voir `logique.py`).

Type exécutable (requêtes réseau) : une fiche reçue d'ailleurs ou modifiée hors de l'application reste inerte tant qu'elle n'est pas validée.
Résultats d'un fil de travail : ramenés au fil de l'interface par un signal (jamais d'objet Qt touché depuis un autre fil)."""
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import QObject, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu,
                             QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from scrinium.core import types_fiche
from scrinium.core.plugins import Plugin
from scrinium.i18n import _
from scrinium.ui.icons import icone
from scrinium.ui.markdown import ouvrir_url

from . import logique

INTERVALLE_FOND = 30 * 60                                 # secondes entre deux relèves en arrière-plan


class DialogueSource(QDialog):
    def __init__(self, s=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Source"))
        self.resize(480, 160)
        f = QFormLayout(self)
        self.nom = QLineEdit(s.nom if s else "")
        self.adresse = QLineEdit(s.adresse if s else "")
        self.adresse.setPlaceholderText("https://exemple.org/flux.xml")
        self.mot = QLineEdit(s.mot if s else "")
        self.mot.setPlaceholderText(_("facultatif : ne garder que les articles qui contiennent ce mot"))
        f.addRow(_("Nom :"), self.nom)
        f.addRow(_("Adresse du flux :"), self.adresse)
        f.addRow(_("Mot-clé :"), self.mot)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        b.accepted.connect(self._valider)
        b.rejected.connect(self.reject)
        f.addRow(b)

    def _valider(self):
        if logique.adresse_valide(self.adresse.text()):
            self.accept()
        else:
            self.adresse.setFocus()
            QMessageBox.warning(self, self.windowTitle(), _("L'adresse doit commencer par http:// ou https://."))

    def resultat(self):
        a = self.adresse.text().strip()
        return logique.Source(" ".join(self.nom.text().split())[:60] or a[:60], a, " ".join(self.mot.text().split())[:40])


class VueVeille(QWidget):
    modifie = pyqtSignal(str)
    _recu = pyqtSignal(int, int, object, str)                 # génération, indice de la source, articles, erreur (venus d'un fil de travail)

    def __init__(self, plugin=None, parent=None):
        super().__init__(parent)
        self.p = plugin
        self.doc = logique.Document()
        self.articles: list = []
        self.affiches: list = []                                  # articles montrés dans le tableau (les lus sont masqués par défaut)
        self.erreurs: dict = {}
        self._actif = True
        self._gen = 0
        self._attendus = 0
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="veille")
        self._recu.connect(self._arrive)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        haut = QHBoxLayout()
        self.b_actualiser = QPushButton(icone("view-refresh"), _("Actualiser"))
        self.b_actualiser.clicked.connect(self.actualiser)
        self.b_lus = QPushButton(icone("mail-mark-read"), _("Tout marquer comme lu"))
        self.b_lus.clicked.connect(self._tout_lire)
        self.b_ajouter = QPushButton(icone("list-add"), _("Ajouter une source…"))
        self.b_ajouter.clicked.connect(self._ajouter)
        self.c_lus = QCheckBox(_("Afficher les lus"))
        self.c_lus.setToolTip(_("Par défaut, un article lu disparaît de la liste."))
        self.c_lus.toggled.connect(lambda *_a: self._afficher())
        self.c_fond = QCheckBox(_("Surveiller en arrière-plan"))
        self.c_fond.setToolTip(_("Relève les fiches Veille validées toutes les 30 minutes, même quand elles ne sont pas affichées, et notifie les "
                                 "nouveautés. Scrinium doit rester ouvert."))
        self.c_fond.setChecked(bool(plugin is not None and plugin.fond))
        self.c_fond.toggled.connect(lambda oui: plugin.regler_fond(oui) if plugin is not None else None)
        for w in (self.b_actualiser, self.b_lus, self.b_ajouter, self.c_lus, self.c_fond):
            haut.addWidget(w)
        self.l_etat = QLabel()
        haut.addWidget(self.l_etat, 1)
        lay.addLayout(haut)
        self.t_sources = QTableWidget(0, 3)
        self.t_sources.setHorizontalHeaderLabels([_("Source"), _("Adresse du flux"), _("Mot-clé")])
        self.t_sources.verticalHeader().setVisible(False)
        self.t_sources.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.t_sources.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.t_sources.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.t_sources.setMaximumHeight(130)
        self.t_sources.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.t_sources.customContextMenuRequested.connect(self._menu_source)
        self.t_sources.doubleClicked.connect(lambda i: self._modifier(i.row()))
        lay.addWidget(self.t_sources)
        self.t_articles = QTableWidget(0, 3)
        self.t_articles.setHorizontalHeaderLabels([_("Source"), _("Titre"), _("Date")])
        self.t_articles.verticalHeader().setVisible(False)
        self.t_articles.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.t_articles.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.t_articles.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.t_articles.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.t_articles.customContextMenuRequested.connect(self._menu_article)
        self.t_articles.doubleClicked.connect(lambda i: self._ouvrir(i.row()))
        lay.addWidget(self.t_articles, 1)
        self.aide = QLabel()
        self.aide.setWordWrap(True)
        lay.addWidget(self.aide)
        self.actif = True

    @property
    def actif(self) -> bool:
        return self._actif

    @actif.setter
    def actif(self, oui: bool) -> None:
        self._actif = bool(oui)
        self.b_actualiser.setEnabled(self._actif)
        self.aide.setText(_("Double-clic sur un article : l'ouvrir dans le navigateur (il est alors marqué lu). Clic droit sur une source : modifier ou retirer.")
                          if self._actif else _("Fiche non validée : relisez les sources, puis validez-la pour lancer la relève et la modifier."))

    def fermer(self):
        self._pool.shutdown(wait=False, cancel_futures=True)

    # ---------- données ----------
    def charger(self, texte: str):
        self.doc = logique.lire(texte)
        self.articles, self.erreurs = [], {}
        self._gen += 1
        self._afficher()
        if self._actif and self.isVisible():
            self.actualiser()

    def showEvent(self, ev):
        super().showEvent(ev)
        if self._actif and self.doc.sources and not self.articles and not self._attendus:
            QTimer.singleShot(0, self.actualiser)

    def _enregistrer(self):
        self.modifie.emit(logique.ecrire(self.doc))
        self._afficher()

    def _ajouter(self):
        d = DialogueSource(None, self)
        if d.exec() and len(self.doc.sources) < logique.MAX_SOURCES:
            self.doc.sources.append(d.resultat())
            self._enregistrer()
            self.actualiser()

    def _modifier(self, i: int):
        if 0 <= i < len(self.doc.sources):
            d = DialogueSource(self.doc.sources[i], self)
            if d.exec():
                self.doc.sources[i] = d.resultat()
                self._enregistrer()
                self.actualiser()

    def _retirer(self, i: int):
        if 0 <= i < len(self.doc.sources):
            del self.doc.sources[i]
            self._enregistrer()
            self.actualiser()

    def _menu_source(self, pos):
        i = self.t_sources.rowAt(pos.y())
        m = QMenu(self)
        m.addAction(icone("list-add"), _("Ajouter une source…"), self._ajouter)
        if i >= 0:
            m.addAction(icone("document-edit"), _("Modifier…"), lambda: self._modifier(i))
            m.addAction(icone("edit-delete"), _("Retirer"), lambda: self._retirer(i))
        m.exec(self.t_sources.viewport().mapToGlobal(pos))

    def _menu_article(self, pos):
        i = self.t_articles.rowAt(pos.y())
        if i < 0:
            return
        m = QMenu(self)
        m.addAction(icone("internet-web-browser"), _("Ouvrir"), lambda: self._ouvrir(i))
        m.addAction(icone("mail-mark-read"), _("Marquer comme lu"), lambda: self._lire_article(i))
        m.exec(self.t_articles.viewport().mapToGlobal(pos))

    def _ouvrir(self, i: int):
        if 0 <= i < len(self.affiches):
            a = self.affiches[i]
            if logique.adresse_valide(a.lien):                  # http et https seulement, et seulement sur clic
                ouvrir_url(QUrl(a.lien), self.p.navigateur() if self.p is not None else "")
            self._lire_article(i)

    def _lire_article(self, i: int):
        if 0 <= i < len(self.affiches) and self._actif:
            logique.marquer_lus(self.doc, [self.affiches[i]])
            self._enregistrer()

    def _tout_lire(self):
        if self._actif:
            logique.marquer_lus(self.doc, self.articles)
            self._enregistrer()

    # ---------- relève ----------
    def actualiser(self):
        """Relève toutes les sources (en arrière-plan). Sans effet pour une fiche non validée."""
        if not self._actif or not self.doc.sources:
            return
        self._gen += 1
        gen = self._gen
        self.articles, self.erreurs = [], {}
        self._attendus = len(self.doc.sources)
        self.l_etat.setText(_("Relève en cours…"))
        for i, s in enumerate(self.doc.sources):
            self._pool.submit(self._travail, gen, i, logique.Source(s.nom, s.adresse, s.mot))

    def _travail(self, gen: int, i: int, s):
        try:
            articles, erreur = logique.recuperer(s)
        except Exception as ex:
            articles, erreur = [], str(ex)[:120]
        try:
            self._recu.emit(gen, i, articles, erreur)
        except RuntimeError:                                  # la vue a été détruite entre-temps
            pass

    def _arrive(self, gen: int, i: int, articles: list, erreur: str):
        if gen != self._gen:
            return
        self._attendus = max(0, self._attendus - 1)
        self.articles += articles
        if erreur and 0 <= i < len(self.doc.sources):
            self.erreurs[self.doc.sources[i].nom] = erreur
        if not self._attendus:
            self.articles.sort(key=lambda a: a.date, reverse=True)
            logique.NON_LUS[logique.cle_sources(self.doc)] = len(logique.non_lus(self.articles, self.doc))
            self._afficher()

    # ---------- affichage ----------
    def _afficher(self):
        d = self.doc
        self.t_sources.setRowCount(len(d.sources))
        for i, s in enumerate(d.sources):
            for c, v in enumerate((s.nom, s.adresse, s.mot)):
                self.t_sources.setItem(i, c, QTableWidgetItem(v))
        self.t_sources.resizeColumnsToContents()
        self.t_sources.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        lus = set(d.lus)
        self.affiches = [a for a in self.articles if self.c_lus.isChecked() or a.empreinte not in lus]
        self.t_articles.setRowCount(len(self.affiches))
        for i, a in enumerate(self.affiches):
            gras = a.empreinte not in lus
            for c, v in enumerate((a.source, a.titre, a.date)):
                it = QTableWidgetItem(v)
                if gras:
                    f = QFont(it.font())
                    f.setBold(True)
                    it.setFont(f)
                self.t_articles.setItem(i, c, it)
        self.t_articles.resizeColumnsToContents()
        self.t_articles.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        n = len(logique.non_lus(self.articles, d))
        if self.articles and not self._attendus:
            logique.NON_LUS[logique.cle_sources(d)] = n
        etat = (_("%d non lu(s) sur %d") % (n, len(self.articles)) if n else _("Tout est lu (%d article(s) masqué(s)).") % len(self.articles)) if self.articles else (_("Ajoutez une source (flux RSS ou Atom).") if not d.sources else "")
        if self.erreurs:
            etat += "  ·  " + _("injoignable : %s") % ", ".join(sorted(self.erreurs))
        if not self._attendus:
            self.l_etat.setText(etat)


class _Pont(QObject):
    arrive = pyqtSignal(str, object)                          # clé de la fiche (empreinte des sources), liste d'articles (arrière-plan)


class VeillePlugin(Plugin):
    api = 1

    def activer(self, ctx):
        self.ctx = ctx
        self.vue = None
        self.fond = bool(ctx.reglages.get("fond", False))
        self._en_cours: set = set()
        ctx.ajouter_doc(_("Extension Veille"), DOC)
        for theme, titre, texte in logique.exemples():
            ctx.ajouter_exemple(theme, titre, texte, "news-subscribe")
        if ctx.ui is not None:
            self.pont = _Pont()
            self.pont.arrive.connect(self._fond_arrive)
            self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="veille-fond")
            self.vue = VueVeille(self)
            ctx.ui.enregistrer_type(logique.TYPE, self.vue)
            ctx.ui.planifier(INTERVALLE_FOND, self._tour, repeter=True)

    def desactiver(self):
        self.fond = False
        if self.vue is not None:
            self.vue.fermer()
        if getattr(self, "_pool", None) is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)

    def navigateur(self) -> str:
        return ""

    def regler_fond(self, oui: bool):
        self.fond = bool(oui)
        self.ctx.reglages.set("fond", self.fond)

    def _fiches_a_relever(self) -> list:
        """Documents des fiches Veille VALIDÉES (une fiche inerte ou verrouillée fermée est ignorée), sans doublon."""
        vus, res = set(), []
        for f in self.ctx.fiches():
            if f.texte is None or types_fiche.marque(f.texte) != logique.TYPE.nom or not self.ctx.fiche_active(f):
                continue
            doc = logique.lire(f.texte)
            cle = logique.cle_sources(doc)
            if doc.sources and cle not in vus:
                vus.add(cle)
                res.append((cle, doc))
        return res

    def _tour(self):
        if not self.fond:
            return
        for cle, doc in self._fiches_a_relever():
            if cle not in self._en_cours:
                self._en_cours.add(cle)
                self._pool.submit(self._travail, cle, doc)

    def _travail(self, cle: str, doc):
        articles = []
        try:
            for s in doc.sources:
                articles += logique.recuperer(s)[0]
        except Exception:
            pass
        try:
            self.pont.arrive.emit(cle, (doc, articles))
        except RuntimeError:
            pass

    def _fond_arrive(self, cle: str, resultat):
        self._en_cours.discard(cle)
        doc, articles = resultat
        n = len(logique.non_lus(articles, doc))
        avant = logique.NON_LUS.get(cle, 0)
        logique.NON_LUS[cle] = n
        if n > avant:
            self.ctx.ui.notifier(_("Veille"), _("%d nouveauté(s) à lire") % n)


DOC = _(
    "Suivre des sites sans les ouvrir un par un : flux RSS ou Atom, avec un mot-clé facultatif.\n"
    "\n"
    "• Nouvelle fiche > « Veille » : « Ajouter une source… » (nom, adresse du flux commençant par http:// ou https://, mot-clé). Les articles s'affichent "
    "du plus récent au plus ancien, les non lus en gras. Double-clic : ouvrir l'article dans le navigateur (il est alors marqué lu) ; "
    "« Tout marquer comme lu » vide la liste des nouveautés.\n"
    "• Le mot-clé garde seulement les articles dont le titre ou le résumé le contient.\n"
    "• Une pastille rouge sur l'icône de la fiche signale les nouveautés non lues ; « Surveiller en arrière-plan » relève toutes les 30 minutes, même "
    "fiche fermée, et notifie. Scrinium doit rester ouvert.\n"
    "• Sûreté : la fiche est inerte tant que vous ne l'avez pas validée (elle fait des requêtes réseau). Seules les adresses http et https sont "
    "suivies, 10 secondes et 2 Mo au plus par flux, rien n'est téléchargé ni exécuté en dehors du flux ; un lien ne s'ouvre que sur un clic.\n"
    "• Ce qui est lu est mémorisé dans la fiche (empreintes courtes).")

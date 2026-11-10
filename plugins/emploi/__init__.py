# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « Emploi » : listes de mots-clés, annonces récentes à lien fort ou faible, suivi des candidatures, demande pour une IA (voir `logique.py`).

Type exécutable (requêtes réseau) : une fiche reçue d'ailleurs ou modifiée hors de l'application reste inerte tant qu'elle n'est pas validée.
Rien n'est envoyé ni postulé automatiquement. Résultats d'un fil de travail : ramenés au fil de l'interface par un signal."""
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import QObject, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QGuiApplication
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                             QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from scrinium.core import flux, types_fiche
from scrinium.core.plugins import Plugin
from scrinium.i18n import _
from scrinium.ui.icons import icone
from scrinium.ui.markdown import ouvrir_url

from . import logique

INTERVALLE_FOND = 30 * 60                                 # secondes entre deux relèves en arrière-plan
COULEURS = {"fort": "#bfe6c2", "faible": "#ffe2a8"}


def _item(texte: str, fond: str | None = None) -> QTableWidgetItem:
    it = QTableWidgetItem(texte)
    if fond:
        it.setBackground(QBrush(QColor(fond)))
        it.setForeground(QBrush(QColor("#1b1b1b")))
    return it


class DialogueDemande(QDialog):
    """La demande à donner à une IA : relisible, modifiable, copiée d'un clic. Elle ne part nulle part toute seule."""

    def __init__(self, texte: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Préparer ma candidature"))
        self.resize(720, 560)
        lay = QVBoxLayout(self)
        info = QLabel(_("Relisez et complétez ce texte, puis copiez-le dans l'assistant de votre choix (il ne part nulle part tout seul). "
                        "Relisez aussi ce que l'IA vous répond avant d'envoyer quoi que ce soit."))
        info.setWordWrap(True)
        lay.addWidget(info)
        self.texte = QPlainTextEdit(texte)
        lay.addWidget(self.texte, 1)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.b_copier = QPushButton(icone("edit-copy"), _("Copier la demande"))
        self.b_copier.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.texte.toPlainText()))
        b.addButton(self.b_copier, QDialogButtonBox.ButtonRole.ActionRole)
        b.rejected.connect(self.reject)
        lay.addWidget(b)


class DialogueSource(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Source d'annonces"))
        self.resize(480, 130)
        f = QFormLayout(self)
        self.nom = QLineEdit()
        self.adresse = QLineEdit()
        self.adresse.setPlaceholderText("https://exemple.org/offres.rss")
        f.addRow(_("Nom :"), self.nom)
        f.addRow(_("Adresse du flux :"), self.adresse)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        b.accepted.connect(self._valider)
        b.rejected.connect(self.reject)
        f.addRow(b)

    def _valider(self):
        if flux.adresse_valide(self.adresse.text()):
            self.accept()
        else:
            self.adresse.setFocus()
            QMessageBox.warning(self, self.windowTitle(), _("L'adresse doit commencer par http:// ou https://."))

    def resultat(self):
        a = self.adresse.text().strip()
        return logique.Source(" ".join(self.nom.text().split())[:60] or a[:60], a, True)


class VueEmploi(QWidget):
    modifie = pyqtSignal(str)
    _recu = pyqtSignal(int, int, object, str)                 # génération, indice de la source, annonces, erreur (venus d'un fil de travail)

    def __init__(self, plugin=None, parent=None):
        super().__init__(parent)
        self.pl = plugin
        self.p = logique.Profil()
        self.annonces: list = []
        self.affichees: list = []                             # [(annonce, lien)] montrées dans le tableau
        self.erreurs: dict = {}
        self._actif = True
        self._remplit = False
        self._gen = 0
        self._attendus = 0
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="emploi")
        self._recu.connect(self._arrive)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.onglets = QTabWidget()
        lay.addWidget(self.onglets, 1)
        self.onglets.addTab(self._onglet_annonces(), icone("view-list-details"), _("Annonces"))
        self.onglets.addTab(self._onglet_suivi(), icone("view-task"), _("Suivi"))
        self.onglets.addTab(self._onglet_recherche(), icone("configure"), _("Ma recherche"))
        self.aide = QLabel()
        self.aide.setWordWrap(True)
        lay.addWidget(self.aide)
        self.actif = True

    # ---------- onglets ----------
    def _onglet_annonces(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        haut = QHBoxLayout()
        self.b_actualiser = QPushButton(icone("view-refresh"), _("Actualiser"))
        self.b_actualiser.clicked.connect(self.actualiser)
        self.b_retenir = QPushButton(icone("bookmark-new"), _("Retenir"))
        self.b_retenir.clicked.connect(lambda: self._retenir(self.t_annonces.currentRow()))
        self.b_preparer = QPushButton(icone("document-edit"), _("Préparer ma candidature…"))
        self.b_preparer.clicked.connect(lambda: self._preparer(self.t_annonces.currentRow()))
        self.b_ecarter = QPushButton(icone("edit-delete"), _("Écarter"))
        self.b_ecarter.clicked.connect(lambda: self._ecarter(self.t_annonces.currentRow()))
        self.c_faibles = QCheckBox(_("Montrer les liens faibles"))
        self.c_faibles.setChecked(True)
        self.c_faibles.toggled.connect(lambda *_a: self._afficher())
        self.c_fond = QCheckBox(_("Surveiller en arrière-plan"))
        self.c_fond.setToolTip(_("Relève les fiches Emploi validées toutes les 30 minutes, même quand elles ne sont pas affichées, et notifie les "
                                 "nouvelles annonces à lien fort. Scrinium doit rester ouvert."))
        self.c_fond.setChecked(bool(self.pl is not None and self.pl.fond))
        self.c_fond.toggled.connect(lambda oui: self.pl.regler_fond(oui) if self.pl is not None else None)
        for x in (self.b_actualiser, self.b_retenir, self.b_preparer, self.b_ecarter, self.c_faibles, self.c_fond):
            haut.addWidget(x)
        haut.addStretch(1)
        lay.addLayout(haut)
        self.l_etat = QLabel()
        self.l_etat.setWordWrap(True)
        lay.addWidget(self.l_etat)
        self.t_annonces = QTableWidget(0, 6)
        self.t_annonces.setHorizontalHeaderLabels([_("Lien"), _("Annonce"), _("Source"), _("Date"), _("Mots trouvés"), _("Indispensables manquants")])
        self.t_annonces.verticalHeader().setVisible(False)
        self.t_annonces.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.t_annonces.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.t_annonces.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.t_annonces.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.t_annonces.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.t_annonces.customContextMenuRequested.connect(self._menu_annonce)
        self.t_annonces.doubleClicked.connect(lambda i: self._ouvrir(i.row()))
        lay.addWidget(self.t_annonces, 1)
        return w

    def _onglet_suivi(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.l_suivi = QLabel()
        self.l_suivi.setWordWrap(True)
        self.l_suivi.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.l_suivi)
        self.t_suivi = QTableWidget(0, 4)
        self.t_suivi.setHorizontalHeaderLabels([_("Statut"), _("Annonce"), _("Depuis le"), _("Note")])
        self.t_suivi.verticalHeader().setVisible(False)
        self.t_suivi.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.t_suivi.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.t_suivi.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.t_suivi.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.t_suivi.customContextMenuRequested.connect(self._menu_suivi)
        self.t_suivi.doubleClicked.connect(lambda i: self._ouvrir_suivi(i.row()))
        lay.addWidget(self.t_suivi, 1)
        return w

    def _onglet_recherche(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        f = QFormLayout()
        self.e_ind = QLineEdit()
        self.e_ind.setPlaceholderText(_("python, linux, admin système | sysadmin"))
        self.e_ind.setToolTip(_("Tous ces mots doivent figurer dans l'annonce pour un lien FORT. Variantes : « admin système | sysadmin »."))
        self.e_sou = QLineEdit()
        self.e_sou.setPlaceholderText(_("xmpp, télétravail"))
        self.e_sou.setToolTip(_("Ces mots améliorent le classement ; sans mot indispensable, deux d'entre eux donnent un lien fort."))
        self.e_exc = QLineEdit()
        self.e_exc.setPlaceholderText(_("stage, alternance"))
        self.e_exc.setToolTip(_("Une annonce qui contient l'un de ces mots est écartée."))
        self.s_jours = QSpinBox()
        self.s_jours.setRange(1, 90)
        self.s_jours.setSuffix(_(" jours"))
        f.addRow(_("Mots indispensables :"), self.e_ind)
        f.addRow(_("Mots souhaités :"), self.e_sou)
        f.addRow(_("Mots à exclure :"), self.e_exc)
        f.addRow(_("Annonces de moins de :"), self.s_jours)
        lay.addLayout(f)
        lay.addWidget(QLabel("<b>%s</b>" % _("Mon profil (sert à préparer la demande pour l'IA ; données personnelles : verrouillez la fiche)")))
        self.e_profil = QPlainTextEdit()
        self.e_profil.setPlaceholderText(_("Mon parcours, mes compétences, ce que je cherche…"))
        self.e_profil.setMaximumHeight(140)
        lay.addWidget(self.e_profil)
        ligne = QHBoxLayout()
        ligne.addWidget(QLabel("<b>%s</b>" % _("Sources d'annonces (flux RSS ou Atom)")), 1)
        b = QPushButton(icone("list-add"), _("Ajouter une source…"))
        b.clicked.connect(self._ajouter_source)
        ligne.addWidget(b)
        lay.addLayout(ligne)
        self.t_sources = QTableWidget(0, 3)
        self.t_sources.setHorizontalHeaderLabels([_("Afficher"), _("Source"), _("Adresse du flux")])
        self.t_sources.verticalHeader().setVisible(False)
        self.t_sources.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.t_sources.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.t_sources.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.t_sources.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.t_sources.customContextMenuRequested.connect(self._menu_source)
        self.t_sources.itemChanged.connect(self._case_source)
        lay.addWidget(self.t_sources, 1)
        for e in (self.e_ind, self.e_sou, self.e_exc):
            e.textChanged.connect(self._champs_changes)
        self.s_jours.valueChanged.connect(self._champs_changes)
        self.e_profil.textChanged.connect(self._champs_changes)
        return w

    @property
    def actif(self) -> bool:
        return self._actif

    @actif.setter
    def actif(self, oui: bool) -> None:
        self._actif = bool(oui)
        self.b_actualiser.setEnabled(self._actif)
        self.aide.setText(_("Double-clic sur une annonce : l'ouvrir dans le navigateur. « Retenir » la met dans votre suivi ; « Préparer ma candidature » compose le texte à donner à une IA. "
                            "Rien n'est envoyé ni postulé automatiquement.") if self._actif else
                          _("Fiche non validée : relisez les sources, puis validez-la pour lancer la relève et la modifier."))

    def fermer(self):
        self._pool.shutdown(wait=False, cancel_futures=True)

    # ---------- données ----------
    def charger(self, texte: str):
        self.p = logique.lire(texte)
        self._remplit = True
        try:
            self.e_ind.setText(", ".join(self.p.indispensables))
            self.e_sou.setText(", ".join(self.p.souhaites))
            self.e_exc.setText(", ".join(self.p.exclus))
            self.s_jours.setValue(self.p.jours)
            self.e_profil.setPlainText(self.p.profil)
        finally:
            self._remplit = False
        self.annonces, self.erreurs = [], {}
        self._gen += 1
        self._afficher()
        if self._actif and self.isVisible():
            self.actualiser()

    def showEvent(self, ev):
        super().showEvent(ev)
        if self._actif and self.p.sources and not self.annonces and not self._attendus:
            QTimer.singleShot(0, self.actualiser)

    def _enregistrer(self):
        self.modifie.emit(logique.ecrire(self.p))
        self._afficher()

    def _champs_changes(self, *_a):
        if self._remplit:
            return
        self.p.indispensables = logique.lire_mots(self.e_ind.text())
        self.p.souhaites = logique.lire_mots(self.e_sou.text())
        self.p.exclus = logique.lire_mots(self.e_exc.text())
        self.p.jours = self.s_jours.value()
        self.p.profil = self.e_profil.toPlainText()[:logique.MAX_PROFIL]
        self.modifie.emit(logique.ecrire(self.p))
        self._afficher_annonces()

    # ---------- sources ----------
    def _ajouter_source(self):
        d = DialogueSource(self)
        if d.exec() and len(self.p.sources) < logique.MAX_SOURCES:
            self.p.sources.append(d.resultat())
            self._enregistrer()
            if self._actif:
                self.actualiser()

    def _retirer_source(self, i: int):
        if 0 <= i < len(self.p.sources):
            del self.p.sources[i]
            self._enregistrer()

    def _menu_source(self, pos):
        i = self.t_sources.rowAt(pos.y())
        m = QMenu(self)
        m.addAction(icone("list-add"), _("Ajouter une source…"), self._ajouter_source)
        if i >= 0:
            m.addAction(icone("edit-delete"), _("Retirer"), lambda: self._retirer_source(i))
        m.exec(self.t_sources.viewport().mapToGlobal(pos))

    def _case_source(self, it):
        ligne = it.row()
        if self._remplit or it.column() != 0 or not self._actif or not (0 <= ligne < len(self.p.sources)):
            return
        oui = it.checkState() == Qt.CheckState.Checked
        s = self.p.sources[ligne]
        if oui != s.afficher:
            s.afficher = oui
            self._enregistrer()
            if oui and not any(a.source == s.nom for a in self.annonces):
                self._attendus += 1
                self.l_etat.setText(_("Relève en cours…"))
                self._demander(ligne)

    # ---------- annonces ----------
    def _selection(self, i: int):
        return self.affichees[i] if 0 <= i < len(self.affichees) else None

    def _ouvrir(self, i: int):
        x = self._selection(i)
        if x and flux.adresse_valide(x[0].lien):                  # http et https seulement, et seulement sur clic
            ouvrir_url(QUrl(x[0].lien), "")

    def _retenir(self, i: int):
        x = self._selection(i)
        if x and self._actif:
            if logique.retenir(self.p, x[0]):
                self._enregistrer()
                self.l_etat.setText(_("Retenue : « %s » est dans l'onglet Suivi.") % x[0].titre)

    def _ecarter(self, i: int):
        x = self._selection(i)
        if x and self._actif:
            logique.vue(self.p, x[0])
            self._enregistrer()

    def _preparer(self, i: int):
        x = self._selection(i)
        if x:
            DialogueDemande(logique.demande_ia(self.p, x[0], x[1]), self).exec()

    def _menu_annonce(self, pos):
        i = self.t_annonces.rowAt(pos.y())
        if i < 0 or not self._selection(i):
            return
        m = QMenu(self)
        m.addAction(icone("internet-web-browser"), _("Ouvrir"), lambda: self._ouvrir(i))
        m.addAction(icone("bookmark-new"), _("Retenir"), lambda: self._retenir(i))
        m.addAction(icone("document-edit"), _("Préparer ma candidature…"), lambda: self._preparer(i))
        m.addAction(icone("edit-delete"), _("Écarter"), lambda: self._ecarter(i))
        m.exec(self.t_annonces.viewport().mapToGlobal(pos))

    # ---------- suivi ----------
    def _menu_suivi(self, pos):
        i = self.t_suivi.rowAt(pos.y())
        if not (0 <= i < len(self.p.suivi)):
            return
        m = QMenu(self)
        m.addAction(icone("internet-web-browser"), _("Ouvrir l'annonce"), lambda: self._ouvrir_suivi(i))
        sous = m.addMenu(icone("view-task"), _("Changer le statut"))
        for st in logique.STATUTS:
            sous.addAction(_(logique.LIBELLES_STATUTS[st]), lambda st=st: self._statut(i, st))
        m.addAction(icone("document-edit"), _("Modifier la note…"), lambda: self._note(i))
        m.addAction(icone("edit-delete"), _("Retirer du suivi"), lambda: self._retirer_suivi(i))
        m.exec(self.t_suivi.viewport().mapToGlobal(pos))

    def _ouvrir_suivi(self, i: int):
        if 0 <= i < len(self.p.suivi) and flux.adresse_valide(self.p.suivi[i].lien):
            ouvrir_url(QUrl(self.p.suivi[i].lien), "")

    def _statut(self, i: int, statut: str):
        if 0 <= i < len(self.p.suivi) and self._actif:
            logique.changer_statut(self.p.suivi[i], statut)
            self._enregistrer()

    def _note(self, i: int):
        if 0 <= i < len(self.p.suivi) and self._actif:
            t, ok = QInputDialog.getText(self, _("Note"), _("Note :"), text=self.p.suivi[i].note)
            if ok:
                self.p.suivi[i].note = " ".join(t.split())[:200]
                self._enregistrer()

    def _retirer_suivi(self, i: int):
        if 0 <= i < len(self.p.suivi) and self._actif:
            del self.p.suivi[i]
            self._enregistrer()

    # ---------- relève ----------
    def actualiser(self):
        """Relève les sources cochées (en arrière-plan). Sans effet pour une fiche non validée."""
        if not self._actif or not self.p.sources:
            return
        self._gen += 1
        self.annonces, self.erreurs = [], {}
        cochees = [i for i, s in enumerate(self.p.sources) if s.afficher]
        self._attendus = len(cochees)
        self.l_etat.setText(_("Relève en cours…") if cochees else "")
        for i in cochees:
            self._demander(i)
        if not cochees:
            self._afficher()

    def _demander(self, i: int):
        s = self.p.sources[i]
        self._pool.submit(self._travail, self._gen, i, logique.Source(s.nom, s.adresse, s.afficher))

    def _travail(self, gen: int, i: int, s):
        try:
            annonces, erreur = logique.recuperer(s)
        except Exception as ex:
            annonces, erreur = [], str(ex)[:120]
        try:
            self._recu.emit(gen, i, annonces, erreur)
        except RuntimeError:                                      # la vue a été détruite entre-temps
            pass

    def _arrive(self, gen: int, i: int, annonces: list, erreur: str):
        if gen != self._gen:
            return
        self._attendus = max(0, self._attendus - 1)
        connues = {a.empreinte for a in self.annonces}
        self.annonces += [a for a in annonces if a.empreinte not in connues]
        if erreur and 0 <= i < len(self.p.sources):
            self.erreurs[self.p.sources[i].nom] = erreur
        if not self._attendus:
            logique.NOUVELLES[logique.cle_recherche(self.p)] = sum(1 for _a, lien in logique.proposees(self.annonces, self.p, faibles=False) if lien.niveau == "fort")
            self._afficher()

    # ---------- affichage ----------
    def _afficher(self):
        self._remplit = True
        try:
            self.t_sources.setRowCount(len(self.p.sources))
            for i, s in enumerate(self.p.sources):
                case = QTableWidgetItem()
                case.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                case.setCheckState(Qt.CheckState.Checked if s.afficher else Qt.CheckState.Unchecked)
                self.t_sources.setItem(i, 0, case)
                self.t_sources.setItem(i, 1, QTableWidgetItem(s.nom))
                self.t_sources.setItem(i, 2, QTableWidgetItem(s.adresse))
            self.t_sources.resizeColumnsToContents()
            self.t_sources.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
            self._afficher_suivi()
        finally:
            self._remplit = False
        self._afficher_annonces()

    def _afficher_suivi(self):
        self.t_suivi.setRowCount(len(self.p.suivi))
        for i, s in enumerate(self.p.suivi):
            fond = {"entretien": "#bfe6c2", "postulée": "#cfe3ff", "relancée": "#cfe3ff", "refus": "#e0e0e0", "abandon": "#e0e0e0"}.get(s.statut)
            self.t_suivi.setItem(i, 0, _item(_(logique.LIBELLES_STATUTS[s.statut]), fond))
            self.t_suivi.setItem(i, 1, _item(s.titre))
            self.t_suivi.setItem(i, 2, _item(s.date))
            self.t_suivi.setItem(i, 3, _item(s.note))
        self.t_suivi.resizeColumnsToContents()
        self.t_suivi.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        r = logique.relances(self.p)
        self.l_suivi.setText(("<span style='color:#c0392b'><b>%s</b></span>" % (_("%d candidature(s) à relancer (sans nouvelle depuis %d jours).") % (len(r), logique.RELANCE_APRES)))
                             if r else (_("Clic droit sur une ligne : changer le statut, noter, ouvrir l'annonce.") if self.p.suivi else
                                        _("Rien ici pour l'instant : « Retenir » une annonce pour la suivre.")))

    def _afficher_annonces(self):
        self.affichees = logique.proposees(self.annonces, self.p, self.c_faibles.isChecked())
        self.t_annonces.setRowCount(len(self.affichees))
        for i, (a, lien) in enumerate(self.affichees):
            fond = COULEURS[lien.niveau]
            self.t_annonces.setItem(i, 0, _item(("● " + _("fort")) if lien.niveau == "fort" else ("◐ " + _("faible")), fond))
            self.t_annonces.setItem(i, 1, _item(a.titre))
            self.t_annonces.setItem(i, 2, _item(a.source))
            self.t_annonces.setItem(i, 3, _item(a.date[:10]))
            self.t_annonces.setItem(i, 4, _item(", ".join(lien.trouves)))
            self.t_annonces.setItem(i, 5, _item(", ".join(lien.manquants)))
            self.t_annonces.item(i, 1).setToolTip(a.resume[:600])
        self.t_annonces.resizeColumnsToContents()
        self.t_annonces.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        fortes = sum(1 for _a, lien in self.affichees if lien.niveau == "fort")
        if self.annonces:
            etat = _("%(f)d à lien fort, %(w)d à lien faible, sur %(n)d annonce(s) récentes relevées.") % {"f": fortes, "w": len(self.affichees) - fortes, "n": len(logique.recentes(self.annonces, self.p.jours))}
        elif not self.p.sources:
            etat = _("Ajoutez une source d'annonces (onglet « Ma recherche ») et vos mots-clés.")
        elif not (self.p.indispensables or self.p.souhaites):
            etat = _("Indiquez des mots-clés dans l'onglet « Ma recherche » : sans eux, aucune annonce n'est proposée.")
        else:
            etat = ""
        if self.erreurs:
            etat += "  ·  " + _("injoignable : %s") % ", ".join(sorted(self.erreurs))
        if not self._attendus:
            self.l_etat.setText(etat)


class _Pont(QObject):
    arrive = pyqtSignal(str, object)                          # clé de la recherche, (profil, annonces) (arrière-plan)


class EmploiPlugin(Plugin):
    api = 1

    def activer(self, ctx):
        self.ctx = ctx
        self.vue = None
        self.fond = bool(ctx.reglages.get("fond", False))
        self._en_cours: set = set()
        ctx.ajouter_doc(_("Extension Emploi"), DOC)
        for theme, titre, texte in logique.exemples():
            ctx.ajouter_exemple(theme, titre, texte, "user-identity")
        if ctx.ui is not None:
            self.pont = _Pont()
            self.pont.arrive.connect(self._fond_arrive)
            self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="emploi-fond")
            self.vue = VueEmploi(self)
            ctx.ui.enregistrer_type(logique.TYPE, self.vue)
            ctx.ui.planifier(INTERVALLE_FOND, self._tour, repeter=True)

    def desactiver(self):
        self.fond = False
        if self.vue is not None:
            self.vue.fermer()
        if getattr(self, "_pool", None) is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)

    def regler_fond(self, oui: bool):
        self.fond = bool(oui)
        self.ctx.reglages.set("fond", self.fond)

    def _fiches_a_relever(self) -> list:
        """Profils des fiches Emploi VALIDÉES (une fiche inerte ou verrouillée fermée est ignorée), sans doublon."""
        vus, res = set(), []
        for f in self.ctx.fiches():
            if f.texte is None or types_fiche.marque(f.texte) != logique.TYPE.nom or not self.ctx.fiche_active(f):
                continue
            p = logique.lire(f.texte)
            cle = logique.cle_recherche(p)
            if any(s.afficher for s in p.sources) and cle not in vus:
                vus.add(cle)
                res.append((cle, p))
        return res

    def _tour(self):
        if not self.fond:
            return
        for cle, p in self._fiches_a_relever():
            if cle not in self._en_cours:
                self._en_cours.add(cle)
                self._pool.submit(self._travail, cle, p)

    def _travail(self, cle: str, p):
        annonces, vus = [], set()
        try:
            for s in p.sources:
                if s.afficher:
                    for a in logique.recuperer(s)[0]:
                        if a.empreinte not in vus:
                            vus.add(a.empreinte)
                            annonces.append(a)
        except Exception:
            pass
        try:
            self.pont.arrive.emit(cle, (p, annonces))
        except RuntimeError:
            pass

    def _fond_arrive(self, cle: str, resultat):
        self._en_cours.discard(cle)
        p, annonces = resultat
        n = sum(1 for _a, lien in logique.proposees(annonces, p, faibles=False) if lien.niveau == "fort")
        avant = logique.NOUVELLES.get(cle, 0)
        logique.NOUVELLES[cle] = n
        if n > avant:
            self.ctx.ui.notifier(_("Emploi"), _("%d nouvelle(s) annonce(s) à lien fort") % n)


DOC = _(
    "Une aide pour qui cherche un emploi : Scrinium relève des annonces récentes, les compare à vos mots-clés et vous dit si le lien est FORT ou FAIBLE.\n"
    "\n"
    "• Nouvelle fiche > « Recherche d'emploi », onglet « Ma recherche » : écrivez vos listes de mots-clés séparés par des virgules. Mots INDISPENSABLES : tous doivent "
    "figurer dans l'annonce pour un lien fort. Mots SOUHAITÉS : ils améliorent le classement (sans mot indispensable, deux mots souhaités donnent un lien fort). "
    "Mots à EXCLURE : une annonce qui en contient un est écartée. Variantes d'un même mot avec « | » (« admin système | sysadmin »). Les majuscules et les accents ne comptent pas. "
    "Réglez aussi l'âge maximal des annonces (14 jours par défaut) et ajoutez votre profil.\n"
    "• Sources : des flux RSS ou Atom d'offres (sites carrière d'entreprises, sites d'offres qui en publient, alertes e-mail converties en flux). "
    "France Travail et l'Apec n'ont pas de flux : pour eux, voir la suite (une source API est prévue). Décochez « Afficher » pour mettre une source de côté sans la supprimer.\n"
    "• Onglet « Annonces » : ● fort (vert) et ◐ faible (orange), les plus fortes d'abord puis les plus récentes, avec les mots trouvés et les indispensables manquants. "
    "« Retenir » met l'annonce dans l'onglet « Suivi » ; « Écarter » la fait disparaître ; « Préparer ma candidature » compose un texte (votre profil, l'annonce, les "
    "mots trouvés et manquants, des consignes) à relire et à copier dans l'assistant de votre choix. Rien n'est envoyé ni postulé automatiquement.\n"
    "• Onglet « Suivi » : statut de chaque candidature (retenue, postulée, relancée, entretien, refus, abandon). Une candidature sans nouvelle depuis 7 jours est signalée à relancer.\n"
    "• Une pastille rouge sur l'icône de la fiche signale de nouvelles annonces à lien fort et les relances ; « Surveiller en arrière-plan » relève toutes les 30 minutes et notifie.\n"
    "• Sûreté : la fiche est inerte tant que vous ne l'avez pas validée (elle fait des requêtes réseau) ; seules les adresses http et https sont suivies ; un lien ne s'ouvre que sur un clic. "
    "Votre profil est une donnée personnelle : verrouillez la fiche (bouton « Verrouiller… »).")

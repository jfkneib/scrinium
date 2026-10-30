# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Fenêtre principale (PyQt6)."""
import time
from pathlib import Path

from PyQt6.QtCore import QEvent, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QKeySequence
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPushButton, QSplitter,
                             QStackedWidget, QSystemTrayIcon, QToolBar, QVBoxLayout, QWidget)

from .. import __version__
from ..core import autostart, capture, crypto, invitation
from ..core.plugins import FicheVue, Gestionnaire
from ..core import doc_extensions, lien as lien_mod, repertoire
from ..core.store import ICONE_DEFAUT, Store, propre
from ..i18n import _
from .assistant import AssistantCle
from .capture_rapide import THEME_DEFAUT, CaptureRapide
from .extensions import DialogueExtensions, UiPlugin
from . import export_pdf
from .choix_icone import DialogueIcone
from .icons import avec_epingle, icone, icone_appli
from .images import BandePieces, Editeur
from .markdown import Apercu, BarreFormat, entourer, navigateurs_installes
from .lien_ajout import DialogueAjoutLien
from .repertoire import VueRepertoire

ORANGE, VERT, GRIS = "#c77700", "#2e8b3a", "gray"


class ListeOrdonnable(QListWidget):
    """Liste dont on change l'ordre par glisser-déposer. Les signaux de sélection sont coupés pendant le déplacement (la fiche
    affichée ne doit pas changer) ; `reordonnee` dit à la fenêtre de relire l'ordre des éléments (donnée `Qt.UserRole`)."""
    reordonnee = pyqtSignal()

    def dropEvent(self, ev):
        self.blockSignals(True)
        try:
            super().dropEvent(ev)
        finally:
            self.blockSignals(False)
        QTimer.singleShot(0, self.reordonnee.emit)            # une fois le glisser-déposer terminé (la liste est alors définitive)

    def cles(self) -> list:
        return [self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count())]


class Fenetre(QMainWindow):
    def __init__(self, store: Store, theme: str | None = None, nouvelle: bool = False):
        super().__init__()
        self.store = store
        self.TOUS = _("★ Toutes les fiches")
        self.theme = self.TOUS
        self.fiche = None          # fiche en cours d'édition
        self.fiche_theme = None    # son thème
        self.chargement = False
        self.rows: list = []       # ligne de la liste des fiches -> (thème, fiche)
        self.quitter_vraiment = False
        self.tray = None
        self.timer = QTimer(self, singleShot=True, interval=700)
        self.timer.timeout.connect(self.sauver)
        self.setWindowTitle(_("Scrinium"))
        self.setWindowIcon(icone_appli())
        self.resize(900, 540)
        store.charger()
        self.actions_image: list = []         # (extension, texte, fn, icône) : clic droit sur une image jointe (voir UiPlugin)
        self._ui()
        self._zone_notification()
        self.plugins = Gestionnaire(store, ui_factory=lambda info: UiPlugin(self, info.nom),
                                    fiche_courante=lambda: self._vue(self.fiche_theme, self.fiche),
                                    sur_desactivation_auto=self._plugin_coupe)
        if not theme and store.premier_lancement:
            theme = _("Bienvenue")   # première ouverture : on commence par les fiches d'aide
        if theme:
            self.theme = next((t.nom for t in store.themes if t.nom.lower() == theme.lower()), self.TOUS)
        self.maj_themes()
        self.maj_fiches()
        if nouvelle:
            self.nouvelle_fiche()
        QTimer.singleShot(0, self.plugins.demarrer)

    # ---------- construction ----------
    def _action(self, texte, ic, slot, raccourci=None):
        a = QAction(icone(ic), texte, self)
        a.triggered.connect(lambda *_: slot())
        if raccourci:
            a.setShortcut(QKeySequence(raccourci))
        return a

    def _ui(self):
        tb = self.barre = QToolBar(_("Actions"))
        tb.setMovable(False)
        tb.setIconSize(QSize(22, 22))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(tb)
        self.a_fiche = self._action(_("Fiche"), "document-new", self.nouvelle_fiche, "Ctrl+N")
        self.a_fiche.setToolTip(_("Nouvelle fiche (Ctrl+N)"))
        self.a_theme = self._action(_("Thème"), "folder-new", self.nouveau_theme, "Ctrl+Shift+N")
        self.a_theme.setToolTip(_("Nouveau thème (Ctrl+Maj+N)"))
        tb.addAction(self.a_theme)          # même ordre que les colonnes : thèmes à gauche, fiches ensuite
        tb.addAction(self.a_fiche)
        self.recherche = QLineEdit()
        self.recherche.setPlaceholderText(_("Chercher (Ctrl+F)…"))
        self.recherche.setClearButtonEnabled(True)
        self.recherche.addAction(icone("edit-find"), QLineEdit.ActionPosition.LeadingPosition)
        self.recherche.textChanged.connect(lambda *_: self.maj_fiches())
        tb.addWidget(self.recherche)

        m = self.menuBar()
        mf = m.addMenu(_("&Fichier"))
        mf.addAction(self.a_theme)
        mf.addAction(self.a_fiche)
        mf.addAction(self._action(_("Nouveau répertoire…"), "x-office-address-book", self.nouveau_repertoire, "Ctrl+Alt+R"))
        mf.addAction(self._action(_("Capture rapide…"), "document-edit", self.capture_rapide, "Ctrl+Alt+N"))
        mf.addAction(self._action(_("Inviter à installer Scrinium…"), "mail-send", self.inviter))
        mf.addSeparator()
        self.a_tray = QAction(_("Réduire dans la zone de notification"), self, checkable=True)
        self.a_tray.setChecked(bool(self.store.reglages().get("tray", True)))
        self.a_tray.toggled.connect(lambda on: self.store.sauver_reglages(tray=bool(on)))
        mf.addAction(self.a_tray)
        self.a_demarrage = QAction(_("Lancer au démarrage de la session"), self, checkable=True)
        self.a_demarrage.setChecked(autostart.actif())
        self.a_demarrage.toggled.connect(self._demarrage)
        mf.addAction(self.a_demarrage)
        mf.addAction(self._action(_("Navigateur pour les liens…"), "internet-web-browser", self.choisir_navigateur))
        mf.addSeparator()
        mf.addAction(self._action(_("Quitter"), "application-exit", self.quitter, "Ctrl+Q"))
        ms = m.addMenu(_("&Sécurité"))
        ms.addAction(self._action(_("Fichier de secours…"), "object-locked", self.assistant_cle))
        ms.addAction(self._action(_("Rouvrir une fiche avec le fichier de secours…"), "object-unlocked", self.secours))
        self.menu_ext = m.addMenu(_("E&xtensions"))
        self.menu_ext.addAction(self._action(_("Gérer les extensions…"), "preferences-plugin", self.gerer_extensions))
        self.menu_ext.addSeparator()
        mh = m.addMenu(_("&Aide"))
        ml = mh.addMenu(_("&Langue"))
        groupe = QActionGroup(self)
        actuelle = self.store.reglages().get("langue", "auto")
        for code, nom in (("auto", _("Automatique")), ("fr", "Français"), ("en", "English")):
            a = QAction(nom, self, checkable=True)
            a.setChecked(code == actuelle)
            a.triggered.connect(lambda _checked, c=code: self._langue(c))
            groupe.addAction(a)
            ml.addAction(a)
        mh.addAction(self._action(_("Documentation des extensions"), "preferences-plugin", self.doc_extensions))
        mh.addAction(self._action(_("À propos"), "help-about", self.a_propos))

        self.liste_themes = ListeOrdonnable()
        self.liste_themes.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.liste_themes.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.liste_themes.reordonnee.connect(self._ordre_themes_change)
        self.liste_themes.setIconSize(QSize(20, 20))
        self.liste_themes.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)   # Ctrl / Maj + clic
        self.liste_themes.currentRowChanged.connect(self._sel_theme)
        self.liste_themes.itemDoubleClicked.connect(lambda *_: self.renommer_theme())
        self._suppr(self.liste_themes, lambda: self.supprimer_theme())
        self._raccourcis_ordre(self.liste_themes)
        self.liste_themes.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.liste_themes.customContextMenuRequested.connect(self._menu_theme)
        bt = QHBoxLayout()
        self.b_pin_theme = QPushButton(avec_epingle(""), "")
        self.b_pin_theme.setCheckable(True)
        self.b_pin_theme.setToolTip(_("Épingler le thème (il reste en haut de la liste)"))
        self.b_pin_theme.clicked.connect(lambda *_: self.epingler_theme())
        bt.addWidget(self.b_pin_theme)
        for ic, tip, slot in (("edit-rename", _("Renommer le thème"), self.renommer_theme),
                              ("view-pim-notes", _("Icône du thème"), self.icone_theme),
                              ("edit-delete", _("Supprimer le thème"), self.supprimer_theme)):
            b = QPushButton(icone(ic), "")
            b.setToolTip(tip)
            b.clicked.connect(lambda *_, s=slot: s())
            bt.addWidget(b)
        gauche = QWidget()
        lg = QVBoxLayout(gauche)
        lg.setContentsMargins(0, 0, 0, 0)
        lg.addWidget(self.liste_themes)
        lg.addLayout(bt)

        self.liste = ListeOrdonnable()
        self.liste.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.liste.reordonnee.connect(self._ordre_fiches_change)
        self.liste.setIconSize(QSize(16, 16))
        self.liste.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.liste.currentRowChanged.connect(self._sel_fiche)
        self._suppr(self.liste, lambda: self.supprimer_fiche())
        self._raccourcis_ordre(self.liste)
        self.liste.itemDoubleClicked.connect(lambda *_: self._double_clic())
        self.liste.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.liste.customContextMenuRequested.connect(self._menu_fiche)
        b_sup = QPushButton(icone("edit-delete"), _("Supprimer la fiche"))
        b_sup.clicked.connect(self.supprimer_fiche)
        self.b_pin_fiche = QPushButton(avec_epingle(""), "")
        self.b_pin_fiche.setCheckable(True)
        self.b_pin_fiche.setToolTip(_("Épingler la fiche (elle reste en haut de la liste)"))
        self.b_pin_fiche.clicked.connect(lambda *_: self.epingler_fiche())
        bas = QHBoxLayout()
        bas.addWidget(b_sup, 1)
        bas.addWidget(self.b_pin_fiche)
        milieu = QWidget()
        lm = QVBoxLayout(milieu)
        lm.setContentsMargins(0, 0, 0, 0)
        lm.addWidget(self.liste)
        lm.addLayout(bas)

        self.titre = QLineEdit()
        self.titre.setPlaceholderText(_("Titre"))
        f = self.titre.font()
        f.setBold(True)
        f.setPointSize(f.pointSize() + 1)
        self.titre.setFont(f)
        self.b_copier = QPushButton(icone("edit-copy"), _("Copier la note"))
        self.b_copier.clicked.connect(self.copier_note)
        self.b_verrou = QPushButton(icone("object-locked"), _("Verrouiller…"))
        self.b_verrou.clicked.connect(self.verrou_action)
        self.b_refermer = QPushButton(icone("object-locked"), _("Refermer"))
        self.b_refermer.setToolTip(_("Referme la fiche : le mot de passe sera redemandé (Ctrl+Maj+L)"))
        self.b_refermer.clicked.connect(self.refermer_fiche)
        ligne = QHBoxLayout()
        ligne.addWidget(self.titre, 1)
        ligne.addWidget(self.b_copier)
        ligne.addWidget(self.b_refermer)
        ligne.addWidget(self.b_verrou)
        self.texte = Editeur()
        self.texte.setPlaceholderText(_("Note"))
        self.bande = BandePieces(self)
        self.texte.images_recues.connect(self.bande.ajouter)
        self.texte.pdf_demande.connect(self.exporter_pdf)
        self.statut = QLabel("")
        droite = QWidget()
        ld = QVBoxLayout(droite)
        ld.setContentsMargins(0, 0, 0, 0)
        self.apercu = Apercu()
        self.apercu.navigateur = lambda: str(self.store.reglages().get("navigateur", ""))
        self.apercu.pdf_demande.connect(self.exporter_pdf)
        self.format = BarreFormat(self.texte)
        self.format.apercu_demande.connect(self.basculer_apercu)
        self.pile = QStackedWidget()
        self.pile.addWidget(self.texte)
        self.pile.addWidget(self.apercu)
        self.repertoire = VueRepertoire()                      # page des fiches « répertoire » (tableau rangé par lettre)
        self.repertoire.modifie.connect(self._repertoire_modifie)
        self.repertoire.navigateur = lambda: str(self.store.reglages().get("navigateur", ""))
        self.pile.addWidget(self.repertoire)
        ld.addLayout(ligne)
        ld.addWidget(self.format)
        ld.addWidget(self.pile, 1)
        ld.addWidget(self.bande)
        ld.addWidget(self.statut)

        sp = QSplitter()
        sp.addWidget(gauche)
        sp.addWidget(milieu)
        sp.addWidget(droite)
        sp.setStretchFactor(0, 0)
        sp.setStretchFactor(1, 1)
        sp.setStretchFactor(2, 3)
        sp.setSizes([170, 220, 510])
        self.setCentralWidget(sp)

        self.titre.textEdited.connect(self._modifie)
        self.texte.textChanged.connect(self._modifie)
        self.titre.editingFinished.connect(self.sauver)
        for seq, slot in (("Ctrl+B", lambda: entourer(self.texte, "**", _("gras"))),
                          ("Ctrl+I", lambda: entourer(self.texte, "*", _("italique")))):
            a = QAction(self.texte)
            a.setShortcut(QKeySequence(seq))
            a.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)      # seulement quand l'éditeur a le focus
            a.triggered.connect(slot)
            self.texte.addAction(a)
        self.texte.textChanged.connect(self._maj_apercu)
        for seq, slot in (("Ctrl+S", self._forcer), ("Ctrl+Shift+L", self.refermer_fiche), ("Ctrl+F", lambda: self.recherche.setFocus()),
                          ("Ctrl+E", lambda: self.format.b_apercu.isEnabled() and self.format.b_apercu.toggle())):
            a = QAction(self)
            a.setShortcut(QKeySequence(seq))
            a.triggered.connect(slot)
            self.addAction(a)
        self._etat_editeur(False)

    # ---------- thèmes ----------
    def _raccourcis_ordre(self, liste):
        for seq, delta in (("Alt+Up", -1), ("Alt+Down", 1)):
            a = QAction(liste)
            a.setShortcut(QKeySequence(seq))
            a.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
            a.triggered.connect(lambda *_a, d=delta, li=liste: self.deplacer(li, d))
            liste.addAction(a)

    @staticmethod
    def _suppr(liste, slot):
        """Touche Suppr : supprime ce qui est sélectionné dans CETTE liste seulement (jamais dans l'éditeur ni le titre)."""
        a = QAction(liste)
        a.setShortcut(QKeySequence(Qt.Key.Key_Delete))
        a.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        a.triggered.connect(lambda *_: slot())
        liste.addAction(a)

    def _themes_ordonnes(self) -> list:
        """Thèmes épinglés d'abord, puis les autres ; dans chaque groupe, l'ordre choisi à la main (sinon alphabétique)."""
        return sorted(self.store.themes_tries(), key=lambda t: not self.store.theme_epingle(t))

    def _noms(self):
        return [self.TOUS] + [t.nom for t in self._themes_ordonnes()]

    def maj_themes(self):
        self.liste_themes.blockSignals(True)
        self.liste_themes.clear()
        it = QListWidgetItem(icone(ICONE_DEFAUT), self.TOUS)
        it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)         # « Toutes les fiches » reste en première ligne
        self.liste_themes.addItem(it)
        for t in self._themes_ordonnes():
            nom_icone = t.icone if not icone(t.icone).isNull() else ICONE_DEFAUT
            ic = avec_epingle(nom_icone) if self.store.theme_epingle(t) else icone(nom_icone)
            it = QListWidgetItem(ic, f"{t.nom}  ({len(t.fiches)})")
            it.setData(Qt.ItemDataRole.UserRole, t.path.name)
            self.liste_themes.addItem(it)
        if self.theme not in self._noms():
            self.theme = self.TOUS
        self.liste_themes.setCurrentRow(self._noms().index(self.theme))
        self.liste_themes.blockSignals(False)
        self._maj_pins()

    def _ordre_fiches_possible(self) -> bool:
        return self.theme != self.TOUS and not self.recherche.text().strip()

    def _ordre_themes_change(self):
        self.store.ordonner_themes([c for c in self.liste_themes.cles() if c])
        self.maj_themes()

    def _ordre_fiches_change(self):
        t = self._theme_courant()
        if t is None or not self._ordre_fiches_possible():
            return self.maj_fiches()
        self.store.ordonner_fiches(t, [c for c in self.liste.cles() if c])
        self.maj_fiches()

    def deplacer(self, liste, delta: int):
        """Alt+Haut / Alt+Bas : monte ou descend l'élément courant d'une place (même effet que le glisser-déposer)."""
        if liste is self.liste_themes:
            cles = [t.path.name for t in self._themes_ordonnes()]
            t = self._theme_courant()
            courant = t.path.name if t else None
        else:
            if not self._ordre_fiches_possible() or not self.fiche:
                return
            cles = [f.path.name for _t, f in self.rows]
            courant = self.fiche.path.name
        if courant not in cles:
            return
        i, j = cles.index(courant), cles.index(courant) + delta
        if not 0 <= j < len(cles):
            return
        cles[i], cles[j] = cles[j], cles[i]
        if liste is self.liste_themes:
            self.store.ordonner_themes(cles)
            self.maj_themes()
        else:
            self.store.ordonner_fiches(self.fiche_theme, cles)
            self.maj_fiches()

    def _maj_pins(self):
        t = self._theme_courant()
        self.b_pin_theme.setEnabled(t is not None)
        self.b_pin_theme.setChecked(bool(t and self.store.theme_epingle(t)))
        f = self.fiche
        self.b_pin_fiche.setEnabled(bool(f and self.fiche_theme))
        self.b_pin_fiche.setChecked(bool(f and self.fiche_theme and self.store.fiche_epinglee(self.fiche_theme, f)))

    def epingler_theme(self):
        t = self._theme_courant()
        if t is None:
            return
        self.store.epingler_theme(t, not self.store.theme_epingle(t))
        self.maj_themes()
        self.maj_fiches()

    def epingler_fiche(self, theme=None, fiche=None):
        t, f = (theme, fiche) if fiche is not None else (self.fiche_theme, self.fiche)
        if f is None or t is None:
            return
        self.store.epingler_fiche(t, f, not self.store.fiche_epinglee(t, f))
        self.maj_fiches()
        self._maj_pins()

    def _menu_fiche(self, pos):
        it = self.liste.itemAt(pos)
        if it is None or not 0 <= self.liste.row(it) < len(self.rows):
            return
        t, f = self.rows[self.liste.row(it)]
        m = QMenu(self)
        n = len(self._fiches_selectionnees())
        if n == 1:                                       # plusieurs sélectionnées : seule la suppression est groupée
            m.addAction(avec_epingle(""), _("Désépingler") if self.store.fiche_epinglee(t, f) else _("Épingler"),
                        lambda: self.epingler_fiche(t, f))
        if self._ordre_fiches_possible() and self.store.ordre()["fiches"].get(t.path.name):
            m.addAction(_("Remettre les fiches dans l'ordre alphabétique"), self._ordre_alphabetique_fiches)
        m.addAction(icone("edit-delete"), _("Supprimer les %d fiches…") % n if n > 1 else _("Supprimer…"), self.supprimer_fiche)
        m.exec(self.liste.mapToGlobal(pos))

    def _theme_courant(self):
        return self.store.theme(self.theme)

    def _sel_theme(self, row):
        if row < 0:
            return
        self.quitter_fiche()
        self.theme = self._noms()[row]
        self.maj_fiches()
        self._maj_pins()

    def _menu_theme(self, pos):
        if not self._theme_courant():
            return
        m = QMenu(self)
        n = len(self._themes_selectionnes())
        if n == 1:                                       # plusieurs sélectionnés : seule la suppression est groupée
            m.addAction(avec_epingle(""), _("Désépingler") if self.store.theme_epingle(self._theme_courant()) else _("Épingler"),
                        self.epingler_theme)
            m.addAction(icone("edit-rename"), _("Renommer…"), self.renommer_theme)
            m.addAction(icone("view-pim-notes"), _("Icône…"), self.icone_theme)
        if self.store.ordre()["themes"]:
            m.addAction(_("Remettre les thèmes dans l'ordre alphabétique"), self._ordre_alphabetique_themes)
        m.addAction(icone("edit-delete"), _("Supprimer les %d thèmes…") % n if n > 1 else _("Supprimer…"), self.supprimer_theme)
        m.exec(self.liste_themes.mapToGlobal(pos))

    def _ordre_alphabetique_themes(self):
        self.store.ordonner_themes(None)
        self.maj_themes()

    def _ordre_alphabetique_fiches(self):
        t = self._theme_courant()
        if t is not None:
            self.store.ordonner_fiches(t, None)
            self.maj_fiches()

    def nouveau_theme(self):
        n, ok = QInputDialog.getText(self, _("Nouveau thème"), _("Nom du thème :"))
        if not ok or not n.strip():
            return
        nom = propre(n, "thème")
        if nom in self._noms():
            QMessageBox.information(self, _("Thème"), _("Ce thème existe déjà."))
            return
        self.quitter_fiche()
        self.store.nouveau_theme(nom)
        self.plugins.emettre("themes_modifies")
        self.theme = nom
        self.maj_themes()
        self.maj_fiches()

    def renommer_theme(self):
        t = self._theme_courant()
        if not t:
            return
        n, ok = QInputDialog.getText(self, _("Renommer"), _("Nouveau nom :"), text=t.nom)
        nom = propre(n, "") if ok and n else ""
        if not nom or nom == t.nom or nom in self._noms():
            return
        self.quitter_fiche()
        self.store.renommer_theme(t, nom)
        self.plugins.emettre("themes_modifies")
        self.theme = t.nom
        self.maj_themes()
        self.maj_fiches()

    def icone_theme(self):
        t = self._theme_courant()
        if not t:
            return
        d = DialogueIcone(self, t.nom, t.icone)
        if d.exec() and d.nom():
            self.store.icone_theme(t, d.nom())
            self.plugins.emettre("themes_modifies")
            self.maj_themes()

    def _themes_selectionnes(self) -> list:
        """Thèmes sélectionnés dans la liste de gauche (Ctrl / Maj + clic), sans « Toutes les fiches » ; à défaut, le thème courant."""
        ordonnes = self._themes_ordonnes()
        lignes = sorted({self.liste_themes.row(i) for i in self.liste_themes.selectedItems()})
        choisis = [ordonnes[r - 1] for r in lignes if 1 <= r <= len(ordonnes)]
        courant = self._theme_courant()
        return choisis or ([courant] if courant else [])

    def _fiches_selectionnees(self) -> list:
        """[(thème, fiche)] sélectionnées dans la liste du milieu ; à défaut, la fiche affichée."""
        lignes = sorted({self.liste.row(i) for i in self.liste.selectedItems()})
        choisies = [self.rows[r] for r in lignes if 0 <= r < len(self.rows)]
        return choisies or ([(self.fiche_theme, self.fiche)] if self.fiche else [])

    def supprimer_theme(self):
        ts = self._themes_selectionnes()
        if not ts:
            return
        if len(ts) == 1:
            t = ts[0]
            question = (_("Supprimer le thème"),
                        _("Mettre « %(nom)s » et ses %(n)d fiche(s) à la corbeille ?\n(%(dossier)s)")
                        % {"nom": t.nom, "n": len(t.fiches), "dossier": self.store.paths.corbeille})
        else:
            question = (_("Supprimer les thèmes"),
                        _("Mettre ces %(t)d thèmes et leurs %(n)d fiche(s) à la corbeille ?\n\n%(liste)s\n\n(%(dossier)s)")
                        % {"t": len(ts), "n": sum(len(t.fiches) for t in ts), "liste": "\n".join("· " + t.nom for t in ts),
                           "dossier": self.store.paths.corbeille})
        if QMessageBox.question(self, *question) == QMessageBox.StandardButton.Yes:
            self.fiche = None
            for t in ts:
                self.store.supprimer_theme(t)
            self.plugins.emettre("themes_modifies")
            self.theme = self.TOUS
            self.maj_themes()
            self.maj_fiches()

    # ---------- fiches ----------
    def _libelle(self, t, f, tous):
        lib = f.titre or _("(sans titre)")
        if f.verrou:
            lib += "   " + _("(verrouillée)")
        if tous:
            lib += f"   [{t.nom}]"
        return lib

    def maj_fiches(self):
        q = self.recherche.text().strip().lower()
        self.liste.blockSignals(True)
        self.liste.clear()
        self.rows = []
        sel = None
        trouvees = []
        for t in self._themes_ordonnes():
            if not q and self.theme != self.TOUS and t.nom != self.theme:
                continue   # une recherche porte sur tous les thèmes
            for f in self.store.fiches_triees(t):
                if q and q not in f.titre.lower() and q not in (f.texte or "").lower() and q not in t.nom.lower() \
                        and q not in self.store.texte_ocr(f).lower():
                    continue   # fiche verrouillée fermée : pas de recherche dans le contenu (ni dans ses images)
                trouvees.append((t, f))
        trouvees.sort(key=lambda tf: not self.store.fiche_epinglee(*tf))          # fiches épinglées d'abord (tri stable)
        for t, f in trouvees:
            nom_icone = "object-locked" if f.verrou else ("x-office-address-book" if repertoire.est_repertoire(f.texte) else "")
            ic = avec_epingle(nom_icone) if self.store.fiche_epinglee(t, f) else (icone(nom_icone) if nom_icone else QIcon_vide())
            it = QListWidgetItem(ic, self._libelle(t, f, self.theme == self.TOUS or q))
            it.setData(Qt.ItemDataRole.UserRole, f.path.name)
            self.liste.addItem(it)
            if f is self.fiche:
                sel = len(self.rows)
            self.rows.append((t, f))
        self.liste.blockSignals(False)
        # glisser-déposer : seulement dans la vue d'un thème (l'ordre est propre à chaque thème), jamais pendant une recherche
        self.liste.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove if self._ordre_fiches_possible()
                                   else QAbstractItemView.DragDropMode.NoDragDrop)
        if self.rows:
            self.liste.setCurrentRow(sel if sel is not None else 0)
            if sel is None:
                self._sel_fiche(0)
        else:
            self._afficher(None, None)

    def _sel_fiche(self, row):
        if 0 <= row < len(self.rows):
            t, f = self.rows[row]
            if f is not self.fiche:
                self.quitter_fiche()
                self._afficher(t, f)

    def _etat_editeur(self, actif):
        self.titre.setEnabled(actif)
        self.texte.setEnabled(actif)
        self.format.setEnabled(actif)
        if not actif and self.format.b_apercu.isChecked():
            self.format.b_apercu.setChecked(False)

    def choisir_navigateur(self):
        """Navigateur utilisé pour les liens de l'aperçu : celui du système, ou une commande (modifiable à la main)."""
        systeme = _("Navigateur du système (par défaut)")
        actuel = str(self.store.reglages().get("navigateur", ""))
        choix = [systeme] + navigateurs_installes()
        if actuel and actuel not in choix:
            choix.append(actuel)
        texte, ok = QInputDialog.getItem(self, _("Navigateur pour les liens"),
                                         _("Choisissez un navigateur, ou tapez une commande (ex. : firefox) :"),
                                         choix, choix.index(actuel) if actuel else 0, True)
        if ok:
            texte = texte.strip()
            self.store.sauver_reglages(navigateur="" if texte in ("", systeme) else texte)

    def basculer_apercu(self, actif: bool):
        """Aperçu Markdown (lecture seule, rien n'est écrit) ou édition."""
        self.format.definir_apercu(actif)
        if actif:
            self.apercu.afficher(self.texte.toPlainText())
        self.pile.setCurrentWidget(self.apercu if actif else self.texte)

    def _maj_apercu(self):
        if self.pile.currentWidget() is self.apercu:
            self.apercu.afficher(self.texte.toPlainText())

    def _statut(self, txt, couleur=GRIS):
        self.statut.setText(txt)
        self.statut.setStyleSheet(f"color: {couleur};")

    def _afficher(self, t, f):
        self.fiche, self.fiche_theme = f, t
        self.chargement = True
        ferme = bool(f and f.fermee)
        self.titre.setText(f.titre if f else "")
        if ferme:
            self.texte.setPlainText(_("Fiche verrouillée.\n\nCliquer sur « Déverrouiller… » (ou double-clic sur la fiche) "
                                      "et saisir le mot de passe."))
            self._statut(_("Verrouillée") + f"  ·  {t.nom}/{f.path.name}", ORANGE)
        elif f:
            self.texte.setPlainText(f.texte)
            etat = _("Verrouillée (ouverte)") if f.verrou else _("✔ Enregistré")
            self._statut(f"{etat} ({_('modifié le')} {f.maj})  ·  {t.nom}/{f.path.name}", VERT)
        else:
            self.texte.clear()
            self._statut(_("Aucune fiche : « Fiche » (Ctrl+N)"))
        self._etat_editeur(f is not None and not ferme)
        self.bande.charger(t, f)
        self._mode_repertoire(bool(f and not ferme and repertoire.est_repertoire(f.texte)))
        self.texte.document().clearUndoRedoStacks()
        self.chargement = False
        self._maj_boutons()
        if f is not None:
            self.plugins.emettre("fiche_ouverte", fiche=FicheVue(t, f))

    def _mode_repertoire(self, actif: bool):
        """Une fiche répertoire montre sa barre de lettres à la place de l'éditeur de texte (le CSV reste dans `self.texte`)."""
        if actif:
            if self.format.b_apercu.isChecked():
                self.format.b_apercu.setChecked(False)
            self.repertoire.charger(self.texte.toPlainText())
            self.pile.setCurrentWidget(self.repertoire)
        elif self.pile.currentWidget() is self.repertoire:
            self.pile.setCurrentWidget(self.texte)
        self.format.setVisible(not actif)
        self.format.b_apercu.setEnabled(not actif)
        if actif:
            self.bande.setVisible(False)             # (sinon la bande se montre ou se cache selon les images, voir `bande.charger`)

    def _repertoire_modifie(self, texte: str):
        if self.fiche is not None and not self.fiche.fermee:
            self.texte.setPlainText(texte)           # déclenche l'enregistrement automatique comme une frappe

    def nouveau_repertoire(self):
        """Crée une fiche répertoire dans le thème courant, à partir d'un modèle de colonnes (modifiables ensuite)."""
        modeles = [_(m[0]) for m in repertoire.MODELES]
        choix, ok = QInputDialog.getItem(self, _("Nouveau répertoire"), _("Modèle de colonnes (modifiables ensuite) :"), modeles, 0, False)
        if not ok:
            return
        titre, ok = QInputDialog.getText(self, _("Nouveau répertoire"), _("Titre du répertoire :"), text=_("Répertoire"))
        if not ok or not titre.strip():
            return
        self.quitter_fiche()
        t = self._theme_courant() or (self.store.themes[0] if self.store.themes else None)
        if t is None:
            self.nouveau_theme()
            t = self._theme_courant()
            if t is None:
                return
        f = self.store.nouvelle_fiche(t)
        self.store.enregistrer(t, f, titre.strip(), repertoire.texte_modele(modeles.index(choix)))
        self.recherche.blockSignals(True)
        self.recherche.clear()
        self.recherche.blockSignals(False)
        if self.theme not in (self.TOUS, t.nom):
            self.theme = t.nom
        self.fiche, self.fiche_theme = f, t
        self.maj_themes()
        self.maj_fiches()
        self._afficher(t, f)

    def ajouter_depuis_cli(self, p: dict) -> str:
        """Appelé par l'instance unique pour `scrinium ajouter` : écrit ici, pour que l'éditeur reste cohérent.
        Retourne un message d'erreur, ou \"\" si tout va bien. Une fiche verrouillée fermée est refusée."""
        try:
            self.sauver()        # ce qui est en cours de frappe est enregistré avant de toucher à la fiche
            t, f = capture.ajouter(self.store, p["theme"], p["fiche"], p["texte"], p.get("commande", ""),
                                   bool(p.get("remplacer")), bool(p.get("brut")))
        except (ValueError, KeyError, OSError) as ex:
            return str(ex)
        if f is self.fiche:
            self._afficher(t, f)          # le texte ajouté apparaît dans l'éditeur
        self.maj_themes()
        self.maj_fiches()
        self.plugins.emettre("fiche_enregistree", fiche=FicheVue(t, f), origine="capture")
        if self.tray is not None and not self.isVisible():
            self.tray.showMessage(_("Scrinium"), _("Ajouté à « %(theme)s / %(fiche)s »") % {"theme": t.nom, "fiche": f.titre},
                                  QSystemTrayIcon.MessageIcon.Information, 4000)
        return ""

    def _theme_invitations(self):
        th = self.store.nouveau_theme(invitation.nom_theme())
        self.store.icone_theme(th, "mail-send")
        return th

    def inviter(self):
        """Crée (ou rouvre, sans l'écraser) la fiche d'invitation à installer Scrinium, puis propose de l'envoyer par courriel."""
        self.sauver()
        th = next((t for t in self.store.themes if t.nom == invitation.nom_theme()), None) or \
            self._theme_invitations()
        titre = invitation.titre_fiche()
        f = next((x for x in th.fiches if x.titre == titre), None)
        if f is None:
            f = self.store.nouvelle_fiche(th)
            self.store.enregistrer(th, f, titre, invitation.texte())
        self.quitter_fiche()
        self.maj_themes()
        self.montrer(theme=th.nom)
        self.selectionner_fiche(FicheVue(th, f))
        courriel = self.plugins.actifs.get("courriel")
        envoyer = getattr(courriel[0], "envoyer", None) if courriel else None
        if envoyer is not None:
            QTimer.singleShot(0, envoyer)                 # la fenêtre d'envoi s'ouvre après l'affichage de la fiche
        else:
            self._statut(_("Fiche d'invitation prête : relisez-la, puis activez l'extension Courriel (Extensions > Gérer les "
                           "extensions…) pour l'envoyer."), ORANGE)

    def doc_extensions(self):
        """Crée (ou rouvre, sans rien écraser) le thème « Doc » : comment écrire une extension. Les fiches absentes sont ajoutées."""
        self.sauver()
        nom = doc_extensions.nom_theme()
        th = next((t for t in self.store.themes if t.nom == nom), None)
        if th is None:
            th = self.store.nouveau_theme(nom)
            self.store.icone_theme(th, doc_extensions.icone())
        titres = {f.titre for f in th.fiches}
        premiere = None
        for titre, texte in doc_extensions.fiches(self.store.paths.base / "plugins"):
            if titre not in titres:
                f = self.store.nouvelle_fiche(th)
                self.store.enregistrer(th, f, titre, texte)
            if premiere is None:
                premiere = next(x for x in th.fiches if x.titre == titre)
        self.quitter_fiche()
        self.maj_themes()
        self.montrer(theme=th.nom)
        self.selectionner_fiche(FicheVue(th, premiere))

    def ouvrir_lien(self, url: str):
        """Lien `scrinium://…` reçu du système : confié à l'extension qui sait le traiter (Partage). Rien n'est fait sans
        un clic de l'utilisateur dans la fenêtre qu'elle ouvre."""
        self.montrer()
        try:
            demande = lien_mod.analyser(url)
        except ValueError as ex:
            QMessageBox.warning(self, _("Lien Scrinium"), str(ex))
            return
        if demande["action"] == "ajouter":
            self._ajout_par_lien(demande)
            return
        partage = self.plugins.actifs.get("partage")
        ouvrir = getattr(partage[0], "rejoindre_lien", None) if partage else None
        if ouvrir is None:
            self._statut(_("Lien de partage reçu : activez l'extension Partage (Extensions > Gérer les extensions…) pour le "
                           "utiliser."), ORANGE)
            return
        self.plugins.appeler("partage", ouvrir, url)

    def _ajout_par_lien(self, demande: dict):
        """`scrinium://ajouter` : montre ce qui serait ajouté ; seule la validation de l'utilisateur crée une NOUVELLE fiche
        (une fiche existante n'est jamais modifiée, une fiche verrouillée jamais touchée)."""
        if getattr(self, "_lien_ouvert", False):                 # un lien qui en enverrait mille ne fait pas mille fenêtres
            return
        self._lien_ouvert = True
        try:
            pref = self.store.reglages().get("capture_rapide", {})
            noms = [t.nom for t in self.store.themes]
            defaut = demande["theme"] if demande["theme"] in noms else (pref.get("theme") if pref.get("theme") in noms
                                                                          else _(THEME_DEFAUT))
            d = DialogueAjoutLien(self, demande, noms, defaut)
            if not d.exec():
                return
            theme, titre, texte = d.resultat()
        finally:
            self._lien_ouvert = False
        self.quitter_fiche()
        nom = propre(theme or _(THEME_DEFAUT), "thème")
        th = self.store.theme(nom) or self.store.nouveau_theme(nom)
        f = self.store.nouvelle_fiche(th)
        self.store.enregistrer(th, f, lien_mod.titre_par_defaut(titre, texte, time.strftime("%Y-%m-%d %H:%M")), texte)
        self.maj_themes()
        self.montrer(theme=th.nom)
        self.selectionner_fiche(FicheVue(th, f))
        self._statut(_("✔ Fiche ajoutée depuis un lien") + f"  ·  {th.nom}/{f.path.name}", VERT)

    def capture_rapide(self):
        """Petite fenêtre de note rapide, au premier plan (la fenêtre principale n'est pas affichée)."""
        self.sauver()
        d = CaptureRapide(self)
        self._capture = d                           # référence : la fenêtre n'a pas de parent
        d.show()
        d.raise_()
        d.activateWindow()

    def pieces_modifiees(self):
        """Appelé par la bande après un ajout ou une suppression d'image."""
        f, t = self.fiche, self.fiche_theme
        if f is not None:
            self._statut(f"{_('✔ Images mises à jour')} ({time.strftime('%H:%M:%S')})  ·  {t.nom}/{f.path.name}", VERT)

    def nouvelle_fiche(self):
        self.quitter_fiche()
        t = self._theme_courant() or (self.store.themes[0] if self.store.themes else None)
        if t is None:
            self.nouveau_theme()
            t = self._theme_courant()
            if t is None:
                return
        f = self.store.nouvelle_fiche(t)
        self.recherche.blockSignals(True)
        self.recherche.clear()
        self.recherche.blockSignals(False)
        if self.theme not in (self.TOUS, t.nom):
            self.theme = t.nom
        self.fiche, self.fiche_theme = f, t
        self.maj_themes()
        self.maj_fiches()
        self._afficher(t, f)
        self.titre.setFocus()

    def supprimer_fiche(self):
        choisies = self._fiches_selectionnees()
        if not choisies:
            return
        if len(choisies) == 1:
            f = choisies[0][1]
            texte = _("Mettre la fiche « %s » à la corbeille ?") % (f.titre or _("(sans titre)"))
        else:
            texte = _("Mettre ces %d fiches à la corbeille ?") % len(choisies) + "\n\n" + "\n".join(
                "· " + (f.titre or _("(sans titre)")) + (" " + _("(verrouillée)") if f.verrou else "") for _t, f in choisies)
        if QMessageBox.question(self, _("Supprimer"), texte) == QMessageBox.StandardButton.Yes:
            self.fiche = None
            for t, f in choisies:
                self.store.supprimer_fiche(t, f)
            self.maj_themes()
            self.maj_fiches()

    # ---------- enregistrement automatique ----------
    def _modifie(self, *_args):
        if self.chargement or not self.fiche:
            return
        self._statut(_("● modification en cours…"), ORANGE)
        self.setWindowTitle(_("Scrinium") + " *")
        self.timer.start()

    def _forcer(self):
        self.sauver()

    def sauver(self):
        self.timer.stop()
        f, t = self.fiche, self.fiche_theme
        if not f or self.chargement or f.fermee:
            return
        self.setWindowTitle(_("Scrinium"))
        titre, texte = self.titre.text().strip(), self.texte.toPlainText()
        if self.store.enregistrer(t, f, titre, texte):
            self._statut(f"{_('✔ Enregistré à')} {time.strftime('%H:%M:%S')}  ·  {t.nom}/{f.path.name}", VERT)
            self.plugins.emettre("fiche_enregistree", fiche=FicheVue(t, f), origine=None)
            row = self.liste.currentRow()
            if 0 <= row < len(self.rows):   # libellé à jour sans perdre la sélection
                self.liste.item(row).setText(self._libelle(t, f, self.theme == self.TOUS or self.recherche.text().strip()))
        else:
            self._statut(f"{_('✔ Enregistré')}  ·  {t.nom}/{f.path.name}", VERT)

    def quitter_fiche(self):
        self.sauver()
        if self.fiche is not None:
            self.plugins.emettre("fiche_fermee", fiche=FicheVue(self.fiche_theme, self.fiche))
        if self.fiche and self.store.jeter_si_vide(self.fiche_theme, self.fiche):
            self.fiche = None
            self.maj_themes()

    # ---------- extensions ----------
    def _vue(self, theme, fiche):
        return FicheVue(theme, fiche) if fiche is not None and theme is not None else None

    def gerer_extensions(self):
        DialogueExtensions(self).exec()

    def _plugin_coupe(self, nom: str, erreur: str):
        QMessageBox.warning(self, _("Extension désactivée"),
                            _("L'extension « %(nom)s » a été désactivée après des erreurs répétées :\n%(erreur)s")
                            % {"nom": nom, "erreur": erreur})

    def selectionner_fiche(self, vue):
        """Sélectionne dans la liste la fiche décrite par `vue` (utilisé par les extensions)."""
        for i, (t, f) in enumerate(self.rows):
            if FicheVue(t, f).id == vue.id:
                self.liste.setCurrentRow(i)
                return

    def _langue(self, code: str):
        self.store.sauver_reglages(langue=code)
        QMessageBox.information(self, _("Langue"), _("Langue modifiée : redémarrez Scrinium pour l'appliquer."))

    def _demarrage(self, on: bool):
        try:
            autostart.activer(on)
        except OSError as ex:
            QMessageBox.warning(self, _("Démarrage de la session"), _("Impossible de modifier le lancement automatique : %s") % ex)
            self.a_demarrage.blockSignals(True)
            self.a_demarrage.setChecked(autostart.actif())
            self.a_demarrage.blockSignals(False)

    # ---------- zone de notification ----------
    def _zone_notification(self):
        """Icône dans la zone de notification, si le bureau en a une (sinon : fenêtre ordinaire)."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.a_tray.setEnabled(False)
            self.a_tray.setToolTip(_("Pas de zone de notification sur ce bureau."))
            return
        self.tray = QSystemTrayIcon(icone_appli(), self)
        self.tray.setToolTip(_("Scrinium"))
        m = QMenu(self)
        m.addAction(icone("view-pim-notes"), _("Ouvrir Scrinium"), self.montrer)
        m.addAction(icone("document-new"), _("Nouvelle fiche"), lambda: self.montrer(nouvelle=True))
        m.addAction(icone("document-edit"), _("Capture rapide…"), self.capture_rapide)
        m.addSeparator()
        m.addAction(icone("application-exit"), _("Quitter"), self.quitter)
        self.tray.setContextMenu(m)
        self.tray.activated.connect(self._clic_tray)
        self.tray.show()
        QApplication.instance().setQuitOnLastWindowClosed(False)

    @property
    def tray_actif(self) -> bool:
        return self.tray is not None and self.a_tray.isChecked()

    def _clic_tray(self, raison):
        if raison == QSystemTrayIcon.ActivationReason.Trigger:
            self.cacher() if self.isVisible() and not self.isMinimized() else self.montrer()

    def montrer(self, theme: str | None = None, nouvelle: bool = False):
        if theme and theme in self._noms():
            self.quitter_fiche()
            self.theme = theme
            self.maj_themes()
            self.maj_fiches()
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.plugins.emettre("fenetre_montree")
        if nouvelle:
            self.nouvelle_fiche()

    def cacher(self):
        """Dans la zone de notification : enregistre, et referme les fiches verrouillées (mot de passe redemandé)."""
        self.quitter_fiche()
        for t in self.store.themes:
            for f in t.fiches:
                if f.verrou and not f.fermee:
                    self.store.refermer(f)
        if self.fiche is not None and self.fiche.fermee:
            self._afficher(self.fiche_theme, self.fiche)
        self.hide()
        self.plugins.emettre("fenetre_cachee")

    def quitter(self):
        self.quitter_vraiment = True
        self.close()
        QApplication.instance().quit()

    def changeEvent(self, ev):
        if ev.type() == QEvent.Type.WindowStateChange and self.isMinimized() and self.tray_actif:
            QTimer.singleShot(0, self.cacher)   # réduire = aller dans la zone de notification
        super().changeEvent(ev)

    def closeEvent(self, ev):
        if self.tray_actif and not self.quitter_vraiment:
            ev.ignore()
            self.cacher()
            return
        self.quitter_fiche()
        self.plugins.arreter()
        super().closeEvent(ev)

    # ---------- copier / verrou ----------
    def _maj_boutons(self):
        f = self.fiche
        self.b_copier.setEnabled(bool(f and not f.fermee))
        self.b_refermer.setVisible(bool(f and f.verrou and not f.fermee))
        if not f:
            txt, ic, ok = _("Verrouiller…"), "object-locked", False
        elif f.fermee:
            txt, ic, ok = _("Déverrouiller…"), "object-unlocked", True
        elif f.verrou:
            txt, ic, ok = _("Retirer le mot de passe"), "object-unlocked", True
        else:
            txt, ic, ok = _("Verrouiller…"), "object-locked", True
        self.b_verrou.setText(txt)
        self.b_verrou.setIcon(icone(ic))
        self.b_verrou.setEnabled(ok)
        self._maj_pins()

    def exporter_pdf(self):
        """Clic droit sur le contenu : écrit la fiche (titre, texte, images) dans un fichier PDF choisi par l'utilisateur."""
        f = self.fiche
        if not f or f.fermee:
            return
        if f.verrou and QMessageBox.question(
                self, _("Exporter en PDF"),
                _("Cette fiche est verrouillée : le PDF contiendra son texte et ses images EN CLAIR. Continuer ?")
        ) != QMessageBox.StandardButton.Yes:
            return
        self.sauver()
        base = propre(f.titre or _("fiche"), "fiche")
        chemin, _filtre = QFileDialog.getSaveFileName(self, _("Exporter en PDF"), str(Path.home() / f"{base}.pdf"),
                                                      _("Documents PDF (*.pdf)"))
        if not chemin:
            return
        if not chemin.lower().endswith(".pdf"):
            chemin += ".pdf"
        images = []
        for p in self.store.lister_pieces(f):
            try:
                images.append((p.nom, self.store.lire_piece(f, p)))
            except (ValueError, OSError):
                continue
        try:
            texte = self.texte.toPlainText()
            if repertoire.est_repertoire(texte):            # un répertoire s'imprime en tableaux, une section par lettre
                texte = repertoire.Tableau.depuis_texte(texte).en_markdown()
            export_pdf.ecrire_pdf(chemin, self.titre.text(), texte, images)
        except OSError as ex:
            QMessageBox.critical(self, _("Exporter en PDF"), _("Écriture impossible : %s") % ex)
            return
        self._statut(_("✔ PDF écrit : %s") % chemin, VERT)

    def copier_note(self):
        f = self.fiche
        if not f or f.fermee:
            return
        QApplication.clipboard().setText(self.texte.toPlainText())
        self._statut(f"{_('✔ Note copiée dans le presse-papiers')} ({time.strftime('%H:%M:%S')})", VERT)

    def _double_clic(self):
        if self.fiche and self.fiche.fermee:
            self.deverrouiller()

    def refermer_fiche(self):
        """Verrouille de nouveau, tout de suite, une fiche verrouillée restée ouverte (sans retaper le mot de passe)."""
        f, t = self.fiche, self.fiche_theme
        if not f or not f.verrou or f.fermee:
            return
        self.sauver()
        self.store.refermer(f)
        self._afficher(t, f)
        self.maj_fiches()

    def verrou_action(self):
        f = self.fiche
        if not f:
            return
        if f.fermee:
            self.deverrouiller()
        elif f.verrou:
            self.retirer_verrou()
        else:
            self.verrouiller()

    def _mdp(self, titre, msg):
        mdp, ok = QInputDialog.getText(self, titre, msg, QLineEdit.EchoMode.Password)
        return mdp if ok and mdp else None

    def deverrouiller(self):
        f, t = self.fiche, self.fiche_theme
        mdp = self._mdp(_("Fiche verrouillée"), _("Mot de passe de « %s » :") % f.titre)
        if not mdp:
            return
        try:
            self.store.deverrouiller(f, mdp)
        except crypto.InvalidTag:
            QMessageBox.critical(self, _("Mot de passe"), _("Mot de passe incorrect."))
            return
        except (ValueError, OSError) as ex:
            QMessageBox.critical(self, _("Fiche verrouillée"), _("Lecture impossible : %s") % ex)
            return
        self._afficher(t, f)

    def verrouiller(self):
        self.sauver()
        f, t = self.fiche, self.fiche_theme
        if not self.store.a_cle_de_secours:
            if not self._proposer_secours():
                return
            avertissement = (_("Mot de passe oublié : le fichier de secours permettra de rouvrir la fiche.")
                             if self.store.a_cle_de_secours else
                             _("Pas de fichier de secours : mot de passe oublié = fiche perdue."))
        else:
            avertissement = _("Mot de passe oublié : le fichier de secours permettra de rouvrir la fiche.")
        if QMessageBox.question(self, _("Verrouiller la fiche"),
                                _("Le texte et les images de la fiche seront chiffrés avec un mot de passe (le titre reste visible).\n\n")
                                + avertissement) != QMessageBox.StandardButton.Yes:
            return
        m1 = self._mdp(_("Verrouiller"), _("Mot de passe (4 caractères minimum) :"))
        if not m1:
            return
        if len(m1) < 4:
            QMessageBox.information(self, _("Mot de passe"), _("Trop court (4 caractères minimum)."))
            return
        m2 = self._mdp(_("Verrouiller"), _("Confirmer le mot de passe :"))
        if m1 != m2:
            QMessageBox.critical(self, _("Mot de passe"), _("Les deux saisies sont différentes, fiche non verrouillée."))
            return
        try:
            self.store.verrouiller(t, f, m1)
        except (ValueError, OSError) as ex:
            QMessageBox.critical(self, _("Verrouiller"), _("Fiche non verrouillée : %s") % ex)
            return
        self._afficher(t, f)
        self.maj_themes()
        self.maj_fiches()

    def retirer_verrou(self):
        f, t = self.fiche, self.fiche_theme
        if QMessageBox.question(self, _("Retirer le mot de passe"),
                                _("Le texte et les images de la fiche seront de nouveau stockés en clair. Continuer ?")
                                ) != QMessageBox.StandardButton.Yes:
            return
        self.sauver()
        try:
            self.store.retirer_verrou(t, f)
        except (ValueError, OSError) as ex:
            QMessageBox.critical(self, _("Retirer le mot de passe"), _("Verrou conservé : %s") % ex)
            return
        self._afficher(t, f)
        self.maj_themes()
        self.maj_fiches()

    # ---------- sécurité ----------
    def _proposer_secours(self) -> bool:
        """Premier verrouillage sans fichier de secours : on explique et on propose. False = annuler le verrouillage."""
        m = QMessageBox(self)
        m.setIcon(QMessageBox.Icon.Question)
        m.setWindowTitle(_("Fichier de secours"))
        m.setText(_("Avant de verrouiller : voulez-vous créer un fichier de secours ?"))
        m.setInformativeText(_("Si vous oubliez le mot de passe d'une fiche, le fichier de secours permet de la "
                               "rouvrir. Sans lui, une fiche dont le mot de passe est oublié est perdue pour toujours."))
        creer = m.addButton(_("Créer le fichier de secours"), QMessageBox.ButtonRole.AcceptRole)
        sans = m.addButton(_("Verrouiller sans fichier de secours"), QMessageBox.ButtonRole.DestructiveRole)
        m.addButton(_("Annuler"), QMessageBox.ButtonRole.RejectRole)
        m.setDefaultButton(creer)
        m.exec()
        c = m.clickedButton()
        if c is creer:
            AssistantCle(self.store, self).exec()
            return True   # même si « Plus tard » : l'utilisateur a vu l'avertissement, on continue
        return c is sans

    def assistant_cle(self):
        if self.store.a_cle_de_secours:
            if QMessageBox.question(
                    self, _("Fichier de secours"),
                    _("Un fichier de secours est déjà actif.\n\nEn créer un nouveau ? Il servira pour les fiches "
                      "verrouillées à partir de maintenant ; les fiches déjà verrouillées ne s'ouvriront qu'avec l'ancien.")
            ) != QMessageBox.StandardButton.Yes:
                return
            AssistantCle(self.store, self, remplacer=True).exec()
        else:
            AssistantCle(self.store, self).exec()

    def secours(self):
        f, t = self.fiche, self.fiche_theme
        if not f or not f.fermee:
            QMessageBox.information(self, _("Fichier de secours"), _("Sélectionnez d'abord une fiche verrouillée."))
            return
        chemin, _ok = QFileDialog.getOpenFileName(self, _("Fichier de secours"), str(self.store.paths.base), "PEM (*.pem);;*")
        if not chemin:
            return
        pem = open(chemin, "rb").read()
        phrase = None
        if b"ENCRYPTED" in pem:
            phrase = self._mdp(_("Fichier de secours"), _("Mot de passe du fichier de secours :"))
            if not phrase:
                return
        try:
            f.texte = self.store.ouvrir_avec_cle_privee(f, pem, phrase)
        except Exception as ex:
            QMessageBox.critical(self, _("Fichier de secours"), _("Impossible de rouvrir la fiche : %s") % ex)
            return
        if QMessageBox.question(self, _("Fichier de secours"),
                                _("Fiche rouverte. La remettre en clair (retirer le mot de passe) ?")
                                ) == QMessageBox.StandardButton.Yes:
            self.store.retirer_verrou(t, f)
        else:
            f.texte = f.cle = f.salt = None   # reste fermée ; rien n'a été écrit
            f.wrap = b""
            self.texte.setPlainText(_("Fiche toujours verrouillée."))
            return
        self._afficher(t, f)
        self.maj_themes()
        self.maj_fiches()

    def a_propos(self):
        QMessageBox.about(self, _("À propos"),
                          f"<b>Scrinium</b> {__version__}<br>"
                          + _("Fiches rangées par thème, verrouillables (AES-256-GCM).") +
                          "<br><br>GPL-3.0-or-later · icônes Breeze (LGPL)")


def QIcon_vide():
    from PyQt6.QtGui import QIcon
    return QIcon()

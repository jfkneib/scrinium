# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Fenêtre principale (PyQt6)."""
import time
from pathlib import Path

from PyQt6.QtCore import QEvent, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QCursor, QKeySequence
from PyQt6.QtPrintSupport import QPrintDialog, QPrinter
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPushButton, QSplitter, QToolButton,
                             QStackedWidget, QSystemTrayIcon, QToolBar, QVBoxLayout, QWidget)

from .. import __version__
from ..core import autostart, capture, crypto, invitation
from ..core.plugins import FicheVue, Gestionnaire
from ..core import doc_extensions, echange_md, images_texte, echange_theme, guide, lien as lien_mod, liens_fiches, repertoire, types_fiche
from ..core.store import ICONE_DEFAUT, Store, propre
from ..i18n import _
from .assistant import AssistantCle
from .capture_rapide import THEME_DEFAUT, CaptureRapide
from .extensions import DialogueExtensions, UiPlugin
from . import export_pdf, export_theme_doc
from .chercher_remplacer import BarreChercherRemplacer
from .choix_icone import DialogueIcone
from .entrees_menu import remplir as remplir_menu
from .icons import avec_epingle, avec_pastille, icone, icone_appli
from . import images
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

    def startDrag(self, actions):
        """La liste des fiches propose aussi la copie : déposée sur un thème (action Copy), Qt n'en retire pas les lignes."""
        if getattr(self, "fiches_glissables", False):
            actions = actions | Qt.DropAction.CopyAction
        super().startDrag(actions)

    def cles(self) -> list:
        return [self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count())]


class ListeThemes(ListeOrdonnable):
    """Liste des thèmes : on peut aussi y déposer des fiches (glissées depuis la liste du milieu) pour les ranger dans le thème visé."""
    fiches_deposees = pyqtSignal(str)          # nom du dossier du thème visé

    def _cible(self, ev):
        src = ev.source()
        if src is None or src is self or not getattr(src, "fiches_glissables", False):
            return None
        it = self.itemAt(ev.position().toPoint())
        return it.data(Qt.ItemDataRole.UserRole) if it is not None else None       # None : « Toutes les fiches » ou vide

    def dragEnterEvent(self, ev):
        if ev.source() is not self and getattr(ev.source(), "fiches_glissables", False):
            ev.acceptProposedAction()
        else:
            super().dragEnterEvent(ev)

    def dragMoveEvent(self, ev):
        if ev.source() is not self and getattr(ev.source(), "fiches_glissables", False):
            if self._cible(ev):
                ev.setDropAction(Qt.DropAction.CopyAction)       # jamais MoveAction : Qt retirerait les lignes de la liste source
                ev.accept()
            else:
                ev.ignore()
        else:
            super().dragMoveEvent(ev)

    def dropEvent(self, ev):
        if ev.source() is not self and getattr(ev.source(), "fiches_glissables", False):
            cible = self._cible(ev)
            if cible:
                ev.setDropAction(Qt.DropAction.CopyAction)
                ev.accept()
                QTimer.singleShot(0, lambda: self.fiches_deposees.emit(cible))
            else:
                ev.ignore()
            return
        super().dropEvent(ev)


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
        self.timer_pastilles = QTimer(self, interval=5 * 60 * 1000)      # le temps passe : une échéance arrive sans qu'on touche à la fiche
        self.timer_pastilles.timeout.connect(self.maj_pastilles)
        self.timer_pastilles.start()
        self.setWindowTitle(_("Scrinium"))
        self.setWindowIcon(icone_appli())
        self.resize(900, 540)
        store.charger()
        self.actions_fiche: list = []         # (extension, texte, fn, icône) : clic droit dans le texte d'une fiche (voir UiPlugin)
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
        self.menu_nouvelle = QMenu(_("Nouvelle fiche d'un type…"), self)       # flèche du bouton « Fiche » et menu Fichier : fiche ordinaire ou typée
        self.menu_nouvelle.aboutToShow.connect(self._remplir_menu_nouvelle)
        bouton = tb.widgetForAction(self.a_fiche)
        bouton.setMenu(self.menu_nouvelle)
        bouton.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)    # clic = fiche ordinaire (comme Ctrl+N), flèche = choix du type
        self.recherche = QLineEdit()
        self.recherche.setPlaceholderText(_("Chercher (Ctrl+F)…"))
        self.recherche.setClearButtonEnabled(True)
        self.recherche.addAction(icone("edit-find"), QLineEdit.ActionPosition.LeadingPosition)
        self.recherche.textChanged.connect(lambda *_: self.maj_fiches())
        tb.addWidget(self.recherche)

        self.setAcceptDrops(True)                  # un .md ou un .zip de thème déposé sur la fenêtre est importé
        m = self.menuBar()
        mf = m.addMenu(_("&Fichier"))
        mf.addAction(self.a_theme)
        mf.addAction(self.a_fiche)
        mf.addMenu(self.menu_nouvelle)
        mf.addAction(self._action(_("Nouveau répertoire…"), "x-office-address-book", self.nouveau_repertoire, "Ctrl+Alt+R"))
        mf.addAction(self._action(_("Fiches liées…"), "insert-link", self.fiches_liees, "Ctrl+Alt+L"))
        mf.addAction(self._action(_("Imprimer la fiche…"), "document-print", self.imprimer_fiche, "Ctrl+P"))
        mf.addAction(self._action(_("Exporter la fiche en Markdown…"), "document-export", self.exporter_markdown))
        mf.addAction(self._action(_("Exporter en Markdown simple (pour un autre outil)…"), "document-export",
                                  lambda *_a: self.exporter_markdown(simple=True)))
        mf.addAction(self._action(_("Importer des fichiers Markdown…"), "document-import", self.importer_markdown))
        mf.addAction(self._action(_("Exporter le thème en archive (.zip)…"), "document-export", self.exporter_theme))
        mf.addAction(self._action(_("Exporter le thème en site HTML…"), "text-html", self.exporter_theme_html))
        mf.addAction(self._action(_("Exporter le thème en un seul PDF…"), "application-pdf", self.exporter_theme_pdf))
        mf.addAction(self._action(_("Importer un thème (.zip)…"), "document-import", self.importer_theme))
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
        mh.addAction(self._action(_("Guide de Scrinium"), "help-contents", self.guide))
        mh.addAction(self._action(_("Documentation des extensions"), "preferences-plugin", self.doc_extensions))
        mh.addAction(self._action(_("À propos"), "help-about", self.a_propos))

        self.liste_themes = ListeThemes()
        self.liste_themes.fiches_deposees.connect(self.deplacer_fiches_vers)
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
        self.liste.fiches_glissables = True            # on peut les déposer sur un thème (voir ListeThemes)
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
        self.texte.impression_demandee.connect(self.imprimer_fiche)
        self.texte.complements = self._entrees_clic_droit
        self.statut = QLabel("")
        droite = QWidget()
        ld = QVBoxLayout(droite)
        ld.setContentsMargins(0, 0, 0, 0)
        self.apercu = Apercu()
        self.apercu.navigateur = lambda: str(self.store.reglages().get("navigateur", ""))
        self.apercu.pdf_demande.connect(self.exporter_pdf)
        self.apercu.impression_demandee.connect(self.imprimer_fiche)
        self.apercu.complements = self._entrees_clic_droit
        self.apercu.fiche_existe = lambda cible: liens_fiches.resoudre(self.store, cible) is not None
        self.apercu.fiche_demandee.connect(self.ouvrir_fiche_liee)
        self.apercu.image_piece = self._octets_piece
        self.format = BarreFormat(self.texte)
        self.format.apercu_demande.connect(self.basculer_apercu)
        self.format.choisir_image = self.inserer_image
        self.format.fiches_cibles = lambda: [(t.nom, f.titre) for t in self.store.themes for f in self.store.fiches_triees(t)
                                             if f.titre and f is not self.fiche]
        self.pile = QStackedWidget()
        self.pile.addWidget(self.texte)
        self.pile.addWidget(self.apercu)
        self.vues_types: dict = {}                             # « tout est fiche » : nom du type -> vue (voir ajouter_vue_type)
        self._validation_en_attente = False                    # la vue d'un type vient d'être modifiée par l'utilisateur
        self.repertoire = VueRepertoire()                      # page des fiches « répertoire » (tableau rangé par lettre)
        self.repertoire.navigateur = lambda: str(self.store.reglages().get("navigateur", ""))
        self.repertoire.applications = lambda: {str(k): str(v) for k, v in (self.store.reglages().get("applications") or {}).items()} \
            if isinstance(self.store.reglages().get("applications"), dict) else {}
        self.repertoire.sauver_applications = lambda d: self.store.sauver_reglages(applications=d)
        self.ajouter_vue_type(repertoire.TYPE.nom, self.repertoire)
        self.bandeau_validation = QWidget()                    # fiche d'un type exécutable reçue de l'extérieur : inerte jusqu'à validation
        lv = QHBoxLayout(self.bandeau_validation)
        lv.setContentsMargins(4, 2, 4, 2)
        self.etiquette_validation = QLabel(_("Cette fiche peut lancer des commandes. Elle est inerte tant que vous ne l'avez pas validée "
                                             "(elle n'a pas été créée ici, ou son contenu a changé)."))
        self.etiquette_validation.setWordWrap(True)
        lv.addWidget(self.etiquette_validation, 1)
        self.b_valider = QPushButton(icone("dialog-ok-apply"), _("Valider cette fiche"))
        self.b_valider.clicked.connect(self.valider_fiche_courante)
        lv.addWidget(self.b_valider)
        self.bandeau_validation.setStyleSheet("background: #fdebd0; color: #5b3a00;")
        self.bandeau_validation.setVisible(False)
        ld.addLayout(ligne)
        ld.addWidget(self.format)
        ld.addWidget(self.bandeau_validation)
        self.barre_remplacer = BarreChercherRemplacer(self.texte)
        ld.addWidget(self.barre_remplacer)
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
                          ("Ctrl+H", self.chercher_remplacer),
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
        if n == 1:                                       # plusieurs sélectionnées : seuls déplacer et supprimer sont groupés
            m.addAction(avec_epingle(""), _("Désépingler") if self.store.fiche_epinglee(t, f) else _("Épingler"),
                        lambda: self.epingler_fiche(t, f))
            a = m.addAction(icone("object-locked"), _("Lecture seule"), lambda: self.basculer_lecture_seule(t, f))
            a.setCheckable(True)
            a.setChecked(self.store.fiche_lecture_seule_propre(t, f))
            a.setEnabled(not self.store.theme_lecture_seule(t))                  # le thème est déjà en lecture seule : on le lève d'abord
        if self._ordre_fiches_possible() and self.store.ordre()["fiches"].get(t.path.name):
            m.addAction(_("Remettre les fiches dans l'ordre alphabétique"), self._ordre_alphabetique_fiches)
        autres = [th for th in self._themes_ordonnes() if not all(x is th for x, _f in self._fiches_selectionnees())]
        if autres:
            sous = m.addMenu(icone("folder"), _("Déplacer vers le thème"))
            for th in autres:
                sous.addAction(icone(th.icone) if not icone(th.icone).isNull() else icone(ICONE_DEFAUT), th.nom,
                               lambda *_a, cle=th.path.name: self.deplacer_fiches_vers(cle))
        m.addAction(icone("edit-delete"), _("Supprimer les %d fiches…") % n if n > 1 else _("Supprimer…"), self.supprimer_fiche)
        m.exec(self.liste.mapToGlobal(pos))

    def deplacer_fiches_vers(self, cle_theme: str):
        """Range les fiches sélectionnées dans le thème dont le dossier s'appelle `cle_theme` (glisser-déposer ou clic droit)."""
        dst = next((t for t in self.store.themes if t.path.name == cle_theme), None)
        if dst is None:
            return
        self.sauver()                                    # ce qui est en cours de frappe est écrit avant de bouger le fichier
        courante = self.fiche
        fait = 0
        for t, f in list(self._fiches_selectionnees()):
            try:
                if self.store.deplacer_fiche(t, f, dst):
                    fait += 1
                    if f is courante:
                        self.fiche_theme = dst
            except OSError as ex:
                QMessageBox.warning(self, _("Scrinium"), _("Déplacement impossible : %s") % ex)
                break
        if fait:
            self.maj_themes()
            self.maj_fiches()
            self.plugins.emettre("themes_modifies")
            self._statut(_("✔ %(n)d fiche(s) déplacée(s) vers « %(theme)s »") % {"n": fait, "theme": dst.nom}, VERT)

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
            th = self._theme_courant()
            a = m.addAction(icone("object-locked"), _("Lecture seule (toutes les fiches du thème)"),
                            lambda: self.basculer_lecture_seule(th))
            a.setCheckable(True)
            a.setChecked(self.store.theme_lecture_seule(th))
            m.addAction(icone("edit-rename"), _("Renommer…"), self.renommer_theme)
            m.addAction(icone("document-export"), _("Exporter le thème (.zip)…"), self.exporter_theme)
            m.addAction(icone("text-html"), _("Exporter le thème en site HTML…"), self.exporter_theme_html)
            m.addAction(icone("application-pdf"), _("Exporter le thème en un seul PDF…"), self.exporter_theme_pdf)
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

    def _icone_fiche(self, t, f):
        """(icône, raison) d'une fiche dans la liste : type, punaise si épinglée, pastille rouge s'il y a quelque chose à faire."""
        nom_icone = "object-locked" if f.verrou else types_fiche.icone_de(f.texte)
        epingle = self.store.fiche_epinglee(t, f)
        raison = None if f.verrou else types_fiche.a_faire_de(f.texte)
        if raison:
            return avec_pastille(nom_icone, epingle), raison
        return (avec_epingle(nom_icone) if epingle else (icone(nom_icone) if nom_icone else QIcon_vide())), None

    def maj_pastilles(self):
        """Remet à jour les seules icônes de la liste (le temps passe : une échéance arrive, un rappel tombe) sans la reconstruire."""
        for row, (t, f) in enumerate(self.rows):
            it = self.liste.item(row)
            if it is not None:
                ic, raison = self._icone_fiche(t, f)
                it.setIcon(ic)
                it.setToolTip(raison or "")

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
            ic, raison = self._icone_fiche(t, f)
            it = QListWidgetItem(ic, self._libelle(t, f, self.theme == self.TOUS or q))
            it.setToolTip(raison or "")
            it.setData(Qt.ItemDataRole.UserRole, f.path.name)
            self.liste.addItem(it)
            if f is self.fiche:
                sel = len(self.rows)
            self.rows.append((t, f))
        self.liste.blockSignals(False)
        # glisser-déposer : seulement dans la vue d'un thème (l'ordre est propre à chaque thème), jamais pendant une recherche
        self.liste.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove if self._ordre_fiches_possible()
                                   else QAbstractItemView.DragDropMode.DragOnly)       # déposer sur un thème reste possible
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

    def chercher_remplacer(self):
        """Ctrl+H : chercher / remplacer dans le texte de la fiche affichée (si elle est modifiable)."""
        if self.texte.isEnabled() and self.pile.currentWidget() is self.texte:
            self.barre_remplacer.ouvrir()

    def _etat_editeur(self, actif):
        if not actif and hasattr(self, "barre_remplacer"):
            self.barre_remplacer.setVisible(False)
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
        ty = types_fiche.type_de(f.texte) if f and not ferme else None
        self._mode_vue(self.vues_types.get(ty.nom) if ty else None)
        self._maj_lecture_seule(a_l_ouverture=True)
        self.texte.document().clearUndoRedoStacks()
        self.chargement = False
        self._maj_boutons()
        if f is not None:
            self.plugins.emettre("fiche_ouverte", fiche=FicheVue(t, f))

    def _maj_lecture_seule(self, a_l_ouverture: bool = False):
        """Fiche (ou thème) en lecture seule : le texte et le titre ne se modifient plus (même par les boutons de mise en forme,
        le collage ou les extensions) ; à l'ouverture, la fiche s'affiche en aperçu. Les fiches typées (tableaux…) gardent leur vue."""
        f, t = self.fiche, self.fiche_theme
        ro = bool(f and not f.fermee and self.store.fiche_lecture_seule(t, f))
        self.texte.setReadOnly(ro)
        self.titre.setReadOnly(ro)
        self.format.lecture_seule = ro
        apercu = self.format.b_apercu.isChecked()
        for b in self.format.boutons:
            b.setEnabled(not ro and not apercu)
        if ro:
            self._statut("🔒 " + _("Lecture seule") + f"  ·  {t.nom}/{f.path.name}", ORANGE)
            if a_l_ouverture and self.pile.currentWidget() is self.texte and self.format.b_apercu.isEnabled():
                self.format.b_apercu.setChecked(True)

    def basculer_lecture_seule(self, t, f=None):
        """Active ou désactive la lecture seule d'une fiche (`f`) ou de tout un thème (f=None)."""
        if f is None:
            self.store.lecture_seule_theme(t, not self.store.theme_lecture_seule(t))
        else:
            self.store.lecture_seule_fiche(t, f, not self.store.fiche_lecture_seule_propre(t, f))
        if self.fiche is not None and (f is self.fiche or (f is None and t is self.fiche_theme)):
            self._maj_lecture_seule(a_l_ouverture=True)
            if not self.store.fiche_lecture_seule(self.fiche_theme, self.fiche):
                self._statut(_("Lecture seule retirée") + f"  ·  {self.fiche_theme.nom}/{self.fiche.path.name}", VERT)

    def ajouter_vue_type(self, nom: str, vue) -> None:
        """Enregistre la vue d'un type de fiche (voir core/types_fiche.py). Une vue est un widget qui a :
        `charger(texte)`, le signal `modifie(str)` (le nouveau texte de la fiche, enregistré comme une frappe) et l'attribut `actif`
        (faux : la fiche est d'un type exécutable et n'est pas validée ; la vue ne doit alors RIEN lancer)."""
        vue.actif = True
        self.vues_types[nom] = vue
        vue.modifie.connect(self._vue_type_modifiee)
        vue.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)         # clic droit hors des listes : menu propre au type
        vue.customContextMenuRequested.connect(lambda pos, n=nom: self._menu_vue_type(n, pos))
        self.pile.addWidget(vue)

    def retirer_vue_type(self, nom: str) -> None:
        vue = self.vues_types.pop(nom, None)
        if vue is None:
            return
        if self.pile.currentWidget() is vue:
            self._mode_vue(None)
        self.pile.removeWidget(vue)
        vue.deleteLater()

    def _mode_vue(self, vue):
        """Une fiche typée montre la vue de son type à la place de l'éditeur de texte (le texte reste dans `self.texte`)."""
        if vue is not None:
            if self.format.b_apercu.isChecked():
                self.format.b_apercu.setChecked(False)
            vue.actif = self.store.fiche_active(self.fiche_theme, self.fiche)
            vue.charger(self.texte.toPlainText())
            self.pile.setCurrentWidget(vue)
        elif self.pile.currentWidget() in self.vues_types.values():
            self.pile.setCurrentWidget(self.texte)
        self.format.setVisible(vue is None)
        self.format.b_apercu.setEnabled(vue is None)
        self.bandeau_validation.setVisible(vue is not None and not vue.actif)
        if vue is not None:
            self.bande.setVisible(False)             # (sinon la bande se montre ou se cache selon les images, voir `bande.charger`)

    def _vue_type_modifiee(self, texte: str):
        if self.fiche is not None and not self.fiche.fermee:
            self._validation_en_attente = True       # modifiée ICI par l'utilisateur : elle sera validée une fois enregistrée
            self.texte.setPlainText(texte)           # déclenche l'enregistrement automatique comme une frappe

    def valider_fiche_courante(self):
        f, t = self.fiche, self.fiche_theme
        if f is None or f.fermee:
            return
        self.sauver()
        self.store.valider_fiche(t, f)
        self._mode_vue(self.vues_types.get((types_fiche.type_de(f.texte) or repertoire.TYPE).nom))
        self._statut(_("✔ Fiche validée : elle peut maintenant agir") + f"  ·  {t.nom}/{f.path.name}", VERT)
        self.plugins.emettre("fiche_validee", fiche=FicheVue(t, f))

    def _texte_repertoire_importe(self, dossier: bool):
        """Texte d'un répertoire dont les colonnes viennent du fichier (CSV ou vCard) ou du dossier de contacts choisi ; None si annulé."""
        kde = Path.home() / ".local/share/kpeoplevcard"
        depart = str(kde if kde.is_dir() else Path.home())
        try:
            if dossier:
                d = QFileDialog.getExistingDirectory(self, _("Dossier de contacts"), depart)
                chemins = sorted(Path(d).rglob("*.vcf"))[:5000] if d else []
            else:
                choisis, _f = QFileDialog.getOpenFileNames(self, _("Importer"), depart, _("Contacts et tableaux (*.vcf *.csv *.txt);;Tous (*)"))
                chemins = [Path(c) for c in choisis]
            fichiers = [c.read_bytes() for c in chemins]
        except OSError as ex:
            QMessageBox.critical(self, _("Importer"), _("Lecture impossible : %s") % ex)
            return None
        if not fichiers:
            return None
        t = repertoire.Tableau.depuis_fichiers(fichiers)
        if not t.lignes:
            QMessageBox.information(self, _("Importer"), _("Rien à importer dans ces fichiers."))
            return None
        return t.en_texte()

    def nouveau_repertoire(self):
        """Crée une fiche répertoire dans le thème courant, à partir d'un modèle de colonnes (modifiables ensuite)."""
        modeles = [_(m[0]) for m in repertoire.MODELES]
        depuis_fichier, depuis_dossier = _("Depuis un fichier (CSV, vCard) : les colonnes s'adaptent…"), _("Depuis un dossier de contacts (KDE Connect…) : les colonnes s'adaptent…")
        choix, ok = QInputDialog.getItem(self, _("Nouveau répertoire"), _("Modèle de colonnes (modifiables ensuite) :"),
                                         modeles + [depuis_fichier, depuis_dossier], 0, False)
        if not ok:
            return
        texte_initial = None
        if choix in (depuis_fichier, depuis_dossier):
            texte_initial = self._texte_repertoire_importe(choix == depuis_dossier)
            if texte_initial is None:
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
        self.store.enregistrer(t, f, titre.strip(), texte_initial if texte_initial is not None else repertoire.texte_modele(modeles.index(choix)))
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

    def _ouvrir_theme_doc(self, nom, icone, fiches):
        """Crée (ou rouvre, sans rien écraser) un thème de documentation ; les fiches absentes sont ajoutées."""
        self.sauver()
        th = next((t for t in self.store.themes if t.nom == nom), None)
        if th is None:
            th = self.store.nouveau_theme(nom)
            self.store.icone_theme(th, icone)
        titres = {f.titre for f in th.fiches}
        premiere = None
        for titre, texte in fiches:
            if titre not in titres:
                f = self.store.nouvelle_fiche(th)
                self.store.enregistrer(th, f, titre, texte)
            if premiere is None:
                premiere = next(x for x in th.fiches if x.titre == titre)
        self.quitter_fiche()
        self.maj_themes()
        self.montrer(theme=th.nom)
        self.selectionner_fiche(FicheVue(th, premiere))

    def doc_extensions(self):
        """Thème « Doc » : comment écrire une extension."""
        self._ouvrir_theme_doc(doc_extensions.nom_theme(), doc_extensions.icone(),
                               doc_extensions.fiches(self.store.paths.base / "plugins"))

    def guide(self):
        """Thème « Guide » : présentation de Scrinium."""
        fiches = guide.fiches(self.store.paths.fiches) + guide.fiches_extensions(self.plugins.docs())
        self._ouvrir_theme_doc(guide.nom_theme(), guide.icone(), fiches)

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

    def _octets_piece(self, numero: int):
        """Octets de la pièce n° `numero` de la fiche affichée (pour ![](pj:N) dans l'aperçu), None si absente ou fermée."""
        f = self.fiche
        if f is None or f.fermee:
            return None
        for p in self.store.lister_pieces(f):
            if p.id == numero:
                return self.store.lire_piece(f, p)
        return None

    def inserer_piece(self, piece) -> None:
        """Écrit `![légende](pj:N)` dans le texte, à part, à la position du curseur."""
        if self.fiche is None or self.fiche.fermee or self.texte.isReadOnly() or self.format.lecture_seule:
            return
        if self.pile.currentWidget() is not self.texte:
            self.format.b_apercu.setChecked(False)
        c = self.texte.textCursor()
        legende = Path(piece.nom).stem
        avant = "" if c.atBlockStart() and c.block().text() == "" else "\n\n"
        c.insertText(f"{avant}{images_texte.reference(piece.id, legende)}\n\n")
        self.texte.setTextCursor(c)
        self.texte.setFocus()

    def inserer_image(self) -> None:
        """Bouton 🖼 : choisir une pièce déjà jointe, ou une nouvelle image (fichier) qui est jointe puis insérée."""
        if self.fiche is None or self.fiche.fermee or self.format.lecture_seule:
            return
        m = QMenu(self)
        pieces = self.store.lister_pieces(self.fiche)
        for p in pieces:
            m.addAction(p.nom, lambda p=p: self.inserer_piece(p))
        if pieces:
            m.addSeparator()
        m.addAction(_("Nouvelle image depuis un fichier…"), self._inserer_nouvelle)
        m.exec(QCursor.pos())

    def _inserer_nouvelle(self) -> None:
        avant = len(self.bande.pieces)
        chemins, _f = QFileDialog.getOpenFileNames(self, _("Ajouter une image"), "", images.FILTRE)
        if chemins:
            self.bande.ajouter([Path(c) for c in chemins])
            for p in self.bande.pieces[avant:]:
                self.inserer_piece(p)

    def pieces_modifiees(self):
        """Appelé par la bande après un ajout ou une suppression d'image."""
        f, t = self.fiche, self.fiche_theme
        if f is not None:
            self._statut(f"{_('✔ Images mises à jour')} ({time.strftime('%H:%M:%S')})  ·  {t.nom}/{f.path.name}", VERT)

    def nouvelle_fiche(self, type_nom: str | None = None):
        """Crée une fiche dans le thème courant : ordinaire, ou d'un type enregistré (`type_nom`, voir core/types_fiche.py). Une fiche
        neuve d'un type exécutable est vide : l'utilisateur vient de la créer, elle est validée d'emblée."""
        type_fiche = next((t for t in types_fiche.types() if t.nom == type_nom), None) if type_nom else None
        self.quitter_fiche()
        t = self._theme_courant() or (self.store.themes[0] if self.store.themes else None)
        if t is None:
            self.nouveau_theme()
            t = self._theme_courant()
            if t is None:
                return
        f = self.store.nouvelle_fiche(t)
        if type_fiche is not None:
            self.store.enregistrer(t, f, _(type_fiche.libelle), type_fiche.texte_neuf())
            if type_fiche.executable:
                self.store.valider_fiche(t, f)
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

    def _remplir_menu_nouvelle(self):
        """Fiche ordinaire, puis un type de fiche par entrée (répertoire, agenda, applications, actions CLI… selon les extensions actives)."""
        m = self.menu_nouvelle
        m.clear()
        m.addAction(icone("document-new"), _("Fiche ordinaire"), lambda *_a: self.nouvelle_fiche())
        m.addSeparator()
        for t in types_fiche.types():
            if t.nom == repertoire.TYPE.nom:
                m.addAction(icone(t.icone or "view-pim-notes"), _(t.libelle) + "…", self.nouveau_repertoire)     # il demande son modèle de colonnes
            else:
                m.addAction(icone(t.icone or "view-pim-notes"), _(t.libelle), lambda *_a, n=t.nom: self.nouvelle_fiche(n))

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
            self.maj_pastilles()
        else:
            self._statut(f"{_('✔ Enregistré')}  ·  {t.nom}/{f.path.name}", VERT)
        if self._validation_en_attente:
            self._validation_en_attente = False
            ty = types_fiche.type_de(f.texte)
            if ty is not None and ty.executable:
                self.store.valider_fiche(t, f)       # texte écrit dans l'application par l'utilisateur : validé tel quel
                self.plugins.emettre("fiche_validee", fiche=FicheVue(t, f))

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

    def _aller_a(self, t, f):
        """Affiche la fiche (t, f) : change de thème et vide la recherche si elle n'est pas dans la liste."""
        self.quitter_fiche()
        if self.recherche.text():
            self.recherche.blockSignals(True)
            self.recherche.clear()
            self.recherche.blockSignals(False)
        if self.theme not in (self.TOUS, t.nom):
            self.theme = t.nom
            self.maj_themes()
        self.maj_fiches()
        self.selectionner_fiche(FicheVue(t, f))

    def ouvrir_fiche_liee(self, cible: str):
        """Clic sur un lien [[fiche]] de l'aperçu : ouvre la fiche, ou propose de la créer si elle n'existe pas encore."""
        r = liens_fiches.resoudre(self.store, cible)
        if r is None:
            titre = cible.partition("/")[2].strip() if "/" in cible and any(x.nom.casefold() == cible.partition("/")[0].strip().casefold()
                                                                           for x in self.store.themes) else cible
            t = self.fiche_theme or self._theme_courant()
            if t is None or QMessageBox.question(self, _("Lien vers une fiche"),
                                                 _("Aucune fiche ne s'appelle « %s ». La créer dans le thème « %s » ?") % (titre, t.nom)) \
                    != QMessageBox.StandardButton.Yes:
                return
            f = self.store.nouvelle_fiche(t)
            self.store.enregistrer(t, f, titre, "")
            r = (t, f)
        self._aller_a(*r)

    def fiches_liees(self):
        """Fiches vers lesquelles pointe la fiche courante (→) et fiches qui pointent vers elle (←) ; un choix ouvre la fiche."""
        f, t = self.fiche, self.fiche_theme
        if f is None:
            return
        entrees = [("→ ", x) for x in liens_fiches.liens_de(self.store, t, f)] + \
                  [("← ", x) for x in liens_fiches.retroliens(self.store, t, f)]
        if not entrees:
            QMessageBox.information(self, _("Fiches liées"), _("Aucun lien avec cette fiche. Écrivez [[Titre d'une fiche]] dans le texte pour en créer un."))
            return
        noms = [f"{sens}{th.nom} / {fi.titre}" for sens, (th, fi) in entrees]
        choix, ok = QInputDialog.getItem(self, _("Fiches liées"), _("→ cette fiche pointe vers · ← pointe vers cette fiche"), noms, 0, False)
        if ok:
            self._aller_a(*entrees[noms.index(choix)][1])

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
        if self.isMinimized():                  # on enlève seulement « réduite » : une fenêtre maximisée le reste
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)
        self.show()                             # sans effet si elle est déjà affichée (showNormal() la sortait du plein écran)
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

    def _entrees_clic_droit(self, type_nom: str | None = None) -> list:
        """Entrées du clic droit dans une fiche, selon son type : pour un texte ordinaire, copier la note puis les entrées des extensions
        (envoyer, partager, lire, traduire…) ; pour une fiche typée, celles des extensions déclarées pour ce type."""
        propres = [(t, fn, ic) for _n, t, fn, ic, types in self.actions_fiche if (types is None and type_nom is None) or
                   (types is not None and type_nom in types)]
        return ([(_("Copier la note"), self.copier_note, "edit-copy")] if type_nom is None else []) + propres

    def _menu_vue_type(self, nom: str, pos):
        """Clic droit sur la vue d'un type de fiche : les actions de ce type, puis l'export PDF."""
        vue = self.vues_types.get(nom)
        if vue is None or not self.fiche or self.fiche.fermee:
            return
        m = QMenu(self)
        propres_vue = getattr(vue, "entrees_menu", None)             # entrées de la vue elle-même (Ajouter, Modifier… selon l'endroit cliqué)
        if propres_vue is not None:
            remplir_menu(m, propres_vue(pos))
            if not m.isEmpty():
                m.addSeparator()
        remplir_menu(m, self._entrees_clic_droit(nom))
        if not m.isEmpty():
            m.addSeparator()
        m.addAction(icone("document-print"), _("Imprimer…"), self.imprimer_fiche)
        m.addAction(icone("document-save"), _("Exporter la fiche en PDF…"), self.exporter_pdf)
        m.addAction(icone("document-export"), _("Exporter la fiche en Markdown…"), self.exporter_markdown)
        m.exec(vue.mapToGlobal(pos))
        m.deleteLater()

    def _contenu_a_sortir(self, titre_dialogue: str, support: str):
        """(fiche, titre, texte, images) de la fiche affichée, prêts pour un PDF ou une impression ; None si rien à sortir ou si
        l'utilisateur renonce (fiche verrouillée : le support contiendra son contenu EN CLAIR)."""
        f = self.fiche
        if not f or f.fermee:
            return None
        if f.verrou and QMessageBox.question(
                self, titre_dialogue,
                _("Cette fiche est verrouillée : %s contiendra son texte et ses images EN CLAIR. Continuer ?") % support
        ) != QMessageBox.StandardButton.Yes:
            return None
        self.sauver()
        donnees_pieces = []
        for p in self.store.lister_pieces(f):
            try:
                donnees_pieces.append((p.nom, self.store.lire_piece(f, p), p.id))
            except (ValueError, OSError):
                continue
        texte = types_fiche.en_markdown(self.texte.toPlainText())      # un répertoire s'imprime en tableaux, une section par lettre
        return f, self.titre.text(), texte, donnees_pieces

    def exporter_markdown(self, chemin: str | None = None, simple: bool = False):
        """Exporte la fiche affichée en fichier Markdown (+ dossier « <nom>_images » pour ses images). `chemin` : sans boîte de dialogue (tests).
        `simple` : pour un autre outil (tableaux en Markdown, sans la marque de type de Scrinium)."""
        f = self.fiche
        if not f or f.fermee:
            QMessageBox.information(self, _("Exporter en Markdown"), _("Ouvrez d'abord une fiche (déverrouillée) à exporter."))
            return
        if chemin is None and f.verrou and QMessageBox.question(
                self, _("Exporter en Markdown"),
                _("Cette fiche est verrouillée : le fichier contiendra son texte et ses images EN CLAIR. Continuer ?")
        ) != QMessageBox.StandardButton.Yes:
            return
        self.sauver()
        if chemin is None:
            base = propre(self.titre.text() or f.titre or "fiche")
            chemin, _f = QFileDialog.getSaveFileName(self, _("Exporter en Markdown"), str(Path.home() / f"{base}.md"),
                                                     _("Markdown (*.md)"))
            if not chemin:
                return
        chemin = Path(chemin)
        if chemin.suffix.lower() != ".md":
            chemin = chemin.with_name(chemin.name + ".md")
        try:
            n = echange_md.exporter(self.store, f, chemin, self.titre.text(), self.texte.toPlainText(), simple)
        except (OSError, ValueError) as ex:
            QMessageBox.critical(self, _("Exporter en Markdown"), _("Écriture impossible : %s") % ex)
            return
        self._statut(_("✔ Fiche exportée") + f"  ·  {chemin}" + (f"  (+ {n} " + _("image(s)") + ")" if n else ""), VERT)

    def importer_markdown(self, chemins: list | None = None):
        """Crée une fiche par fichier Markdown choisi, dans le thème courant ; les images locales qu'il cite sont jointes."""
        from .images import preparer
        if chemins is None:
            choisis, _f = QFileDialog.getOpenFileNames(self, _("Importer des fichiers Markdown"), str(Path.home()),
                                                       _("Markdown et texte (*.md *.markdown *.txt);;Tous (*)"))
            chemins = [Path(c) for c in choisis]
        if not chemins:
            return
        self.quitter_fiche()
        t = self._theme_courant() or (self.store.themes[0] if self.store.themes else None)
        if t is None:
            self.nouveau_theme()
            t = self._theme_courant()
            if t is None:
                return
        derniere, nb, images, problemes = None, 0, 0, []
        for c in chemins:
            try:
                f, n, ignorees = echange_md.importer(self.store, t, Path(c), preparer)
            except (OSError, ValueError) as ex:
                problemes.append(f"{Path(c).name} : {ex}")
                continue
            derniere, nb, images = f, nb + 1, images + n
            problemes += [f"{Path(c).name} → {x}" for x in ignorees]
        if derniere is not None:
            if self.theme not in (self.TOUS, t.nom):
                self.theme = t.nom
            self.recherche.blockSignals(True)
            self.recherche.clear()
            self.recherche.blockSignals(False)
            self.maj_themes()
            self.maj_fiches()
            self._afficher(t, derniere)
            self._statut(_("✔ Fiches importées : %d") % nb + (f"  ·  {images} " + _("image(s)") if images else ""), VERT)
        if problemes:
            QMessageBox.warning(self, _("Importer des fichiers Markdown"),
                                _("Certains éléments n'ont pas été importés :") + "\n\n" + "\n".join(problemes[:15]))

    def _options_export_theme(self, t):
        """Boîte « options d'export » d'un thème : (simple, en_clair) ou None si annulé."""
        ouvertes = [f for f in t.fiches if f.verrou and not f.fermee]
        d = QDialog(self)
        d.setWindowTitle(_("Exporter le thème"))
        lay = QVBoxLayout(d)
        c_simple = QCheckBox(_("Markdown simple, pour un autre outil que Scrinium (sans les marques de type des fiches)"))
        lay.addWidget(c_simple)
        c_clair = None
        if ouvertes:
            c_clair = QCheckBox(_("Inclure EN CLAIR les fiches verrouillées actuellement ouvertes (%d) ; les autres restent chiffrées") % len(ouvertes))
            lay.addWidget(c_clair)
        lay.addWidget(QLabel(_("Sinon, les fiches verrouillées sont copiées chiffrées, telles quelles.")))
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        lay.addWidget(bb)
        if d.exec() != QDialog.DialogCode.Accepted:
            return None
        return c_simple.isChecked(), bool(c_clair and c_clair.isChecked())

    @staticmethod
    def _deposes(src) -> tuple[list, list]:
        """(fichiers Markdown, archives de thème) déposés depuis un gestionnaire de fichiers."""
        chemins = [Path(u.toLocalFile()) for u in src.urls() if u.isLocalFile()]
        return ([c for c in chemins if c.suffix.lower() in (".md", ".markdown")], [c for c in chemins if c.suffix.lower() == ".zip"])

    def dragEnterEvent(self, ev):
        if any(self._deposes(ev.mimeData())):
            ev.acceptProposedAction()

    def dragMoveEvent(self, ev):
        if any(self._deposes(ev.mimeData())):
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        mds, zips = self._deposes(ev.mimeData())
        if mds or zips:
            ev.acceptProposedAction()
            QTimer.singleShot(0, lambda: self._importer_deposes(mds, zips))     # après la fin du glisser (des boîtes de dialogue peuvent s'ouvrir)

    def _importer_deposes(self, mds: list, zips: list):
        if mds:
            self.importer_markdown(mds)
        for z in zips:
            self.importer_theme(str(z))

    def exporter_theme(self, chemin: str | None = None, simple: bool = False, en_clair: bool = False):
        """Exporte le thème courant en archive zip (fiches en Markdown, images ; fiches verrouillées copiées chiffrées)."""
        t = self._theme_courant()
        if t is None:
            QMessageBox.information(self, _("Exporter le thème"), _("Choisissez d'abord un thème (pas « Toutes les fiches »)."))
            return
        self.sauver()
        if chemin is None:
            options = self._options_export_theme(t)
            if options is None:
                return
            simple, en_clair = options
            chemin, _f = QFileDialog.getSaveFileName(self, _("Exporter le thème"), str(Path.home() / f"{propre(t.nom, 'theme')}.zip"),
                                                     _("Archive (*.zip)"))
            if not chemin:
                return
        chemin = Path(chemin)
        if chemin.suffix.lower() != ".zip":
            chemin = chemin.with_name(chemin.name + ".zip")
        try:
            r = echange_theme.exporter(self.store, t, chemin, simple, en_clair)
        except (OSError, ValueError) as ex:
            QMessageBox.critical(self, _("Exporter le thème"), _("Écriture impossible : %s") % ex)
            return
        self._statut(_("✔ Thème exporté : %d fiche(s), dont %d verrouillée(s) (chiffrées)") % (r["fiches"] + r["verrouillees"], r["verrouillees"])
                     + f"  ·  {chemin}", VERT)

    def _rapport_doc(self, r: dict, cible) -> None:
        msg = _("✔ Thème exporté : %d fiche(s)") % r["fiches"]
        if r["ignorees"]:
            msg += "  ·  " + _("%d fiche(s) verrouillée(s) ignorée(s)") % r["ignorees"]
        self._statut(msg + f"  ·  {cible}", VERT)

    def exporter_theme_html(self, dossier: str | None = None):
        """Exporte le thème courant en site HTML (un dossier : index.html, une page par fiche, images/)."""
        t = self._theme_courant()
        if t is None:
            QMessageBox.information(self, _("Exporter le thème"), _("Choisissez d'abord un thème (pas « Toutes les fiches »)."))
            return
        self.sauver()
        if dossier is None:
            dossier = QFileDialog.getExistingDirectory(self, _("Dossier du site (un sous-dossier y sera créé)"), str(Path.home()))
            if not dossier:
                return
            dossier = str(Path(dossier) / propre(t.nom, "theme"))
        try:
            r = export_theme_doc.exporter_html(self.store, t, Path(dossier))
        except (OSError, ValueError) as ex:
            QMessageBox.critical(self, _("Exporter le thème"), _("Écriture impossible : %s") % ex)
            return
        self._rapport_doc(r, dossier)

    def exporter_theme_pdf(self, chemin: str | None = None):
        """Exporte le thème courant en un seul PDF (sommaire, puis chaque fiche)."""
        t = self._theme_courant()
        if t is None:
            QMessageBox.information(self, _("Exporter le thème"), _("Choisissez d'abord un thème (pas « Toutes les fiches »)."))
            return
        self.sauver()
        if chemin is None:
            chemin, _f = QFileDialog.getSaveFileName(self, _("Exporter le thème en PDF"), str(Path.home() / f"{propre(t.nom, 'theme')}.pdf"),
                                                     _("Documents PDF (*.pdf)"))
            if not chemin:
                return
        if not str(chemin).lower().endswith(".pdf"):
            chemin = f"{chemin}.pdf"
        try:
            r = export_theme_doc.exporter_pdf(self.store, t, Path(chemin))
        except OSError as ex:
            QMessageBox.critical(self, _("Exporter le thème"), _("Écriture impossible : %s") % ex)
            return
        self._rapport_doc(r, chemin)

    def importer_theme(self, chemin: str | None = None):
        """Crée un NOUVEAU thème à partir d'une archive exportée par Scrinium (jamais de fusion avec un thème existant)."""
        from .images import preparer
        if chemin is None:
            chemin, _f = QFileDialog.getOpenFileName(self, _("Importer un thème"), str(Path.home()), _("Archive (*.zip)"))
            if not chemin:
                return
        self.quitter_fiche()
        try:
            t, r = echange_theme.importer(self.store, Path(chemin), preparer)
        except (OSError, ValueError) as ex:
            QMessageBox.critical(self, _("Importer un thème"), _("Import impossible : %s") % ex)
            return
        self.plugins.emettre("themes_modifies")
        self.theme = t.nom
        self.maj_themes()
        self.maj_fiches()
        self._statut(_("✔ Thème importé : « %s » (%d fiche(s), dont %d verrouillée(s))") % (t.nom, r["fiches"] + r["verrouillees"], r["verrouillees"]), VERT)
        if r["ignores"]:
            QMessageBox.warning(self, _("Importer un thème"),
                                _("Certains éléments n'ont pas été importés :") + "\n\n" + "\n".join(r["ignores"][:15]))

    def imprimer_fiche(self, imprimante=None):
        """Imprime la fiche affichée (boîte d'impression du système). `imprimante` : un QPrinter déjà réglé (tests, PDF)."""
        sortie = self._contenu_a_sortir(_("Imprimer"), _("l'impression"))
        if sortie is None:
            return
        _f, titre, texte, images = sortie
        if imprimante is None:
            imprimante = QPrinter(QPrinter.PrinterMode.HighResolution)
            if QPrintDialog(imprimante, self).exec() != QDialog.DialogCode.Accepted:
                return
        export_pdf.imprimer(imprimante, titre, texte, images)
        self._statut(_("✔ Fiche envoyée à l'impression"), VERT)

    def exporter_pdf(self):
        """Clic droit sur le contenu : écrit la fiche (titre, texte, images) dans un fichier PDF choisi par l'utilisateur."""
        f = self.fiche
        if not f or f.fermee:
            return
        sortie = self._contenu_a_sortir(_("Exporter en PDF"), _("le PDF"))
        if sortie is None:
            return
        _f, titre, texte, images = sortie
        base = propre(f.titre or _("fiche"), "fiche")
        chemin, _filtre = QFileDialog.getSaveFileName(self, _("Exporter en PDF"), str(Path.home() / f"{base}.pdf"),
                                                      _("Documents PDF (*.pdf)"))
        if not chemin:
            return
        if not chemin.lower().endswith(".pdf"):
            chemin += ".pdf"
        try:
            export_pdf.ecrire_pdf(chemin, titre, texte, images)
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

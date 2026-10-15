"""Fenêtre principale (PyQt6)."""
import time

from PyQt6.QtCore import QSize, Qt, QTimer
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSplitter,
                             QToolBar, QVBoxLayout, QWidget)

from .. import __version__
from ..core import crypto
from ..core.store import ICONE_DEFAUT, Store, propre
from ..i18n import _
from .assistant import AssistantCle
from .icons import icone, icone_appli

ORANGE, VERT, GRIS = "#c77700", "#2e8b3a", "gray"


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
        self.timer = QTimer(self, singleShot=True, interval=700)
        self.timer.timeout.connect(self.sauver)
        self.setWindowTitle(_("Scrinium"))
        self.setWindowIcon(icone_appli())
        self.resize(900, 540)
        store.charger()
        self._ui()
        if theme:
            self.theme = next((t.nom for t in store.themes if t.nom.lower() == theme.lower()), self.TOUS)
        self.maj_themes()
        self.maj_fiches()
        if nouvelle:
            self.nouvelle_fiche()
        if not store.a_cle_de_secours and not store.reglages().get("recovery_asked"):
            QTimer.singleShot(0, lambda: AssistantCle(store, self).exec())

    # ---------- construction ----------
    def _action(self, texte, ic, slot, raccourci=None):
        a = QAction(icone(ic), texte, self)
        a.triggered.connect(lambda *_: slot())
        if raccourci:
            a.setShortcut(QKeySequence(raccourci))
        return a

    def _ui(self):
        tb = QToolBar(_("Actions"))
        tb.setMovable(False)
        tb.setIconSize(QSize(22, 22))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(tb)
        self.a_fiche = self._action(_("Fiche"), "document-new", self.nouvelle_fiche, "Ctrl+N")
        self.a_fiche.setToolTip(_("Nouvelle fiche (Ctrl+N)"))
        self.a_theme = self._action(_("Thème"), "folder-new", self.nouveau_theme)
        self.a_theme.setToolTip(_("Nouveau thème"))
        tb.addAction(self.a_fiche)
        tb.addAction(self.a_theme)
        self.recherche = QLineEdit()
        self.recherche.setPlaceholderText(_("Chercher (Ctrl+F)…"))
        self.recherche.setClearButtonEnabled(True)
        self.recherche.addAction(icone("edit-find"), QLineEdit.ActionPosition.LeadingPosition)
        self.recherche.textChanged.connect(lambda *_: self.maj_fiches())
        tb.addWidget(self.recherche)

        m = self.menuBar()
        mf = m.addMenu(_("&Fichier"))
        mf.addAction(self.a_fiche)
        mf.addAction(self.a_theme)
        mf.addSeparator()
        mf.addAction(self._action(_("Quitter"), "application-exit", self.close, "Ctrl+Q"))
        ms = m.addMenu(_("&Sécurité"))
        ms.addAction(self._action(_("Clé de secours…"), "object-locked", self.assistant_cle))
        ms.addAction(self._action(_("Rouvrir une fiche avec la clé de secours…"), "object-unlocked", self.secours))
        mh = m.addMenu(_("&Aide"))
        mh.addAction(self._action(_("À propos"), "help-about", self.a_propos))

        self.liste_themes = QListWidget()
        self.liste_themes.setIconSize(QSize(20, 20))
        self.liste_themes.currentRowChanged.connect(self._sel_theme)
        self.liste_themes.itemDoubleClicked.connect(lambda *_: self.renommer_theme())
        self.liste_themes.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.liste_themes.customContextMenuRequested.connect(self._menu_theme)
        bt = QHBoxLayout()
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

        self.liste = QListWidget()
        self.liste.setIconSize(QSize(16, 16))
        self.liste.currentRowChanged.connect(self._sel_fiche)
        self.liste.itemDoubleClicked.connect(lambda *_: self._double_clic())
        b_sup = QPushButton(icone("edit-delete"), _("Supprimer la fiche"))
        b_sup.clicked.connect(self.supprimer_fiche)
        milieu = QWidget()
        lm = QVBoxLayout(milieu)
        lm.setContentsMargins(0, 0, 0, 0)
        lm.addWidget(self.liste)
        lm.addWidget(b_sup)

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
        ligne = QHBoxLayout()
        ligne.addWidget(self.titre, 1)
        ligne.addWidget(self.b_copier)
        ligne.addWidget(self.b_verrou)
        self.texte = QPlainTextEdit()
        self.texte.setPlaceholderText(_("Note"))
        self.statut = QLabel("")
        droite = QWidget()
        ld = QVBoxLayout(droite)
        ld.setContentsMargins(0, 0, 0, 0)
        ld.addLayout(ligne)
        ld.addWidget(self.texte, 1)
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
        for seq, slot in (("Ctrl+S", self._forcer), ("Ctrl+F", lambda: self.recherche.setFocus())):
            a = QAction(self)
            a.setShortcut(QKeySequence(seq))
            a.triggered.connect(slot)
            self.addAction(a)
        self._etat_editeur(False)

    # ---------- thèmes ----------
    def _noms(self):
        return [self.TOUS] + [t.nom for t in self.store.themes]

    def maj_themes(self):
        self.liste_themes.blockSignals(True)
        self.liste_themes.clear()
        it = QListWidgetItem(icone(ICONE_DEFAUT), self.TOUS)
        self.liste_themes.addItem(it)
        for t in self.store.themes:
            self.liste_themes.addItem(QListWidgetItem(icone(t.icone), f"{t.nom}  ({len(t.fiches)})"))
        if self.theme not in self._noms():
            self.theme = self.TOUS
        self.liste_themes.setCurrentRow(self._noms().index(self.theme))
        self.liste_themes.blockSignals(False)

    def _theme_courant(self):
        return self.store.theme(self.theme)

    def _sel_theme(self, row):
        if row < 0:
            return
        self.quitter_fiche()
        self.theme = self._noms()[row]
        self.maj_fiches()

    def _menu_theme(self, pos):
        if not self._theme_courant():
            return
        m = QMenu(self)
        m.addAction(icone("edit-rename"), _("Renommer…"), self.renommer_theme)
        m.addAction(icone("view-pim-notes"), _("Icône…"), self.icone_theme)
        m.addAction(icone("edit-delete"), _("Supprimer…"), self.supprimer_theme)
        m.exec(self.liste_themes.mapToGlobal(pos))

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
        self.theme = t.nom
        self.maj_themes()
        self.maj_fiches()

    def icone_theme(self):
        t = self._theme_courant()
        if not t:
            return
        n, ok = QInputDialog.getText(
            self, _("Icône du thème"),
            _("Nom d'icône du thème d'icônes du système, ex : folder-documents, phone, network-wired, "
              "applications-development, view-pim-notes :"), text=t.icone)
        if ok and n.strip():
            self.store.icone_theme(t, n)
            self.maj_themes()

    def supprimer_theme(self):
        t = self._theme_courant()
        if not t:
            return
        if QMessageBox.question(
                self, _("Supprimer le thème"),
                _("Mettre « %s » et ses %d fiche(s) à la corbeille ?\n(%s)") % (t.nom, len(t.fiches), self.store.paths.corbeille)
        ) == QMessageBox.StandardButton.Yes:
            self.fiche = None
            self.store.supprimer_theme(t)
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
        for t in self.store.themes:
            if not q and self.theme != self.TOUS and t.nom != self.theme:
                continue   # une recherche porte sur tous les thèmes
            for f in sorted(t.fiches, key=lambda f: f.titre.lower()):
                if q and q not in f.titre.lower() and q not in (f.texte or "").lower() and q not in t.nom.lower():
                    continue   # fiche verrouillée : pas de recherche dans le contenu
                it = QListWidgetItem(icone("object-locked") if f.verrou else QIcon_vide(), self._libelle(t, f, self.theme == self.TOUS or q))
                self.liste.addItem(it)
                if f is self.fiche:
                    sel = len(self.rows)
                self.rows.append((t, f))
        self.liste.blockSignals(False)
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
        self.texte.document().clearUndoRedoStacks()
        self.chargement = False
        self._maj_boutons()

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
        f, t = self.fiche, self.fiche_theme
        if not f:
            return
        if QMessageBox.question(self, _("Supprimer"),
                                _("Mettre la fiche « %s » à la corbeille ?") % (f.titre or _("(sans titre)"))
                                ) == QMessageBox.StandardButton.Yes:
            self.fiche = None
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
            row = self.liste.currentRow()
            if 0 <= row < len(self.rows):   # libellé à jour sans perdre la sélection
                self.liste.item(row).setText(self._libelle(t, f, self.theme == self.TOUS or self.recherche.text().strip()))
        else:
            self._statut(f"{_('✔ Enregistré')}  ·  {t.nom}/{f.path.name}", VERT)

    def quitter_fiche(self):
        self.sauver()
        if self.fiche and self.store.jeter_si_vide(self.fiche_theme, self.fiche):
            self.fiche = None
            self.maj_themes()

    def closeEvent(self, ev):
        self.quitter_fiche()
        super().closeEvent(ev)

    # ---------- copier / verrou ----------
    def _maj_boutons(self):
        f = self.fiche
        self.b_copier.setEnabled(bool(f and not f.fermee))
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

    def copier_note(self):
        f = self.fiche
        if not f or f.fermee:
            return
        QApplication.clipboard().setText(self.texte.toPlainText())
        self._statut(f"{_('✔ Note copiée dans le presse-papiers')} ({time.strftime('%H:%M:%S')})", VERT)

    def _double_clic(self):
        if self.fiche and self.fiche.fermee:
            self.deverrouiller()

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
        avertissement = (_("Mot de passe oublié : la clé de secours permettra de rouvrir la fiche.")
                         if self.store.a_cle_de_secours else
                         _("ATTENTION : pas de clé de secours (menu Sécurité). Mot de passe oublié = fiche irrécupérable."))
        if QMessageBox.question(self, _("Verrouiller la fiche"),
                                _("Le texte de la fiche sera chiffré avec un mot de passe (le titre reste visible).\n\n")
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
        self.store.verrouiller(t, f, m1)
        self._afficher(t, f)
        self.maj_themes()
        self.maj_fiches()

    def retirer_verrou(self):
        f, t = self.fiche, self.fiche_theme
        if QMessageBox.question(self, _("Retirer le mot de passe"),
                                _("Le texte de la fiche sera de nouveau stocké en clair. Continuer ?")
                                ) != QMessageBox.StandardButton.Yes:
            return
        self.sauver()
        self.store.retirer_verrou(t, f)
        self._afficher(t, f)
        self.maj_themes()
        self.maj_fiches()

    # ---------- sécurité ----------
    def assistant_cle(self):
        if self.store.a_cle_de_secours:
            QMessageBox.information(self, _("Clé de secours"),
                                    _("Une clé de secours est déjà active (%s). Les nouvelles fiches verrouillées l'utilisent.")
                                    % self.store.paths.recovery_pub)
            return
        AssistantCle(self.store, self, premiere_fois=False).exec()

    def secours(self):
        f, t = self.fiche, self.fiche_theme
        if not f or not f.fermee:
            QMessageBox.information(self, _("Clé de secours"), _("Sélectionnez d'abord une fiche verrouillée."))
            return
        chemin, _ok = QFileDialog.getOpenFileName(self, _("Clé privée de secours"), str(self.store.paths.base), "PEM (*.pem);;*")
        if not chemin:
            return
        pem = open(chemin, "rb").read()
        phrase = None
        if b"ENCRYPTED" in pem:
            phrase = self._mdp(_("Clé de secours"), _("Phrase secrète de la clé :"))
            if not phrase:
                return
        try:
            f.texte = self.store.ouvrir_avec_cle_privee(f, pem, phrase)
        except Exception as ex:
            QMessageBox.critical(self, _("Clé de secours"), _("Impossible de rouvrir la fiche : %s") % ex)
            return
        if QMessageBox.question(self, _("Clé de secours"),
                                _("Fiche rouverte. La remettre en clair (retirer le mot de passe) ?")
                                ) == QMessageBox.StandardButton.Yes:
            self.store.retirer_verrou(t, f)
        else:
            f.texte = None   # reste fermée ; rien n'a été écrit
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

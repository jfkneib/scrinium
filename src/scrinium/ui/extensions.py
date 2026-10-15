"""Interface des extensions : ce qu'une extension peut ajouter à la fenêtre, et la boîte de gestion."""
from PyQt6.QtCore import QTimer, QUrl, Qt
from PyQt6.QtGui import QAction, QDesktopServices
from PyQt6.QtWidgets import (QDialog, QDockWidget, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox,
                             QPushButton, QSystemTrayIcon, QVBoxLayout)

from ..i18n import _
from .icons import icone


class UiPlugin:
    """`ctx.ui` d'une extension : tout ce qu'elle ajoute est retiré à sa désactivation."""

    def __init__(self, fenetre, nom: str):
        self._f, self._nom = fenetre, nom
        self._actions, self._docks, self._timers = [], [], []

    def _appeler(self, fn):
        return lambda *_a: self._f.plugins.appeler(self._nom, fn)

    def ajouter_action(self, texte: str, fn, icone_nom: str | None = None) -> QAction:
        """Entrée dans le menu « Extensions »."""
        a = QAction(icone(icone_nom) if icone_nom else icone("view-pim-notes"), texte, self._f)
        a.triggered.connect(self._appeler(fn))
        self._f.menu_ext.addAction(a)
        self._actions.append((self._f.menu_ext, a))
        return a

    def ajouter_bouton(self, texte: str, fn, icone_nom: str | None = None) -> QAction:
        """Bouton dans la barre d'outils."""
        a = QAction(icone(icone_nom) if icone_nom else icone("view-pim-notes"), texte, self._f)
        a.setToolTip(texte)
        a.triggered.connect(self._appeler(fn))
        self._f.barre.addAction(a)
        self._actions.append((self._f.barre, a))
        return a

    def ajouter_panneau(self, titre: str, widget) -> QDockWidget:
        """Panneau ancré sur le côté droit de la fenêtre (widget Qt fourni par l'extension)."""
        d = QDockWidget(titre, self._f)
        d.setWidget(widget)
        self._f.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, d)
        self._docks.append(d)
        return d

    def notifier(self, titre: str, message: str) -> None:
        """Notification du bureau (zone de notification) ; sinon message dans la barre d'état de la fenêtre."""
        if self._f.tray is not None:
            self._f.tray.showMessage(titre, message, QSystemTrayIcon.MessageIcon.Information, 10000)
        else:
            self._f.statusBar().showMessage(f"{titre} : {message}", 15000)

    def planifier(self, secondes: float, fn, repeter: bool = False) -> QTimer:
        t = QTimer(self._f, singleShot=not repeter, interval=int(secondes * 1000))
        t.timeout.connect(lambda: self._f.plugins.appeler(self._nom, fn))
        t.start()
        self._timers.append(t)
        return t

    def inserer_texte(self, texte: str) -> bool:
        """Insère du texte à la position du curseur dans la note affichée (remplace la sélection). False si la note
        n'est pas modifiable (aucune fiche, ou fiche verrouillée fermée)."""
        e = self._f.texte
        if not e.isEnabled() or self._f.fiche is None:
            return False
        e.textCursor().insertText(texte)
        e.setFocus()
        return True

    def texte_selectionne(self) -> str:
        return self._f.texte.textCursor().selectedText().replace("\u2029", "\n") if self._f.texte.isEnabled() else ""

    def afficher_fiche(self, vue) -> None:
        """Affiche la fenêtre sur cette fiche."""
        self._f.montrer(theme=vue.theme)
        self._f.selectionner_fiche(vue)

    def retirer_tout(self) -> None:
        for menu, a in self._actions:
            menu.removeAction(a)
            a.deleteLater()
        for d in self._docks:
            self._f.removeDockWidget(d)
            d.deleteLater()
        for t in self._timers:
            t.stop()
            t.deleteLater()
        self._actions, self._docks, self._timers = [], [], []


class DialogueExtensions(QDialog):
    def __init__(self, fenetre):
        super().__init__(fenetre)
        self.g = fenetre.plugins
        self.setWindowTitle(_("Extensions"))
        self.resize(560, 380)
        lay = QVBoxLayout(self)
        avert = QLabel(_("Une extension est un programme qui s'exécute avec les mêmes droits que Scrinium : elle peut "
                         "lire les fiches ouvertes. N'activez que des extensions dont vous connaissez l'origine."))
        avert.setWordWrap(True)
        lay.addWidget(avert)
        self.liste = QListWidget()
        lay.addWidget(self.liste, 1)
        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        self.detail.setMinimumHeight(60)
        lay.addWidget(self.detail)
        bas = QHBoxLayout()
        b = QPushButton(icone("folder-new"), _("Ouvrir le dossier des extensions"))
        b.clicked.connect(self._ouvrir_dossier)
        f = QPushButton(_("Fermer"))
        f.clicked.connect(self.accept)
        bas.addWidget(b)
        bas.addStretch()
        bas.addWidget(f)
        lay.addLayout(bas)
        self.g.decouvrir()
        self._remplir()
        self.liste.currentRowChanged.connect(self._detail)
        self.liste.itemChanged.connect(self._coche)

    def _remplir(self):
        self.liste.blockSignals(True)
        self.liste.clear()
        for nom, info in sorted(self.g.infos.items()):
            it = QListWidgetItem(f"{info.titre}  ({info.version})")
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if nom in self.g.actifs else Qt.CheckState.Unchecked)
            it.setData(Qt.ItemDataRole.UserRole, nom)
            self.liste.addItem(it)
        self.liste.blockSignals(False)
        if not self.g.infos:
            self.detail.setText(_("Aucune extension installée. Déposez-en dans le dossier des extensions."))
        elif self.liste.count():
            self.liste.setCurrentRow(0)

    def _detail(self, row):
        if row < 0:
            return
        info = self.g.infos[self.liste.item(row).data(Qt.ItemDataRole.UserRole)]
        txt = f"<b>{info.titre}</b> {info.version}" + (f" · {info.auteur}" if info.auteur else "")
        txt += f"<br>{info.description}" if info.description else ""
        txt += "<br><i>" + (_("Installée comme paquet") if info.source == "paquet" else _("Dossier utilisateur")) + "</i>"
        if info.erreur:
            txt += f"<br><span style='color:#c0392b'>⚠ {info.erreur}</span>"
        self.detail.setText(txt)

    def _coche(self, it):
        nom = it.data(Qt.ItemDataRole.UserRole)
        on = it.checkState() == Qt.CheckState.Checked
        if on:
            if QMessageBox.question(self, _("Activer l'extension"),
                                    _("Activer « %s » ? Elle pourra lire les fiches ouvertes.") % self.g.infos[nom].titre
                                    ) != QMessageBox.StandardButton.Yes or not self.g.activer(nom):
                if self.g.infos[nom].erreur:
                    QMessageBox.warning(self, _("Extension"), _("Impossible d'activer : %s") % self.g.infos[nom].erreur)
                self.liste.blockSignals(True)
                it.setCheckState(Qt.CheckState.Unchecked)
                self.liste.blockSignals(False)
        else:
            self.g.desactiver(nom)
        self._detail(self.liste.currentRow())

    def _ouvrir_dossier(self):
        self.g.dossier.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.g.dossier)))

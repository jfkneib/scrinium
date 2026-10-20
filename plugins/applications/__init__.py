# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « Applications » : un panneau d'icônes pour lancer vos applications (Thunderbird, KWrite, LibreOffice…).

- Un clic lance l'application ; rien ne part sans clic. Séparé des « Actions CLI » (commandes en console).
- On choisit les applications parmi celles du système (menus .desktop) ou on tape une commande ; icône du thème.
- Facultatif : `{selection}` (texte sélectionné) et `{fiche}` (titre) dans la commande sont passés comme ARGUMENTS
  (jamais via un shell). `{selection}` est refusé pour une fiche verrouillée, dont le texte ne doit pas apparaître
  dans la liste des processus.
- Les applications sont enregistrées en clair dans les réglages : n'y mettez aucun mot de passe."""
import html
from pathlib import Path

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                             QListView, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from scrinium.core.plugins import Plugin
from scrinium.i18n import _
from scrinium.ui.icons import icone

from . import logique


def _parent():
    return QApplication.activeWindow()


def icone_app(nom: str) -> QIcon:
    """Icône du thème, ou fichier d'image si `nom` est un chemin ; repli sur une icône générique."""
    if nom and Path(nom).is_absolute() and Path(nom).is_file():
        ic = QIcon(nom)
        if not ic.isNull():
            return ic
    for candidat in (nom, "system-run", "applications-other", "view-pim-notes"):
        ic = icone(candidat) if candidat else QIcon()
        if not ic.isNull():
            return ic
    return QIcon()


def info(a: dict) -> str:
    """Infobulle : nom, description, commande."""
    desc = _(a["description"]) if a["description"] else ""
    return (f"<b>{html.escape(a['nom'])}</b>" + (f"<br><i>{html.escape(desc)}</i>" if desc else "")
            + f"<br><br><code>{html.escape(a['commande'])}</code>")


class PanneauApplications(QWidget):
    """Grille de boutons-icônes ; l'infobulle de chacun montre la commande."""

    def __init__(self, plugin):
        super().__init__()
        self.p = plugin
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.liste = QListWidget()
        self.liste.setViewMode(QListView.ViewMode.IconMode)
        self.liste.setResizeMode(QListView.ResizeMode.Adjust)
        self.liste.setMovement(QListView.Movement.Static)
        self.liste.setWrapping(True)
        self.liste.setIconSize(QSize(32, 32))
        self.liste.setGridSize(QSize(92, 74))
        self.liste.setWordWrap(True)
        self.liste.setUniformItemSizes(True)
        self.liste.itemClicked.connect(self._clic)
        lay.addWidget(self.liste, 1)
        b = QPushButton(icone("configure"), _("Modifier les applications…"))
        b.clicked.connect(plugin.modifier)
        lay.addWidget(b)
        self.rafraichir()

    def rafraichir(self):
        self.liste.clear()
        for a in self.p.applications():
            it = QListWidgetItem(icone_app(a["icone"]), a["nom"])
            it.setToolTip(info(a))
            it.setData(Qt.ItemDataRole.UserRole, a)
            it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            self.liste.addItem(it)

    def _clic(self, it):
        self.liste.clearSelection()
        self.p.lancer(it.data(Qt.ItemDataRole.UserRole))


class DialogueChoix(QDialog):
    """Choisir une application parmi celles installées (menus du système)."""

    def __init__(self, parent=None, apps=None):
        super().__init__(parent)
        self.setWindowTitle(_("Applications installées"))
        self.resize(420, 480)
        lay = QVBoxLayout(self)
        self.filtre = QLineEdit()
        self.filtre.setPlaceholderText(_("Filtrer…"))
        lay.addWidget(self.filtre)
        self.liste = QListWidget()
        self.liste.setIconSize(QSize(24, 24))
        self.liste.itemDoubleClicked.connect(lambda *_a: self.accept())
        lay.addWidget(self.liste, 1)
        self.apps = logique.applications_installees() if apps is None else apps
        for a in self.apps:
            it = QListWidgetItem(icone_app(a["icone"]), a["nom"])
            it.setData(Qt.ItemDataRole.UserRole, a)
            it.setToolTip(info(a))
            self.liste.addItem(it)
        self.filtre.textChanged.connect(self._filtrer)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        b.accepted.connect(self.accept)
        b.rejected.connect(self.reject)
        lay.addWidget(b)

    def _filtrer(self, texte: str):
        t = texte.strip().lower()
        for i in range(self.liste.count()):
            self.liste.item(i).setHidden(bool(t) and t not in self.liste.item(i).text().lower())

    def choix(self) -> dict | None:
        it = self.liste.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it is not None else None


class DialogueApplication(QDialog):
    """Créer ou modifier une application."""

    def __init__(self, application=None, parent=None):
        super().__init__(parent)
        a = application or {"nom": "", "icone": "system-run", "commande": "", "description": ""}
        self.setWindowTitle(_("Application"))
        self.resize(480, 300)
        f = QFormLayout(self)
        choisir = QPushButton(icone("system-search"), _("Choisir parmi les applications installées…"))
        choisir.clicked.connect(self._choisir)
        f.addRow(choisir)
        self.nom = QLineEdit(a["nom"])
        self.icone = QLineEdit(a["icone"])
        self.icone.setToolTip(_("Nom d'une icône du thème d'icônes du système (ex. thunderbird, kwrite, system-run), "
                                "ou chemin d'un fichier image."))
        self.apercu = QLabel()
        self.icone.textChanged.connect(self._apercu)
        ligne = QHBoxLayout()
        ligne.addWidget(self.icone, 1)
        ligne.addWidget(self.apercu)
        self.commande = QLineEdit(a["commande"])
        self.commande.setPlaceholderText("thunderbird")
        self.description = QLineEdit(_(a["description"]) if a["description"] else "")
        f.addRow(_("Nom :"), self.nom)
        f.addRow(_("Icône :"), ligne)
        f.addRow(_("Commande :"), self.commande)
        aide = QLabel(_("Facultatif : {selection} = texte sélectionné dans la fiche, {fiche} = son titre (passés comme "
                        "arguments, sans shell). Les applications sont enregistrées en clair : n'y mettez aucun mot de passe."))
        aide.setWordWrap(True)
        f.addRow(aide)
        f.addRow(_("Description :"), self.description)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        b.accepted.connect(self._valider)
        b.rejected.connect(self.reject)
        f.addRow(b)
        self._apercu()

    def _choisir(self):
        d = DialogueChoix(self)
        if d.exec() and d.choix():
            a = d.choix()
            self.nom.setText(a["nom"])
            self.icone.setText(a["icone"])
            self.commande.setText(a["commande"])
            self.description.setText(a["description"])

    def _apercu(self):
        ic = icone_app(self.icone.text().strip())
        self.apercu.setPixmap(ic.pixmap(22, 22))

    def _valider(self):
        if not self.nom.text().strip() or not self.commande.text().strip():
            QMessageBox.warning(self, _("Application"), _("Le nom et la commande sont obligatoires."))
            return
        self.accept()

    def resultat(self) -> dict | None:
        return logique.normaliser({"nom": self.nom.text(), "icone": self.icone.text(), "commande": self.commande.text(),
                                   "description": self.description.text()})


class DialogueApplications(QDialog):
    """Liste des applications : ajouter, modifier, supprimer, réordonner, exemples, export/import."""

    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.p = plugin
        self.setWindowTitle(_("Applications"))
        self.resize(560, 420)
        lay = QHBoxLayout(self)
        self.liste = QListWidget()
        self.liste.setIconSize(QSize(24, 24))
        self.liste.itemDoubleClicked.connect(lambda *_a: self._modifier())
        lay.addWidget(self.liste, 1)
        col = QVBoxLayout()
        for texte, fn in ((_("Ajouter…"), self._ajouter), (_("Modifier…"), self._modifier), (_("Supprimer"), self._supprimer),
                          (_("Monter"), lambda: self._deplacer(-1)), (_("Descendre"), lambda: self._deplacer(1)),
                          (_("Exemples…"), self._exemples), (_("Exporter…"), self._exporter), (_("Importer…"), self._importer)):
            b = QPushButton(texte)
            b.clicked.connect(fn)
            col.addWidget(b)
        col.addStretch()
        f = QPushButton(_("Fermer"))
        f.clicked.connect(self.accept)
        col.addWidget(f)
        lay.addLayout(col)
        self.apps = plugin.applications()
        self._remplir()

    def _remplir(self, ligne=None):
        self.liste.clear()
        for a in self.apps:
            self.liste.addItem(QListWidgetItem(icone_app(a["icone"]), f"{a['nom']}   ·   {a['commande']}"))
        if self.apps:
            self.liste.setCurrentRow(min(ligne if ligne is not None else 0, len(self.apps) - 1))

    def _enregistrer(self, ligne=None):
        self.p.sauver(self.apps)
        self._remplir(ligne)

    def _ajouter(self):
        d = DialogueApplication(None, self)
        if d.exec() and d.resultat():
            self.apps.append(d.resultat())
            self._enregistrer(len(self.apps) - 1)

    def _modifier(self):
        i = self.liste.currentRow()
        if 0 <= i < len(self.apps):
            d = DialogueApplication(self.apps[i], self)
            if d.exec() and d.resultat():
                self.apps[i] = d.resultat()
                self._enregistrer(i)

    def _supprimer(self):
        i = self.liste.currentRow()
        if 0 <= i < len(self.apps):
            del self.apps[i]
            self._enregistrer(i)

    def _deplacer(self, sens):
        i, j = self.liste.currentRow(), self.liste.currentRow() + sens
        if 0 <= i < len(self.apps) and 0 <= j < len(self.apps):
            self.apps[i], self.apps[j] = self.apps[j], self.apps[i]
            self._enregistrer(j)

    def _exemples(self):
        presentes = {a["commande"] for a in self.apps}
        nouveaux = [a for a in logique.exemples_installes() if a["commande"] not in presentes]
        if not nouveaux:
            QMessageBox.information(self, _("Exemples"), _("Aucun exemple de plus : ils sont déjà dans la liste, ou ne sont pas installés."))
            return
        self.apps = logique.normaliser_liste(self.apps + nouveaux)
        self._enregistrer(len(self.apps) - 1)

    def _exporter(self):
        chemin, _f = QFileDialog.getSaveFileName(self, _("Exporter les applications"), "applications-scrinium.json", "JSON (*.json)")
        if chemin:
            try:
                Path(chemin).write_text(logique.exporter(self.apps), encoding="utf-8")
            except OSError as ex:
                QMessageBox.warning(self, _("Applications"), str(ex))

    def _importer(self):
        chemin, _f = QFileDialog.getOpenFileName(self, _("Importer des applications"), "", "JSON (*.json)")
        if not chemin:
            return
        try:
            nouvelles = logique.importer(Path(chemin).read_text(encoding="utf-8"))
        except (OSError, ValueError) as ex:
            QMessageBox.warning(self, _("Applications"), str(ex))
            return
        if QMessageBox.question(self, _("Importer"), _("Ajouter %d application(s) à la liste ? Relisez leurs commandes avant de "
                                                       "les utiliser.") % len(nouvelles)) == QMessageBox.StandardButton.Yes:
            self.apps = logique.normaliser_liste(self.apps + nouvelles)
            self._enregistrer(len(self.apps) - 1)


class ApplicationsPlugin(Plugin):
    api = 1

    def activer(self, ctx):
        self.ctx = ctx
        if ctx.ui is None:
            return
        self.panneau = PanneauApplications(self)
        self.dock = ctx.ui.ajouter_panneau(_("Applications"), self.panneau)
        self.interrupteurs = (ctx.ui.ajouter_action(_("Panneau des applications"), self.basculer_panneau, "view-list-icons"),
                              ctx.ui.ajouter_bouton(_("Applications"), self.basculer_panneau, "view-list-icons"))
        for a in self.interrupteurs:
            a.setCheckable(True)
            a.setChecked(not self.dock.isHidden())
            a.setToolTip(_("Afficher ou masquer le panneau des applications"))
        self.dock.visibilityChanged.connect(self._etat_panneau)
        ctx.ui.ajouter_action(_("Modifier les applications…"), self.modifier, "configure")

    def basculer_panneau(self):
        self.dock.setVisible(self.dock.isHidden())

    def _etat_panneau(self, _visible: bool = True):
        for a in self.interrupteurs:
            a.setChecked(not self.dock.isHidden())

    # ---------- liste ----------
    def applications(self) -> list:
        """Applications enregistrées ; les exemples installés tant que l'utilisateur n'a rien enregistré."""
        brut = self.ctx.reglages.get("applications")
        return logique.exemples_installes() if brut is None else logique.normaliser_liste(brut)

    def sauver(self, applications: list):
        self.ctx.reglages.set("applications", logique.normaliser_liste(applications))
        self.panneau.rafraichir()

    def modifier(self):
        DialogueApplications(self, _parent()).exec()
        self.panneau.rafraichir()

    # ---------- lancement ----------
    def lancer(self, a: dict):
        """Clic sur une icône : lance l'application (avec la sélection ou le titre si la commande les demande)."""
        vue = self.ctx.fiche_courante()
        selection = self.ctx.ui.texte_selectionne()
        if logique.utilise_selection(a["commande"]):
            if vue is not None and vue.verrou:
                self.ctx.ui.notifier(_("Applications"), _("« %s » demande la sélection : refusé pour une fiche verrouillée.") % a["nom"])
                return
            if not selection.strip():
                self.ctx.ui.notifier(_("Applications"), _("Sélectionnez d'abord du texte dans la fiche : « %s » en a besoin.") % a["nom"])
                return
        try:
            logique.lancer(logique.construire(a["commande"], selection, vue.titre if vue else ""))
        except (OSError, ValueError) as ex:
            self.ctx.ui.notifier(_("Applications"), _("Impossible de lancer « %(nom)s » : %(err)s") % {"nom": a["nom"], "err": ex})

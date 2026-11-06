# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « Applications » : vos applications (Thunderbird, KWrite, LibreOffice…) dans une fiche d'icônes, et dans le clic
  droit « Ouvrir avec » de toute fiche (avec le texte sélectionné si la commande le demande).

- Un clic lance l'application ; rien ne part sans clic. Pas de panneau : la fiche est l'écran, le clic droit la configure.
  Séparé des « Actions CLI » (commandes en console).
- On choisit les applications parmi celles du système (menus .desktop) ou on tape une commande ; icône du thème.
- Facultatif : `{selection}` (texte sélectionné) et `{fiche}` (titre) dans la commande sont passés comme ARGUMENTS
  (jamais via un shell). `{selection}` est refusé pour une fiche verrouillée, dont le texte ne doit pas apparaître
  dans la liste des processus.
- « Tout est fiche » : les applications sont une FICHE de type `applications` (`#scrinium-applications`, voir `logique.py`) : elle se partage,
  se synchronise, se sauvegarde comme les autres. C'est un type EXÉCUTABLE : une fiche reçue de l'extérieur ne lance rien tant que
  l'utilisateur ne l'a pas validée (bandeau « Valider cette fiche »). Les applications sont en clair : n'y mettez aucun mot de passe."""
import html
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                             QListView, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from scrinium.core.liste_fiches import ListeDeFiches
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


class VueApplications(QWidget):
    """Vue du type « applications » : la fiche s'affiche comme une grille d'icônes (le texte reste dans la fiche). Un clic lance l'application ;
    le clic droit ajoute, modifie, supprime, réordonne, importe, exporte. Fiche non validée : lisible, rien ne se lance ni ne se modifie."""
    modifie = pyqtSignal(str)

    def __init__(self, plugin=None, parent=None):
        super().__init__(parent)
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
        self.aide = QLabel()
        self.aide.setWordWrap(True)
        lay.addWidget(self.aide)
        self.apps: list = []
        self._actif = True
        self._texte_aide()

    @property
    def actif(self) -> bool:
        return self._actif

    @actif.setter
    def actif(self, oui: bool) -> None:
        """Faux : fiche non validée. La liste se lit (pour relire les commandes avant de valider) mais ne se lance ni ne se modifie."""
        self._actif = bool(oui)
        self._texte_aide()

    def _texte_aide(self):
        self.aide.setText(_("Clic : lancer · clic droit : ajouter, modifier, déplacer…") if self._actif else
                          _("Fiche non validée : relisez les commandes (infobulles), puis validez-la pour lancer et modifier."))

    def charger(self, texte: str):
        self.definir(logique.depuis_texte(texte))

    def definir(self, apps: list):
        self.apps = logique.normaliser_liste(apps)
        self._remplir()

    def _remplir(self, ligne=None):
        self.liste.clear()
        for a in self.apps:
            it = QListWidgetItem(icone_app(a["icone"]), a["nom"])
            it.setToolTip(info(a))
            it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            self.liste.addItem(it)
        if ligne is not None and 0 <= ligne < len(self.apps):
            self.liste.setCurrentRow(ligne)

    def _enregistrer(self, ligne=None):
        self.modifie.emit(logique.en_texte(self.apps))
        self._remplir(ligne)

    def _clic(self, it):
        i = self.liste.row(it)
        self.liste.clearSelection()
        if self._actif and self.p is not None and 0 <= i < len(self.apps):
            self.p.lancer(self.apps[i])

    # ---------- clic droit ----------
    def entrees_menu(self, pos) -> list:
        """Entrées du clic droit (la fenêtre y ajoute celles des extensions) ; `pos` : position dans cette vue."""
        if not self._actif:
            return []
        it = self.liste.itemAt(self.liste.viewport().mapFrom(self, pos))
        i = self.liste.row(it) if it is not None else -1
        e = [(_("Ajouter une application…"), lambda *_a: self._ajouter(), "list-add")]
        if i >= 0:
            e += [(_("Modifier…"), lambda *_a, i=i: self._modifier(i), "document-edit"),
                  (_("Supprimer"), lambda *_a, i=i: self._supprimer(i), "edit-delete"),
                  (_("Monter"), lambda *_a, i=i: self._deplacer(i, -1), "go-up"),
                  (_("Descendre"), lambda *_a, i=i: self._deplacer(i, 1), "go-down")]
        return e + [(_("Ajouter les exemples installés"), lambda *_a: self._exemples(), "view-list-icons"),
                    (_("Exporter…"), lambda *_a: self._exporter(), "document-export"),
                    (_("Importer…"), lambda *_a: self._importer(), "document-import")]

    def _ajouter(self):
        d = DialogueApplication(None, self)
        if d.exec() and d.resultat():
            self.apps.append(d.resultat())
            self._enregistrer(len(self.apps) - 1)

    def _modifier(self, i: int):
        if self._actif and 0 <= i < len(self.apps):
            d = DialogueApplication(self.apps[i], self)
            if d.exec() and d.resultat():
                self.apps[i] = d.resultat()
                self._enregistrer(i)

    def _supprimer(self, i: int):
        if self._actif and 0 <= i < len(self.apps):
            del self.apps[i]
            self._enregistrer(min(i, len(self.apps) - 1))

    def _deplacer(self, i: int, sens: int):
        j = i + sens
        if self._actif and 0 <= i < len(self.apps) and 0 <= j < len(self.apps):
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
        ctx.ajouter_doc(_('Extension Applications'), DOC)
        if ctx.ui is None:
            return
        ctx.ui.enregistrer_type(logique.TYPE, VueApplications(self))
        ctx.ui.ajouter_action(_("Fiche des applications…"), self.modifier, "view-list-icons")
        ctx.ui.ajouter_sous_menu_fiche(_("Ouvrir avec"), self.entrees_ouvrir_avec, "document-open")
        self._migrer()

    def entrees_ouvrir_avec(self) -> list:
        """Sous-menu « Ouvrir avec » du clic droit d'une fiche : les applications des fiches validées (lues à chaque ouverture du menu)."""
        return [(a["nom"], lambda a=a: self._lancer_si_present(a), a["icone"] or "system-run") for a in self.applications()]

    def _lancer_si_present(self, a: dict):
        """Entrée choisie dans le menu : on relit la liste avant de lancer (la fiche a pu changer ou perdre sa validation entre-temps)."""
        if a in self.applications():
            self.lancer(a)

    # ---------- liste ----------
    THEME = "Outils"                           # thème de la fiche créée à la migration ou par « Fiche des applications… »

    def _liste(self) -> ListeDeFiches:
        return ListeDeFiches(self.ctx, logique.TYPE, logique.normaliser_liste, logique.depuis_texte, logique.en_texte, "applications",
                             logique.exemples_installes, _("Applications"), self.THEME, logique.MAX_APPLICATIONS)

    def applications(self) -> list:
        """Applications du menu « Ouvrir avec » : celles des fiches « applications » VALIDÉES (sans doublon) ; tant qu'il n'y en a aucune, les réglages
        d'avant « tout est fiche », puis, sans réglage, les exemples installés."""
        return self._liste().elements()

    def a_valider(self) -> int:
        """Nombre de fiches « applications » en attente de validation (reçues, ou modifiées ailleurs)."""
        return self._liste().a_valider()

    def _migrer(self):
        """Les applications d'avant « tout est fiche » (réglages) deviennent une fiche, une seule fois ; les réglages restent comme copie.
        La fiche créée est inerte : l'utilisateur la valide (bandeau), en attendant, « Ouvrir avec » garde l'ancienne liste."""
        if self._liste().migrer() is not None:
            self.ctx.ui.actualiser()
            self.ctx.ui.notifier(_("Applications"), _("Vos applications sont maintenant une fiche « Applications » (thème « %s ») : ouvrez-la "
                                                      "et validez-la.") % self.THEME)

    def modifier(self):
        """Ouvre la fiche des applications ; sans fiche, la crée à partir de la liste actuelle (à valider ensuite)."""
        vue, creee = self._liste().a_ouvrir()
        if creee:
            self.ctx.ui.actualiser()
            self.ctx.ui.notifier(_("Applications"), _("Fiche « Applications » créée : validez-la pour qu'elle serve à « Ouvrir avec »."))
        self.ctx.ui.afficher_fiche(vue)

    # ---------- lancement ----------
    def lancer(self, a: dict):
        """Lance l'application (avec la sélection ou le titre si la commande les demande)."""
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


DOC = _(
    "Une fiche d'icônes pour lancer vos logiciels (Thunderbird, KWrite, LibreOffice…) sans quitter Scrinium.\n"
    '\n'
    "• Nouvelle fiche > « Applications » : un clic sur une icône lance l'application ; le clic droit ajoute, retire ou règle une application.\n"
    '• On choisit parmi les applications du système ou on tape une commande. Facultatif : {selection} (texte sélectionné) et {fiche} (titre de la fiche) dans la commande lui sont passés comme arguments.\n'
    "• Clic droit sur n'importe quelle fiche > « Ouvrir avec » : la même liste, avec le texte sélectionné.\n"
    "• Type exécutable : une fiche reçue d'un autre ne lance rien tant que vous ne l'avez pas validée (bandeau « Valider cette fiche »).\n"
    "• Les applications sont écrites en clair dans la fiche : n'y mettez aucun mot de passe.")

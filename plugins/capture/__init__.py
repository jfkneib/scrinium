# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « Capture et console ».

- Exécuter une commande… : la sortie s'affiche, puis s'insère au curseur de la fiche (bloc daté, comme `scrinium ajouter`).
  La commande n'est lancée que sur votre demande, avec un délai maximal et une taille de sortie limitée.
- Console : envoie le texte sélectionné dans la fiche vers une console. L'extension ouvre sa propre Konsole (titrée
  « Scrinium »), la réutilise toujours, et la rouvre si vous l'avez fermée. Le texte y est tapé SANS être validé (vous
  relisez, puis Entrée) ; il faut pour cela activer dans Konsole « Enable the security sensitive parts of the DBus API ».
  Sinon, ou ailleurs que sous Konsole : le texte est copié dans le presse-papiers. « Choisir la console cible… » permet
  d'utiliser à la place une de vos consoles existantes. Sous KDE, la console passe au premier plan après l'envoi.
- Panneau d'actions : des boutons-icônes pour des commandes préparées (à définir, modifier, exporter) ; au survol, une
  infobulle montre la commande et ce que le clic fera. Un clic ne lance jamais rien sans que vous l'ayez voulu :
  par défaut le texte est tapé sans être validé ; l'exécution demande une confirmation.
Le pendant « fiche -> commande » (`ip a | scrinium ajouter …`) est dans le cœur : `scrinium ajouter`.
"""
import html
import threading
import time
from pathlib import Path

from PyQt6.QtCore import QObject, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                             QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem,
                             QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from scrinium.core import capture
from scrinium.core.plugins import Plugin
from scrinium.i18n import _
from scrinium.ui.icons import icone

from . import logique

AIDE_KONSOLE = _("Pour que Scrinium tape directement dans Konsole, activez dans Konsole l'option « Enable the security sensitive "
                 "parts of the DBus API » (Paramètres de Konsole). Elle est désactivée par défaut car elle permet à un "
                 "programme d'envoyer du texte à vos terminaux : c'est votre choix. En attendant, le texte est copié "
                 "dans le presse-papiers.")


def _parent():
    return QApplication.activeWindow()


class _Pont(QObject):
    fini = pyqtSignal(object)        # résultat de logique.executer


class DialogueCommande(QDialog):
    """Saisir une commande, voir sa sortie, l'insérer dans la fiche."""

    def __init__(self, plugin, parent=None, commande=None):
        super().__init__(parent)
        self.p = plugin
        self.resultat = None
        self.setWindowTitle(_("Exécuter une commande"))
        self.resize(640, 420)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(_("La commande est lancée par votre shell, uniquement quand vous cliquez sur « Exécuter » "
                               "(délai maximal : %d s).") % logique.DELAI_COMMANDE))
        ligne = QHBoxLayout()
        self.commande = QLineEdit(commande if commande is not None else plugin.ctx.reglages.get("derniere", ""))
        self.commande.setPlaceholderText("ip -br a")
        self.b_exec = QPushButton(_("Exécuter"))
        ligne.addWidget(self.commande, 1)
        ligne.addWidget(self.b_exec)
        lay.addLayout(ligne)
        self.sortie = QPlainTextEdit(readOnly=True)
        lay.addWidget(self.sortie, 1)
        self.etat = QLabel("")
        lay.addWidget(self.etat)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.b_inserer = b.addButton(_("Insérer dans la fiche"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.b_inserer.setEnabled(False)
        b.accepted.connect(self._inserer)
        b.rejected.connect(self.reject)
        lay.addWidget(b)
        self.pont = _Pont()
        self.pont.fini.connect(self._fini)
        self.b_exec.clicked.connect(self._lancer)
        self.commande.returnPressed.connect(self._lancer)
        if commande is not None:
            self.b_exec.setFocus()          # action préparée : la commande est affichée, un clic sur « Exécuter » la lance

    def _lancer(self):
        cmd = self.commande.text().strip()
        if not cmd or not self.b_exec.isEnabled():
            return
        self.p.ctx.reglages.set("derniere", cmd)
        self.b_exec.setEnabled(False)
        self.b_inserer.setEnabled(False)
        self.etat.setText(_("Exécution…"))
        threading.Thread(target=lambda: self.pont.fini.emit(logique.executer(cmd)), daemon=True).start()

    def _fini(self, res):
        self.resultat = res
        code, sortie, tronque, depasse = res
        self.sortie.setPlainText(sortie)
        notes = []
        if depasse:
            notes.append(_("délai dépassé : commande arrêtée, sortie partielle"))
        elif code:
            notes.append(_("code de retour %d") % code)
        if tronque:
            notes.append(_("sortie tronquée"))
        self.etat.setText(" · ".join(notes) or _("Terminé."))
        self.b_exec.setEnabled(True)
        self.b_inserer.setEnabled(bool(sortie.strip()))

    def _inserer(self):
        if self.resultat is None:
            return
        texte = capture.bloc(capture.tronquer(self.resultat[1]), self.commande.text().strip())
        if self.p.ctx.ui.inserer_texte("\n" + texte):
            self.accept()
        else:
            QMessageBox.warning(self, _("Capture"), _("La fiche n'est pas modifiable (aucune fiche ouverte, ou verrouillée fermée)."))


def info_action(a: dict) -> str:
    """Infobulle d'un bouton : nom, description, commande, ce que fera le clic."""
    lignes = a["commande"].splitlines()
    cmd = "<br>".join(html.escape(x) for x in lignes[:6]) + ("<br>…" if len(lignes) > 6 else "")
    return (f"<b>{html.escape(a['nom'])}</b>" + (f"<br><i>{html.escape(a['description'])}</i>" if a["description"] else "")
            + f"<br><br><code>{cmd}</code><br><br>{html.escape(_(logique.MODES[a['mode']]))}")


def icone_action(nom: str) -> QIcon:
    ic = icone(nom)
    return ic if not ic.isNull() else icone("system-run") if not icone("system-run").isNull() else icone("view-pim-notes")


class PanneauActions(QWidget):
    """Grille de boutons-icônes ; l'infobulle de chacun dit ce que le clic fera."""

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
        b = QPushButton(icone("configure"), _("Modifier les actions…"))
        b.clicked.connect(plugin.modifier_actions)
        lay.addWidget(b)
        self.rafraichir()

    def rafraichir(self):
        self.liste.clear()
        for a in self.p.actions():
            it = QListWidgetItem(icone_action(a["icone"]), a["nom"])
            it.setToolTip(info_action(a))
            it.setData(Qt.ItemDataRole.UserRole, a)
            it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            self.liste.addItem(it)

    def _clic(self, it):
        self.liste.clearSelection()
        self.p.lancer_action(it.data(Qt.ItemDataRole.UserRole))


class DialogueAction(QDialog):
    """Créer ou modifier une action."""

    def __init__(self, action=None, parent=None):
        super().__init__(parent)
        a = action or {"nom": "", "icone": "system-run", "mode": "taper", "commande": "", "description": ""}
        self.setWindowTitle(_("Action"))
        self.resize(520, 400)
        f = QFormLayout(self)
        self.nom = QLineEdit(a["nom"])
        self.icone = QLineEdit(a["icone"])
        self.icone.setToolTip(_("Nom d'une icône du thème d'icônes du système (ex. network-wired, drive-harddisk, "
                                "utilities-terminal, system-run, edit-find)."))
        self.apercu = QLabel()
        self.icone.textChanged.connect(self._apercu)
        ligne = QHBoxLayout()
        ligne.addWidget(self.icone, 1)
        ligne.addWidget(self.apercu)
        self.mode = QComboBox()
        for cle, libelle in logique.MODES.items():
            self.mode.addItem(_(libelle), cle)
        self.mode.setCurrentIndex(max(0, self.mode.findData(a["mode"])))
        self.commande = QPlainTextEdit(a["commande"])
        self.commande.setPlaceholderText("ip -br a")
        self.description = QLineEdit(a["description"])
        f.addRow(_("Nom :"), self.nom)
        f.addRow(_("Icône :"), ligne)
        f.addRow(_("Au clic :"), self.mode)
        f.addRow(_("Commande :"), self.commande)
        aide = QLabel(_("{selection} = texte sélectionné dans la fiche ; {fiche} = son titre. En mode « Exécuter », ils sont "
                        "protégés pour le shell. Les actions sont enregistrées en clair : n'y mettez aucun mot de passe."))
        aide.setWordWrap(True)
        f.addRow(aide)
        f.addRow(_("Description :"), self.description)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        b.accepted.connect(self._valider)
        b.rejected.connect(self.reject)
        f.addRow(b)
        self._apercu()

    def _apercu(self):
        ic = icone(self.icone.text().strip())
        self.apercu.setPixmap(ic.pixmap(22, 22) if not ic.isNull() else QIcon().pixmap(22, 22))
        self.apercu.setToolTip("" if not ic.isNull() else _("Icône introuvable : l'icône par défaut sera utilisée."))

    def _valider(self):
        if not self.nom.text().strip() or not self.commande.toPlainText().strip():
            QMessageBox.warning(self, _("Action"), _("Le nom et la commande sont obligatoires."))
            return
        self.accept()

    def resultat(self) -> dict:
        return logique.normaliser_action({"nom": self.nom.text(), "icone": self.icone.text(), "mode": self.mode.currentData(),
                                          "commande": self.commande.toPlainText(), "description": self.description.text()})


class DialogueActions(QDialog):
    """Liste des actions : ajouter, modifier, supprimer, réordonner, exemples, export/import."""

    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.p = plugin
        self.setWindowTitle(_("Actions préparées"))
        self.resize(560, 420)
        lay = QHBoxLayout(self)
        self.liste = QListWidget()
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
        self.actions = plugin.actions()
        self._remplir()

    def _remplir(self, ligne=None):
        self.liste.clear()
        for a in self.actions:
            self.liste.addItem(QListWidgetItem(icone_action(a["icone"]), f"{a['nom']}   ·   {_(logique.MODES[a['mode']])}"))
        if self.actions:
            self.liste.setCurrentRow(min(ligne if ligne is not None else 0, len(self.actions) - 1))

    def _enregistrer(self, ligne=None):
        self.p.sauver_actions(self.actions)
        self._remplir(ligne)

    def _ajouter(self):
        d = DialogueAction(None, self)
        if d.exec() and d.resultat():
            self.actions.append(d.resultat())
            self._enregistrer(len(self.actions) - 1)

    def _modifier(self):
        i = self.liste.currentRow()
        if 0 <= i < len(self.actions):
            d = DialogueAction(self.actions[i], self)
            if d.exec() and d.resultat():
                self.actions[i] = d.resultat()
                self._enregistrer(i)

    def _supprimer(self):
        i = self.liste.currentRow()
        if 0 <= i < len(self.actions):
            del self.actions[i]
            self._enregistrer(i)

    def _deplacer(self, sens):
        i, j = self.liste.currentRow(), self.liste.currentRow() + sens
        if 0 <= i < len(self.actions) and 0 <= j < len(self.actions):
            self.actions[i], self.actions[j] = self.actions[j], self.actions[i]
            self._enregistrer(j)

    def _exemples(self):
        rep = QMessageBox.question(self, _("Exemples"), _("Ajouter les actions d'exemple à la fin de la liste ? "
                                                         "(Aucune n'est lancée.)"))
        if rep == QMessageBox.StandardButton.Yes:
            self.actions += [dict(a) for a in logique.EXEMPLES]
            self.actions = logique.normaliser_liste(self.actions)
            self._enregistrer(len(self.actions) - 1)

    def _exporter(self):
        chemin, _f = QFileDialog.getSaveFileName(self, _("Exporter les actions"), "actions-scrinium.json", "JSON (*.json)")
        if chemin:
            try:
                Path(chemin).write_text(logique.exporter_actions(self.actions), encoding="utf-8")
            except OSError as ex:
                QMessageBox.warning(self, _("Actions"), str(ex))

    def _importer(self):
        chemin, _f = QFileDialog.getOpenFileName(self, _("Importer des actions"), "", "JSON (*.json)")
        if not chemin:
            return
        try:
            nouvelles = logique.importer_actions(Path(chemin).read_text(encoding="utf-8"))
        except (OSError, ValueError) as ex:
            QMessageBox.warning(self, _("Actions"), str(ex))
            return
        if QMessageBox.question(self, _("Importer"), _("Ajouter %d action(s) à la liste ? Relisez leurs commandes avant de les "
                                                      "utiliser.") % len(nouvelles)) == QMessageBox.StandardButton.Yes:
            self.actions = logique.normaliser_liste(self.actions + nouvelles)
            self._enregistrer(len(self.actions) - 1)


class DialogueReglages(QDialog):
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.p = plugin
        self.setWindowTitle(_("Réglages de la capture"))
        f = QFormLayout(self)
        self.direct = QCheckBox(_("Essayer d'abord de taper directement dans Konsole (sans valider)"))
        self.direct.setChecked(bool(plugin.ctx.reglages.get("direct", True)))
        f.addRow(self.direct)
        self.devant = QCheckBox(_("Mettre la console au premier plan après l'envoi (KDE)"))
        self.devant.setChecked(bool(plugin.ctx.reglages.get("premier_plan", True)))
        f.addRow(self.devant)
        aide = QLabel(AIDE_KONSOLE)
        aide.setWordWrap(True)
        f.addRow(aide)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        b.accepted.connect(self._valider)
        b.rejected.connect(self.reject)
        f.addRow(b)

    def _valider(self):
        self.p.ctx.reglages.set("direct", self.direct.isChecked())
        self.p.ctx.reglages.set("premier_plan", self.devant.isChecked())
        self.p.refus_vu = False          # l'utilisateur a peut-être activé l'option de Konsole : on réessaie
        self.accept()


class CapturePlugin(Plugin):
    api = 1

    def activer(self, ctx):
        self.ctx = ctx
        self.cible = None          # console choisie à la main (service, session) : gardée tant qu'elle existe
        self.pid_dedie = None      # PID de la Konsole ouverte par l'extension
        self.refus_vu = False      # Konsole a refusé l'envoi : on n'ouvre plus de console pour rien (remis à zéro par les réglages)
        if ctx.ui is None:
            return
        ctx.ui.ajouter_bouton(_("Console"), self.vers_console, "utilities-terminal")
        ctx.ui.ajouter_action(_("Envoyer la sélection vers une console"), self.vers_console, "utilities-terminal")
        ctx.ui.ajouter_action(_("Choisir la console cible…"), self.choisir_cible, "utilities-terminal")
        ctx.ui.ajouter_action(_("Revenir à la console de l'extension"), self.oublier_cible, "utilities-terminal")
        ctx.ui.ajouter_action(_("Exécuter une commande et insérer la sortie…"), self.commande, "system-run")
        ctx.ui.ajouter_action(_("Réglages de la capture…"), self.reglages, "configure")
        ctx.ui.ajouter_action(_("Modifier les actions préparées…"), self.modifier_actions, "configure")
        self.panneau = PanneauActions(self)
        self.dock = ctx.ui.ajouter_panneau(_("Actions"), self.panneau)
        ctx.ui.ajouter_action(_("Afficher / masquer le panneau des actions"), lambda: self.dock.setVisible(not self.dock.isVisible()),
                              "view-list-icons")

    # ---------- actions préparées ----------
    def actions(self) -> list:
        """Actions enregistrées ; les exemples tant que l'utilisateur n'a rien enregistré."""
        brut = self.ctx.reglages.get("actions")
        return [dict(a) for a in logique.EXEMPLES] if brut is None else logique.normaliser_liste(brut)

    def sauver_actions(self, actions: list):
        self.ctx.reglages.set("actions", logique.normaliser_liste(actions))
        self.panneau.rafraichir()

    def modifier_actions(self):
        DialogueActions(self, _parent()).exec()
        self.panneau.rafraichir()

    def lancer_action(self, a: dict):
        """Clic sur un bouton : selon le mode, tape (sans valider), propose d'exécuter, ou copie."""
        selection = self.ctx.ui.texte_selectionne()
        vue = self.ctx.fiche_courante()
        if logique.utilise_selection(a["commande"]) and not selection.strip():
            self.ctx.ui.notifier(_("Actions"), _("Sélectionnez d'abord du texte dans la fiche : « %s » en a besoin.") % a["nom"])
            return
        cmd = logique.etendre(a["commande"], selection, vue.titre if vue else "", a["mode"])
        if a["mode"] == "executer":
            if vue is None:
                self.ctx.ui.notifier(_("Actions"), _("Ouvrez d'abord une fiche : la sortie y sera insérée."))
                return
            DialogueCommande(self, _parent(), commande=cmd).exec()      # la commande s'affiche ; rien ne part sans clic
        elif a["mode"] == "copier":
            QApplication.clipboard().setText(cmd)
            self.ctx.ui.notifier(_("Actions"), _("Copié dans le presse-papiers : « %s ».") % a["nom"])
        else:
            self.envoyer_a_la_console(cmd)

    def commande(self):
        if self.ctx.fiche_courante() is None:
            self.ctx.ui.notifier(_("Capture"), _("Ouvrez d'abord une fiche."))
            return
        DialogueCommande(self, _parent()).exec()

    def reglages(self):
        DialogueReglages(self, _parent()).exec()

    # ---------- fiche -> console ----------
    def oublier_cible(self):
        self.cible = None
        self.ctx.ui.notifier(_("Console"), _("Le texte ira dans la console de l'extension (ouverte au besoin)."))

    def choisir_cible(self):
        """Choisit (et mémorise) la console qui recevra le texte."""
        qdbus = logique.trouver_qdbus()
        sessions = logique.sessions_konsole(qdbus) if qdbus else []
        if not sessions:
            self.ctx.ui.notifier(_("Console"), _("Aucune console Konsole ouverte : celle de l'extension s'ouvrira au premier envoi."))
            return
        choix = self._choisir(sessions, forcer=True)
        if choix is not None:
            self.cible = choix[:2]
            self.ctx.ui.notifier(_("Console"), _("Console cible : %s") % choix[2])

    def vers_console(self):
        brut = self.ctx.ui.texte_selectionne()
        if not brut.strip():
            self.ctx.ui.notifier(_("Console"), _("Sélectionnez d'abord du texte dans la fiche."))
            return
        self.envoyer_a_la_console(brut)

    def envoyer_a_la_console(self, brut: str):
        """Tape le texte dans la console (sans valider), ou le copie dans le presse-papiers si ce n'est pas possible."""
        texte = logique.nettoyer_pour_console(brut)
        if not texte.strip():
            return
        if self.ctx.reglages.get("direct", True) and self._konsole(texte):
            return
        QApplication.clipboard().setText(texte)
        self.ctx.ui.notifier(_("Console"), _("Copié dans le presse-papiers : collez dans votre console (Ctrl+Maj+V). Rien n'est validé."))

    def _console_dediee(self, qdbus):
        """Session de la Konsole ouverte par l'extension, si elle existe encore (sinon None)."""
        pid = self.pid_dedie or self.ctx.reglages.get("konsole_pid")
        if not pid:
            return None
        return next((x for x in logique.sessions_konsole(qdbus) if x[0] == f"org.kde.konsole-{pid}"), None)

    def _ouvrir_console(self, qdbus):
        """Ouvre la Konsole de l'extension et attend qu'elle soit prête (quelques secondes au plus)."""
        pid = logique.lancer_konsole()
        if pid is None:
            return None
        self.pid_dedie = pid
        self.ctx.reglages.set("konsole_pid", pid)
        for _i in range(50):
            QApplication.processEvents()
            session = self._console_dediee(qdbus)
            if session:
                fin = time.time() + 0.5               # laisse au shell le temps de démarrer
                while time.time() < fin:
                    QApplication.processEvents()
                    time.sleep(0.02)
                return session
            time.sleep(0.15)
        return None

    def _konsole(self, texte: str) -> bool:
        """Tape le texte dans la console cible (ou dans la Konsole de l'extension, ouverte au besoin) ; False si ce n'est
        pas possible (repli sur le presse-papiers)."""
        qdbus = logique.trouver_qdbus()
        if not qdbus:
            return False
        try:
            sessions = logique.sessions_konsole(qdbus)
            choix = next((x for x in sessions if x[:2] == self.cible), None)    # console choisie à la main, si elle existe encore
            neuve = False
            if choix is None:
                choix = self._console_dediee(qdbus)
                if choix is None:
                    if self.refus_vu:
                        return False                       # déjà refusé : inutile d'ouvrir une console qui resterait vide
                    if sessions:                           # sonde sur une console existante : Konsole accepte-t-il l'envoi ?
                        logique.envoyer(qdbus, *sessions[0][:2], "")
                    choix = self._ouvrir_console(qdbus)
                    neuve = choix is not None
            if choix is None:
                return False
            logique.envoyer(qdbus, *choix[:2], texte)
        except logique.AccesRefuse:
            self.refus_vu = True
            self.ctx.ui.notifier(_("Console"), _("Konsole refuse l'envoi direct : texte copié dans le presse-papiers."))
            if not self.ctx.reglages.get("aide_vue", False):
                self.ctx.reglages.set("aide_vue", True)
                QMessageBox.information(_parent(), _("Console"), AIDE_KONSOLE)
            return False
        except Exception as ex:
            self.ctx.ui.notifier(_("Console"), _("Konsole : %s") % ex)
            return False
        if self.ctx.reglages.get("premier_plan", True):
            logique.mettre_au_premier_plan(qdbus, choix[0])
        self.ctx.ui.notifier(_("Console"), (_("Console ouverte : ") if neuve else "")
                             + _("texte tapé dans « %s » (non validé : relisez, puis Entrée).") % choix[2])
        return True

    def _choisir(self, sessions, forcer=False):
        if len(sessions) == 1 and not forcer:
            return sessions[0]
        libelles = [f"{lib}   (n° {service.rsplit('-', 1)[-1]}/{n})" for service, n, lib in sessions]
        defaut = next((i for i, x in enumerate(sessions) if x[:2] == self.cible), 0)
        choix, ok = QInputDialog.getItem(_parent(), _("Console"), _("Envoyer vers quelle console ?"), libelles, defaut, False)
        return sessions[libelles.index(choix)] if ok else None

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
- Actions CLI : des commandes préparées, dans une FICHE (à définir, modifier, exporter par son clic droit) ; elles se lancent
  depuis le clic droit « Actions CLI » de toute fiche, et l'infobulle de la fiche montre la commande et ce que le choix fera. Un clic ne lance jamais rien sans que vous l'ayez voulu :
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
from scrinium.core.liste_fiches import ListeDeFiches
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


class DialogueAction(QDialog):
    """Créer ou modifier une action."""

    def __init__(self, action=None, parent=None):
        super().__init__(parent)
        a = action or {"nom": "", "icone": "system-run", "mode": "taper", "commande": "", "description": ""}
        self.setWindowTitle(_("Action CLI"))
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
            QMessageBox.warning(self, _("Action CLI"), _("Le nom et la commande sont obligatoires."))
            return
        self.accept()

    def resultat(self) -> dict:
        return logique.normaliser_action({"nom": self.nom.text(), "icone": self.icone.text(), "mode": self.mode.currentData(),
                                          "commande": self.commande.toPlainText(), "description": self.description.text()})


class VueActions(QWidget):
    """Vue du type « actions CLI » : la fiche s'affiche comme cette liste (le texte reste dans la fiche). Elle sert à CONFIGURER : les actions
    se lancent depuis le clic droit « Actions CLI » d'une fiche ordinaire (elles travaillent sur sa sélection ou y insèrent leur sortie).
    Double-clic ou clic droit : ajouter, modifier, supprimer, déplacer, importer, exporter. Fiche non validée : lisible, rien ne se modifie."""
    modifie = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.liste = QListWidget()
        self.liste.setIconSize(QSize(24, 24))
        self.liste.itemDoubleClicked.connect(lambda it: self._modifier(self.liste.row(it)))
        lay.addWidget(self.liste, 1)
        self.aide = QLabel()
        self.aide.setWordWrap(True)
        lay.addWidget(self.aide)
        self.actions: list = []
        self._actif = True
        self._texte_aide()

    @property
    def actif(self) -> bool:
        return self._actif

    @actif.setter
    def actif(self, oui: bool) -> None:
        """Faux : fiche non validée. La liste se lit (pour relire les commandes avant de valider) mais ne se modifie pas."""
        self._actif = bool(oui)
        self._texte_aide()

    def _texte_aide(self):
        self.aide.setText(_("Clic droit : ajouter, modifier, déplacer… Pour lancer une action : clic droit dans une fiche → « Actions CLI ».")
                          if self._actif else
                          _("Fiche non validée : relisez les commandes (infobulles), puis validez-la pour pouvoir l'utiliser et la modifier."))

    def charger(self, texte: str):
        self.definir(logique.depuis_texte(texte))

    def definir(self, actions: list):
        self.actions = logique.normaliser_liste(actions)
        self._remplir()

    def _remplir(self, ligne=None):
        self.liste.clear()
        for a in self.actions:
            it = QListWidgetItem(icone_action(a["icone"]), f"{a['nom']}   ·   {_(logique.MODES[a['mode']])}")
            it.setToolTip(info_action(a))
            self.liste.addItem(it)
        if ligne is not None and 0 <= ligne < len(self.actions):
            self.liste.setCurrentRow(ligne)

    def _enregistrer(self, ligne=None):
        self.modifie.emit(logique.en_texte(self.actions))
        self._remplir(ligne)

    # ---------- clic droit ----------
    def entrees_menu(self, pos) -> list:
        """Entrées du clic droit (la fenêtre y ajoute celles des extensions) ; `pos` : position dans cette vue."""
        if not self._actif:
            return []
        it = self.liste.itemAt(self.liste.viewport().mapFrom(self, pos))
        i = self.liste.row(it) if it is not None else -1
        e = [(_("Ajouter une action…"), lambda *_a: self._ajouter(), "list-add")]
        if i >= 0:
            e += [(_("Modifier…"), lambda *_a, i=i: self._modifier(i), "document-edit"),
                  (_("Supprimer"), lambda *_a, i=i: self._supprimer(i), "edit-delete"),
                  (_("Monter"), lambda *_a, i=i: self._deplacer(i, -1), "go-up"),
                  (_("Descendre"), lambda *_a, i=i: self._deplacer(i, 1), "go-down")]
        return e + [(_("Ajouter les exemples…"), lambda *_a: self._exemples(), "view-list-icons"),
                    (_("Exporter…"), lambda *_a: self._exporter(), "document-export"),
                    (_("Importer…"), lambda *_a: self._importer(), "document-import")]

    def _ajouter(self):
        d = DialogueAction(None, self)
        if d.exec() and d.resultat():
            self.actions.append(d.resultat())
            self._enregistrer(len(self.actions) - 1)

    def _modifier(self, i: int):
        if self._actif and 0 <= i < len(self.actions):
            d = DialogueAction(self.actions[i], self)
            if d.exec() and d.resultat():
                self.actions[i] = d.resultat()
                self._enregistrer(i)

    def _supprimer(self, i: int):
        if self._actif and 0 <= i < len(self.actions):
            del self.actions[i]
            self._enregistrer(min(i, len(self.actions) - 1))

    def _deplacer(self, i: int, sens: int):
        j = i + sens
        if self._actif and 0 <= i < len(self.actions) and 0 <= j < len(self.actions):
            self.actions[i], self.actions[j] = self.actions[j], self.actions[i]
            self._enregistrer(j)

    def _exemples(self):
        rep = QMessageBox.question(self, _("Exemples"), _("Ajouter les actions CLI d'exemple à la fin de la liste ? "
                                                         "(Aucune n'est lancée.)"))
        if rep == QMessageBox.StandardButton.Yes:
            self.actions += [dict(a) for a in logique.EXEMPLES]
            self.actions = logique.normaliser_liste(self.actions)
            self._enregistrer(len(self.actions) - 1)

    def _exporter(self):
        chemin, _f = QFileDialog.getSaveFileName(self, _("Exporter les actions CLI"), "actions-scrinium.json", "JSON (*.json)")
        if chemin:
            try:
                Path(chemin).write_text(logique.exporter_actions(self.actions), encoding="utf-8")
            except OSError as ex:
                QMessageBox.warning(self, _("Actions CLI"), str(ex))

    def _importer(self):
        chemin, _f = QFileDialog.getOpenFileName(self, _("Importer des actions CLI"), "", "JSON (*.json)")
        if not chemin:
            return
        try:
            nouvelles = logique.importer_actions(Path(chemin).read_text(encoding="utf-8"))
        except (OSError, ValueError) as ex:
            QMessageBox.warning(self, _("Actions CLI"), str(ex))
            return
        if QMessageBox.question(self, _("Importer"), _("Ajouter %d action(s) CLI à la liste ? Relisez leurs commandes avant de les "
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
        ctx.ajouter_doc(_('Extension Capture et console'), DOC)
        self.cible = None          # console choisie à la main (service, session) : gardée tant qu'elle existe
        self.pid_dedie = None      # PID de la Konsole ouverte par l'extension
        self.refus_vu = False      # Konsole a refusé l'envoi : on n'ouvre plus de console pour rien (remis à zéro par les réglages)
        if ctx.ui is None:
            return
        ctx.ui.enregistrer_type(logique.TYPE, VueActions())
        ctx.ui.ajouter_sous_menu_fiche(_("Actions CLI"), self.entrees_actions, "utilities-terminal")
        ctx.ui.ajouter_bouton(_("Console"), self.vers_console, "utilities-terminal")
        ctx.ui.ajouter_action(_("Envoyer la sélection vers une console"), self.vers_console, "utilities-terminal")
        ctx.ui.ajouter_action(_("Choisir la console cible…"), self.choisir_cible, "utilities-terminal")
        ctx.ui.ajouter_action(_("Revenir à la console de l'extension"), self.oublier_cible, "utilities-terminal")
        ctx.ui.ajouter_action(_("Exécuter une commande et insérer la sortie…"), self.commande, "system-run")
        ctx.ui.ajouter_action(_("Fiche des actions CLI…"), self.modifier_actions, "view-list-icons")
        ctx.ui.ajouter_action(_("Réglages de la capture…"), self.reglages, "configure")
        self._migrer()

    def entrees_actions(self) -> list:
        """Sous-menu « Actions CLI » du clic droit d'une fiche : les actions des fiches validées (lues à chaque ouverture du menu)."""
        return [(a["nom"], lambda a=a: self._lancer_si_presente(a), a["icone"] or "system-run") for a in self.actions()]

    def _lancer_si_presente(self, a: dict):
        """Entrée choisie dans le menu : on relit la liste avant de lancer (la fiche a pu changer ou perdre sa validation entre-temps)."""
        if a in self.actions():
            self.lancer_action(a)

    # ---------- actions préparées ----------
    THEME = "Outils"                           # thème de la fiche créée à la migration ou par « Fiche des actions CLI… »

    def _liste(self) -> ListeDeFiches:
        return ListeDeFiches(self.ctx, logique.TYPE, logique.normaliser_liste, logique.depuis_texte, logique.en_texte, "actions",
                             lambda: [dict(a) for a in logique.EXEMPLES], _("Actions CLI"), self.THEME, logique.MAX_ACTIONS)

    def actions(self) -> list:
        """Actions du menu « Actions CLI » : celles des fiches « actions CLI » VALIDÉES (sans doublon) ; tant qu'il n'y en a aucune, les réglages d'avant
        « tout est fiche », puis, sans réglage, les exemples."""
        return self._liste().elements()

    def a_valider(self) -> int:
        """Nombre de fiches « actions CLI » en attente de validation (reçues, ou modifiées ailleurs)."""
        return self._liste().a_valider()

    def _migrer(self):
        """Les actions d'avant « tout est fiche » (réglages) deviennent une fiche, une seule fois ; les réglages restent comme copie.
        La fiche créée est inerte : l'utilisateur la valide (bandeau), en attendant le menu garde l'ancienne liste."""
        if self._liste().migrer() is not None:
            self.ctx.ui.actualiser()
            self.ctx.ui.notifier(_("Actions CLI"), _("Vos actions CLI sont maintenant une fiche « Actions CLI » (thème « %s ») : ouvrez-la "
                                                    "et validez-la.") % self.THEME)

    def modifier_actions(self):
        """Ouvre la fiche des actions ; sans fiche, la crée à partir de la liste actuelle (à valider ensuite)."""
        vue, creee = self._liste().a_ouvrir()
        if creee:
            self.ctx.ui.actualiser()
            self.ctx.ui.notifier(_("Actions CLI"), _("Fiche « Actions CLI » créée : validez-la pour qu'elle serve au menu « Actions CLI »."))
        self.ctx.ui.afficher_fiche(vue)

    def lancer_action(self, a: dict):
        """Selon le mode, tape (sans valider), propose d'exécuter, ou copie."""
        selection = self.ctx.ui.texte_selectionne()
        vue = self.ctx.fiche_courante()
        if logique.utilise_selection(a["commande"]) and not selection.strip():
            self.ctx.ui.notifier(_("Actions CLI"), _("Sélectionnez d'abord du texte dans la fiche : « %s » en a besoin.") % a["nom"])
            return
        cmd = logique.etendre(a["commande"], selection, vue.titre if vue else "", a["mode"])
        if a["mode"] == "executer":
            if vue is None:
                self.ctx.ui.notifier(_("Actions CLI"), _("Ouvrez d'abord une fiche : la sortie y sera insérée."))
                return
            DialogueCommande(self, _parent(), commande=cmd).exec()      # la commande s'affiche ; rien ne part sans clic
        elif a["mode"] == "copier":
            QApplication.clipboard().setText(cmd)
            self.ctx.ui.notifier(_("Actions CLI"), _("Copié dans le presse-papiers : « %s ».") % a["nom"])
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
        self.ctx.ui.notifier(_("Console"), _("Copié dans le presse-papiers (Konsole n'accepte pas l'envoi direct) : collez dans votre console avec Ctrl+Maj+V, "
                                                    "rien n'est validé. Pour l'envoi direct : Konsole → Configuration → Configurer Konsole → Général → "
                                                    "cocher « Enable the security sensitive parts of the DBus API »."))

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
                        self._aide_refus()
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
            self._aide_refus()
            return False
        except Exception as ex:
            self.ctx.ui.notifier(_("Console"), _("Konsole : %s") % ex)
            return False
        if self.ctx.reglages.get("premier_plan", True):
            logique.mettre_au_premier_plan(qdbus, choix[0])
        self.ctx.ui.notifier(_("Console"), (_("Console ouverte : ") if neuve else "")
                             + _("texte tapé dans « %s » (non validé : relisez, puis Entrée).") % choix[2])
        return True

    def _aide_refus(self):
        """Explique pourquoi aucune console ne s'ouvre (rappelé à chaque fois, sauf si l'utilisateur l'a masqué)."""
        if self.ctx.reglages.get("aide_masquee", False):
            return
        boite = QMessageBox(QMessageBox.Icon.Information, _("Console"), AIDE_KONSOLE, QMessageBox.StandardButton.Ok, _parent())
        case = QCheckBox(_("Ne plus afficher ce message"))
        boite.setCheckBox(case)
        boite.exec()
        if case.isChecked():
            self.ctx.reglages.set("aide_masquee", True)

    def _choisir(self, sessions, forcer=False):
        if len(sessions) == 1 and not forcer:
            return sessions[0]
        libelles = [f"{lib}   (n° {service.rsplit('-', 1)[-1]}/{n})" for service, n, lib in sessions]
        defaut = next((i for i, x in enumerate(sessions) if x[:2] == self.cible), 0)
        choix, ok = QInputDialog.getItem(_parent(), _("Console"), _("Envoyer vers quelle console ?"), libelles, defaut, False)
        return sessions[libelles.index(choix)] if ok else None


DOC = _(
    'Relie vos fiches au terminal, sans jamais rien valider à votre place (voir aussi « Guide 5 »).\n'
    '\n'
    '• Bouton « Console » : le texte sélectionné est tapé dans une Konsole « Scrinium », sans Entrée. Il faut cocher dans Konsole « Enable the security sensitive parts of the DBus API » ; sinon le texte est copié (collez avec Ctrl+Maj+V).\n'
    '• « Choisir la console cible… » : envoyer vers une autre Konsole déjà ouverte.\n'
    '• « Exécuter une commande et insérer la sortie… » : la commande est lancée après confirmation, sa sortie est insérée au curseur dans un bloc daté.\n'
    "• Fiches « Actions CLI » : des commandes à lancer d'un clic ; type exécutable, donc inerte tant que la fiche n'est pas validée.\n"
    '• Depuis un terminal : « ls -al | scrinium ajouter -t Thème -f Fiche ».')

# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « Capture et console ».

- Exécuter une commande… : la sortie s'affiche, puis s'insère au curseur de la fiche (bloc daté, comme `scrinium ajouter`).
  La commande n'est lancée que sur votre demande, avec un délai maximal et une taille de sortie limitée.
- Console : envoie le texte sélectionné dans la fiche vers une console. L'extension ouvre sa propre Konsole (titrée
  « Scrinium »), la réutilise toujours, et la rouvre si vous l'avez fermée. Le texte y est tapé SANS être validé (vous
  relisez, puis Entrée) ; il faut pour cela activer dans Konsole « Enable the security sensitive parts of the DBus API ».
  Sinon, ou ailleurs que sous Konsole : le texte est copié dans le presse-papiers. « Choisir la console cible… » permet
  d'utiliser à la place une de vos consoles existantes.
Le pendant « fiche -> commande » (`ip a | scrinium ajouter …`) est dans le cœur : `scrinium ajouter`.
"""
import threading
import time

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import (QApplication, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QInputDialog,
                             QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout)

from scrinium.core import capture
from scrinium.core.plugins import Plugin
from scrinium.i18n import _

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

    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.p = plugin
        self.resultat = None
        self.setWindowTitle(_("Exécuter une commande"))
        self.resize(640, 420)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(_("La commande est lancée par votre shell, uniquement quand vous cliquez sur « Exécuter » "
                               "(délai maximal : %d s).") % logique.DELAI_COMMANDE))
        ligne = QHBoxLayout()
        self.commande = QLineEdit(plugin.ctx.reglages.get("derniere", ""))
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


class DialogueReglages(QDialog):
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.p = plugin
        self.setWindowTitle(_("Réglages de la capture"))
        f = QFormLayout(self)
        self.direct = QCheckBox(_("Essayer d'abord de taper directement dans Konsole (sans valider)"))
        self.direct.setChecked(bool(plugin.ctx.reglages.get("direct", True)))
        f.addRow(self.direct)
        aide = QLabel(AIDE_KONSOLE)
        aide.setWordWrap(True)
        f.addRow(aide)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        b.accepted.connect(self._valider)
        b.rejected.connect(self.reject)
        f.addRow(b)

    def _valider(self):
        self.p.ctx.reglages.set("direct", self.direct.isChecked())
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
        texte = logique.nettoyer_pour_console(brut)
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

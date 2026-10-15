"""Création du fichier de secours : en mots simples, avec un nom que l'utilisateur reconnaît."""
import getpass
import time
from pathlib import Path

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                             QMessageBox, QPushButton, QVBoxLayout)

from ..core import recovery
from ..core.store import Store
from ..i18n import _
from .icons import icone


def dossier_par_defaut() -> Path:
    d = Path.home() / "Documents"
    return d if d.is_dir() else Path.home()


def nom_par_defaut() -> str:
    return f"Scrinium-secours-{getpass.getuser()}-{time.strftime('%Y-%m-%d')}"


class AssistantCle(QDialog):
    """Crée le fichier de secours. `remplacer` : il en existe déjà un, le nouveau le remplace pour les futures fiches."""

    def __init__(self, store: Store, parent=None, remplacer: bool = False):
        super().__init__(parent)
        self.store, self.remplacer = store, remplacer
        self.setWindowTitle(_("Fichier de secours"))
        self.setMinimumWidth(540)
        lay = QVBoxLayout(self)
        texte = _(
            "Si vous oubliez le mot de passe d'une fiche verrouillée, la fiche est perdue.\n\n"
            "Le fichier de secours est un filet de sécurité : il permet de rouvrir vos fiches verrouillées sans leur "
            "mot de passe. Il est créé une seule fois, maintenant.\n\n"
            "Gardez-le AILLEURS que sur cet ordinateur (clé USB, courriel à vous-même, gestionnaire de mots de passe). "
            "Scrinium n'en garde pas de copie : si vous le perdez, il ne pourra pas être refait pour les fiches déjà "
            "verrouillées.")
        if remplacer:
            texte += _("\n\nUn fichier de secours existe déjà. Le nouveau servira pour les fiches verrouillées À PARTIR "
                       "DE MAINTENANT ; les fiches déjà verrouillées ne s'ouvrent qu'avec l'ancien fichier.")
        lab = QLabel(texte)
        lab.setWordWrap(True)
        lay.addWidget(lab)

        form = QFormLayout()
        self.e_nom = QLineEdit(nom_par_defaut())
        self.e_nom.setToolTip(_("Choisissez un nom que vous reconnaîtrez plus tard (le suffixe .pem est ajouté)."))
        form.addRow(_("Nom du fichier :"), self.e_nom)
        self.e_dossier = QLineEdit(str(dossier_par_defaut()))
        b = QPushButton(icone("document-save"), _("Choisir…"))
        b.clicked.connect(self._choisir)
        ligne = QHBoxLayout()
        ligne.addWidget(self.e_dossier)
        ligne.addWidget(b)
        form.addRow(_("Enregistrer dans le dossier :"), ligne)
        self.e_p1 = QLineEdit()
        self.e_p1.setEchoMode(QLineEdit.EchoMode.Password)
        self.e_p2 = QLineEdit()
        self.e_p2.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(_("Mot de passe du fichier (facultatif) :"), self.e_p1)
        form.addRow(_("Confirmer le mot de passe :"), self.e_p2)
        lay.addLayout(form)
        astuce = QLabel(_("Un mot de passe sur le fichier ajoute une protection si on vous le vole : il faudra alors "
                          "ce mot de passe pour s'en servir. Notez-le : lui non plus ne se retrouve pas."))
        astuce.setWordWrap(True)
        lay.addWidget(astuce)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(_("Créer le fichier de secours"))
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText(_("Plus tard"))
        bb.accepted.connect(self._valider)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _choisir(self):
        d = QFileDialog.getExistingDirectory(self, _("Dossier du fichier de secours"), self.e_dossier.text())
        if d:
            self.e_dossier.setText(d)

    def _valider(self):
        if self.e_p1.text() != self.e_p2.text():
            QMessageBox.warning(self, _("Mot de passe"), _("Les deux saisies sont différentes."))
            return
        nom = self.e_nom.text().strip().replace("/", "-").replace("\\", "-") or nom_par_defaut()
        if not nom.lower().endswith(".pem"):
            nom += ".pem"
        dossier = Path(self.e_dossier.text()).expanduser()
        chemin = dossier / nom
        pub = self.store.paths.recovery_pub
        ancienne = None
        try:
            if self.remplacer and pub.exists():   # on garde l'ancienne clé publique à côté, au cas où
                ancienne = pub.with_name(f"recovery-{time.strftime('%Y%m%d-%H%M%S')}.pub.ancienne")
                pub.rename(ancienne)
            recovery.generer_paire(chemin, pub, self.e_p1.text() or None)
        except FileExistsError:
            if ancienne:
                ancienne.rename(pub)
            QMessageBox.warning(self, _("Fichier de secours"),
                                _("Un fichier porte déjà ce nom dans ce dossier : choisissez un autre nom."))
            return
        except OSError as ex:
            if ancienne and not pub.exists():
                ancienne.rename(pub)
            QMessageBox.critical(self, _("Fichier de secours"), str(ex))
            return
        self.store.sauver_reglages(recovery_asked=True)
        m = QMessageBox(self)
        m.setIcon(QMessageBox.Icon.Information)
        m.setWindowTitle(_("Fichier de secours créé"))
        m.setText(_("Votre fichier de secours est prêt :\n\n%s\n\nCopiez-le MAINTENANT hors de cet ordinateur "
                    "(clé USB, courriel, gestionnaire de mots de passe).") % chemin)
        ouvrir = m.addButton(_("Ouvrir le dossier"), QMessageBox.ButtonRole.ActionRole)
        m.addButton(QMessageBox.StandardButton.Ok)
        m.exec()
        if m.clickedButton() is ouvrir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(dossier)))
        self.accept()

"""Assistant de première utilisation : clé de secours facultative, propre à l'utilisateur."""
from pathlib import Path

from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                             QMessageBox, QPushButton, QRadioButton, QVBoxLayout)

from ..core import recovery
from ..core.store import Store
from ..i18n import _
from .icons import icone


class AssistantCle(QDialog):
    def __init__(self, store: Store, parent=None, premiere_fois: bool = True):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle(_("Clé de secours"))
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        intro = _("Chaque fiche peut être verrouillée par un mot de passe.\n\n"
                  "Si vous l'oubliez, la fiche est perdue, sauf si vous créez une clé de secours : "
                  "une clé personnelle, générée ici, qui permet de rouvrir vos fiches verrouillées. "
                  "Gardez-la hors de cet ordinateur (clé USB, gestionnaire de mots de passe).")
        if premiere_fois:
            intro = _("Bienvenue dans Scrinium.\n\n") + intro
        lab = QLabel(intro)
        lab.setWordWrap(True)
        lay.addWidget(lab)
        self.r_oui = QRadioButton(_("Créer une clé de secours (recommandé)"))
        self.r_non = QRadioButton(_("Pas de clé de secours : mot de passe oublié = fiche irrécupérable"))
        self.r_oui.setChecked(True)
        lay.addWidget(self.r_oui)
        lay.addWidget(self.r_non)

        form = QFormLayout()
        self.e_chemin = QLineEdit(str(store.paths.base / "cle-de-secours.pem"))
        b = QPushButton(icone("document-save"), _("Choisir…"))
        b.clicked.connect(self._choisir)
        ligne = QHBoxLayout()
        ligne.addWidget(self.e_chemin)
        ligne.addWidget(b)
        form.addRow(_("Enregistrer la clé privée dans :"), ligne)
        self.e_p1 = QLineEdit()
        self.e_p1.setEchoMode(QLineEdit.EchoMode.Password)
        self.e_p2 = QLineEdit()
        self.e_p2.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(_("Phrase secrète (facultative, conseillée) :"), self.e_p1)
        form.addRow(_("Confirmer la phrase secrète :"), self.e_p2)
        self.zone = form
        lay.addLayout(form)
        self.r_non.toggled.connect(self._etat)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._valider)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _etat(self):
        for i in range(self.zone.rowCount()):
            for role in (QFormLayout.ItemRole.LabelRole, QFormLayout.ItemRole.FieldRole):
                it = self.zone.itemAt(i, role)
                if it is None:
                    continue
                if it.widget():
                    it.widget().setEnabled(not self.r_non.isChecked())
                elif it.layout():
                    for k in range(it.layout().count()):
                        it.layout().itemAt(k).widget().setEnabled(not self.r_non.isChecked())

    def _choisir(self):
        f, _ok = QFileDialog.getSaveFileName(self, _("Clé privée de secours"), self.e_chemin.text(), "PEM (*.pem)")
        if f:
            self.e_chemin.setText(f)

    def _valider(self):
        if self.r_non.isChecked():
            self.store.sauver_reglages(recovery_asked=True)
            self.accept()
            return
        if self.e_p1.text() != self.e_p2.text():
            QMessageBox.warning(self, _("Phrase secrète"), _("Les deux saisies sont différentes."))
            return
        chemin = Path(self.e_chemin.text()).expanduser()
        try:
            recovery.generer_paire(chemin, self.store.paths.recovery_pub, self.e_p1.text() or None)
        except FileExistsError:
            QMessageBox.warning(self, _("Clé de secours"), _("Ce fichier existe déjà : choisissez un autre nom."))
            return
        except OSError as ex:
            QMessageBox.critical(self, _("Clé de secours"), str(ex))
            return
        self.store.sauver_reglages(recovery_asked=True)
        QMessageBox.information(
            self, _("Clé de secours créée"),
            _("Clé privée : %s\n\nCopiez-la maintenant hors de cet ordinateur. "
              "Sans elle, un mot de passe oublié rend la fiche irrécupérable.") % chemin)
        self.accept()

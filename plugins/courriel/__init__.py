# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « Envoi par courriel » : envoie la fiche affichée à une ou plusieurs adresses du carnet.

- Bouton « Envoyer par courriel » (barre d'outils et menu Extensions), carnet d'adresses, réglages du serveur SMTP.
- Une fiche verrouillée fermée n'est jamais envoyée ; une fiche verrouillée ouverte part EN CLAIR (avertissement + accord).
- Rien ne part sans clic sur « Envoyer » après récapitulatif des destinataires.
- Mot de passe SMTP : trousseau du système si le module `keyring` est présent, sinon gardé en mémoire pour la session,
  ou (case à cocher explicite) dans un fichier réservé à l'utilisateur, non chiffré.
"""
import os
import threading

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                             QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit,
                             QPushButton, QSpinBox, QVBoxLayout)

from scrinium.core.plugins import Plugin
from scrinium.i18n import _

from . import logique

SERVICE = "scrinium-courriel"


def _parent():
    return QApplication.activeWindow()


class _Pont(QObject):
    """Ramène dans le fil de l'interface le résultat du fil d'envoi."""
    fini = pyqtSignal(str, str)      # (message, erreur)


class _Secret:
    """Mot de passe SMTP : trousseau (keyring) > fichier 0600 (si demandé) > mémoire de la session."""

    def __init__(self, dossier):
        self.fichier = dossier / "mot-de-passe"
        self.session = None

    @staticmethod
    def _cle(smtp):
        return f"{smtp.get('utilisateur', '')}@{smtp.get('hote', '')}"

    def lire(self, smtp):
        if self.session is not None:
            return self.session
        try:
            import keyring
            v = keyring.get_password(SERVICE, self._cle(smtp))
            if v is not None:
                return v
        except Exception:
            pass
        try:
            return self.fichier.read_text(encoding="utf-8").rstrip("\n")
        except OSError:
            return None

    def ecrire(self, smtp, mdp, retenir):
        self.session = mdp
        self.effacer(smtp, garder_session=True)
        if not retenir:
            return
        try:
            import keyring
            keyring.set_password(SERVICE, self._cle(smtp), mdp)
            return
        except Exception:
            pass
        self.fichier.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.fichier, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(mdp + "\n")

    def effacer(self, smtp, garder_session=False):
        if not garder_session:
            self.session = None
        try:
            import keyring
            keyring.delete_password(SERVICE, self._cle(smtp))
        except Exception:
            pass
        try:
            self.fichier.unlink()
        except OSError:
            pass


class DialogueServeur(QDialog):
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.p = plugin
        self.setWindowTitle(_("Serveur d'envoi (SMTP)"))
        s = plugin.smtp()
        f = QFormLayout(self)
        self.hote = QLineEdit(s.get("hote", ""))
        self.hote.setPlaceholderText("smtp.exemple.fr")
        self.securite = QComboBox()
        for cle, (libelle, _port) in logique.SECURITES.items():
            self.securite.addItem(_(libelle), cle)
        self.securite.setCurrentIndex(max(0, self.securite.findData(s.get("securite", "starttls"))))
        self.port = QSpinBox(minimum=1, maximum=65535)
        self.port.setValue(int(s.get("port") or logique.SECURITES[self.securite.currentData()][1]))
        self.securite.currentIndexChanged.connect(lambda: self.port.setValue(logique.SECURITES[self.securite.currentData()][1]))
        self.user = QLineEdit(s.get("utilisateur", ""))
        self.mdp = QLineEdit()
        self.mdp.setEchoMode(QLineEdit.EchoMode.Password)
        self.mdp.setPlaceholderText(_("(inchangé)") if plugin.secret.lire(s) is not None else "")
        self.retenir = QCheckBox(_("Mémoriser le mot de passe"))
        self.retenir.setChecked(bool(s.get("retenir")))
        self.retenir.setToolTip(_("Trousseau du système si disponible ; sinon fichier réservé à votre utilisateur, NON chiffré."))
        self.exp = QLineEdit(s.get("expediteur", ""))
        self.nom = QLineEdit(s.get("nom", ""))
        f.addRow(_("Serveur :"), self.hote)
        f.addRow(_("Sécurité :"), self.securite)
        f.addRow(_("Port :"), self.port)
        f.addRow(_("Identifiant :"), self.user)
        f.addRow(_("Mot de passe :"), self.mdp)
        f.addRow("", self.retenir)
        f.addRow(_("Adresse d'expédition :"), self.exp)
        f.addRow(_("Nom affiché :"), self.nom)
        self.etat = QLabel("")
        self.etat.setWordWrap(True)
        f.addRow(self.etat)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        test = b.addButton(_("Tester la connexion"), QDialogButtonBox.ButtonRole.ActionRole)
        test.clicked.connect(self._tester)
        b.accepted.connect(self._valider)
        b.rejected.connect(self.reject)
        f.addRow(b)

    def _valeurs(self):
        return {"hote": self.hote.text().strip(), "securite": self.securite.currentData(), "port": self.port.value(),
                "utilisateur": self.user.text().strip(), "expediteur": self.exp.text().strip(),
                "nom": self.nom.text().strip(), "retenir": self.retenir.isChecked()}

    def _mdp_saisi(self, v):
        return self.mdp.text() or self.p.secret.lire(v)

    def _tester(self):
        v = self._valeurs()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            logique.tester(v, self._mdp_saisi(v))
            self.etat.setText(_("✔ Connexion réussie."))
        except Exception as ex:
            self.etat.setText(f"⚠ {type(ex).__name__}: {ex}")
        finally:
            QApplication.restoreOverrideCursor()

    def _valider(self):
        v = self._valeurs()
        if v["expediteur"] and not logique.adresse_valide(v["expediteur"]):
            QMessageBox.warning(self, _("Serveur d'envoi"), _("Adresse d'expédition invalide."))
            return
        if v["utilisateur"] and v["securite"] == "aucune":
            QMessageBox.warning(self, _("Serveur d'envoi"), _("Un identifiant exige un canal chiffré (STARTTLS ou SSL/TLS)."))
            return
        self.p.ctx.reglages.set("smtp", v)
        if self.mdp.text():
            self.p.secret.ecrire(v, self.mdp.text(), v["retenir"])
        elif not v["retenir"]:
            self.p.secret.effacer(v, garder_session=True)
        self.accept()


class DialogueCarnet(QDialog):
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.p = plugin
        self.setWindowTitle(_("Carnet d'adresses"))
        self.resize(420, 340)
        lay = QVBoxLayout(self)
        self.liste = QListWidget()
        lay.addWidget(self.liste, 1)
        bas = QHBoxLayout()
        for texte, fn in ((_("Ajouter…"), self._ajouter), (_("Modifier…"), self._modifier), (_("Supprimer"), self._supprimer)):
            b = QPushButton(texte)
            b.clicked.connect(fn)
            bas.addWidget(b)
        bas.addStretch()
        f = QPushButton(_("Fermer"))
        f.clicked.connect(self.accept)
        bas.addWidget(f)
        lay.addLayout(bas)
        self._remplir()

    def _remplir(self):
        self.liste.clear()
        for c in self.p.carnet():
            self.liste.addItem(f"{c['nom']} <{c['adresse']}>" if c["nom"] else c["adresse"])

    def _saisir(self, nom="", adresse=""):
        d = QDialog(self)
        d.setWindowTitle(_("Contact"))
        f = QFormLayout(d)
        n, a = QLineEdit(nom), QLineEdit(adresse)
        f.addRow(_("Nom :"), n)
        f.addRow(_("Adresse :"), a)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        b.accepted.connect(d.accept)
        b.rejected.connect(d.reject)
        f.addRow(b)
        while d.exec():
            if logique.adresse_valide(a.text()):
                return n.text().strip(), a.text().strip()
            QMessageBox.warning(d, _("Contact"), _("Adresse invalide."))
        return None

    def _ajouter(self):
        r = self._saisir()
        if r:
            c = self.p.carnet()
            c.append({"nom": r[0], "adresse": r[1]})
            self.p.sauver_carnet(c)
            self._remplir()

    def _modifier(self):
        i = self.liste.currentRow()
        if i < 0:
            return
        c = self.p.carnet()
        r = self._saisir(c[i]["nom"], c[i]["adresse"])
        if r:
            c[i] = {"nom": r[0], "adresse": r[1]}
            self.p.sauver_carnet(c)
            self._remplir()

    def _supprimer(self):
        i = self.liste.currentRow()
        if i >= 0:
            c = self.p.carnet()
            del c[i]
            self.p.sauver_carnet(c)
            self._remplir()


class DialogueEnvoi(QDialog):
    def __init__(self, plugin, vue, parent=None):
        super().__init__(parent)
        self.p, self.vue = plugin, vue
        self.setWindowTitle(_("Envoyer la fiche par courriel"))
        self.resize(520, 560)
        lay = QVBoxLayout(self)
        if vue.verrou:
            av = QLabel(_("⚠ Cette fiche est verrouillée : son texte partira EN CLAIR dans le courriel."))
            av.setWordWrap(True)
            av.setStyleSheet("color:#c0392b")
            lay.addWidget(av)
        lay.addWidget(QLabel(_("Destinataires (carnet) :")))
        self.liste = QListWidget()
        derniers = {a.lower() for a in plugin.ctx.reglages.get("derniers", [])}
        for c in plugin.carnet():
            it = QListWidgetItem(f"{c['nom']} <{c['adresse']}>" if c["nom"] else c["adresse"])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if c["adresse"].lower() in derniers else Qt.CheckState.Unchecked)
            it.setData(Qt.ItemDataRole.UserRole, c["adresse"])
            self.liste.addItem(it)
        lay.addWidget(self.liste, 1)
        carnet = QPushButton(_("Gérer le carnet…"))
        carnet.clicked.connect(self._carnet)
        lay.addWidget(carnet, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(QLabel(_("Autres adresses (séparées par des virgules) :")))
        self.autres = QLineEdit()
        lay.addWidget(self.autres)
        lay.addWidget(QLabel(_("Objet :")))
        self.sujet = QLineEdit(vue.titre)
        lay.addWidget(self.sujet)
        self.corps = QPlainTextEdit(vue.texte or "")
        lay.addWidget(self.corps, 2)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.envoyer = b.addButton(_("Envoyer"), QDialogButtonBox.ButtonRole.AcceptRole)
        b.accepted.connect(self._valider)
        b.rejected.connect(self.reject)
        lay.addWidget(b)

    def _carnet(self):
        coches = set(self.coches())
        DialogueCarnet(self.p, self).exec()
        self.liste.clear()
        for c in self.p.carnet():
            it = QListWidgetItem(f"{c['nom']} <{c['adresse']}>" if c["nom"] else c["adresse"])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if c["adresse"] in coches else Qt.CheckState.Unchecked)
            it.setData(Qt.ItemDataRole.UserRole, c["adresse"])
            self.liste.addItem(it)

    def coches(self):
        return [self.liste.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.liste.count())
                if self.liste.item(i).checkState() == Qt.CheckState.Checked]

    def _valider(self):
        autres, invalides = logique.analyser_adresses(self.autres.text())
        if invalides:
            QMessageBox.warning(self, _("Adresses"), _("Adresse(s) invalide(s) : %s") % ", ".join(invalides))
            return
        self.destinataires = logique.fusionner(self.coches(), autres)
        if not self.destinataires:
            QMessageBox.warning(self, _("Adresses"), _("Choisissez au moins un destinataire."))
            return
        rep = QMessageBox.question(self, _("Confirmer l'envoi"),
                                   _("Envoyer « %s » à :\n\n%s") % (self.sujet.text(), "\n".join(self.destinataires)))
        if rep == QMessageBox.StandardButton.Yes:
            self.accept()


class CourrielPlugin(Plugin):
    api = 1

    def activer(self, ctx):
        self.ctx = ctx
        self.secret = _Secret(ctx.dossier_donnees)
        if ctx.ui is None:
            return
        self.pont = _Pont()
        self.pont.fini.connect(self._fini)
        ctx.ui.ajouter_action(_("Envoyer la fiche par courriel…"), self.envoyer, "mail-send")
        ctx.ui.ajouter_bouton(_("Envoyer par courriel"), self.envoyer, "mail-send")
        ctx.ui.ajouter_action(_("Carnet d'adresses…"), self.carnet_dialogue, "x-office-address-book")
        ctx.ui.ajouter_action(_("Serveur d'envoi…"), self.serveur_dialogue, "network-wired")

    # ---------- données ----------
    def smtp(self) -> dict:
        return dict(self.ctx.reglages.get("smtp", {}))

    def carnet(self) -> list:
        return [dict(c) for c in self.ctx.reglages.get("carnet", [])]

    def sauver_carnet(self, carnet):
        self.ctx.reglages.set("carnet", carnet)

    # ---------- actions ----------
    def carnet_dialogue(self):
        DialogueCarnet(self, _parent()).exec()

    def serveur_dialogue(self):
        return DialogueServeur(self, _parent()).exec()

    def envoyer(self):
        vue = self.ctx.fiche_courante()
        if vue is None:
            self.ctx.ui.notifier(_("Courriel"), _("Ouvrez d'abord une fiche."))
            return
        if vue.fermee:
            QMessageBox.warning(_parent(), _("Courriel"),
                                _("Cette fiche est verrouillée et fermée : déverrouillez-la d'abord. "
                                  "Son contenu n'est jamais envoyé sans que vous l'ayez ouverte."))
            return
        s = self.smtp()
        if not s.get("hote") or not s.get("expediteur"):
            QMessageBox.information(_parent(), _("Courriel"), _("Renseignez d'abord le serveur d'envoi."))
            if not self.serveur_dialogue():
                return
            s = self.smtp()
        if s.get("utilisateur") and self.secret.lire(s) is None:
            mdp, ok = QInputDialog.getText(_parent(), _("Courriel"), _("Mot de passe de %s :") % s["utilisateur"],
                                           QLineEdit.EchoMode.Password)
            if not ok:
                return
            self.secret.session = mdp
        d = DialogueEnvoi(self, vue, _parent())
        if not d.exec():
            return
        try:
            msg = logique.construire(s, d.destinataires, d.sujet.text(), d.corps.toPlainText())
        except ValueError as ex:
            QMessageBox.warning(_parent(), _("Courriel"), str(ex))
            return
        self.ctx.reglages.set("derniers", d.destinataires)
        self.ctx.ui.notifier(_("Courriel"), _("Envoi en cours…"))
        mdp = self.secret.lire(s)
        threading.Thread(target=self._envoyer_fil, args=(s, mdp, msg), daemon=True).start()

    def _envoyer_fil(self, s, mdp, msg):
        try:
            logique.envoyer(s, mdp, msg)
            self.pont.fini.emit(_("Fiche envoyée à %s.") % msg["To"], "")
        except Exception as ex:
            self.pont.fini.emit("", f"{type(ex).__name__}: {ex}")

    def _fini(self, ok, erreur):
        self.ctx.ui.notifier(_("Courriel"), ok if ok else _("Échec de l'envoi : %s") % erreur)
        if erreur:
            QMessageBox.warning(_parent(), _("Courriel"), _("Échec de l'envoi :\n%s") % erreur)

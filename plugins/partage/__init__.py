# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « Partage » : partage de fiches via un serveur Scrinium (dossier `serveur/` du dépôt).

- « Partager la fiche… » : droits des personnes, invitation par courriel (lien valable 48 h) ; la fiche est mise en ligne au premier partage.
- « Rejoindre un partage… » : coller le lien reçu ; crée le compte sur le serveur si besoin.
- « Synchroniser les partages » : à la demande (et, si réglé, à intervalle régulier). Les conflits gardent les DEUX versions.
- Les fiches verrouillées ne sont jamais partagées. Le mot de passe va au trousseau du système si on le demande, sinon il n'est gardé
  que pour la session. Certificat auto-signé : on épingle son empreinte après confirmation.
Les échanges réseau se font dans un fil à part (délai de 10 s) ; pendant l'attente, une fenêtre « Veuillez patienter » (affichée
après 0,4 s) bloque les autres actions mais la fenêtre reste vivante."""
import threading
from datetime import datetime
from urllib.parse import quote

from PyQt6.QtCore import QEventLoop, QObject, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QGuiApplication
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QInputDialog,
                             QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QProgressDialog, QPushButton,
                             QRadioButton, QSpinBox, QVBoxLayout)

from scrinium.core.depots import Depot, enregistrer_depot, lire_depots, supprimer_depot
from scrinium.core.plugins import Plugin
from scrinium.core.synchro import EtatSynchro, chemin_etat
from scrinium.core.synchroniser import partager, publier, synchroniser
from scrinium.core.transport import ErreurTransport, Injoignable, Introuvable, NonAuthentifie, Refuse
from scrinium.i18n import _

from . import logique, theme as themes
from .http import CertificatInconnu, ServeurIncompatible, TransportHttp, empreinte_serveur, formater_empreinte


def _parent():
    return QApplication.activeWindow()


def _heure(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return iso


class _Fin(QObject):
    fini = pyqtSignal()


_en_cours = []        # échanges en cours (le minuteur n'en lance pas un second par-dessus)


def en_fond(fn, message=None):
    """Exécute fn() dans un fil à part et rend son résultat (ou relève son exception) dans le fil de l'interface. L'interface reste
    vivante ; une fenêtre modale « patientez » n'apparaît qu'au-delà de 0,4 s, pour ne pas laisser agir l'utilisateur pendant l'échange."""
    res = {}
    fin = _Fin()
    boucle = QEventLoop()
    fin.fini.connect(boucle.quit)

    def travail():
        try:
            res["v"] = fn()
        except BaseException as ex:        # relevée dans le fil de l'interface
            res["e"] = ex
        fin.fini.emit()

    dlg = QProgressDialog(message or _("Échange avec le serveur de partage…"), None, 0, 0, _parent())
    dlg.setWindowTitle(_("Partage"))
    dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
    dlg.setMinimumDuration(400)
    dlg.setCancelButton(None)
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    _en_cours.append(1)
    try:
        threading.Thread(target=travail, daemon=True).start()
        boucle.exec()
    finally:
        _en_cours.pop()
        dlg.reset()
        dlg.deleteLater()
        QApplication.restoreOverrideCursor()
    if "e" in res:
        raise res["e"]
    return res.get("v")


class PartagePlugin(Plugin):
    api = 1

    def activer(self, ctx):
        self.ctx = ctx
        self.secret = logique.Secret()
        self.transports: dict = {}
        if ctx.ui is None:
            return
        ctx.ui.ajouter_action(_("Partager la fiche…"), self.partager_fiche, "document-share")
        ctx.ui.ajouter_action(_("Partager le thème…"), self.partager_theme, "folder-share")
        ctx.ui.ajouter_action(_("Rejoindre un partage…"), self.rejoindre, "list-add-user")
        ctx.ui.ajouter_action(_("Synchroniser les partages"), self.synchroniser_tout, "view-refresh")
        ctx.ui.ajouter_action(_("Serveurs de partage…"), self.serveurs, "preferences-system-network")
        self._armer_minuteur()

    def desactiver(self):
        self.transports.clear()

    # ---------- accès ----------
    @property
    def store(self):
        return self.ctx._g.store          # extension officielle : accède au cœur (publier / synchroniser)

    def _armer_minuteur(self):
        minutes = int(self.ctx.reglages.get("auto_minutes", 0) or 0)
        if getattr(self, "_minuteur", None) is not None:
            self._minuteur.stop()
            self._minuteur = None
        if minutes > 0 and self.ctx.ui is not None:
            self._minuteur = self.ctx.ui.planifier(minutes * 60, lambda: self.synchroniser_tout(silencieux=True), repeter=True)

    def depots(self) -> list:
        return lire_depots(self.store)

    def empreinte(self, nom: str):
        return self.ctx.reglages.get("empreintes", {}).get(nom)

    def _epingler(self, nom: str, empreinte):
        e = dict(self.ctx.reglages.get("empreintes", {}))
        if empreinte:
            e[nom] = empreinte
        else:
            e.pop(nom, None)
        self.ctx.reglages.set("empreintes", e)

    def _cle(self, depot) -> str:
        return f"{depot.compte}@{depot.url}"

    def _mdp(self, depot):
        """Mot de passe connu (appelé depuis le fil réseau : jamais de boîte de dialogue ici, voir `_demander_mdp`)."""
        return self.secret.lire(self._cle(depot))

    def _demander_mdp(self, depot) -> bool:
        """Dans le fil de l'interface, avant l'échange : demande le mot de passe s'il n'est pas connu. False si saisie annulée."""
        if self.secret.lire(self._cle(depot)) is not None:
            return True
        mdp, ok = QInputDialog.getText(_parent(), _("Partage"), _("Mot de passe de {compte} sur {url} :").format(
            compte=depot.compte, url=depot.url), QLineEdit.EchoMode.Password)
        if not ok or not mdp:
            return False
        self.secret.ecrire(self._cle(depot), mdp, False)
        return True

    def transport(self, depot) -> TransportHttp:
        t = self.transports.get(depot.nom)
        if t is None or t.url != depot.url or t.compte != depot.compte:
            t = TransportHttp(depot.url, depot.compte, lambda d=depot: self._mdp(d), self.empreinte(depot.nom))
            self.transports[depot.nom] = t
        return t

    def avertir(self, titre, texte):
        QMessageBox.warning(_parent(), titre, texte)

    def _erreur(self, ex, depot=None) -> None:
        """Message clair pour une erreur réseau ou de serveur."""
        if isinstance(ex, NonAuthentifie):
            if depot is not None:
                self.secret.effacer(self._cle(depot))
                self.transports.pop(depot.nom, None)
            self.avertir(_("Partage"), _("Compte ou mot de passe refusé par le serveur."))
        elif isinstance(ex, CertificatInconnu):
            self.avertir(_("Partage"), _("Le certificat du serveur n'est pas reconnu ou a changé :\n{m}\n\nPar prudence, rien n'a été envoyé. "
                                         "Vérifiez auprès de l'administrateur, puis réajoutez le serveur.").format(m=ex))
        elif isinstance(ex, Injoignable):
            self.avertir(_("Partage"), _("Serveur injoignable. Rien n'est perdu : réessayez plus tard.\n{m}").format(m=ex))
        elif isinstance(ex, ServeurIncompatible):
            self.avertir(_("Partage"), _("Ce serveur n'est pas compatible avec cette version de Scrinium.\n{m}").format(m=ex))
        elif isinstance(ex, Introuvable):
            self.avertir(_("Partage"), _("Introuvable (lien expiré, déjà utilisé, ou fiche plus partagée avec vous)."))
        elif isinstance(ex, Refuse):
            self.avertir(_("Partage"), _("Refusé par le serveur : {m}").format(m=str(ex) or _("droits insuffisants")))
        else:
            self.avertir(_("Partage"), str(ex) or type(ex).__name__)

    def faire(self, depot, fn):
        """Exécute fn(transport) ; en cas d'erreur, l'explique et retourne None (ErreurTransport) — ou lève les autres."""
        if not self._demander_mdp(depot):
            return None
        try:
            t = self.transport(depot)
            return en_fond(lambda: fn(t))
        except ErreurTransport as ex:
            if isinstance(ex, NonAuthentifie) and str(ex) == "mot de passe absent":
                return None                                   # saisie annulée par l'utilisateur
            self._erreur(ex, depot)
            return None

    def verifier_certificat(self, url: str):
        """Empreinte à épingler (str), None si le certificat est valable tel quel, False si l'utilisateur refuse ou si échec."""
        try:
            en_fond(TransportHttp(url, "").decouverte)
            return None
        except CertificatInconnu:
            pass
        except ErreurTransport as ex:
            self._erreur(ex)
            return False
        try:
            emp = en_fond(lambda: empreinte_serveur(url))
        except ErreurTransport as ex:
            self._erreur(ex)
            return False
        r = QMessageBox.question(_parent(), _("Certificat du serveur"), _(
            "Ce serveur utilise un certificat que votre système ne connaît pas (certificat auto-signé).\n\n"
            "Empreinte SHA-256 :\n{e}\n\nN'acceptez que si elle est identique à celle que vous a donnée l'administrateur du serveur. "
            "Scrinium ne se connectera ensuite qu'à ce certificat précis.\n\nFaire confiance à ce certificat ?").format(e=formater_empreinte(emp)))
        return emp if r == QMessageBox.StandardButton.Yes else False

    # ---------- synchronisation ----------
    def synchroniser_depot(self, depot, silencieux=False):
        etat = EtatSynchro(chemin_etat(self.store, depot.nom)).charger()
        suivis = self.themes_suivis(depot.nom)

        def passage(t):
            for nom in suivis:                      # nouvelles fiches d'un thème partagé : mises en ligne avec les droits communs
                th = self.store.theme(nom)
                if th is not None:
                    themes.propager(self.store, etat, t, th)
            return synchroniser(self.store, etat, t, depot.theme)
        bilan = self.faire(depot, passage)
        if bilan is None:
            return None
        self._rafraichir()
        self._resume(depot, bilan, silencieux)
        return bilan

    def _rafraichir(self):
        f = getattr(self.ctx.ui, "_f", None) if self.ctx.ui else None
        if f is not None:
            f.maj_themes()

    def _resume(self, depot, b, silencieux):
        lignes = []
        for libelle, liste in ((_("Reçues"), b.nouvelles), (_("Mises à jour"), b.recues), (_("Envoyées"), b.envoyees),
                               (_("Identiques des deux côtés"), b.alignees)):
            if liste:
                lignes.append("{} : {}".format(libelle, ", ".join(liste)))
        graves = []
        if b.conflits:
            graves.append(_("Conflits (votre version est gardée dans une copie « conflit », la version du serveur est reprise) :\n  ")
                          + "\n  ".join(f"{t} → {c}" for t, c in b.conflits))
        if b.ecartees:
            graves.append(_("Modifications refusées (lecture seule), gardées dans une copie :\n  ") + "\n  ".join(f"{t} → {c}" for t, c in b.ecartees))
        if b.disparues:
            graves.append(_("N'existent plus sur le serveur (gardées ici, plus partagées) : ") + ", ".join(b.disparues))
        if b.supprimees_ici:
            graves.append(_("Supprimées ici mais toujours sur le serveur (rien n'est supprimé là-bas) : ") + ", ".join(b.supprimees_ici))
        if b.erreurs:
            graves.append(_("Erreurs :\n  ") + "\n  ".join(f"{t} : {m}" for t, m in b.erreurs))
        if graves:
            QMessageBox.warning(_parent(), _("Partage — {nom}").format(nom=depot.nom), "\n\n".join(lignes + graves))
        elif lignes:
            if self.ctx.ui:
                self.ctx.ui.notifier(_("Partage"), "; ".join(lignes))
        elif not silencieux and self.ctx.ui:
            self.ctx.ui.notifier(_("Partage"), _("Tout est à jour."))

    def synchroniser_tout(self, silencieux=False):
        if silencieux and _en_cours:
            return
        depots = self.depots()
        if not depots and not silencieux:
            QMessageBox.information(_parent(), _("Partage"), _("Aucun serveur de partage. Utilisez « Rejoindre un partage… » ou « Serveurs de partage… »."))
        for d in depots:
            self.synchroniser_depot(d, silencieux)

    # ---------- actions ----------
    def serveurs(self):
        DialogueServeurs(self).exec()

    def partager_fiche(self):
        vue = self.ctx.fiche_courante()
        if vue is None:
            QMessageBox.information(_parent(), _("Partage"), _("Ouvrez d'abord la fiche à partager."))
            return
        if vue.verrou:
            QMessageBox.information(_parent(), _("Partage"), _("Une fiche verrouillée ne se partage pas. Déverrouillez-la d'abord, ou copiez son contenu dans une autre fiche."))
            return
        if not self.depots():
            if not DialogueAjoutServeur(self).exec():
                return
        DialoguePartager(self, vue).exec()

    def partager_theme(self):
        if not self.store.themes:
            return
        if not self.depots():
            if not DialogueAjoutServeur(self).exec():
                return
        vue = self.ctx.fiche_courante()
        DialogueTheme(self, vue._th.nom if vue is not None else None).exec()

    def themes_suivis(self, depot_nom: str) -> list:
        return list(self.ctx.reglages.get("themes_suivis", {}).get(depot_nom, []))

    def suivre_theme(self, depot_nom: str, theme: str, suivre: bool) -> None:
        tous = {k: list(v) for k, v in self.ctx.reglages.get("themes_suivis", {}).items()}
        liste = [t for t in tous.get(depot_nom, []) if t != theme] + ([theme] if suivre else [])
        tous[depot_nom] = liste
        self.ctx.reglages.set("themes_suivis", tous)

    def rejoindre(self):
        DialogueRejoindre(self).exec()

    def rejoindre_lien(self, lien: str):
        """Lien `scrinium://rejoindre…` ouvert par le système : pré-remplit la fenêtre, sans contacter le serveur avant le clic."""
        DialogueRejoindre(self, lien).exec()


# ---------- boîtes de dialogue ----------
class DialogueAjoutServeur(QDialog):
    """Ajoute un serveur de partage avec un compte DÉJÀ existant (pour un nouveau compte : « Rejoindre un partage… »)."""

    def __init__(self, plugin, parent=None, url="", compte=""):
        super().__init__(parent or _parent())
        self.p = plugin
        self.setWindowTitle(_("Ajouter un serveur de partage"))
        self.resize(460, 0)
        f = QFormLayout(self)
        self.url = QLineEdit(url)
        self.url.setPlaceholderText("https://serveur.exemple.org")
        self.compte = QLineEdit(compte)
        self.mdp = QLineEdit()
        self.mdp.setEchoMode(QLineEdit.EchoMode.Password)
        self.retenir = QCheckBox(_("Mémoriser le mot de passe (trousseau du système)"))
        f.addRow(_("Adresse du serveur :"), self.url)
        f.addRow(_("Compte :"), self.compte)
        f.addRow(_("Mot de passe :"), self.mdp)
        f.addRow("", self.retenir)
        f.addRow(QLabel(_("Pas encore de compte ? Demandez une invitation au propriétaire d'une fiche, puis « Rejoindre un partage… ».")))
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        b.accepted.connect(self._valider)
        b.rejected.connect(self.reject)
        f.addRow(b)

    def _valider(self):
        depot_brut = Depot(logique.nom_depot(self.url.text(), [d.nom for d in self.p.depots()]), self.url.text(), self.compte.text())
        try:
            from scrinium.core.depots import valider
            depot = valider(depot_brut)
        except ValueError as ex:
            self.p.avertir(_("Partage"), str(ex))
            return
        if not self.mdp.text():
            self.p.avertir(_("Partage"), _("Mot de passe absent."))
            return
        emp = self.p.verifier_certificat(depot.url)
        if emp is False:
            return
        self.p.secret.ecrire(self.p._cle(depot), self.mdp.text(), self.retenir.isChecked())
        self.p._epingler(depot.nom, emp)
        self.p.transports.pop(depot.nom, None)
        if self.p.faire(depot, lambda t: t.lister()) is None:
            self.p.secret.effacer(self.p._cle(depot))
            self.p._epingler(depot.nom, None)
            return
        enregistrer_depot(self.p.store, depot)
        self.accept()


class DialogueServeurs(QDialog):
    def __init__(self, plugin):
        super().__init__(_parent())
        self.p = plugin
        self.setWindowTitle(_("Serveurs de partage"))
        self.resize(520, 340)
        lay = QVBoxLayout(self)
        self.liste = QListWidget()
        lay.addWidget(self.liste, 1)
        bas = QHBoxLayout()
        for texte, fn in ((_("Ajouter…"), self._ajouter), (_("Supprimer"), self._supprimer), (_("Synchroniser"), self._sync)):
            b = QPushButton(texte)
            b.clicked.connect(fn)
            bas.addWidget(b)
        bas.addStretch()
        lay.addLayout(bas)
        auto = QHBoxLayout()
        auto.addWidget(QLabel(_("Synchroniser automatiquement toutes les")))
        self.minutes = QSpinBox(minimum=0, maximum=1440, specialValueText=_("(jamais)"))
        self.minutes.setSuffix(_(" min"))
        self.minutes.setValue(int(plugin.ctx.reglages.get("auto_minutes", 0) or 0))
        auto.addWidget(self.minutes)
        auto.addStretch()
        lay.addLayout(auto)
        lay.addWidget(QLabel(_("Pendant un échange, la fenêtre peut se figer quelques secondes si le serveur répond lentement.")))
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        b.rejected.connect(self.reject)
        b.accepted.connect(self.accept)
        lay.addWidget(b)
        self.finished.connect(self._fin)
        self._remplir()

    def _remplir(self):
        self.liste.clear()
        for d in self.p.depots():
            self.liste.addItem("{} — {} ({})".format(d.compte, d.url, d.theme))

    def _courant(self):
        i = self.liste.currentRow()
        depots = self.p.depots()
        return depots[i] if 0 <= i < len(depots) else None

    def _ajouter(self):
        if DialogueAjoutServeur(self.p, self).exec():
            self._remplir()

    def _supprimer(self):
        d = self._courant()
        if d is None:
            return
        r = QMessageBox.question(self, _("Serveurs de partage"), _(
            "Oublier le serveur {url} ? Vos fiches reçues restent ici, mais ne seront plus synchronisées. Rien n'est supprimé sur le serveur.").format(url=d.url))
        if r == QMessageBox.StandardButton.Yes:
            supprimer_depot(self.p.store, d.nom)
            self.p.secret.effacer(self.p._cle(d))
            self.p._epingler(d.nom, None)
            self.p.transports.pop(d.nom, None)
            self._remplir()

    def _sync(self):
        d = self._courant()
        if d is not None:
            self.p.synchroniser_depot(d)

    def _fin(self, _r):
        self.p.ctx.reglages.set("auto_minutes", self.minutes.value())
        self.p._armer_minuteur()


class DialoguePartager(QDialog):
    def __init__(self, plugin, vue):
        super().__init__(_parent())
        self.p, self.vue = plugin, vue
        self.setWindowTitle(_("Partager « {titre} »").format(titre=vue.titre))
        self.resize(520, 480)
        lay = QVBoxLayout(self)
        self.depots = plugin.depots()
        self.choix = QComboBox()
        for d in self.depots:
            self.choix.addItem("{} — {}".format(d.compte, d.url), d.nom)
        self.choix.currentIndexChanged.connect(self._rafraichir)
        lay.addWidget(self.choix)
        lay.addWidget(QLabel(_("Personnes ayant accès :")))
        self.droits = QListWidget()
        lay.addWidget(self.droits, 1)
        ligne = QHBoxLayout()
        self.retirer = QPushButton(_("Retirer l'accès"))
        self.retirer.clicked.connect(self._retirer)
        ligne.addWidget(self.retirer)
        ligne.addStretch()
        lay.addLayout(ligne)

        lay.addWidget(QLabel(_("Inviter par courriel (le lien est valable 48 h) :")))
        f = QFormLayout()
        self.email = QLineEdit()
        self.email.setPlaceholderText("nom@exemple.org")
        self.role = QComboBox()
        self.role.addItem(_("Lecture seule"), "lecture")
        self.role.addItem(_("Lecture et écriture"), "ecriture")
        f.addRow(_("Adresse :"), self.email)
        f.addRow(_("Droits :"), self.role)
        lay.addLayout(f)
        self.inviter = QPushButton(_("Inviter…"))
        self.inviter.clicked.connect(self._inviter)
        lay.addWidget(self.inviter)

        lay.addWidget(QLabel(_("Invitations :")))
        self.invitations = QListWidget()
        self.invitations.setMaximumHeight(90)
        lay.addWidget(self.invitations)
        ligne2 = QHBoxLayout()
        self.annuler = QPushButton(_("Annuler l'invitation"))
        self.annuler.clicked.connect(self._annuler)
        ligne2.addWidget(self.annuler)
        ligne2.addStretch()
        fermer = QPushButton(_("Fermer"))
        fermer.clicked.connect(self.accept)
        ligne2.addWidget(fermer)
        lay.addLayout(ligne2)
        self._invs: list = []
        self._rafraichir()

    def _depot(self):
        return self.depots[self.choix.currentIndex()]

    def _fiche(self):
        return self.p.ctx._trouver(self.vue)

    def _ident(self):
        return self.p.store.id_fiche(self._fiche()[1])

    def _etat(self):
        return EtatSynchro(chemin_etat(self.p.store, self._depot().nom)).charger()

    def _rafraichir(self):
        self.droits.clear()
        self.invitations.clear()
        self._invs = []
        ident = self._ident()
        etat = self._etat()
        if not ident or not etat.suivi(ident):
            self.droits.addItem(_("Pas encore partagée : elle sera mise en ligne à la première invitation."))
            return
        d = self.p.faire(self._depot(), lambda t: (t.droits(ident), t.invitations(ident)))
        if d is None:
            self.droits.addItem(_("(impossible de lire les droits : voir le message d'erreur)"))
            return
        droits, invs = d
        libelle = {"proprietaire": _("propriétaire"), "ecriture": _("lecture et écriture"), "lecture": _("lecture seule")}
        for compte, role in droits.items():
            it = QListWidgetItem("{} — {}".format(compte, libelle.get(role, role)))
            it.setData(Qt.ItemDataRole.UserRole, compte if role != "proprietaire" else None)
            self.droits.addItem(it)
        etats = {"en_attente": _("en attente"), "acceptee": _("acceptée"), "expiree": _("expirée"), "annulee": _("annulée")}
        for i in invs:
            it = QListWidgetItem("{} — {} — {} ({})".format(i["email"], libelle.get(i["role"], i["role"]), etats.get(i["etat"], i["etat"]),
                                                            _heure(i["expire_le"])))
            it.setData(Qt.ItemDataRole.UserRole, i["id"] if i["etat"] == "en_attente" else None)
            self.invitations.addItem(it)

    def _retirer(self):
        it = self.droits.currentItem()
        compte = it.data(Qt.ItemDataRole.UserRole) if it else None
        if not compte:
            return
        if QMessageBox.question(self, _("Partage"), _("Retirer l'accès de {c} ? Sa copie reste chez lui, mais ne sera plus mise à jour.").format(c=compte)) \
                == QMessageBox.StandardButton.Yes:
            self.p.faire(self._depot(), lambda t: t.retirer_droit(self._ident(), compte))
            self._rafraichir()

    def _annuler(self):
        it = self.invitations.currentItem()
        inv = it.data(Qt.ItemDataRole.UserRole) if it else None
        if inv:
            self.p.faire(self._depot(), lambda t: t.annuler(inv))
            self._rafraichir()

    def _inviter(self):
        email = self.email.text().strip()
        if not logique.adresse_valide(email):
            self.p.avertir(_("Partage"), _("Adresse de courriel invalide."))
            return
        depot = self._depot()
        th, f = self._fiche()
        role = self.role.currentData()

        def tout(t):
            etat = EtatSynchro(chemin_etat(self.p.store, depot.nom)).charger()
            ident = self.p.store.assurer_id(th, f)
            publier(self.p.store, etat, t, th, f)              # no-op si déjà en ligne
            return ident, t.inviter(ident, email, role)

        r = self.p.faire(depot, tout)
        if r is None:
            return
        _ident, inv = r
        objet, message = logique.texte_invitation(f.titre, role, inv["url"], _heure(inv["expire_le"]))
        self.email.clear()
        self._rafraichir()
        DialogueCourriel(self.p, email, objet, message).exec()


class DialogueTheme(QDialog):
    """Partage d'un thème entier : chaque fiche non verrouillée du thème est partagée ; un seul lien d'invitation."""

    def __init__(self, plugin, theme=None):
        super().__init__(_parent())
        self.p = plugin
        self.setWindowTitle(_("Partager un thème"))
        self.resize(520, 500)
        lay = QVBoxLayout(self)
        self.depots = plugin.depots()
        self.choix = QComboBox()
        for d in self.depots:
            self.choix.addItem("{} — {}".format(d.compte, d.url), d.nom)
        self.choix.currentIndexChanged.connect(self._rafraichir)
        lay.addWidget(self.choix)
        self.theme = QComboBox()
        for t in plugin.store.themes:
            self.theme.addItem(t.nom, t.nom)
        if theme:
            self.theme.setCurrentIndex(max(0, self.theme.findData(theme)))
        self.theme.currentIndexChanged.connect(self._rafraichir)
        lay.addWidget(QLabel(_("Thème :")))
        lay.addWidget(self.theme)
        self.resume = QLabel("")
        self.resume.setWordWrap(True)
        lay.addWidget(self.resume)
        lay.addWidget(QLabel(_("Personnes ayant accès à tout le thème :")))
        self.membres = QListWidget()
        lay.addWidget(self.membres, 1)
        self.retirer = QPushButton(_("Retirer l'accès"))
        self.retirer.clicked.connect(self._retirer)
        lay.addWidget(self.retirer, 0, Qt.AlignmentFlag.AlignLeft)
        self.suivre = QCheckBox(_("Mettre aussi en ligne les nouvelles fiches de ce thème, avec les mêmes droits"))
        self.suivre.setChecked(True)
        lay.addWidget(self.suivre)
        lay.addWidget(QLabel(_("Inviter par courriel (un seul lien pour tout le thème, valable 48 h) :")))
        f = QFormLayout()
        self.email = QLineEdit()
        self.email.setPlaceholderText("nom@exemple.org")
        self.role = QComboBox()
        self.role.addItem(_("Lecture seule"), "lecture")
        self.role.addItem(_("Lecture et écriture"), "ecriture")
        f.addRow(_("Adresse :"), self.email)
        f.addRow(_("Droits :"), self.role)
        lay.addLayout(f)
        bas = QHBoxLayout()
        inviter = QPushButton(_("Inviter…"))
        inviter.clicked.connect(self._inviter)
        bas.addWidget(inviter)
        bas.addStretch()
        fermer = QPushButton(_("Fermer"))
        fermer.clicked.connect(self.accept)
        bas.addWidget(fermer)
        lay.addLayout(bas)
        self._rafraichir()

    def _depot(self):
        return self.depots[self.choix.currentIndex()]

    def _theme(self):
        return self.p.store.theme(self.theme.currentData())

    def _etat(self):
        return EtatSynchro(chemin_etat(self.p.store, self._depot().nom)).charger()

    def _rafraichir(self):
        self.membres.clear()
        th = self._theme()
        self.suivre.setChecked(th is not None and th.nom in self.p.themes_suivis(self._depot().nom))
        if th is None:
            return
        r = self.p.faire(self._depot(), lambda t: themes.fiches_du_theme(self.p.store, th, t))
        if r is None:
            self.resume.setText(_("(impossible de lire l'état du partage : voir le message d'erreur)"))
            return
        pretes, autres, verrouillees = r
        txt = _("{n} fiche(s) partageable(s)").format(n=len(pretes))
        if verrouillees:
            txt += " — " + _("{n} verrouillée(s), jamais partagée(s)").format(n=verrouillees)
        if autres:
            txt += " — " + _("{n} reçue(s) d'un autre compte, non partagée(s)").format(n=len(autres))
        self.resume.setText(txt)
        idents = [i for _f, i in pretes if i is not None]
        droits = self.p.faire(self._depot(), lambda t: themes.droits_communs(t, idents)) if idents else {}
        for compte, role in sorted((droits or {}).items()):
            self.membres.addItem(f"{compte} — " + (_("lecture et écriture") if role == "ecriture" else _("lecture seule")))

    def _retirer(self):
        it = self.membres.currentItem()
        th = self._theme()
        if it is None or th is None:
            return
        compte = it.text().split(" — ")[0]
        if QMessageBox.question(self, _("Partage"), _("Retirer l'accès de « {c} » à toutes les fiches du thème ?").format(c=compte)) \
                == QMessageBox.StandardButton.Yes:
            self.p.faire(self._depot(), lambda t: themes.retirer_theme(self.p.store, t, th, compte))
            self._rafraichir()

    def _inviter(self):
        email = self.email.text().strip()
        th = self._theme()
        if th is None or not logique.adresse_valide(email):
            self.p.avertir(_("Partage"), _("Adresse de courriel invalide."))
            return
        depot, role = self._depot(), self.role.currentData()
        etat = self._etat()
        try:
            r = self.p.faire(depot, lambda t: themes.inviter_theme(self.p.store, etat, t, th, email, role))
        except ValueError as ex:
            self.p.avertir(_("Partage"), _("Rien à partager : %s") % ex)
            return
        if r is None:
            return
        n, inv = r
        self.p.suivre_theme(depot.nom, th.nom, self.suivre.isChecked())
        objet, message = logique.texte_invitation_theme(th.nom, n, role, inv["url"], _heure(inv["expire_le"]))
        self.email.clear()
        self._rafraichir()
        DialogueCourriel(self.p, email, objet, message).exec()


class DialogueCourriel(QDialog):
    """Message d'invitation prêt à envoyer : copié ou ouvert dans le logiciel de courriel du système."""

    def __init__(self, plugin, email, objet, message):
        super().__init__(_parent())
        self.p, self.email, self.objet = plugin, email, objet
        self.setWindowTitle(_("Invitation prête"))
        self.resize(520, 380)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(_("Envoyez ce message à {e}. Le lien ne marche qu'une fois, pendant 48 h.").format(e=email)))
        self.texte = QPlainTextEdit(message)
        lay.addWidget(self.texte, 1)
        bas = QHBoxLayout()
        copier = QPushButton(_("Copier le message"))
        copier.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.texte.toPlainText()))
        ouvrir = QPushButton(_("Ouvrir dans mon logiciel de courriel"))
        ouvrir.clicked.connect(self._ouvrir)
        courriel = plugin.ctx._g.actifs.get("courriel")
        self.envoyer = QPushButton(_("Envoyer"))
        self.envoyer.setToolTip(_("Envoie le message avec l'extension Courriel (activez-la dans les extensions)")
                                if courriel is None else _("Envoie le message depuis votre boîte, via l'extension Courriel"))
        self.envoyer.setEnabled(courriel is not None)
        self.envoyer.clicked.connect(self._envoyer)
        fermer = QPushButton(_("Fermer"))
        fermer.clicked.connect(self.accept)
        for b in (self.envoyer, copier, ouvrir):
            bas.addWidget(b)
        bas.addStretch()
        bas.addWidget(fermer)
        lay.addLayout(bas)

    def _envoyer(self):
        courriel = self.p.ctx._g.actifs.get("courriel")
        if courriel is not None and courriel[0].envoyer_message(self.email, self.objet, self.texte.toPlainText()):
            self.accept()

    def _ouvrir(self):
        url = "mailto:{}?subject={}&body={}".format(quote(self.email), quote(self.objet), quote(self.texte.toPlainText()))
        QDesktopServices.openUrl(QUrl(url))


class DialogueRejoindre(QDialog):
    def __init__(self, plugin, lien=""):
        super().__init__(_parent())
        self.p = plugin
        self.serveur = self.jeton = None
        self.setWindowTitle(_("Rejoindre un partage"))
        self.resize(500, 0)
        self.lay = QVBoxLayout(self)
        self.lay.addWidget(QLabel(_("Collez le lien reçu par courriel :")))
        self.lien = QLineEdit()
        self.lien.setPlaceholderText("https://…/inviter/…")
        self.lien.setText(lien)
        self.lay.addWidget(self.lien)
        self.verifier = QPushButton(_("Vérifier l'invitation"))
        self.verifier.clicked.connect(self._verifier)
        self.lay.addWidget(self.verifier)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        self.lay.addWidget(self.info)
        self.zone = QVBoxLayout()
        self.lay.addLayout(self.zone)
        self.ok = QPushButton(_("Rejoindre"))
        self.ok.setEnabled(False)
        self.ok.clicked.connect(self._rejoindre)
        self.lay.addWidget(self.ok)

    def _verifier(self):
        try:
            self.serveur, self.jeton = logique.analyser_invitation(self.lien.text())
        except ValueError as ex:
            self.info.setText("⚠ " + str(ex))
            return
        emp = self.p.verifier_certificat(self.serveur)
        if emp is False:
            return
        self.emp = emp
        try:
            def lire():
                t = TransportHttp(self.serveur, "", None, emp)
                t.decouverte()
                return t.decrire_invitation(self.jeton)
            inv = en_fond(lire)
        except ErreurTransport as ex:
            self.info.setText("⚠ " + (_("Invitation introuvable, expirée ou déjà utilisée.") if isinstance(ex, Introuvable) else str(ex)))
            return
        droit = _("lire et modifier") if inv["role"] == "ecriture" else _("lire")
        nb = int(inv.get("fiches", 1) or 1)
        objet = _("{n} fiches").format(n=nb) if nb > 1 else _("une fiche")
        self.info.setText(_("{qui} vous invite à {droit} {objet} (valable jusqu'au {fin}).").format(
            qui=inv["invite_par"], droit=droit, objet=objet, fin=_heure(inv["expire_le"])))
        self.existant = next((d for d in self.p.depots() if d.url == self.serveur), None)
        while self.zone.count():
            self.zone.takeAt(0).widget().deleteLater()
        if self.existant:
            self.zone.addWidget(QLabel(_("Vous serez ajouté avec votre compte « {c} » sur ce serveur.").format(c=self.existant.compte)))
        else:
            self.nouveau = QRadioButton(_("Créer un compte sur ce serveur"))
            self.nouveau.setChecked(True)
            self.ancien = QRadioButton(_("J'ai déjà un compte sur ce serveur"))
            self.compte, self.mdp = QLineEdit(), QLineEdit()
            self.mdp.setEchoMode(QLineEdit.EchoMode.Password)
            self.retenir = QCheckBox(_("Mémoriser le mot de passe (trousseau du système)"))
            f = QFormLayout()
            f.addRow(_("Nom de compte :"), self.compte)
            f.addRow(_("Mot de passe (10 caractères minimum pour un nouveau compte) :"), self.mdp)
            for w in (self.nouveau, self.ancien):
                self.zone.addWidget(w)
            self.zone.addLayout(f)
            self.zone.addWidget(self.retenir)
            self.zone.addWidget(QLabel(_("Les fiches partagées sont stockées sur ce serveur : son administrateur peut les lire.")))
        self.ok.setEnabled(True)

    def _rejoindre(self):
        if self.existant:
            depot = self.existant
            if not self.p.faire(depot, lambda t: (t.rejoindre(self.jeton), True)[1]):
                return
        else:
            nom, mdp = self.compte.text().strip(), self.mdp.text()
            if not nom or not mdp:
                self.p.avertir(_("Partage"), _("Nom de compte et mot de passe requis."))
                return
            try:
                from scrinium.core.depots import valider
                depot = valider(Depot(logique.nom_depot(self.serveur, [d.nom for d in self.p.depots()]), self.serveur, nom))
            except ValueError as ex:
                self.p.avertir(_("Partage"), str(ex))
                return
            self.p._epingler(depot.nom, self.emp)
            self.p.secret.ecrire(self.p._cle(depot), mdp, self.retenir.isChecked())
            t = TransportHttp(depot.url, nom, mdp, self.emp)
            try:
                en_fond(lambda: t.rejoindre(self.jeton, None if self.ancien.isChecked() else nom, mdp))
            except ErreurTransport as ex:
                self.p.secret.effacer(self.p._cle(depot))
                self.p._epingler(depot.nom, None)
                self.p._erreur(ex)
                return
            enregistrer_depot(self.p.store, depot)
            self.p.transports[depot.nom] = t
        self.accept()
        self.p.synchroniser_depot(depot)


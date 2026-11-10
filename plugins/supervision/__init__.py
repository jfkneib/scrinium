# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « Supervision » : l'état de vos machines (ordinateurs, serveurs, NAS, box) dans une fiche.

- Une fiche « Supervision » = une section par machine : adresse, ports à tester, page web, cible SSH (facultatifs). Le tableau montre si
  la machine répond (ping), ses ports, sa page web et, par SSH, disque, mémoire, charge et durée de fonctionnement.
- Les contrôles se font hors du fil de l'interface (la fenêtre ne se fige pas). « Actualiser », ou automatiquement toutes les minutes.
- Notification quand une machine passe de « bon état » à « alerte » ou « panne ».
- « Tout est fiche » : type EXÉCUTABLE (`#scrinium-supervision`, voir `logique.py`). Une fiche reçue de l'extérieur ne contrôle rien tant que
  l'utilisateur ne l'a pas validée. SSH sans mot de passe (clés) ; la commande envoyée est fixe, en lecture seule."""
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
                             QLineEdit, QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from scrinium.core.plugins import Plugin
from scrinium.i18n import _
from scrinium.ui.icons import icone

from . import logique

COULEURS = {"ok": "#2e7d32", "alerte": "#e08e0b", "panne": "#c0392b", None: "#888888"}
INTERVALLE = 60_000                                      # ms entre deux contrôles automatiques


def couleur_niveau(pct):
    """Fond d'une case de consommation : vert (0 %) -> jaune -> rouge (100 %), en teinte claire ; None sans mesure."""
    if pct is None:
        return None
    return QColor.fromHsv(int(120 * (100 - min(max(pct, 0), 100)) / 100), 110, 240)


def _libelle_etat(e) -> str:
    return {"ok": _("En ligne"), "alerte": _("Alerte"), "panne": _("Panne")}.get(e, _("…"))


class DialogueMachine(QDialog):
    """Créer ou modifier une machine."""

    def __init__(self, machine=None, parent=None):
        super().__init__(parent)
        m = machine or {"nom": "", "adresse": "", "ports": [], "web": "", "ssh": "", "seuil_disque": logique.SEUIL_DISQUE, "watts": None}
        self.setWindowTitle(_("Machine"))
        self.resize(460, 260)
        f = QFormLayout(self)
        self.nom = QLineEdit(m["nom"])
        self.adresse = QLineEdit(m["adresse"])
        self.adresse.setPlaceholderText("192.168.1.10 / serveur.local")
        self.ports = QLineEdit(", ".join(str(p) for p in m["ports"]))
        self.ports.setPlaceholderText("22, 80, 443")
        self.web = QLineEdit(m["web"])
        self.web.setPlaceholderText("http://serveur.local/")
        self.ssh = QLineEdit(m["ssh"])
        self.ssh.setPlaceholderText("utilisateur@serveur.local")
        self.ssh.setToolTip(_("Pour lire disque, mémoire et charge. Connexion par clé (sans mot de passe) ; une commande fixe, en lecture seule."))
        self.seuil = QSpinBox()
        self.seuil.setRange(1, 100)
        self.seuil.setSuffix(" %")
        self.seuil.setValue(m["seuil_disque"])
        f.addRow(_("Nom :"), self.nom)
        f.addRow(_("Adresse :"), self.adresse)
        f.addRow(_("Ports à tester :"), self.ports)
        f.addRow(_("Page web :"), self.web)
        f.addRow(_("Cible SSH :"), self.ssh)
        self.watts = QLineEdit("%d-%d" % m["watts"] if m.get("watts") else "")
        self.watts.setPlaceholderText("40-200")
        self.watts.setToolTip(_("Facultatif : consommation de la machine au repos et à pleine charge, en watts (ex. 40-200). Sert à ESTIMER la puissance "
                                "d'après la charge : ce n'est pas une mesure."))
        f.addRow(_("Alerte disque à :"), self.seuil)
        f.addRow(_("Watts repos-max :"), self.watts)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        b.accepted.connect(self._valider)
        b.rejected.connect(self.reject)
        f.addRow(b)

    def resultat(self) -> dict | None:
        return logique.normaliser({"nom": self.nom.text(), "adresse": self.adresse.text(), "ports": self.ports.text(),
                                   "web": self.web.text(), "ssh": self.ssh.text(), "seuil_disque": self.seuil.value(), "watts": self.watts.text()})

    def _valider(self):
        if not self.nom.text().strip() or not logique.hote_valide(self.adresse.text().strip()):
            QMessageBox.warning(self, _("Machine"), _("Un nom et une adresse valide sont obligatoires (l'adresse ne peut pas commencer par « - »)."))
            return
        if self.web.text().strip() and not logique.web_valide(self.web.text().strip()):
            QMessageBox.warning(self, _("Machine"), _("La page web doit commencer par http:// ou https://."))
            return
        if self.ssh.text().strip() and not logique.cible_ssh_valide(self.ssh.text().strip()):
            QMessageBox.warning(self, _("Machine"), _("Cible SSH refusée : utilisez « utilisateur@machine »."))
            return
        self.accept()


class VueSupervision(QWidget):
    """Vue du type « supervision » : tableau d'état. Fiche non validée : lisible, aucun contrôle ne part."""
    modifie = pyqtSignal(str)
    _recu = pyqtSignal(int, int, object)                 # génération, indice de la machine, résultat (venu d'un fil de travail)

    def __init__(self, plugin=None, parent=None):
        super().__init__(parent)
        self.p = plugin
        self.machines: list = []
        self.resultats: dict = {}                        # indice -> résultat du dernier contrôle
        self.etats: dict = {}                            # nom de la machine -> dernier état connu (pour ne notifier que les changements)
        self._actif = True
        self._gen = 0
        self._pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="supervision")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        haut = QHBoxLayout()
        self.b_actualiser = QPushButton(icone("view-refresh"), _("Actualiser"))
        self.b_actualiser.clicked.connect(self.actualiser)
        haut.addWidget(self.b_actualiser)
        self.c_auto = QCheckBox(_("Toutes les minutes"))
        self.c_auto.setChecked(True)
        haut.addWidget(self.c_auto)
        self.l_maj = QLabel()
        haut.addWidget(self.l_maj, 1)
        lay.addLayout(haut)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels([_("État"), _("Machine"), _("Réseau"), _("Disque"), _("Mémoire"), _("Charge"),
                                              _("Puissance"), _("En marche depuis"), _("Détail")])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(lambda pos: self._menu_table(pos))
        lay.addWidget(self.table, 1)
        self.aide = QLabel()
        self.aide.setWordWrap(True)
        lay.addWidget(self.aide)
        self._recu.connect(self._arrive)
        self.minuteur = QTimer(self, interval=INTERVALLE)
        self.minuteur.timeout.connect(self._auto)
        self.minuteur.start()
        self._texte_aide()

    @property
    def actif(self) -> bool:
        return self._actif

    @actif.setter
    def actif(self, oui: bool) -> None:
        self._actif = bool(oui)
        self.b_actualiser.setEnabled(self._actif)
        self._texte_aide()

    def _texte_aide(self):
        self.aide.setText(_("Clic droit : ajouter, modifier ou retirer une machine.") if self._actif else
                          _("Fiche non validée : relisez les machines, puis validez-la pour lancer les contrôles et la modifier."))

    # ---------- données ----------
    def charger(self, texte: str):
        self.machines = logique.depuis_texte(texte)
        self.resultats = {}
        self._gen += 1
        self._afficher()
        if self._actif and self.isVisible():
            self.actualiser()

    def _enregistrer(self):
        self.modifie.emit(logique.en_texte(self.machines))
        self.resultats = {}
        self._gen += 1
        self._afficher()
        self.actualiser()

    # ---------- contrôles ----------
    def showEvent(self, ev):
        """Première apparition de la fiche : lance les contrôles tout de suite (sinon on attendrait la minute suivante)."""
        super().showEvent(ev)
        if self._actif and self.machines and not self.resultats:
            QTimer.singleShot(0, self.actualiser)

    def _auto(self):
        if self._actif and self.c_auto.isChecked() and self.isVisible():
            self.actualiser()

    def actualiser(self):
        """Lance les contrôles de toutes les machines (en arrière-plan). Sans effet pour une fiche non validée."""
        if not self._actif or not self.machines:
            return
        self._gen += 1
        gen = self._gen
        self.b_actualiser.setEnabled(False)
        self._attendus = len(self.machines)
        for i, m in enumerate(self.machines):
            self._pool.submit(self._travail, gen, i, dict(m))

    def _travail(self, gen: int, i: int, m: dict):
        try:
            r = logique.sonder(m)
        except Exception as ex:                          # un contrôle qui plante ne doit pas bloquer les autres
            r = {"ping": False, "ports": {}, "erreur_ssh": str(ex)[:200]}
        try:
            self._recu.emit(gen, i, r)
        except RuntimeError:                             # la vue a été détruite entre-temps
            pass

    def _arrive(self, gen: int, i: int, r: dict):
        if gen != self._gen or not 0 <= i < len(self.machines):
            return
        self.resultats[i] = r
        m = self.machines[i]
        e, raisons = logique.etat(m, r)
        avant = self.etats.get(m["nom"])
        self.etats[m["nom"]] = e
        if self.p is not None and avant == "ok" and e in ("alerte", "panne"):
            self.p.alerter(m["nom"], e, raisons)
        self._ligne(i)
        if len(self.resultats) >= len(self.machines):
            self.b_actualiser.setEnabled(self._actif)
            from datetime import datetime
            self.l_maj.setText(_("Dernier contrôle : %s") % datetime.now().strftime("%H:%M:%S"))

    # ---------- affichage ----------
    def _afficher(self):
        self.table.setRowCount(len(self.machines))
        for i in range(len(self.machines)):
            self._ligne(i)
        self.table.resizeColumnsToContents()

    def _ligne(self, i: int):
        m, r = self.machines[i], self.resultats.get(i)
        e, raisons = logique.etat(m, r) if r is not None else (None, [])
        mes = (r or {}).get("mesures", {})
        reseau = []
        if r is not None:
            reseau.append("ping " + ("✓" if r["ping"] else "✗"))
            reseau += [f"{p} " + ("✓" if o else "✗") for p, o in r["ports"].items()]
            if "web" in r:
                reseau.append("web " + (str(r["web"]) if r["web"] else "✗"))
        watts = logique.puissance_estimee(m, mes)
        cases = ["● " + _libelle_etat(e), m["nom"] + "  (" + m["adresse"] + ")", "  ".join(reseau),
                 f"{mes['disque_pct']} %" if "disque_pct" in mes else "", f"{mes['memoire_pct']} %" if "memoire_pct" in mes else "",
                 f"{mes['charge']:.2f}" if "charge" in mes else "", f"≈ {watts} W" if watts is not None else ("—" if mes else ""), logique.duree(mes["uptime_s"]) if "uptime_s" in mes else "",
                 ", ".join(raisons)]
        for c, t in enumerate(cases):
            it = QTableWidgetItem(t)
            if c == 0:
                it.setForeground(QBrush(QColor(COULEURS[e])))
            niveau = {3: mes.get("disque_pct"), 4: mes.get("memoire_pct"), 5: logique.charge_pct(mes)}.get(c)
            if niveau is not None:
                it.setBackground(QBrush(couleur_niveau(niveau)))
                it.setForeground(QBrush(QColor("#1b1b1b")))
            if c == 6 and watts is None and mes:
                it.setToolTip(_("Pour estimer la puissance, indiquez les watts de la machine au repos et à pleine charge (clic droit > Modifier > « Watts repos-max », "
                                "ou une ligne « watts: 40-200 » dans la fiche)."))
            if c == 6 and watts is not None:
                a, b = m["watts"]
                it.setToolTip(_("ESTIMATION, pas une mesure : %(repos)d W au repos + (%(maxi)d − %(repos)d) W × charge %(charge)d %% = %(w)d W.\n"
                                "Soit environ %(wh)d Wh par jour si cela dure (%(kwh).1f kWh par mois).") % {
                    "repos": a, "maxi": b, "charge": logique.charge_pct(mes), "w": watts, "wh": watts * 24, "kwh": watts * 24 * 30 / 1000})
            self.table.setItem(i, c, it)
        self.table.resizeColumnsToContents()

    # ---------- clic droit ----------
    def _menu_table(self, pos):
        from PyQt6.QtWidgets import QMenu
        if not self._actif:
            return
        i = self.table.rowAt(pos.y())
        menu = QMenu(self)
        for texte, fn, ic in self.entrees_menu(self.table.viewport().mapTo(self, pos), i):
            menu.addAction(icone(ic), texte, fn)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def entrees_menu(self, pos, i: int | None = None) -> list:
        """Entrées du clic droit (la fenêtre y ajoute celles des extensions) ; `pos` : position dans cette vue."""
        if not self._actif:
            return []
        if i is None:
            i = self.table.rowAt(self.table.viewport().mapFrom(self, pos).y())
        e = [(_("Ajouter une machine…"), lambda *_a: self._ajouter(), "list-add")]
        if i >= 0:
            e += [(_("Modifier…"), lambda *_a, i=i: self._modifier(i), "document-edit"),
                  (_("Retirer"), lambda *_a, i=i: self._retirer(i), "edit-delete")]
        return e + [(_("Actualiser"), lambda *_a: self.actualiser(), "view-refresh")]

    def _ajouter(self):
        d = DialogueMachine(None, self)
        if d.exec() and d.resultat():
            self.machines.append(d.resultat())
            self._enregistrer()

    def _modifier(self, i: int):
        if self._actif and 0 <= i < len(self.machines):
            d = DialogueMachine(self.machines[i], self)
            if d.exec() and d.resultat():
                self.machines[i] = d.resultat()
                self._enregistrer()

    def _retirer(self, i: int):
        if self._actif and 0 <= i < len(self.machines):
            del self.machines[i]
            self._enregistrer()

    def fermer(self):
        self.minuteur.stop()
        self._gen += 1
        self._pool.shutdown(wait=False, cancel_futures=True)


class SupervisionPlugin(Plugin):
    api = 1

    def activer(self, ctx):
        self.ctx = ctx
        self.vue = None
        ctx.ajouter_doc(_("Extension Supervision"), DOC)
        for theme, titre, texte in logique.exemples():
            ctx.ajouter_exemple(theme, titre, texte, "network-server")
        if ctx.ui is not None:
            self.vue = VueSupervision(self)
            ctx.ui.enregistrer_type(logique.TYPE, self.vue)

    def desactiver(self):
        if self.vue is not None:
            self.vue.fermer()

    def alerter(self, nom: str, etat: str, raisons: list):
        self.ctx.ui.notifier(_("Supervision"), (_("« %s » est en panne : elle ne répond plus.") if etat == "panne"
                                                else _("« %s » est en alerte : ") + ", ".join(raisons)) % nom)


DOC = _(
    "L'état de vos machines (ordinateurs, serveurs, NAS, box) dans une fiche.\n"
    "\n"
    "• Nouvelle fiche > « Supervision » : une machine par section, avec son adresse. Clic droit : ajouter, modifier ou retirer une machine.\n"
    "• Le tableau montre si la machine répond au ping, quels ports sont ouverts, si sa page web répond et, avec une cible SSH, le disque, la mémoire, la charge et la durée de fonctionnement.\n"
    "• « Actualiser », ou automatiquement toutes les minutes tant que la fiche est affichée. Une notification prévient quand une machine passe en alerte ou en panne.\n"
    "• Puissance (facultatif) : indiquez les watts de la machine au repos et à pleine charge (ex. 40-200) : Scrinium ESTIME la puissance d'après la charge, et le dit au survol. Ce n'est pas une mesure.\n"
    "• SSH : connexion par clé, sans mot de passe. Scrinium n'envoie qu'une commande fixe, en lecture seule (charge, mémoire, disque).\n"
    "• Type exécutable : une fiche reçue d'un autre ne lance aucun contrôle tant que vous ne l'avez pas validée (bandeau « Valider cette fiche »). "
    "Les adresses sont écrites en clair dans la fiche.")

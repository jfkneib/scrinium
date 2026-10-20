# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « Traduction » : traduit la sélection (ou toute la fiche) avec un moteur LOCAL.

- TranslateGemma (4B) par llama.cpp, sans Ollama : l'extension lance `llama-server` à la demande (127.0.0.1, port libre, clé
  d'accès aléatoire), l'arrête après inactivité ou à la fermeture, ou se connecte à un serveur que vous avez déjà lancé.
- Argos Translate (hors ligne) : installé dans le dossier de l'extension, avec seulement ses dépendances légères.
- Rien ne quitte la machine (un serveur distant n'est utilisé que si vous l'acceptez explicitement). Aucune installation ni aucun
  téléchargement sans votre accord, avec taille et provenance affichées.
"""
import sys
import threading

from PyQt6.QtCore import QEventLoop, QObject, QProcess, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
                             QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar, QProgressDialog, QPushButton,
                             QSpinBox, QVBoxLayout)

from scrinium.core.plugins import Plugin
from scrinium.i18n import _

from . import logique

MOTEURS = {"llama": "TranslateGemma (llama.cpp)", "argos": "Argos Translate"}
AIDE_ARGOS_LOURD = _("Argos Translate n'a pas pu être utilisé avec ses seules dépendances légères. Son installation complète "
                     "ajouterait PyTorch (plusieurs Go) : elle n'est pas faite automatiquement.")


def _parent():
    return QApplication.activeWindow()


def _taille(octets: int) -> str:
    return f"{octets / 1e9:.2f} Go" if octets >= 1e9 else f"{octets / 1e6:.0f} Mo"


class _Pont(QObject):
    """Ramène dans le fil de l'interface ce qui se passe dans un fil de travail."""
    progression = pyqtSignal(int, int)
    etat = pyqtSignal(str)
    fini = pyqtSignal(object, str)          # (résultat, erreur) ; erreur "" = réussi


def _emettre(signal, *args):
    try:
        signal.emit(*args)
    except RuntimeError:                    # la fenêtre a été fermée entre-temps
        pass


def en_arriere_plan(titre: str, message: str, fonction, annulable: bool = False, parent=None):
    """Exécute fonction(annuler: threading.Event, progression) dans un fil, avec une fenêtre d'attente. (résultat, erreur)."""
    dlg = QProgressDialog(message, _("Annuler") if annulable else None, 0, 0, parent or _parent())
    dlg.setWindowTitle(titre)
    dlg.setMinimumDuration(0)
    dlg.setAutoClose(False)
    dlg.setAutoReset(False)
    annuler = threading.Event()
    pont = _Pont()
    boucle = QEventLoop()
    sortie = {}

    def progression(fait, total):
        _emettre(pont.progression, int(fait), int(total))

    def travail():
        try:
            sortie["res"], sortie["err"] = fonction(annuler, progression), ""
        except logique.Annule:
            sortie["res"], sortie["err"] = None, "annulé"
        except Exception as ex:
            sortie["res"], sortie["err"] = None, str(ex) or type(ex).__name__
        _emettre(pont.fini, None, "")

    def maj(fait, total):
        if total > 0:
            dlg.setMaximum(total)
            dlg.setValue(min(fait, total))
            dlg.setLabelText(f"{message}\n{_taille(fait)} / {_taille(total)}" if total > 1e6 else message)
    pont.progression.connect(maj)
    pont.fini.connect(lambda *_a: boucle.quit())
    dlg.canceled.connect(annuler.set)
    threading.Thread(target=travail, daemon=True).start()
    dlg.show()
    boucle.exec()
    dlg.close()
    return sortie.get("res"), sortie.get("err", "")


class _Installation(QDialog):
    """Lance une suite de commandes `pip install --target` et montre leur sortie."""

    def __init__(self, titre, etapes, parent=None):
        super().__init__(parent)
        self.setWindowTitle(titre)
        self.resize(560, 320)
        lay = QVBoxLayout(self)
        self.barre = QProgressBar()
        self.barre.setRange(0, 0)
        self.log = QPlainTextEdit(readOnly=True)
        self.boutons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.boutons.rejected.connect(self.reject)
        self.boutons.setEnabled(False)
        for w in (self.barre, self.log, self.boutons):
            lay.addWidget(w)
        self.ok = False
        self.etapes = list(etapes)
        self.p = QProcess(self)
        self.p.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.p.readyRead.connect(lambda: self.log.appendPlainText(bytes(self.p.readAll()).decode(errors="replace").rstrip()))
        self.p.finished.connect(self._fini)
        self._suite()

    def _suite(self):
        if not self.etapes:
            self.ok = True
            self.barre.setRange(0, 1)
            self.barre.setValue(1)
            self.accept()
            return
        args = self.etapes.pop(0)
        self.log.appendPlainText("$ pip " + " ".join(args[2:]))
        self.p.start(sys.executable, args)

    def _fini(self, code, _statut):
        if code == 0:
            self._suite()
            return
        self.barre.setRange(0, 1)
        self.boutons.setEnabled(True)
        self.log.appendPlainText(_("Échec (code %s).") % code)

    def reject(self):
        if self.p.state() != QProcess.ProcessState.NotRunning:
            self.p.kill()
            self.p.waitForFinished(2000)
        super().reject()


class DialogueReglages(QDialog):
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.p = plugin
        r = plugin.ctx.reglages
        self.setWindowTitle(_("Réglages de la traduction"))
        self.resize(620, 480)
        f = QFormLayout(self)
        self.moteur = QComboBox()
        for cle, nom in MOTEURS.items():
            self.moteur.addItem(nom, cle)
        self.moteur.setCurrentIndex(max(0, self.moteur.findData(r.get("moteur", "llama"))))
        f.addRow(_("Moteur par défaut :"), self.moteur)
        # llama.cpp
        f.addRow(QLabel("<b>" + _("TranslateGemma par llama.cpp") + "</b>"))
        self.exe = QLineEdit(r.get("exe", ""))
        self.exe.setPlaceholderText(logique.trouver_llama("", plugin.ctx.dossier_donnees) or _("(llama-server introuvable)"))
        b1 = QPushButton(_("Parcourir…"))
        b1.clicked.connect(lambda: self._choisir(self.exe, _("Programme llama-server")))
        f.addRow(_("Programme llama-server :"), self._ligne(self.exe, b1))
        self.modele = QLineEdit(r.get("modele", ""))
        self.modele.setPlaceholderText(logique.trouver_modele("", plugin.ctx.dossier_donnees) or _("(modèle introuvable)"))
        b2 = QPushButton(_("Parcourir…"))
        b2.clicked.connect(lambda: self._choisir(self.modele, _("Modèle .gguf"), "GGUF (*.gguf)"))
        f.addRow(_("Modèle (.gguf) :"), self._ligne(self.modele, b2))
        self.gpu = QLineEdit(r.get("gpu", ""))
        self.gpu.setPlaceholderText(_("automatique"))
        self.gpu.setToolTip(_("Nombre de couches sur la carte graphique (option -ngl). Vide = automatique ; 0 = processeur seul."))
        f.addRow(_("Couches sur la carte graphique :"), self.gpu)
        self.url = QLineEdit(r.get("url", ""))
        self.url.setPlaceholderText(_("(vide : l'extension lance son propre serveur)"))
        f.addRow(_("Serveur déjà lancé (adresse) :"), self.url)
        self.distant = QCheckBox(_("J'accepte qu'un serveur NON local reçoive le texte à traduire"))
        self.distant.setChecked(bool(r.get("distant_ok", False)))
        f.addRow(self.distant)
        self.inactif = QSpinBox(minimum=1, maximum=240)
        self.inactif.setValue(int(r.get("inactivite", 10)))
        self.inactif.setSuffix(_(" min"))
        f.addRow(_("Arrêter le serveur après inactivité :"), self.inactif)
        ligne = QHBoxLayout()
        for texte, fn in ((_("Aide à l'installation…"), plugin.aide_installation), (_("Télécharger le modèle…"), plugin.telecharger_modele),
                          (_("Tester"), self._tester)):
            b = QPushButton(texte)
            b.clicked.connect(fn)
            ligne.addWidget(b)
        f.addRow(ligne)
        # Argos
        f.addRow(QLabel("<b>" + _("Argos Translate") + "</b>"))
        statut = _("installé") if logique.argos_present() else _("non installé")
        self.b_argos = QPushButton(_("Installer Argos Translate…"))
        self.b_argos.clicked.connect(plugin.installer_argos)
        f.addRow(_("État : %s") % statut, self.b_argos)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        b.accepted.connect(self._valider)
        b.rejected.connect(self.reject)
        f.addRow(b)

    @staticmethod
    def _ligne(champ, bouton):
        h = QHBoxLayout()
        h.addWidget(champ, 1)
        h.addWidget(bouton)
        return h

    def _choisir(self, champ, titre, filtre=""):
        chemin, _f = QFileDialog.getOpenFileName(self, titre, "", filtre)
        if chemin:
            champ.setText(chemin)

    def _tester(self):
        self._enregistrer()
        self.p.tester_llama()

    def _enregistrer(self):
        r = self.p.ctx.reglages
        r.set("moteur", self.moteur.currentData())
        r.set("exe", self.exe.text().strip())
        r.set("modele", self.modele.text().strip())
        r.set("gpu", self.gpu.text().strip())
        r.set("url", self.url.text().strip())
        r.set("distant_ok", self.distant.isChecked())
        r.set("inactivite", self.inactif.value())

    def _valider(self):
        self._enregistrer()
        self.accept()


class DialogueTraduction(QDialog):
    """Texte à traduire, langues, résultat modifiable, et ce qu'on en fait (insérer, remplacer, copier)."""

    def __init__(self, plugin, texte, selection, vue, parent=None):
        super().__init__(parent)
        self.p, self.selection, self.vue = plugin, selection, vue
        self.annuler = threading.Event()
        self.pont = _Pont()
        self.pont.etat.connect(lambda t: self.etat.setText(t))
        self.pont.progression.connect(self._progression)
        self.pont.fini.connect(self._fini)
        self.travail = False
        r = plugin.ctx.reglages
        self.setWindowTitle(_("Traduire la sélection") if selection else _("Traduire la fiche"))
        self.resize(720, 640)
        lay = QVBoxLayout(self)
        self.source = QPlainTextEdit(texte)
        self.source.setPlaceholderText(_("Texte à traduire"))
        lay.addWidget(self.source, 2)
        ligne = QHBoxLayout()
        self.moteur = QComboBox()
        for cle, nom in MOTEURS.items():
            self.moteur.addItem(nom, cle)
        self.moteur.setCurrentIndex(max(0, self.moteur.findData(r.get("moteur", "llama"))))
        self.src = QComboBox()
        self.src.addItem(_("Détection automatique"), "")
        self.dst = QComboBox()
        for code, (_en, fr) in logique.LANGUES.items():
            self.src.addItem(fr, code)
            self.dst.addItem(fr, code)
        self.detectee = logique.detecter(texte)
        self.dst.setCurrentIndex(max(0, self.dst.findData(logique.cible_par_defaut(self.detectee, r.get("cible", "en")))))
        echange = QPushButton("⇄")
        echange.setToolTip(_("Échanger les langues"))
        echange.clicked.connect(self._echanger)
        for w in (self.moteur, self.src, echange, self.dst):
            ligne.addWidget(w, 0 if w is echange else 1)
        lay.addLayout(ligne)
        self.info = QLabel(_("Langue détectée : %s") % logique.LANGUES[self.detectee][1] if self.detectee
                           else _("Langue source non détectée : choisissez-la."))
        lay.addWidget(self.info)
        self.src.currentIndexChanged.connect(self._src_change)
        haut = QHBoxLayout()
        self.b_trad = QPushButton(_("Traduire"))
        self.b_trad.setDefault(True)
        self.b_trad.clicked.connect(self._lancer)
        self.b_stop = QPushButton(_("Arrêter"))
        self.b_stop.setEnabled(False)
        self.b_stop.clicked.connect(self.annuler.set)
        self.barre = QProgressBar()
        self.barre.setTextVisible(False)
        self.barre.setMaximumHeight(8)
        haut.addWidget(self.b_trad)
        haut.addWidget(self.b_stop)
        haut.addWidget(self.barre, 1)
        lay.addLayout(haut)
        self.etat = QLabel("")
        self.etat.setWordWrap(True)
        lay.addWidget(self.etat)
        self.resultat = QPlainTextEdit()
        self.resultat.setPlaceholderText(_("La traduction apparaît ici ; vous pouvez la corriger avant de l'utiliser."))
        lay.addWidget(self.resultat, 3)
        bas = QHBoxLayout()
        self.b_sous = QPushButton(_("Insérer sous le texte"))
        self.b_rempl = QPushButton(_("Remplacer"))
        self.b_copier = QPushButton(_("Copier"))
        fermer = QPushButton(_("Fermer"))
        self.b_sous.clicked.connect(self._inserer_sous)
        self.b_rempl.clicked.connect(self._remplacer)
        self.b_copier.clicked.connect(lambda: QApplication.clipboard().setText(self.resultat.toPlainText()))
        fermer.clicked.connect(self.reject)
        for b in (self.b_sous, self.b_rempl, self.b_copier):
            bas.addWidget(b)
        bas.addStretch()
        bas.addWidget(fermer)
        lay.addLayout(bas)
        self._maj_boutons()
        self.resultat.textChanged.connect(self._maj_boutons)

    def _maj_boutons(self):
        ok = bool(self.resultat.toPlainText().strip()) and not self.travail
        for b in (self.b_sous, self.b_rempl, self.b_copier):
            b.setEnabled(ok)

    def _echanger(self):
        s, d = self.src.currentData() or self.detectee, self.dst.currentData()
        if s:
            self.src.setCurrentIndex(self.src.findData(d))
            self.dst.setCurrentIndex(self.dst.findData(s))

    def _src_change(self):
        code = self.src.currentData() or self.detectee
        if code:
            self.dst.setCurrentIndex(max(0, self.dst.findData(logique.cible_par_defaut(code, self.p.ctx.reglages.get("cible", "en")))))

    def langues(self):
        return (self.src.currentData() or self.detectee), self.dst.currentData()

    # ----- traduction -----
    def _lancer(self):
        src, dst = self.langues()
        texte = self.source.toPlainText().strip()
        if not texte:
            return
        if not src:
            QMessageBox.information(self, _("Traduction"), _("Choisissez la langue du texte."))
            return
        if src == dst:
            QMessageBox.information(self, _("Traduction"), _("Les langues source et cible sont identiques."))
            return
        moteur = self.moteur.currentData()
        fonction = self.p.preparer(moteur, src, dst, self.vue)
        if fonction is None:
            return
        self.p.ctx.reglages.set("cible", dst)
        self.annuler.clear()
        self.travail = True
        self.b_trad.setEnabled(False)
        self.b_stop.setEnabled(True)
        self.barre.setRange(0, 0)
        self.etat.setText(_("Préparation du moteur…") if moteur == "llama" else _("Traduction…"))
        self._maj_boutons()
        self.p.occupe += 1
        threading.Thread(target=self._travail, args=(fonction, texte, src, dst), daemon=True).start()

    def _travail(self, fonction, texte, src, dst):
        try:
            res = logique.traduire_texte(texte, src, dst, lambda m: fonction(m, self.annuler.is_set),
                                         lambda f, t: _emettre(self.pont.progression, f, t), self.annuler.is_set)
            _emettre(self.pont.fini, res, "")
        except logique.Annule:
            _emettre(self.pont.fini, "", _("Traduction arrêtée."))
        except Exception as ex:
            _emettre(self.pont.fini, "", str(ex) or type(ex).__name__)

    def _progression(self, fait, total):
        self.barre.setRange(0, max(total, 1))
        self.barre.setValue(fait)
        self.etat.setText(_("Traduction… %(f)d / %(t)d") % {"f": fait, "t": total})

    def _fini(self, res, erreur):
        self.p.occupe = max(0, self.p.occupe - 1)
        self.travail = False
        self.b_trad.setEnabled(True)
        self.b_stop.setEnabled(False)
        self.barre.setRange(0, 1)
        self.barre.setValue(0 if erreur else 1)
        if erreur:
            self.etat.setText("⚠ " + erreur)
        else:
            self.resultat.setPlainText(res or "")
            self.etat.setText(_("Terminé : relisez, puis insérez ou remplacez."))
        self._maj_boutons()

    def reject(self):
        self.annuler.set()
        super().reject()

    # ----- que faire de la traduction -----
    def _inserer_sous(self):
        trad = self.resultat.toPlainText().strip()
        ui = self.p.ctx.ui
        ok = ui.inserer_texte(f"{self.source.toPlainText().strip()}\n\n{trad}") if self.selection else ui.ajouter_a_la_fin(f"\n\n{trad}\n")
        self._apres(ok)

    def _remplacer(self):
        trad = self.resultat.toPlainText().strip()
        ui = self.p.ctx.ui
        if not self.selection and QMessageBox.question(
                self, _("Remplacer"), _("Remplacer tout le texte de la fiche par la traduction ? (Ctrl+Z l'annule.)")) != QMessageBox.StandardButton.Yes:
            return
        self._apres(ui.inserer_texte(trad) if self.selection else ui.remplacer_tout(trad))

    def _apres(self, ok):
        if ok:
            self.accept()
        else:
            QMessageBox.warning(self, _("Traduction"), _("La fiche n'est pas modifiable (aucune fiche ouverte, ou verrouillée fermée)."))


class TraductionPlugin(Plugin):
    api = 1

    def activer(self, ctx):
        self.ctx = ctx
        self.occupe = 0
        self.serveur = logique.ServeurLlama(ctx.dossier_donnees / "llama-server.log")
        self.deps = ctx.dossier_donnees / "deps"
        if self.deps.is_dir() and str(self.deps) not in sys.path:
            sys.path.insert(0, str(self.deps))
        if ctx.ui is None:
            return
        ctx.ui.ajouter_bouton(_("Traduire"), self.traduire, "preferences-desktop-locale")
        ctx.ui.ajouter_action(_("Traduire la sélection ou la fiche…"), self.traduire, "preferences-desktop-locale")
        ctx.ui.ajouter_action(_("Réglages de la traduction…"), self.reglages, "configure")
        ctx.ui.planifier(60, self._surveiller, repeter=True)

    def desactiver(self):
        self.serveur.arreter()
        if str(self.deps) in sys.path:
            sys.path.remove(str(self.deps))

    def _surveiller(self):
        """Libère la mémoire (et la carte graphique) quand le serveur lancé par l'extension ne sert plus."""
        minutes = int(self.ctx.reglages.get("inactivite", 10))
        if self.serveur.vivant() and not self.occupe and self.serveur.inactif_depuis() > minutes * 60:
            self.serveur.arreter()

    # ---------- fenêtres ----------
    def traduire(self):
        vue = self.ctx.fiche_courante()
        selection = self.ctx.ui.texte_selectionne()
        texte = selection if selection.strip() else self.ctx.ui.texte_complet()
        if vue is None or not texte.strip():
            self.ctx.ui.notifier(_("Traduction"), _("Ouvrez une fiche (déverrouillée) qui contient du texte."))
            return
        DialogueTraduction(self, texte, bool(selection.strip()), vue, _parent()).exec()

    def reglages(self):
        DialogueReglages(self, _parent()).exec()

    def aide_installation(self):
        m = QMessageBox(_parent())
        m.setWindowTitle(_("Installer llama.cpp"))
        m.setText(_("llama.cpp n'est pas installé par l'extension : vous choisissez comment."))
        m.setInformativeText(logique.aide_installation())
        ouvrir = m.addButton(_("Ouvrir la page des versions"), QMessageBox.ButtonRole.ActionRole)
        m.addButton(QMessageBox.StandardButton.Close)
        m.exec()
        if m.clickedButton() is ouvrir:
            QDesktopServices.openUrl(QUrl(logique.PAGE_VERSIONS))

    # ---------- préparation d'un moteur ----------
    def preparer(self, moteur, src, dst, vue):
        """Retourne `fonction(morceau, annule) -> str` prête, ou None après avoir expliqué ce qui manque ou demandé un accord."""
        return self._preparer_llama(src, dst, vue) if moteur == "llama" else self._preparer_argos(src, dst)

    def _preparer_llama(self, src, dst, vue):
        r = self.ctx.reglages
        src_url = r.get("url", "").strip()
        if src_url:
            if not logique.est_local(src_url):
                if not r.get("distant_ok", False):
                    QMessageBox.warning(_parent(), _("Traduction"), _("Le serveur %s n'est pas local : le texte serait envoyé hors de cette "
                                                                       "machine. Cochez la case d'acceptation dans les réglages pour l'autoriser.") % src_url)
                    return None
                if vue is not None and vue.verrou and QMessageBox.question(
                        _parent(), _("Fiche verrouillée"), _("Cette fiche est verrouillée et le serveur %s n'est pas local : envoyer quand même son texte ?")
                        % src_url) != QMessageBox.StandardButton.Yes:
                    return None
            cle = r.get("cle", "")
            return lambda m, annule: logique.completer(src_url, cle, logique.consigne(m, src, dst), logique.n_predict_pour(m))
        exe = logique.trouver_llama(r.get("exe", ""), self.ctx.dossier_donnees)
        if not exe:
            self.aide_installation()
            return None
        modele = logique.trouver_modele(r.get("modele", ""), self.ctx.dossier_donnees)
        if not modele:
            modele = self.telecharger_modele()
            if not modele:
                return None
        gpu = r.get("gpu", "")

        def fonction(morceau, annule):
            self.serveur.demarrer(exe, modele, gpu, annuler=annule)
            return self.serveur.completer(logique.consigne(morceau, src, dst), logique.n_predict_pour(morceau))
        return fonction

    def _preparer_argos(self, src, dst):
        dossier = self.ctx.dossier_donnees / "argos"
        if not logique.argos_present() and not self.installer_argos():
            return None
        try:
            ok = logique.argos_paire_installee(src, dst, dossier)
        except logique.ErreurMoteur as ex:
            QMessageBox.warning(_parent(), _("Argos Translate"), f"{ex}\n\n{AIDE_ARGOS_LOURD}")
            return None
        if not ok:
            paquets, err = en_arriere_plan(_("Argos Translate"), _("Recherche du modèle de langue…"),
                                           lambda a, p: logique.argos_modeles_necessaires(src, dst, dossier))
            if err:
                QMessageBox.warning(_parent(), _("Argos Translate"), err)
                return None
            noms = ", ".join(f"{x.from_code} → {x.to_code}" for x in paquets)
            if QMessageBox.question(_parent(), _("Modèle de langue"), _("Argos a besoin du modèle de langue : %s.\n\nIl sera téléchargé depuis "
                                                                         "l'index public d'Argos Translate et rangé dans :\n%s\n\nTélécharger maintenant ?")
                                    % (noms, dossier)) != QMessageBox.StandardButton.Yes:
                return None
            _res, err = en_arriere_plan(_("Argos Translate"), _("Téléchargement du modèle de langue…"),
                                        lambda a, p: logique.argos_installer_paquets(paquets, dossier))
            if err:
                QMessageBox.warning(_parent(), _("Argos Translate"), err)
                return None
        return lambda m, annule: logique.argos_traduire(m, src, dst, dossier)

    # ---------- installations (toujours avec accord) ----------
    def telecharger_modele(self):
        """Propose de télécharger le modèle recommandé ; retourne son chemin, ou None."""
        dossier = self.ctx.dossier_donnees / "modeles"
        if QMessageBox.question(
                _parent(), _("Modèle de traduction"),
                _("Il manque le modèle de traduction (TranslateGemma 4B, quantifié Q4_K_M, licence Gemma).\n\nTaille : %(t)s\nSource : %(u)s\n"
                  "Destination : %(d)s\n\nLa somme de contrôle SHA-256 est vérifiée. Télécharger maintenant ?")
                % {"t": _taille(logique.MODELE_TAILLE), "u": logique.MODELE_URL, "d": dossier}) != QMessageBox.StandardButton.Yes:
            return None
        chemin, err = en_arriere_plan(_("Modèle de traduction"), _("Téléchargement du modèle…"),
                                      lambda annuler, prog: logique.telecharger_modele(dossier, progression=prog, annuler=annuler.is_set),
                                      annulable=True)
        if err:
            if err != "annulé":
                QMessageBox.warning(_parent(), _("Modèle de traduction"), err)
            return None
        self.ctx.reglages.set("modele", str(chemin))
        return str(chemin)

    def installer_argos(self) -> bool:
        """Installe Argos Translate dans le dossier de l'extension (sans PyTorch). True si utilisable ensuite."""
        deps = self.deps
        if QMessageBox.question(
                _parent(), _("Argos Translate"),
                _("Argos Translate sera installé uniquement pour cette extension, dans :\n%s\n\nSeules ses dépendances légères sont installées "
                  "(CTranslate2, SentencePiece, SacreMoses, MiniSBD) : PyTorch n'est pas ajouté. L'installation télécharge depuis Internet "
                  "(PyPI). Installer maintenant ?") % deps) != QMessageBox.StandardButton.Yes:
            return False
        deps.mkdir(parents=True, exist_ok=True)
        base = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--target", str(deps)]
        etapes = [base[1:] + ["ctranslate2>=4.0,<5", "sentencepiece>=0.2.0,<0.3", "sacremoses>=0.0.53,<0.2", "minisbd", "packaging"],
                  base[1:] + ["--no-deps", "argostranslate"]]
        dlg = _Installation(_("Installation d'Argos Translate"), etapes, _parent())
        dlg.exec()
        if not dlg.ok:
            QMessageBox.warning(_parent(), _("Argos Translate"), _("L'installation a échoué."))
            return False
        if str(deps) not in sys.path:
            sys.path.insert(0, str(deps))
        import importlib
        importlib.invalidate_caches()
        try:
            logique.argos_langues_installees(self.ctx.dossier_donnees / "argos")
        except logique.ErreurMoteur as ex:
            QMessageBox.warning(_parent(), _("Argos Translate"), f"{ex}\n\n{AIDE_ARGOS_LOURD}")
            return False
        return True

    def tester_llama(self):
        """Démarre le serveur et traduit « Bonjour » : dit si tout est en place."""
        fonction = self._preparer_llama("fr", "en", None)
        if fonction is None:
            return
        res, err = en_arriere_plan(_("Test de la traduction"), _("Démarrage de llama.cpp et traduction d'essai…"),
                                   lambda annuler, prog: fonction("Bonjour, ceci est un test.", annuler.is_set), annulable=True)
        if err and err != "annulé":
            QMessageBox.warning(_parent(), _("Test de la traduction"), err)
        elif not err:
            QMessageBox.information(_parent(), _("Test de la traduction"), _("✔ llama.cpp fonctionne.\n\nBonjour, ceci est un test.\n→ %s") % res)

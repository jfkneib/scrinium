# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « Lecture à voix haute » : lit une fiche, la sélection ou toutes les fiches d'un thème.

- Voix **Piper** (naturelle, hors ligne) : paquet `piper-tts` installé par pip dans le dossier de l'extension et voix
  téléchargée (taille et SHA-256 vérifiés), l'un et l'autre APRÈS votre accord. Repli : **espeak-ng** s'il est installé.
- Français ou anglais : langue détectée fiche par fiche, ou imposée dans les réglages.
- Les fiches verrouillées ne sont JAMAIS lues (même ouvertes). Le texte lu est nettoyé du Markdown ; les blocs de code sautés.
- Contrôles : pause, fiche suivante, arrêt. Le son sort par paplay, pw-play ou aplay ; rien n'est envoyé sur Internet,
  hormis l'installation et le téléchargement demandés explicitement."""
import sys
import threading

from PyQt6.QtCore import QProcess, Qt, QTimer
from PyQt6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QInputDialog, QLabel,
                             QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSlider, QVBoxLayout)

from scrinium.core.plugins import Plugin
from scrinium.i18n import _

from . import logique


def _parent():
    return QApplication.activeWindow()


def _mo(octets: int) -> str:
    return _("%s Mo") % f"{octets / 1048576:,.0f}".replace(",", " ")


class _Installation(QDialog):
    """`pip install --target` du paquet Piper, avec la sortie à l'écran."""

    def __init__(self, cible, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Installation de Piper"))
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
        self.p = QProcess(self)
        self.p.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.p.readyRead.connect(lambda: self.log.appendPlainText(bytes(self.p.readAll()).decode(errors="replace").rstrip()))
        self.p.finished.connect(self._fini)
        self.p.start(sys.executable, ["-m", "pip", "install", "--upgrade", "--disable-pip-version-check", "--target", str(cible),
                                      logique.PAQUET_PIPER])

    def _fini(self, code, _statut):
        self.ok = code == 0
        self.barre.setRange(0, 1)
        self.barre.setValue(1 if self.ok else 0)
        self.boutons.setEnabled(True)
        if self.ok:
            self.accept()
        else:
            self.log.appendPlainText(_("Échec (code %s). Voyez ci-dessus.") % code)

    def reject(self):
        if self.p.state() != QProcess.ProcessState.NotRunning:
            self.p.kill()
            self.p.waitForFinished(2000)
        super().reject()


class _Telechargement(QDialog):
    """Téléchargement d'une voix dans un fil de travail ; l'interface reste vivante (annulable)."""

    def __init__(self, modeles, cle, parent=None):
        super().__init__(parent)
        v = logique.VOIX[cle]
        self.setWindowTitle(_("Téléchargement de la voix"))
        lay = QVBoxLayout(self)
        self.texte = QLabel(_("Téléchargement de « %(voix)s » (%(taille)s)…") % {"voix": _(v["libelle"]), "taille": _mo(v["taille"])})
        self.barre = QProgressBar()
        self.barre.setRange(0, max(1, v["taille"] // 1048576))
        annuler = QPushButton(_("Annuler"))
        annuler.clicked.connect(self.reject)
        for w in (self.texte, self.barre, annuler):
            lay.addWidget(w)
        self.ok, self.erreur, self.fait, self.annule = False, "", 0, False
        self.fini = threading.Event()

        def travail():
            try:
                logique.telecharger_voix(modeles, cle, lambda f, t: setattr(self, "fait", f), lambda: self.annule)
                self.ok = True
            except logique.Annule:
                self.erreur = _("annulé")
            except (OSError, ValueError) as ex:
                self.erreur = str(ex)
            self.fini.set()
        threading.Thread(target=travail, daemon=True).start()
        self.minuteur = QTimer(self, interval=150)
        self.minuteur.timeout.connect(self._maj)
        self.minuteur.start()

    def _maj(self):
        self.barre.setValue(min(self.barre.maximum(), self.fait // 1048576))
        if self.fini.is_set():
            self.minuteur.stop()
            self.accept() if self.ok else super().reject()

    def reject(self):
        self.annule = True                 # le fil s'arrête et supprime le fichier partiel ; _maj ferme la fenêtre


class FenetreLecture(QDialog):
    """Petite fenêtre non modale, au premier plan : fiche en cours, pause, suivante, arrêt."""

    def __init__(self, plugin):
        super().__init__(None)
        self.p = plugin
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle(_("Lecture à voix haute"))
        self.resize(380, 140)
        lay = QVBoxLayout(self)
        self.titre = QLabel("")
        self.titre.setWordWrap(True)
        self.etat = QLabel("")
        self.etat.setWordWrap(True)
        lay.addWidget(self.titre)
        lay.addWidget(self.etat)
        rang = QHBoxLayout()
        self.b_pause = QPushButton(_("Pause"))
        self.b_pause.clicked.connect(plugin.basculer_pause)
        self.b_suivante = QPushButton(_("Fiche suivante"))
        self.b_suivante.clicked.connect(plugin.suivante)
        b_stop = QPushButton(_("Arrêter"))
        b_stop.clicked.connect(self.close)
        for b in (self.b_pause, self.b_suivante, b_stop):
            rang.addWidget(b)
        lay.addLayout(rang)

    def closeEvent(self, ev):
        self.en_fermeture = True               # le plugin ne doit pas rappeler close() sur une fenêtre qui se ferme déjà
        self.p.arreter(ferme=True)
        super().closeEvent(ev)


class DialogueReglages(QDialog):
    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.p = plugin
        r = plugin.ctx.reglages
        self.setWindowTitle(_("Réglages de la lecture"))
        f = QFormLayout(self)
        self.moteur = QComboBox()
        for cle, libelle in (("auto", _("Automatique (Piper si possible, sinon espeak-ng)")), ("piper", _("Piper (voix naturelle)")),
                             ("espeak", _("espeak-ng (voix robotique, rien à télécharger)"))):
            self.moteur.addItem(libelle, cle)
        self.moteur.setCurrentIndex(max(0, self.moteur.findData(r.get("moteur", "auto"))))
        self.langue = QComboBox()
        for cle, libelle in (("auto", _("Automatique (détectée dans le texte)")), ("fr", _("Toujours le français")),
                             ("en", _("Toujours l'anglais"))):
            self.langue.addItem(libelle, cle)
        self.langue.setCurrentIndex(max(0, self.langue.findData(r.get("langue", "auto"))))
        self.vitesse = QSlider(Qt.Orientation.Horizontal)
        self.vitesse.setRange(int(logique.VITESSE_MIN * 10), int(logique.VITESSE_MAX * 10))
        self.vitesse.setValue(int(round(logique.vitesse_valide(r.get("vitesse", 1.0)) * 10)))
        self.vitesse.setToolTip(_("1,0 = vitesse normale"))
        f.addRow(_("Moteur :"), self.moteur)
        f.addRow(_("Langue :"), self.langue)
        f.addRow(_("Vitesse :"), self.vitesse)
        self.voix = {}
        for code in logique.LANGUES:
            c = QComboBox()
            for cle, v in logique.VOIX.items():
                if v["langue"] == code:
                    etat = _("installée") if logique.voix_presente(plugin.modeles, cle) else _("à télécharger, %s") % _mo(v["taille"])
                    c.addItem(f"{_(v['libelle'])} ({etat})", cle)
            c.setCurrentIndex(max(0, c.findData(r.get(f"voix_{code}", logique.VOIX_DEFAUT[code]))))
            self.voix[code] = c
            f.addRow(_("Voix (%s) :") % _(logique.LANGUES[code]), c)
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        b.accepted.connect(self._valider)
        b.rejected.connect(self.reject)
        f.addRow(b)

    def _valider(self):
        r = self.p.ctx.reglages
        r.set("moteur", self.moteur.currentData())
        r.set("langue", self.langue.currentData())
        r.set("vitesse", self.vitesse.value() / 10)
        for code, c in self.voix.items():
            r.set(f"voix_{code}", c.currentData())
        r.set("piper_refuse", False)          # on a changé d'avis possible : la proposition d'installation peut revenir
        self.accept()


class LecturePlugin(Plugin):
    api = 1

    def activer(self, ctx):
        self.ctx = ctx
        self.deps = ctx.dossier_donnees / "deps"
        self.modeles = ctx.dossier_donnees / "modeles"
        self.lecture = None
        self.fenetre = None
        self.file = []
        self.index = 0
        if ctx.ui is None:
            return
        if not logique.systeme_pris_en_charge():
            raise RuntimeError(_("lecture à voix haute : pour l'instant Linux seulement"))
        self.minuteur = ctx.ui.planifier(0.25, self._tic, repeter=True)
        a = ctx.ui.ajouter_action(_("Lire la fiche à voix haute"), self.lire_fiche, "media-playback-start")
        a.setShortcut("Ctrl+Alt+L")
        ctx.ui.ajouter_bouton(_("Lire"), self.lire_fiche, "media-playback-start")
        ctx.ui.ajouter_action(_("Lire la sélection à voix haute"), self.lire_selection, "media-playback-start")
        ctx.ui.ajouter_action(_("Lire un thème à voix haute…"), self.lire_theme, "media-playback-start")
        ctx.ui.ajouter_action(_("Arrêter la lecture"), lambda: self.arreter(ferme=True), "media-playback-stop")
        ctx.ui.ajouter_action(_("Réglages de la lecture…"), self.reglages, "configure")

    def desactiver(self):
        self.arreter(ferme=True)

    # ---------- choix du moteur ----------
    def _voix(self, lang: str) -> str:
        cle = self.ctx.reglages.get(f"voix_{lang}", logique.VOIX_DEFAUT[lang])
        return cle if cle in logique.VOIX and logique.VOIX[cle]["langue"] == lang else logique.VOIX_DEFAUT[lang]

    def preparer(self, lang: str):
        """Moteur à utiliser pour cette langue : ("piper", voix) ou ("espeak", exécutable) ; None (avec message) sinon."""
        r = self.ctx.reglages
        choix = r.get("moteur", "auto")
        cle = self._voix(lang)
        if choix in ("auto", "piper"):
            if logique.piper_present(self.deps) and logique.voix_presente(self.modeles, cle):
                return "piper", cle
            if choix == "piper" or not r.get("piper_refuse", False):
                if self._installer_piper(cle):
                    return "piper", cle
                if choix == "auto":
                    r.set("piper_refuse", True)                # une fois suffit : on ne redemande pas à chaque lecture
        exe = logique.espeak()
        if choix in ("auto", "espeak") and exe:
            return "espeak", exe
        self.ctx.ui.notifier(_("Lecture"), logique.aide_installation())
        return None

    def _installer_piper(self, cle: str) -> bool:
        """Propose (avec taille et provenance) d'installer Piper et/ou la voix ; True si tout est prêt ensuite."""
        besoin_paquet, besoin_voix = not logique.piper_present(self.deps), not logique.voix_presente(self.modeles, cle)
        v = logique.VOIX[cle]
        lignes = []
        if besoin_paquet:
            lignes.append(_("• le paquet Python « piper-tts » (≈ 50 Mo avec ses dépendances), installé uniquement pour cette "
                            "extension dans :\n  %s (depuis PyPI)") % self.deps)
        if besoin_voix:
            lignes.append(_("• la voix « %(voix)s » (%(taille)s), téléchargée depuis huggingface.co dans :\n  %(dossier)s "
                            "(taille et SHA-256 vérifiés)") % {"voix": _(v["libelle"]), "taille": _mo(v["taille"]), "dossier": self.modeles})
        rep = QMessageBox.question(_parent(), _("Lecture à voix haute"),
                                   _("Pour une voix naturelle, Piper a besoin de :\n\n%s\n\nRien d'autre n'est touché sur "
                                     "votre système. Installer maintenant ? (Sinon, espeak-ng sera utilisé s'il est présent.)")
                                   % "\n\n".join(lignes))
        if rep != QMessageBox.StandardButton.Yes:
            return False
        if besoin_paquet:
            self.deps.mkdir(parents=True, exist_ok=True)
            dlg = _Installation(self.deps, _parent())
            dlg.exec()
            if not dlg.ok or not logique.piper_present(self.deps):
                QMessageBox.warning(_parent(), _("Lecture à voix haute"), _("L'installation de Piper a échoué."))
                return False
        if besoin_voix:
            dlg = _Telechargement(self.modeles, cle, _parent())
            dlg.exec()
            if not dlg.ok:
                QMessageBox.warning(_parent(), _("Lecture à voix haute"), _("Téléchargement impossible : %s") % dlg.erreur)
                return False
        return True

    # ---------- ce qu'on lit ----------
    def lire_fiche(self):
        vue = self.ctx.fiche_courante()
        if vue is None:
            self.ctx.ui.notifier(_("Lecture"), _("Ouvrez d'abord une fiche."))
        elif vue.verrou:
            self.ctx.ui.notifier(_("Lecture"), _("Une fiche verrouillée n'est jamais lue à voix haute."))
        else:
            self.lire([(vue.titre, self.ctx.ui.texte_complet())])

    def lire_selection(self):
        vue = self.ctx.fiche_courante()
        if vue is not None and vue.verrou:
            self.ctx.ui.notifier(_("Lecture"), _("Une fiche verrouillée n'est jamais lue à voix haute."))
            return
        texte = self.ctx.ui.texte_selectionne()
        if not texte.strip():
            self.ctx.ui.notifier(_("Lecture"), _("Sélectionnez d'abord du texte dans la fiche."))
            return
        self.lire([(_("Sélection"), texte)])

    def lire_theme(self):
        themes = self.ctx.themes()
        if not themes:
            return
        vue = self.ctx.fiche_courante()
        defaut = themes.index(vue.theme) if vue is not None and vue.theme in themes else 0
        theme, ok = QInputDialog.getItem(_parent(), _("Lecture"), _("Lire toutes les fiches de quel thème ?"), themes, defaut, False)
        if ok:
            self.lire_un_theme(theme)

    def elements_theme(self, theme: str) -> tuple:
        """([(titre, texte)], nombre de fiches verrouillées ignorées) ; fiches sans texte lisible ignorées sans bruit."""
        elements, verrouillees = [], 0
        for v in self.ctx.fiches(theme):
            if v.verrou:
                verrouillees += 1
            elif v.texte and logique.phrases(v.texte):
                elements.append((v.titre, v.texte))
        return elements, verrouillees

    def lire_un_theme(self, theme: str):
        elements, verrouillees = self.elements_theme(theme)
        if not elements:
            self.ctx.ui.notifier(_("Lecture"), _("Aucune fiche à lire dans « %s ».") % theme)
            return
        self.lire(elements, ignorees=verrouillees)

    # ---------- lecture ----------
    def lire(self, elements: list, ignorees: int = 0):
        """File d'attente [(titre, texte)] ; la fenêtre de lecture s'ouvre et la première fiche démarre."""
        self.arreter(ferme=True)
        self.file = [(t, x) for t, x in elements if logique.phrases(x)]
        if not self.file:
            self.ctx.ui.notifier(_("Lecture"), _("Rien à lire."))
            return
        self.ignorees, self.index = ignorees, -1
        self.fenetre = FenetreLecture(self)
        self.fenetre.show()
        self.fenetre.raise_()
        self.suivante()

    def suivante(self):
        """Passe à la fiche suivante de la file (arrête la lecture en cours) ; ferme la fenêtre à la fin."""
        if self.lecture is not None:
            self.lecture.arreter()
            self.lecture = None
        self.index += 1
        if self.index >= len(self.file):
            return self.arreter(ferme=True)
        titre, texte = self.file[self.index]
        lang = logique.langue_de_lecture(texte, self.ctx.reglages.get("langue", "auto"))
        moteur = self.preparer(lang)
        if moteur is None:
            return self.arreter(ferme=True)
        lignes, vitesse = logique.phrases(texte), self.ctx.reglages.get("vitesse", 1.0)
        try:
            if moteur[0] == "piper":
                self.lecture = logique.demarrer_piper(self.deps, self.modeles, moteur[1], lignes, vitesse)
            else:
                self.lecture = logique.demarrer_espeak(moteur[1], lang, lignes, vitesse)
        except OSError as ex:
            self.ctx.ui.notifier(_("Lecture"), _("Impossible de lire : %s") % ex)
            return self.arreter(ferme=True)
        self._afficher(titre, lang, moteur[0])

    def _afficher(self, titre: str, lang: str, moteur: str):
        if self.fenetre is None:
            return
        n = len(self.file)
        self.fenetre.titre.setText(f"<b>{titre.replace('<', '&lt;')}</b>")
        self.fenetre.etat.setText(
            (_("Fiche %(i)d sur %(n)d") % {"i": self.index + 1, "n": n} if n > 1 else "") + (" · " if n > 1 else "")
            + _(logique.LANGUES[lang]) + " · " + ("Piper" if moteur == "piper" else "espeak-ng")
            + (" · " + _("%d fiche(s) verrouillée(s) ignorée(s)") % self.ignorees if self.ignorees else ""))
        self.fenetre.b_pause.setText(_("Pause"))
        self.fenetre.b_suivante.setEnabled(self.index + 1 < n)

    def basculer_pause(self):
        if self.lecture is None:
            return
        if self.lecture.en_pause:
            self.lecture.reprendre()
            self.fenetre.b_pause.setText(_("Pause"))
        else:
            self.lecture.pause()
            self.fenetre.b_pause.setText(_("Reprendre"))

    def arreter(self, ferme: bool = False):
        lecture, self.lecture, self.file = self.lecture, None, []
        if lecture is not None:
            lecture.arreter()
        fenetre, self.fenetre = self.fenetre, None
        if ferme and fenetre is not None and not getattr(fenetre, "en_fermeture", False):
            fenetre.close()

    def _tic(self):
        """Toutes les 250 ms : détecte la fin de la fiche en cours (ou une erreur du moteur) et passe à la suivante."""
        if self.lecture is None or not self.lecture.terminee():
            return
        erreur = self.lecture.erreur()
        if erreur:
            self.ctx.ui.notifier(_("Lecture"), _("Le moteur de voix a échoué : %s") % erreur)
            return self.arreter(ferme=True)
        self.suivante()

    def reglages(self):
        DialogueReglages(self, _parent()).exec()

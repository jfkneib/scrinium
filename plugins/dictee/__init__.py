# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « Dictée vocale » : micro -> faster-whisper (local) -> texte inséré au curseur de la fiche.

- Au premier choix de l'extension, une boîte demande l'accord pour installer `faster-whisper` (pip --target dans le
  dossier de données de l'extension : rien n'est touché dans le système ni dans l'environnement de Scrinium).
- Le modèle de reconnaissance est téléchargé à la première dictée, après accord (taille affichée).
- Enregistrement par `parecord` / `pw-record` / `arecord` (déjà présents sur un bureau Linux) : aucune bibliothèque audio à installer.
- Rien n'est envoyé sur Internet, hormis le téléchargement du modèle et l'installation du paquet, demandés explicitement.
"""
import importlib.util
import shutil
import subprocess
import sys
import threading

from PyQt6.QtCore import QObject, QProcess, Qt, pyqtSignal
from PyQt6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QInputDialog, QMessageBox, QPlainTextEdit,
                             QProgressBar, QVBoxLayout)

from scrinium.core.plugins import Plugin
from scrinium.i18n import _

PAQUET = "faster-whisper"
RATE = 16000
MODELES = {"base": "≈ 145 Mo, rapide", "small": "≈ 480 Mo, meilleur en français", "medium": "≈ 1,5 Go, précis mais lent"}
LANGUES = {"": "automatique", "fr": "français", "en": "anglais"}
ENREGISTREURS = (  # (exécutable, arguments) -> PCM 16 bits mono 16 kHz brut sur la sortie standard
    ("parecord", ["--raw", "--rate=16000", "--channels=1", "--format=s16le"]),
    ("pw-record", ["--rate", "16000", "--channels", "1", "--format", "s16", "-"]),
    ("arecord", ["-q", "-t", "raw", "-f", "S16_LE", "-r", "16000", "-c", "1"]),
)


def _parent():
    return QApplication.activeWindow()


def _present() -> bool:
    return importlib.util.find_spec("faster_whisper") is not None


class _Installation(QDialog):
    """Lance `pip install --target` et affiche la sortie ; se ferme à la main une fois fini."""

    def __init__(self, cible, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Installation de %s") % PAQUET)
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
        self.p.start(sys.executable, ["-m", "pip", "install", "--upgrade", "--disable-pip-version-check",
                                      "--target", str(cible), PAQUET])

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


class _Pont(QObject):
    """Ramène dans le fil de l'interface le résultat du fil de reconnaissance."""
    texte = pyqtSignal(str)
    erreur = pyqtSignal(str)


class DicteePlugin(Plugin):
    api = 1

    # ---------- activation : dépendances d'abord ----------
    def activer(self, ctx):
        self.ctx = ctx
        self.deps = ctx.dossier_donnees / "deps"
        self.modeles = ctx.dossier_donnees / "modeles"
        self.rec = None
        self.modele = None
        self.occupe = False
        if str(self.deps) not in sys.path and self.deps.is_dir():
            sys.path.insert(0, str(self.deps))
        if ctx.ui is None:
            return
        if not self._enregistreur():
            raise RuntimeError(_("aucun enregistreur audio trouvé (parecord, pw-record ou arecord)"))
        if not _present():
            self._demander_installation()
        self.pont = _Pont()
        self.pont.texte.connect(self._texte_pret)
        self.pont.erreur.connect(self._erreur)
        self.action = ctx.ui.ajouter_action(_("Dicter"), self.basculer, "audio-input-microphone")
        self.action.setShortcut("Ctrl+Alt+D")
        self.bouton = ctx.ui.ajouter_bouton(_("Dicter"), self.basculer, "audio-input-microphone")
        self.actions = (self.action, self.bouton)
        for a in self.actions:      # bouton enfoncé = micro ouvert
            a.setCheckable(True)
        ctx.ui.ajouter_action(_("Réglages de la dictée…"), self.reglages, "configure")

    def desactiver(self):
        self._arreter_micro()
        if str(self.deps) in sys.path:
            sys.path.remove(str(self.deps))

    @staticmethod
    def _enregistreur():
        for exe, args in ENREGISTREURS:
            if shutil.which(exe):
                return [shutil.which(exe), *args]
        return None

    def _demander_installation(self):
        rep = QMessageBox.question(
            _parent(), _("Dictée vocale"),
            _("La dictée a besoin du paquet Python « %s » (≈ 250 Mo avec ses dépendances).\n\n"
              "Il sera installé uniquement pour cette extension, dans :\n%s\n\n"
              "L'installation télécharge depuis Internet (PyPI). Installer maintenant ?") % (PAQUET, self.deps))
        if rep != QMessageBox.StandardButton.Yes:
            raise RuntimeError(_("installation de %s refusée") % PAQUET)
        self.deps.mkdir(parents=True, exist_ok=True)
        dlg = _Installation(self.deps, _parent())
        dlg.exec()
        if not dlg.ok:
            raise RuntimeError(_("échec de l'installation de %s") % PAQUET)
        sys.path.insert(0, str(self.deps))
        importlib.invalidate_caches()
        if not _present():
            raise RuntimeError(_("%s installé mais introuvable") % PAQUET)

    # ---------- réglages ----------
    def reglages(self):
        r = self.ctx.reglages
        noms = [f"{m} — {d}" for m, d in MODELES.items()]
        cur = list(MODELES).index(r.get("modele", "small"))
        choix, ok = QInputDialog.getItem(_parent(), _("Dictée"), _("Modèle de reconnaissance :"), noms, cur, False)
        if not ok:
            return
        r.set("modele", choix.split(" — ")[0])
        self.modele = None
        langues = [f"{c or 'auto'} — {n}" for c, n in LANGUES.items()]
        cur = list(LANGUES).index(r.get("langue", "fr"))
        choix, ok = QInputDialog.getItem(_parent(), _("Dictée"), _("Langue parlée :"), langues, cur, False)
        if ok:
            c = choix.split(" — ")[0]
            r.set("langue", "" if c == "auto" else c)

    # ---------- enregistrement ----------
    def basculer(self):
        if self.rec is not None:
            self._arreter_et_transcrire()
        elif not self.occupe:
            self._demarrer_micro()
        self._etat()

    def _etat(self):
        """Aligne boutons et menu sur l'état réel : enfoncé et « ● » tant que le micro enregistre."""
        on = self.rec is not None
        for a in self.actions:
            a.setChecked(on)
            a.setText(_("● Enregistrement… (cliquer pour arrêter)") if on else _("Dicter"))

    def _demarrer_micro(self):
        if not self.ctx.ui.inserer_texte(""):
            self.ctx.ui.notifier(_("Dictée"), _("Ouvrez d'abord une fiche modifiable."))
            return
        if not self._modele_pret():
            return
        self.rec = subprocess.Popen(self._enregistreur(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.audio = bytearray()
        self.lecteur = threading.Thread(target=self._lire, args=(self.rec,), daemon=True)
        self.lecteur.start()
        self.ctx.ui.notifier(_("Dictée"), _("Je vous écoute… (cliquer à nouveau ou Ctrl+Alt+D pour arrêter)"))

    def _lire(self, proc):
        while chunk := proc.stdout.read(4096):
            self.audio += chunk

    def _arreter_micro(self):
        p, self.rec = self.rec, None
        if p is not None:
            p.terminate()
            try:
                p.wait(2)
            except subprocess.TimeoutExpired:
                p.kill()
        if getattr(self, "actions", None):
            self._etat()

    def _arreter_et_transcrire(self):
        self._arreter_micro()
        self.lecteur.join(2)
        audio = bytes(self.audio)
        if len(audio) < RATE * 2 * 0.5:      # moins d'une demi-seconde
            return
        self.occupe = True
        self.ctx.ui.notifier(_("Dictée"), _("Transcription en cours…"))
        threading.Thread(target=self._transcrire, args=(audio,), daemon=True).start()

    # ---------- reconnaissance ----------
    def _nom_modele(self):
        return self.ctx.reglages.get("modele", "small")

    def _modele_pret(self) -> bool:
        """Vrai si le modèle est déjà sur disque, ou si l'utilisateur accepte de le télécharger."""
        nom = self._nom_modele()
        if self.modele is not None or any(self.modeles.glob(f"*faster-whisper-{nom}*")):
            return True
        rep = QMessageBox.question(
            _parent(), _("Dictée vocale"),
            _("Le modèle de reconnaissance « %s » (%s) n'est pas encore sur cet ordinateur.\n\n"
              "Le télécharger depuis Hugging Face dans :\n%s\n\n"
              "(le premier enregistrement attendra la fin du téléchargement). Continuer ?")
            % (nom, MODELES.get(nom, "?"), self.modeles))
        if rep != QMessageBox.StandardButton.Yes:
            return False
        self.modeles.mkdir(parents=True, exist_ok=True)
        self.ctx.ui.notifier(_("Dictée"), _("Téléchargement du modèle %s…") % nom)
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            QApplication.processEvents()
            self._charger()
        except Exception as ex:
            self.ctx.ui.notifier(_("Dictée"), _("Modèle indisponible : %s") % ex)
            return False
        finally:
            QApplication.restoreOverrideCursor()
        return True

    def _charger(self, device=None):
        from faster_whisper import WhisperModel
        device = device or self.ctx.reglages.get("calcul", "auto")
        self.modele = WhisperModel(self._nom_modele(), device=device, compute_type="default",
                                   download_root=str(self.modeles))
        self.device = device

    def _transcrire(self, audio: bytes):
        try:
            import numpy as np
            pcm = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
            langue = self.ctx.reglages.get("langue", "fr") or None
            for essai in (0, 1):
                if self.modele is None:
                    self._charger()
                try:
                    segs, _info = self.modele.transcribe(pcm, language=langue, vad_filter=True, beam_size=5)
                    texte = " ".join(s.text.strip() for s in segs).strip()
                    break
                except Exception:
                    if essai or getattr(self, "device", "cpu") == "cpu":   # CUDA absent/incomplet : repli sur le processeur
                        raise
                    self.modele = None
                    self._charger("cpu")
                    self.ctx.reglages.set("calcul", "cpu")
            self.pont.texte.emit(texte)
        except Exception as ex:
            self.pont.erreur.emit(f"{type(ex).__name__}: {ex}")

    def _texte_pret(self, texte):
        self.occupe = False
        if not texte:
            self.ctx.ui.notifier(_("Dictée"), _("Rien compris."))
        elif not self.ctx.ui.inserer_texte(texte + " "):
            self.ctx.ui.notifier(_("Dictée"), _("La fiche n'est plus modifiable : texte non inséré."))

    def _erreur(self, msg):
        self.occupe = False
        self.ctx.ui.notifier(_("Dictée"), _("Erreur : %s") % msg)

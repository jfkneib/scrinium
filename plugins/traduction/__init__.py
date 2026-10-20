# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « Traduction » : traduit la sélection (ou toute la fiche) avec un moteur LOCAL.

- TranslateGemma (4B) par llama.cpp, sans Ollama : l'extension lance `llama-server` à la demande (127.0.0.1, port libre, clé
  d'accès aléatoire), l'arrête après inactivité ou à la fermeture, ou se connecte à un serveur que vous avez déjà lancé.
- Rien ne quitte la machine (un serveur distant n'est utilisé que si vous l'acceptez explicitement). Aucun
  téléchargement sans votre accord, avec taille et provenance affichées. (Argos Translate a été retiré : il exige PyTorch.)
"""
import threading
import time
from pathlib import Path

from PyQt6.QtCore import QEventLoop, QObject, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
                             QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar, QProgressDialog, QPushButton,
                             QRadioButton, QSpinBox, QVBoxLayout)

from scrinium.core.plugins import Plugin
from scrinium.i18n import _

from . import logique

MOTEURS = {"llama": "TranslateGemma (llama.cpp)"}      # un seul moteur pour l'instant ; la liste reste prête pour d'autres


def _parent():
    return QApplication.activeWindow()


def _taille(octets: int) -> str:
    return f"{octets / 1e9:.2f} Go" if octets >= 1e9 else f"{octets / 1e6:.0f} Mo"


class _Pont(QObject):
    """Ramène dans le fil de l'interface ce qui se passe dans un fil de travail."""
    progression = pyqtSignal(object, object)       # « object » : un entier Qt de 32 bits déformerait les tailles de plus de 2 Go
    etat = pyqtSignal(str)
    fini = pyqtSignal(object, str)          # (résultat, erreur) ; erreur "" = réussi


def _emettre(signal, *args):
    try:
        signal.emit(*args)
    except RuntimeError:                    # la fenêtre a été fermée entre-temps
        pass


def en_arriere_plan(titre: str, message: str, fonction, annulable: bool = False, parent=None):
    """Exécute fonction(annuler: threading.Event, progression) dans un fil, avec une fenêtre qui dit où on en est. (résultat, erreur).
    `progression(fait, total)` met à jour la barre (en Mo : la barre de Qt n'accepte que des entiers de 32 bits) avec pourcentage,
    débit et temps restant ; `progression.etat(texte)` annonce une étape (ex. « Vérification… »)."""
    dlg = QProgressDialog(message, _("Annuler") if annulable else None, 0, 0, parent or _parent())
    dlg.setWindowTitle(titre)
    dlg.setMinimumDuration(0)
    dlg.setAutoClose(False)
    dlg.setAutoReset(False)
    dlg.setMinimumWidth(460)
    annuler = threading.Event()
    pont = _Pont()
    boucle = QEventLoop()
    sortie = {}
    suivi = {"base": None, "debut": time.time()}

    def progression(fait, total):
        _emettre(pont.progression, int(fait), int(total))
    progression.etat = lambda texte: _emettre(pont.etat, str(texte))

    def travail():
        try:
            sortie["res"], sortie["err"] = fonction(annuler, progression), ""
        except logique.Annule:
            sortie["res"], sortie["err"] = None, "annulé"
        except Exception as ex:
            sortie["res"], sortie["err"] = None, str(ex) or type(ex).__name__
        _emettre(pont.fini, None, "")

    def maj(fait, total):
        try:
            if total > 0:
                if suivi["base"] is None:
                    suivi["base"], suivi["debut"] = fait, time.time()
                mo = 1048576
                maxi = max(1, total // mo)
                dlg.setMaximum(maxi)
                dlg.setValue(min(fait // mo, maxi))
                dlg.setLabelText(f"{suivi.get('etat') or message}\n{logique.progression_texte(fait, total, time.time() - suivi['debut'], suivi['base'])}")
        except Exception:                                  # une erreur d'affichage ne doit jamais interrompre le travail
            pass

    def etape(texte):
        try:
            suivi["etat"] = texte if "Vérification" not in texte else None
            dlg.setLabelText(texte)
            if "Vérification" in texte:
                dlg.setMaximum(0)                          # durée inconnue : barre « en attente »
        except Exception:
            pass
    pont.progression.connect(maj)
    pont.etat.connect(etape)
    pont.fini.connect(lambda *_a: boucle.quit())
    dlg.canceled.connect(annuler.set)
    threading.Thread(target=travail, daemon=True).start()
    dlg.show()
    boucle.exec()
    dlg.close()
    return sortie.get("res"), sortie.get("err", "")


# Avantages et inconvénients montrés au choix du modèle. Chiffres MESURÉS le 2026-10-20 (RTX 3070 8 Go, processeur 16 cœurs) :
# 4B ≈ 106 mots-morceaux/s sur la carte, ≈ 10/s sur le processeur récent (16 threads), ≈ 7 à 8/s sur un i7-7500U (2017) et un i5-3570 (2012) ;
# 12B ≈ 7/s (carte de 8 Go : modèle réparti), ≈ 3/s sur le processeur. Mémoire maximale du 4B : 3,1 / 4,4 / 4,6 Go.
DESCRIPTIONS = {
    "4b": ([_("Léger : 2,49 Go à télécharger, 3 à 5 Go de mémoire (mesuré sur trois machines)."),
            _("Très rapide avec une carte graphique (moins d'une seconde par paragraphe), 3 à 5 secondes sur un processeur récent."),
            _("Tourne même sur de vieilles machines sans carte graphique : environ 14 à 15 secondes pour deux phrases sur un i7 de 2017 "
              "et sur un i5 de 2012.")],
           [_("Qualité correcte pour des textes simples ou techniques, mais il se trompe sur les nuances, les accords et le style "
              "littéraire (essai réel : « son détresse », « vague de confusion » pour « shiver of incomprehension »).")]),
    "12b": ([_("Nettement plus fidèle aux nuances, aux accords et au style : la phrase littéraire d'essai est traduite correctement.")],
            [_("Lourd : 7,30 Go à télécharger ; mémoire : jusqu'à 13,6 Go sur processeur seul, environ 8 Go avec une carte graphique de 8 Go (mesuré)."),
             _("Beaucoup plus lent : environ 10 secondes pour deux phrases avec une carte de 8 Go, 20 secondes sur le processeur seul. "
               "Rapide seulement avec une grande carte graphique (12 Go ou plus)."),
             _("Déconseillé sur une machine modeste.")]),
    logique.CHOIX_PERSO: ([_("Vous gardez le contrôle : autre quantification, ou fichier déjà présent sur la machine.")],
                          [_("Le modèle doit comprendre la consigne de TranslateGemma ; aucune garantie pour un autre modèle.")]),
}


def _libelle_modele(cle: str) -> str:
    return logique.MODELES[cle]["libelle"] if cle in logique.MODELES else _("Fichier personnel")


class DialogueChoixModele(QDialog):
    """Quel modèle de traduction installer ? Avantages, inconvénients, mesures, conseil pour cette machine."""

    def __init__(self, plugin, parent=None):
        super().__init__(parent)
        self.p = plugin
        self.chemin = ""
        self.setWindowTitle(_("Choisir le modèle de traduction"))
        self.resize(640, 640)
        lay = QVBoxLayout(self)
        intro = QLabel(_("La traduction se fait sur votre machine : rien n'est envoyé sur Internet. Le modèle est un fichier à télécharger "
                         "une fois (avec votre accord). Plus il est gros, meilleure est la traduction, et plus elle est lente."))
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.mat = logique.materiel()
        self.conseil = logique.recommandation(self.mat)
        machine = QLabel(_("Cette machine : %(m)s.\nConseil : %(c)s.") % {"m": logique.description_materiel(self.mat),
                                                                         "c": _libelle_modele(self.conseil)})
        machine.setWordWrap(True)
        lay.addWidget(machine)
        self.radios, self.alertes = {}, {}
        courant = plugin.modele_choisi() or self.conseil
        for cle in (*logique.MODELES, logique.CHOIX_PERSO):
            plus, moins = DESCRIPTIONS[cle]
            present = cle in logique.MODELES and logique.trouver_modele("", plugin.ctx.dossier_donnees, cle)
            etat = (_(" — déjà téléchargé") if present else _(" — à télécharger (%s)") % _taille(logique.MODELES[cle]["taille"])) \
                if cle in logique.MODELES else ""
            radio = QRadioButton(f"{_libelle_modele(cle)}{etat}" + (_("   ← conseillé ici") if cle == self.conseil else ""))
            f = radio.font()
            f.setBold(True)
            radio.setFont(f)
            radio.setChecked(cle == courant)
            self.radios[cle] = radio
            alerte = logique.avertissement_modele(self.mat, cle)
            self.alertes[cle] = alerte
            if alerte:
                radio.setText(radio.text() + "  ⚠")
            detail = QLabel(("<p style='color:#c0392b'><b>⚠ " + alerte + "</b></p>" if alerte else "") + "<ul style='margin:0'>" + "".join(f"<li>✔ {x}</li>" for x in plus) + "".join(f"<li>✘ {x}</li>" for x in moins) + "</ul>")
            detail.setWordWrap(True)
            lay.addWidget(radio)
            lay.addWidget(detail)
        lay.addStretch()
        b = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        b.button(QDialogButtonBox.StandardButton.Ok).setText(_("Choisir"))
        b.button(QDialogButtonBox.StandardButton.Cancel).setText(_("Plus tard"))
        b.accepted.connect(self._valider)
        b.rejected.connect(self.reject)
        lay.addWidget(b)

    def choix(self) -> str:
        return next((cle for cle, r in self.radios.items() if r.isChecked()), self.conseil)

    def _valider(self):
        alerte = self.alertes.get(self.choix(), "")
        if alerte and QMessageBox.question(self, _("Machine juste"), alerte + "\n\n" + _("Choisir quand même ?")) != QMessageBox.StandardButton.Yes:
            return
        if self.choix() == logique.CHOIX_PERSO:
            chemin, _f = QFileDialog.getOpenFileName(self, _("Modèle .gguf"), "", "GGUF (*.gguf)")
            if not chemin:
                return
            self.chemin = chemin
        self.accept()


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
        if len(MOTEURS) > 1:
            f.addRow(_("Moteur par défaut :"), self.moteur)
        # llama.cpp
        f.addRow(QLabel("<b>" + _("TranslateGemma par llama.cpp") + "</b>"))
        self.exe = QLineEdit(r.get("exe", ""))
        self.exe.setPlaceholderText(logique.trouver_llama("", plugin.ctx.dossier_donnees) or _("(llama-server introuvable)"))
        b1 = QPushButton(_("Parcourir…"))
        b1.clicked.connect(lambda: self._choisir(self.exe, _("Programme llama-server")))
        f.addRow(_("Programme llama-server :"), self._ligne(self.exe, b1))
        self.choix = QComboBox()
        for cle in (*logique.MODELES, logique.CHOIX_PERSO):
            self.choix.addItem(_libelle_modele(cle), cle)
        self.choix.setCurrentIndex(max(0, self.choix.findData(plugin.modele_choisi() or "4b")))
        bm = QPushButton(_("Avantages et inconvénients…"))
        bm.clicked.connect(self._assistant)
        f.addRow(_("Modèle :"), self._ligne(self.choix, bm))
        self.modele = QLineEdit(r.get("modele", ""))
        self.modele.setPlaceholderText(_("(chemin d'un fichier .gguf : seulement pour « Fichier personnel »)"))
        b2 = QPushButton(_("Parcourir…"))
        b2.clicked.connect(lambda: self._choisir(self.modele, _("Modèle .gguf"), "GGUF (*.gguf)"))
        f.addRow(_("Fichier personnel :"), self._ligne(self.modele, b2))
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
        for texte, fn in ((_("Aide à l'installation…"), plugin.aide_installation), (_("Télécharger le modèle…"), lambda: plugin.telecharger_modele(self.choix.currentData())),
                          (_("Tester"), self._tester)):
            b = QPushButton(texte)
            b.clicked.connect(fn)
            ligne.addWidget(b)
        f.addRow(ligne)
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

    def _assistant(self):
        if self.p.assistant_modele(force=True):
            r = self.p.ctx.reglages
            self.choix.setCurrentIndex(max(0, self.choix.findData(r.get("modele_choix", "4b"))))
            self.modele.setText(r.get("modele", ""))

    def _tester(self):
        self._enregistrer()
        self.p.tester_llama()

    def _enregistrer(self):
        r = self.p.ctx.reglages
        r.set("moteur", self.moteur.currentData())
        r.set("exe", self.exe.text().strip())
        r.set("modele_choix", self.choix.currentData())
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
        for w in ((self.moteur,) if len(MOTEURS) > 1 else ()) + (self.src, echange, self.dst):
            ligne.addWidget(w, 0 if w is echange else 1)
        lay.addLayout(ligne)
        qualite = QHBoxLayout()
        self.qualite = QComboBox()
        for cle in (*logique.MODELES, logique.CHOIX_PERSO):
            if cle != logique.CHOIX_PERSO or plugin.modele_choisi() == logique.CHOIX_PERSO:
                self.qualite.addItem(_libelle_modele(cle), cle)
        self.qualite.setCurrentIndex(max(0, self.qualite.findData(plugin.modele_choisi() or "4b")))
        self.qualite.setToolTip(_("Rapide : quelques secondes. Meilleur : plus fidèle, plusieurs fois plus lent. (Le choix par défaut se change dans les réglages.)"))
        qualite.addWidget(QLabel(_("Modèle :")))
        qualite.addWidget(self.qualite, 1)
        qualite.addStretch(2)
        lay.addLayout(qualite)
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
        fonction = self.p.preparer(moteur, src, dst, self.vue, self.qualite.currentData())
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
        if ctx.ui is None:
            return
        ctx.ui.ajouter_bouton(_("Traduire"), self.traduire, "preferences-desktop-locale")
        ctx.ui.ajouter_action(_("Traduire la sélection ou la fiche…"), self.traduire, "preferences-desktop-locale")
        ctx.ui.ajouter_action(_("Réglages de la traduction…"), self.reglages, "configure")
        ctx.ui.planifier(60, self._surveiller, repeter=True)
        if self.modele_choisi() is None and not ctx.reglages.get("url", "").strip():
            ctx.ui.planifier(0.5, self.assistant_modele)          # première activation : on demande quel modèle (et on explique)

    def desactiver(self):
        self.serveur.arreter()

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
    def preparer(self, moteur, src, dst, vue, choix=None):
        """Retourne `fonction(morceau, annule) -> str` prête, ou None après avoir expliqué ce qui manque ou demandé un accord.
        (Un ancien réglage inconnu, par exemple « argos », retombe sur llama.cpp.)"""
        return self._preparer_llama(src, dst, vue, choix)

    def _preparer_llama(self, src, dst, vue, choix=None):
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
        choix = choix or self.modele_choisi()
        if choix is None:                                   # jamais choisi : on explique et on demande
            if not self.assistant_modele():
                return None
            choix = self.modele_choisi()
        modele = logique.trouver_modele(r.get("modele", ""), self.ctx.dossier_donnees, choix)
        if not modele:
            modele = self.telecharger_modele(choix)
            if not modele:
                return None
        decision = self._verifier_memoire(choix, modele)         # assez de mémoire LIBRE maintenant ? (pas seulement au total)
        if decision == "annuler":
            return None
        if decision == "rapide":                                  # l'utilisateur préfère le modèle rapide : mêmes vérifications pour lui
            choix = "4b"
            modele = logique.trouver_modele("", self.ctx.dossier_donnees, "4b") or self.telecharger_modele("4b")
            if not modele or self._verifier_memoire("4b", modele) == "annuler":
                return None
        gpu = r.get("gpu", "")

        def fonction(morceau, annule):
            self.serveur.demarrer(exe, modele, gpu, annuler=annule)
            return self.serveur.completer(logique.consigne(morceau, src, dst), logique.n_predict_pour(morceau))
        return fonction

    # ---------- téléchargement (toujours avec accord) ----------
    def _verifier_memoire(self, choix, modele) -> str:
        """Avant de lancer le moteur : y a-t-il assez de mémoire DISPONIBLE ? « ok » (continuer), « rapide » (passer au 4B) ou « annuler ».
        « danger » : moins que la mémoire non récupérable (arrêts forcés possibles, surtout sans swap) ; « juste » : ça tient mais plus
        lentement. Rien à vérifier si le serveur tourne déjà avec ce modèle, ou si la mémoire disponible est inconnue."""
        if self.serveur.vivant() and self.serveur.config and self.serveur.config[1] == modele:
            return "ok"
        disponible = logique.memoire_disponible()
        besoin = logique.besoin_memoire(choix, modele, logique.gpus_nvidia(), logique.avx2_present())
        verdict = logique.diagnostic_memoire(disponible, besoin)
        if verdict == "ok":
            return "ok"
        go = lambda o: f"{o / 1024 ** 3:.1f}".replace(".", ",") + " Go"
        valeurs = {"d": go(disponible), "m": _libelle_modele(choix), "a": go(besoin[0]), "r": go(besoin[1])}
        if verdict == "danger":
            suite = (_("Cette machine n'a pas de mémoire d'échange (swap) : le système pourrait fermer d'autres programmes de force.")
                     if logique.swap_present() is False else _("La machine risque de ralentir très fortement."))
            texte = _("Il n'y a que %(d)s de mémoire disponible ; « %(m)s » en demande au moins %(a)s (jusqu'à %(r)s pour aller vite).") % valeurs + "\n\n" + suite
        else:
            texte = _("%(d)s de mémoire disponible : « %(m)s » tiendra mais ira plus lentement (il en faut %(r)s pour aller vite). "
                      "Fermer quelques programmes aidera.") % valeurs
        m = QMessageBox(_parent())
        m.setIcon(QMessageBox.Icon.Warning)
        m.setWindowTitle(_("Mémoire insuffisante") if verdict == "danger" else _("Mémoire un peu juste"))
        m.setText(texte)
        rapide = m.addButton(_("Utiliser le modèle rapide (4B)"), QMessageBox.ButtonRole.ActionRole) if choix != "4b" else None
        continuer = m.addButton(_("Continuer quand même"), QMessageBox.ButtonRole.AcceptRole)
        annuler = m.addButton(_("Annuler"), QMessageBox.ButtonRole.RejectRole)
        m.setDefaultButton((rapide or annuler) if verdict == "danger" else continuer)
        m.exec()
        clic = m.clickedButton()
        return "rapide" if rapide is not None and clic is rapide else ("ok" if clic is continuer else "annuler")

    def modele_choisi(self):
        """« 4b », « 12b », « perso » ou None si l'utilisateur n'a pas encore choisi. Reprend une ancienne configuration (chemin seul)."""
        r = self.ctx.reglages
        c = r.get("modele_choix")
        if c in logique.MODELES or c == logique.CHOIX_PERSO:
            return c
        ancien = r.get("modele", "")
        if ancien and Path(ancien).is_file():
            r.set("modele_choix", logique.CHOIX_PERSO)
            return logique.CHOIX_PERSO
        return None

    def assistant_modele(self, force: bool = False) -> bool:
        """Choix du modèle. Sur une machine qui fait tourner le 12B sans hésitation (carte NVIDIA de 12 Go ou plus, Mac Apple Silicon
        avec 16 Go), le choix est évident : pas de question (sauf `force`). Dans tous les autres cas, avantages et inconvénients.
        Le téléchargement demande toujours l'accord de l'utilisateur. True si un modèle est choisi et disponible."""
        r = self.ctx.reglages
        auto = logique.choix_automatique(logique.materiel())
        if auto and not force:
            r.set("modele_choix", auto)
            self.ctx.ui.notifier(_("Traduction"), _("Modèle « %s » choisi pour cette machine (modifiable dans les réglages).") % _libelle_modele(auto))
            return bool(self._assurer_modele(auto))
        d = DialogueChoixModele(self, _parent())
        if not d.exec():
            return False
        choix = d.choix()
        r.set("modele_choix", choix)
        r.set("modele", d.chemin if choix == logique.CHOIX_PERSO else "")
        return bool(self._assurer_modele(choix))

    def _assurer_modele(self, choix):
        fichier = logique.trouver_modele(self.ctx.reglages.get("modele", ""), self.ctx.dossier_donnees, choix)
        return fichier or (self.telecharger_modele(choix) if choix in logique.MODELES else None)

    def telecharger_modele(self, choix=None):
        """Propose de télécharger le modèle choisi (taille, source et destination affichées) ; retourne son chemin, ou None."""
        choix = choix or self.modele_choisi() or "4b"
        if choix not in logique.MODELES:
            QMessageBox.information(_parent(), _("Modèle de traduction"), _("Choisissez un fichier .gguf dans les réglages."))
            return None
        m = logique.MODELES[choix]
        dossier = self.ctx.dossier_donnees / "modeles"
        if QMessageBox.question(
                _parent(), _("Modèle de traduction"),
                _("Il manque le modèle « %(n)s » (TranslateGemma, quantifié Q4_K_M, licence Gemma).\n\nTaille : %(t)s\nSource : %(u)s\n"
                  "Destination : %(d)s\n\nLa somme de contrôle SHA-256 est vérifiée. Télécharger maintenant ?")
                % {"n": m["libelle"], "t": _taille(m["taille"]), "u": m["url"], "d": dossier}) != QMessageBox.StandardButton.Yes:
            return None
        chemin, err = en_arriere_plan(_("Modèle de traduction : %s") % m["libelle"], _("Téléchargement de %(n)s (%(t)s)…") % {"n": m["nom"], "t": _taille(m["taille"])},
                                      lambda annuler, prog: logique.telecharger_modele(dossier, m["url"], m["nom"], m["sha256"], m["taille"],
                                                                                        progression=prog, annuler=annuler.is_set,
                                                                                        etat=getattr(prog, "etat", None)),
                                      annulable=True)
        if err:
            if err != "annulé":
                QMessageBox.warning(_parent(), _("Modèle de traduction"), err)
            return None
        self.ctx.ui.notifier(_("Traduction"), _("Modèle « %s » téléchargé et vérifié.") % m["libelle"])
        return str(chemin)

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

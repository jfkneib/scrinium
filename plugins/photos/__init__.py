# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « Photos » : une fiche d'un nouveau type, `photos` (`#scrinium-photos`), qui garde le chemin d'un dossier d'images
et le montre en vignettes (voir `logique.py`).

- Lecture seule : un double-clic ouvre l'image dans votre visionneuse ; le clic droit ouvre le dossier, en choisit un autre, actualise.
- Les images restent dans leur dossier, rien n'est copié dans la fiche. Le chemin n'a de sens que sur la machine qui a ce dossier.
- Les vignettes se chargent par petits lots (la fenêtre reste utilisable avec un gros dossier) ; elles sont gardées en mémoire tant que
  Scrinium tourne.
- Type non exécutable : la fiche ne lance rien. « Nouvelle fiche » (flèche du bouton « Fiche ») → « Photos »."""
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QIcon, QImageReader, QPixmap
from PyQt6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QListView, QListWidget, QListWidgetItem, QPushButton,
                             QVBoxLayout, QWidget)

from scrinium.core.plugins import Plugin
from scrinium.i18n import _
from scrinium.ui.icons import icone

from . import logique

TAILLE = 128                 # côté des vignettes
LOT = 12                     # vignettes chargées à chaque passage de la boucle d'événements


def vignette(chemin: Path) -> QIcon:
    """Vignette décodée à taille réduite (rapide même pour une grande photo) ; icône vide si le fichier n'est pas une image lisible."""
    lecteur = QImageReader(str(chemin))
    lecteur.setAutoTransform(True)
    taille = lecteur.size()
    if taille.isValid():
        lecteur.setScaledSize(taille.scaled(TAILLE * 2, TAILLE * 2, Qt.AspectRatioMode.KeepAspectRatio))
    img = lecteur.read()
    return QIcon(QPixmap.fromImage(img)) if not img.isNull() else QIcon()


class VuePhotos(QWidget):
    """Vue du type « photos » : la fiche s'affiche comme une grille de vignettes (le texte reste dans la fiche, seule la ligne « dossier: » change)."""
    modifie = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.texte = ""
        self.actif = True                       # type non exécutable : toujours utilisable
        self._cache: dict = {}                  # (chemin, date de modification) -> QIcon
        self._file: list = []                   # (élément, chemin) dont la vignette reste à charger
        self._generation = 0                    # change à chaque rechargement : un lot en cours s'arrête
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        haut = QHBoxLayout()
        self.etiquette = QLabel()
        self.etiquette.setWordWrap(True)
        haut.addWidget(self.etiquette, 1)
        self.b_choisir = QPushButton(icone("folder-open"), _("Choisir un dossier…"))
        self.b_choisir.clicked.connect(lambda *_a: self.choisir())
        haut.addWidget(self.b_choisir)
        lay.addLayout(haut)
        self.liste = QListWidget()
        self.liste.setViewMode(QListView.ViewMode.IconMode)
        self.liste.setResizeMode(QListView.ResizeMode.Adjust)
        self.liste.setMovement(QListView.Movement.Static)
        self.liste.setWrapping(True)
        self.liste.setIconSize(QSize(TAILLE, TAILLE))
        self.liste.setGridSize(QSize(TAILLE + 24, TAILLE + 36))
        self.liste.setUniformItemSizes(True)
        self.liste.itemActivated.connect(self._ouvrir)
        self.liste.itemDoubleClicked.connect(self._ouvrir)
        lay.addWidget(self.liste, 1)

    # ---------- contenu ----------
    def charger(self, texte: str):
        self.texte = texte or ""
        self.recharger()

    def chemin(self) -> str:
        return logique.depuis_texte(self.texte)

    def recharger(self):
        self._generation += 1
        self._file = []
        self.liste.clear()
        chemin = self.chemin()
        d = logique.dossier(chemin)
        if not chemin.strip():
            self.etiquette.setText(_("Aucun dossier : « Choisir un dossier… » (ou clic droit)."))
            return
        if d is None:
            self.etiquette.setText(_("Dossier introuvable sur cette machine : %s") % chemin)
            return
        trouvees, total = logique.images(d)
        texte = _("%(dossier)s — %(n)d image(s)") % {"dossier": chemin, "n": total}
        if total > len(trouvees):
            texte += " " + _("(les %d premières sont montrées)") % len(trouvees)
        self.etiquette.setText(texte)
        vide = icone("image-x-generic")
        for p in trouvees:
            it = QListWidgetItem(self._en_cache(p) or vide, p.name)
            it.setToolTip(p.name)
            it.setData(Qt.ItemDataRole.UserRole, str(p))
            it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            self.liste.addItem(it)
            if self._en_cache(p) is None:
                self._file.append((it, p))
        self._planifier()

    def _cle(self, p: Path):
        try:
            return (str(p), p.stat().st_mtime_ns)
        except OSError:
            return (str(p), 0)

    def _en_cache(self, p: Path):
        return self._cache.get(self._cle(p))

    def _planifier(self):
        if self._file:
            g = self._generation
            QTimer.singleShot(0, lambda: self._lot(g))

    def _lot(self, generation: int):
        """Charge quelques vignettes puis rend la main ; s'arrête si la vue a été rechargée entre-temps."""
        if generation != self._generation:
            return
        for _i in range(min(LOT, len(self._file))):
            it, p = self._file.pop(0)
            ic = vignette(p)
            if not ic.isNull():
                self._cache[self._cle(p)] = ic
                it.setIcon(ic)
        self._planifier()

    # ---------- actions ----------
    def _ouvrir(self, it):
        chemin = it.data(Qt.ItemDataRole.UserRole)
        if chemin:
            QDesktopServices.openUrl(QUrl.fromLocalFile(chemin))

    def ouvrir_dossier(self):
        d = logique.dossier(self.chemin())
        if d is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    def choisir(self):
        depart = logique.dossier(self.chemin()) or Path.home()
        choisi = QFileDialog.getExistingDirectory(self, _("Dossier d'images"), str(depart))
        if choisi:
            self.texte = logique.en_texte(choisi, self.texte)
            self.modifie.emit(self.texte)
            self.recharger()

    def entrees_menu(self, pos) -> list:
        """Entrées du clic droit (la fenêtre y ajoute celles des extensions)."""
        it = self.liste.itemAt(self.liste.viewport().mapFrom(self, pos))
        e = []
        if it is not None:
            e.append((_("Ouvrir l'image"), lambda *_a, it=it: self._ouvrir(it), "document-open"))
        e += [(_("Ouvrir le dossier"), lambda *_a: self.ouvrir_dossier(), "folder-open"),
              (_("Choisir un autre dossier…"), lambda *_a: self.choisir(), "folder-pictures"),
              (_("Actualiser"), lambda *_a: self.recharger(), "view-refresh")]
        return e


class PhotosPlugin(Plugin):
    api = 1

    def activer(self, ctx):
        self.ctx = ctx
        if ctx.ui is None:
            return
        ctx.ui.enregistrer_type(logique.TYPE, VuePhotos())

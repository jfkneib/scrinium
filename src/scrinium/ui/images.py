# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Pièces jointes (images) : import avec réencodage, éditeur qui capte le collage, bande de vignettes, visionneuse.

Voir docs/format-pieces-jointes.md. Le stockage et le chiffrement sont dans `core/store.py` ; ici, seulement l'interface Qt.
"""
import time
from pathlib import Path

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QImage, QImageReader, QPainter, QPixmap
from PyQt6.QtWidgets import (QApplication, QDialog, QFileDialog, QHBoxLayout, QLabel, QListView, QListWidget,
                             QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSizePolicy, QVBoxLayout,
                             QWidget)

from ..core.plugins import FicheVue, PieceVue
from ..core.store import LIMITES_PIECES
from ..i18n import _
from .icons import icone

COTE_MAX = 2560                                  # plus grand côté après import (px)
OCTETS_MAX = LIMITES_PIECES["octets_piece"]
SOURCE_MAX = 50 * 1024 * 1024                    # fichier source refusé au-delà
PIXELS_MAX = 120_000_000                         # garde-fou contre les images « bombes »
SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
FILTRE = "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif)"
VIGNETTE = 96


class ImageInvalide(ValueError):
    pass


# ---------- import : lecture, réduction, réencodage ----------
def _lire(source) -> tuple[QImage, str]:
    """(image, format d'origine en minuscules). L'orientation EXIF est appliquée ici, puis les métadonnées disparaissent
    au réencodage."""
    if isinstance(source, QImage):
        return source, ""
    donnees = Path(source).read_bytes() if isinstance(source, (str, Path)) else bytes(source)
    if len(donnees) > SOURCE_MAX:
        raise ImageInvalide(_("Fichier trop volumineux (plus de 50 Mo)."))
    ba = QByteArray(donnees)
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.ReadOnly)
    r = QImageReader(buf)
    r.setAutoTransform(True)
    taille = r.size()
    if taille.isValid() and taille.width() * taille.height() > PIXELS_MAX:
        raise ImageInvalide(_("Image démesurée (plus de 120 millions de pixels)."))
    fmt = bytes(r.format()).decode("ascii", "ignore").lower()
    img = r.read()
    if img.isNull():
        raise ImageInvalide(_("Image illisible ou format non pris en charge."))
    return img, fmt


def _encoder(img: QImage, format_: str, qualite: int = -1) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    if not img.save(buf, format_, qualite):
        raise ImageInvalide(_("Encodage de l'image impossible."))
    return bytes(ba.data())


def _pixels_seuls(img: QImage) -> QImage:
    """Copie qui ne garde que les pixels : Qt relit puis réécrit les métadonnées texte d'une image (commentaires PNG…),
    ce qui ferait suivre position GPS, appareil ou logiciel jusque dans la pièce jointe."""
    img = img.convertToFormat(QImage.Format.Format_ARGB32 if img.hasAlphaChannel() else QImage.Format.Format_RGB32)
    ptr = img.constBits()
    ptr.setsize(img.sizeInBytes())
    return QImage(ptr, img.width(), img.height(), img.bytesPerLine(), img.format()).copy()


def _aplatir(img: QImage) -> QImage:
    """Fond blanc sous la transparence (le JPEG n'en a pas)."""
    plat = QImage(img.size(), QImage.Format.Format_RGB32)
    plat.fill(QColor("white"))
    p = QPainter(plat)
    p.drawImage(0, 0, img)
    p.end()
    return plat


def preparer(source) -> tuple[str, bytes]:
    """(type MIME, octets) prêts à être joints : réduit à COTE_MAX px, sans métadonnées, ≤ OCTETS_MAX.
    PNG par défaut (net pour les captures et l'OCR) ; JPEG si l'origine l'était, ou si le PNG est trop lourd.
    Lève ImageInvalide."""
    img, fmt = _lire(source)
    img = _pixels_seuls(img)
    if max(img.width(), img.height()) > COTE_MAX:
        img = img.scaled(COTE_MAX, COTE_MAX, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    if not (fmt in ("jpeg", "jpg") and not img.hasAlphaChannel()):
        donnees = _encoder(img, "PNG")
        if len(donnees) <= OCTETS_MAX:
            return "image/png", donnees
    plat = _aplatir(img) if img.hasAlphaChannel() else img.convertToFormat(QImage.Format.Format_RGB32)
    for q in (88, 80, 70, 55):
        donnees = _encoder(plat, "JPEG", q)
        if len(donnees) <= OCTETS_MAX:
            return "image/jpeg", donnees
    raise ImageInvalide(_("Image trop lourde, même compressée."))


def miniature(donnees: bytes) -> QPixmap:
    img = QImage.fromData(donnees)
    if img.isNull():
        return QPixmap()
    return QPixmap.fromImage(img.scaled(VIGNETTE, VIGNETTE, Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation))


# ---------- éditeur : le collage et le glisser-déposer d'images deviennent des pièces jointes ----------
class Editeur(QPlainTextEdit):
    images_recues = pyqtSignal(list)      # liste de QImage et/ou de chemins

    @staticmethod
    def _sources(src) -> list:
        fichiers = [Path(u.toLocalFile()) for u in src.urls() if u.isLocalFile()]
        images = [p for p in fichiers if p.suffix.lower() in SUFFIXES]
        if images:
            return images
        if src.hasImage() and not src.hasText():
            img = src.imageData()
            if isinstance(img, QImage) and not img.isNull():
                return [img]
        return []

    def canInsertFromMimeData(self, src):
        return bool(self._sources(src)) or super().canInsertFromMimeData(src)

    def insertFromMimeData(self, src):
        sources = self._sources(src)
        if sources:
            self.images_recues.emit(sources)
        else:
            super().insertFromMimeData(src)


# ---------- visionneuse ----------
class Visionneuse(QDialog):
    def __init__(self, fenetre, fiche, pieces, index, parent=None):
        super().__init__(parent)
        self.fen, self.fiche, self.pieces, self.i = fenetre, fiche, pieces, index
        self.resize(900, 650)
        lay = QVBoxLayout(self)
        self.image = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumSize(200, 150)
        self.image.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        lay.addWidget(self.image, 1)
        bas = QHBoxLayout()
        self.prec, self.suiv = QPushButton("◀"), QPushButton("▶")
        self.titre = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        fermer = QPushButton(_("Fermer"))
        self.prec.clicked.connect(lambda: self._aller(self.i - 1))
        self.suiv.clicked.connect(lambda: self._aller(self.i + 1))
        fermer.clicked.connect(self.accept)
        for w in (self.prec, self.titre, self.suiv, fermer):
            bas.addWidget(w, 1 if w is self.titre else 0)
        lay.addLayout(bas)
        self._aller(index)

    def _aller(self, i):
        if not 0 <= i < len(self.pieces):
            return
        self.i = i
        p = self.pieces[i]
        try:
            self.donnees = self.fen.store.lire_piece(self.fiche, p)
        except Exception as ex:
            self.donnees = b""
            self.titre.setText(f"⚠ {ex}")
        self.pix = QPixmap.fromImage(QImage.fromData(self.donnees))
        self.setWindowTitle(p.nom)
        self.titre.setText(f"{p.nom}   ({i + 1}/{len(self.pieces)})")
        self.prec.setEnabled(i > 0)
        self.suiv.setEnabled(i < len(self.pieces) - 1)
        self._ajuster()

    def _ajuster(self):
        if not self.pix.isNull():
            self.image.setPixmap(self.pix.scaled(self.image.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._ajuster()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Left:
            self._aller(self.i - 1)
        elif ev.key() == Qt.Key.Key_Right:
            self._aller(self.i + 1)
        else:
            super().keyPressEvent(ev)


# ---------- bande de vignettes sous l'éditeur ----------
class BandePieces(QWidget):
    def __init__(self, fenetre):
        super().__init__(fenetre)
        self.fen = fenetre
        self.pieces: list = []
        self.setAcceptDrops(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        haut = QHBoxLayout()
        self.titre = QLabel("")
        self.ajout = QPushButton(icone("list-add"), _("Ajouter une image…"))
        self.ajout.clicked.connect(self.choisir)
        haut.addWidget(self.titre, 1)
        haut.addWidget(self.ajout)
        lay.addLayout(haut)
        self.liste = QListWidget()
        self.liste.setViewMode(QListView.ViewMode.IconMode)
        self.liste.setFlow(QListView.Flow.LeftToRight)
        self.liste.setWrapping(False)
        self.liste.setMovement(QListView.Movement.Static)
        self.liste.setIconSize(QSize(VIGNETTE, VIGNETTE))
        self.liste.setGridSize(QSize(VIGNETTE + 24, VIGNETTE + 32))
        self.liste.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.liste.setWordWrap(False)
        self.liste.setFixedHeight(VIGNETTE + 36)
        self.liste.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.liste.customContextMenuRequested.connect(self._menu)
        self.liste.itemDoubleClicked.connect(lambda it: self.ouvrir(self.liste.row(it)))
        lay.addWidget(self.liste)
        self.hide()

    # ----- affichage -----
    def charger(self, theme, fiche):
        """Met la bande à jour pour cette fiche (rien tant qu'une fiche verrouillée est fermée)."""
        self.liste.clear()
        self.pieces = []
        if fiche is None or fiche.fermee:
            self.hide()
            return
        self.pieces = self.fen.store.lister_pieces(fiche)
        for p in self.pieces:
            try:
                pm = miniature(self.fen.store.lire_piece(fiche, p))
            except Exception:
                pm = QPixmap()
            self.liste.addItem(QListWidgetItem(QIcon(pm), p.nom))
        self.liste.setVisible(bool(self.pieces))
        self.titre.setText(_("Images (%d)") % len(self.pieces) if self.pieces else _("Images"))
        self.show()

    # ----- ajout -----
    def choisir(self):
        chemins, _f = QFileDialog.getOpenFileNames(self, _("Ajouter une image"), "", FILTRE)
        if chemins:
            self.ajouter([Path(c) for c in chemins])

    def ajouter(self, sources: list) -> int:
        """Joint des images (QImage ou chemins) à la fiche affichée. Retourne le nombre ajouté."""
        f, t = self.fen.fiche, self.fen.fiche_theme
        if f is None or f.fermee:
            return 0
        self.fen.sauver()          # le titre peut changer le nom de la fiche : on l'enregistre d'abord
        ajoutees = 0
        for s in sources:
            nom = s.name if isinstance(s, Path) else _("Image collée") + time.strftime(" %Y-%m-%d %H:%M:%S")
            try:
                type_, donnees = preparer(s)
                piece = self.fen.store.ajouter_piece(f, nom, type_, donnees)
                ajoutees += 1
                self.fen.plugins.emettre("piece_jointe_ajoutee", fiche=FicheVue(t, f), piece=PieceVue(piece))
            except (ImageInvalide, ValueError, OSError) as ex:
                QMessageBox.warning(self.fen, _("Image"), f"{nom} : {ex}")
        if ajoutees:
            self.charger(t, f)
            self.fen.pieces_modifiees()
        return ajoutees

    def dragEnterEvent(self, ev):
        if Editeur._sources(ev.mimeData()):
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        s = Editeur._sources(ev.mimeData())
        if s:
            ev.acceptProposedAction()
            self.ajouter(s)

    # ----- actions sur une pièce -----
    def ouvrir(self, i):
        if 0 <= i < len(self.pieces):
            Visionneuse(self.fen, self.fen.fiche, self.pieces, i, self.fen).exec()

    def _menu(self, pos):
        it = self.liste.itemAt(pos)
        if it is None:
            return
        i = self.liste.row(it)
        m = QMenu(self)
        m.addAction(icone("view-pim-notes"), _("Ouvrir"), lambda: self.ouvrir(i))
        m.addAction(icone("document-save"), _("Enregistrer sous…"), lambda: self.enregistrer_sous(i))
        m.addAction(icone("edit-copy"), _("Copier l'image"), lambda: self.copier(i))
        m.addSeparator()
        m.addAction(icone("edit-delete"), _("Supprimer"), lambda: self.supprimer(i))
        m.exec(self.liste.mapToGlobal(pos))

    def copier(self, i):
        QApplication.clipboard().setImage(QImage.fromData(self.fen.store.lire_piece(self.fen.fiche, self.pieces[i])))

    def enregistrer_sous(self, i):
        f, p = self.fen.fiche, self.pieces[i]
        if f.verrou and QMessageBox.question(
                self.fen, _("Enregistrer sous"),
                _("La fiche est verrouillée : la copie sera enregistrée EN CLAIR. Continuer ?")) != QMessageBox.StandardButton.Yes:
            return
        suffixe = ".jpg" if p.type == "image/jpeg" else ".png"
        nom = p.nom if Path(p.nom).suffix.lower() == suffixe else Path(p.nom).stem + suffixe
        chemin, _f = QFileDialog.getSaveFileName(self.fen, _("Enregistrer l'image"), nom)
        if chemin:
            try:
                Path(chemin).write_bytes(self.fen.store.lire_piece(f, p))
            except OSError as ex:
                QMessageBox.warning(self.fen, _("Image"), str(ex))

    def supprimer(self, i):
        f, t = self.fen.fiche, self.fen.fiche_theme
        piece = self.pieces[i]
        self.fen.store.supprimer_piece(f, piece)
        self.fen.plugins.emettre("piece_jointe_supprimee", fiche=FicheVue(t, f), piece=PieceVue(piece))
        self.charger(t, f)
        self.fen.pieces_modifiees()

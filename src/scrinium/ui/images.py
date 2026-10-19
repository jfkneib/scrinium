# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Pièces jointes (images) : import avec réencodage, éditeur qui capte le collage, bande de vignettes, visionneuse.

Voir docs/format-pieces-jointes.md. Le stockage et le chiffrement sont dans `core/store.py` ; ici, seulement l'interface Qt.
"""
import time
from pathlib import Path

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QRect, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QImage, QImageReader, QPainter, QPixmap
from PyQt6.QtWidgets import (QApplication, QDialog, QFileDialog, QHBoxLayout, QLabel, QListView, QListWidget,
                             QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QRubberBand, QSizePolicy,
                             QVBoxLayout, QWidget)

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


def preparer(source, jpeg: bool = False) -> tuple[str, bytes]:
    """(type MIME, octets) prêts à être joints : réduit à COTE_MAX px, sans métadonnées, ≤ OCTETS_MAX.
    PNG par défaut (net pour les captures et l'OCR) ; JPEG si l'origine l'était (ou si `jpeg`), ou si le PNG est trop lourd.
    Lève ImageInvalide."""
    img, fmt = _lire(source)
    img = _pixels_seuls(img)
    if max(img.width(), img.height()) > COTE_MAX:
        img = img.scaled(COTE_MAX, COTE_MAX, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    if not ((jpeg or fmt in ("jpeg", "jpg")) and not img.hasAlphaChannel()):
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


# ---------- visionneuse (avec recadrage) ----------
def convertir_selection(rect: QRect, etiquette: QSize, affichee: QSize, origine: QSize) -> QRect | None:
    """Rectangle tracé dans l'étiquette (image centrée, mise à l'échelle) -> rectangle en pixels de l'image d'origine.
    None si la sélection est (presque) hors de l'image ou trop petite."""
    decx, decy = (etiquette.width() - affichee.width()) // 2, (etiquette.height() - affichee.height()) // 2
    r = rect.translated(-decx, -decy).intersected(QRect(0, 0, affichee.width(), affichee.height()))
    if r.width() < 8 or r.height() < 8 or affichee.width() <= 0 or affichee.height() <= 0:
        return None
    kx, ky = origine.width() / affichee.width(), origine.height() / affichee.height()
    x, y = round(r.x() * kx), round(r.y() * ky)
    w, h = min(round(r.width() * kx), origine.width() - x), min(round(r.height() * ky), origine.height() - y)
    return QRect(x, y, w, h) if w >= 2 and h >= 2 else None


class _Cadre(QLabel):
    """Image affichée ; en mode recadrage, un rectangle se trace à la souris."""
    selection = pyqtSignal(QRect)      # rectangle en coordonnées de l'étiquette
    redimensionnee = pyqtSignal()

    def __init__(self):
        super().__init__(alignment=Qt.AlignmentFlag.AlignCenter)
        self.actif = False
        self.depart = None
        self.bande = QRubberBand(QRubberBand.Shape.Rectangle, self)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.redimensionnee.emit()

    def activer(self, on: bool):
        self.actif = on
        self.bande.hide()
        self.setCursor(Qt.CursorShape.CrossCursor if on else Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, ev):
        if not self.actif:
            return super().mousePressEvent(ev)
        self.depart = ev.position().toPoint()
        self.bande.setGeometry(QRect(self.depart, QSize()))
        self.bande.show()

    def mouseMoveEvent(self, ev):
        if self.actif and self.depart is not None:
            self.bande.setGeometry(QRect(self.depart, ev.position().toPoint()).normalized())

    def mouseReleaseEvent(self, ev):
        if self.actif and self.depart is not None:
            self.depart = None
            self.selection.emit(self.bande.geometry())


class Visionneuse(QDialog):
    def __init__(self, fenetre, fiche, pieces, index, parent=None):
        super().__init__(parent)
        self.fen, self.fiche, self.pieces, self.i = fenetre, fiche, pieces, index
        self.zone = None
        self.resize(900, 650)
        lay = QVBoxLayout(self)
        self.image = _Cadre()
        self.image.setMinimumSize(200, 150)
        self.image.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.image.selection.connect(self._selection)
        self.image.redimensionnee.connect(self._redim)
        lay.addWidget(self.image, 1)
        # barre du recadrage (cachée tant que le mode n'est pas activé)
        self.barre = QWidget()
        rb = QHBoxLayout(self.barre)
        rb.setContentsMargins(0, 0, 0, 0)
        self.aide = QLabel(_("Tracez un rectangle sur l'image."))
        self.b_nouvelle = QPushButton(_("Garder comme nouvelle image"))
        self.b_remplacer = QPushButton(_("Remplacer l'originale"))
        self.b_remplacer.setToolTip(_("L'ancienne version est conservée dans la corbeille."))
        for b in (self.b_nouvelle, self.b_remplacer):
            b.setEnabled(False)
        self.b_nouvelle.clicked.connect(lambda: self._appliquer(False))
        self.b_remplacer.clicked.connect(lambda: self._appliquer(True))
        rb.addWidget(self.aide, 1)
        rb.addWidget(self.b_nouvelle)
        rb.addWidget(self.b_remplacer)
        self.barre.hide()
        lay.addWidget(self.barre)
        bas = QHBoxLayout()
        self.prec, self.suiv = QPushButton("◀"), QPushButton("▶")
        self.titre = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.b_recadrer = QPushButton(icone("edit-cut"), _("Recadrer"))
        self.b_recadrer.setCheckable(True)
        self.b_recadrer.toggled.connect(self._mode_recadrage)
        fermer = QPushButton(_("Fermer"))
        self.prec.clicked.connect(lambda: self._aller(self.i - 1))
        self.suiv.clicked.connect(lambda: self._aller(self.i + 1))
        fermer.clicked.connect(self.accept)
        for w in (self.prec, self.titre, self.suiv, self.b_recadrer, fermer):
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
        self.b_recadrer.setChecked(False)
        self._ajuster()

    def _ajuster(self):
        if not self.pix.isNull():
            self.image.setPixmap(self.pix.scaled(self.image.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation))

    def _redim(self):
        """L'image suit la taille de sa zone (fenêtre redimensionnée, barre de recadrage affichée ou cachée)."""
        self._ajuster()
        if self.image.actif:
            self._effacer_selection()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Left:
            self._aller(self.i - 1)
        elif ev.key() == Qt.Key.Key_Right:
            self._aller(self.i + 1)
        else:
            super().keyPressEvent(ev)

    # ----- recadrage -----
    def _mode_recadrage(self, on: bool):
        self.image.activer(on)
        self.barre.setVisible(on)
        self._effacer_selection()

    def _effacer_selection(self):
        self.zone = None
        self.image.bande.hide()
        self.aide.setText(_("Tracez un rectangle sur l'image."))
        self.b_nouvelle.setEnabled(False)
        self.b_remplacer.setEnabled(False)

    def _selection(self, rect):
        pm = self.image.pixmap()
        self.zone = convertir_selection(rect, self.image.size(), pm.size(), self.pix.size()) if pm else None
        ok = self.zone is not None
        self.aide.setText(_("Zone : %(l)d × %(h)d px") % {"l": self.zone.width(), "h": self.zone.height()} if ok
                          else _("Sélection trop petite ou hors de l'image."))
        self.b_nouvelle.setEnabled(ok)
        self.b_remplacer.setEnabled(ok)

    def _appliquer(self, remplacer: bool):
        if self.zone is None:
            return
        f, t, piece = self.fiche, self.fen.fiche_theme, self.pieces[self.i]
        if remplacer and QMessageBox.question(
                self, _("Remplacer l'originale"),
                _("Remplacer l'image par la zone recadrée ? L'ancienne version est conservée dans la corbeille. "
                  "Le texte extrait (OCR) de cette image sera effacé.")) != QMessageBox.StandardButton.Yes:
            return
        try:
            type_, donnees = preparer(QImage.fromData(self.donnees).copy(self.zone), jpeg=piece.type == "image/jpeg")
            if remplacer:
                nouvelle = self.fen.store.remplacer_piece(f, piece, type_, donnees)
                self.fen.plugins.emettre("piece_jointe_modifiee", fiche=FicheVue(t, f), piece=PieceVue(nouvelle), origine=None)
            else:
                p = Path(piece.nom)
                nouvelle = self.fen.store.ajouter_piece(f, f"{p.stem} ({_('recadrée')}){p.suffix}", type_, donnees)
                self.fen.plugins.emettre("piece_jointe_ajoutee", fiche=FicheVue(t, f), piece=PieceVue(nouvelle))
        except (ImageInvalide, ValueError, OSError) as ex:
            QMessageBox.warning(self, _("Recadrage"), str(ex))
            return
        self.pieces = self.fen.store.lister_pieces(f)
        self.fen.bande.charger(t, f)
        self.fen.pieces_modifiees()
        self._aller(next((k for k, q in enumerate(self.pieces) if q.id == nouvelle.id), self.i))


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

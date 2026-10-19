# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Import d'images et interface des pièces jointes (Qt hors écran)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QMimeData, QUrl  # noqa: E402
from PyQt6.QtGui import QColor, QImage  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from scrinium.core.paths import Paths  # noqa: E402
from scrinium.core.store import Store  # noqa: E402
from scrinium.ui import images  # noqa: E402
from scrinium.ui.fenetre import Fenetre  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def fen(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    s = Store(Paths(tmp_path / "am"))
    s.sauver_reglages(recovery_asked=True)
    w = Fenetre(s)
    w.nouvelle_fiche()
    w.titre.setText("Ma fiche")
    w.sauver()
    yield w
    w.quitter_vraiment = True
    w.close()


def image(l=200, h=100, couleur="red", alpha=False):
    img = QImage(l, h, QImage.Format.Format_ARGB32 if alpha else QImage.Format.Format_RGB32)
    img.fill(QColor(couleur) if not alpha else QColor(255, 0, 0, 0))
    return img


def encoder(img, fmt):
    ba = QByteArray()
    b = QBuffer(ba)
    b.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(b, fmt)
    return bytes(ba.data())


# ---------- import ----------
def test_png_reste_png_et_est_reduit(app):
    type_, data = images.preparer(image(5000, 2500))
    sortie = QImage.fromData(data)
    assert type_ == "image/png" and data.startswith(b"\x89PNG") and (sortie.width(), sortie.height()) == (2560, 1280)


def test_jpeg_reste_jpeg(app):
    type_, data = images.preparer(encoder(image(300, 200), "JPEG"))
    assert type_ == "image/jpeg" and data.startswith(b"\xff\xd8")


def test_metadonnees_supprimees(app):
    img = image(50, 50)
    img.setText("Comment", "position GPS 48.85,2.35")
    brut = encoder(img, "PNG")
    assert b"GPS" in brut                                           # la source contient bien une métadonnée…
    _t, data = images.preparer(brut)
    assert b"GPS" not in data and b"Comment" not in data            # …le réencodage la supprime


def test_png_trop_lourd_devient_jpeg(app, monkeypatch):
    monkeypatch.setattr(images, "OCTETS_MAX", 1000)                 # force le repli
    import random
    random.seed(1)
    img = QImage(300, 300, QImage.Format.Format_RGB32)
    for x in range(300):
        for y in range(300):
            img.setPixel(x, y, random.getrandbits(24))
    with pytest.raises(images.ImageInvalide):                       # même en JPEG, du bruit dépasse 1000 octets
        images.preparer(img)
    monkeypatch.setattr(images, "OCTETS_MAX", 60000)
    type_, data = images.preparer(img)
    assert type_ == "image/jpeg" and len(data) <= 60000


def test_transparence_aplatie_en_jpeg(app, monkeypatch):
    img = QImage(400, 400, QImage.Format.Format_ARGB32)
    for x in range(400):
        for y in range(400):
            img.setPixelColor(x, y, QColor((x * 7) % 256, (y * 5) % 256, (x + y) % 256, (x * y) % 256))
    assert len(encoder(img, "PNG")) > 55000
    monkeypatch.setattr(images, "OCTETS_MAX", 55000)                # le PNG est trop lourd : repli en JPEG (sans transparence)
    type_, data = images.preparer(img)
    assert type_ == "image/jpeg" and len(data) <= 55000 and not QImage.fromData(data).hasAlphaChannel()


def test_refus_fichier_invalide_et_trop_gros(app, tmp_path, monkeypatch):
    with pytest.raises(images.ImageInvalide):
        images.preparer(b"ceci n'est pas une image")
    monkeypatch.setattr(images, "SOURCE_MAX", 10)
    with pytest.raises(images.ImageInvalide, match="volumineux"):
        images.preparer(b"0" * 11)


# ---------- interface ----------
def test_coller_une_image_la_joint_a_la_fiche(fen):
    mime = QMimeData()
    mime.setImageData(image())
    fen.texte.insertFromMimeData(mime)
    assert fen.texte.toPlainText() == ""                            # rien n'est inséré dans le texte
    assert len(fen.store.lister_pieces(fen.fiche)) == 1 and fen.bande.liste.count() == 1 and not fen.bande.isHidden()


def test_texte_colle_reste_du_texte(fen):
    mime = QMimeData()
    mime.setText("bonjour")
    fen.texte.insertFromMimeData(mime)
    assert fen.texte.toPlainText() == "bonjour" and fen.store.lister_pieces(fen.fiche) == []


def test_glisser_deposer_de_fichiers(fen, tmp_path):
    p = tmp_path / "photo.png"
    p.write_bytes(encoder(image(), "PNG"))
    (tmp_path / "note.txt").write_text("x")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)), QUrl.fromLocalFile(str(tmp_path / "note.txt"))])
    fen.texte.insertFromMimeData(mime)
    pieces = fen.store.lister_pieces(fen.fiche)
    assert [x.nom for x in pieces] == ["photo.png"]                 # le .txt n'est pas une image


def test_suppression_via_la_bande(fen):
    fen.bande.ajouter([image(), image(10, 10)])
    assert fen.bande.liste.count() == 2
    fen.bande.supprimer(0)
    assert fen.bande.liste.count() == 1 and len(os.listdir(fen.store.paths.corbeille)) >= 1


def test_fiche_verrouillee_bande_fermee_puis_ouverte(fen):
    fen.bande.ajouter([image()])
    fen.store.verrouiller(fen.fiche_theme, fen.fiche, "mdp", sans_secours=True)
    fen._afficher(fen.fiche_theme, fen.fiche)
    assert fen.bande.liste.count() == 1                             # ouverte : déchiffrée en mémoire
    f = fen.fiche
    f.texte = f.cle = f.salt = None
    fen._afficher(fen.fiche_theme, f)
    assert fen.bande.isHidden() and fen.bande.liste.count() == 0    # fermée : rien d'affiché
    fen.store.deverrouiller(f, "mdp")
    fen._afficher(fen.fiche_theme, f)
    assert fen.bande.liste.count() == 1


def test_titre_change_apres_ajout_les_images_suivent(fen):
    fen.bande.ajouter([image()])
    fen.titre.setText("Autre titre")
    fen.sauver()
    assert len(fen.store.lister_pieces(fen.fiche)) == 1 and fen.fiche.path.name == "Autre titre.md"


def test_recherche_trouve_le_texte_des_images(fen):
    fen.bande.ajouter([image()])
    piece = fen.store.lister_pieces(fen.fiche)[0]
    fen.store.maj_piece(fen.fiche, piece, ocr="facture électricité octobre")
    fen.recherche.setText("électricité")
    assert any(f is fen.fiche for _t, f in fen.rows)
    fen.recherche.setText("introuvable-xyz")
    assert fen.rows == []

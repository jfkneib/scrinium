# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension « Photos » : logique du type de fiche (chemin du dossier gardé dans la fiche) et vue en vignettes dans la vraie fenêtre."""
import importlib.util
import os
import shutil
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
from PyQt6.QtCore import QPoint  # noqa: E402
from PyQt6.QtGui import QColor, QImage  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from scrinium.core.paths import Paths  # noqa: E402
from scrinium.core.store import Store  # noqa: E402
from scrinium.ui.fenetre import Fenetre  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent / "plugins" / "photos"
_spec = importlib.util.spec_from_file_location("photos_logique", RACINE / "logique.py")
lg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lg)


def _image(chemin: Path, largeur=40, hauteur=30):
    img = QImage(largeur, hauteur, QImage.Format.Format_RGB32)
    img.fill(QColor("red"))
    assert img.save(str(chemin))


def test_format_de_la_fiche_photos():
    t = lg.en_texte("/tmp/mes photos")
    assert t == "#scrinium-photos\ndossier: /tmp/mes photos\n" and lg.depuis_texte(t) == "/tmp/mes photos"       # espaces permis
    avec_notes = t + "\nNotes libres\n"
    assert lg.depuis_texte(avec_notes) == "/tmp/mes photos"
    nouveau = lg.en_texte("/tmp/autre", avec_notes)
    assert lg.depuis_texte(nouveau) == "/tmp/autre" and "Notes libres" in nouveau and nouveau.count("dossier:") == 1   # notes gardées
    assert lg.depuis_texte("") == lg.depuis_texte(None) == lg.depuis_texte("texte libre") == "" and lg.depuis_texte("#scrinium-photos\n") == ""
    assert lg.depuis_texte("#scrinium-photos\nDOSSIER :  /x  \n") == "/x"
    assert lg.TYPE.nom == "photos" and not lg.TYPE.executable and lg.TYPE.marque == lg.MARQUE
    assert lg.en_texte("", None) == "#scrinium-photos\ndossier: \n"


def test_chemin_du_dossier_personnel_s_ecrit_avec_tilde(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "Images").mkdir()
    assert lg.depuis_texte(lg.en_texte(str(tmp_path / "Images"))) == "~/Images"
    assert lg.dossier("~/Images") == tmp_path / "Images" and lg.dossier("~/absent") is None and lg.dossier("  ") is None
    assert lg.raccourcir(str(tmp_path)) == "~" and lg.raccourcir("/tmp/ailleurs") == "/tmp/ailleurs"


def test_images_triees_naturellement_sans_sous_dossier(tmp_path):
    for nom in ("img10.jpg", "img2.png", "IMG1.JPG", "notes.txt", "x.gif"):
        (tmp_path / nom).write_bytes(b"x")
    (tmp_path / "sous.jpg").mkdir()                                        # un dossier nommé comme une image : ignoré
    (tmp_path / "sous").mkdir()
    (tmp_path / "sous" / "cache.jpg").write_bytes(b"x")                    # pas de descente dans les sous-dossiers
    liste, total = lg.images(tmp_path)
    assert [p.name for p in liste] == ["IMG1.JPG", "img2.png", "img10.jpg", "x.gif"] and total == 4
    liste, total = lg.images(tmp_path, maximum=2)
    assert len(liste) == 2 and total == 4
    assert lg.images(tmp_path / "absent") == ([], 0)


# ---------- dans la fenêtre ----------
@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def fen(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    s = Store(Paths(tmp_path / "am"))
    s.sauver_reglages(recovery_asked=True)
    shutil.copytree(RACINE, s.paths.base / "plugins" / "photos")
    w = Fenetre(s)
    w.plugins.decouvrir()
    assert w.plugins.activer("photos"), w.plugins.infos["photos"].erreur
    yield w
    w.quitter_vraiment = True
    w.close()


def _vider_file(vue):
    while vue._file:
        vue._lot(vue._generation)


def test_nouvelle_fiche_photos_puis_choix_du_dossier(fen, tmp_path, monkeypatch):
    m = fen.menu_nouvelle
    m.aboutToShow.emit()
    next(a for a in m.actions() if a.text() == "Photos").trigger()
    vue = fen.vues_types["photos"]
    assert fen.pile.currentWidget() is vue and fen.fiche.texte.startswith("#scrinium-photos") and fen.bandeau_validation.isHidden()
    assert "Aucun dossier" in vue.etiquette.text()
    dossier = tmp_path / "pics"
    dossier.mkdir()
    for nom in ("a.png", "b.png", "c.jpg"):
        _image(dossier / nom)
    (dossier / "faux.png").write_bytes(b"pas une image")
    import sys
    monkeypatch.setattr(sys.modules["scrinium_plugin_photos"].QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(dossier)))
    vue.choisir()
    fen.sauver()
    assert lg.depuis_texte(fen.fiche.texte) == str(dossier)                          # le chemin est dans la fiche
    assert vue.liste.count() == 4 and "4 image(s)" in vue.etiquette.text()
    _vider_file(vue)
    pas_image = next(i for i in range(4) if vue.liste.item(i).text() == "faux.png")
    assert all(vue._cache.get(vue._cle(Path(vue.liste.item(i).data(0x0100)))) is not None for i in range(4) if i != pas_image)   # vignettes en cache
    assert vue._cache.get(vue._cle(dossier / "faux.png")) is None                    # un faux fichier image : pas de vignette, pas de plantage


def test_dossier_introuvable_et_ouverture(fen, tmp_path, monkeypatch):
    import sys
    mod = sys.modules["scrinium_plugin_photos"]
    ouverts = []
    monkeypatch.setattr(mod.QDesktopServices, "openUrl", staticmethod(lambda u: ouverts.append(u.toLocalFile())))
    (tmp_path / "p").mkdir()
    _image(tmp_path / "p" / "un.png")
    vue = fen.vues_types["photos"]
    vue.charger(lg.en_texte(str(tmp_path / "absent")))
    assert "introuvable" in vue.etiquette.text() and vue.liste.count() == 0
    vue.charger(lg.en_texte(str(tmp_path / "p")))
    assert vue.liste.count() == 1
    vue._ouvrir(vue.liste.item(0))
    vue.ouvrir_dossier()
    assert ouverts == [str(tmp_path / "p" / "un.png"), str(tmp_path / "p")]
    noms = [t for t, _fn, _ic in vue.entrees_menu(QPoint(2, 2))]
    assert "Choisir un autre dossier…" in noms and "Actualiser" in noms


def test_rechargement_arrete_le_lot_en_cours_et_le_cache_sert(fen, tmp_path):
    (tmp_path / "p").mkdir()
    for i in range(30):
        _image(tmp_path / "p" / f"{i:02d}.png")
    vue = fen.vues_types["photos"]
    vue.charger(lg.en_texte(str(tmp_path / "p")))
    ancienne = vue._generation
    vue._lot(ancienne)                                                                 # un seul lot : le reste attend
    assert 0 < len(vue._file) < 30
    vue.charger(lg.en_texte(str(tmp_path / "p")))                                      # rechargé : la file repart d'ici
    vue._lot(ancienne)                                                                 # un lot de l'ancienne génération : ne fait rien
    n = len(vue._file)
    vue._lot(vue._generation)
    assert len(vue._file) == max(0, n - 12)
    _vider_file(vue)
    vue.recharger()
    assert vue._file == []                                                             # tout vient du cache : rien à recharger


def test_desactiver_retire_le_type(fen):
    from scrinium.core import types_fiche
    assert types_fiche.type_de("#scrinium-photos\n") is not None and "photos" in fen.vues_types
    fen.plugins.desactiver("photos")
    assert types_fiche.type_de("#scrinium-photos\n") is None and "photos" not in fen.vues_types


def test_clic_droit_ocr_cree_une_fiche_avec_le_texte(fen, app, tmp_path, monkeypatch):
    import sys
    import time
    vue = fen.vues_types["photos"]
    (tmp_path / "p").mkdir()
    _image(tmp_path / "p" / "scan.png")
    vue.charger(lg.en_texte(str(tmp_path / "p")))
    noms = lambda: [t for t, _f, _i in vue.entrees_menu(vue.liste.visualItemRect(vue.liste.item(0)).center())]   # noqa: E731
    assert not any("OCR" in t for t in noms())                                       # extension OCR absente : pas d'entrée
    shutil.copytree(RACINE.parent / "ocr", fen.store.paths.base / "plugins" / "ocr")
    fen.plugins.decouvrir()
    assert fen.plugins.activer("ocr"), fen.plugins.infos["ocr"].erreur
    mod = sys.modules["scrinium_plugin_ocr.logique"]
    monkeypatch.setattr(mod, "trouver", lambda chemin="": "/faux/tesseract")
    monkeypatch.setattr(mod, "langues_manquantes", lambda exe, langue: [])
    monkeypatch.setattr(mod, "reconnaitre", lambda exe, donnees, langue="fra": "Total 42 €")
    entree = next(fn for t, fn, _i in vue.entrees_menu(vue.liste.visualItemRect(vue.liste.item(0)).center()) if "OCR" in t)
    avant = sum(len(t.fiches) for t in fen.store.themes)
    entree()
    fin = time.time() + 8
    while time.time() < fin and sum(len(t.fiches) for t in fen.store.themes) == avant:
        app.processEvents()
        time.sleep(0.01)
    nouvelles = [f for t in fen.store.themes for f in t.fiches if f.titre == "Texte de scan.png"]
    assert len(nouvelles) == 1 and "Total 42 €" in nouvelles[0].texte and "scan.png" in nouvelles[0].texte

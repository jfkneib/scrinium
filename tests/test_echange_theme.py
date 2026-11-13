"""Export / import d'un thème entier en zip."""
import json
import zipfile

import pytest
from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

from scrinium.core import echange_theme, types_fiche
from scrinium.core.paths import Paths
from scrinium.core.store import Store
from scrinium.ui.images import preparer


def _png(couleur=0xFF3366) -> bytes:
    QApplication.instance() or QApplication([])
    img = QImage(24, 16, QImage.Format.Format_RGB32)
    img.fill(couleur)
    ba = QByteArray()
    b = QBuffer(ba)
    b.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(b, "PNG")
    return bytes(ba)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    s = Store(Paths(tmp_path / "am"))
    s.sauver_reglages(recovery_asked=True)
    return s


def _theme_riche(s):
    t = s.nouveau_theme("Doc")
    s.icone_theme(t, "folder-documents")
    a = s.nouvelle_fiche(t)
    s.enregistrer(t, a, "Beta", "texte de beta")
    b = s.nouvelle_fiche(t)
    s.enregistrer(t, b, "Alpha", "texte d'alpha")
    s.ajouter_piece(b, "photo.png", "image/png", _png())
    c = s.nouvelle_fiche(t)
    s.enregistrer(t, c, "Secrète", "contenu confidentiel")
    s.ajouter_piece(c, "carte.png", "image/png", _png(0x112233))
    s.verrouiller(t, c, "mdp", sans_secours=True)
    s.ordonner_fiches(t, ["Beta.md", "Alpha.md", "Secrète.lock"])
    return t


def test_export_puis_import(store, tmp_path):
    t = _theme_riche(store)
    z = tmp_path / "doc.zip"
    r = echange_theme.exporter(store, t, z)
    assert r == {"fiches": 2, "verrouillees": 1, "images": 1}
    noms = zipfile.ZipFile(z).namelist()
    assert "Doc/Alpha.md" in noms and "Doc/Secrète.lock" in noms and any(n.startswith("Doc/Secrète.pj/") for n in noms)
    brut = b"".join(zipfile.ZipFile(z).read(n) for n in noms)
    assert b"contenu confidentiel" not in brut                       # la fiche verrouillée reste chiffrée dans l'archive
    th2, rap = echange_theme.importer(store, z, preparer)
    assert th2.nom == "Doc (2)" and th2 is not t                      # jamais de fusion avec l'existant
    assert (rap["fiches"], rap["verrouillees"], rap["images"]) == (2, 1, 1) and not rap["ignores"]
    assert th2.icone == "folder-documents"
    assert [f.titre for f in store.fiches_triees(th2)] == ["Beta", "Alpha", "Secrète"]   # l'ordre est conservé
    alpha = next(f for f in th2.fiches if f.titre == "Alpha")
    assert alpha.texte.strip() == "texte d'alpha" and len(store.lister_pieces(alpha)) == 1
    sec = next(f for f in th2.fiches if f.verrou)
    assert sec.fermee
    store.deverrouiller(sec, "mdp")
    assert sec.texte == "contenu confidentiel" and len(store.lister_pieces(sec)) == 1


def test_import_archive_dangereuse(store, tmp_path):
    z = tmp_path / "mal.zip"
    with zipfile.ZipFile(z, "w") as zz:
        zz.writestr("../evade.md", "# X\n\nx")
        zz.writestr("/abs.md", "# Y")
        zz.writestr("T/ok.md", "# Ok\n\nbien")
        zz.writestr("T/bizarre.exe", "MZ")
        zz.writestr("T/faux.lock", b"pas verrouille")
    th, rap = echange_theme.importer(store, z, preparer)
    assert [f.titre for f in th.fiches] == ["Ok"] and rap["fiches"] == 1 and rap["verrouillees"] == 0
    assert len(rap["ignores"]) == 4
    assert not (tmp_path / "evade.md").exists() and not (store.paths.fiches.parent / "evade.md").exists()


def test_import_zip_invalide_ou_demesure(store, tmp_path, monkeypatch):
    (tmp_path / "x.zip").write_bytes(b"pas un zip")
    with pytest.raises(ValueError):
        echange_theme.importer(store, tmp_path / "x.zip", preparer)
    z = tmp_path / "gros.zip"
    with zipfile.ZipFile(z, "w") as zz:
        zz.writestr("a.md", "# a")
    monkeypatch.setattr(echange_theme, "ENTREES_MAX", 0)
    with pytest.raises(ValueError):
        echange_theme.importer(store, z, preparer)
    assert store.themes == []                                         # rien n'est créé quand l'archive est refusée


def test_fiche_executable_importee_inerte(store, tmp_path):
    tf = types_fiche.TypeFiche("essai-th", "Essai", "document-new", executable=True, modele=lambda: "")
    types_fiche.enregistrer(tf)
    try:
        z = tmp_path / "e.zip"
        with zipfile.ZipFile(z, "w") as zz:
            zz.writestr("T/e.md", "# Essai\n\n#scrinium-essai-th\nx\n")
            zz.writestr(echange_theme.MANIFESTE, json.dumps({"format": echange_theme.FORMAT, "theme": "Venu d'ailleurs"}))
        th, _r = echange_theme.importer(store, z, preparer)
        assert th.nom == "Venu d'ailleurs" and not store.fiche_active(th, th.fiches[0])
    finally:
        types_fiche.desenregistrer("essai-th")


def test_depuis_la_fenetre(tmp_path, monkeypatch):
    from scrinium.ui.fenetre import Fenetre
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    s = Store(Paths(tmp_path / "am"))
    s.sauver_reglages(recovery_asked=True)
    t = _theme_riche(s)
    w = Fenetre(s)
    try:
        w.theme = t.nom
        z = tmp_path / "sortie.zip"
        w.exporter_theme(str(z))
        assert z.exists()
        w.importer_theme(str(z))
        assert w.theme == "Doc (2)" and s.theme("Doc (2)") is not None
    finally:
        w.close()

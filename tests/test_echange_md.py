"""Export / import d'une fiche en fichier Markdown, avec ses images."""
import pytest
from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
from PyQt6.QtGui import QImage
from PyQt6.QtWidgets import QApplication

from scrinium.core import echange_md, types_fiche
from scrinium.core.paths import Paths
from scrinium.core.store import Store
from scrinium.ui.fenetre import Fenetre
from scrinium.ui.images import preparer


def _png(couleur=0xFF3366, taille=(30, 20)) -> bytes:
    QApplication.instance() or QApplication([])
    img = QImage(*taille, QImage.Format.Format_RGB32)
    img.fill(couleur)
    ba = QByteArray()
    b = QBuffer(ba)
    b.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(b, "PNG")
    return bytes(ba)


@pytest.fixture
def fen(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    s = Store(Paths(tmp_path / "am"))
    s.sauver_reglages(recovery_asked=True)
    t = s.nouveau_theme("Doc")
    w = Fenetre(s)
    yield w, t, tmp_path
    w.close()


def test_analyser():
    titre, texte, refs = echange_md.analyser("# Ma page\n\nBonjour\n\n![schéma](img/a%20b.png)\n\nFin [lien](https://x.org) ![d](https://x.org/i.png)\n\n## Images\n\n![z](z.png)\n", "defaut")
    assert titre == "Ma page" and "Bonjour" in texte and "Fin [lien]" in texte
    assert [r[1] for r in refs] == ["img/a b.png", "z.png"]           # les adresses http ne sont pas des images locales
    assert "## Images" not in texte and "schéma" not in texte
    assert echange_md.analyser("pas de titre\n", "nom")[:2] == ("nom", "pas de titre\n")
    assert echange_md.analyser("# C#\n\nx", "n")[0] == "C#"


def test_aller_retour_avec_images(fen):
    w, t, tmp = fen
    f = w.store.nouvelle_fiche(t)
    w.store.enregistrer(t, f, "Page de doc", "Texte avec **gras**.\n\n- un\n- deux")
    w.store.ajouter_piece(f, "capture.png", "image/png", _png())
    w.store.ajouter_piece(f, "autre image.png", "image/png", _png(0x3366FF))
    w._afficher(t, f)
    sortie = tmp / "export" / "Page de doc.md"
    sortie.parent.mkdir()
    w.exporter_markdown(str(sortie))
    md = sortie.read_text(encoding="utf-8")
    assert md.startswith("# Page de doc\n\nTexte avec **gras**.") and "## Images" in md
    images = sorted((sortie.parent / "Page de doc_images").iterdir())
    assert [p.name for p in images] == ["01-capture.png", "02-autre image.png"]
    # réimport : une NOUVELLE fiche, mêmes texte et images
    w.importer_markdown([sortie])
    g = w.fiche
    assert g is not f and g.titre == "Page de doc"
    assert g.texte.strip() == "Texte avec **gras**.\n\n- un\n- deux"
    assert len(w.store.lister_pieces(g)) == 2 and len(w.store.lister_pieces(f)) == 2


def test_import_refuse_ce_qui_sort_du_dossier(fen):
    w, t, tmp = fen
    (tmp / "secret.png").write_bytes(_png())
    d = tmp / "d"
    d.mkdir()
    (d / "a.md").write_text("# A\n\n![x](../secret.png)\n\n![y](/etc/passwd.png)\n", encoding="utf-8")
    f, n, ignorees = echange_md.importer(w.store, t, d / "a.md", preparer)
    assert n == 0 and len(ignorees) == 1 and "secret.png" in ignorees[0]      # « ../ » refusé ; le chemin absolu n'est pas une image locale


def test_import_fichier_binaire_ou_trop_gros(fen, tmp_path):
    w, t, tmp = fen
    (tmp / "b.md").write_bytes(b"abc\x00def")
    with pytest.raises(ValueError):
        echange_md.importer(w.store, t, tmp / "b.md", preparer)


def test_fiche_executable_importee_reste_inerte(fen):
    w, t, tmp = fen
    tf = types_fiche.TypeFiche("essai-md", "Essai", "document-new", executable=True, modele=lambda: "")
    types_fiche.enregistrer(tf)
    try:
        (tmp / "e.md").write_text("# Essai\n\n#scrinium-essai-md\nlignes\n", encoding="utf-8")
        f, n, _i = echange_md.importer(w.store, t, tmp / "e.md", preparer)
        assert types_fiche.type_de(f.texte) is not None and not w.store.fiche_active(t, f)
    finally:
        types_fiche.desenregistrer("essai-md")


def test_export_fiche_fermee_refuse(fen):
    w, t, tmp = fen
    f = w.store.nouvelle_fiche(t)
    w.store.enregistrer(t, f, "Secrète", "x")
    w.store.verrouiller(t, f, "mdp", sans_secours=True)
    w.store.refermer(f)
    assert f.fermee
    with pytest.raises(ValueError):
        echange_md.exporter(w.store, f, tmp / "s.md", "Secrète", "")
    assert not (tmp / "s.md").exists()

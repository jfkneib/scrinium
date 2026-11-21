# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Documents : une fiche `#scrinium-objet` = une description + un fichier joint."""
import importlib.util
import os
import shutil
from pathlib import Path

import pytest

from scrinium.core import types_fiche
from scrinium.core.paths import Paths
from scrinium.core.store import Store

PLUGINS = Path(__file__).resolve().parent.parent / "plugins"
ODT = "application/vnd.oasis.opendocument.text"


def _logique():
    spec = importlib.util.spec_from_file_location("doc_logique", PLUGINS / "documents" / "logique.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_texte_et_description_font_l_aller_retour():
    L = _logique()
    assert L.texte_de("") == "#scrinium-objet\n" and L.description(L.texte_de("")) == ""
    t = L.texte_de("Contrat de location\nsigné le 3 mai")
    assert t.startswith("#scrinium-objet\n\n") and L.description(t) == "Contrat de location\nsigné le 3 mai\n"
    assert L.texte_de(L.description(t)) == t                                  # stable : pas de lignes vides qui s'ajoutent
    assert L.description("texte libre") == "texte libre" and L.description(None) == ""
    assert L.description("#scrinium-autre\nreste") == "#scrinium-autre\nreste"   # la marque d'un autre type n'est pas retirée


def test_type_mime_et_taille():
    L = _logique()
    assert L.type_mime("a.odt") == ODT and L.type_mime("Rapport.PDF") == "application/pdf"
    assert L.type_mime("inconnu.zzzq") == "application/octet-stream" and L.type_mime("") == "application/octet-stream"
    assert L.titre_de("kate.png") == "kate" and L.titre_de("Rapport final.v2.odt") == "Rapport final.v2" and L.titre_de(".bashrc") == ".bashrc"
    assert L.titre_de("/tmp/x/kate.odt") == "kate" and L.titre_de("") == "document"
    assert L.taille_lisible(10) == ("ko", "1") and L.taille_lisible(5000) == ("ko", "5")
    assert L.taille_lisible(3 * 1048576) == ("mo", "3,0")


def test_le_type_se_reconnait_et_s_imprime_sans_marque():
    L = _logique()
    types_fiche.desenregistrer("objet")
    types_fiche.enregistrer(L.TYPE)
    try:
        t = L.TYPE.texte_neuf()
        assert types_fiche.type_de(t) == L.TYPE and not L.TYPE.executable
        assert types_fiche.en_markdown(L.texte_de("Notice")) == "Notice\n"
    finally:
        types_fiche.desenregistrer("objet")


def test_la_fiche_garde_son_fichier_sans_l_extension(tmp_path):
    """Sans l'extension : la fiche reste un texte ordinaire et le fichier reste une pièce lisible et enregistrable."""
    L = _logique()
    s = Store(Paths(tmp_path / "am"))
    s.charger()
    th = s.nouveau_theme("T")
    f = s.nouvelle_fiche(th)
    s.enregistrer(th, f, "Contrat", L.texte_de("Location"))
    s.ajouter_piece(f, "contrat.odt", ODT, b"PK-contenu")
    g = Store(s.paths)
    g.charger()
    h = g.theme("T").fiches[0]
    assert types_fiche.type_de(h.texte) is None and "Location" in h.texte           # type inconnu : texte libre
    (p,) = g.lister_pieces(h)
    assert (p.nom, p.type) == ("contrat.odt", ODT) and g.lire_piece(h, p) == b"PK-contenu"


def test_copie_de_travail_surveillance_et_purge(tmp_path):
    L = _logique()
    assert L.nom_sur_disque("../../etc/passwd") == "passwd" and L.nom_sur_disque("a:b*c.odt") == "a_b_c.odt"
    assert L.nom_sur_disque("") == "document" and L.nom_sur_disque("...") == "document"
    c = L.copie_de_travail(tmp_path / "w", "Rapport.odt", b"abc")
    assert c.read_bytes() == b"abc" and c.name == "Rapport.odt" and c.parent.parent == tmp_path / "w"
    if os.name == "posix":
        assert c.stat().st_mode & 0o777 == 0o600 and c.parent.stat().st_mode & 0o777 == 0o700
    v = L.Surveillance(c)
    assert not v.sonder() and not v.a_change()
    c.write_bytes(b"abcd")
    os.utime(c, ns=(1, 1))                                  # date nettement différente, même si l'écriture est dans la même seconde
    assert v.a_change() and not v.sonder()                   # première interrogation : pas encore stable
    assert v.sonder()                                        # deuxième, même signature : stable, à reprendre
    c.write_bytes(b"abcde")                                  # l'application écrit encore : le compteur repart
    os.utime(c, ns=(2, 2))
    assert not v.sonder() and v.sonder()
    v.acquitter()
    assert not v.sonder() and not v.a_change()
    L.purger(c)
    assert not c.parent.exists()
    d = tmp_path / "w"
    (d / "edition-restee").mkdir()
    (d / "autre").mkdir()
    L.purger_tout(d)
    assert not (d / "edition-restee").exists() and (d / "autre").exists()


# ---------- extraction du texte ----------
def _extraction():
    spec = importlib.util.spec_from_file_location("doc_extraction", PLUGINS / "documents" / "extraction.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _zip(membres: dict) -> bytes:
    import io
    import zipfile
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        for nom, contenu in membres.items():
            z.writestr(nom, contenu)
    return b.getvalue()


def test_extraction_odf_ooxml_et_texte_brut():
    X = _extraction()
    odt = _zip({"content.xml": '<?xml version="1.0"?><office:document-content xmlns:office="o" xmlns:text="t" xmlns:table="b">'
                '<office:automatic-styles><text:p>STYLE</text:p></office:automatic-styles>'
                '<office:body><text:h>Titre</text:h><text:p>Un<text:s text:c="2"/>deux<text:tab/>trois<text:line-break/>quatre</text:p>'
                '<table:table><table:table-row><table:table-cell><text:p>A1</text:p></table:table-cell>'
                '<table:table-cell><text:p>B1</text:p></table:table-cell></table:table-row></table:table></office:body></office:document-content>'})
    t = X.extraire("Rapport.odt", ODT, odt)
    assert t == "Titre\nUn deux trois\nquatre\nA1\nB1"                          # sans le style, espaces réduits, un saut par paragraphe
    docx = _zip({"word/document.xml": '<w:document xmlns:w="w"><w:body><w:p><w:r><w:t>Contrat</w:t></w:r><w:r><w:tab/><w:t>signé</w:t></w:r></w:p>'
                 '<w:p><w:r><w:delText>supprimé</w:delText><w:instrText>CHAMP</w:instrText></w:r><w:r><w:t>fin</w:t></w:r></w:p></w:body></w:document>'})
    assert X.extraire("a.docx", "", docx) == "Contrat signé\nfin"
    xlsx = _zip({"xl/sharedStrings.xml": '<sst xmlns="s"><si><t>Loyer</t></si><si><r><t>Charges</t></r><r><t> 2026</t></r></si></sst>'})
    assert X.extraire("a.xlsx", "", xlsx) == "Loyer\nCharges 2026"
    pptx = _zip({"ppt/slides/slide10.xml": '<p:sld xmlns:p="p" xmlns:a="a"><a:p><a:r><a:t>dix</a:t></a:r></a:p></p:sld>',
                 "ppt/slides/slide2.xml": '<p:sld xmlns:p="p" xmlns:a="a"><a:p><a:r><a:t>deux</a:t></a:r></a:p></p:sld>'})
    assert X.extraire("a.pptx", "", pptx) == "deux\ndix"                        # dans l'ordre des numéros, pas alphabétique
    assert X.extraire("n.txt", "text/plain", "caf\u00e9\r\nlait".encode("cp1252")) == "café\nlait"
    assert X.extraire("inconnu.xyz", "application/octet-stream", b"abc") is None and not X.prise_en_charge("a.doc")


def test_extraction_refuse_le_dangereux_et_borne(monkeypatch):
    X = _extraction()
    dtd = _zip({"content.xml": '<!DOCTYPE x [<!ENTITY a "bombe">]><office:document-content xmlns:office="o">&a;</office:document-content>'})
    with pytest.raises(X.FormatIllisible):
        X.extraire("a.odt", ODT, dtd)
    with pytest.raises(X.FormatIllisible):
        X.extraire("a.odt", ODT, b"PK pas une archive")
    gros = _zip({"content.xml": "<a>" + "x" * 5000 + "</a>"})
    monkeypatch.setattr(X, "MEMBRE_MAX", 1000)
    with pytest.raises(X.FormatIllisible):
        X.extraire("a.odt", ODT, gros)                                          # une fois décompressé : trop gros
    monkeypatch.undo()
    assert X.extraire("a.txt", "text/plain", b"x" * 10) == "x" * 10
    monkeypatch.setattr(X, "TEXTE_MAX", 5)
    assert X.extraire("a.txt", "text/plain", b"123456789") == "12345"
    monkeypatch.setattr(X, "SOURCE_MAX", 3)
    assert X.extraire("a.txt", "text/plain", b"1234") is None                  # fichier source trop gros : pas d'extraction
    monkeypatch.undo()
    with pytest.raises(X.FormatIllisible):
        X.extraire("b.txt", "text/plain", b"ab\x00cd")                          # contenu binaire sous un nom de texte


def test_extraction_pdf_sans_outil_le_dit(monkeypatch):
    X = _extraction()
    monkeypatch.setattr(X.shutil, "which", lambda nom: None)
    with pytest.raises(X.OutilManquant):
        X.extraire("a.pdf", "application/pdf", b"%PDF-1.7")


# ---------- avec la fenêtre (Qt hors écran) ----------
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def fen(tmp_path, monkeypatch):
    pytest.importorskip("PyQt6")
    from PyQt6.QtWidgets import QApplication
    from scrinium.ui.fenetre import Fenetre
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    s = Store(Paths(tmp_path / "am"))
    s.sauver_reglages(recovery_asked=True)
    shutil.copytree(PLUGINS / "documents", s.paths.base / "plugins" / "documents")
    w = Fenetre(s)
    w.plugins.decouvrir()
    assert w.plugins.activer("documents"), w.plugins.infos["documents"].erreur
    w.nouvelle_fiche()
    w.titre.setText("Contrat")
    w.sauver()
    yield w
    w.quitter_vraiment = True
    w.close()
    types_fiche.desenregistrer("objet")


def test_vue_document_ajoute_remplace_et_enregistre(fen, monkeypatch, tmp_path):
    from PyQt6.QtWidgets import QFileDialog, QMessageBox
    L = _logique()
    assert any(t.nom == "objet" for t in types_fiche.types()) and "objet" in fen.vues_types
    vue = fen.vues_types["objet"]
    f = fen.fiche
    vue.charger(L.texte_de("Location"))
    assert vue.desc.toPlainText() == "Location\n"
    emis = []
    vue.modifie.connect(emis.append)
    vue.desc.setPlainText("Location 2026")
    assert emis[-1] == L.texte_de("Location 2026")
    source = tmp_path / "contrat.odt"
    source.write_bytes(b"PK-un")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(source), ""))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: pytest.fail("erreur inattendue : %s" % (a,)))
    vue.choisir()
    (p,) = fen.store.lister_pieces(f)
    assert (p.nom, p.type) == ("contrat.odt", ODT) and vue.b_sous.isEnabled() and "contrat.odt" in vue.etat.text()
    source.write_bytes(b"PK-deux")
    vue.choisir()                                                                       # remplace : même pièce, ancienne version à la corbeille
    (q,) = fen.store.lister_pieces(f)
    assert q.id == p.id and fen.store.lire_piece(f, q) == b"PK-deux" and os.listdir(fen.store.paths.corbeille)
    sortie = tmp_path / "copie.odt"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(sortie), ""))
    vue.enregistrer_sous()
    assert sortie.read_bytes() == b"PK-deux"


def test_vue_edition_externe_reprend_les_enregistrements(fen, monkeypatch):
    from PyQt6.QtGui import QDesktopServices
    from PyQt6.QtWidgets import QMessageBox
    L = _logique()
    vue = fen.vues_types["objet"]
    f = fen.fiche
    ctx = fen.plugins.actifs["documents"][1]
    fv = ctx.fiche_courante()
    ctx.ajouter_piece(fv, "contrat.odt", ODT, b"PK-un")
    vue.charger(L.texte_de("Location"))
    ouverts = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: ouverts.append(url.toLocalFile()) or True)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: pytest.fail("erreur inattendue : %s" % (a,)))
    vue.ouvrir_externe()
    (chemin,) = ouverts
    chemin = Path(chemin)
    assert chemin.read_bytes() == b"PK-un" and not vue.b_ouvrir.isEnabled() and not vue.b_fin.isHidden()
    chemin.write_bytes(b"PK-modifie")
    os.utime(chemin, ns=(5, 5))
    vue._sonder()                                            # pas encore stable
    assert fen.store.lire_piece(f, fen.store.lister_pieces(f)[0]) == b"PK-un"
    vue._sonder()                                            # stable : repris dans la fiche
    (p,) = fen.store.lister_pieces(f)
    assert fen.store.lire_piece(f, p) == b"PK-modifie" and p.type == ODT and os.listdir(fen.store.paths.corbeille)
    chemin.write_bytes(b"PK-dernier")                        # enregistré juste avant « Terminer » : repris quand même
    os.utime(chemin, ns=(9, 9))
    vue.terminer()
    assert fen.store.lire_piece(f, fen.store.lister_pieces(f)[0]) == b"PK-dernier"
    assert not chemin.exists() and vue.b_fin.isHidden() and vue.b_ouvrir.isEnabled()


def test_fichiers_deposes_sur_la_fenetre_creent_des_fiches_documents(fen, monkeypatch, tmp_path):
    from PyQt6.QtWidgets import QMessageBox
    L = _logique()
    assert [n for n, _fn in fen.depots] == ["documents"]
    a, b = tmp_path / "kate.odt", tmp_path / "carte.png"
    a.write_bytes(b"PK-kate")
    b.write_bytes(b"\x89PNG-carte")
    monkeypatch.setattr(QMessageBox, "warning", lambda *a_, **k: pytest.fail("erreur inattendue"))
    fen._importer_deposes([], [], [a, b, tmp_path / "absent.pdf"])         # le dernier n'existe pas : signalé, sans bloquer les autres
    nouvelles = [f for t in fen.store.themes for f in t.fiches if f.titre in ("kate", "carte")]
    assert sorted(f.titre for f in nouvelles) == ["carte", "kate"]
    for f in nouvelles:
        assert types_fiche.type_de(f.texte).nom == "objet" and L.description(f.texte) == ""
        (p,) = fen.store.lister_pieces(f)
        assert p.nom in ("kate.odt", "carte.png") and fen.store.lire_piece(f, p) in (b"PK-kate", b"\x89PNG-carte")
    assert {fen.store.lister_pieces(f)[0].type for f in nouvelles} == {ODT, "image/png"}


def test_sans_l_extension_les_fichiers_deposes_ne_font_rien(fen):
    fen.plugins.desactiver("documents")
    assert fen.depots == [] and fen._autres_deposes(_MimeFichiers(["/etc/hostname"])) == []


class _MimeFichiers:
    """Faux QMimeData : seulement `urls()`."""
    def __init__(self, chemins):
        self._c = chemins

    def urls(self):
        from PyQt6.QtCore import QUrl
        return [QUrl.fromLocalFile(c) for c in self._c]


def test_le_texte_des_documents_joints_est_cherchable(fen, monkeypatch, tmp_path):
    from PyQt6.QtWidgets import QFileDialog, QMessageBox
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: pytest.fail("erreur inattendue : %s" % (a,)))
    docx = tmp_path / "bail.docx"
    docx.write_bytes(_zip({"word/document.xml": '<w:document xmlns:w="w"><w:body><w:p><w:r><w:t>Loyer mensuel : 650 euros</w:t></w:r></w:p></w:body></w:document>'}))
    fen._importer_deposes([], [], [docx])
    f = next(f for t in fen.store.themes for f in t.fiches if f.titre == "bail")
    (p,) = fen.store.lister_pieces(f)
    assert p.ocr == "Loyer mensuel : 650 euros" and p.ocr_moteur == "documents"
    assert "650 euros" in fen.store.texte_ocr(f)                                   # c'est ce que cherche Ctrl+F
    # remplacement par la vue : l'ancien texte disparaît, le nouveau est rangé (une seule fois, sans boucle d'événements)
    vue = fen.vues_types["objet"]
    ctx = fen.plugins.actifs["documents"][1]
    fv = next(v for v in ctx.fiches() if v.titre == "bail")
    monkeypatch.setattr(vue, "_piece", lambda: (fv, ctx.pieces(fv)[0]))
    autre = tmp_path / "bail2.docx"
    autre.write_bytes(_zip({"word/document.xml": '<w:document xmlns:w="w"><w:body><w:p><w:r><w:t>Charges : 80 euros</w:t></w:r></w:p></w:body></w:document>'}))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(autre), ""))
    vue.choisir()
    (q,) = fen.store.lister_pieces(f)
    assert q.ocr == "Charges : 80 euros" and "650" not in fen.store.texte_ocr(f)
    # un texte que l'extension ne sait pas lire reste sans texte, sans erreur
    inconnu = tmp_path / "image.xyz"
    inconnu.write_bytes(b"\x00\x01")
    fen._importer_deposes([], [], [inconnu])
    g = next(f for t in fen.store.themes for f in t.fiches if f.titre == "image")
    assert fen.store.lister_pieces(g)[0].ocr == ""

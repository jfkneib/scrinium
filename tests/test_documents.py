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

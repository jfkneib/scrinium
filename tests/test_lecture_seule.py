"""Lecture seule d'une fiche ou d'un thème : le texte, le titre, la mise en forme, le collage et les extensions ne l'écrivent plus."""
import pytest
from PyQt6.QtWidgets import QApplication

from scrinium.core.paths import Paths
from scrinium.core.store import Store
from scrinium.ui.fenetre import Fenetre


@pytest.fixture
def fen(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    s = Store(Paths(tmp_path / "am"))
    s.sauver_reglages(recovery_asked=True)
    t = s.nouveau_theme("Doc")
    f = s.nouvelle_fiche(t)
    s.enregistrer(t, f, "Page", "texte de la page")
    g = s.nouvelle_fiche(t)
    s.enregistrer(t, g, "Autre", "autre texte")
    w = Fenetre(s)
    yield w, t, f, g
    w.close()


def test_fiche_en_lecture_seule(fen):
    w, t, f, g = fen
    w._afficher(t, f)
    assert not w.texte.isReadOnly()
    w.basculer_lecture_seule(t, f)
    assert w.store.fiche_lecture_seule(t, f) and not w.store.fiche_lecture_seule(t, g)
    assert w.texte.isReadOnly() and w.titre.isReadOnly()
    assert not any(b.isEnabled() for b in w.format.boutons)
    w.format.b_apercu.setChecked(False)                    # retour à l'éditeur : les boutons d'écriture restent grisés
    assert not any(b.isEnabled() for b in w.format.boutons)
    assert w.plugins is not None
    w._afficher(t, g)                                      # l'autre fiche reste modifiable
    assert not w.texte.isReadOnly() and not w.titre.isReadOnly() and all(b.isEnabled() for b in w.format.boutons)
    w._afficher(t, f)
    w.basculer_lecture_seule(t, f)                         # on la lève
    assert not w.texte.isReadOnly() and not w.store.fiche_lecture_seule(t, f)


def test_theme_en_lecture_seule_et_renommage(fen):
    w, t, f, g = fen
    w._afficher(t, g)
    w.basculer_lecture_seule(t)
    assert w.store.theme_lecture_seule(t) and w.texte.isReadOnly()
    assert w.store.fiche_lecture_seule(t, f)
    w.store.renommer_theme(t, "Documentation")             # le réglage suit le renommage
    t2 = t                                                 # le thème est renommé en place
    assert t.path.name == "Documentation"
    assert t2 is not None and w.store.theme_lecture_seule(t2) and w.store.fiche_lecture_seule(t2, t2.fiches[0])
    w.basculer_lecture_seule(t2)
    assert not w.store.theme_lecture_seule(t2)


def test_collage_et_extensions_refusent(fen):
    from PyQt6.QtCore import QMimeData
    w, t, f, g = fen
    w._afficher(t, f)
    w.basculer_lecture_seule(t, f)
    avant = w.texte.toPlainText()
    m = QMimeData()
    m.setText("intrus")
    w.texte.insertFromMimeData(m)
    assert w.texte.toPlainText() == avant
    from scrinium.ui.chercher_remplacer import BarreChercherRemplacer
    b = BarreChercherRemplacer(w.texte)
    b.chercher.setText("texte")
    b.remplacer.setText("X")
    assert b.remplacer_tout() == 0 and w.texte.toPlainText() == avant

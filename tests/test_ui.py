import os
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication  # noqa: E402

from scrinium.core.paths import Paths  # noqa: E402
from scrinium.core.store import Store  # noqa: E402
from scrinium.ui import instance  # noqa: E402
from scrinium.ui.fenetre import Fenetre  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def fen(app, tmp_path):
    s = Store(Paths(tmp_path / "am"))
    s.sauver_reglages(recovery_asked=True)
    w = Fenetre(s)
    yield w
    w.quitter_vraiment = True
    w.close()


def test_demarre_sur_bienvenue(fen):
    assert fen.theme == "Bienvenue" and fen.fiche.titre.startswith("1")


def test_cacher_referme_les_fiches_verrouillees(fen):
    demo = next(f for t in fen.store.themes for f in t.fiches if f.verrou)
    fen.store.deverrouiller(demo, "scrinium")
    assert not demo.fermee
    fen.cacher()
    assert demo.fermee and demo.cle is None and not fen.isVisible()


def test_fermer_sans_option_ferme(fen):
    fen.a_tray.setChecked(False)
    assert not fen.tray_actif
    fen.show()
    assert fen.close() and not fen.isVisible()


def test_fermer_avec_option_cache_dans_la_zone_de_notification(fen):
    if fen.tray is None:
        pytest.skip("pas de zone de notification sur cette session")
    fen.a_tray.setChecked(True)
    fen.show()
    assert fen.tray_actif
    assert not fen.close()          # fermeture interceptée
    assert not fen.isVisible()      # cachée, l'application tourne toujours
    fen.montrer()
    assert fen.isVisible()


def test_instance_unique(app):
    srv = instance.Serveur()
    recus = []
    srv.reveil.connect(lambda th, nv: recus.append((th, nv)))
    assert instance.reveiller_existante("Perso", True)
    for _ in range(50):
        app.processEvents()
        if recus:
            break
    assert recus == [("Perso", True)]


def test_lancement_automatique(fen, tmp_path, monkeypatch):
    import sys
    if sys.platform in ("win32", "darwin"):
        pytest.skip("test limité à Linux (XDG autostart)")
    from scrinium.core import autostart
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert not autostart.actif()
    fen.a_demarrage.setChecked(True)
    f = tmp_path / "xdg" / "autostart" / "scrinium.desktop"
    assert f.exists() and autostart.actif()
    contenu = f.read_text(encoding="utf-8")
    assert "--minimise" in contenu and "Exec=" in contenu
    fen.a_demarrage.setChecked(False)
    assert not f.exists()


def test_pas_de_popup_au_demarrage_et_fichier_de_secours_au_premier_verrou(fen, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    from scrinium.ui import assistant
    assert not fen.store.a_cle_de_secours          # rien n'a été imposé à l'ouverture
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: self.buttons()[0])
    dlg = assistant.AssistantCle(fen.store, fen)
    dlg.e_nom.setText("Mon secours perso")
    dlg.e_dossier.setText(str(tmp_path / "docs"))
    dlg.e_p1.setText("abc"); dlg.e_p2.setText("abc")
    dlg._valider()
    assert (tmp_path / "docs" / "Mon secours perso.pem").exists()
    assert fen.store.a_cle_de_secours


def test_nouveau_fichier_de_secours_garde_l_ancienne_cle_publique(fen, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    from scrinium.ui import assistant
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: self.buttons()[0])
    for nom, rempl in (("un", False), ("deux", True)):
        d = assistant.AssistantCle(fen.store, fen, remplacer=rempl)
        d.e_nom.setText(nom); d.e_dossier.setText(str(tmp_path / "k"))
        d._valider()
    assert (tmp_path / "k" / "un.pem").exists() and (tmp_path / "k" / "deux.pem").exists()
    assert len(list(fen.store.paths.base.glob("recovery-*.pub.ancienne"))) == 1


def test_nom_deja_pris_refuse(fen, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    from scrinium.ui import assistant
    vu = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a: vu.append(a[2])))
    d = assistant.AssistantCle(fen.store, fen)
    d.e_nom.setText("x"); d.e_dossier.setText(str(tmp_path))
    (tmp_path / "x.pem").write_text("déjà là")
    d._valider()
    assert vu and (tmp_path / "x.pem").read_text() == "déjà là" and not fen.store.a_cle_de_secours

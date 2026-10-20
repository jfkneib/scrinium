# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
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
def fen(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))   # jamais de lecture/écriture dans le vrai ~/.config
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


def test_instance_unique(app, monkeypatch):
    monkeypatch.setenv("SCRINIUM_INSTANCE", f"scrinium-test-{os.getpid()}")   # jamais le canal d'une vraie instance
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


# ---------- extensions ----------
def _plugin_ui(fen):
    d = fen.store.paths.base / "plugins" / "demo"
    d.mkdir(parents=True)
    (d / "plugin.json").write_text('{"titre": "Demo", "classe": "P", "api": 1}')
    (d / "__init__.py").write_text('''
from PyQt6.QtWidgets import QLabel
from scrinium.core.plugins import Plugin
class P(Plugin):
    def activer(self, ctx):
        self.vus = []
        ctx.ui.ajouter_action("Faire un truc", lambda: self.vus.append("action"))
        ctx.ui.ajouter_bouton("Bouton", lambda: None)
        ctx.ui.ajouter_panneau("Mon panneau", QLabel("salut"))
        ctx.on("fiche_ouverte", lambda fiche: self.vus.append(fiche.titre))
''')
    return d


def test_extension_ajoute_puis_retire_menu_bouton_panneau(fen):
    _plugin_ui(fen)
    g = fen.plugins
    g.decouvrir()
    textes = lambda m: [a.text() for a in m.actions()]
    avant_menu, avant_barre = len(fen.menu_ext.actions()), len(fen.barre.actions())
    assert g.activer("demo")
    assert "Faire un truc" in textes(fen.menu_ext) and "Bouton" in textes(fen.barre)
    from PyQt6.QtWidgets import QDockWidget
    assert [d.windowTitle() for d in fen.findChildren(QDockWidget)] == ["Mon panneau"]
    fen.menu_ext.actions()[-1].trigger()
    assert g.actifs["demo"][0].vus[-1] == "action"
    fen._sel_fiche(1)    # ouvre une autre fiche : l'événement arrive à l'extension
    assert g.actifs["demo"][0].vus[-1] != "action"
    g.desactiver("demo")
    assert len(fen.menu_ext.actions()) == avant_menu and len(fen.barre.actions()) == avant_barre
    assert not [d for d in fen.dockWidgetArea.__self__.findChildren(QDockWidget) if d.isVisibleTo(fen)]


def test_dialogue_extensions_liste_et_active(fen, monkeypatch):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QMessageBox
    from scrinium.ui.extensions import DialogueExtensions
    _plugin_ui(fen)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    d = DialogueExtensions(fen)
    assert d.liste.count() == 1 and "Demo" in d.liste.item(0).text()
    d.liste.item(0).setCheckState(Qt.CheckState.Checked)
    assert "demo" in fen.plugins.actifs and fen.plugins.actifs_reglage() == ["demo"]
    d.liste.item(0).setCheckState(Qt.CheckState.Unchecked)
    assert "demo" not in fen.plugins.actifs


def test_extension_exemple_du_depot(fen):
    from pathlib import Path
    import shutil
    src = Path(__file__).resolve().parent.parent / "plugins" / "hello"
    shutil.copytree(src, fen.store.paths.base / "plugins" / "hello")
    fen.plugins.decouvrir()
    assert fen.plugins.activer("hello")
    fen.plugins.actifs["hello"][1].ui.notifier = lambda t, m: None   # pas de notification réelle en test
    fen.plugins.actifs["hello"][0].compter()


def test_inserer_texte_dans_la_note(fen):
    from scrinium.ui.extensions import UiPlugin
    ui = UiPlugin(fen, "x")
    fen.texte.setPlainText("début fin")
    c = fen.texte.textCursor(); c.setPosition(6); fen.texte.setTextCursor(c)
    assert ui.inserer_texte("[dicté] ") and fen.texte.toPlainText() == "début [dicté] fin"
    fen.texte.selectAll()
    assert ui.texte_selectionne() == "début [dicté] fin"
    # fiche verrouillée fermée : refusé
    fen.texte.setEnabled(False)
    assert not ui.inserer_texte("non") and ui.texte_selectionne() == ""


def test_dialogue_extensions_montre_les_extensions_fournies(fen, tmp_path, monkeypatch):
    import json
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QMessageBox
    from scrinium.ui.extensions import DialogueExtensions
    d = tmp_path / "officielles" / "demo"
    d.mkdir(parents=True)
    (d / "plugin.json").write_text(json.dumps({"titre": "Démo fournie", "version": "3", "description": "livrée avec Scrinium", "auteur": "Scrinium", "classe": "P", "api": 1}))
    (d / "__init__.py").write_text("from scrinium.core.plugins import Plugin\nclass P(Plugin): api = 1\n")
    fen.plugins.officiels = [tmp_path / "officielles"]
    dlg = DialogueExtensions(fen)
    assert dlg.liste.count() == 1 and "Démo fournie" in dlg.liste.item(0).text()
    assert dlg.liste.item(0).checkState() == Qt.CheckState.Unchecked                                  # désactivée par défaut
    assert "Fournie avec Scrinium" in dlg.detail.text() and "livrée avec Scrinium" in dlg.detail.text()
    demandes = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: demandes.append(a[2]) or QMessageBox.StandardButton.No)
    dlg.liste.item(0).setCheckState(Qt.CheckState.Checked)                                             # l'activer demande l'accord (avertissement « code arbitraire »)
    assert demandes and "Démo fournie" in demandes[0] and "demo" not in fen.plugins.actifs
    assert dlg.liste.item(0).checkState() == Qt.CheckState.Unchecked                                   # refusé : elle reste désactivée

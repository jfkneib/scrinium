# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension « Applications » : logique (commande sans shell, fichiers .desktop) et panneau dans la vraie fenêtre."""
import importlib.util
import os
import shutil
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication  # noqa: E402

from scrinium.core.paths import Paths  # noqa: E402
from scrinium.core.store import Store  # noqa: E402
from scrinium.ui.fenetre import Fenetre  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent / "plugins" / "applications"
_spec = importlib.util.spec_from_file_location("applications_logique", RACINE / "logique.py")
lg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lg)


def test_normaliser():
    assert lg.normaliser({"nom": "  Kate  ", "commande": " kate "})["nom"] == "Kate"
    assert lg.normaliser({"nom": "", "commande": "x"}) is None and lg.normaliser({"nom": "x", "commande": " "}) is None
    assert lg.normaliser("pas un dict") is None and lg.normaliser_liste("pas une liste") == []
    assert len(lg.normaliser_liste([{"nom": str(i), "commande": "x"} for i in range(500)])) == lg.MAX_APPLICATIONS


def test_commande_sans_shell_pas_d_injection():
    argv = lg.construire("kwrite --title 'a b' {selection}", "x; rm -rf ~ && $(id)", "T")
    assert argv == ["kwrite", "--title", "a b", "x; rm -rf ~ && $(id)"]        # la sélection reste UN argument
    assert lg.construire("mail -s {fiche}", "", "Mon titre") == ["mail", "-s", "Mon titre"]
    assert lg.construire("firefox", "ignorée", "T") == ["firefox"]
    with pytest.raises(ValueError):
        lg.construire("   ")
    with pytest.raises(ValueError):
        lg.construire("kwrite 'non fermé")
    assert lg.utilise_selection("a {selection}") and not lg.utilise_selection("a {fiche}")


def test_exemples_seulement_si_installes(monkeypatch):
    monkeypatch.setattr(lg.shutil, "which", lambda n: "/usr/bin/" + n if n in ("kwrite", "libreoffice") else None)
    assert [a["nom"] for a in lg.exemples_installes()] == ["KWrite", "LibreOffice Writer"]
    assert lg.installee("libreoffice --writer") and not lg.installee("introuvable") and not lg.installee("")


def test_lire_desktop(tmp_path):
    f = tmp_path / "a.desktop"
    f.write_text("[Desktop Entry]\nType=Application\nName=Éditeur\nName[fr]=Éditeur FR\nComment=Texte\nExec=editeur --nouveau %U %f\n"
                 "Icon=editeur\n[Desktop Action x]\nName=Autre\nExec=ailleurs\n")
    a = lg.lire_desktop(f, "fr")
    assert a == {"nom": "Éditeur FR", "icone": "editeur", "commande": "editeur --nouveau", "description": "Texte"}
    assert lg.lire_desktop(f, "")["nom"] == "Éditeur"
    for contenu in ("[Desktop Entry]\nType=Application\nName=X\nExec=x\nNoDisplay=true\n",
                    "[Desktop Entry]\nType=Link\nName=X\nExec=x\n", "[Desktop Entry]\nType=Application\nName=X\n"):
        g = tmp_path / "b.desktop"
        g.write_text(contenu)
        assert lg.lire_desktop(g) is None
    assert lg.lire_desktop(tmp_path / "absent.desktop") is None


def test_applications_installees_triees_sans_doublon(tmp_path, monkeypatch):
    d = tmp_path / "applications"
    d.mkdir()
    for nom, exe in (("Zeta", "zeta"), ("Alpha", "alpha"), ("Alpha2", "alpha")):
        (d / f"{nom}.desktop").write_text(f"[Desktop Entry]\nType=Application\nName={nom}\nExec={exe}\n")
    monkeypatch.setattr(lg, "dossiers_desktop", lambda: [d])
    assert [a["nom"] for a in lg.applications_installees()] == ["Alpha", "Zeta"]


def test_export_import():
    texte = lg.exporter([{"nom": "A", "commande": "a"}, {"nom": "", "commande": "x"}])
    assert lg.importer(texte) == [{"nom": "A", "icone": "", "commande": "a", "description": ""}]
    for mauvais in ("pas du json", '{"autre": 1}', '[1,2]'):
        with pytest.raises(ValueError):
            lg.importer(mauvais)


def test_lancer_detache(monkeypatch):
    appels = []
    monkeypatch.setattr(lg.subprocess, "Popen", lambda argv, **kw: appels.append((argv, kw)))
    lg.lancer(["kwrite", "x"])
    assert appels[0][0] == ["kwrite", "x"] and appels[0][1].get("start_new_session") is True
    with pytest.raises(OSError):
        monkeypatch.undo()
        lg.lancer(["commande-qui-n-existe-pas-xyz"])


# ---------- dans la fenêtre ----------
@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def fen(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/" + n if n in ("kwrite", "thunderbird") else None)
    s = Store(Paths(tmp_path / "am"))
    s.sauver_reglages(recovery_asked=True)
    shutil.copytree(RACINE, s.paths.base / "plugins" / "applications")
    w = Fenetre(s)
    w.plugins.decouvrir()
    assert w.plugins.activer("applications"), w.plugins.infos["applications"].erreur
    w.nouvelle_fiche()
    w.titre.setText("Notes")
    w.texte.setPlainText("du texte à passer")
    w.sauver()
    monkeypatch.setattr(QApplication, "activeWindow", staticmethod(lambda: None))
    yield w
    w.quitter_vraiment = True
    w.close()


def plugin(fen):
    return fen.plugins.actifs["applications"][0]


@pytest.fixture
def lances(monkeypatch):
    res = []
    monkeypatch.setattr(sys.modules["scrinium_plugin_applications"].logique, "lancer", lambda argv: res.append(argv))
    return res


def test_panneau_montre_les_exemples_installes_et_lance_au_clic(fen, lances):
    p = plugin(fen)
    noms = [p.panneau.liste.item(i).text() for i in range(p.panneau.liste.count())]
    assert noms == ["Thunderbird", "KWrite"] and p.dock.windowTitle() == "Applications"
    p.panneau._clic(p.panneau.liste.item(0))
    assert lances == [["thunderbird"]]


def test_selection_et_titre_passes_en_arguments(fen, lances):
    p = plugin(fen)
    fen.texte.selectAll()
    p.lancer({"nom": "K", "icone": "", "commande": "kwrite --caption {fiche} {selection}", "description": ""})
    assert lances == [["kwrite", "--caption", "Notes", "du texte à passer"]]


def test_selection_manquante_et_fiche_verrouillee_refusees(fen, lances):
    p = plugin(fen)
    notes = []
    p.ctx.ui.notifier = lambda t, m: notes.append(m)
    a = {"nom": "K", "icone": "", "commande": "kwrite {selection}", "description": ""}
    fen.texte.moveCursor(fen.texte.textCursor().MoveOperation.Start)
    p.lancer(a)
    assert lances == [] and "Sélectionnez" in notes[-1]
    demo = next(f for t in fen.store.themes for f in t.fiches if f.verrou)
    fen.store.deverrouiller(demo, "scrinium")
    th = next(t for t in fen.store.themes if demo in t.fiches)
    fen._afficher(th, demo)
    fen.texte.selectAll()
    p.lancer(a)
    assert lances == [] and "verrouillée" in notes[-1]
    p.lancer({"nom": "T", "icone": "", "commande": "thunderbird", "description": ""})      # sans {selection} : permis
    assert lances == [["thunderbird"]]


def test_liste_enregistree_remplace_les_exemples(fen):
    p = plugin(fen)
    p.sauver([{"nom": "Seule", "commande": "seule"}])
    assert [a["nom"] for a in p.applications()] == ["Seule"] and p.panneau.liste.count() == 1
    p.sauver([])
    assert p.applications() == [] and p.panneau.liste.count() == 0                  # une liste vide reste vide


def test_dialogues_se_construisent(fen):
    m = sys.modules["scrinium_plugin_applications"]
    p = plugin(fen)
    d = m.DialogueApplications(p)
    assert d.liste.count() == 2
    ch = m.DialogueChoix(None, apps=[{"nom": "Alpha", "icone": "", "commande": "alpha", "description": ""},
                                     {"nom": "Beta", "icone": "", "commande": "beta", "description": ""}])
    ch.filtre.setText("bet")
    assert [ch.liste.item(i).isHidden() for i in range(2)] == [True, False]
    da = m.DialogueApplication({"nom": "X", "icone": "", "commande": "x", "description": ""})
    assert da.resultat()["commande"] == "x"

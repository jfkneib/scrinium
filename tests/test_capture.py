# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""`scrinium ajouter` : texte reçu par un tube vers une fiche (écriture directe, ou par l'instance déjà ouverte)."""
import io
import os
import threading

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from scrinium import cli  # noqa: E402
from scrinium.core import capture  # noqa: E402
from scrinium.core.paths import Paths  # noqa: E402
from scrinium.core.store import Store  # noqa: E402


@pytest.fixture
def store(tmp_path):
    s = Store(Paths(tmp_path / "am"))
    s.charger()
    s.nouveau_theme("Capture")
    return s


# ---------- logique ----------
def test_bloc():
    b = capture.bloc("eth0: UP\r\nlo: UNKNOWN\n\n", "ip a", horodatage="2026-10-20 14:03")
    assert b == "### 2026-10-20 14:03 — ip a\n```\neth0: UP\nlo: UNKNOWN\n```\n"
    assert capture.bloc("x", brut=True) == "x\n"
    assert capture.bloc("sans commande", horodatage="D").startswith("### D\n```\n")
    avec = capture.bloc("a\n```\nb\n```\n````\nc", "cmd", horodatage="D")          # le texte contient des barrières
    assert avec.splitlines()[1] == "`````" and avec.rstrip().endswith("`````")


def test_tronquer():
    gros = "é" * capture.TAILLE_MAX
    t = capture.tronquer(gros)
    assert len(t.encode("utf-8")) <= capture.TAILLE_MAX + len(capture.MARQUE.encode()) and t.endswith("[… tronqué]")
    assert capture.tronquer("court") == "court"


def test_creation_puis_ajout_puis_remplacement(store):
    th, f = capture.ajouter(store, "Capture", "Réseau", "ip 1", "ip a", horodatage="J1")
    assert f.titre == "Réseau" and f.path.exists() and "### J1 — ip a" in f.texte
    capture.ajouter(store, "capture", "réseau", "ip 2", "ip a", horodatage="J2")      # casse ignorée
    f2 = store.theme("Capture").fiches[0]
    assert len(store.theme("Capture").fiches) == 1
    assert f2.texte.index("ip 1") < f2.texte.index("ip 2") and f2.texte.count("###") == 2
    capture.ajouter(store, "Capture", "Réseau", "seul", remplacer=True, brut=True)
    assert store.theme("Capture").fiches[0].texte == "seul\n"
    relu = Store(store.paths)
    relu.charger()
    assert relu.theme("Capture").fiches[0].texte == "seul\n"


def test_erreurs(store):
    with pytest.raises(ValueError, match="thème introuvable"):
        capture.ajouter(store, "Inexistant", "x", "t")
    with pytest.raises(ValueError, match="titre"):
        capture.ajouter(store, "Capture", "  ", "t")


def test_fiche_verrouillee(store):
    th, f = capture.ajouter(store, "Capture", "Secret", "x", brut=True)
    store.verrouiller(th, f, "mdp", sans_secours=True)
    f.texte = f.cle = f.salt = None                                          # fermée : refus, rien n'est écrit en clair
    with pytest.raises(ValueError, match="verrouillée"):
        capture.ajouter(store, "Capture", "Secret", "ajout")
    assert not list(th.path.glob("*.md")) and b"ajout" not in f.path.read_bytes()
    store.deverrouiller(f, "mdp")                                            # ouverte (cas de la fenêtre) : ajout chiffré
    capture.ajouter(store, "Capture", "Secret", "ajout", brut=True)
    assert b"ajout" not in f.path.read_bytes() and f.texte.endswith("ajout\n") and f.path.suffix == ".lock"


# ---------- ligne de commande (écriture directe) ----------
class Entree(io.TextIOWrapper):
    def __init__(self, texte, tty=False):
        super().__init__(io.BytesIO(texte.encode("utf-8")), encoding="utf-8")
        self._tty = tty

    def isatty(self):
        return self._tty


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("SCRINIUM_HOME", str(tmp_path / "h"))
    monkeypatch.setenv("SCRINIUM_LANG", "fr")
    monkeypatch.setenv("SCRINIUM_INSTANCE", f"scrinium-test-cli-{os.getpid()}")   # aucune instance ne l'écoute
    s = Store(Paths())
    s.charger()
    s.nouveau_theme("Capture")
    return s


def test_cli_ecriture_directe(env, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", Entree("lo UP\n"))
    assert cli.main(["ajouter", "-t", "Capture", "-f", "Réseau", "-c", "ip a"]) == 0
    assert "Ajouté" in capsys.readouterr().err
    s = Store(Paths())
    s.charger()
    f = next(x for x in s.theme("Capture").fiches if x.titre == "Réseau")
    assert "lo UP" in f.texte and "— ip a" in f.texte


def test_cli_sans_tube_et_erreurs(env, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", Entree("", tty=True))
    assert cli.main(["add", "-t", "Capture", "-f", "X"]) == 2 and "tube" in capsys.readouterr().err
    monkeypatch.setattr("sys.stdin", Entree("  \n"))
    assert cli.main(["add", "-t", "Capture", "-f", "Vide"]) == 2 and "vide" in capsys.readouterr().err   # pas de fiche vide
    s = Store(Paths())
    s.charger()
    assert not any(x.titre == "Vide" for x in s.theme("Capture").fiches)
    monkeypatch.setattr("sys.stdin", Entree("t"))
    assert cli.main(["add", "-t", "Nulle part", "-f", "X"]) == 1 and "introuvable" in capsys.readouterr().err
    monkeypatch.setattr("sys.stdin", Entree("t"))
    with pytest.raises(SystemExit):                                           # --theme et --fiche sont obligatoires
        cli.main(["add", "-f", "X"])


# ---------- canal de l'instance et fenêtre ----------
pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication  # noqa: E402

from scrinium.ui import instance  # noqa: E402
from scrinium.ui.fenetre import Fenetre  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def en_fil(app, fn):
    """Exécute fn dans un fil (client bloquant) pendant que la boucle Qt de ce fil-ci sert le canal."""
    res = []
    t = threading.Thread(target=lambda: res.append(fn()), daemon=True)
    t.start()
    while t.is_alive():
        app.processEvents()
        t.join(0.01)
    return res[0]


def test_canal_ajout_ok_erreur_et_gros_message(app, monkeypatch):
    monkeypatch.setenv("SCRINIUM_INSTANCE", f"scrinium-test-canal-{os.getpid()}")
    srv = instance.Serveur()
    recus = []
    srv.ajout = lambda p: recus.append(p) or ("" if p["fiche"] != "mauvaise" else "fiche refusée")
    assert en_fil(app, lambda: instance.envoyer_ajout({"fiche": "ok", "texte": "é" * 300000})) == (True, "")
    assert recus[0]["texte"] == "é" * 300000                                  # message plus gros qu'un paquet : reçu en entier
    assert en_fil(app, lambda: instance.envoyer_ajout({"fiche": "mauvaise"})) == (False, "fiche refusée")
    srv.ajout = None
    assert en_fil(app, lambda: instance.envoyer_ajout({"fiche": "x"}))[0] is False


def test_canal_sans_instance(app, monkeypatch):
    monkeypatch.setenv("SCRINIUM_INSTANCE", f"scrinium-test-vide-{os.getpid()}")
    assert instance.envoyer_ajout({"fiche": "x"}) is None


def test_noms_de_canal_distincts(monkeypatch):
    monkeypatch.delenv("SCRINIUM_INSTANCE", raising=False)
    monkeypatch.delenv("SCRINIUM_HOME", raising=False)
    base = instance.nom()
    monkeypatch.setenv("SCRINIUM_HOME", "/tmp/a")
    a = instance.nom()
    monkeypatch.setenv("SCRINIUM_HOME", "/tmp/b")
    assert len({base, a, instance.nom()}) == 3                                 # un autre dossier de données = un autre canal


def test_cli_via_la_fenetre_ouverte(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("SCRINIUM_HOME", str(tmp_path / "h"))
    monkeypatch.setenv("SCRINIUM_LANG", "fr")
    monkeypatch.setenv("SCRINIUM_INSTANCE", f"scrinium-test-fen-{os.getpid()}")
    s = Store(Paths())
    s.sauver_reglages(recovery_asked=True)
    w = Fenetre(s)
    srv = instance.Serveur(w)
    srv.ajout = w.ajouter_depuis_cli
    w.nouveau_theme = lambda: None
    s.nouveau_theme("Capture")
    w.maj_themes()
    w.theme = "Capture"
    w.maj_fiches()
    w.nouvelle_fiche()
    w.titre.setText("Réseau")
    w.texte.setPlainText("note existante")
    w.sauver()
    monkeypatch.setattr("sys.stdin", Entree("lo UP\n"))
    code = en_fil(app, lambda: cli.main(["ajouter", "-t", "Capture", "-f", "Réseau", "-c", "ip a"]))
    assert code == 0
    assert "note existante" in w.texte.toPlainText() and "lo UP" in w.texte.toPlainText()     # visible dans l'éditeur ouvert
    relu = Store(Paths())
    relu.charger()
    assert "lo UP" in next(x for x in relu.theme("Capture").fiches if x.titre == "Réseau").texte       # et sur le disque
    monkeypatch.setattr("sys.stdin", Entree("t"))
    assert en_fil(app, lambda: cli.main(["ajouter", "-t", "Nulle part", "-f", "X"])) == 1
    w.quitter_vraiment = True
    w.close()

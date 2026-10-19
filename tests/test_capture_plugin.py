# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension « Capture et console » : exécution de commandes, envoi vers Konsole (faux qdbus), repli presse-papiers."""
import importlib.util
import os
import shutil
import stat
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication  # noqa: E402

from scrinium.core.paths import Paths  # noqa: E402
from scrinium.core.store import Store  # noqa: E402
from scrinium.ui.fenetre import Fenetre  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent / "plugins" / "capture"
_spec = importlib.util.spec_from_file_location("capture_logique", RACINE / "logique.py")
lg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lg)

FAUX_QDBUS = '''#!/usr/bin/env python3
import os, sys
a = sys.argv[1:]
d = os.environ["FAUX_DIR"]
sessions = [l.split() for l in open(d + "/sessions").read().splitlines() if l.strip()]   # "service numero titre"
if not a:
    print("\\n".join(" " + s for s in sorted({x[0] for x in sessions})))
elif len(a) == 1:
    print("/\\n/Sessions\\n" + "\\n".join("/Sessions/%s" % x[1] for x in sessions if x[0] == a[0]) + "\\n/Windows")
else:
    svc, obj, meth = a[0], a[1], a[2]
    n = obj.rsplit("/", 1)[1]
    if meth.endswith(".title"):
        print(next(x[2] for x in sessions if x[0] == svc and x[1] == n))
    elif meth.endswith(".foregroundProcessId"):
        print(os.environ["FAUX_PID"])
    elif meth.endswith(".sendText"):
        if os.path.exists(d + "/refus"):
            sys.stderr.write("Error: org.freedesktop.DBus.Error.AccessDenied\\n")
            sys.exit(2)
        open(d + "/envois", "a").write(repr((svc, n, a[3])) + "\\n")
'''


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


# ---------- logique ----------
def test_nettoyer_pour_console():
    assert lg.nettoyer_pour_console("ls -la\r\nps\n\n") == "ls -la\nps"
    sale = "echo a\x1b[201~; rm -rf ~\x03\x07\x00\x7f\x9b tab\there"
    propre = lg.nettoyer_pour_console(sale)
    assert "\x1b" not in propre and "\x03" not in propre and "\x7f" not in propre and "\t" in propre
    assert propre.startswith("echo a[201~; rm")                      # plus de séquence d'échappement : texte inerte
    assert lg.nettoyer_pour_console("a\u2028b") == "a\nb"


def test_charge_utile_collage_seulement_si_plusieurs_lignes():
    assert lg.charge_utile("une seule ligne") == "une seule ligne"
    assert lg.charge_utile("a\nb") == "\x1b[200~a\nb\x1b[201~"


def test_executer():
    code, sortie, tronque, depasse = lg.executer("echo bonjour; echo erreur >&2; exit 3")
    assert (code, tronque, depasse) == (3, False, False) and "bonjour" in sortie and "erreur" in sortie
    code, sortie, tronque, depasse = lg.executer("echo début; sleep 5", delai=1)
    assert depasse and code is None
    code, sortie, tronque, depasse = lg.executer("head -c 5000 /dev/zero | tr '\\0' x", taille_max=100)
    assert tronque and len(sortie) == 100
    assert lg.executer("cat")[1] == ""                                     # l'entrée standard est fermée : jamais d'attente


@pytest.fixture
def faux(tmp_path, monkeypatch):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    q = bin_ / "qdbus6"
    q.write_text(FAUX_QDBUS)
    q.chmod(q.stat().st_mode | stat.S_IEXEC)
    d = tmp_path / "faux"
    d.mkdir()
    (d / "sessions").write_text("org.kde.konsole-111 1 claude : bash\n")
    monkeypatch.setenv("FAUX_DIR", str(d))
    monkeypatch.setenv("FAUX_PID", str(os.getpid()))
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    return d


def envois(d):
    f = d / "envois"
    return [eval(x) for x in f.read_text().splitlines()] if f.exists() else []


def test_sessions_et_envoi(faux):
    (faux / "sessions").write_text("org.kde.konsole-111 1 admin\norg.kde.konsole-111 2 build\norg.kde.konsole-222 1 ssh\n")
    q = lg.trouver_qdbus()
    s = lg.sessions_konsole(q)
    assert [(x[0], x[1]) for x in s] == [("org.kde.konsole-111", 1), ("org.kde.konsole-111", 2), ("org.kde.konsole-222", 1)]
    assert s[0][2].startswith("admin — ") and "[" in s[0][2]                  # titre, dossier courant, programme
    lg.envoyer(q, "org.kde.konsole-111", 2, "echo un")
    lg.envoyer(q, "org.kde.konsole-222", 1, "a\nb")
    assert envois(faux) == [("org.kde.konsole-111", "2", "echo un"), ("org.kde.konsole-222", "1", "\x1b[200~a\nb\x1b[201~")]
    (faux / "refus").write_text("")
    with pytest.raises(lg.AccesRefuse):
        lg.envoyer(q, "org.kde.konsole-111", 1, "x")


# ---------- dans la fenêtre ----------
@pytest.fixture
def fen(app, tmp_path, monkeypatch, faux):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    s = Store(Paths(tmp_path / "am"))
    s.sauver_reglages(recovery_asked=True)
    shutil.copytree(RACINE, s.paths.base / "plugins" / "capture")
    w = Fenetre(s)
    w.plugins.decouvrir()
    assert w.plugins.activer("capture"), w.plugins.infos["capture"].erreur
    w.nouvelle_fiche()
    w.titre.setText("Notes")
    w.texte.setPlainText("ls -la\nps aux")
    w.sauver()
    monkeypatch.setattr(QApplication, "activeWindow", staticmethod(lambda: None))
    yield w
    w.quitter_vraiment = True
    w.close()


def plugin(fen):
    return fen.plugins.actifs["capture"][0]


def mod():
    return sys.modules["scrinium_plugin_capture"]


def selectionner(fen, texte=None):
    if texte is not None:
        fen.texte.setPlainText(texte)
    fen.texte.selectAll()


def test_sans_selection_rien_ne_part(fen, faux):
    fen.texte.moveCursor(fen.texte.textCursor().MoveOperation.Start)
    plugin(fen).vers_console()
    assert envois(faux) == []


def test_une_seule_console_envoi_direct_sans_valider(fen, faux):
    selectionner(fen)
    plugin(fen).vers_console()
    assert envois(faux) == [("org.kde.konsole-111", "1", "\x1b[200~ls -la\nps aux\x1b[201~")]    # multi-ligne : collage, pas d'exécution
    selectionner(fen, "ip a")
    plugin(fen).vers_console()
    assert envois(faux)[-1][2] == "ip a"                                                          # jamais de retour à la ligne final


def test_acces_refuse_copie_dans_le_presse_papiers_et_explique_une_fois(fen, faux, monkeypatch):
    (faux / "refus").write_text("")
    infos = []
    monkeypatch.setattr(mod().QMessageBox, "information", lambda *a, **k: infos.append(a[2]))
    selectionner(fen, "uname -a")
    plugin(fen).vers_console()
    assert QApplication.clipboard().text() == "uname -a" and len(infos) == 1 and "DBus" in infos[0]
    plugin(fen).vers_console()
    assert len(infos) == 1                                              # l'explication n'est donnée qu'une fois


def test_sans_qdbus_ou_sans_console_presse_papiers(fen, faux, monkeypatch):
    selectionner(fen, "date")
    (faux / "sessions").write_text("")
    plugin(fen).vers_console()
    assert QApplication.clipboard().text() == "date"
    QApplication.clipboard().setText("")
    (faux / "sessions").write_text("org.kde.konsole-111 1 x\n")
    monkeypatch.setattr(mod().logique, "trouver_qdbus", lambda: None)
    plugin(fen).vers_console()
    assert QApplication.clipboard().text() == "date" and envois(faux) == []


def test_option_directe_desactivee(fen, faux):
    fen.plugins.actifs["capture"][1].reglages.set("direct", False)
    selectionner(fen, "df -h")
    plugin(fen).vers_console()
    assert envois(faux) == [] and QApplication.clipboard().text() == "df -h"


def test_plusieurs_consoles_choix_memorise_puis_oublie_si_disparue(fen, faux, monkeypatch):
    (faux / "sessions").write_text("org.kde.konsole-111 1 admin\norg.kde.konsole-222 1 build\n")
    questions = []

    def choisir(parent, titre, texte, libelles, defaut, editable):
        questions.append(libelles)
        return libelles[1], True
    monkeypatch.setattr(mod().QInputDialog, "getItem", staticmethod(choisir))
    selectionner(fen, "make")
    plugin(fen).vers_console()
    assert len(questions) == 1 and "build" in questions[0][1] and envois(faux)[-1][:2] == ("org.kde.konsole-222", "1")
    plugin(fen).vers_console()
    assert len(questions) == 1 and len(envois(faux)) == 2                                   # même console : on ne redemande pas
    (faux / "sessions").write_text("org.kde.konsole-111 1 admin\norg.kde.konsole-333 1 autre\n")   # la cible a disparu
    plugin(fen).vers_console()
    assert len(questions) == 2


def test_annuler_le_choix_n_envoie_ni_ne_copie_rien(fen, faux, monkeypatch):
    (faux / "sessions").write_text("org.kde.konsole-111 1 a\norg.kde.konsole-222 1 b\n")
    monkeypatch.setattr(mod().QInputDialog, "getItem", staticmethod(lambda *a, **k: ("", False)))
    QApplication.clipboard().setText("avant")
    selectionner(fen, "rm x")
    plugin(fen).vers_console()
    assert envois(faux) == [] and QApplication.clipboard().text() == "avant"


def test_choisir_la_console_cible(fen, faux, monkeypatch):
    (faux / "sessions").write_text("org.kde.konsole-111 1 a\norg.kde.konsole-222 1 b\n")
    monkeypatch.setattr(mod().QInputDialog, "getItem", staticmethod(lambda p, t, m, libelles, d, e: (libelles[1], True)))
    plugin(fen).choisir_cible()
    assert plugin(fen).cible == ("org.kde.konsole-222", 1)
    selectionner(fen, "echo ok")
    plugin(fen).vers_console()
    assert envois(faux)[-1][:2] == ("org.kde.konsole-222", "1")


def test_dialogue_commande_insere_la_sortie(fen, app):
    selectionner(fen, "début")
    fen.texte.moveCursor(fen.texte.textCursor().MoveOperation.End)
    d = mod().DialogueCommande(plugin(fen))
    d.commande.setText("echo bonjour-capture")
    d._lancer()
    fin = time.time() + 8
    while d.resultat is None and time.time() < fin:
        app.processEvents()
        time.sleep(0.01)
    assert d.resultat and "bonjour-capture" in d.sortie.toPlainText() and d.b_inserer.isEnabled()
    d._inserer()
    assert "### " in fen.texte.toPlainText() and "— echo bonjour-capture" in fen.texte.toPlainText()
    assert "bonjour-capture\n```" in fen.texte.toPlainText()

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
elif a[0] == "org.kde.KWin":                      # gestionnaire de fenêtres : scripts de mise au premier plan
    if os.path.exists(d + "/sans_kwin"):
        print("Error: org.freedesktop.DBus.Error.ServiceUnknown")
        sys.exit(2)
    if a[2].endswith(".loadScript"):
        open(d + "/focus-script", "w").write(open(a[3]).read())
        print(7)
    elif a[2].endswith(".Script.run"):
        open(d + "/focus-lance", "a").write("1\\n")
    elif a[2].endswith(".unloadScript"):
        print("true")
else:
    svc, obj, meth = a[0], a[1], a[2]
    n = obj.rsplit("/", 1)[1]
    if meth.endswith(".title"):
        print(next(x[2] for x in sessions if x[0] == svc and x[1] == n))
    elif meth.endswith(".foregroundProcessId"):
        print(os.environ["FAUX_PID"])
    elif meth.endswith(".sendText"):
        if os.path.exists(d + "/refus"):
            print("Error: org.freedesktop.DBus.Error.AccessDenied")      # comme le vrai qdbus6 : sur la sortie standard
            print("L'API « D-Bus » de confidentialité pour la sécurité est désactivée dans la configuration.")
            sys.exit(2)
        open(d + "/envois", "a").write(repr((svc, n, a[3])) + "\\n")
'''


FAUX_KONSOLE = '''#!/usr/bin/env python3
import os, signal, sys, time
d = os.environ["FAUX_DIR"]
open(d + "/lancements", "a").write(" ".join(sys.argv[1:]) + "\\n")
ligne = "org.kde.konsole-%d 1 Scrinium\\n" % os.getpid()
open(d + "/sessions", "a").write(ligne)
def fin(*a):
    open(d + "/sessions", "w").write(open(d + "/sessions").read().replace(ligne, ""))
    sys.exit(0)
signal.signal(signal.SIGTERM, fin)
while True:
    time.sleep(0.1)
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
    k = bin_ / "konsole"
    k.write_text(FAUX_KONSOLE)
    k.chmod(k.stat().st_mode | stat.S_IEXEC)
    d = tmp_path / "faux"
    d.mkdir()
    (d / "sessions").write_text("org.kde.konsole-111 1 claude : bash\n")        # une console de l'utilisateur, déjà ouverte
    monkeypatch.setenv("FAUX_DIR", str(d))
    monkeypatch.setenv("FAUX_PID", str(os.getpid()))
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    yield d
    for ligne in (d / "sessions").read_text().splitlines():                       # ne laisse aucun faux Konsole derrière soi
        service = ligne.split()[0]
        if service != "org.kde.konsole-111" and service.rsplit("-", 1)[-1].isdigit():
            try:
                os.kill(int(service.rsplit("-", 1)[-1]), 15)
            except OSError:
                pass


def envois(d):
    f = d / "envois"
    tous = [eval(x) for x in f.read_text().splitlines()] if f.exists() else []
    return [e for e in tous if e[2] != ""]                      # un envoi de texte vide est une sonde, pas un envoi


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


def lancements(d):
    f = d / "lancements"
    return f.read_text().splitlines() if f.exists() else []


def pid_dedie(d):
    return next(int(x.split()[0].rsplit("-", 1)[-1]) for x in (d / "sessions").read_text().splitlines() if x.endswith("Scrinium"))


def test_ouvre_sa_propre_console_puis_la_reutilise(fen, faux):
    selectionner(fen)
    plugin(fen).vers_console()
    assert len(lancements(faux)) == 1 and "--separate" in lancements(faux)[0] and "tabtitle=Scrinium" in lancements(faux)[0]
    dedie = f"org.kde.konsole-{pid_dedie(faux)}"
    assert envois(faux) == [(dedie, "1", "\x1b[200~ls -la\nps aux\x1b[201~")]      # multi-ligne : collage, pas d'exécution
    assert all(e[0] != "org.kde.konsole-111" for e in envois(faux))                   # la console de l'utilisateur n'est pas touchée
    selectionner(fen, "ip a")
    plugin(fen).vers_console()
    assert len(lancements(faux)) == 1 and envois(faux)[-1] == (dedie, "1", "ip a")    # même console, pas de retour à la ligne final


def test_console_fermee_est_rouverte(fen, faux):
    selectionner(fen, "un")
    plugin(fen).vers_console()
    premier = pid_dedie(faux)
    os.kill(premier, 15)                                                               # l'utilisateur ferme la console
    fin = time.time() + 5
    while f"konsole-{premier}" in (faux / "sessions").read_text() and time.time() < fin:
        time.sleep(0.05)
    selectionner(fen, "deux")
    plugin(fen).vers_console()
    assert len(lancements(faux)) == 2 and pid_dedie(faux) != premier
    assert envois(faux)[-1] == (f"org.kde.konsole-{pid_dedie(faux)}", "1", "deux")


def test_console_retrouvee_apres_redemarrage_de_scrinium(fen, faux):
    selectionner(fen, "un")
    plugin(fen).vers_console()
    plugin(fen).pid_dedie = None                                                       # nouveau démarrage : seule la mémoire disque reste
    selectionner(fen, "deux")
    plugin(fen).vers_console()
    assert len(lancements(faux)) == 1 and envois(faux)[-1][2] == "deux"


def test_console_choisie_a_la_main_prioritaire_puis_retour_a_celle_de_l_extension(fen, faux, monkeypatch):
    monkeypatch.setattr(mod().QInputDialog, "getItem", staticmethod(lambda p, t, m, libelles, d, e: (libelles[0], True)))
    plugin(fen).choisir_cible()                                                        # « claude : bash » (n° 111)
    assert plugin(fen).cible == ("org.kde.konsole-111", 1)
    selectionner(fen, "echo ok")
    plugin(fen).vers_console()
    assert envois(faux)[-1][:2] == ("org.kde.konsole-111", "1") and lancements(faux) == []
    plugin(fen).oublier_cible()
    plugin(fen).vers_console()
    assert len(lancements(faux)) == 1 and envois(faux)[-1][0] != "org.kde.konsole-111"


def test_cible_disparue_retombe_sur_la_console_de_l_extension(fen, faux, monkeypatch):
    monkeypatch.setattr(mod().QInputDialog, "getItem", staticmethod(lambda p, t, m, libelles, d, e: (libelles[0], True)))
    plugin(fen).choisir_cible()
    (faux / "sessions").write_text("")                                                 # la console choisie est fermée
    selectionner(fen, "make")
    plugin(fen).vers_console()
    assert len(lancements(faux)) == 1 and envois(faux)[-1][0] != "org.kde.konsole-111"


def test_acces_refuse_copie_explique_une_fois_et_n_ouvre_pas_de_console_inutile(fen, faux, monkeypatch):
    (faux / "refus").write_text("")
    infos = []
    monkeypatch.setattr(mod().QMessageBox, "information", lambda *a, **k: infos.append(a[2]))
    selectionner(fen, "uname -a")
    plugin(fen).vers_console()
    assert QApplication.clipboard().text() == "uname -a" and len(infos) == 1 and "DBus" in infos[0]
    assert lancements(faux) == [] and envois(faux) == []                  # la sonde a suffi : aucune console ouverte pour rien
    selectionner(fen, "date")
    plugin(fen).vers_console()
    assert QApplication.clipboard().text() == "date" and len(infos) == 1 and lancements(faux) == []   # explication donnée une fois


def test_refus_avec_la_console_de_l_extension_deja_ouverte(fen, faux, monkeypatch):
    selectionner(fen, "un")
    plugin(fen).vers_console()                                            # autorisé : la console de l'extension s'ouvre
    assert len(lancements(faux)) == 1
    (faux / "refus").write_text("")                                       # l'option est ensuite désactivée dans Konsole
    monkeypatch.setattr(mod().QMessageBox, "information", lambda *a, **k: None)
    selectionner(fen, "deux")
    plugin(fen).vers_console()
    assert QApplication.clipboard().text() == "deux" and len(lancements(faux)) == 1


def test_refus_aucune_console_ouverte_ouvre_celle_de_l_extension_puis_n_insiste_pas(fen, faux, monkeypatch):
    (faux / "sessions").write_text("")                                    # aucune console ouverte : pas de sonde possible
    (faux / "refus").write_text("")
    monkeypatch.setattr(mod().QMessageBox, "information", lambda *a, **k: None)
    selectionner(fen, "un")
    plugin(fen).vers_console()
    assert len(lancements(faux)) == 1 and QApplication.clipboard().text() == "un"      # la console ouverte sert de sonde
    (faux / "sessions").write_text("")
    selectionner(fen, "deux")
    plugin(fen).vers_console()
    assert len(lancements(faux)) == 1 and QApplication.clipboard().text() == "deux"    # pas de seconde console pour rien


def test_reessayer_apres_les_reglages(fen, faux, monkeypatch):
    (faux / "refus").write_text("")
    monkeypatch.setattr(mod().QMessageBox, "information", lambda *a, **k: None)
    selectionner(fen, "un")
    plugin(fen).vers_console()
    assert plugin(fen).refus_vu and lancements(faux) == []
    (faux / "refus").unlink()                                             # l'utilisateur active l'option dans Konsole
    d = mod().DialogueReglages(plugin(fen))
    d._valider()                                                          # enregistrer les réglages remet le compteur à zéro
    selectionner(fen, "deux")
    plugin(fen).vers_console()
    assert len(lancements(faux)) == 1 and envois(faux)[-1][2] == "deux"


def test_logique_reconnait_le_refus_sur_stdout_comme_sur_stderr(faux, monkeypatch):
    q = lg.trouver_qdbus()
    (faux / "refus").write_text("")
    with pytest.raises(lg.AccesRefuse):
        lg.envoyer(q, "org.kde.konsole-111", 1, "x")                      # le faux qdbus écrit sur stdout, comme le vrai
    import subprocess as sp
    monkeypatch.setattr(lg, "_qdbus", lambda *a: sp.CompletedProcess(a, 2, b"", b"Error: org.freedesktop.DBus.Error.AccessDenied"))
    with pytest.raises(lg.AccesRefuse):
        lg.envoyer(q, "org.kde.konsole-111", 1, "x")                      # et sur stderr si une autre version le fait


def test_sans_konsole_ou_sans_qdbus_presse_papiers(fen, faux, monkeypatch):
    selectionner(fen, "date")
    monkeypatch.setattr(mod().logique, "lancer_konsole", lambda: None)                 # Konsole non installé
    plugin(fen).vers_console()
    assert QApplication.clipboard().text() == "date" and envois(faux) == []
    QApplication.clipboard().setText("")
    monkeypatch.setattr(mod().logique, "trouver_qdbus", lambda: None)
    plugin(fen).vers_console()
    assert QApplication.clipboard().text() == "date" and envois(faux) == []


def test_option_directe_desactivee(fen, faux):
    fen.plugins.actifs["capture"][1].reglages.set("direct", False)
    selectionner(fen, "df -h")
    plugin(fen).vers_console()
    assert envois(faux) == [] and QApplication.clipboard().text() == "df -h"


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


# ---------- mise au premier plan ----------
def test_script_premier_plan_cible_le_bon_processus(faux):
    q = lg.trouver_qdbus()
    assert lg.mettre_au_premier_plan(q, "org.kde.konsole-4242") is True
    js = (faux / "focus-script").read_text()
    assert "var pid = 4242;" in js and "workspace.activeWindow = w" in js and (faux / "focus-lance").exists()


def test_premier_plan_sans_kwin_ne_plante_pas(faux):
    (faux / "sans_kwin").write_text("")
    assert lg.mettre_au_premier_plan(lg.trouver_qdbus(), "org.kde.konsole-4242") is False
    assert lg.mettre_au_premier_plan(lg.trouver_qdbus(), "pas-un-service") is False


def test_console_au_premier_plan_apres_l_envoi(fen, faux):
    selectionner(fen, "ls")
    plugin(fen).vers_console()
    assert f"var pid = {pid_dedie(faux)};" in (faux / "focus-script").read_text()          # la console de l'extension est mise devant


def test_premier_plan_desactivable_et_absent_si_refus(fen, faux, monkeypatch):
    fen.plugins.actifs["capture"][1].reglages.set("premier_plan", False)
    selectionner(fen, "ls")
    plugin(fen).vers_console()
    assert envois(faux) and not (faux / "focus-script").exists()
    fen.plugins.actifs["capture"][1].reglages.set("premier_plan", True)
    (faux / "refus").write_text("")
    monkeypatch.setattr(mod().QMessageBox, "information", lambda *a, **k: None)
    plugin(fen).vers_console()                                                              # refus : rien à mettre devant
    assert not (faux / "focus-script").exists()

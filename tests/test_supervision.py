# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension « Supervision » : fiche, contrôles (sans réseau réel), sécurité des valeurs, vue dans la vraie fenêtre."""
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication  # noqa: E402

from scrinium.core.paths import Paths  # noqa: E402
from scrinium.core.store import Store  # noqa: E402
from scrinium.ui.fenetre import Fenetre  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent / "plugins" / "supervision"
_spec = importlib.util.spec_from_file_location("supervision_logique", RACINE / "logique.py")
lg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lg)

SORTIE = ("0.52 0.40 0.30 1/200 999\n12345.67 999\nMemTotal:       1000 kB\nMemAvailable:    250 kB\n"
          "Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/sda1 100 50 50 91% /\n")


def test_texte_aller_retour_et_valeurs_nettoyees():
    t = lg.en_texte([{"nom": " Serveur ", "adresse": "10.0.0.2", "ports": "22, 80 22 99999", "web": "http://10.0.0.2/",
                      "ssh": "root@10.0.0.2", "seuil_disque": 80}])
    assert t.startswith("#scrinium-supervision\n") and "ports: 22, 80\n" in t and "seuil_disque: 80" in t
    m = lg.depuis_texte(t)[0]
    assert m["nom"] == "Serveur" and m["ports"] == [22, 80] and m["seuil_disque"] == 80
    assert lg.depuis_texte("notes libres\n## Sans adresse\nports: 22") == []                 # pas d'adresse : écartée
    assert len(lg.normaliser_liste([{"nom": str(i), "adresse": "h"} for i in range(500)])) == lg.MAX_MACHINES


def test_valeurs_qui_ressemblent_a_des_options_sont_refusees():
    assert lg.normaliser({"nom": "x", "adresse": "-oProxyCommand=id"}) is None
    assert lg.normaliser({"nom": "x", "adresse": "a b"}) is None
    m = lg.normaliser({"nom": "x", "adresse": "h", "ssh": "-oProxyCommand=id", "web": "file:///etc/passwd"})
    assert m["ssh"] == "" and m["web"] == ""
    with pytest.raises(ValueError):
        lg.commande_ssh("-oProxyCommand=id")
    argv = lg.commande_ssh("root@h")
    assert argv[:3] == ["ssh", "-o", "BatchMode=yes"] and "--" in argv and argv.index("--") < argv.index("root@h")
    assert lg.page_web("file:///etc/passwd") is None and lg.ping("-c1") is False


def test_analyse_des_mesures():
    assert lg.analyser_mesures(SORTIE) == {"charge": 0.52, "uptime_s": 12345, "memoire_pct": 75, "disque_pct": 91}
    avec = lg.analyser_mesures(SORTIE + "4\n")
    assert avec["coeurs"] == 4 and lg.charge_pct(avec) == 13 and lg.charge_pct({"charge": 9.0, "coeurs": 4}) == 100
    assert lg.charge_pct({}) is None and lg.charge_pct({"charge": 0.5}) == 50
    assert lg.analyser_mesures("n'importe quoi") == {} and lg.analyser_mesures("") == {}
    assert lg.duree(90061) == "1 j 1 h" and lg.duree(3700) == "1 h 1 min"


def test_etat_ok_alerte_panne():
    m = lg.normaliser({"nom": "x", "adresse": "h", "ports": [22, 80], "web": "http://h/"})
    ok = {"ping": True, "ports": {22: True, 80: True}, "web": 200}
    assert lg.etat(m, ok) == ("ok", [])
    e, r = lg.etat(m, {**ok, "ports": {22: True, 80: False}})
    assert e == "alerte" and any("80" in x for x in r)
    assert lg.etat(m, {**ok, "web": 503})[0] == "alerte" and lg.etat(m, {**ok, "web": None})[0] == "alerte"
    assert lg.etat(m, {"ping": False, "ports": {22: False, 80: False}})[0] == "panne"
    assert lg.etat(m, {"ping": False, "ports": {22: True, 80: True}, "web": 200})[0] == "ok"      # le ping peut être filtré
    m2 = lg.normaliser({"nom": "x", "adresse": "h", "ssh": "u@h", "seuil_disque": 90})
    assert lg.etat(m2, {"ping": True, "ports": {}, "mesures": {"disque_pct": 95}})[0] == "alerte"
    assert lg.etat(m2, {"ping": True, "ports": {}, "erreur_ssh": "refusé"})[0] == "alerte"


def test_machine_locale_sans_ssh_donne_des_mesures(monkeypatch):
    monkeypatch.setattr(lg, "ping", lambda a, d=4: True)
    m = lg.normaliser({"nom": "ici", "adresse": "127.0.0.1"})
    mes = lg.sonder(m).get("mesures", {})
    if Path("/proc/meminfo").exists():
        assert {"charge", "uptime_s", "memoire_pct", "disque_pct"} <= set(mes)
    assert lg.est_locale("localhost") and not lg.est_locale("192.168.1.2")


def test_sonder_avec_ssh_simule(monkeypatch):
    monkeypatch.setattr(lg, "ping", lambda a, d=4: True)
    monkeypatch.setattr(lg, "port_ouvert", lambda a, p, d=4: p == 22)
    vus = []

    def faux_run(argv, **kw):
        vus.append(argv)
        return subprocess.CompletedProcess(argv, 0, SORTIE, "")
    monkeypatch.setattr(lg.subprocess, "run", faux_run)
    m = lg.normaliser({"nom": "x", "adresse": "h", "ports": [22, 80], "ssh": "u@h"})
    r = lg.sonder(m)
    assert r["ports"] == {22: True, 80: False} and r["mesures"]["disque_pct"] == 91 and vus[0][-2:] == ["u@h", lg.COMMANDE_SSH]
    monkeypatch.setattr(lg.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 255, "", "Permission denied\n"))
    assert "Permission denied" in lg.sonder(m)["erreur_ssh"]


# ---------- dans la vraie fenêtre ----------
@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def fen(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    s = Store(Paths(tmp_path / "am"))
    s.sauver_reglages(recovery_asked=True)
    shutil.copytree(RACINE, s.paths.base / "plugins" / "supervision")
    w = Fenetre(s)
    w.plugins.decouvrir()
    assert w.plugins.activer("supervision"), w.plugins.infos["supervision"].erreur
    yield w
    w.quitter_vraiment = True
    w.close()


def test_vue_et_alerte_sur_changement(fen, monkeypatch):
    vue = fen.vues_types["supervision"]
    p = fen.plugins.actifs["supervision"][0]
    assert vue.actif
    vue.charger(lg.en_texte([{"nom": "Srv", "adresse": "h", "ports": [22]}]))
    assert vue.table.rowCount() == 1
    notes = []
    monkeypatch.setattr(p.ctx.ui, "notifier", lambda t, m: notes.append(m))
    gen = vue._gen
    vue._arrive(gen, 0, {"ping": True, "ports": {22: True}})
    assert vue.table.item(0, 0).text().endswith("En ligne") and notes == []
    vue._arrive(gen, 0, {"ping": False, "ports": {22: False}})
    assert vue.table.item(0, 0).text().endswith("Panne") and len(notes) == 1 and "Srv" in notes[0]
    vue._arrive(gen, 0, {"ping": False, "ports": {22: False}})
    assert len(notes) == 1                                                            # pas de répétition tant que l'état ne change pas
    vue._arrive(gen - 1, 0, {"ping": True, "ports": {22: True}})                      # résultat périmé : ignoré
    assert vue.table.item(0, 0).text().endswith("Panne")


def test_fiche_non_validee_ne_controle_rien(fen, monkeypatch):
    vue = fen.vues_types["supervision"]
    lances = []
    monkeypatch.setattr(sys.modules["scrinium_plugin_supervision"].logique, "sonder", lambda m: lances.append(m) or {"ping": True, "ports": {}})
    vue.actif = False
    vue.charger(lg.en_texte([{"nom": "Srv", "adresse": "h"}]))
    vue.actualiser()
    assert lances == [] and vue.entrees_menu(vue.rect().center()) == []
    assert vue.table.rowCount() == 1                                                  # la liste reste lisible


def test_actualiser_utilise_le_fil_de_travail(fen, monkeypatch, app):
    vue = fen.vues_types["supervision"]
    monkeypatch.setattr(sys.modules["scrinium_plugin_supervision"].logique, "sonder", lambda m: {"ping": True, "ports": {}})
    vue.machines = lg.depuis_texte(lg.en_texte([{"nom": "A", "adresse": "h"}, {"nom": "B", "adresse": "h2"}]))
    vue._afficher()
    vue.actualiser()
    for _i in range(100):
        app.processEvents()
        if len(vue.resultats) == 2:
            break
        import time
        time.sleep(0.02)
    assert len(vue.resultats) == 2 and vue.b_actualiser.isEnabled() and vue.table.item(1, 0).text().endswith("En ligne")


def test_desactiver_retire_le_type(fen):
    from scrinium.core import types_fiche
    assert types_fiche.type_de("#scrinium-supervision\n") is not None
    fen.plugins.desactiver("supervision")
    assert "supervision" not in fen.vues_types


def test_couleurs_de_consommation_du_vert_au_rouge(fen):
    mod = sys.modules["scrinium_plugin_supervision"]
    assert mod.couleur_niveau(None) is None
    vert, jaune, rouge = (mod.couleur_niveau(x) for x in (0, 50, 100))
    assert vert.hue() == 120 and jaune.hue() == 60 and rouge.hue() == 0 and mod.couleur_niveau(250).hue() == 0
    vue = fen.vues_types["supervision"]
    vue.machines = lg.depuis_texte(lg.en_texte([{"nom": "A", "adresse": "h", "ssh": "u@h"}]))
    vue._afficher()
    vue._gen += 1
    vue._arrive(vue._gen, 0, {"ping": True, "ports": {}, "mesures": {"disque_pct": 95, "memoire_pct": 10, "charge": 1.0, "coeurs": 4}})
    assert vue.table.item(0, 3).background().color().hue() < 20 and vue.table.item(0, 4).background().color().hue() > 100


def test_puissance_estimee_et_dite_estimee(fen):
    assert lg.lire_watts("40-200") == (40, 200) and lg.lire_watts("40 200") == (40, 200)
    assert lg.lire_watts("200-40") is None and lg.lire_watts("abc") is None and lg.lire_watts("") is None
    m = lg.normaliser({"nom": "x", "adresse": "h", "watts": "40-200"})
    assert "watts: 40-200" in lg.en_texte([m]) and lg.depuis_texte(lg.en_texte([m]))[0]["watts"] == (40, 200)
    assert lg.puissance_estimee(m, {"charge": 2.0, "coeurs": 4}) == 120                 # 40 + 160 x 50 %
    assert lg.puissance_estimee(m, {}) is None and lg.puissance_estimee(lg.normaliser({"nom": "x", "adresse": "h"}), {"charge": 1.0}) is None
    vue = fen.vues_types["supervision"]
    vue.machines = [m]
    vue._afficher()
    vue._gen += 1
    vue._arrive(vue._gen, 0, {"ping": True, "ports": {}, "mesures": {"charge": 2.0, "coeurs": 4}})
    assert vue.table.item(0, 6).text() == "≈ 120 W"
    assert "ESTIMATION" in vue.table.item(0, 6).toolTip() and "2880 Wh" in vue.table.item(0, 6).toolTip()

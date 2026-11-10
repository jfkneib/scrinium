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


def _attendre(app, cond):
    import time
    for _i in range(150):
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_surveillance_en_arriere_plan_seulement_fiches_validees(fen, monkeypatch, app):
    p = fen.plugins.actifs["supervision"][0]
    mod = sys.modules["scrinium_plugin_supervision"].logique
    f = p.ctx.creer_fiche("Parc", "Mes machines", lg.en_texte([{"nom": "Srv", "adresse": "h"}]))
    th = fen.store.theme("Parc")
    assert p.machines_a_surveiller() == []                       # fiche reçue/créée par une extension : inerte, donc pas surveillée
    fen.store.valider_fiche(th, th.fiches[0])
    assert [m["nom"] for m in p.machines_a_surveiller()] == ["Srv"]
    notes = []
    monkeypatch.setattr(p.ctx.ui, "notifier", lambda t, m: notes.append(m))
    reponse = {"ping": True, "ports": {}}
    monkeypatch.setattr(mod, "sonder", lambda m: dict(reponse))
    p._tour()                                                    # case décochée : rien ne part
    app.processEvents()
    assert p.etats == {} and not p.fond
    p.regler_fond(True)
    assert p.ctx.reglages.get("fond") is True
    p._tour()
    assert _attendre(app, lambda: p.etats.get("Srv|h") == "ok") and notes == []
    reponse.update(ping=False)
    p._tour()
    assert _attendre(app, lambda: p.etats.get("Srv|h") == "panne") and len(notes) == 1 and "Srv" in notes[0]
    p._tour()
    assert _attendre(app, lambda: not p._en_cours) and len(notes) == 1               # pas de répétition
    fen.store.enregistrer(th, th.fiches[0], "Mes machines", lg.en_texte([{"nom": "Srv", "adresse": "h"}, {"nom": "Autre", "adresse": "h2"}]))
    assert p.machines_a_surveiller() == []                       # texte modifié : la validation tombe, plus de contrôle


def test_cumul_d_energie_estimee_pur():
    import time
    from datetime import datetime
    debut = datetime(2026, 11, 10).timestamp()
    assert lg.cumuler(None, "", 100, debut) is None and lg.cumuler(None, "pas une date", 100, debut) is None
    e = lg.cumuler(None, "2026-11-10", 100, debut + 3600)                       # premier contrôle : rien à compter encore
    assert e["wh"] == 0 and e["dernier"] == debut + 3600
    e = lg.cumuler(e, "2026-11-10", 100, debut + 3600 + 60)                     # 100 W pendant 60 s
    assert round(e["wh"], 3) == round(100 * 60 / 3600, 3) and e["secondes"] == 60
    e2 = lg.cumuler(e, "2026-11-10", 100, debut + 3600 + 60 + 3600)             # trou d'une heure : Scrinium fermé, non compté
    assert e2["wh"] == e["wh"] and e2["secondes"] == 60
    assert lg.cumuler(e, "2026-11-10", None, debut + 3600 + 120)["wh"] == e["wh"]    # pas de watts : rien ajouté
    assert lg.cumuler(e, "2026-11-11", 100, debut + 3600 + 120)["wh"] == 0           # autre date : remis à zéro
    futur = lg.cumuler(lg.cumuler(None, "2030-01-01", 100, debut), "2030-01-01", 100, debut + 60)
    assert futur["wh"] == 0                                                          # avant la date de mise en service : rien
    assert lg.formater_energie(850) == "850 Wh" and lg.formater_energie(12345) == "12.35 kWh"
    assert lg.lire_date("10/11/2026") == "2026-11-10" and lg.lire_date("2026-11-10") == "2026-11-10" and lg.lire_date("x") == ""
    m = lg.normaliser({"nom": "x", "adresse": "h", "watts": "40-200", "depuis": "10/11/2026"})
    assert "depuis: 2026-11-10" in lg.en_texte([m]) and lg.depuis_texte(lg.en_texte([m]))[0]["depuis"] == "2026-11-10"
    assert time.time() > 0


def test_cumul_seulement_en_suivi_continu_et_affiche(fen):
    p = fen.plugins.actifs["supervision"][0]
    m = lg.normaliser({"nom": "Srv", "adresse": "h", "watts": "100-100", "depuis": "2026-01-01"})
    r = {"ping": True, "ports": {}, "mesures": {"charge": 1.0, "coeurs": 1}}
    t0 = 1_800_000_000.0
    p.cumuler(m, r, t0)
    p.cumuler(m, r, t0 + 60)
    assert p.cumul_de(m) is None                                                     # suivi continu coché ? non : rien n'est compté
    p.regler_fond(True)
    p.cumuler(m, r, t0 + 120)
    p.cumuler(m, r, t0 + 180)
    assert round(p.cumul_de(m)["wh"], 2) == round(100 * 60 / 3600, 2)
    assert p.ctx.reglages.get("cumul")["Srv|h"]["secondes"] == 60                    # mémorisé sur cette machine
    vue = fen.vues_types["supervision"]
    vue.machines = [m]
    vue._afficher()
    vue._gen += 1
    vue._arrive(vue._gen, 0, r)
    item = vue.table.item(0, 7)
    assert item.text().endswith("Wh") and "ESTIMÉE" in item.toolTip() and "01/01/2026" in item.toolTip()
    assert vue.table.item(0, 6).text() == "≈ 100 W"

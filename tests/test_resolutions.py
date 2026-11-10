# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension « Résolutions » : fiche, taux, séries, note automatique, encouragements et vue dans la vraie fenêtre."""
import importlib.util
import os
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication, QCheckBox  # noqa: E402

from scrinium.core.paths import Paths  # noqa: E402
from scrinium.core.store import Store  # noqa: E402
from scrinium.ui.fenetre import Fenetre  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent / "plugins" / "resolutions"
_spec = importlib.util.spec_from_file_location("resolutions_logique", RACINE / "logique.py")
lg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lg)

AUJ = date(2026, 11, 11)                                                    # un mercredi


def jours(*decalages):
    return {(AUJ - timedelta(days=k)).isoformat() for k in decalages}


def quotidienne(faits, debut=30):
    return lg.Resolution("Marcher", 0, (AUJ - timedelta(days=debut)).isoformat(), "", faits)


def test_texte_aller_retour_et_tolerance():
    r = lg.Resolution("Lire", 3, "2026-11-01", "", {f"2026-11-{d:02d}" for d in range(1, 12)})
    t = lg.ecrire([r])
    assert t.startswith("#scrinium-resolutions\n\n## Lire\ncible: 3 par semaine\ndebut: 2026-11-01\nfait: 2026-11-01,")
    assert t.count("\nfait: ") == 2                                         # lignes courtes de 8 dates
    assert lg.lire(t)[0].faits == r.faits and lg.ecrire(lg.lire(t)) == t
    assert lg.lire_cible("3 fois par semaine") == 3 and lg.lire_cible("jour") == 0 and lg.lire_cible("9 par semaine") == 6 and lg.lire_cible("0 par semaine") == 0
    assert lg.lire("")  == [] and lg.lire("texte libre") == []
    x = lg.lire("## Eau\ncible: jour\nfait: 10/11/2026, n'importe quoi, 2026-11-09", AUJ)[0]
    assert x.faits == {"2026-11-10", "2026-11-09"} and x.debut == AUJ.isoformat()
    assert lg.lire("## \n## Ok")[0].nom == "Ok"


def test_taux_chaque_jour_et_jour_en_cours_non_compte():
    r = quotidienne(jours(1, 2, 3, 4, 5, 6, 7))                              # 7 jours faits, aujourd'hui pas encore coché
    assert lg.taux(r, AUJ) == 7 / 13                                       # 13 jours comptés (14 moins aujourd'hui), 7 réussis
    r.faits |= jours(0)
    assert lg.taux(r, AUJ) == 8 / 14                                       # aujourd'hui coché : compté
    neuve = lg.Resolution("Neuve", 0, AUJ.isoformat(), "", set())
    assert lg.taux(neuve, AUJ) is None and lg.score([neuve], AUJ) is None   # rien à compter le premier jour
    assert lg.taux(lg.Resolution("Fin", 0, "2026-01-01", "2026-01-31", set()), AUJ) is None       # terminée avant la fenêtre
    parfaite = quotidienne(jours(*range(0, 40)))
    assert lg.taux(parfaite, AUJ) == 1.0


def test_taux_par_semaine():
    lundi = AUJ - timedelta(days=AUJ.weekday())                                # lundi 9 novembre
    r = lg.Resolution("Lire", 3, (lundi - timedelta(days=21)).isoformat(), "", set())
    for sem in (1, 2):                                                       # deux semaines précédentes : 3 jours chacune
        for k in range(3):
            r.faits.add((lundi - timedelta(days=7 * sem) + timedelta(days=k)).isoformat())
    assert lg.taux(r, AUJ) == 1.0                                              # deux semaines à 3 sur 3 ; la semaine en cours ne compte pas contre
    assert lg.serie(r, AUJ) == 2                                             # la semaine en cours n'a pas cassé la série
    r.faits.add(lundi.isoformat())
    r.faits.add((lundi + timedelta(days=1)).isoformat())
    r.faits.add((lundi + timedelta(days=2)).isoformat())
    assert lg.serie(r, AUJ) == 3 and lg.meilleure_serie(r, AUJ) == 3
    vide = lg.Resolution("Lire", 3, (lundi - timedelta(days=21)).isoformat(), "", set())
    assert lg.taux(vide, AUJ) == 0.0 and lg.serie(vide, AUJ) == 0


def test_series_et_records():
    r = quotidienne(jours(0, 1, 2, 10, 11, 12, 13, 14))
    assert lg.serie(r, AUJ) == 3 and lg.meilleure_serie(r, AUJ) == 5
    r.faits.discard((AUJ).isoformat())
    assert lg.serie(r, AUJ) == 2                                              # aujourd'hui non coché : la série de la veille tient
    r.faits.discard((AUJ - timedelta(days=1)).isoformat())
    assert lg.serie(r, AUJ) == 0
    assert lg.basculer(r, AUJ) is True and lg.est_fait(r, AUJ) and lg.basculer(r, AUJ) is False and not lg.est_fait(r, AUJ)
    ancien = lg.Resolution("X", 0, AUJ.isoformat(), "", set())
    lg.basculer(ancien, AUJ - timedelta(days=3))                              # cocher dans le passé avance le début
    assert ancien.debut == (AUJ - timedelta(days=3)).isoformat()


def test_note_etoiles_tendance_et_encouragements():
    bien = quotidienne(jours(*range(0, 40)))
    moyen = quotidienne(jours(*range(0, 40, 2)))
    rien = quotidienne(set())
    assert lg.score([bien], AUJ) == 100 and lg.etoiles(100) == "★★★★★" and lg.etoiles(None) == "☆☆☆☆☆" and lg.etoiles(52) == "★★★☆☆"
    assert lg.score([bien, rien], AUJ) == 50 and lg.score([], AUJ) is None
    assert "Excellent" in lg.encouragement([bien], AUJ)[0]
    assert "bon début" in lg.encouragement([lg.Resolution("m", 0, quotidienne(set()).debut, "", jours(*range(0, 40, 2)))], AUJ)[0] or lg.score([moyen], AUJ) >= 50
    assert "sans vous juger" in lg.encouragement([rien], AUJ)[0]
    assert "première résolution" in lg.encouragement([], AUJ)[0]
    assert "C'est parti" in lg.encouragement([lg.Resolution("n", 0, AUJ.isoformat(), "", set())], AUJ)[0]
    assert any("Série de 31 jours" in m and "Marcher" in m for m in lg.encouragement([bien], AUJ))
    montee = quotidienne(jours(*range(0, 14)))                                # rien avant, tout dans les 14 derniers jours
    assert lg.tendance([montee], AUJ) >= 5 and any("En hausse" in m for m in lg.encouragement([montee], AUJ))
    baisse = quotidienne(jours(*range(14, 28)))
    assert any("En baisse" in m for m in lg.encouragement([baisse], AUJ))


def test_exemple_valide():
    (_theme, _titre, texte), = lg.exemples(AUJ)
    rs = lg.lire(texte, AUJ)
    assert len(rs) == 3 and lg.ecrire(rs) == texte and lg.score(rs, AUJ) is not None


# ---------- dans la vraie fenêtre ----------
@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def fen(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    s = Store(Paths(tmp_path / "am"))
    s.sauver_reglages(recovery_asked=True)
    shutil.copytree(RACINE, s.paths.base / "plugins" / "resolutions")
    w = Fenetre(s)
    w.plugins.decouvrir()
    assert w.plugins.activer("resolutions"), w.plugins.infos["resolutions"].erreur
    yield w
    w.quitter_vraiment = True
    w.close()


def test_vue_cocher_note_et_encouragement(fen):
    vue = fen.vues_types["resolutions"]
    textes = []
    vue.modifie.connect(textes.append)
    auj = date.today()
    vue.charger(lg.ecrire([lg.Resolution("Marcher", 0, (auj - timedelta(days=5)).isoformat(), "", set()),
                           lg.Resolution("Lire", 3, (auj - timedelta(days=5)).isoformat(), "", set())]))
    assert vue.table.rowCount() == 2 and "Note : 0 / 100" in vue.l_note.text() and "☆☆☆☆☆" in vue.l_note.text()
    case = vue.table.cellWidget(0, 0).findChild(QCheckBox)
    assert case.isEnabled() and not case.isChecked()
    case.setChecked(True)                                                     # clic de l'utilisateur
    assert textes and auj.isoformat() in textes[-1]
    assert vue.table.cellWidget(0, 0).findChild(QCheckBox).isChecked()
    assert "1 j" in vue.table.item(0, 3).text() and vue.l_encourage.text()
    assert vue.table.cellWidget(0, 5).text().count("■") >= 1                  # la bande des 14 jours
    vue.e_jour.setDate(vue.e_jour.date().addDays(-1))                          # hier : la case est décochée, on peut la cocher
    assert not vue.table.cellWidget(0, 0).findChild(QCheckBox).isChecked()
    vue.table.cellWidget(0, 0).findChild(QCheckBox).setChecked(True)
    assert "2 j" in vue.table.item(0, 3).text()
    vue._supprimer(1)
    assert vue.table.rowCount() == 1 and "Lire" not in textes[-1]


def test_couleurs_du_taux(fen):
    m = sys.modules["scrinium_plugin_resolutions"]
    assert m.couleur_taux(0).hue() == 0 and m.couleur_taux(1).hue() == 120 and m.couleur_taux(0.5).hue() == 60


def test_pastille_a_faire():
    auj = date(2026, 11, 11)                      # mercredi
    r = lg.Resolution("Marcher", 0, "2026-11-01", "", set())
    assert "1 résolution" in lg.a_faire(lg.ecrire([r]), auj)
    r.faits = {"2026-11-11"}
    assert lg.a_faire(lg.ecrire([r]), auj) is None
    s = lg.Resolution("Sport", 2, "2026-11-01", "", {"2026-11-09", "2026-11-10"})    # 2 fois cette semaine : semaine remplie
    assert lg.a_faire(lg.ecrire([s]), auj) is None
    s.faits = {"2026-11-09"}
    assert lg.a_faire(lg.ecrire([s]), auj) is not None
    assert lg.a_faire("#scrinium-resolutions\n", auj) is None

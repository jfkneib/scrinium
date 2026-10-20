# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension « Agenda et rappels » : logique des événements, notifications, plugin avec un faux contexte."""
import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent / "plugins" / "agenda"
_spec = importlib.util.spec_from_file_location("agenda", RACINE / "__init__.py", submodule_search_locations=[str(RACINE)])
mod = importlib.util.module_from_spec(_spec)
sys.modules["agenda"] = mod
_spec.loader.exec_module(mod)
lg = mod.logique

T0 = datetime(2026, 10, 21, 9, 0)


def test_normaliser_et_charger():
    assert lg.normaliser({"titre": "  a   b ", "quand": "2026-10-21 09:00"})["titre"] == "a b"
    assert lg.normaliser({"titre": "", "quand": "2026-10-21 09:00"}) is None
    assert lg.normaliser({"titre": "x", "quand": "demain"}) is None
    assert lg.normaliser({"titre": "x", "quand": "2026-10-21 09:00", "fiche": {"theme": "T"}})["fiche"] is None
    brut = [{"id": "1", "titre": "b", "quand": "2026-10-22 10:00"}, {"id": "1", "titre": "doublon", "quand": "2026-10-22 10:00"},
            {"id": "2", "titre": "a", "quand": "2026-10-21 10:00"}, "n'importe quoi", None]
    assert [e["titre"] for e in lg.charger(brut)] == ["a", "b"] and lg.charger("pas une liste") == []


def test_ajouter_trie_et_refuse_titre_vide():
    evs = []
    lg.ajouter(evs, "plus tard", T0 + timedelta(days=1))
    lg.ajouter(evs, "tôt", T0, {"theme": "T", "titre": "F"})
    assert [e["titre"] for e in evs] == ["tôt", "plus tard"] and evs[0]["fiche"] == {"theme": "T", "titre": "F"}
    with pytest.raises(ValueError):
        lg.ajouter(evs, "  ", T0)


def test_a_notifier_et_a_venir():
    evs = lg.charger([{"id": "a", "titre": "passé", "quand": "2026-10-21 08:00"},
                      {"id": "b", "titre": "fait", "quand": "2026-10-21 08:30", "notifie": True},
                      {"id": "c", "titre": "futur", "quand": "2026-10-21 12:00"}])
    assert [e["id"] for e in lg.a_notifier(evs, T0)] == ["a"]
    assert [e["id"] for e in lg.a_venir(evs, T0)] == ["c"]


def test_delai_texte():
    assert lg.delai_texte(T0 + timedelta(minutes=5), T0) == "dans 5 min"
    assert lg.delai_texte(T0 + timedelta(hours=3), T0) == "dans 3 h"
    assert lg.delai_texte(T0 + timedelta(days=2), T0) == "dans 2 j"
    assert lg.delai_texte(T0 - timedelta(minutes=10), T0) == "en retard de 10 min"
    assert lg.delai_texte(T0 - timedelta(days=3), T0) == "en retard de 3 j"


class Reglages(dict):
    def set(self, k, v):
        self[k] = v


def faux_ctx(fiches=(), courante=None):
    notes, ouvertes = [], []
    ui = SimpleNamespace(ajouter_action=lambda *a: None, ajouter_bouton=lambda *a: None, planifier=lambda *a, **k: None,
                         notifier=lambda t, m: notes.append((t, m)), afficher_fiche=ouvertes.append)
    ctx = SimpleNamespace(reglages=Reglages(), ui=ui, fiche_courante=lambda: courante,
                          fiches=lambda theme=None: [f for f in fiches if theme in (None, f.theme)])
    return ctx, notes, ouvertes


def fiche(titre, verrou=False):
    return SimpleNamespace(theme="T", titre=titre, verrou=verrou)


def test_plugin_notifie_une_seule_fois():
    ctx, notes, _o = faux_ctx()
    p = mod.AgendaPlugin()
    p.activer(ctx)
    p.ajouter("Appeler", datetime.now() - timedelta(seconds=5))
    p.ajouter("Plus tard", datetime.now() + timedelta(days=1))
    p.verifier()
    p.verifier()
    assert notes == [("Rappel", "Appeler")]
    p.ajouter("Raté", datetime.now() - timedelta(hours=3))
    p.verifier()
    assert len(notes) == 2 and "en retard" in notes[1][1]


def test_plugin_liens_de_fiche():
    ouverte, verrouillee = fiche("Libre"), fiche("Secret", verrou=True)
    ctx, _n, ouvertes = faux_ctx([ouverte, verrouillee], courante=verrouillee)
    p = mod.AgendaPlugin()
    p.activer(ctx)
    assert p.fiche_liable() is None                    # jamais de lien vers une fiche verrouillée
    ctx.fiche_courante = lambda: ouverte
    assert p.fiche_liable() == {"theme": "T", "titre": "Libre"}
    assert p.ouvrir_fiche({"theme": "T", "titre": "Libre"}) and ouvertes == [ouverte]
    assert not p.ouvrir_fiche({"theme": "T", "titre": "Secret"}) and not p.ouvrir_fiche({"theme": "T", "titre": "Absente"})


def test_plugin_modifier_et_supprimer():
    ctx, _n, _o = faux_ctx()
    p = mod.AgendaPlugin()
    p.activer(ctx)
    p.ajouter("a", T0)
    ident = p.evenements()[0]["id"]
    p.remplacer(ident, "b", T0 + timedelta(hours=1))
    assert [e["titre"] for e in p.evenements()] == ["b"]
    p.supprimer(ident)
    assert p.evenements() == []


def test_dialogues_se_construisent():
    app = QApplication.instance() or QApplication([])
    assert app
    ctx, _n, _o = faux_ctx([fiche("Libre")], courante=fiche("Libre"))
    p = mod.AgendaPlugin()
    p.activer(ctx)
    p.ajouter("Réunion", T0, {"theme": "T", "titre": "Libre"})
    dlg = mod.DialogueAgenda(p)
    assert dlg.liste.count() == 1 and "Réunion" in dlg.liste.item(0).text() and dlg.vide.isHidden()
    d = mod.DialogueEvenement(None, fiche=p.fiche_liable())
    d.titre.setText("Nouveau")
    titre, quand, lien = d.resultat()
    assert titre == "Nouveau" and lien == {"theme": "T", "titre": "Libre"} and quand.second == 0

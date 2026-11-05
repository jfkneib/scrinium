# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""core/liste_fiches.py : une liste d'éléments tenue par des fiches d'un type exécutable (validation, repli sur les réglages, migration)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from scrinium.core import types_fiche  # noqa: E402
from scrinium.core.liste_fiches import ListeDeFiches  # noqa: E402
from scrinium.core.paths import Paths  # noqa: E402
from scrinium.core.plugins import Contexte, Gestionnaire, InfoPlugin  # noqa: E402
from scrinium.core.store import Store  # noqa: E402
from scrinium.core.types_fiche import TypeFiche  # noqa: E402

TYPE = TypeFiche("essai-liste", "Essai", "", executable=True)


def _lire(texte):
    return [{"nom": l[3:], "commande": l[3:] + "!"} for l in (texte or "").splitlines() if l.startswith("## ")]


def _ecrire(elements):
    return "#scrinium-essai-liste\n" + "".join(f"## {e['nom']}\n" for e in elements)


def _norm(brut):
    return [e for e in brut if isinstance(e, dict) and e.get("nom")][:3] if isinstance(brut, list) else []


@pytest.fixture
def liste(tmp_path):
    types_fiche.enregistrer(TYPE)
    s = Store(Paths(tmp_path / "am"))
    s.charger()
    g = Gestionnaire(s)
    ctx = Contexte(g, InfoPlugin(nom="essai", titre="e", version="1", description="", auteur="t", source="dossier", charger=lambda: None))
    yield ListeDeFiches(ctx, TYPE, _norm, _lire, _ecrire, "elements", lambda: [{"nom": "Exemple", "commande": "e"}], "Titre", "Outils", 3), ctx, s
    types_fiche.desenregistrer(TYPE.nom)


def test_repli_reglages_puis_exemples(liste):
    l, ctx, _s = liste
    assert l.elements() == [{"nom": "Exemple", "commande": "e"}]                     # ni fiche ni réglage : exemples
    ctx.reglages.set("elements", [{"nom": "Ancien"}, {"x": 1}])
    assert [e["nom"] for e in l.elements()] == ["Ancien"]                            # réglages d'avant
    ctx.reglages.set("elements", [])
    assert l.elements() == []                                                       # vide reste vide


def test_seules_les_fiches_validees_comptent_sans_doublon_et_plafonnees(liste):
    l, ctx, s = liste
    ctx.creer_fiche("Outils", "B", _ecrire([{"nom": "x"}, {"nom": "y"}]))
    ctx.creer_fiche("Outils", "A", _ecrire([{"nom": "y"}, {"nom": "z"}, {"nom": "w"}]))
    assert l.a_valider() == 2 and l.elements() == [{"nom": "Exemple", "commande": "e"}]
    th = s.theme("Outils")
    for f in th.fiches:
        s.valider_fiche(th, f)
    assert l.a_valider() == 0 and [e["nom"] for e in l.elements()] == ["y", "z", "w"]    # A puis B, doublon « y » retiré, plafond 3
    ctx.creer_fiche("Outils", "texte libre", "pas du type")                          # une fiche d'un autre type est ignorée
    assert len(l.fiches()) == 2


def test_migration_une_seule_fois_et_creee_inerte(liste):
    l, ctx, s = liste
    ctx.reglages.set("elements", [{"nom": "Ancien"}])
    v = l.migrer()
    th = s.theme("Outils")
    assert v is not None and len(th.fiches) == 1 and not s.fiche_validee(th, th.fiches[0]) and l.migrer() is None
    assert ctx.reglages.get("elements") == [{"nom": "Ancien"}]                       # les réglages restent comme copie


def test_sans_reglage_la_fiche_est_creee_une_fois_depuis_les_exemples(liste):
    l, ctx, s = liste
    v = l.migrer()                                                                  # premier lancement : pas de réglage → les exemples
    th = s.theme("Outils")
    assert v is not None and len(th.fiches) == 1 and not s.fiche_validee(th, th.fiches[0])
    assert [e["nom"] for e in _lire(th.fiches[0].texte)] == ["Exemple"]
    s.supprimer_fiche(th, th.fiches[0])                                             # l'utilisateur la supprime
    assert l.migrer() is None and l.fiches() == []                                  # jamais recréée


def test_migration_sans_ecraser_une_fiche_existante(liste):
    l, ctx, s = liste
    ctx.creer_fiche("Outils", "Déjà là", _ecrire([{"nom": "x"}]))
    ctx.reglages.set("elements", [{"nom": "Ancien"}])
    assert l.migrer() is None and len(s.theme("Outils").fiches) == 1


def test_a_ouvrir(liste):
    l, ctx, s = liste
    v, creee = l.a_ouvrir()
    assert creee and [e["nom"] for e in _lire(v.texte)] == ["Exemple"]               # créée à partir de la liste actuelle
    v2, creee2 = l.a_ouvrir()
    assert not creee2 and v2.id == v.id

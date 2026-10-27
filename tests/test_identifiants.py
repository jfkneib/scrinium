# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Identifiant stable des fiches (base du partage) : créé à la demande, jamais avant ; survit au renommage, au changement de
thème, au verrouillage et au rechargement ; les copies sont repérées."""
import re
import shutil

import pytest

from scrinium.core.paths import Paths
from scrinium.core.plugins import FicheVue, Gestionnaire
from scrinium.core.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(Paths(tmp_path / "am"))
    s.charger()
    return s


def une_fiche(store, titre="Ma fiche", texte="Contenu."):
    th = store.theme("Perso") or store.nouveau_theme("Perso")
    f = store.nouvelle_fiche(th)
    store.enregistrer(th, f, titre, texte)
    return th, f


def test_aucun_identifiant_tant_qu_on_ne_partage_pas(store):
    th, f = une_fiche(store)
    avant = f.path.read_bytes()
    assert Store.id_fiche(f) is None and store.trouver_par_id("x") is None
    store.enregistrer(th, f, f.titre, "Contenu modifié.")                    # enregistrer ne crée jamais d'identifiant
    assert Store.id_fiche(f) is None and b"scrinium:" not in f.path.read_bytes() and avant != f.path.read_bytes()


def test_identifiant_cree_a_la_demande_et_stable(store):
    th, f = une_fiche(store)
    ident = store.assurer_id(th, f)
    assert re.fullmatch(r"[0-9a-f]{32}", ident) and store.assurer_id(th, f) == ident        # même valeur à chaque demande
    assert store.trouver_par_id(ident) == (th, f)
    assert "Contenu." == f.texte and ident not in f.texte                                      # le texte de la fiche n'est pas touché
    relu = Store(store.paths)
    relu.charger()
    th2, f2 = relu.trouver_par_id(ident)
    assert f2.texte == "Contenu." and f2.titre == "Ma fiche"                                   # survit au rechargement


def test_identifiant_survit_au_renommage_au_changement_de_theme_et_au_verrou(store):
    th, f = une_fiche(store)
    ident = store.assurer_id(th, f)
    store.enregistrer(th, f, "Nouveau titre", f.texte)                                         # renommage de la fiche
    assert store.id_fiche(f) == ident
    store.renommer_theme(th, "Perso renommé")                                                  # renommage du thème
    assert store.trouver_par_id(ident)[1].titre == "Nouveau titre"
    store.verrouiller(th, f, "secret", sans_secours=True)                                      # verrouillage : l'identifiant est chiffré avec la fiche
    assert f.verrou and store.id_fiche(f) == ident                                              # fiche ouverte : lisible
    relu = Store(store.paths)
    relu.charger()
    g = next(x for t in relu.themes for x in t.fiches if x.verrou and x.titre == "Nouveau titre")
    assert g.fermee and Store.id_fiche(g) is None and relu.trouver_par_id(ident) is None       # fermée : identifiant invisible
    with pytest.raises(ValueError):
        relu.assurer_id(relu.themes[0], g)
    relu.deverrouiller(g, "secret")
    assert Store.id_fiche(g) == ident                                                          # rouverte : le même
    t_g = next(t for t in relu.themes if g in t.fiches)
    relu.retirer_verrou(t_g, g)
    assert relu.id_fiche(g) == ident


def test_copie_detectee_et_renouvelee(store):
    th, f = une_fiche(store)
    ident = store.assurer_id(th, f)
    copie = f.path.with_name("Copie.md")
    shutil.copy(f.path, copie)                                                                  # fiche copiée à la main
    relu = Store(store.paths)
    relu.charger()
    doubles = relu.ids_en_double()
    assert list(doubles) == [ident] and len(doubles[ident]) == 2
    th2, c = next(x for x in doubles[ident] if x[1].path.name == "Copie.md")
    nouveau = relu.renouveler_id(th2, c)
    assert nouveau != ident and relu.ids_en_double() == {} and relu.trouver_par_id(ident)[1].path.name != "Copie.md"


def test_api_des_extensions(store, tmp_path):
    th, f = une_fiche(store)
    g = Gestionnaire(store)
    d = store.paths.base / "plugins" / "p"
    d.mkdir(parents=True)
    (d / "plugin.json").write_text('{"titre": "P", "classe": "P", "api": 1}')
    (d / "__init__.py").write_text("from scrinium.core.plugins import Plugin\nclass P(Plugin):\n    api = 1\n"
                                   "    def activer(self, ctx):\n        self.ctx = ctx\n")
    g.decouvrir()
    assert g.activer("p")
    ctx = g.actifs["p"][1]
    vue = FicheVue(th, f)
    evenements = []
    ctx.on("fiche_enregistree", lambda fiche, origine=None: evenements.append((fiche.titre, origine)))
    assert vue.identifiant is None
    ident = ctx.assurer_identifiant(vue)
    assert FicheVue(th, f).identifiant == ident and ctx.assurer_identifiant(vue) == ident
    assert evenements == [("Ma fiche", "p")]                      # un seul événement : le second appel ne modifie rien

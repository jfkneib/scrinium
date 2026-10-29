# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Dépôts partagés : réglages valides (https obligatoire), enregistrement, suppression sans perte de fiches."""
import pytest

from scrinium.core import depots, synchro
from scrinium.core.depots import Depot
from scrinium.core.paths import Paths
from scrinium.core.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(Paths(tmp_path / "am"))
    s.charger()
    return s


def test_validation():
    d = depots.valider(Depot("serveur-jfk", " https://jfk.exemple.fr/scrinium/ ", " dede ", " Amis "))
    assert (d.nom, d.url, d.compte, d.theme) == ("serveur-jfk", "https://jfk.exemple.fr/scrinium", "dede", "Amis")
    assert depots.valider(Depot("local", "http://localhost:8080", "x")).theme == depots.THEME_ARRIVEE          # http : ordinateur local seulement
    assert depots.valider(Depot("v6", "http://[::1]:8080/s", "x")).url == "http://[::1]:8080/s"
    for mauvais in (Depot("", "https://a.fr", "x"), Depot("a/b", "https://a.fr", "x"), Depot("../x", "https://a.fr", "x"),
                    Depot("ok", "http://exemple.fr", "x"), Depot("ok", "ftp://a.fr", "x"), Depot("ok", "pas une adresse", "x"),
                    Depot("ok", "https://a.fr", "  ")):
        with pytest.raises(ValueError):
            depots.valider(mauvais)
    assert depots.valider(Depot("ok", "https://a.fr", "x", "a/b")).theme == "a-b"                 # un thème n'est pas un chemin


def test_enregistrer_remplacer_lire_supprimer(store):
    assert depots.lire_depots(store) == []
    depots.enregistrer_depot(store, Depot("a", "https://a.fr", "u1"))
    depots.enregistrer_depot(store, Depot("b", "https://b.fr", "u2", "Famille"))
    depots.enregistrer_depot(store, Depot("a", "https://a2.fr", "u1"))                              # même nom : remplacé
    assert [(d.nom, d.url) for d in depots.lire_depots(store)] == [("b", "https://b.fr"), ("a", "https://a2.fr")]
    assert "mot" not in str(store.reglages()["depots"]).lower()                                    # aucun mot de passe dans les réglages
    relu = Store(store.paths)
    assert [d.nom for d in depots.lire_depots(relu)] == ["b", "a"]


def test_reglages_abimes_ignores(store):
    store.sauver_reglages(depots=[{"nom": "ok", "url": "https://a.fr", "compte": "u"}, {"nom": "../mal", "url": "https://a.fr", "compte": "u"},
                                   "n'importe quoi", {"nom": "x"}])
    assert [d.nom for d in depots.lire_depots(store)] == ["ok"]
    store.sauver_reglages(depots="pas une liste")
    assert depots.lire_depots(store) == []


def test_supprimer_un_depot_garde_les_fiches(store):
    depots.enregistrer_depot(store, Depot("a", "https://a.fr", "u"))
    th = store.nouveau_theme("Partagées")
    f = store.nouvelle_fiche(th)
    store.enregistrer(th, f, "Reçue", "contenu")
    etat = synchro.EtatSynchro(synchro.chemin_etat(store, "a"))
    etat.valider(store, th, f, 1)
    etat.sauver()
    assert synchro.chemin_etat(store, "a").exists()
    depots.supprimer_depot(store, "a")
    assert depots.lire_depots(store) == [] and not synchro.chemin_etat(store, "a").exists()
    assert f.path.exists() and f.texte == "contenu"                                                # la fiche reste, simplement plus suivie

# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Règles de l'interface de transport, vérifiées sur le serveur de référence en mémoire (celles que le vrai serveur devra respecter)."""
import pytest

from scrinium.core.conflits import ContenuDistant
from scrinium.core.transport import (ConflitDeVersion, Introuvable, NonAuthentifie, Refuse, ServeurMemoire, Transport)


@pytest.fixture
def srv():
    return ServeurMemoire(["jfk", "dede", "alphonse"])


def contenu(texte="t"):
    return ContenuDistant(0, "Titre", texte, [])


def test_implemente_l_interface(srv):
    assert isinstance(srv.pour("jfk"), Transport)


def test_creation_puis_versions_successives(srv):
    jfk = srv.pour("jfk")
    assert jfk.ecrire("f1", contenu("a"), 0) == 1
    assert jfk.ecrire("f1", contenu("b"), 1) == 2
    assert jfk.lire("f1").texte == "b" and jfk.lire("f1").version == 2
    assert [(r.id, r.version, r.role, r.proprietaire) for r in jfk.lister()] == [("f1", 2, "proprietaire", "jfk")]


def test_version_perimee_refusee(srv):
    jfk = srv.pour("jfk")
    jfk.ecrire("f1", contenu("a"), 0)
    jfk.ecrire("f1", contenu("b"), 1)
    with pytest.raises(ConflitDeVersion) as e:
        jfk.ecrire("f1", contenu("c"), 1)                          # part de la version 1 alors que le serveur est à la 2
    assert e.value.version_serveur == 2 and jfk.lire("f1").texte == "b"
    with pytest.raises(ConflitDeVersion):
        jfk.ecrire("f1", contenu("d"), 0)                          # « création » d'une fiche qui existe déjà : refusée aussi


def test_les_trois_roles(srv):
    jfk, dede, alphonse = srv.pour("jfk"), srv.pour("dede"), srv.pour("alphonse")
    jfk.ecrire("f1", contenu("a"), 0)
    assert dede.lister() == [] and alphonse.lister() == []                  # rien n'est partagé : invisible
    with pytest.raises(Introuvable):
        dede.lire("f1")
    jfk.partager("f1", "dede", "ecriture")
    jfk.partager("f1", "alphonse", "lecture")
    assert [r.role for r in dede.lister()] == ["ecriture"] and [r.role for r in alphonse.lister()] == ["lecture"]
    assert dede.ecrire("f1", contenu("par dede"), 1) == 2                   # écriture : permise
    assert alphonse.lire("f1").texte == "par dede"                          # lecture : permise
    with pytest.raises(Refuse):
        alphonse.ecrire("f1", contenu("non"), 2)                            # lecture seule : refusée PAR LE SERVEUR
    assert jfk.lire("f1").texte == "par dede"
    with pytest.raises(Refuse):
        dede.partager("f1", "alphonse", "ecriture")                         # seul le propriétaire gère les droits
    with pytest.raises(Refuse):
        dede.supprimer("f1")
    with pytest.raises(Refuse):
        alphonse.droits("f1")
    assert jfk.droits("f1") == {"jfk": "proprietaire", "dede": "ecriture", "alphonse": "lecture"}


def test_retirer_un_droit_et_supprimer(srv):
    jfk, dede = srv.pour("jfk"), srv.pour("dede")
    jfk.ecrire("f1", contenu(), 0)
    jfk.partager("f1", "dede", "lecture")
    jfk.partager("f1", "dede", "ecriture")                                  # changer le rôle remplace l'ancien
    assert jfk.droits("f1")["dede"] == "ecriture"
    jfk.retirer_droit("f1", "dede")
    assert dede.lister() == []
    with pytest.raises(Introuvable):
        dede.lire("f1")
    with pytest.raises(Refuse):
        jfk.retirer_droit("f1", "jfk")                                      # le propriétaire ne se retire pas
    jfk.supprimer("f1")
    assert jfk.lister() == []


def test_partages_invalides(srv):
    jfk = srv.pour("jfk")
    jfk.ecrire("f1", contenu(), 0)
    for compte, role in (("inconnu", "lecture"), ("dede", "proprietaire"), ("dede", "admin"), ("jfk", "lecture")):
        with pytest.raises(Refuse):
            jfk.partager("f1", compte, role)


def test_compte_inconnu(srv):
    intrus = srv.pour("intrus")
    with pytest.raises(NonAuthentifie):
        intrus.lister()
    with pytest.raises(NonAuthentifie):
        intrus.ecrire("f1", contenu(), 0)


def test_ecriture_sans_droit_ne_cree_rien(srv):
    jfk, dede = srv.pour("jfk"), srv.pour("dede")
    jfk.ecrire("f1", contenu("a"), 0)
    with pytest.raises(Introuvable):
        dede.ecrire("f1", contenu("pirate"), 1)                             # non partagée avec lui : comme si elle n'existait pas
    assert jfk.lire("f1").texte == "a" and srv.ecritures == 1

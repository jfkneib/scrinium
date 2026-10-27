# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Détection des changements locaux d'un dépôt partagé : état de synchronisation, empreintes, renommage, déplacement,
suppression, fiches verrouillées. Aucun réseau ; `detecter` ne modifie jamais rien."""
import json
import os
import stat

import pytest

from scrinium.core import synchro
from scrinium.core.paths import Paths
from scrinium.core.store import Store

PNG = b"\x89PNG\r\n\x1a\n" + b"IMAGE-" * 40


@pytest.fixture
def store(tmp_path):
    s = Store(Paths(tmp_path / "am"))
    s.charger()
    return s


def fiche(store, theme="Partage", titre="Ma fiche", texte="Contenu."):
    th = store.theme(theme) or store.nouveau_theme(theme)
    f = store.nouvelle_fiche(th)
    store.enregistrer(th, f, titre, texte)
    return th, f


def etat_de(store):
    return synchro.EtatSynchro(synchro.chemin_etat(store, "serveur-jfk")).charger()


def test_une_fiche_non_suivie_n_est_jamais_touchee(store):
    th, f = fiche(store)
    avant = f.path.read_bytes()
    e = etat_de(store)
    assert synchro.detecter(store, e) == [] and f.path.read_bytes() == avant
    assert not synchro.chemin_etat(store, "serveur-jfk").exists()              # ni fichier d'état, ni identifiant créé
    assert synchro.Store.id_fiche(f) is None


def test_suivre_une_fiche_puis_aucun_changement(store):
    th, f = fiche(store)
    e = etat_de(store)
    ident = e.valider(store, th, f, version=3)
    assert e.suivi(ident) and e.entrees[ident]["version"] == 3 and e.entrees[ident]["theme"] == "Partage"
    assert synchro.detecter(store, e) == []                                    # tout est à jour


def test_modification_du_texte_du_titre_et_des_pieces(store):
    th, f = fiche(store)
    e = etat_de(store)
    ident = e.valider(store, th, f, 1)
    store.enregistrer(th, f, f.titre, "Contenu modifié.")
    (c,) = synchro.detecter(store, e)
    assert (c.id, c.etat, c.contenu, c.deplacee) == (ident, "modifiee", True, False)
    e.valider(store, th, f, 2)                                                 # synchronisée : plus rien à signaler
    assert synchro.detecter(store, e) == []
    store.enregistrer(th, f, "Autre titre", f.texte)                           # le titre fait partie du contenu
    assert [x.contenu for x in synchro.detecter(store, e)] == [True]
    e.valider(store, th, f, 3)
    p = store.ajouter_piece(f, "schema.png", "image/png", PNG)                 # une pièce jointe ajoutée
    assert [x.contenu for x in synchro.detecter(store, e)] == [True]
    e.valider(store, th, f, 4)
    store.supprimer_piece(f, p)                                                # ... puis supprimée
    assert [x.contenu for x in synchro.detecter(store, e)] == [True]


def test_deplacement_dans_un_autre_theme_sans_changer_le_contenu(store):
    th, f = fiche(store)
    e = etat_de(store)
    e.valider(store, th, f, 1)
    autre = store.nouveau_theme("Archives")
    nouveau = autre.path / f.path.name
    os.replace(f.path, nouveau)                                                # la fiche change de dossier
    relu = Store(store.paths)
    relu.charger()
    (c,) = synchro.detecter(relu, e)
    assert (c.etat, c.contenu, c.deplacee, c.theme) == ("modifiee", False, True, "Partage")


def test_suppression_et_corbeille(store):
    th, f = fiche(store)
    e = etat_de(store)
    ident = e.valider(store, th, f, 1)
    store.supprimer_fiche(th, f) if hasattr(store, "supprimer_fiche") else store.a_la_corbeille(f.path)
    relu = Store(store.paths)
    relu.charger()
    (c,) = synchro.detecter(relu, e)
    assert (c.id, c.etat) == (ident, "supprimee")


def test_fiche_suivie_puis_verrouillee(store):
    th, f = fiche(store)
    e = etat_de(store)
    ident = e.valider(store, th, f, 1)
    store.verrouiller(th, f, "secret", sans_secours=True)
    (c,) = synchro.detecter(store, e)                                          # ouverte : verrouillée, pas supprimée
    assert (c.id, c.etat) == (ident, "verrouillee")
    relu = Store(store.paths)
    relu.charger()
    (c,) = synchro.detecter(relu, e)                                           # fermée : son identifiant est invisible
    assert (c.id, c.etat) == (ident, "inaccessible")                           # ... mais elle n'est PAS prise pour supprimée
    with pytest.raises(ValueError):
        relu.assurer_id(relu.themes[0], next(x for t in relu.themes for x in t.fiches if x.verrou and x.titre == "Ma fiche"))
    with pytest.raises(ValueError):
        e.valider(store, th, f, 2)                                             # pas de synchronisation de contenu verrouillé


def test_etat_persistant_prive_et_tolerant(store):
    th, f = fiche(store)
    e = etat_de(store)
    ident = e.valider(store, th, f, 7)
    e.sauver()
    fichier = synchro.chemin_etat(store, "serveur-jfk")
    assert stat.S_IMODE(fichier.stat().st_mode) & 0o077 == 0                   # lisible par l'utilisateur seulement
    assert json.loads(fichier.read_text())["fiches"][ident]["version"] == 7
    assert etat_de(store).entrees == e.entrees                                 # relu à l'identique
    fichier.write_text("pas du json")                                          # fichier abîmé : état vide, pas de plantage
    assert etat_de(store).entrees == {}
    fichier.write_text(json.dumps({"format": 99, "fiches": {"x": {}}}))        # format inconnu : ignoré
    assert etat_de(store).entrees == {}


def test_noms_de_depot_sans_danger(store):
    for nom in ("../../etc/passwd", "a/b", "", "serveur jfk:443"):
        c = synchro.chemin_etat(store, nom)
        assert c.parent == store.paths.base / "synchro" and c.suffix == ".json"


def test_detecter_ne_modifie_rien(store):
    th, f = fiche(store)
    e = etat_de(store)
    e.valider(store, th, f, 1)
    store.enregistrer(th, f, f.titre, "autre")
    avant = (f.path.read_bytes(), json.dumps(e.entrees, sort_keys=True))
    synchro.detecter(store, e)
    synchro.detecter(store, e)
    assert (f.path.read_bytes(), json.dumps(e.entrees, sort_keys=True)) == avant

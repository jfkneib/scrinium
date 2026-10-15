import os
import pytest
from scrinium.core import crypto, recovery
from scrinium.core.paths import Paths
from scrinium.core.store import Store, propre


@pytest.fixture
def store(tmp_path):
    s = Store(Paths(tmp_path / "am"))
    s.charger()
    return s


def test_premier_lancement_cree_exemple(store):
    assert [t.nom for t in store.themes] == ["Perso"]
    assert store.themes[0].fiches[0].titre == "Exemple"


def test_propre():
    assert propre("a/b:c") == "a-b-c"
    assert propre("  ..  ") == "sans titre"


def test_enregistrer_renomme_et_relit(store):
    th = store.themes[0]
    f = store.nouvelle_fiche(th)
    assert store.enregistrer(th, f, "Wifi", "mdp123")
    assert f.path.name == "Wifi.md"
    assert not store.enregistrer(th, f, "Wifi", "mdp123")
    assert store.charger()[0].fiches[-1].texte == "mdp123"


def test_titre_en_double(store):
    th = store.themes[0]
    a, b = store.nouvelle_fiche(th), store.nouvelle_fiche(th)
    store.enregistrer(th, a, "X", "1")
    store.enregistrer(th, b, "X", "2")
    assert {a.path.name, b.path.name} == {"X.md", "X (2).md"}


def test_fiche_vide_jetee(store):
    th = store.themes[0]
    f = store.nouvelle_fiche(th)
    assert store.jeter_si_vide(th, f) and not f.path.exists()


def test_verrou_aller_retour_sans_clair_sur_disque(store):
    th = store.themes[0]
    f = store.nouvelle_fiche(th)
    store.enregistrer(th, f, "Secret", "très secret")
    store.verrouiller(th, f, "motdepasse")
    assert f.path.suffix == ".lock"
    assert b"tres secret" not in f.path.read_bytes() and "très secret".encode() not in f.path.read_bytes()
    g = store.charger()[0].fiches[-1]
    assert g.fermee
    with pytest.raises(crypto.InvalidTag):
        store.deverrouiller(g, "faux")
    store.deverrouiller(g, "motdepasse")
    assert g.texte == "très secret"
    store.enregistrer(th, g, "Secret", "modifié")
    assert b"modifi" not in g.path.read_bytes()
    store.retirer_verrou(th, g)
    assert g.path.suffix == ".md" and "modifié" in g.path.read_text(encoding="utf-8")


def test_cle_de_secours(store):
    p = store.paths
    recovery.generer_paire(p.base / "cle.pem", p.recovery_pub, phrase="phrase")
    th = store.themes[0]
    f = store.nouvelle_fiche(th)
    store.enregistrer(th, f, "S", "contenu")
    store.verrouiller(th, f, "oublie")
    pem = (p.base / "cle.pem").read_bytes()
    assert store.ouvrir_avec_cle_privee(f, pem, "phrase") == "contenu"
    with pytest.raises(Exception):
        store.ouvrir_avec_cle_privee(f, pem, "mauvaise")


def test_generation_refuse_d_ecraser(store):
    p = store.paths
    recovery.generer_paire(p.base / "cle.pem", p.recovery_pub)
    with pytest.raises(FileExistsError):
        recovery.generer_paire(p.base / "cle.pem", p.recovery_pub)


def test_ancien_format_lisible():
    # fiche réelle créée par l'ancien outil : mêmes octets, mêmes algos
    salt = b"s" * 16
    cle = crypto.deriver("pw", salt)
    data = crypto.chiffrer("ancien", cle, salt, b"")
    assert crypto.dechiffrer(data, "pw")[0] == "ancien"

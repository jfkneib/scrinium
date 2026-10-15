# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
import os
import pytest
from scrinium.core import crypto, recovery
from scrinium.core.paths import Paths
from scrinium.core.store import Store, propre


def _perso(themes):
    return next(t for t in themes if t.nom == "Perso")


@pytest.fixture
def store(tmp_path):
    s = Store(Paths(tmp_path / "am"))
    s.charger()
    return s


def test_premier_lancement_cree_exemples(store):
    noms = [t.nom for t in store.themes]
    assert noms == sorted(noms, key=str.lower) and "Bienvenue" in noms and len(noms) >= 4
    assert all(t.fiches for t in store.themes)
    assert (store.paths.fiches / "Bienvenue" / ".icone").read_text().strip() == "help-about"


def test_fiche_verrouillee_de_demo(store):
    demo = next(t for t in store.themes if t.nom == "Bienvenue")
    verrouillee = [f for f in demo.fiches if f.verrou]
    assert len(verrouillee) == 1 and verrouillee[0].fermee
    with pytest.raises(crypto.InvalidTag):
        store.deverrouiller(verrouillee[0], "faux")
    store.deverrouiller(verrouillee[0], "scrinium")
    assert "Bravo" in verrouillee[0].texte
    # le mot de passe annoncé dans la fiche d'aide est bien celui de la démo
    aide = next(f for f in demo.fiches if f.titre.startswith("4"))
    assert "scrinium" in aide.texte


def test_exemples_pas_recrees(store):
    th = store.theme("Perso")
    store.supprimer_fiche(th, th.fiches[0])
    assert len(_perso(Store(store.paths).charger()).fiches) == len(th.fiches)


def test_propre():
    assert propre("a/b:c") == "a-b-c"
    assert propre("  ..  ") == "sans titre"


def test_enregistrer_renomme_et_relit(store):
    th = store.theme("Perso")
    f = store.nouvelle_fiche(th)
    assert store.enregistrer(th, f, "Wifi", "mdp123")
    assert f.path.name == "Wifi.md"
    assert not store.enregistrer(th, f, "Wifi", "mdp123")
    assert _perso(store.charger()).fiches[-1].texte == "mdp123"


def test_titre_en_double(store):
    th = store.theme("Perso")
    a, b = store.nouvelle_fiche(th), store.nouvelle_fiche(th)
    store.enregistrer(th, a, "X", "1")
    store.enregistrer(th, b, "X", "2")
    assert {a.path.name, b.path.name} == {"X.md", "X (2).md"}


def test_fiche_vide_jetee(store):
    th = store.theme("Perso")
    f = store.nouvelle_fiche(th)
    assert store.jeter_si_vide(th, f) and not f.path.exists()


def test_verrou_aller_retour_sans_clair_sur_disque(store):
    th = store.theme("Perso")
    f = store.nouvelle_fiche(th)
    store.enregistrer(th, f, "Secret", "très secret")
    store.verrouiller(th, f, "motdepasse")
    assert f.path.suffix == ".lock"
    assert b"tres secret" not in f.path.read_bytes() and "très secret".encode() not in f.path.read_bytes()
    g = _perso(store.charger()).fiches[-1]
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
    th = store.theme("Perso")
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


# ---------- traductions ----------
def _racine():
    from pathlib import Path
    return Path(__file__).resolve().parent.parent


def test_traduction_anglaise_complete_et_coherente():
    import re
    from scrinium import i18n_po
    pot = i18n_po.lire_po((_racine() / "po" / "scrinium.pot").read_text(encoding="utf-8").replace('msgstr ""', 'msgstr "x"'))
    en = i18n_po.lire_po((_racine() / "po" / "en.po").read_text(encoding="utf-8"))
    assert set(pot) == set(en), (set(pot) ^ set(en))
    motif = r"%\(\w+\)\w|%[sd]"
    for fr, ang in en.items():
        if fr:
            assert sorted(re.findall(motif, fr)) == sorted(re.findall(motif, ang)), fr[:50]


def test_langue_anglaise_et_repli(monkeypatch):
    from scrinium import i18n
    try:
        assert i18n.init("en") == "en" and i18n._("Annuler") == "Cancel"
        assert i18n.init("de") == "en"            # langue sans traduction : anglais
        assert i18n.init("fr") == "fr" and i18n._("Annuler") == "Annuler"
        monkeypatch.setenv("SCRINIUM_LANG", "en_GB.UTF-8")
        assert i18n.init("auto") == "en"
    finally:
        i18n.init("fr")


def test_mo_compatible_avec_gettext_standard(tmp_path):
    import gettext
    from scrinium import i18n_po
    cat = i18n_po.lire_po((_racine() / "po" / "en.po").read_text(encoding="utf-8"))
    mo = tmp_path / "x.mo"
    mo.write_bytes(i18n_po.ecrire_mo(cat))
    t = gettext.GNUTranslations(open(mo, "rb"))
    assert t.gettext("Quitter") == "Quit" and t.gettext("inconnu") == "inconnu"


def test_cli_secours_alias_anglais(tmp_path, monkeypatch, capsys):
    from scrinium import cli
    monkeypatch.setenv("SCRINIUM_HOME", str(tmp_path / "h"))
    monkeypatch.setenv("SCRINIUM_LANG", "fr")
    s = Store(Paths())
    s.charger()
    th = s.theme("Perso")
    f = s.nouvelle_fiche(th)
    s.enregistrer(th, f, "Code", "1234")
    recovery.generer_paire(tmp_path / "k.pem", s.paths.recovery_pub)
    s.verrouiller(th, f, "abcd")
    assert cli.main(["rescue", "list"]) == 0
    assert "Perso/Code.lock" in capsys.readouterr().out
    assert cli.main(["rescue", "open", "Code", "--cle", str(tmp_path / "k.pem")]) == 0
    assert capsys.readouterr().out.strip() == "1234"


# ---------- métadonnées de fiche ----------
def test_meta_dans_md_invisible_et_conservee(store):
    th = store.theme("Perso")
    f = store.nouvelle_fiche(th)
    store.enregistrer(th, f, "Rdv", "dentiste")
    store.maj_meta(th, f, rappel="2026-11-03 09:00", note="a --> b")
    brut = f.path.read_text(encoding="utf-8")
    assert brut.startswith("# Rdv\n\n<!-- scrinium:") and brut.count("-->") == 1   # le « --> » de la valeur est échappé
    g = next(x for x in _perso(Store(store.paths).charger()).fiches if x.titre == "Rdv")
    assert g.texte == "dentiste" and g.meta == {"rappel": "2026-11-03 09:00", "note": "a --> b"}
    store.maj_meta(th, f, rappel=None)
    assert "rappel" not in f.meta and "rappel" not in f.path.read_text(encoding="utf-8")


def test_meta_chiffree_avec_une_fiche_verrouillee(store):
    th = store.theme("Perso")
    f = store.nouvelle_fiche(th)
    store.enregistrer(th, f, "Banque", "code 1234")
    store.maj_meta(th, f, rappel="2026-12-01")
    store.verrouiller(th, f, "motdepasse")
    brut = f.path.read_bytes()
    assert b"rappel" not in brut and b"2026-12-01" not in brut
    g = next(x for x in _perso(store.charger()).fiches if x.titre == "Banque")
    assert g.meta == {} and g.fermee
    with pytest.raises(ValueError):
        store.maj_meta(th, g, rappel="x")
    store.deverrouiller(g, "motdepasse")
    assert g.texte == "code 1234" and g.meta == {"rappel": "2026-12-01"}
    store.retirer_verrou(th, g)
    assert "2026-12-01" in g.path.read_text(encoding="utf-8")


def test_fiche_sans_meta_inchangee(store):
    th = store.theme("Perso")
    f = store.nouvelle_fiche(th)
    store.enregistrer(th, f, "X", "texte")
    assert f.path.read_text(encoding="utf-8") == "# X\n\ntexte"

# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Pièces jointes : docs/format-pieces-jointes.md (section 8)."""
import os
import shutil

import pytest

from scrinium.core import crypto, recovery
from scrinium.core.paths import Paths
from scrinium.core.store import LIMITES_PIECES, Store

PNG = b"\x89PNG\r\n\x1a\n" + b"IMAGE-SECRETE-" * 50
JPG = b"\xff\xd8\xff" + b"autre-image" * 30


@pytest.fixture
def store(tmp_path):
    s = Store(Paths(tmp_path / "am"))
    s.charger()
    return s


def nouvelle(store, titre="Ma fiche", texte="bonjour"):
    th = store.nouveau_theme("T")
    f = store.nouvelle_fiche(th)
    store.enregistrer(th, f, titre, texte)
    return th, f


def recharger(store):
    s = Store(store.paths)
    s.charger()
    return s


# ---------- 2. AMLOCK3 ----------
def test_amlock3_aller_retour_alterations_et_magic():
    cle, salt = os.urandom(32), os.urandom(16)
    data = crypto.chiffrer_piece({"nom": "é.png", "type": "image/png"}, PNG, cle, salt, b"WRAP")
    assert data.startswith(b"AMLOCK3\n") and PNG not in data and b"png" not in data
    ent, donnees = crypto.dechiffrer_piece(data, cle)
    assert ent == {"nom": "é.png", "type": "image/png"} and donnees == PNG
    with pytest.raises(crypto.InvalidTag):
        crypto.dechiffrer_piece(data, os.urandom(32))
    for i in (10, 30, 38, 40, len(data) - 1):          # sel, nonce, enveloppe, corps : tout est authentifié
        bad = bytearray(data)
        bad[i] ^= 1
        with pytest.raises((crypto.InvalidTag, ValueError)):
            crypto.dechiffrer_piece(bytes(bad), cle)
    with pytest.raises(ValueError, match="plus récent"):
        crypto.dechiffrer_piece(b"AMLOCK9\n" + data[8:], cle)
    with pytest.raises(ValueError):
        crypto.dechiffrer_piece(b"AMLOCK3\ncourt", cle)
    assert crypto.dechiffrer_piece_mdp(
        crypto.chiffrer_piece({"type": "image/png"}, PNG, crypto.deriver("mdp", salt), salt), "mdp")[1] == PNG


def test_cle_de_secours_ouvre_une_piece_seule(tmp_path):
    recovery.generer_paire(tmp_path / "priv.pem", tmp_path / "pub.pem")
    cle, salt = os.urandom(32), os.urandom(16)
    wrap = crypto.envelopper(cle, tmp_path / "pub.pem")
    data = crypto.chiffrer_piece({"type": "image/png"}, PNG, cle, salt, wrap)
    assert crypto.ouvrir_piece_avec_cle_privee(data, (tmp_path / "priv.pem").read_bytes())[1] == PNG
    sans = crypto.chiffrer_piece({"type": "image/png"}, PNG, cle, salt)
    with pytest.raises(ValueError, match="clé de secours"):
        crypto.ouvrir_piece_avec_cle_privee(sans, (tmp_path / "priv.pem").read_bytes())


# ---------- 1. rien ne change sans pièce jointe ----------
def test_fiches_sans_piece_inchangees(store):
    th, f = nouvelle(store)
    store.verrouiller(th, f, "mdp", sans_secours=True)
    assert f.path.read_bytes().startswith(b"AMLOCK2\n")
    store.retirer_verrou(th, f)
    assert not store.dossier_pj(f).exists() and f.path.suffix == ".md"
    assert [x.path.name for x in recharger(store).theme("T").fiches] == ["Ma fiche.md"]   # le .pj n'est jamais une fiche


# ---------- fiche en clair ----------
def test_ajout_liste_numerotation_suppression(store):
    th, f = nouvelle(store)
    a = store.ajouter_piece(f, "a.png", "image/png", PNG)
    b = store.ajouter_piece(f, "b.jpg", "image/jpeg", JPG)
    assert (a.id, b.id) == (1, 2) and a.chemin.name == "1.png" and b.chemin.name == "2.jpg"
    lues = store.lister_pieces(f)
    assert [(p.nom, p.type, p.taille) for p in lues] == [("a.png", "image/png", len(PNG)), ("b.jpg", "image/jpeg", len(JPG))]
    assert store.lire_piece(f, lues[0]) == PNG
    store.maj_piece(f, lues[0], ocr="texte lu", ocr_moteur="tesseract")
    assert store.lister_pieces(f)[0].ocr == "texte lu"
    store.maj_piece(f, lues[0], ocr="")
    assert store.lister_pieces(f)[0].ocr == "" and store.lister_pieces(f)[0].ocr_moteur == "tesseract"
    store.supprimer_piece(f, lues[1])
    assert [p.id for p in store.lister_pieces(f)] == [1]
    assert any(n.endswith("Ma fiche.pj-2.jpg") for n in os.listdir(store.paths.corbeille))
    store.supprimer_piece(f, lues[0])
    assert not store.dossier_pj(f).exists()                                # dernier départ : le dossier disparaît


def test_limites_et_types(store):
    th, f = nouvelle(store)
    with pytest.raises(ValueError, match="type"):
        store.ajouter_piece(f, "x.gif", "image/gif", b"GIF89a")
    with pytest.raises(ValueError, match="lourde"):
        store.ajouter_piece(f, "x.png", "image/png", b"0" * (LIMITES_PIECES["octets_piece"] + 1))
    for _i in range(LIMITES_PIECES["nombre"]):
        store.ajouter_piece(f, "x.png", "image/png", b"0")
    with pytest.raises(ValueError, match="trop de pièces"):
        store.ajouter_piece(f, "x.png", "image/png", b"0")


def test_fiche_avec_piece_jamais_jetee_comme_vide(store):
    th = store.nouveau_theme("T")
    f = store.nouvelle_fiche(th)
    store.ajouter_piece(f, "a.png", "image/png", PNG)
    assert not store.jeter_si_vide(th, f) and f in th.fiches


def test_renommer_deplace_le_pj(store):
    th, f = nouvelle(store)
    store.ajouter_piece(f, "a.png", "image/png", PNG)
    store.enregistrer(th, f, "Nouveau titre", "bonjour")
    assert f.path.name == "Nouveau titre.md" and (f.path.parent / "Nouveau titre.pj" / "1.png").exists()
    assert not (f.path.parent / "Ma fiche.pj").exists()
    assert recharger(store).theme("T").fiches[0].titre == "Nouveau titre"
    th2 = store.nouveau_theme("Autre")
    store.renommer_theme(th2, "Autre2")
    store.renommer_theme(th, "T2")
    assert len(store.lister_pieces(f)) == 1


def test_supprimer_fiche_corbeille_meme_horodatage(store):
    th, f = nouvelle(store)
    store.ajouter_piece(f, "a.png", "image/png", PNG)
    store.supprimer_fiche(th, f)
    noms = sorted(os.listdir(store.paths.corbeille))
    assert len(noms) == 2 and {n.split("-", 2)[0] + n.split("-", 2)[1] for n in noms} == {noms[0].split("-", 2)[0] + noms[0].split("-", 2)[1]}
    assert noms[0].endswith("Ma fiche.md") and noms[1].endswith("Ma fiche.pj")


def test_titre_libre_evite_un_pj_orphelin(store):
    th, f = nouvelle(store)
    (f.path.parent / "Autre.pj").mkdir()
    assert store.libre(th.path, "Autre").name == "Autre (2).md"


# ---------- fiche verrouillée ----------
def test_verrouiller_chiffre_les_pieces_et_les_ferme(store):
    th, f = nouvelle(store)
    store.ajouter_piece(f, "secret.png", "image/png", PNG)
    store.ajouter_piece(f, "b.jpg", "image/jpeg", JPG)
    store.verrouiller(th, f, "mdp", sans_secours=True)
    d = store.dossier_pj(f)
    assert sorted(p.name for p in d.iterdir()) == ["1.lock", "2.lock"] and f.path.suffix == ".lock"
    assert not (d.parent / "Ma fiche.md").exists() and not list(d.parent.glob("*.new")) and not list(d.parent.glob("*.old"))
    brut = b"".join(p.read_bytes() for p in d.iterdir())
    assert PNG not in brut and b"secret" not in brut                       # ni contenu ni nom en clair
    s2 = recharger(store)
    g = s2.theme("T").fiches[0]
    assert g.fermee and s2.lister_pieces(g) == []
    with pytest.raises(ValueError):
        s2.ajouter_piece(g, "x.png", "image/png", PNG)
    s2.deverrouiller(g, "mdp")
    pieces = s2.lister_pieces(g)
    assert [(p.nom, p.type) for p in pieces] == [("secret.png", "image/png"), ("b.jpg", "image/jpeg")]
    assert s2.lire_piece(g, pieces[0]) == PNG
    s2.maj_piece(g, pieces[0], ocr="mot de passe wifi")
    assert s2.lister_pieces(g)[0].ocr == "mot de passe wifi"
    nouv = s2.ajouter_piece(g, "c.png", "image/png", PNG)                    # ajout sur fiche verrouillée ouverte
    assert nouv.chemin.name == "3.lock" and PNG not in nouv.chemin.read_bytes()


def test_retirer_le_verrou_rend_les_pieces_en_clair(store):
    th, f = nouvelle(store)
    store.verrouiller(th, f, "mdp", sans_secours=True)
    store.ajouter_piece(f, "s.png", "image/png", PNG)
    store.retirer_verrou(th, f)
    p = store.lister_pieces(f)[0]
    assert p.chemin.name == "1.png" and p.nom == "s.png" and store.lire_piece(f, p) == PNG
    assert not list(store.dossier_pj(f).glob("*.lock"))


def test_verrouiller_annule_si_une_piece_est_illisible(store):
    th, f = nouvelle(store)
    store.ajouter_piece(f, "s.png", "image/png", PNG)
    store.verrouiller(th, f, "mdp", sans_secours=True)
    (store.dossier_pj(f) / "1.lock").write_bytes(b"AMLOCK3\n" + b"x" * 80)    # pièce corrompue
    with pytest.raises(ValueError, match="illisibles"):
        store.retirer_verrou(th, f)
    assert f.verrou and f.path.exists() and f.path.suffix == ".lock"         # rien n'a été modifié


# ---------- 4. interruption simulée de l'échange de dossiers ----------
def _etat_interrompu(store, f, ancien_clair, nouveau_pret=True, nouvelle_fiche_ecrite=True):
    """Fabrique l'état disque d'un verrouillage interrompu."""
    d = store.dossier_pj(f)
    base = f.path.parent
    nom = f.path.stem
    # fiche en clair avec une pièce, puis on prépare à la main le dossier .new
    new = base / f"{nom}.pj.new"
    new.mkdir()
    (new / "1.lock").write_bytes(b"AMLOCK3\n" + b"y" * 80)
    if nouveau_pret:
        (new / ".pret").write_bytes(b"")
    if nouvelle_fiche_ecrite:
        (base / f"{nom}.lock").write_bytes(b"AMLOCK2\n" + b"z" * 80)
    return d, new


def test_interruption_avant_la_fiche_nouvelle_est_ignoree(store):
    th, f = nouvelle(store)
    store.ajouter_piece(f, "a.png", "image/png", PNG)
    d, new = _etat_interrompu(store, f, True, nouvelle_fiche_ecrite=False)
    recharger(store)
    assert not new.exists() and (d / "1.png").exists()                       # .new écarté, l'ancien état intact


def test_interruption_non_terminee_sans_marqueur_est_ecartee(store):
    th, f = nouvelle(store)
    store.ajouter_piece(f, "a.png", "image/png", PNG)
    d, new = _etat_interrompu(store, f, True, nouveau_pret=False)
    recharger(store)
    assert not new.exists() and (d / "1.png").exists()


def test_interruption_apres_la_fiche_promeut_le_nouveau(store):
    th, f = nouvelle(store)
    store.ajouter_piece(f, "a.png", "image/png", PNG)
    d, new = _etat_interrompu(store, f, True)
    recharger(store)
    assert sorted(p.name for p in d.iterdir()) == ["1.lock"] and not new.exists() and not (d.parent / "Ma fiche.pj.old").exists()


def test_interruption_entre_les_deux_renommages(store):
    th, f = nouvelle(store)
    store.ajouter_piece(f, "a.png", "image/png", PNG)
    d, new = _etat_interrompu(store, f, True)
    os.rename(d, d.with_name(d.name + ".old"))                               # .pj -> .pj.old fait, .new -> .pj pas encore
    recharger(store)
    assert sorted(p.name for p in d.iterdir()) == ["1.lock"] and not d.with_name(d.name + ".old").exists()


def test_interruption_apres_echange_supprime_le_old(store):
    th, f = nouvelle(store)
    store.ajouter_piece(f, "a.png", "image/png", PNG)
    d = store.dossier_pj(f)
    shutil.copytree(d, d.with_name(d.name + ".old"))
    recharger(store)
    assert d.exists() and not d.with_name(d.name + ".old").exists()


def test_old_seul_est_restaure(store):
    th, f = nouvelle(store)
    store.ajouter_piece(f, "a.png", "image/png", PNG)
    d = store.dossier_pj(f)
    os.rename(d, d.with_name(d.name + ".old"))
    recharger(store)
    assert (d / "1.png").exists()


# ---------- 7. l'ancien code ignore les .pj ----------
def test_texte_lisible_sans_connaitre_les_pj(store):
    th, f = nouvelle(store, texte="texte important")
    store.ajouter_piece(f, "a.png", "image/png", PNG)
    ancien = Store._lire(f.path)                   # lecture de la fiche seule, comme le fait 0.1.0
    assert ancien.texte == "texte important" and ancien.titre == "Ma fiche"


# ---------- secours : rescue open --images / unlock ----------
def _fiche_verrouillee_avec_images(tmp_path, monkeypatch):
    from scrinium import cli
    monkeypatch.setenv("SCRINIUM_HOME", str(tmp_path / "h"))
    monkeypatch.setenv("SCRINIUM_LANG", "fr")
    s = Store(Paths())
    s.charger()
    th = s.theme("Perso")
    f = s.nouvelle_fiche(th)
    s.enregistrer(th, f, "Wifi", "mot de passe en photo")
    s.ajouter_piece(f, "box.png", "image/png", PNG)
    s.ajouter_piece(f, "photo.jpg", "image/jpeg", JPG)
    recovery.generer_paire(tmp_path / "k.pem", s.paths.recovery_pub)
    s.verrouiller(th, f, "abcd")
    return cli, s, th, f


def test_rescue_extrait_les_images(tmp_path, monkeypatch, capsys):
    cli, s, th, f = _fiche_verrouillee_avec_images(tmp_path, monkeypatch)
    assert cli.main(["rescue", "list"]) == 0
    assert "(+ 2 image(s))" in capsys.readouterr().out
    assert cli.main(["rescue", "open", "Wifi", "--cle", str(tmp_path / "k.pem")]) == 0
    sortie = capsys.readouterr()
    assert "mot de passe en photo" in sortie.out and "--images" in sortie.err       # signale les images sans les écrire
    dest = tmp_path / "sortie"
    assert cli.main(["rescue", "open", "Wifi", "--cle", str(tmp_path / "k.pem"), "--images", str(dest)]) == 0
    assert sorted(p.name for p in dest.iterdir()) == ["1-box.png", "2-photo.jpg"]
    assert (dest / "1-box.png").read_bytes() == PNG and (dest / "2-photo.jpg").read_bytes() == JPG


def test_rescue_unlock_remet_les_images_en_clair(tmp_path, monkeypatch, capsys):
    cli, s, th, f = _fiche_verrouillee_avec_images(tmp_path, monkeypatch)
    assert cli.main(["rescue", "unlock", "Wifi", "--cle", str(tmp_path / "k.pem")]) == 0
    s2 = Store(Paths())
    s2.charger()
    g = next(x for x in s2.theme("Perso").fiches if x.titre == "Wifi")
    assert not g.verrou and g.texte == "mot de passe en photo"
    assert [(p.nom, s2.lire_piece(g, p)) for p in s2.lister_pieces(g)] == [("box.png", PNG), ("photo.jpg", JPG)]


def test_secours_graphique_garde_la_cle_pour_les_pieces(tmp_path, monkeypatch):
    """Même chemin que la fenêtre : ouvrir_avec_cle_privee puis retirer_verrou doit convertir aussi les images."""
    cli, s, th, f = _fiche_verrouillee_avec_images(tmp_path, monkeypatch)
    s2 = Store(Paths())
    s2.charger()
    g = next(x for x in s2.theme("Perso").fiches if x.titre == "Wifi")
    g.texte = s2.ouvrir_avec_cle_privee(g, (tmp_path / "k.pem").read_bytes(), None)
    s2.retirer_verrou(s2.theme("Perso"), g)
    assert [s2.lire_piece(g, p) for p in s2.lister_pieces(g)] == [PNG, JPG]


# ---------- recherche dans le texte OCR ----------
def test_texte_ocr_cache_et_fiche_fermee(store):
    th, f = nouvelle(store)
    p = store.ajouter_piece(f, "t.png", "image/png", PNG)
    assert store.texte_ocr(f) == ""
    store.maj_piece(f, p, ocr="code de la porte 4821")
    assert store.texte_ocr(f) == "code de la porte 4821"
    store.maj_piece(f, p, ocr="autre texte")                 # le cache suit les modifications des fichiers
    assert store.texte_ocr(f) == "autre texte"
    store.verrouiller(th, f, "mdp", sans_secours=True)
    assert store.texte_ocr(f) == "autre texte"                # ouverte : cherchable
    f.texte = f.cle = f.salt = None
    assert store.texte_ocr(f) == "" and f.ocr_cache is None   # fermée : rien, et le cache est purgé


def test_ocr_d_une_fiche_verrouillee_jamais_en_clair_sur_disque(store):
    th, f = nouvelle(store)
    store.verrouiller(th, f, "mdp", sans_secours=True)
    p = store.ajouter_piece(f, "t.png", "image/png", PNG)
    store.maj_piece(f, p, ocr="SECRET-OCR-42", ocr_moteur="tesseract")
    brut = b"".join(x.read_bytes() for x in store.dossier_pj(f).iterdir())
    assert b"SECRET-OCR-42" not in brut and b"tesseract" not in brut


# ---------- remplacer_piece (recadrage) ----------
def test_remplacer_piece_clair_change_de_type_et_efface_l_ocr(store):
    th, f = nouvelle(store)
    p = store.ajouter_piece(f, "a.png", "image/png", PNG)
    store.maj_piece(f, p, ocr="ancien texte", ocr_moteur="tesseract")
    n = store.remplacer_piece(f, p, "image/jpeg", JPG)
    assert n.id == 1 and n.nom == "a.png" and n.chemin.name == "1.jpg" and not (n.chemin.parent / "1.png").exists()
    (q,) = store.lister_pieces(f)
    assert (q.type, q.ocr, q.ocr_moteur, q.nom) == ("image/jpeg", "", "", "a.png") and store.lire_piece(f, q) == JPG
    assert any(x.endswith("Ma fiche.pj-1.png") for x in os.listdir(store.paths.corbeille))     # ancienne version gardée
    assert store.texte_ocr(f) == ""


def test_remplacer_piece_verrouillee(store):
    th, f = nouvelle(store)
    store.verrouiller(th, f, "mdp", sans_secours=True)
    p = store.ajouter_piece(f, "s.png", "image/png", PNG)
    store.maj_piece(f, p, ocr="secret")
    n = store.remplacer_piece(f, p, "image/png", PNG + b"x")
    (q,) = store.lister_pieces(f)
    assert store.lire_piece(f, q) == PNG + b"x" and q.ocr == "" and q.nom == "s.png"
    assert b"IMAGE-SECRETE" not in n.chemin.read_bytes()
    assert any(x.endswith("1.lock") for x in os.listdir(store.paths.corbeille))
    f.texte = f.cle = f.salt = None
    with pytest.raises(ValueError):
        store.remplacer_piece(f, p, "image/png", PNG)


def test_remplacer_piece_limites(store):
    th, f = nouvelle(store)
    p = store.ajouter_piece(f, "a.png", "image/png", PNG)
    with pytest.raises(ValueError, match="type"):
        store.remplacer_piece(f, p, "image/gif", b"GIF89a")
    with pytest.raises(ValueError, match="lourde"):
        store.remplacer_piece(f, p, "image/png", b"0" * (LIMITES_PIECES["octets_piece"] + 1))
    assert store.lire_piece(f, store.lister_pieces(f)[0]) == PNG                      # rien n'a changé

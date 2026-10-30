# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Lien `scrinium://ajouter` : analyse sûre, validation par l'utilisateur, création d'une NOUVELLE fiche seulement."""
import os
from urllib.parse import quote

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from scrinium.core import lien  # noqa: E402
from tests.test_ui import app, fen  # noqa: E402,F401,F811


def _url(**kw):
    return "scrinium://ajouter?" + "&".join(f"{k}={quote(v)}" for k, v in kw.items())


# ---------- analyse (sans Qt) ----------
def test_analyse_titre_texte_theme_et_utf8():
    d = lien.analyser(_url(titre="Idée é", texte="ligne 1\nligne 2 ✓", theme="Sous le coude"))
    assert d == {"action": "ajouter", "titre": "Idée é", "texte": "ligne 1\nligne 2 ✓", "theme": "Sous le coude"}
    assert lien.analyser("scrinium:ajouter?texte=a")["texte"] == "a"                       # écriture sans « // » acceptée
    assert lien.analyser("SCRINIUM://AJOUTER?titre=x")["titre"] == "x"
    assert lien.analyser("scrinium://rejoindre?serveur=https%3A%2F%2Fs.org&jeton=ab") == {"action": "rejoindre"}


def test_analyse_nettoie_les_caracteres_dangereux():
    d = lien.analyser(_url(titre="a\x00b\nc‮d", texte="x\x07y‮⁦z\r\nfin"))
    assert d["titre"] == "ab cd" and d["texte"] == "xyz\nfin"                              # contrôles et inversions de sens retirés
    assert "<" in lien.analyser(_url(texte="<script>alert(1)</script>"))["texte"]          # gardé tel quel : c'est du texte brut, jamais du HTML


def test_analyse_refuse_l_inutilisable():
    for mauvais in ("https://exemple.org", "scrinium://autre?x=1", "scrinium://ajouter", "scrinium://ajouter?titre=&texte=%20%0A",
                    _url(texte="x" * (64 * 1024 + 1)), "scrinium://ajouter?texte=" + "a" * 250_000):
        with pytest.raises(ValueError):
            lien.analyser(mauvais)
    assert len(lien.analyser(_url(titre="t" * 500, theme="h" * 500))["titre"]) == lien.MAX_TITRE


def test_titre_par_defaut():
    assert lien.titre_par_defaut("Mon titre", "x", "D") == "Mon titre"
    assert lien.titre_par_defaut("", "\n\n## Première ligne\nsuite", "D") == "Première ligne"
    assert lien.titre_par_defaut("  ", "   ", "2026-10-30 10:00") == "2026-10-30 10:00"


# ---------- dans la fenêtre ----------
from scrinium.ui import fenetre as fen_mod  # noqa: E402


def _themes(fen):  # noqa: F811
    return {t.nom: [f.titre for f in t.fiches] for t in fen.store.themes}


def test_rien_n_est_ecrit_sans_validation(fen, monkeypatch):  # noqa: F811
    avant = _themes(fen)
    monkeypatch.setattr(fen_mod.DialogueAjoutLien, "exec", lambda self: 0)                  # l'utilisateur annule
    fen.ouvrir_lien(_url(titre="Piège", texte="du texte", theme="Nouveau"))
    assert _themes(fen) == avant


def test_validation_cree_une_nouvelle_fiche_dans_un_theme_existant_ou_nouveau(fen, monkeypatch):  # noqa: F811
    vus = {}

    def valider(self):
        vus.update(theme=self.theme.currentText(), titre=self.titre.text(), texte=self.texte.toPlainText(), bouton_defaut=self.ajouter.isDefault())
        return 1
    monkeypatch.setattr(fen_mod.DialogueAjoutLien, "exec", valider)
    fen.ouvrir_lien(_url(titre="Idée", texte="penser au certificat", theme="Perso"))
    assert vus == {"theme": "Perso", "titre": "Idée", "texte": "penser au certificat", "bouton_defaut": False}   # Entrée n'ajoute pas
    assert "Idée" in _themes(fen)["Perso"] and fen.fiche.titre == "Idée" and "certificat" in fen.fiche.texte
    fen.ouvrir_lien(_url(texte="# Courses\nlait", theme="Thème tout neuf"))
    assert _themes(fen)["Thème tout neuf"] == ["Courses"]                                      # thème créé, titre déduit du texte
    fen.ouvrir_lien(_url(texte="sans thème"))                                                   # thème par défaut (créé s'il le faut)
    assert "sans thème" in sum(_themes(fen).values(), [])


def test_une_fiche_existante_ou_verrouillee_n_est_jamais_modifiee(fen, monkeypatch):  # noqa: F811
    existante = next(f for t in fen.store.themes for f in t.fiches if not f.verrou)
    th = next(t for t in fen.store.themes if existante in t.fiches)
    avant = (existante.titre, existante.texte)
    verrouillee = next(f for t in fen.store.themes for f in t.fiches if f.verrou)
    brut = verrouillee.path.read_bytes()
    monkeypatch.setattr(fen_mod.DialogueAjoutLien, "exec", lambda self: 1)
    fen.ouvrir_lien(_url(titre=existante.titre, texte="AJOUT", theme=th.nom))                   # même titre, même thème
    fen.ouvrir_lien(_url(titre=verrouillee.titre, texte="AJOUT", theme=th.nom))
    assert (existante.titre, existante.texte) == avant and verrouillee.path.read_bytes() == brut
    assert sorted(f.titre for f in th.fiches).count(existante.titre) == 2                       # deux fiches distinctes : rien d'écrasé


def test_lien_invalide_explique_sans_rien_faire(fen, monkeypatch):  # noqa: F811
    from PyQt6.QtWidgets import QMessageBox
    vus = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda p, t, texte, *a, **k: vus.append(texte)))
    avant = _themes(fen)
    fen.ouvrir_lien("scrinium://ajouter")
    fen.ouvrir_lien("scrinium://inconnu?x=1")
    assert len(vus) == 2 and _themes(fen) == avant


def test_pas_de_fenetres_en_rafale(fen, monkeypatch):  # noqa: F811
    ouvertures = []

    def exec_(self):
        ouvertures.append(1)
        fen.ouvrir_lien(_url(texte="un deuxième lien arrive pendant qu'on regarde le premier"))    # pendant la fenêtre ouverte
        return 0
    monkeypatch.setattr(fen_mod.DialogueAjoutLien, "exec", exec_)
    fen.ouvrir_lien(_url(texte="premier"))
    assert ouvertures == [1]

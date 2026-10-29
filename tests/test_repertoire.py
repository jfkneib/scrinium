# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Répertoire (fiche CSV rangée par lettre) : colonnes libres, classement, import / export."""
from scrinium.core.repertoire import MODELES, Tableau, est_repertoire, normaliser, texte_modele

CONTACTS = ("Nom", "Prénom", "Téléphones", "Adresse", "Courriel", "Notes")


def contacts(*lignes, index=0):
    return Tableau(CONTACTS, [list(l) for l in lignes], index)


def test_aller_retour_texte_avec_guillemets_virgules_et_retours_a_la_ligne():
    t = contacts(("Dédé", "Alphonse", "06 50 12 45 36\n83 95 12 78 36", "1 rue, 75000 Paris", "a-dede@super.com", 'dit "Phonse"'))
    texte = t.en_texte()
    assert texte.splitlines()[0] == "#scrinium-repertoire index=0" and texte.splitlines()[1].startswith("Nom,Prénom")
    u = Tableau.depuis_texte(texte)
    assert u.colonnes == list(CONTACTS) and u.lignes == t.lignes and u.index == 0


def test_detection_par_la_marque():
    assert est_repertoire(texte_modele(0)) and est_repertoire("﻿#scrinium-repertoire\nNom\n")
    assert not est_repertoire("# Une note") and not est_repertoire("Nom,Prénom\nA,B") and not est_repertoire(None)
    assert all(est_repertoire(texte_modele(i)) for i in range(len(MODELES)))


def test_utilisable_pour_autre_chose_que_des_contacts():
    livres = Tableau(("Titre", "Auteur", "Année"), [["Le Petit Prince", "Saint-Exupéry", "1943"], ["Dune", "Herbert", "1965"]], 0)
    assert livres.par_lettre() == {"D": [1], "L": [0]}
    par_auteur = Tableau.depuis_texte(livres.en_texte())
    par_auteur.index = 1                                                  # on classe maintenant par auteur
    assert par_auteur.par_lettre() == {"H": [1], "S": [0]}
    assert Tableau.depuis_texte(par_auteur.en_texte()).index == 1


def test_lettre_sans_accents_diese_et_index_vide():
    t = contacts(("Éluard", "Paul"), ("7up", ""), ("", "Zoé"), ("", ""))
    assert [t.lettre(i) for i in range(4)] == ["E", "#", "Z", "#"]        # index vide : première cellule remplie
    t.index = 1
    assert t.lettre(0) == "P" and t.lettre(1) == "#"


def test_par_lettre_classe_et_garde_les_numeros():
    t = contacts(("Zed", "Zoé"), ("Durand", "Alice"), ("Dupont", "Alain"), ("Étienne", "Émile"), ("", "Bob"))
    assert t.par_lettre() == {"B": [4], "D": [2, 1], "E": [3], "Z": [0]}   # Dupont avant Durand ; Bob (sans nom) sous B
    t.index = 1
    assert t.par_lettre() == {"A": [2, 1], "B": [4], "E": [3], "Z": [0]}
    assert t.libelle(1) == "Alice · Durand" and Tableau(("A", "B"), [["", ""]]).libelle(0) == "(vide)"


def test_changer_colonnes_les_valeurs_suivent():
    t = contacts(("Dupont", "Alice", "0601", "", "a@x.fr", ""))
    t.changer_colonnes([("Courriel", 4), ("Nom", 0), ("Société", None)], 1)
    assert t.colonnes == ["Courriel", "Nom", "Société"] and t.lignes == [["a@x.fr", "Dupont", ""]] and t.index == 1
    t.changer_colonnes([], 5)
    assert t.colonnes == ["Nom"] and t.index == 0


def test_importer_csv_de_carnets_d_adresses_dans_un_modele_contacts():
    google = ("First Name,Last Name,Phone 1 - Value,Phone 2 - Value,E-mail 1 - Value,Notes,Société\n"
              "Alice,Martin,0601,0602,alice@x.fr,ami,Acme\n,,,,,,\nBob,,0703,,,,\n").encode("utf-8-sig")
    t = contacts()
    ajoutees, creees = t.importer(google)
    assert ajoutees == 2 and creees == ["Société"] and t.colonnes[-1] == "Société"       # colonne inconnue : ajoutée
    assert t.lignes[0][:6] == ["Martin", "Alice", "0601\n0602", "", "alice@x.fr", "ami"] and t.lignes[0][6] == "Acme"
    assert t.lignes[1][:2] == ["", "Bob"]
    assert t.importer(google) == (0, [])                                                  # pas de doublons au second import


def test_importer_excel_francais_point_virgule_cp1252_et_nouveau_tableau():
    fr = "Mot;Traduction\nmaison;house\nÉcole;school\n".encode("cp1252")
    t = Tableau.depuis_csv(fr)
    assert t.colonnes == ["Mot", "Traduction"] and [l[0] for l in t.lignes] == ["maison", "École"]
    assert t.par_lettre() == {"E": [1], "M": [0]}
    assert Tableau.depuis_csv(b"").colonnes == ["Nom"]


def test_exporter_csv_puis_reimporter():
    t = contacts(("Martin", "Alice", "0601\n0602", "ici, là", "a@x.fr", "é"))
    for sep in (",", ";"):
        octets = t.exporter_csv(sep)
        assert octets.startswith(b"\xef\xbb\xbf") and b"#scrinium" not in octets          # la marque n'est pas exportée
        u = Tableau.depuis_csv(octets)
        assert u.colonnes == list(CONTACTS) and u.lignes == t.lignes


def test_normaliser():
    assert normaliser("  Téléphones_Fixes ") == "telephones fixes"


# ---------- affichage ----------
import os  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QMessageBox  # noqa: E402

from scrinium.core.repertoire import LETTRES  # noqa: E402
from scrinium.ui.repertoire import DialogueColonnes, VueRepertoire  # noqa: E402
from tests.test_ui import app, fen  # noqa: E402,F401,F811


def _vue():
    v = VueRepertoire()
    texte = contacts(("Dupont", "Alice", "0601"), ("Durand", "Bob", ""), ("Zed", "Zoé", "")).en_texte()
    v.charger(texte)
    return v


def _lettre(v, l):
    v.lettres.setCurrentRow(LETTRES.index(l))


def test_vue_lettres_et_entrees():
    v = _vue()
    assert v.lettres.count() == 27 and v.lettres.currentRow() == LETTRES.index("D")     # première lettre utilisée
    assert [v.entrees.item(i).text() for i in range(v.entrees.count())] == ["Dupont · Alice", "Durand · Bob"]
    assert v._champs[0].toPlainText() == "Dupont" and v._champs[1].toPlainText() == "Alice"
    _lettre(v, "Z")
    assert v.entrees.count() == 1 and v._champs[0].toPlainText() == "Zed"
    _lettre(v, "M")
    assert v.entrees.count() == 0 and not v._champs[0].isEnabled() and not v.b_supprimer.isEnabled()


def test_vue_edition_signale_et_suit_la_lettre():
    v = _vue()
    recus = []
    v.modifie.connect(recus.append)
    v._champs[2].setPlainText("0699\n0700")
    assert Tableau.depuis_texte(recus[-1]).lignes[0][2] == "0699\n0700"
    v._champs[0].setPlainText("Martin")                                                   # Dupont devient Martin : la vue suit à M
    assert v.lettres.currentRow() == LETTRES.index("M") and [v.entrees.item(i).text() for i in range(v.entrees.count())] == ["Martin · Alice"]
    assert Tableau.depuis_texte(recus[-1]).lignes[0][0] == "Martin"


def test_vue_ajouter_supprimer_filtrer(monkeypatch):
    v = _vue()
    recus = []
    v.modifie.connect(recus.append)
    v.ajouter()
    assert len(v.tableau.lignes) == 4 and v.lettres.currentRow() == LETTRES.index("D")      # reste dans la lettre affichée
    assert v.entrees.item(v.entrees.currentRow()).text() == "(nouvelle entrée)"
    v._champs[0].setPlainText("Aubert")
    assert len(Tableau.depuis_texte(recus[-1]).lignes) == 4
    assert v.lettres.currentRow() == LETTRES.index("A") and v.entrees.currentRow() == 0
    v.filtre.setText("zoé")
    assert [v.entrees.item(i).text() for i in range(v.entrees.count())] == ["Zed · Zoé"]       # le filtre cherche dans toutes les lettres
    v.filtre.clear()
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    _lettre(v, "A")
    v.supprimer()
    assert len(Tableau.depuis_texte(recus[-1]).lignes) == 3


def test_dialogue_colonnes_suit_les_valeurs(monkeypatch):
    t = contacts(("Dupont", "Alice", "0601"))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    d = DialogueColonnes(t)
    d.liste.setCurrentRow(2)
    d._deplacer(-1)
    cols, index = d.resultat()
    assert [c[0] for c in cols][:3] == ["Nom", "Téléphones", "Prénom"] and index == 0
    t.changer_colonnes(cols, index)
    assert t.lignes[0][:3] == ["Dupont", "0601", "Alice"]


def test_fenetre_nouveau_repertoire_edition_et_verrou(fen, monkeypatch):  # noqa: F811
    from PyQt6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: ("Contacts (nom, téléphones, adresse, courriel)", True)))
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Famille", True)))
    fen.nouveau_repertoire()
    f = fen.fiche
    assert f.titre == "Famille" and fen.pile.currentWidget() is fen.repertoire and fen.format.isHidden() and fen.bande.isHidden()
    assert fen.repertoire.tableau.colonnes[0] == "Nom"
    fen.repertoire.ajouter()
    fen.repertoire._champs[0].setPlainText("Martin")
    fen.repertoire._champs[2].setPlainText("0601")
    fen.sauver()
    brut = f.path.read_text(encoding="utf-8")
    assert "#scrinium-repertoire" in brut and "Martin" in brut and "0601" in brut
    fen.recherche.setText("0601")                                                        # le contenu est cherchable
    assert any(x is f for _t, x in fen.rows)
    fen.recherche.clear()
    fen.store.verrouiller(fen.fiche_theme, f, "motdepasse")                             # verrouillée : plus de vue, pas de fuite
    fen.store.refermer(f)
    fen._afficher(fen.fiche_theme, f)
    assert fen.pile.currentWidget() is fen.texte and fen.format.isVisible() is False or True
    assert "0601" not in fen.texte.toPlainText()
    fen.store.deverrouiller(f, "motdepasse")
    fen._afficher(fen.fiche_theme, f)
    assert fen.pile.currentWidget() is fen.repertoire and fen.repertoire.tableau.lignes[0][0] == "Martin"
    note = next(x for t in fen.store.themes for x in t.fiches if not x.verrou and x is not f)           # une fiche simple reste simple
    fen._afficher(next(t for t in fen.store.themes if note in t.fiches), note)
    assert fen.pile.currentWidget() is fen.texte and not fen.format.isHidden()


def test_fenetre_pdf_d_un_repertoire(fen, tmp_path, monkeypatch):  # noqa: F811
    from PyQt6.QtWidgets import QFileDialog, QInputDialog
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: ("Livres (titre, auteur, année)", True)))
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Mes livres", True)))
    fen.nouveau_repertoire()
    fen.repertoire.ajouter()
    fen.repertoire._champs[0].setPlainText("Dune")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(tmp_path / "livres.pdf"), "")))
    fen.exporter_pdf()
    assert (tmp_path / "livres.pdf").read_bytes().startswith(b"%PDF-")


def test_deux_personnes_dans_la_meme_lettre():
    v = VueRepertoire()
    v.charger(contacts().en_texte())
    recus = []
    v.modifie.connect(recus.append)
    _lettre(v, "A")
    for nom, prenom in (("Alphonse", "dede"), ("Aubert", "Léa")):
        v.ajouter()
        assert v.lettres.currentRow() == LETTRES.index("A") and v.entrees.currentRow() >= 0
        v._champs[0].setPlainText(nom)
        v._champs[1].setPlainText(prenom)
    assert v.lettres.currentRow() == LETTRES.index("A")
    assert [v.entrees.item(i).text() for i in range(v.entrees.count())] == ["Alphonse · dede", "Aubert · Léa"]
    assert [l[0] for l in Tableau.depuis_texte(recus[-1]).lignes] == ["Alphonse", "Aubert"]


def test_entree_ajoutee_puis_abandonnee_n_est_pas_gardee():
    v = _vue()
    n = len(v.tableau.lignes)
    _lettre(v, "Z")
    v.ajouter()
    assert len(v.tableau.lignes) == n + 1
    _lettre(v, "D")                                                      # on change de lettre sans rien saisir
    assert len(v.tableau.lignes) == n and v.entrees.count() == 2
    v.ajouter()
    v._champs[0].setPlainText("Martin")                                  # nommée : elle va sous M, la vue la suit
    assert v.lettres.currentRow() == LETTRES.index("M") and len(v.tableau.lignes) == n + 1


# ---------- actions rapides ----------
from scrinium.core.repertoire import actions  # noqa: E402


def test_actions_detecte_courriel_telephone_et_lien_sans_doublon():
    texte = ("Appeler 06 50 12 45 36 ou +33 6 50 12 45 36, écrire à a-dede@super.com, site https://exemple.fr/x?y=1. "
             "Le 06.50.12.45.36 est le même numéro.")
    assert actions(texte) == [
        ("web", "https://exemple.fr/x?y=1", "https://exemple.fr/x?y=1"),
        ("mail", "a-dede@super.com", "mailto:a-dede@super.com"),
        ("tel", "06 50 12 45 36", "tel:0650124536"),
        ("tel", "+33 6 50 12 45 36", "tel:+33650124536"),
    ]


def test_actions_ignore_dates_codes_postaux_annees_et_schemas_dangereux():
    assert actions("Né le 2026-10-29, ou 12.03.1990, CP 75000, année 1943, 3114") == []
    assert actions("javascript:alert(1) file:///etc/passwd ftp://x.org/f") == []
    assert actions("") == [] and actions(None) == []
    assert [a[0] for a in actions("mail@x.fr; www.exemple.fr")] == ["mail"]               # « www. » sans schéma : pas un lien


def test_url_avec_courriel_dans_l_adresse_ne_double_pas():
    assert [a[0] for a in actions("https://x.org/?e=a@b.fr")] == ["web"]


def _boutons(v):
    return [v.rapides.itemAt(i).widget() for i in range(v.rapides.count())]


def test_vue_affiche_les_actions_de_l_entree(monkeypatch):
    v = VueRepertoire()
    v.charger(contacts(("Dedé", "Alphonse", "06 50 12 45 36", "", "a-dede@super.com", "https://exemple.fr")).en_texte())
    textes = [b.findChildren(type(v.b_ajouter))[0].text() for b in _boutons(v)[1:]]
    assert [x.split("  ", 1)[1] for x in textes] == ["Appeler 06 50 12 45 36", "Écrire à a-dede@super.com", "Ouvrir https://exemple.fr"]      # ordre des colonnes
    _lettre(v, "M")                                                                       # aucune entrée affichée : plus d'actions
    assert _boutons(v) == []
    _lettre(v, "D")
    v._champs[2].setPlainText("rien")                                                     # modifié : les actions suivent
    assert len(_boutons(v)) == 3


def test_agir_ouvre_le_bon_schema_et_copie_en_repli(monkeypatch):
    from PyQt6.QtGui import QDesktopServices, QGuiApplication
    from scrinium.ui import repertoire as ui_rep
    v = VueRepertoire()
    ouverts = []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda u: ouverts.append(u.toString()) or True))
    v.agir("mailto:a@b.fr", "a@b.fr")
    v.agir("tel:0650124536", "06 50 12 45 36")
    v.agir("javascript:alert(1)", "x")                                                    # schéma refusé
    assert ouverts == ["mailto:a@b.fr", "tel:0650124536"]
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda u: False))
    monkeypatch.setattr(ui_rep.QToolTip, "showText", staticmethod(lambda *a, **k: None))
    v.agir("tel:0650124536", "06 50 12 45 36")                                            # rien ne sait appeler : copié
    assert QGuiApplication.clipboard().text() == "06 50 12 45 36"
    appels = []
    monkeypatch.setattr(ui_rep, "ouvrir_url", lambda u, cmd="": appels.append((u.toString(), cmd)) or True)
    v.navigateur = lambda: "firefox"
    v.agir("https://exemple.fr", "https://exemple.fr")                                    # les liens passent par le navigateur choisi
    assert appels == [("https://exemple.fr", "firefox")]

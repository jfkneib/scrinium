# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extensions inventaire, collection, mots de passe (tableaux), recettes, journal, veille, santé : logique et vues."""
import importlib.util
import os
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication, QDialog  # noqa: E402

from scrinium.core import table_fiche as tf  # noqa: E402
from scrinium.core import types_fiche  # noqa: E402
from scrinium.core.paths import Paths  # noqa: E402
from scrinium.core.store import Store  # noqa: E402
from scrinium.ui.fenetre import Fenetre  # noqa: E402

PLUGINS = Path(__file__).resolve().parent.parent / "plugins"
NOMS = ("inventaire", "collection", "motsdepasse", "recettes", "journal", "veille", "sante", "emploi")


def _charger(nom):
    spec = importlib.util.spec_from_file_location(f"nf_{nom}", PLUGINS / nom / "logique.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def fen(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    s = Store(Paths(tmp_path / "am"))
    s.sauver_reglages(recovery_asked=True)
    for n in NOMS:
        shutil.copytree(PLUGINS / n, s.paths.base / "plugins" / n)
    w = Fenetre(s)
    w.plugins.decouvrir()
    for n in NOMS:
        assert w.plugins.activer(n), (n, w.plugins.infos[n].erreur)
    yield w
    w.quitter_vraiment = True
    w.close()


def test_tous_les_types_sont_enregistres_et_ont_un_modele(fen):
    for t in ("inventaire", "collection", "motsdepasse", "recettes", "journal", "veille", "sante", "emploi"):
        ty = next(x for x in types_fiche.types() if x.nom == t)
        texte = ty.texte_neuf()
        assert types_fiche.type_de(texte) == ty and t in fen.vues_types
        fen.vues_types[t].charger(texte)                                  # un modèle neuf se charge sans erreur
        assert types_fiche.a_faire_de(texte) in (None, "") or isinstance(types_fiche.a_faire_de(texte), str)
    assert next(x for x in types_fiche.types() if x.nom == "veille").executable


def test_table_aller_retour_et_tolerance():
    C = [tf.Colonne("a", "A"), tf.Colonne("n", "N", "nombre"), tf.Colonne("d", "D", "date"), tf.Colonne("c", "C", "case"),
         tf.Colonne("x", "X", "choix", ("un", "deux"))]
    t = "#scrinium-t\ndevise: €\n\n| A | N | D | C | X |\n|---|---|---|---|---|\n| objet | 1 200,5 € | 10/11/2026 | x | DEUX |\n| mauvais | abc | pas | | trois |\n|  |  |  |  |  |\n"
    d = tf.lire(t, "#scrinium-t", C, ("devise",))
    assert d.reglages == {"devise": "€"} and len(d.lignes) == 2
    assert d.lignes[0] == {"a": "objet", "n": "1200.5", "d": "2026-11-10", "c": "oui", "x": "deux"}
    assert d.lignes[1] == {"a": "mauvais", "n": "", "d": "", "c": "", "x": ""}
    assert tf.lire(tf.ecrire(d, "#scrinium-t", C), "#scrinium-t", C, ("devise",)).lignes == d.lignes
    assert tf.lire(None, "#scrinium-t", C).lignes == [] and tf.lire("texte libre", "#scrinium-t", C).lignes == []


def test_inventaire_totaux_et_garantie_et_pastille(fen):
    lg = _charger("inventaire")
    auj = date.today()
    lignes = [{"objet": "TV", "quantite": "1", "valeur": "650", "lieu": "Salon", "garantie": (auj + timedelta(days=10)).isoformat()},
              {"objet": "Chaises", "quantite": "4", "valeur": "45", "lieu": "Salon"}]
    assert lg.valeur_totale(lignes) == 830 and lg.par_lieu(lignes)["Salon"] == 830
    assert lg.garantie_proche(lignes[0], auj) == 10 and lg.garantie_proche(lignes[1], auj) is None
    assert lg.montant(1234.5, "€") == "1 234,5 €"
    texte = tf.ecrire(tf.Document({"devise": "€"}, [tf.normaliser(lg.COLONNES, d) for d in lignes]), lg.MARQUE, lg.COLONNES)
    assert "1 garantie" in types_fiche.a_faire_de(texte)
    assert types_fiche.a_faire_de(lg.texte_neuf()) is None


def test_vue_inventaire_ajouter_par_le_vrai_bouton(fen, monkeypatch):
    from scrinium.ui import table_fiche as ui
    vue = fen.vues_types["inventaire"]
    vue.charger(_charger("inventaire").texte_neuf())
    sortie = []
    vue.modifie.connect(sortie.append)

    def faux_exec(self):                                                  # remplit le formulaire puis clique sur OK
        self.champs["objet"].setText("Perceuse")
        self.champs["quantite"].setText("2")
        self.champs["valeur"].setText("59,90")
        self.findChild(ui.QDialogButtonBox).button(ui.QDialogButtonBox.StandardButton.Ok).click()
        return self.result()
    monkeypatch.setattr(ui.DialogueLigne, "exec", faux_exec)
    vue._ajouter()
    assert vue.table.rowCount() == 1 and vue.table.item(0, 0).text() == "Perceuse" and "| Perceuse |" in sortie[-1] and "59.9" in sortie[-1]
    assert "119,8" in vue.l_resume.text()


def test_dialogue_ligne_nom_vide_previent(fen, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    from scrinium.ui import table_fiche as ui
    vus = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: vus.append(a))
    lg = _charger("inventaire")
    d = ui.DialogueLigne(ui.Spec(lg.MARQUE, lg.COLONNES, "Ajouter"), None)
    d.findChild(ui.QDialogButtonBox).button(ui.QDialogButtonBox.StandardButton.Ok).click()
    assert vus and d.result() == QDialog.DialogCode.Rejected


def test_collection(fen):
    lg = _charger("collection")
    lignes = [{"titre": "A", "statut": lg.AI, "prix": "8"}, {"titre": "B", "statut": lg.CHERCHE}, {"titre": "C", "statut": lg.PRETE, "prix": "5"}]
    assert lg.compter(lignes) == {"ai": 1, "cherche": 1, "prete": 1} and lg.depense(lignes) == 13
    texte = tf.ecrire(tf.Document({}, [tf.normaliser(lg.COLONNES, d) for d in lignes]), lg.MARQUE, lg.COLONNES)
    assert "1 prêté" in types_fiche.a_faire_de(texte) and types_fiche.a_faire_de(lg.texte_neuf()) is None


def test_mots_de_passe(fen):
    lg = _charger("motsdepasse")
    for _i in range(20):
        p = lg.generer(20)
        assert len(p) == 20 and any(c.isdigit() for c in p) and any(c.isupper() for c in p)
    assert len(lg.generer(3)) == 8
    vue = fen.vues_types["motsdepasse"]
    vue.charger(tf.ecrire(tf.Document({}, [{"site": "ex", "identifiant": "moi", "secret": "abc", "adresse": "", "note": ""}]), lg.MARQUE, lg.COLONNES))
    assert vue.table.item(0, 2).text() == "••••••••" and "court" in vue.l_resume.text()
    vue.c_montrer.setChecked(True)
    assert vue.table.item(0, 2).text() == "abc"
    vue.recherche.setText("abc")                                          # la recherche ne lit pas les secrets
    assert vue.table.rowCount() == 0
    vue._copier  # présent
    from PyQt6.QtGui import QGuiApplication
    vue.recherche.setText("")
    vue._copier(0, "secret")
    assert QGuiApplication.clipboard().text() == "abc"


def test_recettes_echelle_et_vue(fen):
    lg = _charger("recettes")
    f = lg.mettre_a_l_echelle
    assert f("200 g de farine", 1.5) == "300 g de farine" and f("1/2 litre de lait", 2) == "1 litre de lait" and f("sel", 3) == "sel"
    assert f("1,5 l d'eau", 2) == "3 l d'eau" and f("½ citron", 2) == "1 citron" and f("3 œufs", 0.5) == "1.5 œufs" and f("1 1/2 kg", 2) == "3 kg"
    r = lg.lire(lg.exemples()[0][2])
    assert r.personnes == 4 and len(r.ingredients) == 5 and len(r.etapes) == 3 and r.note == 4 and lg.ecrire(r) == lg.exemples()[0][2]
    assert lg.pour(r, 8)[0] == "400 g de farine"
    vue = fen.vues_types["recettes"]
    sortie = []
    vue.modifie.connect(sortie.append)
    vue.charger(lg.exemples()[0][2])
    assert not sortie and vue.ingredients.toPlainText().startswith("200 g")
    vue.pour.setValue(2)
    assert vue.courses.toPlainText().splitlines()[0] == "- 100 g de farine"
    vue.etapes.setPlainText("Une seule étape")
    assert "1. Une seule étape" in sortie[-1] and "## Ingrédients" in sortie[-1]


def test_journal_et_vue(fen):
    lg = _charger("journal")
    j = lg.Journal()
    lg.definir(j, "2026-11-10", 4, "Bien.\n## 2026-01-01 faux titre")
    lg.definir(j, "2025-11-10", 3, "L'an dernier")
    t = lg.ecrire(j)
    assert t.index("2026-11-10") < t.index("2025-11-10") and lg.lire(t).entrees["2026-11-10"].texte.endswith("faux titre")
    assert len(lg.lire(t).entrees) == 2
    assert lg.il_y_a(j, date(2026, 11, 10))[0][0] == 1
    assert lg.serie(j, date(2026, 11, 10)) == 1 and lg.serie(j, date(2026, 11, 12)) == 0
    assert lg.a_faire(t, datetime(2026, 11, 11, 19, 0)) and lg.a_faire(t, datetime(2026, 11, 11, 10, 0)) is None and lg.a_faire(t, datetime(2026, 11, 10, 19, 0)) is None
    lg.definir(j, "2026-11-10", 0, "  ")
    assert "2026-11-10" not in j.entrees
    vue = fen.vues_types["journal"]
    sortie = []
    vue.modifie.connect(sortie.append)
    vue.charger(lg.MARQUE + "\n")
    vue.texte.setPlainText("Aujourd'hui")
    assert sortie and "Aujourd'hui" in sortie[-1] and date.today().isoformat() in sortie[-1]


def test_veille_flux_et_surete(fen):
    lg = _charger("veille")
    rss = (b'<?xml version="1.0"?><rss><channel><item><title>Salut</title><link>https://x.org/a</link><guid>1</guid>'
           b'<pubDate>Tue, 10 Nov 2026 10:00:00 +0000</pubDate><description>foo bar</description></item>'
           b'<item><title>Piege</title><link>javascript:alert(1)</link></item></channel></rss>')
    s = lg.Source("S", "https://x.org/f")
    arts = lg.analyser(s, rss)
    assert [a.titre for a in arts] == ["Salut"] and arts[0].date == "2026-11-10 10:00"
    assert lg.analyser(lg.Source("S", "https://x.org/f", "absent"), rss) == [] and lg.analyser(lg.Source("S", "https://x.org/f", "BAR"), rss)
    assert lg.analyser(s, b"<!DOCTYPE a [<!ENTITY x 'y'>]><a/>") == [] and lg.analyser(s, b"pas du xml") == []
    atom = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>T</title><link rel="alternate" href="https://y.org/1"/><id>i1</id></entry></feed>'
    assert lg.analyser(s, atom)[0].lien == "https://y.org/1"
    assert not lg.adresse_valide("file:///etc/passwd") and not lg.adresse_valide("ftp://x") and lg.adresse_valide("https://x.org/f")
    doc = lg.lire("#scrinium-veille\n| S | https://x.org/f | |\n| mauvais | file:///etc/passwd | |\n\n## Lus\nabcdef0123\nnimporte quoi\n")
    assert len(doc.sources) == 1 and doc.lus == ["abcdef0123"] and lg.lire(lg.ecrire(doc)).lus == ["abcdef0123"]
    assert lg.non_lus(arts, doc) == arts
    lg.marquer_lus(doc, arts)
    assert lg.non_lus(arts, doc) == []
    lg.NON_LUS[lg.cle_sources(doc)] = 3
    assert "3 nouveauté" in lg.a_faire(lg.ecrire(doc))
    articles, erreur = lg.recuperer(s, ouvrir=lambda src: (_ for _ in ()).throw(OSError("hors ligne")))
    assert articles == [] and "hors ligne" in erreur


def test_veille_vue_inerte_ne_relève_rien(fen, monkeypatch):
    vue = fen.vues_types["veille"]
    appels = []
    monkeypatch.setattr(vue._pool, "submit", lambda *a, **k: appels.append(a))
    vue.charger(_charger("veille").ecrire(_charger("veille").Document([_charger("veille").Source("S", "https://x.org/f")])))
    vue.actif = False
    vue.actualiser()
    assert appels == []
    vue.actif = True
    vue.actualiser()
    assert len(appels) == 1


def test_sante(fen):
    lg = _charger("sante")
    assert lg.categorie(115, 75) == "optimale" and lg.categorie(125, 70) == "normale" and lg.categorie(135, 70) == "limite"
    assert lg.categorie(145, 70) == "forte1" and lg.categorie(120, 95) == "forte1" and lg.categorie(165, 80) == "forte2" and lg.categorie(185, 80) == "grave"
    assert lg.mesure_valide(120, 80) and not lg.mesure_valide(80, 120) and not lg.mesure_valide(10, 5)
    assert lg.lire_horaires("20h00, 8:30; 08:30") == ["08:30", "20:00"]
    auj = date(2026, 11, 10)
    d = lg.Document([lg.Mesure("2026-11-09", "08:00", 130, 80, 70), lg.Mesure("2026-11-10", "08:00", 140, 90)],
                    [lg.Medicament("Aspirine", "1 cp", ["08:00", "20:00"], "2026-11-01"), lg.Medicament("Fini", "", ["09:00"], "", "2026-10-01")])
    assert lg.moyenne(d.mesures, auj) == (135, 85, 70)
    assert [p[:2] for p in lg.prises_du_jour(d, auj)] == [("08:00", "Aspirine"), ("20:00", "Aspirine")]
    assert [x[:2] for x in lg.en_retard(d, datetime(2026, 11, 10, 9, 0))] == [("08:00", "Aspirine")] and lg.en_retard(d, datetime(2026, 11, 10, 8, 10)) == []
    lg.basculer_prise(d, auj, "08:00", "Aspirine")
    assert lg.en_retard(d, datetime(2026, 11, 10, 9, 0)) == []
    texte = lg.ecrire(d, auj)
    d2 = lg.lire(texte)
    assert len(d2.mesures) == 2 and len(d2.medicaments) == 2 and d2.prises == d.prises
    assert lg.a_faire(texte, datetime(2026, 11, 10, 21, 0)) and lg.a_faire(texte, datetime(2026, 11, 10, 8, 5)) is None
    assert lg.lire("#scrinium-sante\n## Tension\n| 2026-01-01 | 08:00 | 400 | 20 | | |\n").mesures == []


def test_vue_sante_ajoute_une_mesure_et_coche_une_prise(fen, monkeypatch):
    from PyQt6.QtCore import Qt
    lg = _charger("sante")
    vue = fen.vues_types["sante"]
    sortie = []
    vue.modifie.connect(sortie.append)
    vue.charger(lg.ecrire(lg.Document([], [lg.Medicament("Aspirine", "1 cp", ["00:00"], "2020-01-01")])))
    vue.haute.setValue(128)
    vue.basse.setValue(82)
    vue._ajouter_mesure()
    assert "| 128 | 82 |" in sortie[-1] and vue.t_mesures.rowCount() == 1 and "128/82" in vue.l_bilan_t.text()
    assert vue.t_prises.rowCount() == 1 and vue.t_prises.item(0, 0).checkState() == Qt.CheckState.Unchecked
    vue.t_prises.item(0, 0).setCheckState(Qt.CheckState.Checked)
    assert date.today().isoformat() + " 00:00 Aspirine" in sortie[-1]
    vue.haute.setValue(60)
    vue.basse.setValue(90)
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    n = len(vue.d.mesures)
    vue._ajouter_mesure()
    assert len(vue.d.mesures) == n


def test_veille_les_lus_sont_masques(fen):
    lg = _charger("veille")
    vue = fen.vues_types["veille"]
    vue.charger(lg.ecrire(lg.Document([lg.Source("S", "https://x.org/f")])))
    vue.articles = [lg.Article("S", "Un", "https://x.org/1", "2026-11-10 10:00", "aaaaaaaaaa"), lg.Article("S", "Deux", "https://x.org/2", "2026-11-09 10:00", "bbbbbbbbbb")]
    vue._afficher()
    assert vue.t_articles.rowCount() == 2
    vue._lire_article(0)
    assert vue.t_articles.rowCount() == 1 and vue.t_articles.item(0, 1).text() == "Deux"
    vue.c_lus.setChecked(True)
    assert vue.t_articles.rowCount() == 2
    vue.c_lus.setChecked(False)
    vue._tout_lire()
    assert vue.t_articles.rowCount() == 0 and "Tout est lu" in vue.l_etat.text()


def test_veille_cases_par_source(fen):
    from PyQt6.QtCore import Qt
    lg = _charger("veille")
    doc = lg.Document([lg.Source("ejabberd", "https://x.org/e"), lg.Source("slixmpp", "https://x.org/s")])
    t = lg.ecrire(doc)
    assert "| ejabberd | https://x.org/e |  | oui |" in t
    vue = fen.vues_types["veille"]
    sortie = []
    vue.modifie.connect(sortie.append)
    vue.charger(t)
    vue.articles = [lg.Article("ejabberd", "v1", "https://x.org/e1", "2026-11-10 10:00", "aaaaaaaaaa"), lg.Article("slixmpp", "v2", "https://x.org/s1", "2026-11-09 10:00", "bbbbbbbbbb")]
    vue._afficher()
    assert vue.t_articles.rowCount() == 2
    vue.t_sources.item(1, 0).setCheckState(Qt.CheckState.Unchecked)                  # on ne veut que ejabberd
    assert vue.t_articles.rowCount() == 1 and vue.t_articles.item(0, 0).text() == "ejabberd" and "| slixmpp | https://x.org/s |  | non |" in sortie[-1]
    assert len(lg.non_lus(vue.articles, vue.doc)) == 1
    assert lg.lire(sortie[-1]).sources[1].afficher is False and lg.lire("| S | https://x.org/f | |\n").sources[0].afficher is True
    demandes = []
    vue._pool.submit = lambda *a, **k: demandes.append(a)                              # pas de réseau dans le test
    vue.t_sources.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    vue.t_sources.item(1, 0).setCheckState(Qt.CheckState.Checked)
    assert vue.t_articles.rowCount() == 1 and vue.t_articles.item(0, 0).text() == "slixmpp"
    assert len(demandes) == 0                                                         # slixmpp avait déjà ses articles : rien à relever
    vue.articles = []
    vue.t_sources.item(1, 0).setCheckState(Qt.CheckState.Unchecked)
    vue.t_sources.item(1, 0).setCheckState(Qt.CheckState.Checked)
    assert len(demandes) == 1 and demandes[0][2] == 1                                 # cochée sans articles : on ne relève que cette source
    vue.actualiser()
    assert len(demandes) == 2                                                         # ejabberd est décochée : seule slixmpp est interrogée
    assert demandes[1][3].nom == "slixmpp"
    # le mot-clé regarde aussi l'adresse de l'article (un flux de versions a des titres comme « v2.7.0 »)
    flux = (b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>v2.7.0</title><link rel="alternate" href="https://github.com/processone/ejabberd/releases/tag/v2.7.0"/><id>1</id></entry></feed>')
    assert lg.analyser(lg.Source("G", "https://x.org/f", "ejabberd"), flux) and not lg.analyser(lg.Source("G", "https://x.org/f", "slixmpp"), flux)


def test_veille_exemple_informatique():
    lg = _charger("veille")
    (_theme, _titre, texte), = lg.exemples()
    doc = lg.lire(texte)
    assert len(doc.sources) == 22 and all(lg.adresse_valide(s.adresse) for s in doc.sources)
    assert 0 < sum(s.afficher for s in doc.sources) < 8


def test_veille_remettre_non_lu(fen):
    lg = _charger("veille")
    vue = fen.vues_types["veille"]
    vue.charger(lg.ecrire(lg.Document([lg.Source("S", "https://x.org/f")])))
    vue.articles = [lg.Article("S", "Un", "https://x.org/1", "2026-11-10 10:00", "aaaaaaaaaa")]
    vue._afficher()
    vue._lire_article(0)
    assert vue.t_articles.rowCount() == 0
    vue.c_lus.setChecked(True)
    assert vue.t_articles.rowCount() == 1 and len(lg.non_lus(vue.articles, vue.doc)) == 0
    vue._non_lire_article(0)
    assert len(lg.non_lus(vue.articles, vue.doc)) == 1 and "aaaaaaaaaa" not in lg.ecrire(vue.doc)


def test_flux_commun():
    from scrinium.core import flux
    rss = (b'<rss><channel><item><title>Dev Python</title><link>https://x.org/1</link><guid>g1</guid><pubDate>Tue, 10 Nov 2026 10:00:00 +0000</pubDate>'
           b'<description>&lt;p&gt;Poste &lt;b&gt;Linux&lt;/b&gt; &amp;amp; XMPP&lt;/p&gt;</description></item>'
           b'<item><title>Piege</title><link>javascript:alert(1)</link></item><item><link>https://x.org/3</link></item></channel></rss>')
    e = flux.entrees(rss)
    assert len(e) == 1 and e[0].titre == "Dev Python" and e[0].date == "2026-11-10 10:00" and e[0].cle == "g1" and e[0].resume == "Poste Linux & XMPP"
    assert flux.entrees(b"<!DOCTYPE a [<!ENTITY x 'y'>]><a/>") == [] and flux.entrees(b"pas du xml") == []
    assert flux.adresse_valide("https://a.org/x") and not flux.adresse_valide("file:///etc/passwd") and not flux.adresse_valide("javascript:alert(1)")
    with pytest.raises(ValueError):
        flux.telecharger("ftp://x.org/f")


def _annonce(lg, titre, resume="", date_=None, source="S"):
    return lg.Annonce(titre, "https://x.org/" + titre.replace(" ", "-"), (date_ or date.today()).isoformat() + " 10:00", resume, source, lg.empreinte(source, titre))


def test_emploi_lien_fort_faible_exclu():
    lg = _charger("emploi")
    p = lg.Profil(14, ["python", "linux", "admin système | sysadmin"], ["xmpp", "télétravail"], ["stage", "alternance"])
    niveau = lambda t, r="": lg.evaluer(_annonce(lg, t, r), p)                            # noqa: E731
    assert niveau("Développeur Python", "Linux, SYSADMIN, XMPP").niveau == "fort"
    assert niveau("Développeur Python", "Linux, SYSADMIN, XMPP").manquants == []
    faible = niveau("Développeur Python", "télétravail")
    assert faible.niveau == "faible" and faible.manquants == ["linux", "admin système | sysadmin"] and faible.trouves == ["python", "télétravail"]
    assert niveau("Comptable").niveau == "aucun" and niveau("Stage Python Linux Admin Système").niveau == "exclue"
    assert niveau("Admin Systeme", "python linux").niveau == "fort"                       # accents et majuscules ne comptent pas
    assert niveau("Pythonista", "linuxien").niveau == "aucun"                              # mot entier seulement
    assert lg.evaluer(_annonce(lg, "Dev C++", ""), lg.Profil(14, ["c++"])).niveau == "fort"
    assert lg.evaluer(_annonce(lg, "Dev C", ""), lg.Profil(14, ["c++"])).niveau == "aucun"
    q = lg.Profil(14, [], ["xmpp", "linux"])                                              # sans indispensable : deux souhaités = fort
    assert lg.evaluer(_annonce(lg, "XMPP Linux"), q).niveau == "fort" and lg.evaluer(_annonce(lg, "XMPP"), q).niveau == "faible"
    assert lg.evaluer(_annonce(lg, "XMPP"), lg.Profil(14, [], ["xmpp"])).niveau == "fort"
    assert lg.evaluer(_annonce(lg, "Python Linux"), p).score > lg.evaluer(_annonce(lg, "Python"), p).score
    assert lg.lire_mots("python, Django ; admin système | sysadmin, PYTHON") == ["python", "Django", "admin système | sysadmin"]


def test_emploi_recentes_proposees_et_tri():
    lg = _charger("emploi")
    auj = date(2026, 11, 11)
    p = lg.Profil(7, ["python", "linux"], [])
    a_fort_vieux = _annonce(lg, "Python Linux vieux", "", date(2026, 11, 1))
    a_fort = _annonce(lg, "Python Linux", "", date(2026, 11, 10))
    a_faible = _annonce(lg, "Python seul", "", date(2026, 11, 11))
    a_sans_date = lg.Annonce("Python sans date", "https://x.org/sd", "", "", "S", "0123456789")
    toutes = [a_faible, a_fort_vieux, a_fort, a_sans_date]
    res = lg.proposees(toutes, p, True, auj)
    assert [a.titre for a, _l in res][:2] == ["Python Linux", "Python seul"] and "Python Linux vieux" not in [a.titre for a, _l in res]
    assert [a.titre for a, _l in res][-1] == "Python sans date"
    assert [l.niveau for _a, l in lg.proposees(toutes, p, False, auj)] == ["fort"]
    lg.vue(p, a_fort)
    assert "Python Linux" not in [a.titre for a, _l in lg.proposees(toutes, p, True, auj)]


def test_emploi_suivi_relance_texte_et_demande():
    lg = _charger("emploi")
    auj = date(2026, 11, 20)
    p = lg.Profil(14, ["python"], ["xmpp"], ["stage"], "Dix ans de Python.", [lg.Source("S", "https://x.org/f", False)])
    a = _annonce(lg, "Dev Python", "Poste XMPP à Lyon")
    assert lg.retenir(p, a, date(2026, 11, 1)) and not lg.retenir(p, a) and a.empreinte in p.vus
    lg.changer_statut(p.suivi[0], "postulée", date(2026, 11, 10))
    assert [s.titre for s in lg.relances(p, auj)] == ["Dev Python"] and lg.relances(p, date(2026, 11, 15)) == []
    lg.changer_statut(p.suivi[0], "n'importe quoi", auj)
    assert p.suivi[0].statut == "postulée"
    t = lg.ecrire(p)
    q = lg.lire(t)
    assert q.indispensables == ["python"] and q.exclus == ["stage"] and q.profil == "Dix ans de Python." and q.sources[0].afficher is False
    assert q.suivi[0].statut == "postulée" and q.suivi[0].date == "2026-11-10" and q.vus == p.vus and lg.ecrire(q) == t
    assert "javascript" not in lg.ecrire(lg.lire("#scrinium-emploi\n## Sources\n| X | javascript:alert(1) | |\n")) and lg.lire(None) == lg.Profil()
    d = lg.demande_ia(p, a, lg.evaluer(a, p))
    assert "Dix ans de Python." in d and "Dev Python" in d and "Poste XMPP à Lyon" in d and "N'invente" in d and "python, xmpp" in d
    lg.NOUVELLES[lg.cle_recherche(q)] = 2
    assert "2 nouvelle" in lg.a_faire(t, auj) and "relancer" in lg.a_faire(t, auj)
    lg.NOUVELLES.clear()
    assert lg.a_faire(lg.texte_neuf()) is None


def test_vue_emploi(fen, monkeypatch):
    from PyQt6.QtWidgets import QDialog
    lg = _charger("emploi")
    vue = fen.vues_types["emploi"]
    sortie = []
    vue.modifie.connect(sortie.append)
    vue.charger(lg.ecrire(lg.Profil(14, ["python", "linux"], ["xmpp"], ["stage"], "Mon profil", [lg.Source("S", "https://x.org/f")])))
    assert not sortie
    vue.annonces = [_annonce(lg, "Python Linux XMPP"), _annonce(lg, "Python"), _annonce(lg, "Stage Python Linux"), _annonce(lg, "Comptable")]
    vue._afficher()
    assert vue.t_annonces.rowCount() == 2 and vue.t_annonces.item(0, 1).text() == "Python Linux XMPP" and "fort" in vue.t_annonces.item(0, 0).text()
    assert "faible" in vue.t_annonces.item(1, 0).text()
    vue.c_faibles.setChecked(False)
    assert vue.t_annonces.rowCount() == 1
    vue.c_faibles.setChecked(True)
    vue.t_annonces.selectRow(0)
    vue._retenir(0)
    assert vue.t_annonces.rowCount() == 1 and vue.t_suivi.rowCount() == 1 and "| retenue | Python Linux XMPP |" in sortie[-1]
    vue._statut(0, "postulée")
    assert vue.t_suivi.item(0, 0).text() == "postulée"
    vus = []
    monkeypatch.setattr(QDialog, "exec", lambda self: vus.append(self.texte.toPlainText()) or 0)
    vue._preparer(0)
    assert vus and "Mon profil" in vus[0] and "Python" in vus[0]
    vue._ecarter(0)
    assert vue.t_annonces.rowCount() == 0
    vue.e_ind.setText("python, linux, django")                                                    # les listes se modifient dans l'onglet « Ma recherche »
    assert "indispensables: python, linux, django" in sortie[-1]
    appels = []
    monkeypatch.setattr(vue._pool, "submit", lambda *a, **k: appels.append(a))
    vue.actif = False
    vue.actualiser()
    assert appels == []
    vue.actif = True
    vue.actualiser()
    assert len(appels) == 1

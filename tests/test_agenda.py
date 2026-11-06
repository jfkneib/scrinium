# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension « Agenda et rappels » : logique des événements, notifications, plugin avec un faux contexte."""
import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent / "plugins" / "agenda"
_spec = importlib.util.spec_from_file_location("agenda", RACINE / "__init__.py", submodule_search_locations=[str(RACINE)])
mod = importlib.util.module_from_spec(_spec)
sys.modules["agenda"] = mod
_spec.loader.exec_module(mod)
lg = mod.logique

T0 = datetime(2026, 10, 21, 9, 0)


def test_normaliser_et_charger():
    assert lg.normaliser({"titre": "  a   b ", "quand": "2026-10-21 09:00"})["titre"] == "a b"
    assert lg.normaliser({"titre": "", "quand": "2026-10-21 09:00"}) is None
    assert lg.normaliser({"titre": "x", "quand": "demain"}) is None
    assert lg.normaliser({"titre": "x", "quand": "2026-10-21 09:00", "fiche": {"theme": "T"}})["fiche"] is None
    brut = [{"id": "1", "titre": "b", "quand": "2026-10-22 10:00"}, {"id": "1", "titre": "doublon", "quand": "2026-10-22 10:00"},
            {"id": "2", "titre": "a", "quand": "2026-10-21 10:00"}, "n'importe quoi", None]
    assert [e["titre"] for e in lg.charger(brut)] == ["a", "b"] and lg.charger("pas une liste") == []


def test_ajouter_trie_et_refuse_titre_vide():
    evs = []
    lg.ajouter(evs, "plus tard", T0 + timedelta(days=1))
    lg.ajouter(evs, "tôt", T0, {"theme": "T", "titre": "F"})
    assert [e["titre"] for e in evs] == ["tôt", "plus tard"] and evs[0]["fiche"] == {"theme": "T", "titre": "F"}
    with pytest.raises(ValueError):
        lg.ajouter(evs, "  ", T0)


def test_a_notifier_et_a_venir():
    evs = lg.charger([{"id": "a", "titre": "passé", "quand": "2026-10-21 08:00"},
                      {"id": "b", "titre": "fait", "quand": "2026-10-21 08:30", "notifie": True},
                      {"id": "c", "titre": "futur", "quand": "2026-10-21 12:00"}])
    assert [e["id"] for e in lg.a_notifier(evs, T0)] == ["a"]
    assert [e["id"] for e in lg.a_venir(evs, T0)] == ["c"]


def test_delai_texte():
    assert lg.delai_texte(T0 + timedelta(minutes=5), T0) == "dans 5 min"
    assert lg.delai_texte(T0 + timedelta(hours=3), T0) == "dans 3 h"
    assert lg.delai_texte(T0 + timedelta(days=2), T0) == "dans 2 j"
    assert lg.delai_texte(T0 - timedelta(minutes=10), T0) == "en retard de 10 min"
    assert lg.delai_texte(T0 - timedelta(days=3), T0) == "en retard de 3 j"


class Reglages(dict):
    def set(self, k, v):
        self[k] = v


@pytest.fixture(autouse=True)
def silence(monkeypatch):
    """Aucun son réel, aucune vraie fenêtre de rappel laissée ouverte."""
    sons = []
    monkeypatch.setattr(lg, "jouer_son", lambda: sons.append(1) or True)
    monkeypatch.setattr(QApplication, "beep", staticmethod(lambda: sons.append("bip")))
    yield sons
    for w in QApplication.topLevelWidgets():
        if isinstance(w, mod.RappelPopup):
            w.close()


@pytest.fixture(autouse=True)
def type_agenda():
    from scrinium.core import types_fiche
    types_fiche.enregistrer(lg.TYPE)
    yield
    types_fiche.desenregistrer(lg.TYPE.nom)


def faux_ctx(fiches=(), courante=None):
    notes, ouvertes, toutes = [], [], list(fiches)

    def creer(theme, titre, texte):
        f = SimpleNamespace(theme=theme, titre=titre, verrou=False, texte=texte)
        toutes.append(f)
        return f

    def modifier(f, titre=None, texte=None):
        f.texte = f.texte if texte is None else texte

    ui = SimpleNamespace(ajouter_action=lambda *a: None, ajouter_bouton=lambda *a: None, ajouter_action_fiche=lambda *a, **k: None, planifier=lambda *a, **k: None,
                         notifier=lambda t, m: notes.append((t, m)), afficher_fiche=ouvertes.append,
                         enregistrer_type=lambda *a: None, actualiser=lambda: None)
    ctx = SimpleNamespace(reglages=Reglages(), ui=ui, ajouter_doc=lambda *a: None, fiche_courante=lambda: courante, creer_fiche=creer, modifier=modifier,
                          fiches=lambda theme=None: [f for f in toutes if theme in (None, f.theme)])
    return ctx, notes, ouvertes


def fiche(titre, verrou=False):
    return SimpleNamespace(theme="T", titre=titre, verrou=verrou, texte=None)


def test_son_facultatif(silence):
    app = QApplication.instance() or QApplication([])
    assert app
    ctx, notes, _o = faux_ctx()
    p = mod.AgendaPlugin()
    p.activer(ctx)
    p.ajouter("avec", datetime.now() - timedelta(seconds=5))
    p.ajouter("sans", datetime.now() - timedelta(seconds=5), son=False)
    p.verifier()
    assert len(notes) == 2 and silence == [1]                 # un seul son : celui de l'événement qui en demande un
    assert [e["son"] for e in p.evenements()] == [True, False] or sorted(e["son"] for e in p.evenements()) == [False, True]


def test_popup_repousser_et_fait():
    app = QApplication.instance() or QApplication([])
    assert app
    ctx, _n, ouvertes = faux_ctx([fiche("Libre")])
    p = mod.AgendaPlugin()
    p.activer(ctx)
    p.ajouter("R1", datetime.now() - timedelta(seconds=5), {"theme": "T", "titre": "Libre"})
    p.verifier()
    assert len(p.popups) == 1 and p.popups[0].isVisible()
    p.popups[0]._ouvrir()
    assert len(ouvertes) == 1
    p.popups[0]._repousser()
    e = p.evenements()[0]
    assert not e["notifie"] and not e["fait"] and datetime.now() + timedelta(minutes=8) < logique_date(e) < datetime.now() + timedelta(minutes=11)
    p.verifier()
    assert len(p.popups) == 1                                  # pas de nouvelle fenêtre avant l'échéance
    p.marquer_fait(e["id"])
    assert p.evenements()[0]["fait"] and lg.a_notifier(p.evenements(), datetime.now() + timedelta(days=1)) == []


def logique_date(e):
    return lg.en_date(e["quand"])


def test_plugin_notifie_une_seule_fois():
    ctx, notes, _o = faux_ctx()
    p = mod.AgendaPlugin()
    p.activer(ctx)
    p.ajouter("Appeler", datetime.now() - timedelta(seconds=5))
    p.ajouter("Plus tard", datetime.now() + timedelta(days=1))
    p.verifier()
    p.verifier()
    assert notes == [("Rappel", "Appeler")]
    p.ajouter("Raté", datetime.now() - timedelta(hours=3))
    p.verifier()
    assert len(notes) == 2 and "en retard" in notes[1][1]


def test_plugin_liens_de_fiche():
    ouverte, verrouillee = fiche("Libre"), fiche("Secret", verrou=True)
    ctx, _n, ouvertes = faux_ctx([ouverte, verrouillee], courante=verrouillee)
    p = mod.AgendaPlugin()
    p.activer(ctx)
    assert p.fiche_liable() is None                    # jamais de lien vers une fiche verrouillée
    ctx.fiche_courante = lambda: ouverte
    assert p.fiche_liable() == {"theme": "T", "titre": "Libre"}
    assert p.ouvrir_fiche({"theme": "T", "titre": "Libre"}) and ouvertes == [ouverte]
    assert not p.ouvrir_fiche({"theme": "T", "titre": "Secret"}) and not p.ouvrir_fiche({"theme": "T", "titre": "Absente"})


def test_plugin_modifier_et_supprimer():
    ctx, _n, _o = faux_ctx()
    p = mod.AgendaPlugin()
    p.activer(ctx)
    p.ajouter("a", T0)
    ident = p.evenements()[0]["id"]
    p.remplacer(ident, "b", T0 + timedelta(hours=1))
    assert [e["titre"] for e in p.evenements()] == ["b"]
    p.supprimer(ident)
    assert p.evenements() == []


def test_dialogues_se_construisent():
    app = QApplication.instance() or QApplication([])
    assert app
    ctx, _n, _o = faux_ctx([fiche("Libre")], courante=fiche("Libre"))
    p = mod.AgendaPlugin()
    p.activer(ctx)
    p.ajouter("Réunion", T0, {"theme": "T", "titre": "Libre"})
    dlg = mod.DialogueAgenda(p)
    assert dlg.liste.count() == 1 and "Réunion" in dlg.liste.item(0).text() and dlg.vide.isHidden()
    d = mod.DialogueEvenement(None, fiche=p.fiche_liable())
    d.titre.setText("Nouveau")
    titre, quand, lien, son, repete = d.resultat()
    assert titre == "Nouveau" and lien == {"theme": "T", "titre": "Libre"} and son is True and repete == "" and quand.second == 0
    d._demain()
    assert d.quand().hour == 9 and d.quand().date() == (datetime.now() + timedelta(days=1)).date()
    d._dans(hours=1)
    assert timedelta(minutes=58) < d.quand() - datetime.now() < timedelta(minutes=62)


# ---------- répétitions ----------
def dt(texte):
    return datetime.strptime(texte, "%Y-%m-%d %H:%M")


def test_occurrences_et_fins_de_mois():
    a = dt("2026-01-31 09:00")
    assert lg.occurrence(a, "jour", 3) == dt("2026-02-03 09:00") and lg.occurrence(a, "semaine", 2) == dt("2026-02-14 09:00")
    assert [lg.occurrence(a, "mois", n) for n in (1, 2, 13)] == [dt("2026-02-28 09:00"), dt("2026-03-31 09:00"), dt("2027-02-28 09:00")]
    assert lg.occurrence(dt("2028-01-31 09:00"), "mois", 1) == dt("2028-02-29 09:00")                      # année bissextile
    bissextile = dt("2024-02-29 08:00")
    assert lg.occurrence(bissextile, "annee", 1) == dt("2025-02-28 08:00") and lg.occurrence(bissextile, "annee", 4) == bissextile.replace(year=2028)


def test_prochaine_strictement_apres_sans_derive():
    a = dt("2026-01-31 09:00")
    assert lg.prochaine(a, "mois", dt("2026-01-31 09:00")) == dt("2026-02-28 09:00")                       # strictement après
    assert lg.prochaine(a, "mois", dt("2026-03-15 12:00")) == dt("2026-03-31 09:00")                       # le 31 revient : pas de dérive au 28
    assert lg.prochaine(a, "jour", dt("2026-01-31 09:00")) == dt("2026-02-01 09:00")
    assert lg.prochaine(a, "semaine", dt("2026-01-31 09:01")) == dt("2026-02-07 09:00")
    assert lg.prochaine(dt("2020-03-12 09:00"), "annee", dt("2026-10-21 10:00")) == dt("2027-03-12 09:00")
    assert lg.prochaine(dt("2020-03-12 09:00"), "annee", dt("2026-03-12 08:00")) == dt("2026-03-12 09:00")
    assert lg.prochaine(a, "", dt("2030-01-01 00:00")) == a and lg.prochaine(a, "jour", dt("2025-01-01 00:00")) == a      # série pas commencée
    assert lg.prochaine(dt("2000-01-01 06:30"), "jour", dt("2026-10-21 07:00")) == dt("2026-10-22 06:30")                  # longue série


def test_normaliser_repetition():
    n = lg.normaliser({"titre": "x", "quand": "2026-10-21 09:00", "repete": "mois", "ancre": "2026-01-05 09:00"})
    assert n["repete"] == "mois" and n["ancre"] == "2026-01-05 09:00"
    assert lg.normaliser({"titre": "x", "quand": "2026-10-21 09:00", "repete": "toutes les lunes"})["repete"] == ""
    sans = lg.normaliser({"titre": "x", "quand": "2026-10-21 09:00", "ancre": "2020-01-01 00:00"})
    assert sans["repete"] == "" and sans["ancre"] == "2026-10-21 09:00"            # sans répétition, l'ancre ne sert à rien
    assert lg.normaliser({"titre": "x", "quand": "2026-10-21 09:00", "repete": "mois"})["ancre"] == "2026-10-21 09:00"


def test_anniversaire_passe_recoit_sa_prochaine_occurrence_sans_alerte():
    evs = []
    now = dt("2026-10-21 10:00")
    e = lg.ajouter(evs, "Anniversaire", dt("1985-03-12 09:00"), repete="annee", maintenant=now)
    assert e["quand"] == "2027-03-12 09:00" and e["ancre"] == "1985-03-12 09:00" and lg.a_notifier(evs, now) == []
    unique = lg.ajouter(evs, "Passé", dt("2026-10-01 09:00"), maintenant=now)
    assert unique["quand"] == "2026-10-01 09:00"                                   # un événement unique passé reste « en retard »


def test_serie_alertee_une_fois_puis_avance(silence):
    app = QApplication.instance() or QApplication([])
    assert app
    ctx, notes, _o = faux_ctx()
    p = mod.AgendaPlugin()
    p.activer(ctx)
    maintenant = datetime.now().replace(second=0, microsecond=0)
    ancre = maintenant - timedelta(days=10, minutes=1)                 # série quotidienne : 10 occurrences manquées
    evs = p.evenements()
    e = lg.ajouter(evs, "Boire de l'eau", ancre, repete="jour", maintenant=ancre - timedelta(seconds=1))
    e["quand"] = lg.en_texte(ancre)
    p._sauver(evs)
    p.verifier()
    p.verifier()
    assert len(notes) == 1                                             # une seule alerte malgré les occurrences manquées
    suivant = p.evenements()[0]
    assert dt(suivant["quand"]) > maintenant and not suivant["notifie"] and suivant["ancre"] == lg.en_texte(ancre)
    assert dt(suivant["quand"]) - maintenant <= timedelta(days=1)


def test_popup_d_une_serie_repousse_en_rappel_isole_et_fait_ne_termine_pas_la_serie(silence):
    app = QApplication.instance() or QApplication([])
    assert app
    ctx, _n, _o = faux_ctx()
    p = mod.AgendaPlugin()
    p.activer(ctx)
    ancre = datetime.now().replace(second=0, microsecond=0) - timedelta(minutes=1)
    evs = []
    lg.ajouter(evs, "Hebdo", ancre, repete="semaine", maintenant=ancre - timedelta(seconds=1))
    p._sauver(evs)
    p.verifier()
    serie = p.evenements()[0]
    assert serie["repete"] == "semaine" and dt(serie["quand"]) == ancre + timedelta(weeks=1)
    popup = p.popups[0]
    popup._repousser()
    assert len(p.evenements()) == 2                                    # la série + un rappel isolé dans 10 minutes
    isole = next(e for e in p.evenements() if not e["repete"])
    assert timedelta(minutes=8) < dt(isole["quand"]) - datetime.now() < timedelta(minutes=11)
    reste = next(e for e in p.evenements() if e["repete"])
    assert reste["quand"] == serie["quand"] and not reste["fait"]      # la série n'a pas bougé
    mod.RappelPopup(p, dict(reste))._fait()                            # « Fait » sur une série : rien n'est terminé
    assert next(e for e in p.evenements() if e["repete"])["fait"] is False


def test_dialogue_repetition_et_liste(silence):
    app = QApplication.instance() or QApplication([])
    assert app
    ctx, _n, _o = faux_ctx()
    p = mod.AgendaPlugin()
    p.activer(ctx)
    d = mod.DialogueEvenement(None)
    d.titre.setText("Anniv")
    d.repete.setCurrentIndex(d.repete.findData("annee"))
    assert d.resultat()[4] == "annee"
    p.ajouter("Anniv", dt("1990-05-04 09:00"), None, True, "annee")
    e = p.evenements()[0]
    assert e["ancre"] == "1990-05-04 09:00" and dt(e["quand"]) > datetime.now()
    edition = mod.DialogueEvenement(None, e)
    assert edition.date.date().year() == 1990 and edition.repete.currentData() == "annee"      # on édite la date de départ de la série
    assert "↻" in mod.DialogueAgenda(p).liste.item(0).text()


# ---------- « tout est fiche » : #scrinium-agenda ----------
def test_format_de_la_fiche_aller_retour():
    evs = []
    lg.ajouter(evs, "Anniv", dt("1990-05-04 09:00"), {"theme": "Perso", "titre": "Cadeaux"}, son=False, repete="annee")
    lg.ajouter(evs, "Notaire", dt("2030-01-02 14:30"))
    defs = [lg.definition(e) for e in evs]
    texte = lg.fiche_en_texte(defs)
    assert texte.startswith("#scrinium-agenda\n") and "repete: annee" in texte and "son: non" in texte
    assert lg.fiche_depuis_texte(texte) == sorted(defs, key=lambda d: d["ancre"])
    assert lg.fiche_depuis_texte(None) == [] and lg.fiche_depuis_texte("## Sans date\nid: x\n") == []


def test_texte_ecrit_a_la_main_a_un_id_stable():
    a = lg.fiche_depuis_texte("#scrinium-agenda\n\n## Dentiste\nquand: 2030-03-01 10:00\n")
    b = lg.fiche_depuis_texte("#scrinium-agenda\n\n## Dentiste\nquand: 2030-03-01 10:00\n")
    assert len(a) == 1 and a[0]["id"] == b[0]["id"] and a[0]["son"] is True and a[0]["fiche"] is None


def test_creation_de_la_fiche_et_etat_local():
    ctx, notes, _o = faux_ctx()
    p = mod.AgendaPlugin()
    p.activer(ctx)
    p.ajouter("Appeler", datetime.now() - timedelta(seconds=5))
    fiches = ctx.fiches()
    assert len(fiches) == 1 and fiches[0].theme == "Agenda" and fiches[0].texte.startswith("#scrinium-agenda")
    avant = fiches[0].texte
    p.verifier()
    assert notes and fiches[0].texte == avant                      # l'alerte ne réécrit pas la fiche (rien à synchroniser)
    assert list(ctx.reglages["etat"].values())[0]["notifie"] is True
    p.verifier()
    assert len(notes) == 1


def test_fiche_recue_les_evenements_passes_ne_sont_pas_rejoues():
    ctx, notes, _o = faux_ctx()
    recu = lg.fiche_en_texte([lg.normaliser({"titre": "Vieux", "quand": "2020-01-01 09:00"}),
                              lg.normaliser({"titre": "Futur", "quand": "2099-01-01 09:00"})])
    ctx.creer_fiche("Partagées", "Agenda reçu", recu)
    p = mod.AgendaPlugin()
    p.activer(ctx)
    p.verifier()
    assert notes == []                                             # première fois sur cette machine : pas d'historique rejoué
    ctx.creer_fiche("Partagées", "Autre", lg.fiche_en_texte([lg.normaliser({"titre": "Nouveau retard", "quand": "2020-02-02 09:00"})]))
    p.verifier()
    assert len(notes) == 1 and "Nouveau retard" in notes[0][1]    # ensuite, un événement arrivé en retard est annoncé


def test_modification_dans_la_bonne_fiche_et_doublons():
    ctx, _n, _o = faux_ctx()
    e = lg.normaliser({"id": "aaa", "titre": "Même", "quand": "2099-01-01 09:00"})
    f1 = ctx.creer_fiche("A", "un", lg.fiche_en_texte([e]))
    f2 = ctx.creer_fiche("B", "deux", lg.fiche_en_texte([e, lg.normaliser({"id": "bbb", "titre": "Autre", "quand": "2099-02-01 09:00"})]))
    p = mod.AgendaPlugin()
    p.activer(ctx)
    assert sorted(x["id"] for x in p.evenements()) == ["aaa", "bbb"]              # « aaa » compté une seule fois
    p.remplacer("bbb", "Autre bis", dt("2099-03-01 09:00"))
    assert "Autre bis" in f2.texte and "Autre bis" not in f1.texte
    p.supprimer("aaa")
    assert "Même" not in f1.texte and "Même" not in f2.texte


def test_fiche_verrouillee_ou_texte_libre_ignores():
    ctx, _n, _o = faux_ctx([fiche("Verrouillée", verrou=True)])
    ctx.creer_fiche("T", "Libre", "## Pas un agenda\nquand: 2099-01-01 09:00\n")
    p = mod.AgendaPlugin()
    p.activer(ctx)
    assert p.evenements() == []


def test_migration_des_reglages_en_fiche_garde_l_etat():
    ctx, notes, _o = faux_ctx()
    ctx.reglages["evenements"] = [
        {"id": "x1", "titre": "Déjà annoncé", "quand": "2020-01-01 09:00", "notifie": True},
        {"id": "x2", "titre": "À venir", "quand": "2099-01-01 09:00", "repete": "mois", "son": False}]
    p = mod.AgendaPlugin()
    p.activer(ctx)
    assert len(ctx.fiches()) == 1 and ctx.reglages["migrees"] and "evenements" in ctx.reglages
    assert [e["titre"] for e in p.evenements()] == ["Déjà annoncé", "À venir"] and p.evenements()[1]["son"] is False
    p.verifier()
    assert not [n for n in notes if n[0] == "Rappel"]              # déjà annoncé avant la migration : pas annoncé de nouveau
    p2 = mod.AgendaPlugin()
    p2.activer(ctx)
    assert len(ctx.fiches()) == 1                                  # une seule migration


def test_vue_du_type_agenda():
    app = QApplication.instance() or QApplication([])
    assert app
    vue = mod.VueAgenda()
    recus = []
    vue.modifie.connect(recus.append)
    vue.charger(lg.fiche_en_texte([lg.normaliser({"titre": "Réunion", "quand": "2099-01-01 09:00"})]))
    assert vue.liste.count() == 1 and "Réunion" in vue.liste.item(0).text()
    vue.liste.setCurrentRow(0)
    vue._supprimer()
    assert vue.liste.count() == 0 and recus and lg.fiche_depuis_texte(recus[-1]) == []

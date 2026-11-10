# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Inventaire : ce que l'on possède, où, pour combien, jusqu'à quand c'est garanti (sans interface). Le tableau est géré par `core/table_fiche.py`."""
from datetime import date, timedelta

from scrinium.core import table_fiche as tf
from scrinium.core.types_fiche import TypeFiche
from scrinium.i18n import N_, _

MARQUE = "#scrinium-inventaire"
DELAI_GARANTIE = 60                                      # jours avant la fin de garantie à partir desquels la fiche a une pastille
COLONNES = [tf.Colonne("objet", N_("Objet")), tf.Colonne("categorie", N_("Catégorie")), tf.Colonne("lieu", N_("Lieu")),
            tf.Colonne("quantite", N_("Quantité"), "nombre"), tf.Colonne("valeur", N_("Valeur unitaire"), "nombre"),
            tf.Colonne("achat", N_("Acheté le"), "date"), tf.Colonne("garantie", N_("Garantie jusqu'au"), "date"),
            tf.Colonne("note", N_("Note"))]
REGLAGES = (("devise", N_("Devise")),)


def quantite(d: dict) -> float:
    return float(d.get("quantite") or 1)


def valeur_totale(lignes: list) -> float:
    return sum(quantite(d) * float(d.get("valeur") or 0) for d in lignes)


def par_lieu(lignes: list) -> dict:
    """{lieu: valeur totale} (lieu vide : « sans lieu » est géré à l'affichage)."""
    res: dict = {}
    for d in lignes:
        res[d.get("lieu", "")] = res.get(d.get("lieu", ""), 0.0) + quantite(d) * float(d.get("valeur") or 0)
    return res


def garantie_proche(d: dict, aujourdhui: date, delai: int = DELAI_GARANTIE) -> int | None:
    """Jours restants avant la fin de garantie (négatif : terminée depuis peu), si elle tombe dans le délai ; sinon None."""
    if not d.get("garantie"):
        return None
    j = (date.fromisoformat(d["garantie"]) - aujourdhui).days
    return j if -30 <= j <= delai else None


def montant(v: float, devise: str) -> str:
    t = ("%.2f" % v).rstrip("0").rstrip(".")
    ent, _p, dec = t.partition(".")
    ent = f"{int(ent):,}".replace(",", " ")
    return (ent + ("," + dec if dec else "") + " " + devise).strip()


def resume(lignes: list, reglages: dict) -> str:
    dev = reglages.get("devise", "€")
    lieux = {k: v for k, v in par_lieu(lignes).items() if v}
    txt = _("<b>%d</b> objet(s) · valeur totale <b>%s</b>") % (int(sum(quantite(d) for d in lignes)), montant(valeur_totale(lignes), dev))
    if lieux:
        top = sorted(lieux.items(), key=lambda x: -x[1])[:4]
        txt += " · " + ", ".join(f"{k or _('sans lieu')} : {montant(v, dev)}" for k, v in top)
    n = sum(1 for d in lignes if garantie_proche(d, date.today()) is not None)
    if n:
        txt += " · <span style='color:#c0392b'><b>%s</b></span>" % (_("%d garantie(s) à surveiller") % n)
    return txt


def couleur(d: dict) -> str | None:
    j = garantie_proche(d, date.today())
    return None if j is None else ("#f4b6b0" if j < 0 else "#ffe2a8")


def a_faire(texte: str, aujourdhui: date | None = None) -> str | None:
    """Pastille de la liste : des garanties qui se terminent bientôt (ou viennent de se terminer)."""
    auj = aujourdhui or date.today()
    n = sum(1 for d in tf.lire(texte, MARQUE, COLONNES, ("devise",)).lignes if garantie_proche(d, auj) is not None)
    return _("%d garantie(s) à surveiller") % n if n else None


def texte_neuf() -> str:
    return tf.ecrire(tf.Document({"devise": "€"}), MARQUE, COLONNES, [_(c.titre) for c in COLONNES])


def exemples(aujourdhui: date | None = None) -> list:
    auj = aujourdhui or date.today()
    j = lambda n: (auj + timedelta(days=n)).isoformat()                    # noqa: E731
    lignes = [
        {"objet": _("Téléviseur"), "categorie": _("Image et son"), "lieu": _("Salon"), "quantite": "1", "valeur": "650", "achat": j(-700), "garantie": j(30)},
        {"objet": _("Lave-linge"), "categorie": _("Électroménager"), "lieu": _("Cuisine"), "quantite": "1", "valeur": "480", "achat": j(-300), "garantie": j(400)},
        {"objet": _("Chaises"), "categorie": _("Mobilier"), "lieu": _("Salle à manger"), "quantite": "4", "valeur": "45"},
    ]
    return [(_("Inventaire (exemples)"), _("Exemple · Mon inventaire"),
             tf.ecrire(tf.Document({"devise": "€"}, [tf.normaliser(COLONNES, d) for d in lignes]), MARQUE, COLONNES, [_(c.titre) for c in COLONNES]))]


TYPE = TypeFiche("inventaire", N_("Inventaire"), "package-x-generic", modele=texte_neuf, a_faire=a_faire)

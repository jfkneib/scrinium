# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Collection : ce que l'on a, ce que l'on cherche, ce que l'on a prêté (sans interface). Le tableau est géré par `core/table_fiche.py`."""
from datetime import date

from scrinium.core import table_fiche as tf
from scrinium.core.types_fiche import TypeFiche
from scrinium.i18n import N_, _

MARQUE = "#scrinium-collection"
AI, CHERCHE, PRETE = "Je l'ai", "Je le cherche", "Prêté"
COLONNES = [tf.Colonne("titre", N_("Titre")), tf.Colonne("auteur", N_("Auteur ou artiste")), tf.Colonne("serie", N_("Série ou numéro")),
            tf.Colonne("etat", N_("État"), "choix", (N_("Neuf"), N_("Très bon"), N_("Bon"), N_("Moyen"), N_("Abîmé"))),
            tf.Colonne("statut", N_("Statut"), "choix", (N_("Je l'ai"), N_("Je le cherche"), N_("Prêté"))),
            tf.Colonne("prix", N_("Prix payé"), "nombre"), tf.Colonne("note", N_("Note"))]
REGLAGES = (("devise", N_("Devise")),)


def compter(lignes: list) -> dict:
    return {"ai": sum(1 for d in lignes if d.get("statut") in ("", AI)), "cherche": sum(1 for d in lignes if d.get("statut") == CHERCHE),
            "prete": sum(1 for d in lignes if d.get("statut") == PRETE)}


def depense(lignes: list) -> float:
    return sum(float(d.get("prix") or 0) for d in lignes if d.get("statut") in ("", AI, PRETE))


def resume(lignes: list, reglages: dict) -> str:
    n = compter(lignes)
    dev = reglages.get("devise", "€")
    t = _("<b>%(a)d</b> dans la collection · <b>%(c)d</b> recherché(s)") % {"a": n["ai"] + n["prete"], "c": n["cherche"]}
    if n["prete"]:
        t += " · <span style='color:#c0392b'><b>%s</b></span>" % (_("%d prêté(s)") % n["prete"])
    d = depense(lignes)
    if d:
        t += " · " + _("payé en tout : <b>%s</b>") % (("%.2f" % d).rstrip("0").rstrip(".") + " " + dev).strip()
    return t


def couleur(d: dict) -> str | None:
    return {CHERCHE: "#ffe2a8", PRETE: "#cfe3ff"}.get(d.get("statut", ""))


def a_faire(texte: str, aujourdhui: date | None = None) -> str | None:
    """Pastille de la liste : des objets prêtés à récupérer."""
    n = compter(tf.lire(texte, MARQUE, COLONNES, ("devise",)).lignes)["prete"]
    return _("%d prêté(s) à récupérer") % n if n else None


def texte_neuf() -> str:
    return tf.ecrire(tf.Document({"devise": "€"}), MARQUE, COLONNES, [_(c.titre) for c in COLONNES])


def exemples() -> list:
    lignes = [
        {"titre": _("Dune"), "auteur": "Frank Herbert", "serie": "1", "etat": "Bon", "statut": AI, "prix": "8"},
        {"titre": _("Le Messie de Dune"), "auteur": "Frank Herbert", "serie": "2", "statut": CHERCHE},
        {"titre": _("Les Enfants de Dune"), "auteur": "Frank Herbert", "serie": "3", "etat": "Bon", "statut": PRETE, "note": _("prêté à un ami")},
    ]
    return [(_("Collection (exemples)"), _("Exemple · Ma collection"),
             tf.ecrire(tf.Document({"devise": "€"}, [tf.normaliser(COLONNES, d) for d in lignes]), MARQUE, COLONNES, [_(c.titre) for c in COLONNES]))]


TYPE = TypeFiche("collection", N_("Collection"), "bookmarks", modele=texte_neuf, a_faire=a_faire)

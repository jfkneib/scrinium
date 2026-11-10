# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Mots de passe : un carnet de sites, identifiants et mots de passe (sans interface). Le tableau est géré par `core/table_fiche.py`.

Limites honnêtes : le texte n'est protégé que si la fiche est **verrouillée** (chiffrée par Scrinium). Une fiche non verrouillée est un fichier
lisible par quiconque accède au disque. Un gestionnaire dédié (KeePassXC, Bitwarden…) est plus sûr et mieux éprouvé."""
import secrets
import string

from scrinium.core import table_fiche as tf
from scrinium.core.types_fiche import TypeFiche
from scrinium.i18n import N_, _

MARQUE = "#scrinium-motsdepasse"
COLONNES = [tf.Colonne("site", N_("Site ou service")), tf.Colonne("identifiant", N_("Identifiant")), tf.Colonne("secret", N_("Mot de passe"), "secret"),
            tf.Colonne("adresse", N_("Adresse")), tf.Colonne("note", N_("Note"))]
AVERTISSEMENT = N_("⚠ Carnet pratique, pas un coffre-fort : verrouillez cette fiche (bouton « Verrouiller… ») pour qu'elle soit chiffrée. "
                   "Un gestionnaire dédié (KeePassXC, Bitwarden…) reste plus sûr.")


def generer(longueur: int = 20) -> str:
    """Un mot de passe aléatoire (module `secrets`)."""
    alphabet = string.ascii_letters + string.digits + "-_.!?+="
    longueur = min(128, max(8, longueur))
    while True:
        s = "".join(secrets.choice(alphabet) for _i in range(longueur))
        if any(c.islower() for c in s) and any(c.isupper() for c in s) and any(c.isdigit() for c in s):
            return s


def resume(lignes: list, reglages: dict) -> str:
    faibles = sum(1 for d in lignes if d.get("secret") and len(d["secret"]) < 10)
    doubles = len(lignes) - len({d["secret"] for d in lignes if d.get("secret")}) - sum(1 for d in lignes if not d.get("secret"))
    t = _("<b>%d</b> entrée(s)") % len(lignes)
    if faibles:
        t += " · " + _("%d mot(s) de passe court(s) (moins de 10 caractères)") % faibles
    if doubles > 0:
        t += " · " + _("%d mot(s) de passe utilisé(s) plusieurs fois") % doubles
    return t


def texte_neuf() -> str:
    return tf.ecrire(tf.Document(), MARQUE, COLONNES, [_(c.titre) for c in COLONNES])


def exemples() -> list:
    lignes = [{"site": _("Exemple de site"), "identifiant": "moi@example.org", "secret": "exemple-a-remplacer", "adresse": "https://example.org"}]
    return [(_("Mots de passe (exemples)"), _("Exemple · Mes mots de passe"),
             tf.ecrire(tf.Document({}, [tf.normaliser(COLONNES, d) for d in lignes]), MARQUE, COLONNES, [_(c.titre) for c in COLONNES]))]


TYPE = TypeFiche("motsdepasse", N_("Mots de passe"), "dialog-password", modele=texte_neuf)

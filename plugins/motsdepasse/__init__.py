# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « Mots de passe » : un carnet de sites, identifiants et mots de passe (voir `logique.py`).
Mots de passe masqués à l'écran, copie dans le presse-papiers vidé après 20 s, bandeau d'avertissement. À verrouiller. Type non exécutable."""
from scrinium.core.plugins import Plugin
from scrinium.i18n import N_, _
from scrinium.ui.table_fiche import Spec, VueTable

from . import logique

DOC = _(
    "Un carnet de sites, identifiants et mots de passe, dans une fiche.\n"
    "\n"
    "• Nouvelle fiche > « Mots de passe » : « Ajouter une entrée… » (site, identifiant, mot de passe, adresse, note). Les mots de passe sont masqués à l'écran ; "
    "« Afficher les secrets » les montre. « Générer » propose un mot de passe aléatoire de 20 caractères.\n"
    "• Clic droit sur une ligne > « Copier : Mot de passe » : il est copié dans le presse-papiers, qui est vidé après 20 secondes.\n"
    "• IMPORTANT : verrouillez la fiche (chiffrement par Scrinium). Une fiche non verrouillée est un fichier lisible par quiconque accède au disque. "
    "Les fiches verrouillées et fermées ne sont ni lues ni cherchées.\n"
    "• Honnêtement : un gestionnaire dédié (KeePassXC, Bitwarden…) reste plus sûr et mieux éprouvé. Cette fiche est un carnet pratique, pas un coffre-fort.")


class MotsDePassePlugin(Plugin):
    api = 1

    def activer(self, ctx):
        ctx.ajouter_doc(_("Extension Mots de passe"), DOC)
        for theme, titre, texte in logique.exemples():
            ctx.ajouter_exemple(theme, titre, texte, "dialog-password")
        if ctx.ui is not None:
            ctx.ui.enregistrer_type(logique.TYPE, VueTable(Spec(logique.MARQUE, logique.COLONNES, N_("Ajouter une entrée…"), nom_obligatoire="site",
                                                                resume=logique.resume, avertissement=logique.AVERTISSEMENT, copier=("secret",), generer=logique.generer)))

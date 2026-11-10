# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « Inventaire » : ce que l'on possède, où, pour combien, jusqu'à quand c'est garanti (voir `logique.py`).

Une fiche « Inventaire » = un tableau (objet, catégorie, lieu, quantité, valeur, achat, garantie), avec la valeur totale et par lieu en haut. Une
garantie qui se termine sous 60 jours colore la ligne et met une pastille sur l'icône de la fiche. Type non exécutable : la fiche ne lance rien."""
from scrinium.core.plugins import Plugin
from scrinium.i18n import N_, _
from scrinium.ui.table_fiche import Spec, VueTable

from . import logique

DOC = _(
    "Ce que vous possédez, où c'est rangé, ce que cela vaut : utile pour l'assurance, un déménagement ou pour retrouver quelque chose.\n"
    "\n"
    "• Nouvelle fiche > « Inventaire » : « Ajouter un objet… » (objet, catégorie, lieu, quantité, valeur unitaire, date d'achat, fin de garantie, note). "
    "Cliquez sur un titre de colonne pour trier ; la recherche filtre le tableau.\n"
    "• En haut : le nombre d'objets, la valeur totale et la valeur par lieu (la devise se règle à côté). Les valeurs sont celles que vous saisissez.\n"
    "• Une garantie qui se termine sous 60 jours (ou vient de se terminer) colore la ligne et met une pastille rouge sur l'icône de la fiche.\n"
    "• Le texte reste un tableau Markdown lisible, cherchable et partageable ; rien n'est exécuté. Photos : joignez-les à la fiche.")


def _spec() -> Spec:
    return Spec(logique.MARQUE, logique.COLONNES, N_("Ajouter un objet…"), reglages=logique.REGLAGES, resume=logique.resume, couleur=logique.couleur)


class InventairePlugin(Plugin):
    api = 1

    def activer(self, ctx):
        ctx.ajouter_doc(_("Extension Inventaire"), DOC)
        for theme, titre, texte in logique.exemples():
            ctx.ajouter_exemple(theme, titre, texte, "package-x-generic")
        if ctx.ui is not None:
            ctx.ui.enregistrer_type(logique.TYPE, VueTable(_spec()))

# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension Scrinium « Collection » : livres, disques, jeux, vins, timbres… ce que l'on a, ce que l'on cherche, ce que l'on a prêté (voir `logique.py`).
Une fiche = un tableau ; une pastille sur l'icône de la fiche quand quelque chose est prêté. Type non exécutable : la fiche ne lance rien."""
from scrinium.core.plugins import Plugin
from scrinium.i18n import N_, _
from scrinium.ui.table_fiche import Spec, VueTable

from . import logique

DOC = _(
    "Pour un passionné : livres, disques, jeux, vins, timbres, figurines… savoir ce que l'on a, ce qui manque et à qui on l'a prêté.\n"
    "\n"
    "• Nouvelle fiche > « Collection » : « Ajouter à la collection… » (titre, auteur ou artiste, série ou numéro, état, statut, prix payé, note). "
    "Le statut est « Je l'ai », « Je le cherche » ou « Prêté » ; les lignes recherchées sont en jaune, les prêtées en bleu.\n"
    "• Pour compléter une série : triez par « Série ou numéro » et repérez les « Je le cherche ». En haut : combien vous en avez, combien il en manque, "
    "combien sont prêtés et ce que vous avez payé en tout.\n"
    "• Tant que quelque chose est prêté, une pastille rouge est posée sur l'icône de la fiche : c'est le rappel de le récupérer.\n"
    "• Le texte reste un tableau Markdown lisible, cherchable et partageable ; rien n'est exécuté.")


class CollectionPlugin(Plugin):
    api = 1

    def activer(self, ctx):
        ctx.ajouter_doc(_("Extension Collection"), DOC)
        for theme, titre, texte in logique.exemples():
            ctx.ajouter_exemple(theme, titre, texte, "bookmarks")
        if ctx.ui is not None:
            ctx.ui.enregistrer_type(logique.TYPE, VueTable(Spec(logique.MARQUE, logique.COLONNES, N_("Ajouter à la collection…"),
                                                                reglages=logique.REGLAGES, resume=logique.resume, couleur=logique.couleur)))

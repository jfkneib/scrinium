# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Entrées de clic droit fournies par la fenêtre et les extensions : [(texte, fn, icône)].

Une entrée dont `fn` est un `SousMenu` devient un sous-menu, dont le contenu est demandé au moment où le menu s'ouvre (liste qui change :
applications, modèles…). Ce module est partagé par les trois menus (texte, aperçu, vue d'un type de fiche)."""
from .icons import icone


class SousMenu:
    """`fournisseur()` renvoie les entrées [(texte, fn, icône)] du sous-menu, calculées à chaque ouverture du menu."""

    def __init__(self, fournisseur):
        self.fournisseur = fournisseur

    def __call__(self, *_a):          # jamais appelé : une entrée de sous-menu n'agit pas par elle-même
        return None


def remplir(menu, entrees) -> None:
    for texte, fn, ic in entrees:
        ico = icone(ic) if ic else icone("view-pim-notes")
        if isinstance(fn, SousMenu):
            sous = menu.addMenu(ico, texte)
            remplir(sous, fn.fournisseur())
            sous.setEnabled(not sous.isEmpty())
        else:
            menu.addAction(ico, texte, fn)

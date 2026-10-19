# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Ajouter du texte (typiquement la sortie d'une commande) à une fiche. Aucune dépendance graphique.

Utilisé par `scrinium ajouter` (tube : `ip a | scrinium ajouter -t Informatique -f Réseau`), directement ou par l'instance
déjà ouverte, qui écrit alors elle-même pour que l'éditeur reste cohérent.
"""
import re
import time

from .store import Fiche, Store, Theme

TAILLE_MAX = 256 * 1024        # octets de texte conservés par ajout
MARQUE = "\n[… tronqué]"


def tronquer(texte: str) -> str:
    brut = texte.encode("utf-8")
    if len(brut) <= TAILLE_MAX:
        return texte
    return brut[:TAILLE_MAX].decode("utf-8", "ignore") + MARQUE


def bloc(texte: str, commande: str = "", brut: bool = False, horodatage: str | None = None) -> str:
    """Texte à insérer : `brut` = tel quel ; sinon un titre daté (et la commande) puis le texte entre barrières ```."""
    texte = texte.replace("\r\n", "\n").rstrip("\n")
    if brut:
        return texte + "\n"
    quand = horodatage or time.strftime("%Y-%m-%d %H:%M")
    entete = f"### {quand}" + (f" — {commande.strip()}" if commande.strip() else "")
    plus_long = max((len(m) for m in re.findall(r"`+", texte)), default=0)
    barriere = "`" * max(3, plus_long + 1)      # le texte peut lui-même contenir ```
    return f"{entete}\n{barriere}\n{texte}\n{barriere}\n"


def _theme(store: Store, nom: str) -> Theme:
    th = store.theme(nom) or next((t for t in store.themes if t.nom.lower() == nom.strip().lower()), None)
    if th is None:
        raise ValueError(f"thème introuvable : {nom} (thèmes : {', '.join(t.nom for t in store.themes) or 'aucun'})")
    return th


def ajouter(store: Store, theme: str, titre: str, texte: str, commande: str = "", remplacer: bool = False,
            brut: bool = False, horodatage: str | None = None) -> tuple[Theme, Fiche]:
    """Ajoute le texte à la fin de la fiche (la crée si elle n'existe pas ; `remplacer` : remplace tout son texte).
    ValueError : thème inconnu, titre vide, ou fiche verrouillée fermée (jamais d'écriture en clair d'une fiche verrouillée)."""
    th = _theme(store, theme)
    titre = titre.strip()
    if not titre:
        raise ValueError("titre de fiche vide")
    f = next((x for x in th.fiches if x.titre.lower() == titre.lower()), None)
    if f is not None and f.fermee:
        raise ValueError(f"fiche verrouillée : « {f.titre} » doit d'abord être déverrouillée dans la fenêtre de Scrinium")
    ajout = bloc(tronquer(texte), commande, brut, horodatage)
    if f is None:
        f = store.nouvelle_fiche(th)
        store.enregistrer(th, f, titre, ajout)
        return th, f
    actuel = (f.texte or "").rstrip("\n")
    store.enregistrer(th, f, f.titre, ajout if remplacer or not actuel.strip() else f"{actuel}\n\n{ajout}")
    return th, f

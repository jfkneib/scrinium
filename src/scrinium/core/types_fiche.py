# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Fiches typées : « tout est fiche » (principe 9 de docs/principes.md).

Ce que Scrinium gère au-delà du texte libre (répertoire, applications, actions, agenda…) vit dans des fiches ordinaires, repérées par
une **marque** à la première ligne : `#scrinium-<type>` (suivie, au besoin, de paramètres : `#scrinium-repertoire index=0`). La marque
est dans le texte : elle survit au partage, à la synchronisation, à la sauvegarde et à la copie. Partage, verrouillage, recherche,
corbeille et dépôt de l'extérieur marchent donc pour tous les types, sans code en plus.

Ce module est le **registre** (sans interface) : un type = un nom, un libellé, une icône, de quoi l'imprimer en texte, et un drapeau
`executable`. L'affichage (la « vue » du type) est enregistré côté interface (`ui/fenetre.py`, `UiPlugin.enregistrer_type`).

Sécurité : une fiche d'un type `executable` (qui lance des commandes) est **inerte tant que l'utilisateur ne l'a pas validée**, quelle
que soit son origine (partage, dépôt, lien, fichier déposé à la main). La validation est liée à l'**empreinte du texte** : si le texte
change ensuite (une mise à jour reçue d'ailleurs, par exemple), elle tombe et la fiche redevient inerte. Voir `Store.fiche_validee`.
Une fiche verrouillée n'a pas de type lisible (son texte est chiffré)."""
import hashlib
import re
from dataclasses import dataclass
from typing import Callable

_NOM = re.compile(r"[a-z][a-z0-9-]{0,30}")
_MARQUE = re.compile(r"\A\ufeff?#scrinium-([a-z][a-z0-9-]{0,30})(?=[ \t]|\r?\n|\Z)")


@dataclass(frozen=True)
class TypeFiche:
    nom: str                                          # identifiant court, minuscules : « repertoire » (marque : #scrinium-repertoire)
    libelle: str                                      # nom affiché, à traduire (N_)
    icone: str = ""                                   # nom d'icône du thème, pour la liste des fiches
    executable: bool = False                          # la fiche déclenche des commandes : inerte tant qu'elle n'est pas validée
    en_markdown: Callable[[str], str] | None = None   # rendu texte pour l'impression et l'export PDF (sinon : le texte tel quel)
    modele: Callable[[], str] | None = None           # texte d'une fiche neuve de ce type (sinon : la marque seule) ; menu « Nouvelle fiche »
    a_faire: Callable[[str], str | None] | None = None  # texte -> raison courte (déjà traduite) s'il y a quelque chose à faire dans la fiche,
                                                        # sinon None : une pastille s'affiche sur son icône dans la liste

    @property
    def marque(self) -> str:
        return "#scrinium-" + self.nom

    def texte_neuf(self) -> str:
        """Texte d'une fiche neuve de ce type."""
        return self.modele() if self.modele else self.marque + "\n"


_types: dict = {}


def _integres() -> None:
    from . import repertoire  # noqa: F401  (s'enregistre à l'import)


def enregistrer(t: TypeFiche) -> None:
    """Ajoute un type. Un nom déjà pris (par un autre type) est refusé : deux types ne partagent pas une marque."""
    if not isinstance(t, TypeFiche) or not _NOM.fullmatch(t.nom or ""):
        raise ValueError("nom de type invalide : minuscules, chiffres et tirets, 31 caractères au plus")
    if t.nom in _types and _types[t.nom] != t:
        raise ValueError(f"type « {t.nom} » déjà enregistré")
    _types[t.nom] = t


def desenregistrer(nom: str) -> None:
    _types.pop(nom, None)


def types() -> list:
    _integres()
    return sorted(_types.values(), key=lambda t: t.nom)


def marque(texte: str | None) -> str | None:
    """Le nom lu dans la marque de la première ligne, que le type soit connu ou non ; None s'il n'y en a pas."""
    m = _MARQUE.match(texte or "")
    return m.group(1) if m else None


def type_de(texte: str | None) -> TypeFiche | None:
    """Le type de la fiche d'après son texte (None : texte libre, type inconnu ou fiche verrouillée sans texte)."""
    _integres()
    nom = marque(texte)
    return _types.get(nom) if nom else None


def icone_de(texte: str | None) -> str:
    t = type_de(texte)
    return t.icone if t else ""


def a_faire_de(texte: str | None) -> str | None:
    """La raison pour laquelle la fiche demande de l'attention (pastille sur l'icône), ou None. Jamais d'exception : un type en panne n'abîme pas la liste."""
    t = type_de(texte)
    if t is None or t.a_faire is None:
        return None
    try:
        return t.a_faire(texte or "") or None
    except Exception:
        return None


def en_markdown(texte: str | None) -> str:
    """Le texte à imprimer : le rendu du type s'il en a un, sinon le texte tel quel."""
    t = type_de(texte)
    return t.en_markdown(texte or "") if t and t.en_markdown else (texte or "")


def empreinte(texte: str | None) -> str:
    """Empreinte du texte d'une fiche (fins de ligne normalisées) : ce à quoi la validation d'une fiche exécutable est liée."""
    return hashlib.sha256((texte or "").replace("\r\n", "\n").encode("utf-8")).hexdigest()

# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension « Documents » : logique sans interface. Une fiche `#scrinium-objet` = une description (le texte de la fiche) + un fichier
gardé comme pièce jointe (`.pj`, chiffrée avec la fiche si elle est verrouillée). Type non exécutable : rien n'est lancé à l'ouverture."""
import mimetypes

from scrinium.core.types_fiche import TypeFiche, marque as _marque_de
from scrinium.i18n import N_

NOM = "objet"
MARQUE = "#scrinium-" + NOM
TYPE_INCONNU = "application/octet-stream"
SOURCE_MAX = 100 * 1024 * 1024            # fichier source refusé au-delà, avant même de le lire (les limites de la fiche s'appliquent ensuite)


def description(texte: str | None) -> str:
    """Le texte de la fiche sans sa marque (première ligne) ni les lignes vides qui la suivent."""
    brut = texte or ""
    if _marque_de(brut) == NOM:
        brut = brut.partition("\n")[2]
    return brut.lstrip("\r\n")


def texte_de(desc: str) -> str:
    """Texte de la fiche : la marque, puis la description."""
    desc = (desc or "").strip("\r\n")
    return MARQUE + "\n" + ("\n" + desc + "\n" if desc else "")


def type_mime(nom: str) -> str:
    """Type MIME d'après le nom du fichier (octet-stream s'il est inconnu ou mal formé)."""
    t = mimetypes.guess_type(nom or "", strict=False)[0] or TYPE_INCONNU
    return t.lower() if "/" in t else TYPE_INCONNU


def taille_lisible(octets: int) -> tuple:
    """("ko" ou "mo", nombre en texte) : l'interface choisit le format traduit (« %s Ko », « %s Mo »)."""
    if octets < 1024 * 1024:
        return "ko", str(max(1, round(octets / 1024)))
    return "mo", f"{octets / 1048576:.1f}".replace(".", ",")


def _modele() -> str:
    return texte_de("")


TYPE = TypeFiche(NOM, N_("Fiche-document"), icone="x-office-document", executable=False,
                 en_markdown=description, modele=_modele)

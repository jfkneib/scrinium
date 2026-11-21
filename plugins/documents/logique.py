# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extension « Documents » : logique sans interface. Une fiche `#scrinium-objet` = une description (le texte de la fiche) + un fichier
gardé comme pièce jointe (`.pj`, chiffrée avec la fiche si elle est verrouillée). Type non exécutable : rien n'est lancé à l'ouverture."""
import mimetypes
import os
import re
import shutil
import tempfile
from pathlib import Path

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


def titre_de(nom_fichier: str) -> str:
    """Titre d'une fiche créée à partir d'un fichier : son nom sans l'extension (le nom entier s'il n'en reste rien)."""
    nom = Path((nom_fichier or "").replace("\\", "/")).name
    return Path(nom).stem.strip() or nom.strip() or "document"


def type_mime(nom: str) -> str:
    """Type MIME d'après le nom du fichier (octet-stream s'il est inconnu ou mal formé)."""
    t = mimetypes.guess_type(nom or "", strict=False)[0] or TYPE_INCONNU
    return t.lower() if "/" in t else TYPE_INCONNU


def taille_lisible(octets: int) -> tuple:
    """("ko" ou "mo", nombre en texte) : l'interface choisit le format traduit (« %s Ko », « %s Mo »)."""
    if octets < 1024 * 1024:
        return "ko", str(max(1, round(octets / 1024)))
    return "mo", f"{octets / 1048576:.1f}".replace(".", ",")


def nom_sur_disque(nom: str) -> str:
    """Nom de fichier sûr pour la copie de travail : sans dossier, sans caractère de contrôle ni séparateur, jamais vide ni caché."""
    base = re.sub(r"[\x00-\x1f\\/:*?\"<>|]", "_", Path((nom or "").replace("\\", "/")).name).strip(" .")
    return (base or "document")[:120]


def copie_de_travail(dossier: Path, nom: str, donnees: bytes) -> Path:
    """Écrit `donnees` dans un sous-dossier neuf (droits 0700) de `dossier`, sous le nom d'origine (droits 0600) ; renvoie le chemin.
    Cette copie est EN CLAIR, même pour une fiche verrouillée : elle ne doit durer que le temps de l'édition (`purger`)."""
    dossier.mkdir(parents=True, exist_ok=True)
    try:
        dossier.chmod(0o700)
    except OSError:
        pass
    chemin = Path(tempfile.mkdtemp(prefix="edition-", dir=dossier)) / nom_sur_disque(nom)
    fd = os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(donnees)
    return chemin


def purger(chemin: Path | None) -> None:
    """Supprime une copie de travail et son sous-dossier (rien si elle n'existe plus)."""
    if chemin is not None:
        shutil.rmtree(chemin.parent, ignore_errors=True)


def purger_tout(dossier: Path) -> None:
    """Supprime les copies de travail restées d'une session interrompue (sous-dossiers `edition-*`)."""
    if dossier.is_dir():
        for d in dossier.glob("edition-*"):
            shutil.rmtree(d, ignore_errors=True)


class Surveillance:
    """Repère qu'un fichier a été enregistré par une autre application. On l'interroge à intervalles réguliers (`sonder`) : la
    signature (date, taille) doit avoir changé ET être la même à deux interrogations de suite (l'application a fini d'écrire)."""

    def __init__(self, chemin: Path):
        self.chemin = chemin
        self.base = self._signature()
        self._vu = None

    def _signature(self):
        try:
            st = self.chemin.stat()
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size)

    def sonder(self) -> bool:
        """Vrai quand une modification stable est à reprendre ; l'appelant la reprend puis appelle `acquitter`."""
        sig = self._signature()
        if sig is None or sig == self.base:
            self._vu = None
            return False
        if sig == self._vu:
            return True
        self._vu = sig
        return False

    def a_change(self) -> bool:
        """Le fichier n'est plus tel qu'à la dernière reprise (même si la modification n'est pas encore stable)."""
        sig = self._signature()
        return sig is not None and sig != self.base

    def acquitter(self) -> None:
        """La modification courante a été reprise (ou abandonnée) : elle ne sera pas signalée de nouveau."""
        self.base = self._signature()
        self._vu = None


def _modele() -> str:
    return texte_de("")


TYPE = TypeFiche(NOM, N_("Fiche-document"), icone="x-office-document", executable=False,
                 en_markdown=description, modele=_modele)

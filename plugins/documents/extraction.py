# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Extraction du texte d'un document joint (sans interface), pour que la recherche (Ctrl+F) le trouve.

Formats : ODF (.odt .ods .odp), OOXML (.docx .xlsx .pptx), texte brut (.txt .md .csv…), et PDF si `pdftotext` (poppler-utils) est installé.
Les formats ZIP sont lus avec la bibliothèque standard : rien à installer. Jamais d'ancien format binaire OLE (.doc .xls).

Prudence : le fichier vient de n'importe où. Rien n'est extrait sur le disque, les membres de l'archive sont lus avec une taille maximale,
un XML qui déclare une DTD ou des entités est refusé, et le texte rendu est borné."""
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from xml.parsers import expat

TEXTE_MAX = 500_000                       # caractères gardés
MEMBRE_MAX = 30 * 1024 * 1024             # octets lus pour un membre de l'archive (une fois décompressé)
TOTAL_MAX = 60 * 1024 * 1024              # total décompressé lu pour un fichier
SOURCE_MAX = 30 * 1024 * 1024             # fichier source au-delà duquel on n'extrait pas
DELAI_PDF = 30                            # secondes accordées à pdftotext


class OutilManquant(Exception):
    """Le format est connu mais l'outil qui le lit n'est pas installé (le nom de l'outil est dans `args[0]`)."""


class FormatIllisible(Exception):
    """Fichier abîmé, trop gros une fois décompressé, ou XML refusé."""


# ---------- XML : lecture en flux, dans l'ordre du document ----------
_ODF_IGNORES = {"automatic-styles", "font-face-decls", "scripts", "styles", "master-styles"}


def _local(nom: str) -> str:
    return nom.rpartition(":")[2]


def _xml_en_texte(donnees: bytes, mode: str) -> str:
    """mode « odf » : tout le texte du contenu ; « ooxml » : seulement le contenu des éléments `t` (w:t, a:t, t des chaînes partagées)."""
    if b"<!DOCTYPE" in donnees[:4096].upper() or b"<!ENTITY" in donnees.upper():
        raise FormatIllisible("XML avec DTD ou entités : refusé")
    sortie, etat = [], {"ignore": 0, "dans_t": 0, "taille": 0}

    def ajouter(t: str) -> None:
        if etat["taille"] < TEXTE_MAX * 2:
            sortie.append(t)
            etat["taille"] += len(t)

    def debut(nom, attrs):
        n = _local(nom)
        if mode == "odf":
            if n in _ODF_IGNORES:
                etat["ignore"] += 1
            elif n == "tab":
                ajouter("\t")
            elif n == "line-break":
                ajouter("\n")
            elif n == "s":
                c = attrs.get("text:c", "1")
                ajouter(" " * min(int(c) if c.isdigit() else 1, 50))
        else:
            if n in ("t", "tab", "br", "cr"):
                if n == "t":
                    etat["dans_t"] += 1
                elif n == "tab":
                    ajouter("\t")
                else:
                    ajouter("\n")

    def fin(nom):
        n = _local(nom)
        if mode == "odf":
            if n in _ODF_IGNORES:
                etat["ignore"] = max(0, etat["ignore"] - 1)
            elif n in ("p", "h", "table-row", "list-item"):
                ajouter("\n")
            elif n == "table-cell":
                ajouter(" ")
        else:
            if n == "t":
                etat["dans_t"] = max(0, etat["dans_t"] - 1)
            elif n in ("p", "si", "tr"):
                ajouter("\n")
            elif n in ("tc", "c"):
                ajouter(" ")

    def texte(t):
        if mode == "odf":
            if not etat["ignore"]:
                ajouter(t)
        elif etat["dans_t"]:
            ajouter(t)

    p = expat.ParserCreate()
    p.buffer_text = True
    p.StartElementHandler, p.EndElementHandler, p.CharacterDataHandler = debut, fin, texte
    p.EntityDeclHandler = lambda *a: (_ for _ in ()).throw(FormatIllisible("entité refusée"))
    try:
        p.Parse(donnees, True)
    except expat.ExpatError as ex:
        raise FormatIllisible(str(ex)) from ex
    return "".join(sortie)


def _membres(z: zipfile.ZipFile, noms: list, restant: list) -> list:
    """Octets des membres demandés (ceux qui existent), avec les plafonds de taille."""
    res = []
    for nom in noms:
        try:
            info = z.getinfo(nom)
        except KeyError:
            continue
        if info.file_size > MEMBRE_MAX or info.file_size > restant[0]:
            raise FormatIllisible("membre trop gros une fois décompressé")
        with z.open(info) as f:
            donnees = f.read(info.file_size + 1)
        if len(donnees) > info.file_size:
            raise FormatIllisible("taille annoncée fausse")
        restant[0] -= len(donnees)
        res.append(donnees)
    return res


def _zip(donnees: bytes, suffixe: str) -> str:
    import io
    try:
        z = zipfile.ZipFile(io.BytesIO(donnees))
    except zipfile.BadZipFile as ex:
        raise FormatIllisible(str(ex)) from ex
    restant = [TOTAL_MAX]
    with z:
        if len(z.namelist()) > 20000:
            raise FormatIllisible("trop de membres")
        if suffixe in (".odt", ".ods", ".odp"):
            return "".join(_xml_en_texte(d, "odf") for d in _membres(z, ["content.xml"], restant))
        if suffixe == ".docx":
            noms = ["word/document.xml", "word/footnotes.xml", "word/endnotes.xml"]
        elif suffixe == ".xlsx":
            noms = ["xl/sharedStrings.xml"]
        else:                                                                  # .pptx : les diapositives dans l'ordre de leur numéro
            def numero(n):
                m = re.search(r"(\d+)\.xml\Z", n)
                return int(m.group(1)) if m else 0
            noms = sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)), key=numero)[:500]
        return "".join(_xml_en_texte(d, "ooxml") for d in _membres(z, noms, restant))


# ---------- texte brut et PDF ----------
_TEXTE_BRUT = {".txt", ".md", ".markdown", ".csv", ".tsv", ".log", ".json", ".yaml", ".yml", ".ini", ".conf", ".xml", ".html", ".htm", ".tex", ".rst"}


def _brut(donnees: bytes) -> str:
    if b"\x00" in donnees[:4096]:
        raise FormatIllisible("contenu binaire")
    for codage in ("utf-8-sig", "cp1252"):
        try:
            return donnees.decode(codage)
        except UnicodeDecodeError:
            continue
    return donnees.decode("latin-1")


def _pdf(donnees: bytes) -> str:
    exe = shutil.which("pdftotext")
    if exe is None:
        raise OutilManquant("pdftotext")
    try:
        r = subprocess.run([exe, "-q", "-enc", "UTF-8", "-", "-"], input=donnees, capture_output=True, timeout=DELAI_PDF)
    except (OSError, subprocess.SubprocessError) as ex:
        raise FormatIllisible(str(ex)) from ex
    if r.returncode != 0:
        raise FormatIllisible("pdftotext a échoué")
    return r.stdout[:TEXTE_MAX * 4].decode("utf-8", errors="replace")


def prise_en_charge(nom: str, type_: str = "") -> bool:
    s = Path(nom or "").suffix.lower()
    return s in (".odt", ".ods", ".odp", ".docx", ".xlsx", ".pptx", ".pdf") or s in _TEXTE_BRUT or (type_ or "").startswith("text/")


def extraire(nom: str, type_: str, donnees: bytes) -> str | None:
    """Texte du document, nettoyé et borné ; None si le format n'est pas pris en charge. OutilManquant ou FormatIllisible sinon."""
    s = Path(nom or "").suffix.lower()
    if len(donnees) > SOURCE_MAX or not prise_en_charge(nom, type_):
        return None
    if s in (".odt", ".ods", ".odp", ".docx", ".xlsx", ".pptx"):
        brut = _zip(donnees, s)
    elif s == ".pdf" or type_ == "application/pdf":
        brut = _pdf(donnees)
    else:
        brut = _brut(donnees)
    brut = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", brut)                # caractères de contrôle (sauf \t \n \r)
    brut = re.sub(r"[ \t]+", " ", brut)
    brut = re.sub(r"\s*\n\s*", "\n", brut).strip()
    return brut[:TEXTE_MAX]

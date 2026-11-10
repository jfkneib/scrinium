# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Répertoire : une fiche dont le texte est un tableau CSV, rangé par lettre (A-Z) d'après une colonne « d'index ».

Contacts (nom, téléphones, adresse…), livres, vocabulaire, inventaire… : les colonnes sont celles de l'utilisateur. Le tableau est du
texte ordinaire (il se verrouille, se cherche, se partage, se sauvegarde comme n'importe quelle fiche). Format du texte :

    #scrinium-repertoire index=0        ← marque (survit au partage) ; `index` = numéro de la colonne qui donne la lettre
    Nom,Prénom,Téléphones,…              ← en-tête : les noms des colonnes
    Dupont,Alice,"06 01 02 03 04",…      ← une ligne par entrée (CSV standard : guillemets, virgules et retours à la ligne permis)

Partie sans interface ; l'affichage est dans `ui/repertoire.py`."""
import csv
import io
import os
import quopri
import re
import shlex
import unicodedata

from ..i18n import N_
from .types_fiche import TypeFiche, enregistrer

MARQUE = "#scrinium-repertoire"
_MARQUE = re.compile(r"\A﻿?#scrinium-repertoire(?: +index=(\d+))?[ \t]*(?:\r?\n|\Z)")
LETTRES = tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ") + ("#",)
MAX_COLONNES = 30

# Modèles proposés à la création : (titre du modèle, colonnes, numéro de la colonne d'index)
MODELES = (
    (N_("Contacts (nom, téléphones, adresse, courriel)"), ("Nom", "Prénom", "Téléphones", "Adresse", "Courriel", "Lien", "Notes"), 0),
    (N_("Livres (titre, auteur, année)"), ("Titre", "Auteur", "Année", "Notes"), 0),
    (N_("Vocabulaire (mot, traduction, exemple)"), ("Mot", "Traduction", "Exemple"), 0),
    (N_("Tableau libre (nom, détails)"), ("Nom", "Détails"), 0),
)

# noms de colonnes d'exportateurs courants (carnets d'adresses) -> nom de colonne de Scrinium (pour l'import dans un modèle Contacts)
ALIAS = {
    "prenom": "Prénom", "firstname": "Prénom", "first name": "Prénom", "given name": "Prénom", "givenname": "Prénom",
    "lastname": "Nom", "last name": "Nom", "family name": "Nom", "surname": "Nom", "nom de famille": "Nom",
    "telephone": "Téléphones", "tel": "Téléphones", "phone": "Téléphones", "phones": "Téléphones", "mobile": "Téléphones",
    "portable": "Téléphones", "numero": "Téléphones", "phone 1 - value": "Téléphones", "phone 2 - value": "Téléphones",
    "address": "Adresse", "adresse postale": "Adresse",
    "email": "Courriel", "e-mail": "Courriel", "e-mail 1 - value": "Courriel", "e-mail 2 - value": "Courriel", "mail": "Courriel", "e-mail address": "Courriel", "email 1 - value": "Courriel",
    "adresse email": "Courriel", "adresse e-mail": "Courriel",
    "website": "Lien", "site web": "Lien", "site": "Lien", "url": "Lien", "web": "Lien", "page web": "Lien", "homepage": "Lien", "website 1 - value": "Lien",
    "note": "Notes", "commentaire": "Notes", "commentaires": "Notes", "comments": "Notes",
}


_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_URL = re.compile(r"https?://[^\s<>\"']+", re.I)
_TEL = re.compile(r"(?<![\w@./:-])\+?\(?\d[\d .()\-]{5,}\d(?![\w@])")
_DATE = re.compile(r"\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[-.]\d{1,2}[-.]\d{2,4}")


def actions(texte: str) -> list:
    """Éléments d'un texte sur lesquels on peut agir : [(type, valeur affichée, adresse à ouvrir)], sans doublon, dans l'ordre.
    type : « mail » (mailto:), « tel » (tel:, 7 à 15 chiffres ; les dates ne comptent pas), « web » (http ou https seulement)."""
    trouves, vus = [], set()

    def ajouter(type_, valeur, cible):
        if (type_, cible) not in vus:
            vus.add((type_, cible))
            trouves.append((type_, valeur, cible))
    reste = texte or ""
    for m in _URL.finditer(reste):
        ajouter("web", m.group(0).rstrip(".,;)"), m.group(0).rstrip(".,;)"))
    reste = _URL.sub(" ", reste)
    for m in _EMAIL.finditer(reste):
        ajouter("mail", m.group(0), "mailto:" + m.group(0))
    reste = _EMAIL.sub(" ", reste)
    for m in _TEL.finditer(reste):
        brut = m.group(0).strip()
        chiffres = re.sub(r"\D", "", brut)
        if not 7 <= len(chiffres) <= 15 or _DATE.fullmatch(brut):
            continue
        ajouter("tel", brut, "tel:" + ("+" if brut.startswith("+") else "") + chiffres)
    return trouves


# ---------- applications à lancer (« app:nom paramètre ») ----------
# La fiche ne contient que le NOM d'une application et un paramètre ; la commande réelle est déclarée sur chaque machine (réglages, jamais dans
# la fiche) : une fiche reçue ne peut donc rien lancer que l'utilisateur n'ait déclaré. Le paramètre est UN seul argument (pas de shell).
_APP = re.compile(r"(?<![\w:/@.-])app:([A-Za-z0-9_-]{1,30})(?:[ \t]+([^\n\r]{1,200}))?", re.I)
MAX_APPLICATIONS = 100


def applications_citees(texte: str) -> list:
    """[(nom en minuscules, paramètre)] des conventions « app:nom paramètre » d'un texte, sans doublon."""
    res = []
    for m in _APP.finditer(texte or ""):
        a = (m.group(1).lower(), (m.group(2) or "").strip())
        if a not in res:
            res.append(a)
    return res


def sans_applications(texte: str) -> str:
    """Le texte sans ses conventions « app:… » (le paramètre n'est alors pas pris pour un courriel ou un numéro)."""
    return _APP.sub(" ", texte or "")


def lire_declarations(texte: str) -> dict:
    """{nom: commande} depuis des lignes « nom = commande » (les lignes vides et celles qui commencent par # sont ignorées)."""
    res = {}
    for ligne in (texte or "").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        nom, _sep, cmd = ligne.partition("=")
        nom, cmd = nom.strip().lower(), cmd.strip()
        if re.fullmatch(r"[a-z0-9_-]{1,30}", nom) and cmd and len(res) < MAX_APPLICATIONS:
            res[nom] = cmd
    return res


def texte_declarations(declarations: dict) -> str:
    return "".join(f"{nom} = {cmd}\n" for nom, cmd in sorted(declarations.items()))


def commande_application(modele: str, valeur: str) -> list:
    """Arguments à lancer pour la commande déclarée `modele` (« {valeur} » est remplacé, entier, par le paramètre ; sans « {valeur} »,
    le paramètre est ajouté en dernier argument). ValueError si le paramètre est refusé : il ne doit pas pouvoir passer pour une option
    (commençant par « - ») ni contenir de caractère de contrôle."""
    valeur = (valeur or "").strip()
    if valeur.startswith("-") or any(ord(c) < 32 for c in valeur):
        raise ValueError("paramètre refusé")
    argv = shlex.split(modele, posix=os.name != "nt")
    if not argv:
        raise ValueError("commande vide")
    if any("{valeur}" in a for a in argv):
        return [a.replace("{valeur}", valeur) for a in argv]
    return argv + ([valeur] if valeur else [])


def sans_accents(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texte) if not unicodedata.combining(c))


def normaliser(nom: str) -> str:
    return " ".join(sans_accents(nom).replace("_", " ").lower().split())


def est_repertoire(texte: str | None) -> bool:
    return bool(texte) and _MARQUE.match(texte) is not None


TYPE = TypeFiche("repertoire", N_("Répertoire"), "x-office-address-book",
                 en_markdown=lambda texte: Tableau.depuis_texte(texte).en_markdown())
enregistrer(TYPE)             # « tout est fiche » : le répertoire est le premier type de fiche (voir types_fiche.py)


class Tableau:
    """Colonnes (noms), lignes (listes de textes, une valeur par colonne) et colonne d'index."""

    def __init__(self, colonnes, lignes=(), index: int = 0):
        self.colonnes = [str(c).strip() or f"Colonne {i + 1}" for i, c in enumerate(colonnes)] or ["Nom"]
        self.index = index if 0 <= index < len(self.colonnes) else 0
        self.lignes = [self._ajuster(l) for l in lignes]

    def _ajuster(self, ligne) -> list:
        ligne = [str(x).replace("\r\n", "\n").replace("\r", "\n").strip() for x in ligne][:len(self.colonnes)]
        return ligne + [""] * (len(self.colonnes) - len(ligne))

    def ligne_vide(self) -> list:
        return [""] * len(self.colonnes)

    # ---------- texte ----------
    @classmethod
    def depuis_texte(cls, texte: str) -> "Tableau":
        m = _MARQUE.match(texte or "")
        index = int(m.group(1)) if m and m.group(1) else 0
        corps = (texte or "")[m.end():] if m else (texte or "").lstrip("﻿")
        lignes = list(csv.reader(io.StringIO(corps, newline="")))
        if not lignes:
            return cls(["Nom"], [], 0)
        return cls(lignes[0], [l for l in lignes[1:] if any(x.strip() for x in l)], index)

    def en_texte(self) -> str:
        tampon = io.StringIO(newline="")
        w = csv.writer(tampon, lineterminator="\n")
        w.writerow(self.colonnes)
        for l in self.lignes:
            w.writerow(l)
        return f"{MARQUE} index={self.index}\n{tampon.getvalue()}"

    # ---------- classement ----------
    def cle(self, i: int) -> str:
        """Clé de classement de la ligne i : la colonne d'index, puis les autres ; sans accents ni casse."""
        l = self.lignes[i]
        return normaliser(" ".join([l[self.index]] + [x for k, x in enumerate(l) if k != self.index]))

    def lettre(self, i: int) -> str:
        """Lettre A-Z de la ligne (accents ignorés) ; « # » si l'index ne commence pas par une lettre. Index vide : première cellule remplie."""
        l = self.lignes[i]
        base = (l[self.index] or next((x for x in l if x), "")).strip()
        base = sans_accents(base).upper()
        return base[0] if base[:1] in LETTRES[:-1] else "#"

    def par_lettre(self) -> dict:
        """{lettre: [numéros de lignes, classés]} ; seules les lettres utilisées figurent."""
        res: dict = {}
        for i in sorted(range(len(self.lignes)), key=self.cle):
            res.setdefault(self.lettre(i), []).append(i)
        return res

    def libelle(self, i: int) -> str:
        """Texte court d'une ligne dans la liste : l'index, puis la première autre cellule remplie."""
        l = self.lignes[i]
        autre = next((x for k, x in enumerate(l) if k != self.index and x), "")
        return " · ".join(x.split("\n")[0] for x in (l[self.index], autre) if x) or "(vide)"

    def en_markdown(self) -> str:
        """Le tableau lisible (une section par lettre) : sert à l'export PDF."""
        morceaux = []
        for lettre, numeros in sorted(self.par_lettre().items(), key=lambda kv: LETTRES.index(kv[0])):
            morceaux.append(f"## {lettre}\n")
            morceaux.append("| " + " | ".join(self.colonnes) + " |")
            morceaux.append("|" + "---|" * len(self.colonnes))
            for i in numeros:
                morceaux.append("| " + " | ".join(x.replace("|", "\\|").replace("\n", "<br>") for x in self.lignes[i]) + " |")
            morceaux.append("")
        return "\n".join(morceaux)

    # ---------- colonnes ----------
    def changer_colonnes(self, colonnes: list, index: int) -> None:
        """Nouvelles colonnes : liste de (nom, ancien numéro ou None pour une colonne nouvelle). Les valeurs suivent leur colonne."""
        noms = [str(n).strip() or f"Colonne {k + 1}" for k, (n, _old) in enumerate(colonnes)] or ["Nom"]
        lignes = [[(l[old] if old is not None and 0 <= old < len(l) else "") for _n, old in colonnes] or [""] for l in self.lignes]
        self.colonnes, self.lignes = noms, lignes
        self.index = index if 0 <= index < len(noms) else 0

    # ---------- CSV ----------
    def exporter_csv(self, separateur: str = ",") -> bytes:
        """CSV en UTF-8 avec marque d'ordre des octets (reconnu par les tableurs) ; « ; » pour un Excel en français."""
        tampon = io.StringIO(newline="")
        w = csv.writer(tampon, delimiter=separateur, lineterminator="\r\n")
        w.writerow(self.colonnes)
        for l in self.lignes:
            w.writerow(l)
        return tampon.getvalue().encode("utf-8-sig")

    def importer(self, octets: bytes) -> tuple[int, list]:
        """Ajoute les lignes d'un fichier CSV (séparateur et codage reconnus). Les colonnes sont repérées par leur nom (sans accents ni
        casse, noms courants des carnets d'adresses compris) ; une colonne inconnue est AJOUTÉE (rien n'est perdu), plusieurs colonnes
        vers une même cible sont réunies. Les lignes déjà présentes ne sont pas doublées. Retourne (lignes ajoutées, colonnes créées)."""
        entete, lignes = lire_csv(octets)
        return self.importer_lignes(entete, lignes)

    def importer_vcf(self, fichiers) -> tuple[int, list]:
        """Ajoute les contacts de fichiers vCard (.vcf : un ou plusieurs contacts par fichier). Mêmes règles que le CSV."""
        entete, lignes = lire_vcards(fichiers)
        return self.importer_lignes(entete, lignes)

    def importer_lignes(self, entete: list, lignes: list) -> tuple[int, list]:
        if not entete:
            return 0, []
        cibles, creees = [], []
        connues = {normaliser(c): k for k, c in enumerate(self.colonnes)}
        for nom in entete:
            n = normaliser(nom)
            k = connues.get(n)
            if k is None and n in ALIAS:
                k = connues.get(normaliser(ALIAS[n]))
            if k is None and nom.strip() and len(self.colonnes) < MAX_COLONNES:
                self.colonnes.append(nom.strip())
                for l in self.lignes:
                    l.append("")
                k = len(self.colonnes) - 1
                connues[n] = k
                creees.append(nom.strip())
            cibles.append(k)
        existantes = {tuple(l) for l in self.lignes}
        ajoutees = 0
        for brut in lignes:
            nouv = self.ligne_vide()
            for k, val in zip(cibles, brut):
                val = val.replace("\r\n", "\n").replace("\r", "\n").strip()
                if k is None or not val:
                    continue
                nouv[k] = f"{nouv[k]}\n{val}" if nouv[k] else val
            if any(nouv) and tuple(nouv) not in existantes:
                existantes.add(tuple(nouv))
                self.lignes.append(nouv)
                ajoutees += 1
        return ajoutees, creees

    @classmethod
    def depuis_csv(cls, octets: bytes, index: int = 0) -> "Tableau":
        """Nouveau tableau dont les colonnes et les lignes sont celles du fichier."""
        entete, lignes = lire_csv(octets)
        t = cls(entete[:MAX_COLONNES] or ["Nom"], [], index)
        t.importer(octets)
        return t


def decoder(octets: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return octets.decode(enc)
        except UnicodeDecodeError:
            continue
    return octets.decode("latin-1")


def lire_csv(octets: bytes) -> tuple[list, list]:
    """(en-tête, lignes) d'un CSV quelconque : codage et séparateur reconnus, lignes vides ignorées."""
    texte = decoder(octets)
    echantillon = texte[:4096]
    try:
        sep = csv.Sniffer().sniff(echantillon, delimiters=",;\t").delimiter
    except csv.Error:
        sep = ";" if echantillon.count(";") > echantillon.count(",") else ","
    lignes = list(csv.reader(io.StringIO(texte, newline=""), delimiter=sep))
    if not lignes:
        return [], []
    return lignes[0], [l for l in lignes[1:] if any(x.strip() for x in l)]


# ---------- vCard (.vcf) ----------
ENTETE_VCARD = ["Nom", "Prénom", "Téléphones", "Adresse", "Courriel", "Lien", "Notes"]
MAX_CONTACTS = 20000


def _vc_valeur(v: str) -> str:
    return v.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def _vc_decouper(valeur: str) -> list:
    """Composants séparés par des « ; » non échappés."""
    return [_vc_valeur(x) for x in re.split(r"(?<!\\);", valeur)]


def lire_vcards(fichiers) -> tuple[list, list]:
    """(en-tête, lignes) des contacts de fichiers vCard (2.1, 3.0 ou 4.0) donnés en octets (un objet ou une liste). Nom, prénom, téléphones,
    adresse postale, courriels, sites et notes ont leur colonne ; société, fonction et anniversaire passent dans les notes (rien n'est perdu)."""
    if isinstance(fichiers, (bytes, bytearray)):
        fichiers = [bytes(fichiers)]
    lignes = []
    for octets in fichiers:
        texte = decoder(octets).replace("\r\n", "\n").replace("\r", "\n")
        texte = re.sub(r"=\n(?=[ \t]*[=\w])", "", texte) if "QUOTED-PRINTABLE" in texte.upper() else texte
        texte = re.sub(r"\n[ \t]", "", texte)                                  # lignes repliées
        carte = None
        for brut in texte.split("\n"):
            ligne = brut.strip()
            if ligne.upper() == "BEGIN:VCARD":
                carte = {"tel": [], "mail": [], "web": [], "adr": [], "notes": [], "autres": []}
            elif ligne.upper() == "END:VCARD" and carte is not None:
                ligne_csv = _vc_en_ligne(carte)
                if any(ligne_csv):
                    lignes.append(ligne_csv)
                carte = None
                if len(lignes) >= MAX_CONTACTS:
                    return ENTETE_VCARD, lignes
            elif carte is not None and ":" in ligne:
                cle, _sep, valeur = ligne.partition(":")
                parties = cle.split(";")
                nom = parties[0].split(".")[-1].upper()
                if any(p.upper().startswith("ENCODING=QUOTED-PRINTABLE") or p.upper() == "QUOTED-PRINTABLE" for p in parties[1:]):
                    try:
                        valeur = quopri.decodestring(valeur.encode("latin-1")).decode("utf-8", "replace")
                    except (ValueError, UnicodeError):
                        pass
                _vc_noter(carte, nom, valeur.strip())
    return ENTETE_VCARD, lignes


def _vc_noter(carte: dict, nom: str, valeur: str) -> None:
    if not valeur:
        return
    if nom == "N":
        c = _vc_decouper(valeur) + [""] * 5
        carte["nom"], carte["prenom"] = c[0].strip(), " ".join(x for x in (c[1], c[2]) if x.strip()).strip()
    elif nom == "FN":
        carte["fn"] = _vc_valeur(valeur).strip()
    elif nom == "TEL":
        carte["tel"].append(_vc_valeur(valeur).replace("tel:", "").strip())
    elif nom == "EMAIL":
        carte["mail"].append(_vc_valeur(valeur).strip())
    elif nom == "URL":
        carte["web"].append(_vc_valeur(valeur).strip())
    elif nom == "ADR":
        carte["adr"].append(", ".join(x.strip() for x in _vc_decouper(valeur) if x.strip()))
    elif nom == "NOTE":
        carte["notes"].append(_vc_valeur(valeur).strip())
    elif nom in ("ORG", "TITLE", "BDAY"):
        etiquette = {"ORG": "Société", "TITLE": "Fonction", "BDAY": "Anniversaire"}[nom]
        carte["autres"].append(f"{etiquette} : " + " ".join(x for x in _vc_decouper(valeur) if x.strip()))


def _vc_en_ligne(c: dict) -> list:
    nom, prenom = c.get("nom", ""), c.get("prenom", "")
    if not nom and not prenom:
        nom = c.get("fn", "")                    # pas de nom structuré : le nom affiché va dans « Nom »
    notes = c["autres"] + c["notes"]
    return [nom, prenom, "\n".join(dict.fromkeys(c["tel"])), "\n".join(c["adr"]), "\n".join(dict.fromkeys(c["mail"])),
            "\n".join(dict.fromkeys(c["web"])), "\n".join(notes)]


def texte_modele(numero: int) -> str:
    _titre, colonnes, index = MODELES[numero]
    return Tableau(colonnes, [], index).en_texte()

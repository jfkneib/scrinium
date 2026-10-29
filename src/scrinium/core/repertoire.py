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
import re
import unicodedata

from ..i18n import N_

MARQUE = "#scrinium-repertoire"
_MARQUE = re.compile(r"\A﻿?#scrinium-repertoire(?: +index=(\d+))?[ \t]*(?:\r?\n|\Z)")
LETTRES = tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ") + ("#",)
MAX_COLONNES = 30

# Modèles proposés à la création : (titre du modèle, colonnes, numéro de la colonne d'index)
MODELES = (
    (N_("Contacts (nom, téléphones, adresse, courriel)"), ("Nom", "Prénom", "Téléphones", "Adresse", "Courriel", "Notes"), 0),
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


def sans_accents(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texte) if not unicodedata.combining(c))


def normaliser(nom: str) -> str:
    return " ".join(sans_accents(nom).replace("_", " ").lower().split())


def est_repertoire(texte: str | None) -> bool:
    return bool(texte) and _MARQUE.match(texte) is not None


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


def texte_modele(numero: int) -> str:
    _titre, colonnes, index = MODELES[numero]
    return Tableau(colonnes, [], index).en_texte()

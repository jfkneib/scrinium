# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Logique (sans interface) de l'extension « Tableur » : un mini tableur dont le texte est un tableau Markdown (`#scrinium-tableur`).

    #scrinium-tableur
    | Date | Valeur |
    | --- | --- |
    | 2026-11-06 | 12,5 |
    | 2026-11-07 | 13 |
    | Somme | =SOMME(B2:B3) |

Chaque cellule est du texte brut : un nombre (virgule ou point décimal), du texte, ou une FORMULE qui commence par « = ». Les formules
sont évaluées par un évaluateur SÛR (arbre syntaxique, jamais d'`eval`) : nombres, + - * / ^ %, parenthèses, références (A1, b2), plages
(B2:B10) et quelques fonctions (SOMME, MOYENNE, MIN, MAX, NB, ABS, ARRONDI…). Type NON exécutable : la fiche ne lance rien.
Le texte qui n'est pas une ligne de tableau (notes libres) est conservé tel quel, après le tableau."""
import ast
import csv
import io
import math
import operator
import re
import zipfile
from datetime import date
from xml.sax.saxutils import escape as _esc, quoteattr as _attr

from scrinium.core.types_fiche import TypeFiche
from scrinium.i18n import N_, _

MARQUE = "#scrinium-tableur"
MAX_LIGNES = 2000
MAX_COLONNES = 52
MAX_PROFONDEUR = 50


# ---------- le tableau dans le texte ----------
def _decouper(ligne: str) -> list:
    s = ligne.strip()
    s = s[1:] if s.startswith("|") else s
    s = s[:-1] if s.endswith("|") and not s.endswith("\\|") else s
    return [c.replace("\\|", "|").strip() for c in re.split(r"(?<!\\)\|", s)]


def _est_separateur(cellules: list) -> bool:
    return bool(cellules) and all(re.fullmatch(r":?-{3,}:?", c) for c in cellules)


def lire(texte: str | None) -> tuple:
    """(lignes, notes) : `lignes` = liste rectangulaire de cellules brutes (texte) ; `notes` = lignes hors tableau, telles quelles."""
    corps = (texte or "").replace("\r\n", "\n").split("\n")
    if corps and corps[0].startswith(MARQUE):
        corps = corps[1:]
    lignes, notes = [], []
    for l in corps:
        if l.lstrip().startswith("|"):
            c = _decouper(l)
            if not _est_separateur(c):
                lignes.append(c)
        else:
            notes.append(l)
    while notes and not notes[-1].strip():
        notes.pop()
    while notes and not notes[0].strip():
        notes.pop(0)
    lignes = lignes[:MAX_LIGNES]
    largeur = min(max((len(r) for r in lignes), default=0), MAX_COLONNES)
    return [(r + [""] * largeur)[:largeur] for r in lignes], "\n".join(notes)


def ecrire(lignes: list, notes: str = "") -> str:
    """Texte de la fiche : marque, tableau Markdown (le séparateur suit la première ligne), puis les notes."""
    sortie = [MARQUE]
    if lignes:
        n = len(lignes[0])
        sortie.append(_ligne(lignes[0]))
        sortie.append("|" + " --- |" * n)
        sortie += [_ligne(r) for r in lignes[1:]]
    if notes.strip():
        sortie += ["", notes.strip("\n")]
    return "\n".join(sortie) + "\n"


def _ligne(cellules: list) -> str:
    return "| " + " | ".join(str(c).replace("|", "\\|").replace("\n", " ") for c in cellules) + " |"


def vide(colonnes: int = 6, lignes: int = 12) -> list:
    """Tableau neuf : une grille vide (A1 est la première cellule, comme dans tous les tableurs)."""
    return [[""] * colonnes for _i in range(lignes)]


def texte_neuf() -> str:
    return ecrire(vide())


# ---------- références ----------
def nom_colonne(i: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def index_colonne(nom: str) -> int:
    n = 0
    for ch in nom.upper():
        n = n * 26 + ord(ch) - 64
    return n - 1


def nom_cellule(ligne: int, colonne: int) -> str:
    return f"{nom_colonne(colonne)}{ligne + 1}"


_REF = re.compile(r"^([A-Za-z]{1,2})(\d{1,4})$")


def ref(texte: str) -> tuple:
    """« B3 » -> (2, 1) (ligne, colonne, base 0). ValueError sinon."""
    m = _REF.match(texte.strip())
    if not m:
        raise ValueError(texte)
    return int(m.group(2)) - 1, index_colonne(m.group(1))


# ---------- valeurs ----------
class ErreurCellule(Exception):
    """Erreur d'une formule : le texte (#VALEUR!, #DIV/0!…) est celui qui s'affiche dans la cellule."""


def nombre(texte: str):
    """Nombre contenu dans le texte d'une cellule (« 12,5 », « 1 200.5 », « 8% »), sinon None."""
    s = texte.strip().replace("\u00a0", "").replace(" ", "")
    if not s:
        return None
    pct = s.endswith("%")
    s = s[:-1] if pct else s
    if "," in s and "." in s:
        return None
    s = s.replace(",", ".")
    if not re.fullmatch(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?", s):
        return None
    v = float(s)
    v = v / 100 if pct else v
    return int(v) if v == int(v) and abs(v) < 1e15 and "." not in s and "e" not in s.lower() and not pct else v


def formater(v) -> str:
    """Texte d'un résultat : entier exact, sinon 10 chiffres significatifs, virgule décimale."""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v == int(v) and abs(v) < 1e15:
            return str(int(v))
        return format(v, ".10g").replace(".", ",")
    return str(v)


def _a_plat(valeurs):
    for v in valeurs:
        if isinstance(v, list):
            yield from _a_plat(v)
        else:
            yield v


def _nums(args) -> list:
    return [v for v in _a_plat(args) if isinstance(v, (int, float)) and not isinstance(v, bool)]


def _somme(*a):
    return sum(_nums(a))


def _moyenne(*a):
    n = _nums(a)
    if not n:
        raise ErreurCellule("#DIV/0!")
    return sum(n) / len(n)


def _min(*a):
    n = _nums(a)
    return min(n) if n else 0


def _max(*a):
    n = _nums(a)
    return max(n) if n else 0


def _nb(*a):
    return len(_nums(a))


def _arrondi(x, d=0):
    return round(x, int(d))


FONCTIONS = {"SOMME": _somme, "SUM": _somme, "MOYENNE": _moyenne, "AVERAGE": _moyenne, "MIN": _min, "MAX": _max, "NB": _nb,
             "COUNT": _nb, "ABS": abs, "ARRONDI": _arrondi, "ROUND": _arrondi, "RACINE": math.sqrt, "SQRT": math.sqrt,
             "ENT": math.floor, "INT": math.floor}
_BINAIRES = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Pow: operator.pow,
             ast.Mod: operator.mod}
_UNAIRES = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_PLAGE = re.compile(r"\b([A-Za-z]{1,2}\d{1,4}):([A-Za-z]{1,2}\d{1,4})\b")
_CELLULE = re.compile(r"(?<![A-Za-z_\"'])([A-Za-z]{1,2}\d{1,4})(?![\w(\"'])")


def _preparer(formule: str) -> str:
    """Formule -> expression Python lisible par l'évaluateur : plages `_p("B2:B9")`, cellules `_c("B2")`, « ; » -> « , », « ^ » -> « ** »."""
    f = formule.strip().lstrip("=").strip().replace(";", ",").replace("^", "**").replace("×", "*").replace("÷", "/")
    f = re.sub(r"(\d+)\s*%(?!\s*[\d(A-Za-z])", r"(\1/100)", f)
    f = _PLAGE.sub(lambda m: f'_p("{m.group(1).upper()}:{m.group(2).upper()}")', f)
    return _CELLULE.sub(lambda m: f'_c("{m.group(1).upper()}")', f)


class Feuille:
    """Évalue les cellules d'un tableau (liste rectangulaire de textes bruts), avec détection des références circulaires."""

    def __init__(self, lignes: list):
        self.lignes = lignes
        self._cache: dict = {}
        self._en_cours: list = []

    def brut(self, l: int, c: int) -> str:
        return self.lignes[l][c] if 0 <= l < len(self.lignes) and 0 <= c < len(self.lignes[l]) else ""

    def valeur(self, l: int, c: int):
        """Valeur de la cellule : None (vide), nombre, texte ; ErreurCellule si la formule est en erreur."""
        if not (0 <= l < len(self.lignes) and 0 <= c < (len(self.lignes[0]) if self.lignes else 0)):
            raise ErreurCellule("#REF!")
        cle = (l, c)
        if cle in self._cache:
            r = self._cache[cle]
            if isinstance(r, ErreurCellule):
                raise r
            return r
        if cle in self._en_cours:
            raise ErreurCellule("#CYCLE!")
        if len(self._en_cours) > MAX_PROFONDEUR:
            raise ErreurCellule("#CYCLE!")
        self._en_cours.append(cle)
        try:
            r = self._calculer(self.brut(l, c))
        except ErreurCellule as ex:
            r = ex
        finally:
            self._en_cours.pop()
        self._cache[cle] = r
        if isinstance(r, ErreurCellule):
            raise r
        return r

    def _calculer(self, brut: str):
        b = brut.strip()
        if not b:
            return None
        if b.startswith("="):
            return self._formule(b)
        n = nombre(b)
        return n if n is not None else b

    def _formule(self, formule: str):
        try:
            arbre = ast.parse(_preparer(formule), mode="eval")
        except (SyntaxError, ValueError):
            raise ErreurCellule("#ERREUR!") from None
        if len(formule) > 500:
            raise ErreurCellule("#ERREUR!")
        try:
            v = self._eval(arbre)
        except ErreurCellule:
            raise
        except ZeroDivisionError:
            raise ErreurCellule("#DIV/0!") from None
        except (ValueError, TypeError, OverflowError, RecursionError, MemoryError):
            raise ErreurCellule("#VALEUR!") from None
        if isinstance(v, list):
            raise ErreurCellule("#VALEUR!")
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            raise ErreurCellule("#VALEUR!")
        return v

    def _eval(self, n):
        if isinstance(n, ast.Expression):
            return self._eval(n.body)
        if isinstance(n, ast.Constant) and type(n.value) in (int, float):
            return n.value
        if isinstance(n, ast.UnaryOp) and type(n.op) in _UNAIRES:
            return _UNAIRES[type(n.op)](self._num(self._eval(n.operand)))
        if isinstance(n, ast.BinOp) and type(n.op) in _BINAIRES:
            a, b = self._num(self._eval(n.left)), self._num(self._eval(n.right))
            if isinstance(n.op, ast.Pow) and abs(b) > 1000:
                raise ErreurCellule("#VALEUR!")
            return _BINAIRES[type(n.op)](a, b)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and not n.keywords:
            nom = n.func.id
            if nom == "_c" and len(n.args) == 1:
                return self._cellule(n.args[0].value)
            if nom == "_p" and len(n.args) == 1:
                return self._plage(n.args[0].value)
            f = FONCTIONS.get(nom.upper())
            if f is not None:
                args = [self._eval(x) for x in n.args]
                if nom.upper() in ("ABS", "ARRONDI", "ROUND", "RACINE", "SQRT", "ENT", "INT"):
                    args = [self._num(a) for a in args]
                return f(*args)
        raise ErreurCellule("#NOM?")

    @staticmethod
    def _num(v):
        if v is None:
            return 0
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ErreurCellule("#VALEUR!")
        return v

    def _cellule(self, nom: str):
        l, c = ref(nom)
        return self.valeur(l, c)

    def _plage(self, nom: str) -> list:
        a, b = nom.split(":")
        (l1, c1), (l2, c2) = ref(a), ref(b)
        l1, l2, c1, c2 = min(l1, l2), max(l1, l2), min(c1, c2), max(c1, c2)
        if (l2 - l1 + 1) * (c2 - c1 + 1) > 20000:
            raise ErreurCellule("#VALEUR!")
        return [self.valeur(l, c) for l in range(l1, l2 + 1) for c in range(c1, c2 + 1)]

    def affichage(self, l: int, c: int) -> str:
        """Texte montré dans la cellule : le résultat d'une formule, le texte, ou le code d'erreur."""
        try:
            v = self.valeur(l, c)
        except ErreurCellule as ex:
            return str(ex)
        return "" if v is None else formater(v)

    def est_erreur(self, l: int, c: int) -> bool:
        try:
            self.valeur(l, c)
            return False
        except ErreurCellule:
            return True


def en_markdown(texte: str) -> str:
    """Rendu pour l'impression et l'export PDF : le tableau avec les résultats des formules."""
    lignes, notes = lire(texte)
    f = Feuille(lignes)
    calcule = [[f.affichage(l, c) for c in range(len(r))] for l, r in enumerate(lignes)]
    return ecrire(calcule, notes).split("\n", 1)[1]


# ---------- CSV ----------
def vers_csv(lignes: list, separateur: str = ";") -> str:
    """CSV (RÉSULTATS des formules, pas les formules) ; « ; » par défaut, que les tableurs français ouvrent directement."""
    f = Feuille(lignes)
    calcule = [[f.affichage(l, c) for c in range(len(lignes[l]))] for l in range(len(lignes))]
    while calcule and not any(calcule[-1]):                    # la grille vide du bas n'est pas exportée
        calcule.pop()
    largeur = max((max((i + 1 for i, v in enumerate(r) if v), default=0) for r in calcule), default=0)
    sortie = io.StringIO()
    w = csv.writer(sortie, delimiter=separateur, lineterminator="\n")
    for r in calcule:
        w.writerow(r[:largeur])
    return sortie.getvalue()


def depuis_csv(texte: str) -> list:
    """Tableau (rectangulaire) lu dans un CSV ; le séparateur (; , tabulation |) est deviné sur la première ligne."""
    texte = (texte or "").lstrip("\ufeff").replace("\r\n", "\n")
    premiere = texte.split("\n", 1)[0]
    sep = max((";", ",", "\t", "|"), key=premiere.count)
    lignes = [r for r in csv.reader(io.StringIO(texte), delimiter=sep) if any(c.strip() for c in r)][:MAX_LIGNES]
    largeur = min(max((len(r) for r in lignes), default=0), MAX_COLONNES)
    return [([c.strip() for c in r] + [""] * largeur)[:largeur] for r in lignes]


# ---------- Excel (.xlsx) et LibreOffice (.ods) ----------
_ANGLAIS = {"SOMME": "SUM", "MOYENNE": "AVERAGE", "NB": "COUNT", "ARRONDI": "ROUND", "RACINE": "SQRT", "ENT": "INT"}
_PLAGE_OU_CELLULE = re.compile(_PLAGE.pattern.replace("(", "(", 1) + "|" + _CELLULE.pattern)
_FONCTION = re.compile(r"\b([A-Za-zÉé]+)\s*\(")


def formule_standard(formule: str, ods: bool = False) -> str:
    """Formule Scrinium (noms français, « ; ») -> formule d'Excel (SUM, virgules) ou d'OpenDocument (`of:=SUM([.A1:.A3];2)`), sans le « = »."""
    f = formule.strip().lstrip("=").strip().replace("×", "*").replace("÷", "/")
    f = _FONCTION.sub(lambda m: _ANGLAIS.get(m.group(1).upper(), m.group(1).upper()) + "(", f)
    if ods:
        return _PLAGE_OU_CELLULE.sub(lambda m: f"[.{m.group(1).upper()}:.{m.group(2).upper()}]" if m.group(1) else f"[.{m.group(3).upper()}]", f)
    f = f.replace(";", ",")
    f = _PLAGE.sub(lambda m: f"{m.group(1).upper()}:{m.group(2).upper()}", f)
    return _CELLULE.sub(lambda m: m.group(1).upper(), f)


def _cellules_export(lignes: list) -> list:
    """[[(brut, valeur ou ErreurCellule ou None)]] rognées à la dernière ligne et colonne utilisées (la grille vide du bas n'est pas exportée)."""
    f = Feuille(lignes)
    nl = max((i + 1 for i, r in enumerate(lignes) if any(c.strip() for c in r)), default=0)
    nc = max((j + 1 for r in lignes for j, c in enumerate(r) if c.strip()), default=0)
    res = []
    for l in range(nl):
        ligne = []
        for c in range(nc):
            brut = f.brut(l, c).strip()
            try:
                v = f.valeur(l, c)
            except ErreurCellule as ex:
                v = ex
            ligne.append((brut, v))
        res.append(ligne)
    return res


def _num(v) -> str:
    return repr(float(v)) if isinstance(v, float) else str(int(v))


def vers_xlsx(lignes: list) -> bytes:
    """Classeur Excel (.xlsx) : les formules sont gardées (avec leur résultat), lisible par Excel, LibreOffice, Google Sheets…"""
    rangees = []
    for l, ligne in enumerate(_cellules_export(lignes), 1):
        cases = []
        for c, (brut, v) in enumerate(ligne):
            if not brut:
                continue
            nom = nom_cellule(l - 1, c)
            if brut.startswith("="):
                f = _esc(formule_standard(brut))
                if isinstance(v, ErreurCellule):
                    cases.append(f'<c r="{nom}" t="e"><f>{f}</f><v>{_esc(str(v))}</v></c>')
                elif isinstance(v, (int, float)) and not isinstance(v, bool):
                    cases.append(f'<c r="{nom}"><f>{f}</f><v>{_num(v)}</v></c>')
                else:
                    cases.append(f'<c r="{nom}" t="str"><f>{f}</f><v>{_esc(str(v if v is not None else ""))}</v></c>')
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                cases.append(f'<c r="{nom}"><v>{_num(v)}</v></c>')
            else:
                cases.append(f'<c r="{nom}" t="inlineStr"><is><t xml:space="preserve">{_esc(brut)}</t></is></c>')
        rangees.append(f'<row r="{l}">{"".join(cases)}</row>')
    entete = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    fichiers = {
        "[Content_Types].xml": entete + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>',
        "_rels/.rels": entete + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/workbook.xml": entete + f'<workbook {ns} xmlns:r="{rel}"><sheets><sheet name="Tableur" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": entete + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{rel}/worksheet" Target="worksheets/sheet1.xml"/>'
        f'<Relationship Id="rId2" Type="{rel}/styles" Target="styles.xml"/></Relationships>',
        "xl/styles.xml": entete + f'<styleSheet {ns}><fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/></cellXfs></styleSheet>',
        "xl/worksheets/sheet1.xml": entete + f'<worksheet {ns}><sheetData>{"".join(rangees)}</sheetData></worksheet>',
    }
    sortie = io.BytesIO()
    with zipfile.ZipFile(sortie, "w", zipfile.ZIP_DEFLATED) as z:
        for nom, contenu in fichiers.items():
            z.writestr(nom, contenu)
    return sortie.getvalue()


def vers_ods(lignes: list) -> bytes:
    """Classeur LibreOffice (.ods) : les formules sont gardées (avec leur résultat)."""
    rangees = []
    for ligne in _cellules_export(lignes):
        cases = []
        for brut, v in ligne:
            if not brut:
                cases.append("<table:table-cell/>")
            elif brut.startswith("="):
                f = _attr("of:=" + formule_standard(brut, ods=True))
                if isinstance(v, ErreurCellule):
                    cases.append(f"<table:table-cell table:formula={f}/>")
                elif isinstance(v, (int, float)) and not isinstance(v, bool):
                    cases.append(f'<table:table-cell table:formula={f} office:value-type="float" office:value="{_num(v)}"/>')
                else:
                    cases.append(f'<table:table-cell table:formula={f} office:value-type="string"><text:p>{_esc(str(v or ""))}</text:p></table:table-cell>')
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                cases.append(f'<table:table-cell office:value-type="float" office:value="{_num(v)}"/>')
            else:
                cases.append(f'<table:table-cell office:value-type="string"><text:p>{_esc(brut)}</text:p></table:table-cell>')
        rangees.append(f'<table:table-row>{"".join(cases)}</table:table-row>')
    contenu = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" xmlns:of="urn:oasis:names:tc:opendocument:xmlns:of:1.2" '
        'office:version="1.2"><office:body><office:spreadsheet><table:table table:name="Tableur">'
        f'{"".join(rangees)}</table:table></office:spreadsheet></office:body></office:document-content>')
    manifeste = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" '
        'manifest:version="1.2"><manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.spreadsheet"/>'
        '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/></manifest:manifest>')
    sortie = io.BytesIO()
    with zipfile.ZipFile(sortie, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/vnd.oasis.opendocument.spreadsheet")      # d'abord, non compressé
        z.writestr("META-INF/manifest.xml", manifeste, zipfile.ZIP_DEFLATED)
        z.writestr("content.xml", contenu, zipfile.ZIP_DEFLATED)
    return sortie.getvalue()


# ---------- aides à l'édition ----------
def ajouter_ligne(lignes: list, aujourdhui: date | None = None) -> list:
    """Ajoute une ligne vide à la fin ; si la première colonne s'intitule « Date », elle reçoit la date du jour (AAAA-MM-JJ)."""
    n = len(lignes[0]) if lignes else 2
    if not lignes:
        lignes = vide()
    nouvelle = [""] * n
    if lignes and lignes[0] and lignes[0][0].strip().lower() in ("date", "jour", "day"):
        nouvelle[0] = (aujourdhui or date.today()).isoformat()
    return lignes + [nouvelle]


def ligne_de_totaux(lignes: list, fonction: str = "SOMME", libelle: str = "") -> list:
    """Met une ligne de totaux (SOMME, MOYENNE, MIN, MAX) sous les données : dans la première ligne vide après la dernière ligne remplie
    (ou à la fin). Chaque colonne sauf la première totalise les lignes du dessus (le texte, comme un en-tête, est ignoré)."""
    if not lignes:
        return lignes
    n = len(lignes[0])
    derniere = max((i for i, r in enumerate(lignes) if any(c.strip() for c in r)), default=-1)      # base 0
    totaux = [libelle or fonction.capitalize()] + [f"={fonction}({nom_colonne(c)}1:{nom_colonne(c)}{derniere + 1})" for c in range(1, n)]
    lignes = [list(r) for r in lignes]
    if derniere + 1 < len(lignes):
        lignes[derniere + 1] = totaux
        return lignes
    return lignes + [totaux]


def exemples() -> list:
    """[(thème, titre, texte)] : une fiche d'exemple (une liste de courses calculée), créée à la première activation de l'extension."""
    lignes = [[_("Article"), _("Quantité"), _("Prix"), _("Total")],
              [_("Pommes"), "3", "1,20", "=B2*C2"], [_("Pain"), "2", "1,10", "=B3*C3"], [_("Lait"), "6", "0,95", "=B4*C4"],
              [_("Somme"), "", "", "=SOMME(D2:D4)"], ["", "", "", ""]]
    notes = _("Exemple. Cliquez une cellule : la barre au-dessus de la grille montre sa formule (ici « =B2*C2 » : quantité fois prix). "
              "Tapez = dans une cellule pour écrire la vôtre, par exemple =SOMME(D2:D4) ou =D5*1.2. Entrée valide.")
    return [(_("Tableur (exemples)"), _("Exemple · Liste de courses"), ecrire(lignes, notes))]


TYPE = TypeFiche("tableur", N_("Tableur"), "x-office-spreadsheet", modele=texte_neuf, en_markdown=en_markdown)

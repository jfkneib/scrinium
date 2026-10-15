"""Lecture des fichiers .po et écriture des .mo, sans dépendance (Python n'embarque pas msgfmt)."""
import ast
import struct


def lire_po(texte: str) -> dict:
    """{msgid: msgstr} (entrées traduites et non « fuzzy »)."""
    cat: dict = {}
    mid = mstr = None
    fuzzy_courant = fuzzy_suivant = False
    cible = None

    def vider():
        nonlocal mid, mstr
        if mid is not None and mstr and not fuzzy_courant:
            cat[mid] = mstr
        mid = mstr = None

    for ligne in texte.splitlines():
        l = ligne.strip()
        if l.startswith("#,"):
            fuzzy_suivant = fuzzy_suivant or "fuzzy" in l
        elif l.startswith("#"):
            continue
        elif l.startswith("msgid "):
            vider()
            fuzzy_courant, fuzzy_suivant = fuzzy_suivant, False
            mid, mstr, cible = ast.literal_eval(l[6:]), "", "id"
        elif l.startswith("msgstr "):
            mstr, cible = ast.literal_eval(l[7:]), "str"
        elif l.startswith('"') and mid is not None:
            v = ast.literal_eval(l)
            if cible == "id":
                mid += v
            else:
                mstr += v
        elif not l:
            vider()
    vider()
    return cat


def ecrire_mo(cat: dict) -> bytes:
    """Format GNU .mo (little endian), entrées triées par msgid."""
    cles = sorted(cat)
    ids = b"\0".join(k.encode("utf-8") for k in cles) + b"\0"
    strs = b"\0".join(cat[k].encode("utf-8") for k in cles) + b"\0"
    n = len(cles)
    debut_ids = 7 * 4 + 16 * n
    debut_strs = debut_ids + len(ids)
    tab_ids, tab_strs, off_i, off_s = b"", b"", 0, 0
    for k in cles:
        li, ls = len(k.encode("utf-8")), len(cat[k].encode("utf-8"))
        tab_ids += struct.pack("<II", li, debut_ids + off_i)
        tab_strs += struct.pack("<II", ls, debut_strs + off_s)
        off_i += li + 1
        off_s += ls + 1
    entete = struct.pack("<IIIIIII", 0x950412DE, 0, n, 7 * 4, 7 * 4 + 8 * n, 0, 0)
    return entete + tab_ids + tab_strs + ids + strs

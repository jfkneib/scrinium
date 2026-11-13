# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Export d'un thème entier comme DOCUMENT : un site HTML (une page par fiche + sommaire, liens [[fiche]] devenus liens entre pages,
images dans « images/ ») ou un seul PDF (sommaire puis toutes les fiches). Les fiches verrouillées fermées sont ignorées
(on n'écrit jamais en clair ce que l'utilisateur n'a pas déverrouillé) ; une fiche typée sort en tableaux Markdown."""
import html
import re
from pathlib import Path
from urllib.parse import quote, unquote

from PyQt6.QtCore import QMarginsF, QSizeF, QUrl
from PyQt6.QtGui import QImage, QPageLayout, QPageSize, QPdfWriter, QTextDocument

from ..core import images_texte, types_fiche
from ..core.store import propre
from .export_pdf import LARGEUR_IMAGE

_LIEN_FICHE = re.compile(r"\[([^\]]*)\]\(scrinium-fiche:([^)]*)\)")
CSS = ("body{font-family:sans-serif;max-width:50em;margin:2em auto;padding:0 1em;line-height:1.5;color:#222}"
       "img{max-width:100%}table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:.2em .5em}"
       "pre,code{background:#f3f3f3}nav{margin-bottom:2em;font-size:.9em}")


def fiches_exportables(store, th) -> tuple[list, int]:
    """([(fiche, titre, texte)], nombre de fiches ignorées car verrouillées et fermées)."""
    sorties, ignorees = [], 0
    for f in store.fiches_triees(th):
        if f.fermee:
            ignorees += 1
            continue
        sorties.append((f, f.titre or "?", types_fiche.en_markdown(f.texte or "")))
    return sorties, ignorees


def _liens(texte: str, th_nom: str, pages: dict) -> str:
    """[[fiche]] -> lien vers sa page (dict titre en minuscules -> fichier) ; sinon le simple texte."""
    from ..core import liens_fiches

    def sub(m):
        cible = unquote(m.group(2))
        cible = cible[len(th_nom) + 1:] if cible.startswith(th_nom + "/") else cible
        page = pages.get(cible.casefold())
        return f"[{m.group(1)}]({quote(page)})" if page else m.group(1)
    return _LIEN_FICHE.sub(sub, liens_fiches.vers_markdown(texte))


def _markdown_fiche(store, f, texte: str, th_nom: str, pages: dict, adresse) -> str:
    """Markdown d'une fiche : images citées (pj:N) à leur place, les autres à la fin. `adresse(piece) -> url de l'image`."""
    pieces = {p.id: p for p in store.lister_pieces(f)}
    texte = images_texte.remplacer(texte, lambda alt, n: f"![{alt}]({adresse(pieces[n])})" if n in pieces else "")
    md = _liens(texte, th_nom, pages)
    reste = [p for n, p in pieces.items() if n not in images_texte.numeros(f.texte or "")]
    if reste:
        md = md.rstrip() + "\n\n" + "\n\n".join(f"![{p.nom}]({adresse(p)})" for p in reste)
    return md


def _corps(md: str) -> str:
    doc = QTextDocument()
    doc.setMarkdown(md)
    h = doc.toHtml()
    m = re.search(r"<body[^>]*>(.*)</body>", h, re.S)
    return m.group(1) if m else h


def exporter_html(store, th, dossier: Path) -> dict:
    """Écrit `index.html`, une page par fiche et `images/` dans `dossier` (créé, doit être vide ou absent).
    Retourne {"fiches": n, "images": n, "ignorees": n}."""
    dossier = Path(dossier)
    if dossier.exists() and any(dossier.iterdir()):
        raise ValueError("le dossier existe déjà et n'est pas vide")
    fiches, ignorees = fiches_exportables(store, th)
    dossier.mkdir(parents=True, exist_ok=True)
    pages = {}
    for i, (f, titre, _t) in enumerate(fiches, 1):
        pages.setdefault(titre.casefold(), f"{i:02d}-{propre(titre, 'fiche')}.html")
    nb_images = 0
    liste = []
    for i, (f, titre, texte) in enumerate(fiches, 1):
        def adresse(p, i=i):
            nonlocal nb_images
            (dossier / "images").mkdir(exist_ok=True)
            nom = f"{i:02d}-{p.id}{'.jpg' if p.type == 'image/jpeg' else '.png'}"
            (dossier / "images" / nom).write_bytes(store.lire_piece(f, p))
            nb_images += 1
            return f"images/{nom}"
        md = _markdown_fiche(store, f, texte, th.nom, pages, adresse)
        page = f"{i:02d}-{propre(titre, 'fiche')}.html"
        entete = f'<nav><a href="index.html">← {html.escape(th.nom)}</a></nav>'
        (dossier / page).write_text(
            f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{html.escape(titre)}</title><style>{CSS}</style></head><body>{entete}<h1>{html.escape(titre)}</h1>'
            f"{_corps(md)}</body></html>", encoding="utf-8")
        liste.append((page, titre))
    items = "".join(f'<li><a href="{quote(p)}">{html.escape(t)}</a></li>' for p, t in liste)
    (dossier / "index.html").write_text(
        f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{html.escape(th.nom)}</title><style>{CSS}</style></head><body><h1>{html.escape(th.nom)}</h1><ul>{items}</ul></body></html>',
        encoding="utf-8")
    return {"fiches": len(fiches), "images": nb_images, "ignorees": ignorees}


def exporter_pdf(store, th, chemin: Path) -> dict:
    """Un seul PDF (A4) : le nom du thème, le sommaire, puis chaque fiche. Retourne {"fiches": n, "ignorees": n}."""
    fiches, ignorees = fiches_exportables(store, th)
    doc = QTextDocument()
    n = 0
    parties = [f"# {th.nom}\n\n" + "\n".join(f"- {t}" for _f, t, _x in fiches)]
    for f, titre, texte in fiches:
        def adresse(p):
            nonlocal n
            n += 1
            img = QImage.fromData(store.lire_piece(f, p))
            if not img.isNull():
                if img.width() > LARGEUR_IMAGE:
                    img = img.scaledToWidth(LARGEUR_IMAGE)
                doc.addResource(QTextDocument.ResourceType.ImageResource.value, QUrl(f"pj:{n}"), img)
            return f"pj:{n}"
        parties.append(f"# {titre}\n\n" + _markdown_fiche(store, f, texte, th.nom, {}, adresse))
    doc.setMarkdown("\n\n---\n\n".join(parties))
    w = QPdfWriter(str(chemin))
    w.setResolution(96)                  # unités du document = pixels à 96 ppp (sinon le texte sort minuscule)
    w.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    w.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Unit.Millimeter)
    w.setTitle(th.nom)
    w.setCreator("Scrinium")
    doc.setPageSize(QSizeF(w.width(), w.height()))
    doc.print(w)
    return {"fiches": len(fiches), "ignorees": ignorees}

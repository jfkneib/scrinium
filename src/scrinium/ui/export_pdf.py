# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Export d'une fiche en PDF : titre, texte (Markdown rendu comme dans l'aperçu) et images jointes, en A4."""
import html

from PyQt6.QtCore import QMarginsF, QSizeF, QUrl
from PyQt6.QtGui import QImage, QPageLayout, QPageSize, QPdfWriter, QTextDocument

LARGEUR_IMAGE = 480          # px dans le document (les images plus larges sont réduites, jamais agrandies)


def document(titre: str, texte: str, images=()) -> QTextDocument:
    """`images` : liste de (nom, octets). Le document contient le titre, le texte rendu, puis les images."""
    doc = QTextDocument()
    doc.setMarkdown(f"# {titre.strip()}\n\n{texte}" if titre.strip() else texte)
    reste = []
    for i, (nom, octets) in enumerate(images):
        img = QImage.fromData(octets)
        if img.isNull():
            continue
        adresse = f"image-jointe:{i}"
        doc.addResource(QTextDocument.ResourceType.ImageResource.value, QUrl(adresse), img)
        largeur = min(img.width(), LARGEUR_IMAGE)
        reste.append(f'<p><img src="{adresse}" width="{largeur}"><br><small>{html.escape(nom)}</small></p>')
    if reste:
        from PyQt6.QtGui import QTextCursor
        c = QTextCursor(doc)
        c.movePosition(QTextCursor.MoveOperation.End)
        c.insertHtml("<hr>" + "".join(reste))
    return doc


def ecrire_pdf(chemin: str, titre: str, texte: str, images=()) -> None:
    """Écrit le PDF ; lève OSError si le fichier ne peut pas être écrit."""
    w = QPdfWriter(chemin)
    w.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    w.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Unit.Millimeter)
    w.setTitle(titre or "Scrinium")
    w.setCreator("Scrinium")
    doc = document(titre, texte, images)
    doc.setPageSize(QSizeF(w.width(), w.height()))
    doc.print(w)

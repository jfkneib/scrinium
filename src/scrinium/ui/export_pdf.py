# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Export d'une fiche en PDF : titre, texte (Markdown rendu comme dans l'aperçu) et images jointes, en A4."""
import html

from PyQt6.QtCore import QMarginsF, QSizeF, Qt, QUrl
from PyQt6.QtGui import QImage, QPageLayout, QPageSize, QPdfWriter, QTextDocument

from ..core import images_texte

LARGEUR_IMAGE = 480          # px dans le document (les images plus larges sont réduites, jamais agrandies)


def document(titre: str, texte: str, images=()) -> QTextDocument:
    """`images` : liste de (nom, octets[, n° de pièce]). Le document contient le titre, le texte rendu (les `![](pj:N)` y montrent
    leur image), puis les images jointes qui ne sont pas citées dans le texte."""
    doc = QTextDocument()
    doc.setMarkdown(f"# {titre.strip()}\n\n{texte}" if titre.strip() else texte)
    reste = []
    citees = images_texte.numeros(texte)
    for i, (nom, octets, *numero) in enumerate(images):
        img = QImage.fromData(octets)
        if img.isNull():
            continue
        if numero:
            doc.addResource(QTextDocument.ResourceType.ImageResource.value, QUrl(f"pj:{numero[0]}"),
                            img.scaledToWidth(LARGEUR_IMAGE, Qt.TransformationMode.SmoothTransformation) if img.width() > LARGEUR_IMAGE else img)
            if numero[0] in citees:
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


def imprimer(imprimante, titre: str, texte: str, images=()) -> None:
    """Imprime sur un QPrinter (A4 par défaut, marges 15 mm), la mise en page étant celle du PDF."""
    imprimante.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Unit.Millimeter)
    imprimante.setDocName(titre or "Scrinium")
    doc = document(titre, texte, images)
    doc.setPageSize(QSizeF(imprimante.width(), imprimante.height()))
    doc.print(imprimante)


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

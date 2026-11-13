# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Images dans le texte : `![légende](pj:N)` (aperçu, PDF, export et import Markdown)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QBuffer, QByteArray, QIODevice  # noqa: E402
from PyQt6.QtGui import QColor, QImage, QTextDocument  # noqa: E402

from scrinium.core import echange_md, images_texte  # noqa: E402
from scrinium.core.paths import Paths  # noqa: E402
from scrinium.core.store import Store  # noqa: E402
from scrinium.ui import export_pdf  # noqa: E402
from tests.test_ui import app, fen  # noqa: E402,F401,F811


def _png(c="red", w=40, h=20):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(c))
    ba = QByteArray()
    b = QBuffer(ba)
    b.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(b, "PNG")
    return bytes(ba)


def _preparer(src):
    return "image/png", _png()


def test_reference_trouver_remplacer():
    r = images_texte.reference(3, "a[b]")
    assert r == "![a(b)](pj:3)"
    assert images_texte.trouver(f"x\n{r}\n![](pj:12)") == [("a(b)", 3), ("", 12)]
    assert images_texte.remplacer("![x](pj:1)", lambda a, n: f"<{a}{n}>") == "<x1>"


def test_pdf_place_l_image_dans_le_texte_sans_doublon(app):  # noqa: F811
    img = _png()
    doc = export_pdf.document("T", "avant\n\n![fig](pj:7)\n\naprès", [("a.png", img, 7), ("b.png", img, 8)])
    html = doc.toHtml()
    assert html.count("<img") == 2                    # pj:7 dans le texte + b.png (non citée) à la fin
    doc2 = export_pdf.document("T", "texte", [("a.png", img)])   # ancien format (sans n°) toujours accepté
    assert doc2.toHtml().count("<img") == 1


def test_export_import_garde_la_position(tmp_path):
    s = Store(Paths(tmp_path / "am"))
    s.charger()
    th = s.themes[0]
    f = s.nouvelle_fiche(th)
    p1 = s.ajouter_piece(f, "un.png", "image/png", _png("red"))
    p2 = s.ajouter_piece(f, "deux.png", "image/png", _png("blue"))
    texte = f"début\n\n{images_texte.reference(p2.id, 'deux')}\n\nfin"
    s.enregistrer(th, f, "Doc", texte)
    chemin = tmp_path / "Doc.md"
    assert echange_md.exporter(s, f, chemin, "Doc", texte) == 2
    md = chemin.read_text(encoding="utf-8")
    assert "![deux](Doc_images/02-deux.png)" in md and "pj:" not in md
    assert md.count("![") == 2 and md.index("![deux]") < md.index("fin")      # deux à sa place ; un rappelé à la fin
    g, n, ign = echange_md.importer(s, th, chemin, _preparer)
    assert n == 2 and not ign
    pieces = {p.nom: p.id for p in s.lister_pieces(g)}
    assert f"![deux](pj:{pieces['deux']})" in g.texte
    assert g.texte.index("pj:") < g.texte.index("fin") and "## Images" not in g.texte


def test_apercu_charge_pj_et_rien_d_autre(fen):  # noqa: F811
    f = fen.fiche
    p = fen.store.ajouter_piece(f, "x.png", "image/png", _png(w=3000, h=100))
    assert fen._octets_piece(p.id) and fen._octets_piece(9999) is None
    ap = fen.apercu
    from PyQt6.QtCore import QUrl
    img = ap.loadResource(2, QUrl(f"pj:{p.id}"))
    assert img is not None and img.width() <= max(ap.viewport().width(), 100)
    assert ap.loadResource(2, QUrl("file:///etc/hostname")) is None
    assert ap.loadResource(2, QUrl("http://exemple.org/a.png")) is None


def test_inserer_piece_ecrit_la_reference(fen):  # noqa: F811
    f = fen.fiche
    p = fen.store.ajouter_piece(f, "photo.png", "image/png", _png())
    fen.texte.setPlainText("ligne")
    fen.texte.moveCursor(fen.texte.textCursor().MoveOperation.End)
    fen.inserer_piece(p)
    assert f"![photo](pj:{p.id})" in fen.texte.toPlainText()


def test_bouton_raccourcis(fen, monkeypatch):  # noqa: F811
    from PyQt6.QtWidgets import QMessageBox
    vus = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a: vus.append(a[2]))
    assert fen.menuBar().cornerWidget() is not None
    fen.raccourcis()
    assert "Ctrl+H" in vus[0] and "Ctrl+N" in vus[0]

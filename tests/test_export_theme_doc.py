# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Export d'un thème en site HTML ou en un PDF."""
import os
from urllib.parse import quote

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from scrinium.core import images_texte  # noqa: E402
from scrinium.core.paths import Paths  # noqa: E402
from scrinium.core.store import Store  # noqa: E402
from scrinium.ui import export_theme_doc  # noqa: E402
from tests.test_images_texte import _png  # noqa: E402
from tests.test_ui import app  # noqa: E402,F401


def _theme(tmp_path):
    s = Store(Paths(tmp_path / "am"))
    s.charger()
    th = s.nouveau_theme("Site")
    a = s.nouvelle_fiche(th)
    p = s.ajouter_piece(a, "fig.png", "image/png", _png())
    s.enregistrer(th, a, "Accueil", f"Voir [[Détails]] et [[Absente]]\n\n{images_texte.reference(p.id, 'fig')}")
    b = s.nouvelle_fiche(th)
    s.enregistrer(th, b, "Détails", "# Sous-titre\n\nretour [[Accueil|accueil]]")
    return s, th


def test_site_html(app, tmp_path):  # noqa: F811
    s, th = _theme(tmp_path)
    r = export_theme_doc.exporter_html(s, th, tmp_path / "site")
    assert r == {"fiches": 2, "images": 1, "ignorees": 0}
    index = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    pages = sorted(p.name for p in (tmp_path / "site").glob("*-*.html"))
    assert len(pages) == 2 and all(quote(p) in index for p in pages)
    acc = next(p for p in pages if "accueil" in p.lower())
    html = (tmp_path / "site" / acc).read_text(encoding="utf-8")
    assert 'href="02-D%C3%A9tails.html"' in html
    assert "Absente" in html and "scrinium-fiche" not in html and "images/" in html
    assert (tmp_path / "site" / "images").is_dir()


def test_site_refuse_un_dossier_non_vide(app, tmp_path):  # noqa: F811
    import pytest
    s, th = _theme(tmp_path)
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "a").write_text("1")
    with pytest.raises(ValueError):
        export_theme_doc.exporter_html(s, th, tmp_path / "x")


def test_pdf_theme(app, tmp_path):  # noqa: F811
    s, th = _theme(tmp_path)
    r = export_theme_doc.exporter_pdf(s, th, tmp_path / "t.pdf")
    assert r == {"fiches": 2, "ignorees": 0}
    assert (tmp_path / "t.pdf").read_bytes().startswith(b"%PDF")

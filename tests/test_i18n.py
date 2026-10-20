# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Traductions anglaises : complètes, mêmes marqueurs de format, et le .po sert bien de source au .mo."""
import importlib.util
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("outils_i18n", RACINE / "outils" / "i18n.py")
outil = importlib.util.module_from_spec(spec)
spec.loader.exec_module(outil)


def test_toutes_les_chaines_ont_une_traduction_anglaise():
    assert outil.problemes() == []


def test_le_catalogue_anglais_est_chargeable():
    from scrinium import i18n_po
    cat = i18n_po.lire_po((RACINE / "po" / "en.po").read_text(encoding="utf-8"))
    assert cat.get("Copier dans le presse-papiers") == "Copy to the clipboard"
    assert i18n_po.ecrire_mo(cat)[:4] in (b"\xde\x12\x04\x95", b"\x95\x04\x12\xde")

# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Compile les traductions (po/*.po -> scrinium/locale/<langue>/LC_MESSAGES/scrinium.mo) pendant le build."""
import importlib.util
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

RACINE = Path(__file__).parent


def _outil():
    spec = importlib.util.spec_from_file_location("i18n_po", RACINE / "src" / "scrinium" / "i18n_po.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class BuildAvecTraductions(build_py):
    def run(self):
        super().run()
        outil = _outil()
        for po in sorted((RACINE / "po").glob("*.po")):
            dest = Path(self.build_lib) / "scrinium" / "locale" / po.stem / "LC_MESSAGES"
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "scrinium.mo").write_bytes(outil.ecrire_mo(outil.lire_po(po.read_text(encoding="utf-8"))))


setup(cmdclass={"build_py": BuildAvecTraductions})

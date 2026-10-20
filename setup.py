# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Pendant le build : compile les traductions (po/*.po -> scrinium/locale/<langue>/LC_MESSAGES/scrinium.mo) et range les extensions
officielles (plugins/<nom> -> scrinium/plugins_officiels/<nom>) dans le paquet. Même chemin pour pip, install.sh et le .deb."""
import importlib.util
import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

RACINE = Path(__file__).parent


def _outil():
    spec = importlib.util.spec_from_file_location("i18n_po", RACINE / "src" / "scrinium" / "i18n_po.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


EXEMPLES = {"hello"}        # extension d'exemple : documentée (docs/plugins.md), pas livrée comme extension officielle


class BuildAvecTraductions(build_py):
    def run(self):
        super().run()
        officielles = Path(self.build_lib) / "scrinium" / "plugins_officiels"
        shutil.rmtree(officielles, ignore_errors=True)
        for plug in sorted((RACINE / "plugins").glob("*/plugin.json")):
            if plug.parent.name not in EXEMPLES:
                shutil.copytree(plug.parent, officielles / plug.parent.name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        outil = _outil()
        for po in sorted((RACINE / "po").glob("*.po")):
            dest = Path(self.build_lib) / "scrinium" / "locale" / po.stem / "LC_MESSAGES"
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "scrinium.mo").write_bytes(outil.ecrire_mo(outil.lire_po(po.read_text(encoding="utf-8"))))


setup(cmdclass={"build_py": BuildAvecTraductions})

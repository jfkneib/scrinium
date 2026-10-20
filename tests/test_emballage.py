# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Ce que contient réellement le paquet construit (pip, install.sh, .deb passent tous par `setup.py build_py`)."""
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
OFFICIELLES = {"agenda", "applications", "capture", "courriel", "dictee", "lecture", "ocr", "traduction"}


@pytest.fixture(scope="module")
def construit(tmp_path_factory):
    cible = tmp_path_factory.mktemp("build")
    r = subprocess.run([sys.executable, "setup.py", "-q", "build_py", "--build-lib", str(cible)], cwd=RACINE, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-800:]
    return cible / "scrinium"


def test_les_extensions_officielles_sont_dans_le_paquet(construit):
    d = construit / "plugins_officiels"
    assert {p.name for p in d.iterdir() if p.is_dir()} == OFFICIELLES                       # ni hello (exemple), ni autre chose
    for nom in OFFICIELLES:
        assert (d / nom / "plugin.json").is_file() and (d / nom / "__init__.py").is_file()
    assert not list(d.rglob("__pycache__")) and not list(d.rglob("*.pyc"))                  # pas de fichiers compilés dans le paquet


def test_les_traductions_sont_dans_le_paquet(construit):
    assert (construit / "locale" / "en" / "LC_MESSAGES" / "scrinium.mo").stat().st_size > 1000


def test_le_paquet_contient_le_noyau_et_pas_les_tests(construit):
    assert (construit / "cli.py").is_file() and (construit / "core" / "plugins.py").is_file() and (construit / "ui" / "fenetre.py").is_file()
    assert not (construit.parent / "tests").exists()


def test_les_extensions_emballees_se_decouvrent_depuis_le_paquet(construit, tmp_path):
    """Depuis le paquet construit (pas depuis le dépôt) : la découverte retrouve les cinq extensions."""
    code = (f"import sys; sys.path.insert(0, {str(construit.parent)!r})\n"
            "from scrinium.core import plugins\n"
            "d = plugins.dossiers_officiels_reels() if hasattr(plugins, 'dossiers_officiels_reels') else plugins.dossiers_officiels()\n"
            "print(sorted(p.name for x in d for p in x.iterdir() if (p / 'plugin.json').is_file()))\n"
            "print([str(x) for x in d])")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, cwd=tmp_path)
    assert r.returncode == 0, r.stderr[-500:]
    ligne1, ligne2 = r.stdout.strip().splitlines()
    assert set(eval(ligne1)) == OFFICIELLES and str(construit) in ligne2 and str(RACINE / "plugins") not in ligne2

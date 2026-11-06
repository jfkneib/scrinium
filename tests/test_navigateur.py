# SPDX-License-Identifier: GPL-3.0-or-later
"""Extension de navigateur « Envoyer à Scrinium » : manifeste, textes, et lien compatible avec core/lien.py."""
import json
import re
from pathlib import Path
from urllib.parse import quote

from scrinium.core import lien

DOSSIER = Path(__file__).resolve().parent.parent / "navigateur"


def test_manifeste_et_traductions():
    m = json.loads((DOSSIER / "manifest.json").read_text(encoding="utf-8"))
    assert m["manifest_version"] == 3 and (DOSSIER / "icon.png").exists()
    for langue in ("fr", "en"):
        msgs = json.loads((DOSSIER / "_locales" / langue / "messages.json").read_text(encoding="utf-8"))
        for cle in re.findall(r"__MSG_(\w+)__", json.dumps(m)) + ["menuSelection", "menuPage"]:
            assert msgs[cle]["message"]


def test_lien_construit_comme_background_js_est_accepte():
    texte = "https://exemple.org/a?b=1&c=é\n\nligne 1\nligne « 2 » & 100 %"
    url = "scrinium://ajouter?titre=" + quote("Page d'essai", safe="-_.!~*'()") + "&texte=" + quote(texte, safe="-_.!~*'()")
    r = lien.analyser(url)
    assert r["action"] == "ajouter" and r["texte"].startswith("https://exemple.org") and "100 %" in r["texte"]

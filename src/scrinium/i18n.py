"""Traduction (gettext). Les textes sources sont en français ; po/<langue>.po fournit les autres langues.

Langue : réglage « langue » (settings.json : fr, en ou auto), sinon variable SCRINIUM_LANG, sinon langue du système.
Français = textes sources. Autre langue sans traduction = anglais.
"""
import gettext
import io
import locale
import os
import sys
from pathlib import Path

from . import i18n_po

_trad = gettext.NullTranslations()
_langue = "fr"
RACINE_PO = Path(__file__).resolve().parents[2] / "po"   # utilisé seulement en lançant depuis les sources


def langue_systeme() -> str:
    for var in ("SCRINIUM_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        v = os.environ.get(var, "").split(":")[0].strip()
        if v and v not in ("C", "POSIX"):
            return v.split(".")[0].split("_")[0].lower()
    try:
        if sys.platform == "win32":
            import ctypes
            buf = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, 85):
                return buf.value.split("-")[0].lower()
        code = locale.getlocale()[0] or locale.getdefaultlocale()[0]
        if code:
            return code.split("_")[0].lower()
    except Exception:
        pass
    return "en"


def _charger(code: str):
    for d in (Path(__file__).parent / "locale", Path("/usr/share/locale")):
        try:
            return gettext.translation("scrinium", localedir=str(d), languages=[code])
        except OSError:
            continue
    po = RACINE_PO / f"{code}.po"   # lancement depuis les sources : on lit le .po directement
    if po.exists():
        return gettext.GNUTranslations(io.BytesIO(i18n_po.ecrire_mo(i18n_po.lire_po(po.read_text(encoding="utf-8")))))
    return None


def init(choix: str = "auto") -> str:
    """Choisit la langue ('auto', 'fr', 'en'…) et retourne le code effectivement utilisé."""
    global _trad, _langue
    code = langue_systeme() if choix in ("", "auto", None) else choix.lower()
    _trad, _langue = gettext.NullTranslations(), "fr"
    if code == "fr":
        return _langue
    for essai in (code, "en"):
        t = _charger(essai)
        if t is not None:
            _trad, _langue = t, essai
            break
    return _langue


def langue() -> str:
    return _langue


def _(s: str) -> str:
    return _trad.gettext(s)

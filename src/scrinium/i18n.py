"""Traduction : les textes sources sont en français ; un catalogue gettext (domaine « scrinium ») les remplace."""
import gettext
from pathlib import Path

_dossiers = [Path(__file__).parent / "locale", Path("/usr/share/locale")]
_trad = gettext.NullTranslations()
for d in _dossiers:
    try:
        _trad = gettext.translation("scrinium", localedir=str(d), languages=None)
        break
    except OSError:
        continue


def _(s: str) -> str:
    return _trad.gettext(s)

"""Ligne de commande : fenêtre, ou récupération de fiches en ligne de commande avec la clé de secours."""
import argparse
import getpass
import sys
from pathlib import Path

from . import __version__
from .core.paths import Paths
from .core.store import Store
from .i18n import _


def _recuperer(args) -> int:
    store = Store(Paths())
    store.charger()
    verrouillees = [(t, f) for t in store.themes for f in t.fiches if f.verrou]
    if args.action == "lister":
        for t, f in verrouillees:
            from .core.crypto import a_cle_de_secours
            print(("secours " if a_cle_de_secours(f.path.read_bytes()) else "SANS    ") + f"{t.nom}/{f.path.name}")
        return 0
    ref = (args.fiche or "").lower()
    res = [(t, f) for t, f in verrouillees if ref in f.titre.lower() or ref in f"{t.nom}/{f.titre}".lower()]
    exact = [(t, f) for t, f in res if f.titre.lower() == ref]
    res = exact or res
    if len(res) != 1:
        print(_("Fiche introuvable.") if not res else _("Plusieurs fiches :\n  ") + "\n  ".join(f"{t.nom}/{f.titre}" for t, f in res),
              file=sys.stderr)
        return 1
    t, f = res[0]
    pem = Path(args.cle).expanduser().read_bytes()
    phrase = getpass.getpass(_("Phrase secrète de la clé (vide si aucune) : ")) or None if b"ENCRYPTED" in pem else None
    try:
        texte = store.ouvrir_avec_cle_privee(f, pem, phrase)
    except Exception as ex:
        print(_("Impossible : %s") % ex, file=sys.stderr)
        return 1
    if args.action == "ouvrir":
        sys.stdout.write(texte if texte.endswith("\n") else texte + "\n")
    else:
        f.texte = texte
        store.retirer_verrou(t, f)
        print(_("Remise en clair : %s") % f.path)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="scrinium", description=_("Scrinium : fiches rangées par thème."))
    p.add_argument("--version", action="version", version=f"scrinium {__version__}")
    p.add_argument("--theme", metavar="NOM", help=_("ouvre directement sur ce thème"))
    p.add_argument("--nouvelle", "--new", dest="nouvelle", action="store_true", help=_("ouvre avec une nouvelle fiche"))
    sub = p.add_subparsers(dest="cmd")
    r = sub.add_parser("secours", help=_("rouvrir une fiche verrouillée avec la clé de secours (sans interface)"))
    r.add_argument("action", choices=["lister", "ouvrir", "deverrouiller"])
    r.add_argument("fiche", nargs="?")
    r.add_argument("--cle", required=False, default="~/.config/scrinium/cle-de-secours.pem",
                   help=_("clé privée de secours (PEM)"))
    a = p.parse_args(argv)
    if a.cmd == "secours":
        return _recuperer(a)
    from PyQt6.QtWidgets import QApplication
    from .ui.fenetre import Fenetre
    app = QApplication(sys.argv[:1])
    app.setApplicationName("scrinium")
    app.setDesktopFileName("scrinium")
    w = Fenetre(Store(Paths()), theme=a.theme, nouvelle=a.nouvelle)
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

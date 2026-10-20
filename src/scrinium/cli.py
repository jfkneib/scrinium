# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Ligne de commande : fenêtre, ou récupération de fiches en ligne de commande avec la clé de secours."""
import argparse
import getpass
import sys
from pathlib import Path

from . import __version__
from .core.paths import Paths
from .core.store import Store
from . import i18n
from .i18n import _


def _recuperer(args) -> int:
    store = Store(Paths())
    store.charger()
    verrouillees = [(t, f) for t in store.themes for f in t.fiches if f.verrou]
    if args.action == "lister":
        for t, f in verrouillees:
            from .core.crypto import a_cle_de_secours
            n = len(store.chemins_pieces(f))
            print(("secours " if a_cle_de_secours(f.path.read_bytes()) else "SANS    ") + f"{t.nom}/{f.path.name}"
                  + (_("  (+ %d image(s))") % n if n else ""))
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
    phrase = getpass.getpass(_("Mot de passe du fichier de secours (vide si aucun) : ")) or None if b"ENCRYPTED" in pem else None
    try:
        texte = store.ouvrir_avec_cle_privee(f, pem, phrase)
    except Exception as ex:
        print(_("Impossible : %s") % ex, file=sys.stderr)
        return 1
    pieces = store.chemins_pieces(f)
    if args.action == "ouvrir":
        sys.stdout.write(texte if texte.endswith("\n") else texte + "\n")
        if pieces and args.images:
            return _extraire_images(pieces, pem, phrase, Path(args.images).expanduser())
        if pieces:
            print(_("%d image(s) jointe(s) : ajoutez --images DOSSIER pour les extraire (EN CLAIR).") % len(pieces), file=sys.stderr)
    else:
        f.texte = texte
        try:
            store.retirer_verrou(t, f)
        except (ValueError, OSError) as ex:
            print(_("Impossible : %s") % ex, file=sys.stderr)
            return 1
        print(_("Remise en clair : %s") % f.path)
    return 0


def _extraire_images(pieces, pem, phrase, dossier: Path) -> int:
    """Écrit les images d'une fiche verrouillée, déchiffrées avec la clé de secours, dans `dossier` (droits 700)."""
    from .core import crypto
    from .core.store import mkdir_prive, propre
    mkdir_prive(dossier)
    code = 0
    for n, p in pieces:
        try:
            ent, donnees = crypto.ouvrir_piece_avec_cle_privee(p.read_bytes(), pem, phrase)
        except Exception as ex:
            print(_("Image %(n)s illisible : %(ex)s") % {"n": p.name, "ex": ex}, file=sys.stderr)
            code = 1
            continue
        suffixe = ".jpg" if ent.get("type") == "image/jpeg" else ".png"
        cible = dossier / f"{n}-{Path(propre(str(ent.get('nom', 'image')))).stem}{suffixe}"
        cible.write_bytes(donnees)
        cible.chmod(0o600)
        print(cible, file=sys.stderr)
    return code


def _ajouter(args) -> int:
    """`scrinium ajouter` : le texte reçu sur l'entrée standard est ajouté à une fiche (créée au besoin)."""
    from .core import capture
    if sys.stdin.isatty():
        print(_("Aucun texte reçu : utilisez un tube, par exemple :  ip a | scrinium ajouter -t Informatique -f Réseau"),
              file=sys.stderr)
        return 2
    texte = capture.tronquer(sys.stdin.buffer.read(capture.TAILLE_MAX + 1).decode("utf-8", "replace"))
    if not texte.strip():
        print(_("Aucun texte reçu (entrée vide) : rien n'a été ajouté."), file=sys.stderr)
        return 2
    payload = {"theme": args.theme_cible, "fiche": args.fiche_cible, "texte": texte, "commande": args.commande or "",
               "remplacer": args.remplacer, "brut": args.brut}
    rep = None
    try:   # une fenêtre déjà ouverte écrit elle-même (son éditeur reste cohérent) ; Qt absent = écriture directe
        from PyQt6.QtCore import QCoreApplication
        from .ui import instance
        _app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])   # (à garder vivante pendant l'échange)
        assert _app is not None
        rep = instance.envoyer_ajout(payload)
    except ImportError:
        pass
    if rep is not None:
        ok, msg = rep
        print(_("Ajouté à « %(theme)s / %(fiche)s ».") % {"theme": args.theme_cible, "fiche": args.fiche_cible} if ok
              else _("Impossible : %s") % msg, file=sys.stderr)
        return 0 if ok else 1
    store = Store(Paths())
    store.charger()
    try:
        th, f = capture.ajouter(store, args.theme_cible, args.fiche_cible, texte, args.commande or "", args.remplacer, args.brut)
    except (ValueError, OSError) as ex:
        print(_("Impossible : %s") % ex, file=sys.stderr)
        return 1
    print(_("Ajouté à « %(theme)s / %(fiche)s ».") % {"theme": th.nom, "fiche": f.titre}, file=sys.stderr)
    return 0


def main(argv=None) -> int:
    langue = i18n.init(Store(Paths()).reglages().get("langue", "auto"))
    p = argparse.ArgumentParser(prog="scrinium", description=_("Scrinium : fiches rangées par thème."))
    p.add_argument("--version", action="version", version=f"scrinium {__version__}")
    p.add_argument("--theme", metavar="NAME", help=_("ouvre directement sur ce thème"))
    p.add_argument("--new", "--nouvelle", dest="nouvelle", action="store_true", help=_("ouvre avec une nouvelle fiche"))
    p.add_argument("--minimise", action="store_true",
                   help=_("démarre caché dans la zone de notification (ex. lancement à l'ouverture de session)"))
    p.add_argument("--rapide", "--quick", dest="rapide", action="store_true",
                   help=_("ouvre seulement la petite fenêtre de capture rapide (à lier à un raccourci clavier du bureau)"))
    sub = p.add_subparsers(dest="cmd")
    r = sub.add_parser("rescue", aliases=["secours"], help=_("rouvrir une fiche verrouillée avec le fichier de secours (sans interface)"))
    r.add_argument("action", choices=["list", "open", "unlock", "lister", "ouvrir", "deverrouiller"])
    r.add_argument("fiche", metavar="TITLE", nargs="?")
    r.add_argument("--images", metavar="DIR", help=_("avec « open » : extrait les images jointes (EN CLAIR) dans ce dossier"))
    r.add_argument("--key", "--cle", dest="cle", metavar="FILE", required=False, default="~/.config/scrinium/cle-de-secours.pem",
                   help=_("fichier de secours (PEM)"))
    c = sub.add_parser("add", aliases=["ajouter"], help=_("ajoute à une fiche le texte reçu sur l'entrée standard (tube)"))
    c.add_argument("-t", "--theme", "--topic", dest="theme_cible", metavar="NAME", required=True, help=_("thème de la fiche"))
    c.add_argument("-f", "--fiche", "--note", dest="fiche_cible", metavar="TITLE", required=True,
                   help=_("titre de la fiche (créée si elle n'existe pas)"))
    c.add_argument("-c", "--commande", "--command", dest="commande", metavar="TEXT",
                   help=_("commande à rappeler dans l'en-tête du bloc ajouté"))
    c.add_argument("--remplacer", "--replace", action="store_true", help=_("remplace le texte de la fiche au lieu d'ajouter à la fin"))
    c.add_argument("--brut", "--raw", action="store_true", help=_("ajoute le texte tel quel, sans en-tête daté ni barrières"))
    a = p.parse_args(argv)
    if a.cmd in ("add", "ajouter"):
        return _ajouter(a)
    if a.cmd in ("secours", "rescue"):
        a.action = {"list": "lister", "open": "ouvrir", "unlock": "deverrouiller"}.get(a.action, a.action)
        return _recuperer(a)
    from PyQt6.QtWidgets import QApplication
    from .ui import instance
    from .ui.fenetre import Fenetre
    app = QApplication(sys.argv[:1])
    app.setApplicationName("scrinium")
    from PyQt6.QtCore import QLibraryInfo, QTranslator
    qt_tr = QTranslator(app)   # boutons standard de Qt (OK, Annuler, Copier, Coller…)
    if qt_tr.load(f"qtbase_{langue}", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(qt_tr)
    app.setDesktopFileName("scrinium")
    if a.rapide and instance.demander_capture():             # instance déjà lancée : elle ouvre la capture
        return 0
    if not a.rapide and instance.reveiller_existante(a.theme, a.nouvelle):   # déjà lancé (peut-être dans la zone de notification)
        return 0
    w = Fenetre(Store(Paths()), theme=a.theme, nouvelle=a.nouvelle)
    serveur = instance.Serveur(w)
    serveur.ajout = w.ajouter_depuis_cli
    serveur.reveil.connect(lambda th, nv: w.montrer(th or None, nv))
    serveur.capture.connect(w.capture_rapide)
    if not ((a.minimise or a.rapide) and w.tray_actif):
        w.show()
    if a.rapide:
        w.capture_rapide()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

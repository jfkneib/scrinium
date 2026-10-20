# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Partie sans interface de l'extension « Envoi par courriel » : adresses, message, SMTP (bibliothèque standard seule)."""
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from scrinium.i18n import N_, _

ADRESSE = re.compile(r"^[^@\s,;<>\"']+@[^@\s,;<>\"']+\.[^@\s,;<>\"']+$")
SECURITES = {"starttls": (N_("STARTTLS (port 587)"), 587), "ssl": (N_("SSL/TLS (port 465)"), 465), "aucune": (N_("Aucune (port 25)"), 25)}
DELAI = 20     # secondes


def adresse_valide(a: str) -> bool:
    return bool(ADRESSE.match(a.strip()))


def analyser_adresses(texte: str) -> tuple[list, list]:
    """(valides, invalides) d'une saisie séparée par virgules, points-virgules, espaces ou retours ; sans doublon."""
    vues, valides, invalides = set(), [], []
    for a in filter(None, re.split(r"[,;\s]+", texte.strip())):
        if not adresse_valide(a):
            invalides.append(a)
        elif a.lower() not in vues:
            vues.add(a.lower())
            valides.append(a)
    return valides, invalides


def fusionner(*listes) -> list:
    """Concatène des listes d'adresses sans doublon (insensible à la casse), ordre conservé."""
    vues, res = set(), []
    for liste in listes:
        for a in liste:
            if a.lower() not in vues:
                vues.add(a.lower())
                res.append(a)
    return res


def construire(smtp: dict, destinataires: list, sujet: str, corps: str) -> EmailMessage:
    if not destinataires:
        raise ValueError(_("aucun destinataire"))
    exp = smtp.get("expediteur", "").strip()
    if not adresse_valide(exp):
        raise ValueError(_("adresse d'expédition absente ou invalide (réglages du serveur)"))
    for d in destinataires:
        if not adresse_valide(d):
            raise ValueError(_("adresse invalide : %s") % d)
    m = EmailMessage()
    m["From"] = formataddr((smtp.get("nom", "").strip(), exp))
    m["To"] = ", ".join(destinataires)
    m["Subject"] = sujet.replace("\r", " ").replace("\n", " ").strip() or "(sans titre)"
    m["Date"] = formatdate(localtime=True)
    m["Message-ID"] = make_msgid(domain=exp.split("@")[1])
    m.set_content(corps, charset="utf-8")
    return m


def ouvrir(smtp: dict, mot_de_passe: str | None) -> smtplib.SMTP:
    """Connexion prête à envoyer. Refuse d'envoyer un mot de passe sans chiffrement."""
    hote, mode = smtp.get("hote", "").strip(), smtp.get("securite", "starttls")
    port = int(smtp.get("port") or SECURITES.get(mode, SECURITES["starttls"])[1])
    if not hote:
        raise ValueError(_("serveur d'envoi non renseigné"))
    user = smtp.get("utilisateur", "").strip()
    if user and mode == "aucune":
        raise ValueError(_("authentification refusée sans chiffrement : choisissez STARTTLS ou SSL/TLS"))
    ctx = ssl.create_default_context()
    if mode == "ssl":
        s = smtplib.SMTP_SSL(hote, port, timeout=DELAI, context=ctx)
    else:
        s = smtplib.SMTP(hote, port, timeout=DELAI)
    try:
        s.ehlo()
        if mode == "starttls":
            s.starttls(context=ctx)
            s.ehlo()
        if user:
            s.login(user, mot_de_passe or "")
    except Exception:
        s.close()
        raise
    return s


def envoyer(smtp: dict, mot_de_passe: str | None, message: EmailMessage) -> None:
    with ouvrir(smtp, mot_de_passe) as s:
        s.send_message(message)


def tester(smtp: dict, mot_de_passe: str | None) -> None:
    with ouvrir(smtp, mot_de_passe) as s:
        s.noop()

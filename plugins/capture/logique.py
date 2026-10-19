# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Partie sans interface de l'extension « Capture et console » : exécuter une commande, parler à Konsole par D-Bus."""
import os
import re
import shutil
import subprocess

DELAI_COMMANDE = 30          # secondes
SORTIE_MAX = 200 * 1024      # octets conservés
SERVICE = re.compile(r"org\.kde\.konsole-\d+")
SESSION = re.compile(r"^/Sessions/(\d+)$")
COLLAGE_DEBUT, COLLAGE_FIN = "\x1b[200~", "\x1b[201~"      # « bracketed paste » : le shell ne valide pas les retours à la ligne


class AccesRefuse(Exception):
    """Konsole refuse l'API D-Bus qui permet d'envoyer du texte (option de sécurité désactivée par défaut)."""


# ---------- commandes ----------
def executer(commande: str, delai: int = DELAI_COMMANDE, taille_max: int = SORTIE_MAX):
    """(code de retour ou None, sortie standard + erreurs, tronquée ?, délai dépassé ?). La commande passe par le shell :
    elle ne doit être appelée que sur demande explicite de l'utilisateur."""
    try:
        r = subprocess.run(commande, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=delai,
                           stdin=subprocess.DEVNULL)
        brut, code, depasse = r.stdout, r.returncode, False
    except subprocess.TimeoutExpired as ex:
        brut, code, depasse = ex.stdout or b"", None, True
    tronque = len(brut) > taille_max
    return code, brut[:taille_max].decode("utf-8", "replace"), tronque, depasse


# ---------- texte envoyé à une console ----------
def nettoyer_pour_console(texte: str) -> str:
    """Retire tout caractère de contrôle (sauf retour à la ligne et tabulation) : un texte de fiche ne doit pas pouvoir
    injecter de séquence d'échappement dans un terminal. Pas de retour à la ligne final : rien n'est « validé »."""
    texte = texte.replace("\r\n", "\n").replace("\r", "\n").replace(" ", "\n").replace(" ", "\n")
    texte = re.sub(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]", "", texte)
    return texte.rstrip("\n")


def charge_utile(texte: str) -> str:
    """Texte nettoyé, entouré du « collage » du terminal s'il a plusieurs lignes (pas d'exécution ligne par ligne)."""
    return f"{COLLAGE_DEBUT}{texte}{COLLAGE_FIN}" if "\n" in texte else texte


# ---------- Konsole ----------
def trouver_qdbus() -> str | None:
    return next((p for n in ("qdbus6", "qdbus-qt6", "qdbus") if (p := shutil.which(n))), None)


def lancer_konsole() -> int | None:
    """Ouvre une Konsole à part (processus à elle) titrée « Scrinium » ; retourne son PID, qui est aussi celui de son service
    D-Bus (org.kde.konsole-<pid>). None si Konsole n'est pas installé."""
    exe = shutil.which("konsole")
    if not exe:
        return None
    p = subprocess.Popen([exe, "--separate", "--nofork", "-p", "tabtitle=Scrinium"], cwd=os.path.expanduser("~"),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    return p.pid


def _qdbus(qdbus: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([qdbus, *args], capture_output=True, timeout=10)


def _libelle(qdbus: str, service: str, chemin: str) -> str:
    """« titre — dossier courant [programme au premier plan] » : de quoi reconnaître une console parmi d'autres."""
    titre = _qdbus(qdbus, service, chemin, "org.kde.konsole.Session.title", "1").stdout.decode("utf-8", "replace").strip()
    try:
        pid = int(_qdbus(qdbus, service, chemin, "org.kde.konsole.Session.foregroundProcessId").stdout.decode().strip())
        cwd = os.readlink(f"/proc/{pid}/cwd").replace(os.path.expanduser("~"), "~", 1)
        with open(f"/proc/{pid}/comm", encoding="utf-8") as f:
            prog = f.read().strip()
    except (ValueError, OSError):
        return titre or chemin
    return f"{titre or chemin} — {cwd}" + (f" [{prog}]" if prog and prog not in titre else "")


def sessions_konsole(qdbus: str) -> list:
    """[(service, numéro de session, libellé)] de toutes les sessions Konsole ouvertes."""
    res = []
    for service in sorted(set(SERVICE.findall(_qdbus(qdbus).stdout.decode("utf-8", "replace")))):
        objets = _qdbus(qdbus, service).stdout.decode("utf-8", "replace").splitlines()
        for ligne in objets:
            m = SESSION.match(ligne.strip())
            if m:
                res.append((service, int(m[1]), _libelle(qdbus, service, ligne.strip())))
    return res


def envoyer(qdbus: str, service: str, session: int, texte: str) -> None:
    """Tape `texte` dans la session Konsole, SANS le valider. AccesRefuse si l'API est désactivée dans Konsole."""
    r = _qdbus(qdbus, service, f"/Sessions/{session}", "org.kde.konsole.Session.sendText", charge_utile(texte))
    # qdbus écrit ses erreurs sur la sortie standard (constaté avec qdbus6) : on regarde les deux flux
    message = (r.stdout + b"\n" + r.stderr).decode("utf-8", "replace").strip()
    if "AccessDenied" in message:
        raise AccesRefuse(message)
    if r.returncode != 0:
        raise RuntimeError(message or f"qdbus a échoué (code {r.returncode})")

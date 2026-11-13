# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Partie sans interface de l'extension « Sécurité » : « y a-t-il quelqu'un dans ma machine, et qui ? ».

Scrinium LIT l'état de la machine (sessions ouvertes, ports en écoute, accès à distance, comptes, clés SSH, tâches planifiées) avec des commandes
du système en lecture seule, sans shell et sans droits d'administrateur. Rien n'est modifié, rien n'est envoyé.

Principe : on accepte l'état actuel comme « normal » (liste de confiance, rangée dans la fiche, une section par machine) ; ensuite tout
ce qui est NOUVEAU est signalé. Limite à dire clairement : c'est une vue depuis la machine elle-même, pas un antivirus ; quelqu'un qui a déjà
les droits d'administrateur peut cacher ses traces.

Texte d'une fiche :

    #scrinium-securite

    ## machine-exemple
    ok: ecoute|tcp|22
    ok: compte|utilisateur
"""
import base64
import hashlib
import os
import re
import socket
import subprocess
import sys
from dataclasses import dataclass

from scrinium.core.types_fiche import TypeFiche
from scrinium.i18n import N_, _

MARQUE = "#scrinium-securite"
DELAI = 8.0
MAX_CONFIANCE = 2000
CATEGORIES = {"session": N_("Session"), "connexion": N_("Connexion récente"), "ecoute": N_("Port ouvert"), "acces": N_("Accès à distance"),
              "compte": N_("Compte"), "cle": N_("Clé SSH autorisée"), "planifie": N_("Tâche planifiée")}
# Programmes qui donnent la main sur la machine à distance (nom de processus, en minuscules, comme sous-chaîne).
OUTILS_ACCES = ("sshd", "telnetd", "teamviewer", "anydesk", "x11vnc", "vncserver", "xvnc", "tigervnc", "winvnc", "tvnserver", "xrdp", "rustdesk",
                "nxserver", "chrome-remote-desktop", "screenconnect", "connectwise", "logmein", "radmin", "splashtop", "dwagent", "ngrok",
                "screensharingd", "ardagent", "termservice")
LOCAL = ("127.", "::1", "[::1]", "localhost")


@dataclass(frozen=True)
class Constat:
    categorie: str
    cle: str                                             # identité stable (indépendante de la langue) : « ecoute|tcp|22 »
    libelle: str
    detail: str = ""
    expose: bool = False                                 # joignable depuis l'extérieur de la machine
    auto_connu: bool = False                             # va de soi (la session de l'utilisateur courant) : jamais « nouveau »


# ---------- analyse des sorties de commandes (fonctions pures, testées avec des exemples) ----------
def _origine_locale(o: str) -> bool:
    o = o.strip().lower()
    return not o or o.startswith(":") or o.startswith(LOCAL) or "tmux" in o or "screen" in o


def lire_who(texte: str) -> list:
    """Sortie de `who` (Linux, macOS) -> [(utilisateur, terminal, origine)] ; origine vide ou « :0 » = locale."""
    res = []
    for ligne in texte.splitlines():
        champs = ligne.split()
        if len(champs) < 2:
            continue
        m = re.search(r"\(([^)]*(?:\([^)]*\))?[^)]*)\)\s*$", ligne)
        res.append((champs[0], champs[1], m[1] if m else ""))
    return res


def lire_ss(texte: str) -> list:
    """Sortie de `ss -H -tulnp` (Linux) -> [(protocole, adresse, port, programmes)]."""
    res = []
    for ligne in texte.splitlines():
        c = ligne.split()
        if len(c) < 5 or c[0] not in ("tcp", "udp"):
            continue
        adresse, _sep, port = c[4].rpartition(":")
        if not port.isdigit():
            continue
        progs = re.findall(r'\(\("([^"]+)"', ligne) + re.findall(r'\),\("([^"]+)"', ligne)
        res.append((c[0], adresse, int(port), sorted(set(progs))))
    return res


def lire_lsof(texte: str) -> list:
    """Sortie de `lsof -nP -iTCP -sTCP:LISTEN` (macOS) -> [(« tcp », adresse, port, [programme])]."""
    res = []
    for ligne in texte.splitlines()[1:]:
        c = ligne.split()
        m = re.search(r"(\S+):(\d+)\s*\(LISTEN\)", ligne)
        if len(c) >= 9 and m:
            res.append(("tcp", m[1], int(m[2]), [c[0]]))
    return res


def lire_netstat_windows(texte: str) -> list:
    """Sortie de `netstat -ano -p tcp` (Windows) -> [(« tcp », adresse, port, [pid])] des ports en écoute (indépendant de la langue : adresse distante 0.0.0.0:0)."""
    res = []
    for ligne in texte.splitlines():
        c = ligne.split()
        if len(c) >= 5 and c[0].upper() == "TCP" and c[2] in ("0.0.0.0:0", "[::]:0", "*:0"):
            adresse, _sep, port = c[1].rpartition(":")
            if port.isdigit():
                res.append(("tcp", adresse, int(port), [c[4]]))
    return res


def lire_tasklist_csv(texte: str) -> dict:
    """Sortie de `tasklist /fo csv /nh` (Windows) -> {pid: nom}."""
    res = {}
    for ligne in texte.splitlines():
        c = [x.strip('"') for x in ligne.strip().split('","')]
        if len(c) >= 2 and c[1].strip('"').isdigit():
            res[c[1].strip('"')] = c[0].strip('"')
    return res


def lire_query_user(texte: str) -> list:
    """Sortie de `query user` (Windows) -> [(utilisateur, session, origine)] ; une session « rdp-… » est à distance."""
    res = []
    for ligne in texte.splitlines()[1:]:
        c = ligne.replace(">", " ", 1).split()
        if not c:
            continue
        session = c[1] if len(c) > 1 and not c[1].isdigit() else ""
        res.append((c[0], session, "rdp" if session.lower().startswith("rdp") else ""))
    return res


def lire_net_user(texte: str) -> list:
    """Sortie de `net user` (Windows) -> noms de comptes."""
    noms, dedans = [], False
    for ligne in texte.splitlines():
        if ligne.startswith("---"):
            dedans = True
        elif dedans and ligne.strip():
            if not re.match(r"^\S.*\.$", ligne.strip()) or ligne.strip().count(" ") > 40:
                noms += ligne.split()
            else:
                break
    return noms


def lire_passwd(texte: str) -> list:
    """Contenu de /etc/passwd -> comptes qui peuvent ouvrir une session : root et les comptes de personnes (uid 1000 et plus, avec un vrai interpréteur)."""
    res = []
    for ligne in texte.splitlines():
        c = ligne.split(":")
        if len(c) >= 7 and c[2].isdigit():
            uid = int(c[2])
            if (uid == 0 or 1000 <= uid < 60000) and not c[6].strip().endswith(("nologin", "false")):
                res.append(c[0])
    return res


def lire_dscl(texte: str) -> list:
    """Sortie de `dscl . -list /Users UniqueID` (macOS) -> comptes de personnes (uid 500 et plus) et root."""
    res = []
    for ligne in texte.splitlines():
        c = ligne.split()
        if len(c) == 2 and c[1].isdigit() and (int(c[1]) == 0 or int(c[1]) >= 500) and not c[0].startswith("_"):
            res.append(c[0])
    return res


def empreinte_cle(blob: str) -> str:
    """Empreinte SHA256 d'une clé publique SSH (comme `ssh-keygen -l`) ; chaîne vide si illisible."""
    try:
        return "SHA256:" + base64.b64encode(hashlib.sha256(base64.b64decode(blob, validate=True)).digest()).decode().rstrip("=")
    except (ValueError, TypeError):
        return ""


def lire_authorized_keys(texte: str) -> list:
    """Contenu d'authorized_keys -> [(empreinte, commentaire)]."""
    res = []
    for ligne in texte.splitlines():
        if not ligne.strip() or ligne.lstrip().startswith("#"):
            continue
        c = ligne.split()
        for i, mot in enumerate(c):
            if re.match(r"(ssh-|ecdsa-|sk-)", mot) and i + 1 < len(c):
                fp = empreinte_cle(c[i + 1])
                if fp:
                    res.append((fp, " ".join(c[i + 2:])[:60]))
                break
    return res


def lire_last(texte: str) -> list:
    """Sortie de `last -i -w` (Linux) -> [(utilisateur, adresse)] des connexions venues d'une autre adresse que la machine."""
    res = []
    for ligne in texte.splitlines():
        c = ligne.split()
        if len(c) >= 3 and c[0] not in ("reboot", "wtmp", "shutdown") and c[2] not in ("0.0.0.0", "::") and not c[2].startswith(("127.", "::1")) \
                and (re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", c[2]) or (re.fullmatch(r"[0-9a-fA-F:]+", c[2]) and c[2].count(":") >= 2)):
            res.append((c[0], c[2]))
    return res


def lire_processus(texte: str) -> list:
    """Noms de processus connus pour donner la main à distance (sans doublon), d'après une liste de noms."""
    vus = []
    for nom in texte.split():
        n = nom.strip().lower()
        if any(o in n for o in OUTILS_ACCES) and n not in vus:
            vus.append(n)
    return vus


# ---------- les constats ----------
def _expose(adresse: str) -> bool:
    return not adresse.startswith(LOCAL)


def _ports(liste: list, noms_pid: dict | None = None) -> list:
    groupes = {}
    for proto, adresse, port, progs in liste:
        if proto == "udp" and port >= 32768:             # ports UDP éphémères : tirés au hasard à chaque lancement, ils fausseraient toute comparaison
            continue
        progs = [noms_pid.get(p, p) for p in progs] if noms_pid else progs
        g = groupes.setdefault((proto, port), {"expose": False, "progs": set()})
        g["expose"] = g["expose"] or _expose(adresse)
        g["progs"].update(progs)
    res = []
    for (proto, port), g in sorted(groupes.items(), key=lambda x: (x[0][1], x[0][0])):
        progs = ", ".join(sorted(g["progs"]))
        res.append(Constat("ecoute", f"ecoute|{proto}|{port}", f"{proto.upper()} {port}" + (f" ({progs})" if progs else ""),
                           _("Accessible depuis le réseau") if g["expose"] else _("Seulement depuis cette machine"), g["expose"]))
    return res


def scanner(systeme: str, executer, lire, utilisateur: str, maison: str) -> list:
    """Constats pour `systeme` (« linux », « windows » ou « macos »). `executer(argv)` renvoie la sortie d'une commande ('' si elle échoue),
    `lire(chemin)` le contenu d'un fichier (None s'il est illisible) : ainsi l'analyse se teste sans toucher à la machine."""
    res = []
    if systeme in ("linux", "macos"):
        for u, tty, origine in lire_who(executer(["who"])):
            if _origine_locale(origine):
                res.append(Constat("session", f"session|{u}|local", _("Session de %s (locale)") % u, tty, False, u == utilisateur))
            else:
                res.append(Constat("session", f"session|{u}|{origine}", _("Session de %(u)s depuis %(o)s") % {"u": u, "o": origine}, tty, True))
    elif systeme == "windows":
        for u, session, origine in lire_query_user(executer(["query", "user"])):
            if origine:
                res.append(Constat("session", f"session|{u}|{origine}", _("Session de %(u)s à distance (%(s)s)") % {"u": u, "s": session}, session, True))
            else:
                res.append(Constat("session", f"session|{u}|local", _("Session de %s (locale)") % u, session, False, u.lower() == utilisateur.lower()))
    if systeme == "linux":
        res += _ports(lire_ss(executer(["ss", "-H", "-tulnp"])))
        vues = set()
        for u, adresse in lire_last(executer(["last", "-i", "-w", "-n", "40"])):
            if (u, adresse) not in vues:
                vues.add((u, adresse))
                res.append(Constat("connexion", f"connexion|{u}|{adresse}", _("Connexion de %(u)s depuis %(a)s") % {"u": u, "a": adresse}, "", True))
        for nom in lire_passwd(lire("/etc/passwd") or ""):
            res.append(Constat("compte", f"compte|{nom}", nom))
        outils = lire_processus(executer(["ps", "-eo", "comm="]))
    elif systeme == "macos":
        res += _ports(lire_lsof(executer(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"])))
        for nom in lire_dscl(executer(["dscl", ".", "-list", "/Users", "UniqueID"])):
            res.append(Constat("compte", f"compte|{nom}", nom))
        outils = lire_processus(executer(["ps", "-axco", "comm"]))
    elif systeme == "windows":
        pids = lire_tasklist_csv(executer(["tasklist", "/fo", "csv", "/nh"]))
        res += _ports(lire_netstat_windows(executer(["netstat", "-ano", "-p", "tcp"])), pids)
        for nom in lire_net_user(executer(["net", "user"])):
            res.append(Constat("compte", f"compte|{nom}", nom))
        outils = lire_processus(" ".join(n.replace(" ", "_") for n in pids.values()))
        rdp = executer(["reg", "query", r"HKLM\SYSTEM\CurrentControlSet\Control\Terminal Server", "/v", "fDenyTSConnections"])
        if re.search(r"0x0\b", rdp):
            res.append(Constat("acces", "acces|bureau-a-distance", _("Bureau à distance (RDP) activé"), "", True))
    else:
        return res
    for nom in outils:
        res.append(Constat("acces", f"acces|{nom}", nom, _("Programme en cours d'exécution"), True))
    if systeme in ("linux", "macos"):
        for fichier in (os.path.join(maison, ".ssh", "authorized_keys"), "/root/.ssh/authorized_keys"):
            for fp, commentaire in lire_authorized_keys(lire(fichier) or ""):
                res.append(Constat("cle", f"cle|{fp[:23]}", commentaire or fp[:23], f"{fichier} · {fp}", True))
        for ligne in executer(["crontab", "-l"]).splitlines():
            if ligne.strip() and not ligne.lstrip().startswith("#"):
                res.append(Constat("planifie", "planifie|" + hashlib.sha256(ligne.strip().encode()).hexdigest()[:12], ligne.strip()[:70]))
    vus, uniques = set(), []
    for c in res:
        if c.cle not in vus:
            vus.add(c.cle)
            uniques.append(c)
    return uniques


def systeme_courant() -> str:
    return "windows" if sys.platform.startswith("win") else "macos" if sys.platform == "darwin" else "linux"


def executer(argv: list) -> str:
    """Lance une commande de LECTURE (sans shell, sans droits d'administrateur) ; '' si elle manque, échoue ou dépasse le délai."""
    try:
        p = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=DELAI, errors="replace")
        return p.stdout if p.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def lire_fichier(chemin: str):
    try:
        with open(chemin, encoding="utf-8", errors="replace") as f:
            return f.read(200_000)
    except OSError:
        return None


def analyser_machine() -> list:
    """Constats de CETTE machine, maintenant (bloquant : à lancer hors du fil de l'interface)."""
    try:
        utilisateur = os.getlogin()
    except OSError:
        utilisateur = os.environ.get("USER") or os.environ.get("USERNAME") or ""
    return scanner(systeme_courant(), executer, lire_fichier, utilisateur, os.path.expanduser("~"))


# ---------- la fiche (liste de confiance, une section par machine) ----------
def nom_machine() -> str:
    return socket.gethostname()


def lire(texte: str | None) -> dict:
    """{machine: ensemble de clés « normales »}."""
    res, courante = {}, None
    lignes = (texte or "").lstrip("﻿").splitlines()
    for ligne in lignes[1:] if lignes and lignes[0].startswith(MARQUE) else lignes:
        if ligne.startswith("## "):
            courante = res.setdefault(ligne[3:].strip(), set())
        elif courante is not None and ligne.startswith("ok:") and len(courante) < MAX_CONFIANCE:
            cle = ligne[3:].strip()
            if cle and "|" in cle:
                courante.add(cle)
    return res


def ecrire(confiance: dict) -> str:
    sortie = [MARQUE]
    for machine, cles in confiance.items():
        sortie += ["", "## " + machine] + ["ok: " + c for c in sorted(cles)]
    return "\n".join(sortie) + "\n"


def texte_neuf() -> str:
    return MARQUE + "\n"


TYPE = TypeFiche("securite", N_("Sécurité"), "security-medium", executable=True, modele=texte_neuf)


def statut(c: Constat, confiance: set | None) -> str:
    """« connu » (accepté ou évident), « a_verifier » (nouveau ET joignable depuis l'extérieur), « nouveau » (nouveau)."""
    if c.auto_connu or (confiance is not None and c.cle in confiance):
        return "connu"
    return "a_verifier" if c.expose else "nouveau"


def nouveautes(constats: list, confiance: set | None) -> list:
    """Constats nouveaux À SIGNALER ; vide si la machine n'a pas encore de référence (confiance None : on n'inonde pas de signalements au premier essai).
    Un port ouvert seulement à cette machine (127.0.0.1) change à chaque lancement d'un programme : il se voit dans le tableau, il n'est pas signalé."""
    if confiance is None:
        return []
    return [c for c in constats if statut(c, confiance) != "connu" and not (c.categorie == "ecoute" and not c.expose)]

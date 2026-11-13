# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Partie sans interface de l'extension « Supervision » : la fiche (une section par machine), les contrôles (ping, ports, page web, mesures par
SSH) et l'analyse des résultats. Aucun shell : chaque commande est une liste d'arguments, et une valeur qui pourrait passer pour une option
(« -oProxyCommand=… ») est refusée."""
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta
from urllib.parse import urlparse

from scrinium.core.types_fiche import TypeFiche
from scrinium.i18n import N_, _

MAX_MACHINES = 60
MARQUE = "#scrinium-supervision"
DELAI = 4.0                                              # secondes par contrôle
SEUIL_DISQUE = 90                                        # % d'occupation au-delà duquel la machine est « en alerte »
_HOTE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._:\-\[\]]{0,252}")
_CIBLE_SSH = re.compile(r"(?:[A-Za-z0-9_][A-Za-z0-9._\-]{0,63}@)?[A-Za-z0-9_][A-Za-z0-9._:\-\[\]]{0,252}")
_CLES = ("adresse", "ports", "web", "ssh", "seuil_disque", "watts", "depuis")
# Commande envoyée par SSH : fixe, en lecture seule. Elle ne dépend d'aucune valeur de la fiche.
COMMANDE_SSH = "cat /proc/loadavg /proc/uptime; grep -E '^(MemTotal|MemAvailable):' /proc/meminfo; df -P /; nproc"


def hote_valide(h: str) -> bool:
    return bool(_HOTE.fullmatch(h or ""))


def cible_ssh_valide(c: str) -> bool:
    return bool(_CIBLE_SSH.fullmatch(c or ""))


def web_valide(u: str) -> bool:
    p = urlparse(u or "")
    return p.scheme in ("http", "https") and bool(p.hostname) and not any(c.isspace() or ord(c) < 32 for c in u)


def lire_ports(texte) -> list:
    """« 22, 80 443 » -> [22, 80, 443] (1 à 65535, sans doublon, 12 au plus)."""
    if isinstance(texte, (list, tuple)):
        texte = " ".join(str(x) for x in texte)
    ports = []
    for m in re.findall(r"\d+", str(texte or "")):
        p = int(m)
        if 1 <= p <= 65535 and p not in ports:
            ports.append(p)
    return ports[:12]


def lire_watts(texte) -> tuple | None:
    """« 40-200 » (ou « 40 200 », ou un tuple) -> (40, 200) : watts au repos et à pleine charge. None si absent ou incohérent."""
    if isinstance(texte, (list, tuple)):
        texte = " ".join(str(x) for x in texte)
    nombres = re.findall(r"\d+", str(texte or ""))
    if len(nombres) != 2:
        return None
    repos, maxi = int(nombres[0]), int(nombres[1])
    return (repos, maxi) if 1 <= repos <= maxi <= 5000 else None


def lire_date(texte) -> str:
    """« 2026-11-10 » ou « 10/11/2026 » -> « 2026-11-10 » ; chaîne vide si absente ou invalide."""
    t = str(texte or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(t, fmt).date().isoformat()
        except ValueError:
            pass
    return ""


PLAFOND = 180                                            # secondes : au-delà, l'intervalle entre deux contrôles n'est pas compté


def cumuler(etat: dict | None, depuis: str, watts: int | None, maintenant: float, plafond: float = PLAFOND) -> dict | None:
    """Cumul d'énergie ESTIMÉE (Wh) depuis la date de mise en service : puissance estimée x temps écoulé depuis le contrôle précédent.
    Un intervalle plus long que `plafond` (Scrinium fermé, ordinateur en veille…) n'est PAS compté. Changer la date remet le cumul à zéro.
    -> {"depuis", "wh", "secondes", "dernier"} ; None sans date."""
    if not depuis:
        return None
    try:
        debut = datetime.strptime(depuis, "%Y-%m-%d").timestamp()
    except ValueError:
        return None
    if not etat or etat.get("depuis") != depuis:
        etat = {"depuis": depuis, "wh": 0.0, "secondes": 0.0, "dernier": None, "jours": {}}
    nouveau = dict(etat, dernier=maintenant)
    dernier = etat.get("dernier")
    if watts is not None and dernier is not None and maintenant >= debut:
        dt = maintenant - max(dernier, debut)
        if 0 < dt <= plafond:
            ajout = watts * dt / 3600
            nouveau["wh"] = etat["wh"] + ajout
            nouveau["secondes"] = etat["secondes"] + dt
            jour = datetime.fromtimestamp(maintenant).date().isoformat()
            jours = dict(etat.get("jours") or {})
            jours[jour] = jours.get(jour, 0.0) + ajout
            nouveau["jours"] = dict(sorted(jours.items())[-MAX_JOURS:])
    return nouveau


MAX_JOURS = 400                                          # jours d'historique gardés (de quoi comparer deux mois et deux semaines)


def energie_periode(etat: dict | None, debut: date, fin: date) -> float:
    """Wh estimés entre deux jours (inclus), d'après l'énergie rangée par jour."""
    if not etat:
        return 0.0
    return sum(v for j, v in (etat.get("jours") or {}).items() if debut.isoformat() <= j <= fin.isoformat())


def periodes(etat: dict | None, aujourdhui: date) -> dict:
    """Énergie estimée de la semaine en cours (depuis lundi), de la semaine précédente, du mois en cours et du mois précédent."""
    lundi = aujourdhui - timedelta(days=aujourdhui.weekday())
    premier = aujourdhui.replace(day=1)
    fin_mois_prec = premier - timedelta(days=1)
    return {"lundi": lundi, "semaine": energie_periode(etat, lundi, aujourdhui),
            "semaine_prec": energie_periode(etat, lundi - timedelta(days=7), lundi - timedelta(days=1)),
            "mois": energie_periode(etat, premier, aujourdhui),
            "mois_prec": energie_periode(etat, fin_mois_prec.replace(day=1), fin_mois_prec), "premier": premier,
            "premier_prec": fin_mois_prec.replace(day=1)}


def formater_energie(wh: float) -> str:
    return f"{wh:.0f} Wh" if wh < 1000 else f"{wh / 1000:.2f} kWh"


def puissance_estimee(m: dict, mesures: dict) -> int | None:
    """Estimation en watts : repos + (max - repos) x charge. None sans valeurs « watts » dans la fiche ou sans mesure de charge.
    C'est une ESTIMATION, jamais une mesure : l'interface le dit."""
    w, c = m.get("watts"), charge_pct(mesures)
    return None if not w or c is None else round(w[0] + (w[1] - w[0]) * c / 100)


def normaliser(m) -> dict | None:
    """Machine valide (champs nettoyés, valeurs dangereuses ou incorrectes écartées) ou None sans nom ni adresse valides."""
    if not isinstance(m, dict):
        return None
    nom = " ".join(str(m.get("nom", "")).split())[:80]
    adresse = str(m.get("adresse", "")).strip()
    if not nom or not hote_valide(adresse):
        return None
    ssh = str(m.get("ssh", "")).strip()
    web = str(m.get("web", "")).strip()
    try:
        seuil = int(str(m.get("seuil_disque", "")).strip() or SEUIL_DISQUE)
    except ValueError:
        seuil = SEUIL_DISQUE
    return {"nom": nom, "adresse": adresse, "ports": lire_ports(m.get("ports", "")),
            "web": web if web_valide(web) else "", "ssh": ssh if cible_ssh_valide(ssh) else "",
            "seuil_disque": min(max(seuil, 1), 100), "watts": lire_watts(m.get("watts", "")),
            "depuis": lire_date(m.get("depuis", ""))}


def cle(m: dict) -> str:
    """Identité d'une machine pour mémoriser son dernier état (un même nom sur deux adresses reste distinct)."""
    return f"{m['nom']}|{m['adresse']}"


def normaliser_liste(liste) -> list:
    if not isinstance(liste, list):
        return []
    return [m for m in (normaliser(x) for x in liste) if m][:MAX_MACHINES]


# ---------- la fiche ----------
#     #scrinium-supervision
#     ## Serveur
#     adresse: 192.0.2.10
#     ports: 22, 80
#     web: http://192.0.2.10/
#     ssh: root@192.0.2.10
#     seuil_disque: 90
def depuis_texte(texte: str | None) -> list:
    machines, courante = [], None
    lignes = (texte or "").lstrip("﻿").splitlines()
    for ligne in lignes[1:] if lignes and lignes[0].startswith(MARQUE) else lignes:
        if ligne.startswith("## "):
            courante = {"nom": ligne[3:]}
            machines.append(courante)
        elif courante is not None and ":" in ligne:
            cle, _sep, valeur = ligne.partition(":")
            if cle.strip().lower() in _CLES:
                courante[cle.strip().lower()] = valeur.strip()
    return normaliser_liste(machines)


def en_texte(machines: list) -> str:
    sortie = [MARQUE]
    for m in normaliser_liste(machines):
        sortie += ["", "## " + m["nom"], "adresse: " + m["adresse"]]
        if m["ports"]:
            sortie.append("ports: " + ", ".join(str(p) for p in m["ports"]))
        if m["web"]:
            sortie.append("web: " + m["web"])
        if m["ssh"]:
            sortie.append("ssh: " + m["ssh"])
        if m["watts"]:
            sortie.append("watts: %d-%d" % m["watts"])
        if m["depuis"]:
            sortie.append("depuis: " + m["depuis"])
        if m["seuil_disque"] != SEUIL_DISQUE:
            sortie.append(f"seuil_disque: {m['seuil_disque']}")
    return "\n".join(sortie) + "\n"


def texte_neuf() -> str:
    return en_texte([{"nom": _("Cette machine"), "adresse": "127.0.0.1", "ports": [22]}])


TYPE = TypeFiche("supervision", N_("Supervision"), "network-server", executable=True, modele=texte_neuf)


def exemples() -> list:
    """[(thème, titre, texte)] : une fiche d'exemple qui ne regarde que cette machine."""
    return [(_("Supervision (exemples)"), _("Exemple · Mes machines"), en_texte(
        [{"nom": _("Cette machine"), "adresse": "127.0.0.1", "ports": [], "watts": "40-150", "depuis": date.today().isoformat()},
         {"nom": _("Exemple de serveur (à adapter)"), "adresse": "192.0.2.10", "ports": [22, 80], "web": "http://192.0.2.10/",
          "ssh": "root@192.0.2.10", "watts": "30-120"}]))]


# ---------- contrôles ----------
def ping(adresse: str, delai: float = DELAI) -> bool:
    """La machine répond au ping ? Faux si la commande `ping` manque ou si l'adresse est refusée."""
    if not hote_valide(adresse):
        return False
    if sys.platform.startswith("win"):
        argv = ["ping", "-n", "1", "-w", str(int(delai * 1000)), adresse]
    else:
        argv = ["ping", "-c", "1", "-W", str(max(1, int(delai))), adresse]
    try:
        return subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=delai + 2).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def port_ouvert(adresse: str, port: int, delai: float = DELAI) -> bool:
    try:
        with socket.create_connection((adresse.strip("[]"), port), timeout=delai):
            return True
    except OSError:
        return False


def page_web(url: str, delai: float = DELAI) -> int | None:
    """Code HTTP de la page (200, 404…), ou None si elle ne répond pas. Les redirections sont suivies par urllib ; seuls http et https passent."""
    if not web_valide(url):
        return None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Scrinium-supervision"}), timeout=delai) as r:
            return int(r.status)
    except urllib.error.HTTPError as ex:
        return int(ex.code)
    except (OSError, ValueError):
        return None


def commande_ssh(cible: str) -> list:
    """Arguments SSH (sans shell, sans mot de passe : `BatchMode`). ValueError si la cible ressemble à une option."""
    if not cible_ssh_valide(cible):
        raise ValueError(_("cible SSH refusée"))
    return ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={int(DELAI)}", "--", cible, COMMANDE_SSH]


def analyser_mesures(texte: str) -> dict:
    """Sortie de COMMANDE_SSH -> {"charge", "uptime_s", "memoire_pct", "disque_pct"} (clés absentes si illisibles)."""
    lignes = (texte or "").splitlines()
    r = {}
    if lignes:
        m = re.match(r"\s*([\d.]+)\s", lignes[0])
        if m:
            r["charge"] = float(m[1])
    if len(lignes) > 1:
        m = re.match(r"\s*([\d.]+)\s", lignes[1])
        if m:
            r["uptime_s"] = int(float(m[1]))
    total = dispo = None
    for ligne in lignes:
        m = re.match(r"(MemTotal|MemAvailable):\s+(\d+)", ligne)
        if m:
            total, dispo = (int(m[2]), dispo) if m[1] == "MemTotal" else (total, int(m[2]))
    if total and dispo is not None:
        r["memoire_pct"] = round(100 * (total - dispo) / total)
    for ligne in lignes:
        m = re.search(r"\s(\d+)%\s+/\s*$", ligne)
        if m:
            r["disque_pct"] = int(m[1])
    if lignes and re.fullmatch(r"\s*\d{1,4}\s*", lignes[-1]):
        r["coeurs"] = max(1, int(lignes[-1]))
    return r


def charge_pct(mesures: dict) -> int | None:
    """Charge en % de la capacité (charge sur 1 minute / nombre de cœurs, 1 cœur si inconnu), plafonnée à 100 ; None sans mesure."""
    if "charge" not in mesures:
        return None
    return min(100, round(100 * mesures["charge"] / mesures.get("coeurs", 1)))


def mesures_ssh(cible: str) -> dict:
    """Mesures lues sur la machine par SSH. OSError / ValueError / TimeoutExpired si elle ne répond pas ou si la clé n'est pas acceptée."""
    p = subprocess.run(commande_ssh(cible), stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=DELAI * 3)
    if p.returncode != 0:
        raise OSError((p.stderr or "").strip().splitlines()[-1] if (p.stderr or "").strip() else _("SSH a échoué"))
    return analyser_mesures(p.stdout)


def est_locale(adresse: str) -> bool:
    return adresse.strip("[]").lower() in ("127.0.0.1", "localhost", "::1")


def mesures_locales() -> dict:
    """Mesures de CETTE machine (Linux), sans SSH : on lit directement /proc et le disque racine. {} ailleurs."""
    try:
        with open("/proc/loadavg", encoding="ascii") as f1, open("/proc/uptime", encoding="ascii") as f2, \
                open("/proc/meminfo", encoding="ascii") as f3:
            r = analyser_mesures(f1.readline() + f2.readline() + f3.read())
        u = shutil.disk_usage("/")
        r["disque_pct"] = round(100 * u.used / u.total)
        r["coeurs"] = max(1, os.cpu_count() or 1)
        return r
    except (OSError, ValueError, ZeroDivisionError):
        return {}


def sonder(m: dict) -> dict:
    """Tous les contrôles demandés par la fiche pour cette machine (bloquant : à lancer hors du fil de l'interface).
    -> {"ping", "ports": {22: True}, "web": code|None (ou absent), "mesures": {...} (ou absent), "erreur_ssh": str (ou absent)}"""
    r = {"ping": ping(m["adresse"]), "ports": {p: port_ouvert(m["adresse"], p) for p in m["ports"]}}
    if m["web"]:
        r["web"] = page_web(m["web"])
    if not m["ssh"] and est_locale(m["adresse"]):
        r["mesures"] = mesures_locales()
    if m["ssh"]:
        try:
            r["mesures"] = mesures_ssh(m["ssh"])
        except (OSError, ValueError, subprocess.SubprocessError) as ex:
            r["erreur_ssh"] = str(ex)[:200]
    return r


def etat(m: dict, r: dict) -> tuple:
    """(« ok » | « alerte » | « panne », [raisons]). Panne : ni ping ni port ne répondent. Alerte : un contrôle échoue ou le disque est presque plein."""
    raisons = []
    reponses = [r.get("ping")] + list(r.get("ports", {}).values())
    if not any(reponses):
        return "panne", [_("ne répond pas")]
    for p, ouvert in r.get("ports", {}).items():
        if not ouvert:
            raisons.append(_("port %d fermé") % p)
    if "web" in r and (r["web"] is None or r["web"] >= 400):
        raisons.append(_("page web en erreur") if r["web"] else _("page web muette"))
    if r.get("erreur_ssh"):
        raisons.append(_("SSH : %s") % r["erreur_ssh"])
    d = r.get("mesures", {}).get("disque_pct")
    if d is not None and d >= m["seuil_disque"]:
        raisons.append(_("disque à %d %%") % d)
    return ("alerte" if raisons else "ok"), raisons


def duree(secondes: int) -> str:
    j, reste = divmod(int(secondes), 86400)
    h, reste = divmod(reste, 3600)
    return f"{j} j {h} h" if j else f"{h} h {reste // 60} min"

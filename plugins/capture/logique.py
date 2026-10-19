# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Partie sans interface de l'extension « Capture et console » : exécuter une commande, parler à Konsole par D-Bus."""
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time

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


SCRIPT_PREMIER_PLAN = """(function () {
    var pid = %d;
    var liste = workspace.windowList ? workspace.windowList() : workspace.clientList();
    for (var i = 0; i < liste.length; i++) {
        if (liste[i].pid === pid) {
            var w = liste[i];
            if (w.minimized) { w.minimized = false; }
            if ("activeWindow" in workspace) { workspace.activeWindow = w; } else { workspace.activeClient = w; }
            break;
        }
    }
})();
"""


def mettre_au_premier_plan(qdbus: str, service: str) -> bool:
    """Ramène devant la fenêtre de la Konsole `service` (org.kde.konsole-<pid>) grâce à un petit script KWin (KDE, X11 ou
    Wayland), retrouvée par son numéro de processus. False, sans erreur, si ce n'est pas possible (autre bureau)."""
    m = re.search(r"-(\d+)$", service)
    if not m:
        return False
    fd, chemin = tempfile.mkstemp(suffix=".js", prefix="scrinium-focus-")
    nom = f"scrinium-focus-{os.getpid()}-{time.time_ns()}"
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(SCRIPT_PREMIER_PLAN % int(m[1]))
        r = _qdbus(qdbus, "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.loadScript", chemin, nom)
        ident = r.stdout.decode().strip()
        if r.returncode != 0 or not ident.lstrip("-").isdigit() or int(ident) < 0:
            return False
        _qdbus(qdbus, "org.kde.KWin", f"/Scripting/Script{ident}", "org.kde.kwin.Script.run")
        time.sleep(0.3)                                       # laisse le script s'exécuter avant de le décharger
        _qdbus(qdbus, "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.unloadScript", nom)
        return True
    except (OSError, subprocess.SubprocessError):
        return False
    finally:
        try:
            os.unlink(chemin)
        except OSError:
            pass


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


# ---------- actions préparées (panneau d'icônes) ----------
MODES = {
    "taper": "Taper dans la console, sans valider",
    "executer": "Exécuter (après confirmation) et insérer la sortie dans la fiche",
    "copier": "Copier dans le presse-papiers",
}
MAX_ACTIONS = 200
EXEMPLES = (
    {"nom": "Réseau", "icone": "network-wired", "mode": "executer", "commande": "ip -br a",
     "description": "Adresses des interfaces réseau."},
    {"nom": "Disques", "icone": "drive-harddisk", "mode": "executer", "commande": "df -h",
     "description": "Espace disque par système de fichiers."},
    {"nom": "Services en échec", "icone": "dialog-warning", "mode": "executer", "commande": "systemctl --failed --no-pager",
     "description": "Unités systemd en erreur."},
    {"nom": "Erreurs du boot", "icone": "dialog-error", "mode": "executer",
     "commande": "journalctl -p err -b --no-pager | tail -n 50", "description": "50 dernières erreurs depuis le démarrage."},
    {"nom": "Git status", "icone": "vcs-normal", "mode": "taper", "commande": "git status",
     "description": "État du dépôt de la console (tapé, à valider vous-même)."},
    {"nom": "Chercher la sélection", "icone": "edit-find", "mode": "taper", "commande": "grep -rn {selection} .",
     "description": "Tape un grep du texte sélectionné dans la fiche (guillemets à ajouter si besoin)."},
)


def normaliser_action(a) -> dict | None:
    """Action valide (champs nettoyés, mode connu) ou None si elle n'a ni nom ni commande."""
    if not isinstance(a, dict):
        return None
    nom, commande = str(a.get("nom", "")).strip()[:60], str(a.get("commande", "")).strip("\n")[:4000]
    if not nom or not commande.strip():
        return None
    mode = a.get("mode") if a.get("mode") in MODES else "taper"
    return {"nom": nom, "icone": str(a.get("icone", "")).strip()[:80] or "system-run", "mode": mode,
            "commande": commande, "description": str(a.get("description", "")).strip()[:300]}


def normaliser_liste(liste) -> list:
    if not isinstance(liste, list):
        return []
    return [a for a in (normaliser_action(x) for x in liste) if a][:MAX_ACTIONS]


def exporter_actions(actions: list) -> str:
    return json.dumps({"scrinium_actions": 1, "actions": normaliser_liste(actions)}, ensure_ascii=False, indent=2)


def importer_actions(texte: str) -> list:
    """Actions lues dans un fichier d'export. ValueError si ce n'en est pas un."""
    try:
        d = json.loads(texte)
    except ValueError as ex:
        raise ValueError("fichier JSON invalide") from ex
    if not isinstance(d, dict) or d.get("scrinium_actions") != 1:
        raise ValueError("ce n'est pas un export d'actions de Scrinium")
    actions = normaliser_liste(d.get("actions"))
    if not actions:
        raise ValueError("aucune action valide dans ce fichier")
    return actions


def citer(texte: str) -> str:
    """Texte rendu inoffensif pour le shell (une sélection ne doit jamais pouvoir ajouter de commande)."""
    return shlex.quote(texte) if os.name == "posix" else subprocess.list2cmdline([texte])


_VARIABLE = re.compile(r"\{(selection|fiche)\}")


def utilise_selection(commande: str) -> bool:
    return "{selection}" in commande


def etendre(commande: str, selection: str, titre: str, mode: str) -> str:
    """Remplace {selection} et {fiche}. Mode « executer » (shell) : valeurs entre guillemets du shell ; sinon telles quelles
    (« taper » : relues par l'utilisateur avant validation ; « copier » : jamais exécutées)."""
    valeurs = {"selection": selection, "fiche": titre}
    return _VARIABLE.sub(lambda m: citer(valeurs[m[1]]) if mode == "executer" else valeurs[m[1]], commande)

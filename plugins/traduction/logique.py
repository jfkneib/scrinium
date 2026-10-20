# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Partie sans interface de l'extension « Traduction » : langues, consigne TranslateGemma, découpage, serveur llama.cpp
lancé à la demande, téléchargement du modèle. Bibliothèque standard seule."""
import glob
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

# code : (nom anglais pour la consigne du modèle, nom français affiché)
LANGUES = {
    "fr": ("French", "français"), "en": ("English", "anglais"), "es": ("Spanish", "espagnol"), "de": ("German", "allemand"),
    "it": ("Italian", "italien"), "pt": ("Portuguese", "portugais"), "nl": ("Dutch", "néerlandais"), "pl": ("Polish", "polonais"),
    "ru": ("Russian", "russe"), "uk": ("Ukrainian", "ukrainien"), "tr": ("Turkish", "turc"), "ar": ("Arabic", "arabe"),
    "zh": ("Chinese", "chinois"), "ja": ("Japanese", "japonais"), "ko": ("Korean", "coréen"), "hi": ("Hindi", "hindi"),
    "sv": ("Swedish", "suédois"), "da": ("Danish", "danois"), "fi": ("Finnish", "finnois"), "el": ("Greek", "grec"),
    "cs": ("Czech", "tchèque"), "ro": ("Romanian", "roumain"), "hu": ("Hungarian", "hongrois"),
    "vi": ("Vietnamese", "vietnamien"), "id": ("Indonesian", "indonésien"),
}
MORCEAU_MAX = 1500                 # caractères par requête (contexte du serveur : 4096 jetons)
CONTEXTE = 4096
TEXTE_MAX = 200_000                # au-delà, la traduction est refusée (il faut choisir une partie)
DELAI_REQUETE = 300                # secondes
DELAI_DEMARRAGE = 180
HOTES_LOCAUX = ("127.0.0.1", "localhost", "::1", "[::1]")

# modèles proposés (quantifiés Q4_K_M depuis les poids officiels de Google par mradermacher ; licence Gemma)
_DEPOT = "https://huggingface.co/mradermacher/translategemma-%s-it-GGUF/resolve/main/translategemma-%s-it.Q4_K_M.gguf"
MODELES = {
    "4b": {"libelle": "Rapide (4B)", "nom": "translategemma-4b-it.Q4_K_M.gguf", "url": _DEPOT % ("4b", "4b"),
           "sha256": "81200d03e843d2ec1ece6eeafe7d13cb6e5211e1fcd336ade55790b683a08330", "taille": 2_489_909_760},
    "12b": {"libelle": "Meilleur (12B)", "nom": "translategemma-12b-it.Q4_K_M.gguf", "url": _DEPOT % ("12b", "12b"),
            "sha256": "b7aac4b4be7ab0c49b6556c29c4467e74313df7f1e95d9f9676bb2adf0afa528", "taille": 7_300_794_112},
}
CHOIX_PERSO = "perso"              # fichier .gguf choisi par l'utilisateur
# le 4B reste le modèle « par défaut » pour le code qui n'en précise pas
MODELE_URL, MODELE_NOM = MODELES["4b"]["url"], MODELES["4b"]["nom"]
MODELE_SHA256, MODELE_TAILLE = MODELES["4b"]["sha256"], MODELES["4b"]["taille"]
PAGE_VERSIONS = "https://github.com/ggml-org/llama.cpp/releases"


class ErreurMoteur(Exception):
    """Échec d'un moteur (message lisible par l'utilisateur)."""


class Annule(Exception):
    pass


# ---------- langues ----------
_MOTS = {
    "fr": "le la les des du de un une et est que qui dans pour pas sur avec au aux ce cette sont il elle nous vous je tu ne se en à "
          "ont été être mais ou où plus très comme par".split(),
    "en": "the and of to in is that it for with as on are this be was by not or from at an have you we they will can your".split(),
    "es": "el la los las de que y en un una es por con para no se su al lo como más pero está son fue muy".split(),
    "de": "der die das und ist nicht ein eine zu den mit von auf für im dem sich auch es an wir sie ich sind wird".split(),
    "it": "il lo la i gli le di che e un una è per con non si su da come più ma sono questo della del".split(),
    "pt": "o a os as de que e um uma é para com não se em por mais como mas da do são está muito".split(),
    "nl": "de het een en van is dat niet op te zijn voor met die aan ook als maar dit wordt".split(),
}


def detecter(texte: str) -> str | None:
    """Langue probable du texte (code) ou None si on ne peut pas trancher. Heuristique par mots courants et par écriture."""
    lettres = [c for c in texte if c.isalpha()]
    if len(lettres) < 12:
        return None
    n = len(lettres)

    def part(a, b):
        return sum(1 for c in lettres if a <= c <= b) / n
    if part("぀", "ヿ") > 0.1:
        return "ja"
    if part("一", "鿿") > 0.3:
        return "zh"
    if part("가", "힯") > 0.3:
        return "ko"
    if part("؀", "ۿ") > 0.3:
        return "ar"
    if part("Ѐ", "ӿ") > 0.3:
        return "uk" if re.search(r"[іїєґ]", texte.lower()) else "ru"
    mots = re.findall(r"[a-zà-ÿ]+", texte.lower().replace("'", " ").replace("’", " "))
    scores = sorted(((sum(1 for m in mots if m in set(liste)), code) for code, liste in _MOTS.items()), reverse=True)
    meilleur, code = scores[0]
    second = scores[1][0]
    return code if meilleur >= 3 and meilleur >= 1.4 * second else None


def cible_par_defaut(source: str | None, preferee: str = "en") -> str:
    """Langue cible proposée : l'inverse du couple fr/en, sinon la préférée (sans jamais égaler la source)."""
    if source == "fr":
        return "en"
    if source == "en":
        return "fr"
    return preferee if preferee != source else ("en" if source != "en" else "fr")


# ---------- consigne et découpage ----------
def consigne(texte: str, src: str, dst: str) -> str:
    """Consigne recommandée pour TranslateGemma, dans le gabarit de chat de Gemma, prête pour POST /completion."""
    ns, nd = LANGUES[src][0], LANGUES[dst][0]
    demande = (f"You are a professional {ns} ({src}) to {nd} ({dst}) translator. Your goal is to accurately convey the meaning and "
               f"nuances of the original {ns} text while adhering to {nd} grammar, vocabulary, and cultural sensitivities.\n"
               f"Produce only the {nd} translation, without any additional explanations or commentary. "
               f"Please translate the following {ns} text into {nd}:\n\n\n{texte}")
    return f"<start_of_turn>user\n{demande}<end_of_turn>\n<start_of_turn>model\n"


def decouper(texte: str, maxi: int = MORCEAU_MAX) -> list:
    """Morceaux d'au plus `maxi` caractères, coupés entre paragraphes (puis lignes, puis phrases). Aucun texte perdu."""
    texte = texte.strip()
    if not texte:
        return []

    def petits(bloc: str) -> list:
        if len(bloc) <= maxi:
            return [bloc]
        for sep in ("\n", None):
            morceaux = bloc.split("\n") if sep else re.split(r"(?<=[.!?…])\s+", bloc)
            if len(morceaux) > 1:
                res, cur = [], ""
                for m in morceaux:
                    ajout = f"{cur}\n{m}" if (cur and sep) else (f"{cur} {m}" if cur else m)
                    if len(ajout) <= maxi:
                        cur = ajout
                    else:
                        res += petits(cur) if cur else []
                        cur = m
                return res + (petits(cur) if cur else [])
        return [bloc[i:i + maxi] for i in range(0, len(bloc), maxi)]      # un seul « mot » géant : coupe brute

    morceaux, cur = [], ""
    for para in re.split(r"\n{2,}", texte):
        for p in petits(para):
            ajout = f"{cur}\n\n{p}" if cur else p
            if len(ajout) <= maxi:
                cur = ajout
            else:
                morceaux.append(cur)
                cur = p
    return morceaux + ([cur] if cur else [])


# ---------- recherche des fichiers ----------
def nom_programme() -> str:
    return "llama-server.exe" if os.name == "nt" else "llama-server"


def trouver_llama(chemin: str = "", dossier_donnees: Path | None = None) -> str | None:
    """llama-server : chemin des réglages, sinon PATH, sinon dossier de l'extension, sinon ~/.local/opt/llama.cpp."""
    if chemin and Path(chemin).is_file():
        return chemin
    p = shutil.which("llama-server")
    if p:
        return p
    racines = ([str(dossier_donnees / "llama.cpp")] if dossier_donnees else []) + [os.path.expanduser("~/.local/opt/llama.cpp")]
    for racine in racines:
        trouves = sorted(glob.glob(os.path.join(racine, "**", nom_programme()), recursive=True), reverse=True)
        if trouves:
            return trouves[0]
    return None


def dossiers_modeles(dossier_donnees: Path | None = None) -> list:
    return ([dossier_donnees / "modeles"] if dossier_donnees else []) + [Path(os.path.expanduser("~/.local/opt/llama.cpp/modeles"))]


def trouver_modele(chemin: str = "", dossier_donnees: Path | None = None, choix: str = "4b") -> str | None:
    """Fichier .gguf du modèle. Choix « perso » (ou chemin donné sans choix) : ce chemin. Sinon : le fichier du modèle choisi
    (« 4b », « 12b ») dans le dossier de l'extension ou dans ~/.local/opt/llama.cpp/modeles."""
    if choix == CHOIX_PERSO or choix not in MODELES:
        return chemin if chemin and Path(chemin).is_file() else None
    for d in dossiers_modeles(dossier_donnees):
        if (d / MODELES[choix]["nom"]).is_file():
            return str(d / MODELES[choix]["nom"])
    return None


def memoire_totale() -> int | None:
    """Mémoire vive de la machine en octets (None si on ne sait pas la lire)."""
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError, AttributeError):
        pass
    if os.name == "nt":
        try:
            import ctypes

            class Etat(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong), ("a", ctypes.c_ulonglong), ("b", ctypes.c_ulonglong),
                            ("c", ctypes.c_ulonglong), ("d", ctypes.c_ulonglong), ("e", ctypes.c_ulonglong)]
            e = Etat()
            e.dwLength = ctypes.sizeof(e)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(e))
            return int(e.ullTotalPhys)
        except Exception:
            return None
    return None


def gpus_nvidia() -> list:
    """Cartes NVIDIA vues par `nvidia-smi` : [{"nom", "total", "libre"}] en octets. Liste vide si absent ou en échec."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    try:
        r = subprocess.run([exe, "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"], capture_output=True,
                           text=True, timeout=8, **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
    except (OSError, subprocess.SubprocessError):
        return []
    cartes = []
    for ligne in r.stdout.splitlines():
        morceaux = [x.strip() for x in ligne.split(",")]
        if len(morceaux) == 3 and morceaux[1].isdigit() and morceaux[2].isdigit():
            cartes.append({"nom": morceaux[0], "total": int(morceaux[1]) * 1024 ** 2, "libre": int(morceaux[2]) * 1024 ** 2})
    return cartes


def apple_silicon() -> bool:
    import platform
    return sys.platform == "darwin" and platform.machine() == "arm64"


def materiel() -> dict:
    """Ce que la machine peut offrir : mémoire vive, cœurs, cartes NVIDIA, Apple Silicon (mémoire partagée avec la carte)."""
    return {"memoire": memoire_totale(), "coeurs": os.cpu_count(), "gpus": gpus_nvidia(), "apple": apple_silicon()}


GO12 = 12 * 1024 ** 3


def choix_automatique(m: dict) -> str | None:
    """« 12b » quand la machine le fait tourner vite sans hésitation (carte NVIDIA de 12 Go ou plus ; Mac Apple Silicon avec 16 Go
    ou plus), sinon None : il faut alors demander. Mesures (RTX 3070 8 Go) : 12B ≈ 7 mots-morceaux/s contre ≈ 106 pour le 4B."""
    if any(g["total"] >= GO12 for g in m.get("gpus", [])) or (m.get("apple") and (m.get("memoire") or 0) >= 16 * 1024 ** 3):
        return "12b"
    return None


def recommandation(m: dict) -> str:
    """Modèle conseillé : le 12B si le choix est évident, sinon le 4B (rapide ; le 12B reste possible, plus lent)."""
    return choix_automatique(m) or "4b"


def description_materiel(m: dict) -> str:
    gb = lambda o: f"{o / 1024 ** 3:.0f} Go"
    morceaux = [f"mémoire {gb(m['memoire'])}" if m.get("memoire") else "mémoire inconnue", f"{m.get('coeurs') or '?'} cœurs"]
    if m.get("gpus"):
        morceaux.append(" + ".join(f"{g['nom']} ({gb(g['total'])})" for g in m["gpus"]))
    elif m.get("apple"):
        morceaux.append("Apple Silicon (mémoire partagée)")
    else:
        morceaux.append("pas de carte NVIDIA détectée")
    return ", ".join(morceaux)


def est_local(url: str) -> bool:
    return (urlparse(url).hostname or "") in [h.strip("[]") for h in HOTES_LOCAUX]


# ---------- requêtes à un serveur llama.cpp ----------
def _requete(url: str, cle: str, chemin: str, corps: dict | None, delai: float):
    en_tetes = {"Content-Type": "application/json"}
    if cle:
        en_tetes["Authorization"] = f"Bearer {cle}"
    req = urllib.request.Request(url.rstrip("/") + chemin, json.dumps(corps).encode() if corps is not None else None, en_tetes)
    try:
        with urllib.request.urlopen(req, timeout=delai) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace") or "null")
    except urllib.error.HTTPError as ex:
        try:
            return ex.code, json.loads(ex.read().decode("utf-8", "replace") or "null")
        except ValueError:
            return ex.code, None


def sante(url: str, delai: float = 2) -> int:
    """Code HTTP de /health (200 = prêt, 503 = modèle en cours de chargement) ; 0 si injoignable."""
    try:
        return _requete(url, "", "/health", None, delai)[0]
    except (OSError, ValueError):
        return 0


def completer(url: str, cle: str, prompt: str, n_predict: int, delai: float = DELAI_REQUETE) -> str:
    """Texte généré par POST /completion (gabarit déjà dans `prompt`, température 0, arrêt sur <end_of_turn>)."""
    try:
        code, rep = _requete(url, cle, "/completion", {"prompt": prompt, "n_predict": n_predict, "temperature": 0,
                                                       "stop": ["<end_of_turn>"], "cache_prompt": True}, delai)
    except (OSError, ValueError) as ex:
        raise ErreurMoteur(f"serveur injoignable : {ex}") from ex
    if code == 401:
        raise ErreurMoteur("clé d'accès refusée par le serveur llama.cpp")
    if code != 200 or not isinstance(rep, dict) or "content" not in rep:
        detail = (rep or {}).get("error", {}) if isinstance(rep, dict) else {}
        raise ErreurMoteur(f"réponse inattendue du serveur (HTTP {code}) {detail.get('message', '') if isinstance(detail, dict) else detail}".strip())
    return str(rep["content"]).strip()


def n_predict_pour(texte: str) -> int:
    return min(2048, max(256, len(texte) // 2))


def _port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServeurLlama:
    """llama-server lancé à la demande sur 127.0.0.1 (port libre, clé d'accès aléatoire), arrêté à la fermeture ou après inactivité."""

    def __init__(self, journal: Path):
        self.journal = Path(journal)
        self.proc = None
        self.url = ""
        self.cle = ""
        self.config = None
        self.dernier_usage = time.time()
        self._verrou = threading.RLock()

    def vivant(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def demarrer(self, exe: str, modele: str, gpu: str = "", contexte: int = CONTEXTE, delai: float = DELAI_DEMARRAGE, annuler=None) -> None:
        """Lance le serveur (ou garde celui qui tourne déjà avec la même configuration) et attend qu'il soit prêt."""
        with self._verrou:
            self.dernier_usage = time.time()
            config = (exe, modele, str(gpu), contexte)
            if self.vivant() and self.config == config:
                return
            self.arreter()
            if not Path(exe).is_file():
                raise ErreurMoteur(f"llama-server introuvable : {exe}")
            if not Path(modele).is_file():
                raise ErreurMoteur(f"modèle introuvable : {modele}")
            port, self.cle = _port_libre(), secrets.token_hex(16)
            cmd = [exe, "-m", modele, "--host", "127.0.0.1", "--port", str(port), "--api-key", self.cle, "-c", str(contexte), "--no-webui"]
            if str(gpu).strip():
                cmd += ["-ngl", str(gpu).strip()]
            env = dict(os.environ)
            dossier = str(Path(exe).resolve().parent)
            env["LD_LIBRARY_PATH"] = dossier + (os.pathsep + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
            self.journal.parent.mkdir(parents=True, exist_ok=True)
            with open(self.journal, "wb") as j:
                self.proc = subprocess.Popen(cmd, stdout=j, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env, cwd=dossier,
                                             start_new_session=(os.name == "posix"))
            self.url, self.config = f"http://127.0.0.1:{port}", config
            fin = time.time() + delai
            while True:
                if self.proc.poll() is not None:
                    raise ErreurMoteur("llama-server s'est arrêté : " + self._derniere_erreur())
                if sante(self.url, 1) == 200:
                    return
                if annuler is not None and annuler():
                    self.arreter()
                    raise Annule()
                if time.time() > fin:
                    self.arreter()
                    raise ErreurMoteur("llama-server n'est pas prêt après %d s" % delai)
                time.sleep(0.25)

    def _derniere_erreur(self) -> str:
        try:
            lignes = self.journal.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return "(journal illisible)"
        erreurs = [x for x in lignes if re.search(r"error|failed|unknown|not found|cannot", x, re.I)]
        return (erreurs or lignes or ["(aucun message)"])[-1][:300]

    def arreter(self) -> None:
        with self._verrou:
            p, self.proc = self.proc, None
            if p is None or p.poll() is not None:
                return
            p.terminate()
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait(5)

    def inactif_depuis(self) -> float:
        return time.time() - self.dernier_usage

    def completer(self, prompt: str, n_predict: int) -> str:
        self.dernier_usage = time.time()
        return completer(self.url, self.cle, prompt, n_predict)


# ---------- traduction par morceaux ----------
def traduire_texte(texte: str, src: str, dst: str, fonction, progression=None, annuler=None) -> str:
    """Traduit `texte` morceau par morceau avec `fonction(morceau) -> str`. Progression (fait, total), annulation entre morceaux."""
    if len(texte) > TEXTE_MAX:
        raise ErreurMoteur("texte trop long : sélectionnez-en une partie")
    morceaux = decouper(texte)
    sortie = []
    for i, m in enumerate(morceaux):
        if annuler is not None and annuler():
            raise Annule()
        if progression:
            progression(i, len(morceaux))
        sortie.append(fonction(m))
    if progression:
        progression(len(morceaux), len(morceaux))
    return "\n\n".join(sortie)


# ---------- téléchargement du modèle ----------
def sha256_fichier(chemin: Path) -> str:
    h = hashlib.sha256()
    with open(chemin, "rb") as f:
        for bloc in iter(lambda: f.read(1 << 20), b""):
            h.update(bloc)
    return h.hexdigest()


def telecharger_modele(dossier: Path, url: str = MODELE_URL, nom: str = MODELE_NOM, sha256: str = MODELE_SHA256,
                       taille: int = MODELE_TAILLE, progression=None, annuler=None) -> Path:
    """Télécharge le modèle dans `dossier` (reprise possible), vérifie taille et SHA-256, puis le renomme. Retourne le chemin."""
    dossier.mkdir(parents=True, exist_ok=True)
    final, partiel = dossier / nom, dossier / (nom + ".part")
    if final.is_file() and final.stat().st_size == taille and sha256_fichier(final) == sha256:
        return final
    deja = partiel.stat().st_size if partiel.exists() else 0
    en_tetes = {"Range": f"bytes={deja}-"} if deja else {}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=en_tetes), timeout=60) as r:
            if deja and r.status != 206:                 # le serveur ne reprend pas : on recommence à zéro
                deja = 0
            with open(partiel, "ab" if deja else "wb") as f:
                while True:
                    bloc = r.read(1 << 20)
                    if not bloc:
                        break
                    if annuler is not None and annuler():
                        raise Annule()
                    f.write(bloc)
                    deja += len(bloc)
                    if progression:
                        progression(deja, taille)
    except urllib.error.URLError as ex:
        raise ErreurMoteur(f"téléchargement impossible : {ex}") from ex
    if partiel.stat().st_size != taille or sha256_fichier(partiel) != sha256:
        partiel.unlink(missing_ok=True)
        raise ErreurMoteur("fichier téléchargé incorrect (taille ou somme de contrôle) : supprimé")
    os.replace(partiel, final)
    return final


# ---------- aide à l'installation de llama.cpp ----------
def aide_installation() -> str:
    commun = (f"Les programmes officiels sont sur {PAGE_VERSIONS} : prenez une version « bNNNNN » (préversion) ; la page indique la "
              "somme de contrôle SHA-256 de chaque fichier, à vérifier. Décompressez où vous voulez, puis indiquez le chemin de "
              "llama-server dans les réglages (ou placez le dossier dans celui de l'extension).")
    if sys.platform.startswith("win"):
        return ("Windows : fichier « llama-bNNNNN-bin-win-cpu-x64.zip » (sans carte graphique), « …-win-vulkan-x64.zip » (carte "
                "graphique, tous constructeurs) ou « …-win-cuda-…-x64.zip » (NVIDIA).\n" + commun)
    if sys.platform == "darwin":
        return "macOS : fichier « llama-bNNNNN-bin-macos-arm64.tar.gz » (Apple Silicon) ou « …-macos-x64.tar.gz » (Intel).\n" + commun
    return ("Linux : fichier « llama-bNNNNN-bin-ubuntu-x64.tar.gz » (sans carte graphique), « …-ubuntu-vulkan-x64.tar.gz » (carte "
            "graphique, tous constructeurs ; testé avec une NVIDIA) ou « …-ubuntu-cuda-…-x64.tar.gz » (NVIDIA, plus gros).\n" + commun)

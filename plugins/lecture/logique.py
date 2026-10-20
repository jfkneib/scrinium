# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Partie sans interface de l'extension « Lecture à voix haute » : texte à lire, voix, moteurs (Piper, espeak-ng), lecture
en processus séparés (pause, arrêt), téléchargement vérifié des voix. Bibliothèque standard seule."""
import hashlib
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

from scrinium.i18n import N_, _, langue

PAQUET_PIPER = "piper-tts>=1.8,<2"            # pip --target dans le dossier de données ; fournit aussi les données espeak
URL_VOIX = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
TEXTE_MAX = 400_000                           # caractères lus d'une seule fiche
LIGNE_MAX = 400                               # une « phrase » plus longue est coupée (réactivité de la pause et de l'arrêt)
VITESSE_MIN, VITESSE_MAX = 0.6, 1.6

# Voix Piper « medium » (≈ 22 kHz). Tailles et SHA-256 relevés le 2026-10-20 sur huggingface.co/rhasspy/piper-voices.
VOIX = {
    "fr_FR-siwis-medium": {"langue": "fr", "libelle": N_("Français — Siwis"), "dossier": "fr/fr_FR/siwis/medium", "taille": 63_201_294,
                           "sha256": "641d1ab097da2b81128c076810edb052b385decc8be3381814802a64a73baf99",
                           "sha256_json": "39479916c2db192b5ac9764daddd0c744d83e023ad890c6976c0633ae4df8959", "taille_json": 4875},
    "fr_FR-upmc-medium": {"langue": "fr", "libelle": N_("Français — UPMC"), "dossier": "fr/fr_FR/upmc/medium", "taille": 76_733_615,
                          "sha256": "9abb3800c199148897a9ed64e100d224f3de83579f100044174ad19418f1786f",
                          "sha256_json": "e8636ec15dfd5d72db37a02cb5320a20f2b8d339f2a0e4337da64c58a33a5868", "taille_json": 4996},
    "en_US-lessac-medium": {"langue": "en", "libelle": N_("Anglais (États-Unis) — Lessac"), "dossier": "en/en_US/lessac/medium",
                            "taille": 63_201_294, "sha256": "5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f",
                            "sha256_json": "efe19c417bed055f2d69908248c6ba650fa135bc868b0e6abb3da181dab690a0", "taille_json": 4885},
    "en_GB-alba-medium": {"langue": "en", "libelle": N_("Anglais (Royaume-Uni) — Alba"), "dossier": "en/en_GB/alba/medium",
                          "taille": 63_201_294, "sha256": "401369c4a81d09fdd86c32c5c864440811dbdcc66466cde2d64f7133a66ad03b",
                          "sha256_json": "aa965a2f02ecced632c2694e1fc72bbff6d65f265fab567ca945918c73dd89f4", "taille_json": 4888},
}
VOIX_DEFAUT = {"fr": "fr_FR-siwis-medium", "en": "en_US-lessac-medium"}
LANGUES = {"fr": N_("français"), "en": N_("anglais")}
ESPEAK_VOIX = {"fr": "fr", "en": "en-gb"}
LECTEURS = (   # (exécutable, arguments avant le taux) -> PCM 16 bits mono brut sur l'entrée standard
    ("paplay", lambda r: ["--raw", f"--rate={r}", "--channels=1", "--format=s16le"]),
    ("pw-play", lambda r: ["--rate", str(r), "--channels", "1", "--format", "s16", "-"]),
    ("aplay", lambda r: ["-q", "-t", "raw", "-f", "S16_LE", "-r", str(r), "-c", "1"]),
)


class Annule(Exception):
    pass


# ---------- texte ----------
_META = re.compile(r"<!--.*?-->", re.S)
_CLOTURE = re.compile(r"^[ \t]*(```|~~~).*?^[ \t]*\1[ \t]*$", re.S | re.M)
_PREFIXE = re.compile(r"^[ \t]*(?:#{1,6}[ \t]+|[-*+][ \t]+|\d+[.)][ \t]+|>[ \t]?)", re.M)
_IMAGE = re.compile(r"!\[([^\]\n]*)\]\([^)\n]*\)")
_LIEN = re.compile(r"\[([^\]\n]*)\]\([^)\n]*\)")
_URL = re.compile(r"<?(?:https?://|www\.)[^\s<>]+>?|<mailto:[^>\s]+>")
_ACCENT = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*|(?<!\w)__(?=\S)(.+?)(?<=\S)__(?!\w)|(?<![*\w])\*(?![\s*])(.+?)(?<![\s*])\*(?![*\w])")
_CODE = re.compile(r"`([^`\n]+)`")
_FIN_PHRASE = re.compile(r"(?<=[.!?…])\s+(?=\S)")


def nettoyer(texte: str) -> str:
    """Texte lisible : sans commentaire de métadonnées, blocs de code, adresses ni syntaxe Markdown (le contenu reste)."""
    texte = _META.sub("", texte)
    texte = _CLOTURE.sub("", texte)                 # un bloc de code lu à voix haute n'a aucun intérêt
    texte = _IMAGE.sub(r"\1", texte)
    texte = _LIEN.sub(r"\1", texte)
    texte = _URL.sub("", texte)
    texte = _PREFIXE.sub("", texte)
    texte = _ACCENT.sub(lambda m: m[1] or m[2] or m[3], texte)
    texte = _CODE.sub(r"\1", texte)
    return texte.replace("\r\n", "\n")


def phrases(texte: str) -> list:
    """Lignes à lire : une par paragraphe ou phrase, aucune au-delà de LIGNE_MAX caractères ; sans ligne vide."""
    res = []
    for bloc in nettoyer(texte)[:TEXTE_MAX].split("\n"):
        bloc = " ".join(bloc.split())
        if not bloc:
            continue
        for phrase in _FIN_PHRASE.split(bloc):
            while len(phrase) > LIGNE_MAX:
                coupe = max(phrase.rfind(sep, 0, LIGNE_MAX) for sep in (", ", "; ", " "))
                coupe = coupe if coupe > 0 else LIGNE_MAX
                res.append(phrase[:coupe].strip(" ,;"))
                phrase = phrase[coupe:].strip(" ,;")
            if phrase:
                res.append(phrase)
    return [x for x in res if any(c.isalnum() for c in x)]


_MOTS = {
    "fr": {"le", "la", "les", "des", "du", "un", "une", "et", "est", "que", "qui", "dans", "pour", "pas", "sur", "avec", "ce", "se",
           "au", "aux", "il", "elle", "nous", "vous", "ils", "je", "ne", "ou", "mais", "par", "plus", "sont", "été", "être", "avoir"},
    "en": {"the", "of", "and", "to", "in", "is", "that", "it", "for", "was", "with", "as", "on", "are", "this", "be", "by", "at", "or",
           "from", "have", "not", "but", "they", "you", "we", "his", "her", "which", "will", "can", "there", "their"},
}


def detecter_langue(texte: str) -> str | None:
    """« fr » ou « en » d'après les mots courants, None si on ne peut pas trancher."""
    mots = re.findall(r"[a-zà-ÿ]+", nettoyer(texte).lower().replace("'", " ").replace("’", " "))
    fr, en = (sum(1 for m in mots if m in _MOTS[c]) for c in ("fr", "en"))
    if max(fr, en) < 3:
        return None
    return "fr" if fr >= 1.3 * en else "en" if en >= 1.3 * fr else None


def langue_de_lecture(texte: str, reglage: str = "auto") -> str:
    """Langue de la voix : celle imposée par le réglage, sinon détectée, sinon celle de l'interface (fr par défaut)."""
    if reglage in LANGUES:
        return reglage
    return detecter_langue(texte) or (langue() if langue() in LANGUES else "fr")


# ---------- voix et moteurs ----------
def fichiers_voix(modeles: Path, cle: str) -> tuple:
    return modeles / f"{cle}.onnx", modeles / f"{cle}.onnx.json"


def voix_presente(modeles: Path, cle: str) -> bool:
    onnx, cfg = fichiers_voix(modeles, cle)
    return cle in VOIX and onnx.is_file() and onnx.stat().st_size == VOIX[cle]["taille"] and cfg.is_file()


def piper_present(deps: Path) -> bool:
    return (deps / "piper" / "__main__.py").is_file()


def espeak() -> str | None:
    return shutil.which("espeak-ng") or shutil.which("espeak")


def lecteur_audio(taux: int) -> list | None:
    for exe, args in LECTEURS:
        chemin = shutil.which(exe)
        if chemin:
            return [chemin, *args(taux)]
    return None


def systeme_pris_en_charge() -> bool:
    return sys.platform.startswith("linux")


def aide_installation() -> str:
    return _("Aucun moteur de voix disponible. Installez espeak-ng (Debian/Ubuntu : sudo apt install espeak-ng), ou laissez "
             "l'extension installer Piper (voix plus naturelle) quand elle le propose.")


def vitesse_valide(v) -> float:
    try:
        return min(VITESSE_MAX, max(VITESSE_MIN, float(v)))
    except (TypeError, ValueError):
        return 1.0


def commande_piper(deps: Path, modeles: Path, cle: str, vitesse: float = 1.0) -> tuple:
    """(arguments, environnement) pour lire des lignes de texte (entrée standard) en PCM brut (sortie standard)."""
    onnx, _cfg = fichiers_voix(modeles, cle)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(deps) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env.pop("PYTHONHOME", None)
    argv = [sys.executable, "-m", "piper", "-m", str(onnx), "--output-raw", "--sentence-silence", "0.35",
            "--length-scale", f"{1.0 / vitesse_valide(vitesse):.3f}"]
    return argv, env


def commande_espeak(exe: str, lang: str, vitesse: float = 1.0) -> list:
    return [exe, "-v", ESPEAK_VOIX.get(lang, "fr"), "-s", str(int(165 * vitesse_valide(vitesse))), "--stdin"]


# ---------- lecture ----------
class Lecture:
    """Une lecture en cours : un ou deux processus (Piper puis lecteur audio, ou espeak-ng seul), pause et arrêt par signaux."""

    def __init__(self, procs: list, lignes: list):
        self.procs = procs
        self.erreurs: list = []
        self.en_pause = False
        for p in procs:
            if p.stderr is not None:
                threading.Thread(target=self._lire_erreurs, args=(p,), daemon=True).start()
        premier = procs[0]
        threading.Thread(target=self._ecrire, args=(premier, lignes), daemon=True).start()

    def _lire_erreurs(self, p):
        try:
            for ligne in p.stderr:
                self.erreurs = (self.erreurs + [ligne.decode("utf-8", "replace").rstrip()])[-8:]
        except (OSError, ValueError):
            pass

    @staticmethod
    def _ecrire(p, lignes):
        try:
            p.stdin.write(("\n".join(lignes) + "\n").encode("utf-8"))
            p.stdin.close()
        except (OSError, ValueError):
            pass                                 # le moteur s'est arrêté (arrêt demandé, ou erreur) : rien à écrire

    def _signal(self, sig):
        for p in self.procs:
            if p.poll() is None:
                try:
                    os.killpg(p.pid, sig) if os.name == "posix" else p.send_signal(sig)
                except (ProcessLookupError, PermissionError, OSError):
                    pass

    def pause(self):
        if os.name == "posix" and not self.en_pause:
            self._signal(signal.SIGSTOP)
            self.en_pause = True

    def reprendre(self):
        if self.en_pause:
            self._signal(signal.SIGCONT)
            self.en_pause = False

    def arreter(self):
        self.reprendre()
        self._signal(signal.SIGTERM)
        for p in self.procs:
            try:
                p.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._signal(signal.SIGKILL)
                p.wait(timeout=2)

    def terminee(self) -> bool:
        return self.procs[-1].poll() is not None

    def erreur(self) -> str:
        """Message d'erreur du moteur si la lecture s'est mal terminée, sinon chaîne vide."""
        if not self.terminee():
            return ""
        if any(p.returncode not in (0, None) and p.returncode > 0 for p in self.procs):
            return " ".join(self.erreurs[-3:]) or _("le moteur de voix s'est arrêté avec une erreur")
        return ""


def _lancer(argv, **kw) -> subprocess.Popen:
    options = {"start_new_session": True} if os.name == "posix" else {}
    return subprocess.Popen(argv, stderr=subprocess.PIPE, **options, **kw)


def demarrer_piper(deps: Path, modeles: Path, cle: str, lignes: list, vitesse: float = 1.0) -> Lecture:
    """Piper (processus Python avec le dossier `deps` en PYTHONPATH) -> PCM -> lecteur audio du système."""
    lecteur = lecteur_audio(22050)
    if lecteur is None:
        raise OSError(_("aucun lecteur audio trouvé (paplay, pw-play ou aplay)"))
    argv, env = commande_piper(deps, modeles, cle, vitesse)
    p1 = _lancer(argv, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        p2 = _lancer(lecteur, stdin=p1.stdout, stdout=subprocess.DEVNULL)
    except OSError:
        p1.kill()
        raise
    p1.stdout.close()
    return Lecture([p1, p2], lignes)


def demarrer_espeak(exe: str, lang: str, lignes: list, vitesse: float = 1.0) -> Lecture:
    p = _lancer(commande_espeak(exe, lang, vitesse), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL)
    return Lecture([p], lignes)


# ---------- téléchargement d'une voix ----------
def telecharger(url: str, dest: Path, sha256: str, taille: int, progression=None, annule=None) -> None:
    """Télécharge vers `dest` (via un fichier .part), vérifie la taille et le SHA-256 ; supprime tout fichier incorrect.
    Annule si `annule()` devient vrai ; OSError ou ValueError en cas d'échec."""
    if not url.startswith("https://"):
        raise ValueError(_("téléchargement refusé : adresse non sécurisée"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    h, fait = hashlib.sha256(), 0
    try:
        with urllib.request.urlopen(url, timeout=60) as r, open(part, "wb") as f:
            while True:
                if annule and annule():
                    raise Annule()
                bloc = r.read(1 << 20)
                if not bloc:
                    break
                f.write(bloc)
                h.update(bloc)
                fait += len(bloc)
                if progression:
                    progression(fait, taille)
        if fait != taille or h.hexdigest() != sha256:
            raise ValueError(_("fichier téléchargé incorrect (taille ou somme de contrôle) : supprimé"))
        os.replace(part, dest)
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def telecharger_voix(modeles: Path, cle: str, progression=None, annule=None) -> None:
    """Fichier modèle puis fichier de configuration d'une voix du catalogue (vérifiés)."""
    v = VOIX[cle]
    base = f"{URL_VOIX}{v['dossier']}/{cle}.onnx"
    onnx, cfg = fichiers_voix(modeles, cle)
    telecharger(base + ".json", cfg, v["sha256_json"], v["taille_json"], None, annule)
    telecharger(base, onnx, v["sha256"], v["taille"], progression, annule)

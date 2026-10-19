# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Chiffrement des fiches : AES-256-GCM, clé dérivée du mot de passe par scrypt.

Format `.lock` (inchangé depuis les premières versions, donc compatible) :
  AMLOCK2\\n | sel(16) | nonce(12) | taille clé enveloppée(2) | clé enveloppée | texte chiffré
La clé enveloppée est la clé AES de la fiche chiffrée (RSA-OAEP/SHA-256) avec la clé publique de secours.
"""
import json
import os
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC1 = b"AMLOCK1\n"   # ancien format (sans clé de secours)
MAGIC = b"AMLOCK2\n"
MAGIC3 = b"AMLOCK3\n"   # pièce jointe verrouillée (même enveloppe que AMLOCK2, voir docs/format-pieces-jointes.md)

__all__ = ["InvalidTag", "MAGIC", "MAGIC1", "MAGIC3", "chiffrer_piece", "dechiffrer_piece", "dechiffrer_piece_mdp",
           "ouvrir_piece_avec_cle_privee", "deriver", "envelopper", "chiffrer", "dechiffrer",
           "a_cle_de_secours", "ouvrir_avec_cle_privee"]


def _oaep():
    return padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)


def deriver(mdp: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(mdp.encode("utf-8"))


def envelopper(cle: bytes, recovery_pub: Path | None) -> bytes:
    """Clé de la fiche chiffrée avec la clé publique de secours ; b'' s'il n'y en a pas."""
    if recovery_pub is None or not recovery_pub.exists():
        return b""
    pub = serialization.load_pem_public_key(recovery_pub.read_bytes())
    return pub.encrypt(cle, _oaep())


def chiffrer(texte: str, cle: bytes, salt: bytes, wrap: bytes = b"") -> bytes:
    nonce = os.urandom(12)
    wl = len(wrap).to_bytes(2, "big")
    return MAGIC + salt + nonce + wl + wrap + AESGCM(cle).encrypt(nonce, texte.encode("utf-8"), MAGIC + salt + wl + wrap)


def dechiffrer(data: bytes, mdp: str):
    """(texte, clé, sel, clé enveloppée). InvalidTag si mot de passe faux, ValueError si fichier invalide."""
    if data.startswith(MAGIC1) and len(data) >= 36 + 16:
        salt, nonce, ct = data[8:24], data[24:36], data[36:]
        cle = deriver(mdp, salt)
        return AESGCM(cle).decrypt(nonce, ct, MAGIC1 + salt).decode("utf-8"), cle, salt, b""
    if not data.startswith(MAGIC) or len(data) < 38 + 16:
        raise ValueError("fichier verrouillé invalide")
    salt, nonce = data[8:24], data[24:36]
    n = int.from_bytes(data[36:38], "big")
    wrap, ct = data[38:38 + n], data[38 + n:]
    cle = deriver(mdp, salt)
    texte = AESGCM(cle).decrypt(nonce, ct, MAGIC + salt + data[36:38] + wrap)
    return texte.decode("utf-8"), cle, salt, wrap


def a_cle_de_secours(data: bytes) -> bool:
    return data.startswith(MAGIC) and int.from_bytes(data[36:38], "big") > 0


def ouvrir_avec_cle_privee(data: bytes, pem_prive: bytes, phrase: str | None = None) -> str:
    """Rouvre une fiche sans son mot de passe avec la clé privée de secours."""
    if not data.startswith(MAGIC):
        raise ValueError("fiche sans clé de secours (ancien format) : seul son mot de passe peut l'ouvrir")
    salt, nonce = data[8:24], data[24:36]
    n = int.from_bytes(data[36:38], "big")
    wrap, ct = data[38:38 + n], data[38 + n:]
    if not wrap:
        raise ValueError("fiche sans clé de secours : seul son mot de passe peut l'ouvrir")
    priv = serialization.load_pem_private_key(pem_prive, password=phrase.encode("utf-8") if phrase else None)
    cle = priv.decrypt(wrap, _oaep())
    return AESGCM(cle).decrypt(nonce, ct, MAGIC + salt + data[36:38] + wrap).decode("utf-8")


# ---------- pièces jointes verrouillées (AMLOCK3) ----------
# AMLOCK3\n | sel(16) | nonce(12) | taille clé enveloppée(2) | clé enveloppée | AES-GCM( taille en-tête(4) | en-tête JSON | données )
# sel, clé AES et clé enveloppée sont ceux de la fiche ; données authentifiées = MAGIC3 | sel | taille clé enveloppée | clé enveloppée.

def chiffrer_piece(entete: dict, donnees: bytes, cle: bytes, salt: bytes, wrap: bytes = b"") -> bytes:
    eb = json.dumps(entete, ensure_ascii=False, sort_keys=True).encode("utf-8")
    nonce = os.urandom(12)
    wl = len(wrap).to_bytes(2, "big")
    clair = len(eb).to_bytes(4, "big") + eb + donnees
    return MAGIC3 + salt + nonce + wl + wrap + AESGCM(cle).encrypt(nonce, clair, MAGIC3 + salt + wl + wrap)


def _decouper_piece(data: bytes):
    if not data.startswith(MAGIC3):
        if data.startswith(b"AMLOCK"):
            raise ValueError("format de pièce jointe plus récent ou inconnu : mettez Scrinium à jour")
        raise ValueError("pièce jointe verrouillée invalide")
    if len(data) < 38 + 16:
        raise ValueError("pièce jointe verrouillée invalide")
    n = int.from_bytes(data[36:38], "big")
    if len(data) < 38 + n + 16:
        raise ValueError("pièce jointe verrouillée invalide")
    return data[8:24], data[24:36], data[36:38], data[38:38 + n], data[38 + n:]


def _ouvrir_clair(clair: bytes):
    hl = int.from_bytes(clair[:4], "big")
    if len(clair) < 4 + hl:
        raise ValueError("pièce jointe verrouillée invalide")
    try:
        entete = json.loads(clair[4:4 + hl].decode("utf-8"))
    except ValueError as ex:
        raise ValueError("en-tête de pièce jointe invalide") from ex
    if not isinstance(entete, dict):
        raise ValueError("en-tête de pièce jointe invalide")
    return entete, clair[4 + hl:]


def dechiffrer_piece(data: bytes, cle: bytes):
    """(en-tête, données). InvalidTag si la clé est fausse ou si le fichier a été modifié."""
    salt, nonce, wl, wrap, ct = _decouper_piece(data)
    return _ouvrir_clair(AESGCM(cle).decrypt(nonce, ct, MAGIC3 + salt + wl + wrap))


def dechiffrer_piece_mdp(data: bytes, mdp: str):
    return dechiffrer_piece(data, deriver(mdp, _decouper_piece(data)[0]))


def ouvrir_piece_avec_cle_privee(data: bytes, pem_prive: bytes, phrase: str | None = None):
    """Rouvre une pièce jointe seule avec la clé privée de secours : (en-tête, données)."""
    salt, nonce, wl, wrap, ct = _decouper_piece(data)
    if not wrap:
        raise ValueError("pièce sans clé de secours : seul le mot de passe de la fiche peut l'ouvrir")
    priv = serialization.load_pem_private_key(pem_prive, password=phrase.encode("utf-8") if phrase else None)
    cle = priv.decrypt(wrap, _oaep())
    return _ouvrir_clair(AESGCM(cle).decrypt(nonce, ct, MAGIC3 + salt + wl + wrap))

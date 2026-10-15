# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Jean-François Kneib
"""Clé de secours : paire RSA propre à chaque utilisateur, créée à la demande (jamais par l'installation)."""
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def generer_paire(dest_prive: Path, dest_pub: Path, phrase: str | None = None, bits: int = 3072) -> None:
    """Crée la clé privée (PEM, chiffrée par `phrase` si fournie, droits 600) et la clé publique."""
    priv = rsa.generate_private_key(public_exponent=65537, key_size=bits)
    chiffrement = (serialization.BestAvailableEncryption(phrase.encode("utf-8")) if phrase
                   else serialization.NoEncryption())
    pem = priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, chiffrement)
    pub = priv.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    dest_prive.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(dest_prive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)   # refuse d'écraser une clé existante
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    dest_pub.parent.mkdir(parents=True, exist_ok=True)
    dest_pub.write_bytes(pub)


def cle_privee_chiffree(pem: bytes) -> bool:
    return b"ENCRYPTED" in pem.split(b"\n", 1)[0] or b"ENCRYPTED PRIVATE KEY" in pem

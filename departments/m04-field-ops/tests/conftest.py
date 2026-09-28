"""Aides partagées aux tests M4 (T1.4-e2) : base durable et dépôt d'un fichier de test réel.

`base_durable` : un test de ce dossier qui définit déjà sa PROPRE fixture du même nom (patron
établi avant T1.4-e2 dans plusieurs fichiers) continue de l'utiliser telle quelle — une fixture
locale masque celle-ci sans conflit, comportement standard de pytest. Elle n'existait pas encore
pour `test_outils_agent.py`, qui en a désormais besoin pour déposer un fichier réel avant de
compléter une intervention.
"""

from __future__ import annotations

import base64
import hashlib
import struct
import zlib

import pytest

from opsys import stockage
from opsys.outils import executer_atomique


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    """Base SQLite temporaire migrée, comme au démarrage de l'instance (ADR-0009)."""
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


def png_minimal() -> bytes:
    """PNG RVB 1x1 réel (T1.4-e2 : « petits fichiers de test réels », pas un simple préfixe
    magique) — signature + IHDR + IDAT (zlib d'une ligne filtrée « aucun ») + IEND, CRC32 correct
    sur chaque chunk."""
    def chunk(tag: bytes, donnees: bytes) -> bytes:
        return struct.pack(">I", len(donnees)) + tag + donnees + struct.pack(">I", zlib.crc32(tag + donnees))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\xff\xff", 9)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


@pytest.fixture
def deposer_photo_test():
    """Rend une fonction ``f(par_nom, contenu=None, type_mime="image/png") -> reference`` qui
    dépose, par le VRAI outil ``m4_deposer_fichier`` (``executer_atomique``, une transaction
    complète comme en production), un fichier de test réel et rend sa référence
    ``fichier:sha256:<hex>`` — utilisable dans ``preuves_completion.photos_apres``/``signature``."""
    def _deposer(par_nom, contenu: bytes | None = None, type_mime: str = "image/png") -> str:
        contenu_reel = contenu if contenu is not None else png_minimal()
        r = executer_atomique(par_nom["m4_deposer_fichier"], {
            "empreinte_sha256": hashlib.sha256(contenu_reel).hexdigest(),
            "taille_octets": len(contenu_reel), "type_mime": type_mime,
            "index_bloc": 0, "nombre_blocs": 1,
            "bloc_base64": base64.b64encode(contenu_reel).decode("ascii"),
        })
        assert r["ok"] and r["resultat"]["accepte"] and r["resultat"]["resultat"]["complet"], r
        return r["resultat"]["resultat"]["reference"]

    return _deposer

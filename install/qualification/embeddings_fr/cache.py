"""Cache disque des vecteurs et journal des appels de la passerelle (SQLite), HORS du dépôt.

Un vecteur est identifié par (modèle, préfixe de texte, type d'entrée, texte) : changer l'une de ces quatre choses est
une autre mesure. Le journal des appels conserve latence, nombre de textes et jetons de CHAQUE appel réel, ce qui permet
de reconstruire le rapport (y compris latence et coût) sans refaire d'appel. Le cache refuse de vivre dans le dépôt :
vecteurs et réponses de modèles n'y entrent jamais.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import struct
import time
from collections.abc import Sequence
from pathlib import Path

RACINE_DEPOT = Path(__file__).resolve().parents[3]


class ErreurCache(RuntimeError):
    pass


def cle_vecteur(modele: str, prefixe: str, input_type: str | None, texte: str) -> str:
    return hashlib.sha256("\x00".join((modele, prefixe, input_type or "", texte)).encode("utf-8")).hexdigest()


class Cache:
    def __init__(self, dossier: str | Path) -> None:
        dossier = Path(dossier).expanduser().resolve()
        if dossier == RACINE_DEPOT or RACINE_DEPOT in dossier.parents:
            raise ErreurCache("le cache de vecteurs doit rester HORS du dépôt")
        dossier.mkdir(parents=True, exist_ok=True)
        os.chmod(dossier, 0o700)
        self.dossier = dossier
        self._cnx = sqlite3.connect(dossier / "cache.sqlite")
        self._cnx.executescript(
            "CREATE TABLE IF NOT EXISTS vecteurs(cle TEXT PRIMARY KEY, modele TEXT NOT NULL,"
            " dimension INTEGER NOT NULL, blob BLOB NOT NULL);"
            "CREATE TABLE IF NOT EXISTS appels(id INTEGER PRIMARY KEY AUTOINCREMENT, horodatage REAL NOT NULL,"
            " modele TEXT NOT NULL, configuration TEXT NOT NULL, role TEXT NOT NULL, textes INTEGER NOT NULL,"
            " secondes REAL NOT NULL, jetons INTEGER, jetons_sortie INTEGER, cout_usd REAL);"
            "CREATE TABLE IF NOT EXISTS jugements(cle TEXT PRIMARY KEY, modele TEXT NOT NULL, reponse TEXT NOT NULL);")
        self._cnx.commit()

    def lire(self, cle: str) -> list[float] | None:
        ligne = self._cnx.execute("SELECT dimension, blob FROM vecteurs WHERE cle = ?", (cle,)).fetchone()
        if ligne is None:
            return None
        dimension, blob = ligne
        if len(blob) != 4 * dimension:
            raise ErreurCache("vecteur en cache corrompu")
        return list(struct.unpack(f"<{dimension}f", blob))

    def ecrire(self, cle: str, modele: str, vecteur: Sequence[float]) -> None:
        blob = struct.pack(f"<{len(vecteur)}f", *vecteur)
        self._cnx.execute("INSERT OR REPLACE INTO vecteurs(cle, modele, dimension, blob) VALUES (?, ?, ?, ?)",
                          (cle, modele, len(vecteur), blob))
        self._cnx.commit()

    def journaliser_appel(self, modele: str, configuration: str, role: str, textes: int, secondes: float,
                          jetons: int | None, jetons_sortie: int | None = None, cout_usd: float | None = None) -> None:
        self._cnx.execute(
            "INSERT INTO appels(horodatage, modele, configuration, role, textes, secondes, jetons, jetons_sortie,"
            " cout_usd) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (time.time(), modele, configuration, role, textes, secondes, jetons, jetons_sortie, cout_usd))
        self._cnx.commit()

    def appels(self, configuration: str, role: str | None = None) -> list[dict]:
        requete = ("SELECT modele, role, textes, secondes, jetons, jetons_sortie, cout_usd FROM appels"
                   " WHERE configuration = ?")
        parametres: list = [configuration]
        if role is not None:
            requete += " AND role = ?"
            parametres.append(role)
        colonnes = ("modele", "role", "textes", "secondes", "jetons", "jetons_sortie", "cout_usd")
        return [dict(zip(colonnes, ligne, strict=True)) for ligne in self._cnx.execute(requete + " ORDER BY id",
                                                                                         parametres)]

    def lire_jugement(self, cle: str) -> str | None:
        ligne = self._cnx.execute("SELECT reponse FROM jugements WHERE cle = ?", (cle,)).fetchone()
        return ligne[0] if ligne else None

    def ecrire_jugement(self, cle: str, modele: str, reponse: str) -> None:
        self._cnx.execute("INSERT OR REPLACE INTO jugements(cle, modele, reponse) VALUES (?, ?, ?)",
                          (cle, modele, reponse))
        self._cnx.commit()

    def fermer(self) -> None:
        self._cnx.close()

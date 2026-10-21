"""Préflight POSIX des volumes serveur : métadonnées seulement, aucune réparation."""

from __future__ import annotations

import os
import stat
import sys
from collections.abc import Sequence
from pathlib import Path

MAX_ENTREES = 10000
MAX_PROFONDEUR = 32
FRAGMENTS = (
    "models.json", "agents.json", "mcp.json", "tools.json", "memory.json", "plugins.json",
    "channels.json", "bindings.json", "session.json", "contexte.json", "roles.json",
    "profils-en-attente.json", "appareils.json", "automatisations.sh",
)
FICHIERS_DONNEES = (
    "opsys.db", "opsys.db-wal", "opsys.db-shm", "opsys.db-journal", "paliers.yaml", "entreprise.yaml",
)


class RefusPermissions(ValueError):
    """Une reprise humaine des volumes est nécessaire avant le démarrage."""


def _refuser(raison: str) -> None:
    raise RefusPermissions(f"REJ-PERMISSIONS-SERVEUR : {raison}; snapshot et reprise assistée requis")


def verifier(dossiers: Sequence[Path]) -> None:
    """Vérifie les racines et cibles Python déclarées, jamais tout le volume Core.

    La borne concerne cette seule collection et les arbres skills réécrits. Les annexes
    (Git, médias, mémoire, transcripts, état Core) ne sont ni parcourues ni refusées.
    Aucune lecture de contenu ou réparation ; les contrôles du noyau restent définitifs.
    """
    uid = os.geteuid()
    if uid == 0:
        _refuser("service non-root requis")
    compteur = 0

    def metadata(chemin: Path, *, dossier: bool | None = None, obligatoire: bool = False) -> bool:
        nonlocal compteur
        try:
            infos = os.lstat(chemin)
        except FileNotFoundError:
            if obligatoire:
                _refuser("volume absent")
            return False  # cible nouvelle ou temporaire disparu ; aucune réparation
        except OSError:
            _refuser("cible ou métadonnées inaccessibles")
        compteur += 1
        if compteur > MAX_ENTREES:
            _refuser("plafond de vérification des cibles atteint")
        if stat.S_ISLNK(infos.st_mode):
            _refuser("lien sur une cible serveur")
        if infos.st_uid != uid:
            _refuser("propriétaire d'une cible différent du service")
        est_dossier = stat.S_ISDIR(infos.st_mode)
        if dossier is not None and est_dossier != dossier:
            _refuser("type de cible incompatible")
        if not est_dossier and not stat.S_ISREG(infos.st_mode):
            _refuser("type de fichier cible incompatible")
        droits = os.R_OK | os.W_OK | (os.X_OK if est_dossier else 0)
        if not os.access(chemin, droits, effective_ids=True):
            _refuser("droits de lecture/écriture/traversée inaccessibles")
        return True

    def skills(racine: Path) -> None:
        pending = [(racine, 0)]
        while pending:
            chemin, profondeur = pending.pop()
            if profondeur > MAX_PROFONDEUR:
                _refuser("plafond de profondeur des cibles atteint")
            if not metadata(chemin, dossier=True if profondeur == 0 else None):
                continue
            if chemin.is_dir():
                for enfant in enfants(chemin):
                    if compteur + len(pending) >= MAX_ENTREES:
                        _refuser("plafond de vérification des cibles atteint")
                    pending.append((enfant, profondeur + 1))

    def enfants(dossier: Path):
        try:
            with os.scandir(dossier) as entries:
                for enfant in entries:
                    yield Path(enfant.path)
        except OSError:
            _refuser("collection de cibles inaccessible")

    def espace(racine: Path) -> None:
        # Sélection par les seuls noms produits par generer(), sans entrer dans les annexes.
        # Un emplacement sans ces cibles existantes reste soumis au noyau lors de sa création.
        if not any(os.path.lexists(racine / nom) for nom in ("SOUL.md", "AGENTS.md", "skills")):
            return
        if not metadata(racine, dossier=True):
            return
        for nom in ("SOUL.md", "AGENTS.md"):
            metadata(racine / nom, dossier=False)
        skills(racine / "skills")

    for racine in dossiers:
        metadata(racine, dossier=True, obligatoire=True)
    if dossiers:
        config = dossiers[0]
        for nom in ("openclaw.json", "opsys.json"):
            metadata(config / nom, dossier=False)
        base = config / "opsys"
        if metadata(base, dossier=True):
            for nom in FRAGMENTS:
                metadata(base / nom, dossier=False)
            espaces = base / "espaces"
            if metadata(espaces, dossier=True):
                for racine in enfants(espaces):
                    if racine.name == "agents":
                        if metadata(racine, dossier=True):
                            for profil in enfants(racine):
                                espace(profil)
                    else:
                        espace(racine)
    if len(dossiers) > 1:
        for nom in FICHIERS_DONNEES:
            metadata(dossiers[1] / nom, dossier=False)
    if len(dossiers) > 2:
        metadata(dossiers[2] / "config.yaml", dossier=False)


def main() -> int:
    dossiers = [
        Path(os.environ.get("OPENCLAW_CONFIG_DIR", "/openclaw-config")),
        Path(os.environ.get("OPSYS_HOME", "/opt/data")),
    ]
    try:
        mode = os.environ.get("OPSYS_MODE_FOURNISSEUR", "natif")
        if mode == "litellm":
            dossiers.append(Path(os.environ.get("LITELLM_CONFIG_DIR", "/shared/litellm-config")))
        elif mode != "natif":
            _refuser("mode fournisseur inconnu")
        verifier(dossiers)
    except RefusPermissions as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

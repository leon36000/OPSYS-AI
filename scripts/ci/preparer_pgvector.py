"""Préparer l'image CI officielle par cache documenté, sans modifier la fixture PostgreSQL.

Le cache Google peut manquer : le pull canonique reste alors soumis au quota Hub et échoue.
Aucun retry, login ou changement de version n'est effectué. Les commandes n'affichent jamais
la configuration du démon ni les détails bruts d'une erreur. Les versions sont relues dans
l'image sur le runner ; les scénarios PostgreSQL/pgvector existants restent nécessaires.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

MIROIR = "https://mirror.gcr.io"
DIGEST = "sha256:ac08538c6f8b9904c33c8224c5e5706dbe760aca29db1d096972b4052c22a75d"
REFERENCE = "pgvector/pgvector@" + DIGEST
TAG_LOCAL = "pgvector/pgvector:pg17"
MAX_CONFIGURATION = 65536
MAX_SORTIE = 8192

# Écriture atomique privilégiée ; stdin capturé, jamais un tee qui expose la configuration.
ECRITURE = """
import os, pathlib, stat, sys, tempfile
destination = pathlib.Path(sys.argv[1])
donnees = sys.stdin.buffer.read(65537)
if len(donnees) > 65536:
    raise SystemExit(1)
destination.parent.mkdir(parents=True, exist_ok=True)
mode = stat.S_IMODE(destination.stat().st_mode) if destination.exists() else 0o600
fd, temporaire = tempfile.mkstemp(prefix='.opsys-ci-', dir=destination.parent)
try:
    with os.fdopen(fd, 'wb') as flux:
        flux.write(donnees)
        flux.flush()
        os.fsync(flux.fileno())
        os.fchmod(flux.fileno(), mode)
    os.replace(temporaire, destination)
finally:
    if os.path.exists(temporaire):
        os.unlink(temporaire)
"""


class PreparationRefusee(Exception):
    """Erreur fermée de préparation : aucune donnée de configuration ou stderr Docker."""


def _objet_unique(paires):
    objet = {}
    for cle, valeur in paires:
        if cle in objet:
            raise ValueError("clé dupliquée")
        objet[cle] = valeur
    return objet


def _non_fini(_valeur):
    raise ValueError("nombre non fini")


def lire_configuration(chemin: Path) -> dict:
    try:
        if chemin.exists():
            with chemin.open("rb") as flux:
                brut = flux.read(MAX_CONFIGURATION + 1)
            if len(brut) > MAX_CONFIGURATION:
                raise ValueError("borne dépassée")
            configuration = json.loads(brut, object_pairs_hook=_objet_unique, parse_constant=_non_fini)
        else:
            configuration = {}
        if not isinstance(configuration, dict):
            raise ValueError("objet attendu")
        miroirs = configuration.get("registry-mirrors", [])
        if not isinstance(miroirs, list) or any(not isinstance(m, str) or not m for m in miroirs):
            raise ValueError("liste de miroirs invalide")
        configuration["registry-mirrors"] = [MIROIR, *(m for m in miroirs if m != MIROIR)]
        return configuration
    except (OSError, ValueError, RecursionError):
        raise PreparationRefusee("configuration Docker invalide ou illisible") from None


def _commande(executer, nom: str, arguments: list[str], *, delai: int, entree=None) -> bytes:
    try:
        options = {"check": True, "capture_output": True, "timeout": delai}
        if entree is not None:
            options["input"] = entree
        resultat = executer(arguments, **options)
        sortie = resultat.stdout
        if not isinstance(sortie, bytes) or len(sortie) > MAX_SORTIE:
            raise ValueError("sortie invalide")
        return sortie
    except (OSError, ValueError, subprocess.SubprocessError):
        raise PreparationRefusee(f"préparation PostgreSQL échouée : {nom}") from None


def configurer_miroir(chemin: Path = Path("/etc/docker/daemon.json"), *, executer=subprocess.run) -> None:
    configuration = lire_configuration(chemin)
    try:
        entree = (json.dumps(configuration, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
        if len(entree) > MAX_CONFIGURATION:
            raise ValueError("borne dépassée")
    except (ValueError, RecursionError, UnicodeError):
        raise PreparationRefusee("configuration Docker trop volumineuse ou invalide") from None

    _commande(executer, "configuration", ["sudo", sys.executable, "-c", ECRITURE, str(chemin)],
              delai=30, entree=entree)
    _commande(executer, "redémarrage", ["sudo", "systemctl", "restart", "docker"], delai=60)


def preparer(chemin: Path = Path("/etc/docker/daemon.json"), *, executer=subprocess.run) -> dict:
    configurer_miroir(chemin, executer=executer)
    _commande(executer, "pull", ["docker", "pull", REFERENCE], delai=900)
    _commande(executer, "tag", ["docker", "tag", REFERENCE, TAG_LOCAL], delai=30)
    sortie = _commande(
        executer, "identité",
        ["docker", "image", "inspect", "--format", '{"id":{{json .Id}},"digests":{{json .RepoDigests}}}',
         REFERENCE, TAG_LOCAL], delai=30,
    )
    try:
        images = [json.loads(ligne) for ligne in sortie.splitlines()]
        if len(images) != 2:
            raise ValueError("deux images attendues")
        for image in images:
            if not isinstance(image, dict) or set(image) != {"id", "digests"}:
                raise ValueError("projection invalide")
            if not isinstance(image["id"], str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image["id"]):
                raise ValueError("identifiant invalide")
            if not isinstance(image["digests"], list) or REFERENCE not in image["digests"]:
                raise ValueError("digest inattendu")
        if images[0]["id"] != images[1]["id"]:
            raise ValueError("tag divergent")
    except (ValueError, TypeError, RecursionError):
        raise PreparationRefusee("identité de l'image PostgreSQL invalide") from None

    versions = _commande(
        executer, "versions",
        ["docker", "run", "--rm", "--pull=never", "--network=none", "--read-only", "--entrypoint", "sh",
         REFERENCE, "-ec",
         'postgres --version; grep "^default_version = " "$(pg_config --sharedir)/extension/vector.control"'],
        delai=60,
    )
    try:
        lignes = versions.decode("utf-8").splitlines()
        if len(lignes) != 2 or not re.fullmatch(r"postgres \(PostgreSQL\) 17\.[0-9]+(?:\s.*)?", lignes[0]):
            raise ValueError("PostgreSQL 17 attendu")
        if lignes[1] != "default_version = '0.8.7'":
            raise ValueError("pgvector 0.8.7 attendu")
    except (ValueError, UnicodeError):
        raise PreparationRefusee("versions PostgreSQL/pgvector inattendues") from None
    return {"image": TAG_LOCAL, "digest": DIGEST, "postgres_major": 17,
            "pgvector_version_installee": "0.8.7"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--miroir-seulement", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.miroir_seulement:
            configurer_miroir()
            resultat = {"miroir_configure": MIROIR}
        else:
            resultat = preparer()
    except PreparationRefusee as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(resultat, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

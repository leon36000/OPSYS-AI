"""Paquet versionné d'un site généré : archive `tar.gz` reproductible et manifeste d'empreintes (décision r6, ex. 4).

Même fichiers et même version -> mêmes octets d'archive : entrées triées, horodatage des entrées tiré de la VERSION
(jamais de l'horloge), propriétaire 0/0 sans nom, mode 0644, en-tête gzip sans nom ni date. L'empreinte SHA-256 de
l'archive est donc une identité stable du contenu exact à publier : c'est elle que la demande de publication porte
et que la direction approuve (`service.demander_publication`).

L'archive contient les fichiers du site et `SHA256SUMS` (format `sha256sum -c`) pour la vérification sur le serveur.
Le manifeste (`MANIFESTE.json`, hors archive) liste chaque fichier, sa taille et son empreinte.

Module pur : aucune entrée-sortie (le service écrit les octets rendus ici).
"""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import io
import json
import re
import tarfile
from collections.abc import Mapping
from typing import Any

SCHEMA_PAQUET = "opsys.site-paquet/v1"
FICHIER_SOMMES = "SHA256SUMS"
VERSION = re.compile(r"^\d{8}T\d{6}Z$")
REJ_VERSION = "REJ-SITE-PAQUET-VERSION"


def version_valide(version: Any) -> bool:
    """`AAAAMMJJTHHMMSSZ` (UTC), une date réelle : le nom du répertoire `releases/<version>` sur le serveur."""
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        return False
    try:
        dt.datetime.strptime(version, "%Y%m%dT%H%M%SZ")
    except ValueError:
        return False
    return True


def _epoch(version: str) -> int:
    return int(dt.datetime.strptime(version, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.UTC).timestamp())


def _sha256(octets: bytes) -> str:
    return hashlib.sha256(octets).hexdigest()


def empreinte_schema(schema: Mapping[str, Any]) -> str:
    """Empreinte du schéma de contenu sous forme canonique (clés triées, séparateurs fixes)."""
    canonique = json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha256(canonique.encode("utf-8"))


def sommes(fichiers: Mapping[str, bytes]) -> str:
    """Le fichier `SHA256SUMS` : une ligne `<empreinte>  <chemin>` par fichier, triées par chemin."""
    return "".join(f"{_sha256(fichiers[chemin])}  {chemin}\n" for chemin in sorted(fichiers))


def construire_archive(fichiers: Mapping[str, bytes], version: str) -> bytes:
    """L'archive `tar.gz` reproductible des `fichiers` et de leur `SHA256SUMS`."""
    if not version_valide(version):
        raise ValueError(f"{REJ_VERSION}: version {version!r} invalide (AAAAMMJJTHHMMSSZ)")
    contenu = {**fichiers, FICHIER_SOMMES: sommes(fichiers).encode("utf-8")}
    tampon_tar = io.BytesIO()
    with tarfile.open(fileobj=tampon_tar, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for chemin in sorted(contenu):
            info = tarfile.TarInfo(chemin)
            info.size = len(contenu[chemin])
            info.mtime = _epoch(version)
            info.mode = 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            archive.addfile(info, io.BytesIO(contenu[chemin]))
    tampon_gz = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=tampon_gz, mtime=0, compresslevel=9) as flux:
        flux.write(tampon_tar.getvalue())
    return tampon_gz.getvalue()


def nom_archive(site_id: str, version: str) -> str:
    return f"{site_id}-{version}.tar.gz"


def construire_paquet(
    fichiers: Mapping[str, bytes], schema: Mapping[str, Any], version: str, rapport_qa: Mapping[str, Any]
) -> tuple[bytes, dict[str, Any]]:
    """(archive, manifeste). Le manifeste lie l'archive à son schéma (empreinte), à sa version et au résultat du
    contrôle qualité qui l'a acceptée."""
    archive = construire_archive(fichiers, version)
    manifeste = {
        "schema_paquet": SCHEMA_PAQUET,
        "site_id": schema["site_id"],
        "domaine": schema["domaine"],
        "fictif": schema["fictif"],
        "version": version,
        "schema_site": schema["schema"],
        "empreinte_schema": empreinte_schema(schema),
        "archive": {"nom": nom_archive(schema["site_id"], version), "octets": len(archive), "sha256": _sha256(archive)},
        "fichiers": [
            {"chemin": chemin, "octets": len(fichiers[chemin]), "sha256": _sha256(fichiers[chemin])}
            for chemin in sorted(fichiers)
        ],
        "octets_total": sum(len(v) for v in fichiers.values()),
        "qa": {
            "conforme": bool(rapport_qa.get("conforme")),
            "controles": len(rapport_qa.get("controles", [])),
            "echecs": [c["code"] for c in rapport_qa.get("controles", []) if not c["ok"]],
        },
    }
    return archive, manifeste


def manifeste_json(manifeste: Mapping[str, Any]) -> bytes:
    return (json.dumps(manifeste, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")

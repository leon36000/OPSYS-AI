#!/usr/bin/env python3
"""Relève les licences des paquets INSTALLÉS sur une machine et met à jour `docs/compliance/donnees/constats-licences.json`.

Hors ligne et en lecture seule sur les sources : on lit les `METADATA` des `*.dist-info` (Python) et les `package.json`
d'un magasin pnpm déjà installé (`node_modules/.pnpm`). Le script ne sait PAS interroger un registre : un paquet dont
aucune métadonnée locale n'existe reste `non_verifiee` (jamais complété de mémoire).

Usage (exemple) :
  python scripts/compliance/collecter_constats.py --date 2026-11-01 \\
      --pypi /chemin/site-packages --pypi /chemin/cache-uv/archive \\
      --pnpm /chemin/core/node_modules/.pnpm
Les sections `declarations_documentation` et `sources` écrites à la main sont conservées.
"""

# ruff: noqa: E501  (assertions et chaînes de documentation longues, lisibles telles quelles)

from __future__ import annotations

import argparse
import email
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _licences as L  # noqa: E402


def _dist_infos(racine: Path):
    for dossier, sous, _ in os.walk(racine):
        profondeur = len(Path(dossier).relative_to(racine).parts)
        if profondeur > 3:
            sous[:] = []
            continue
        for d in list(sous):
            if d.endswith(".dist-info"):
                yield Path(dossier) / d
        sous[:] = [d for d in sous if not d.endswith(".dist-info") and d != "node_modules"]


def releve_pypi(racines: list[Path], attendus: set[tuple[str, str]]) -> dict[str, dict]:
    sortie: dict[str, dict] = {}
    for racine in racines:
        for info in _dist_infos(racine):
            m = re.match(r"^(.*?)-(\d[^-]*)\.dist-info$", info.name)
            metadata = info / "METADATA"
            if not m or not metadata.is_file():
                continue
            cle = (L.normaliser_nom_pypi(m.group(1)), m.group(2))
            if cle not in attendus or f"{cle[0]}=={cle[1]}" in sortie:
                continue
            msg = email.message_from_string(metadata.read_text(encoding="utf-8", errors="replace"))
            classifieurs = [c.split("::", 1)[1].strip() for c in msg.get_all("Classifier", []) if c.startswith("License ::")]
            classifieurs = [c.split("::")[-1].strip() for c in classifieurs]
            spdx, brut = L.spdx_depuis_metadonnees_pypi(msg.get("License-Expression"), msg.get("License"), classifieurs)
            sortie[f"{cle[0]}=={cle[1]}"] = {
                "spdx": spdx, "brut": brut, "niveau": "metadonnees_locales" if spdx else "non_verifiee",
                "source": "S-PYPI", **({} if spdx else {"raison": "métadonnées sans identifiant précis (variante non dite)"}),
            }
    return sortie


def releve_pnpm(magasin: Path, attendus: set[tuple[str, str]]) -> dict[str, dict]:
    sortie: dict[str, dict] = {}
    index = {}
    for entree in os.listdir(magasin):
        if entree.startswith(".") or entree == "node_modules":
            continue
        index.setdefault(re.sub(r"_.*$", "", entree), []).append(entree)
    for nom, version in sorted(attendus):
        dossier = index.get(nom.replace("/", "+") + "@" + version)
        if not dossier:
            continue
        pj = magasin / dossier[0] / "node_modules" / nom / "package.json"
        if not pj.is_file():
            continue
        try:
            donnees = json.loads(pj.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if donnees.get("name") != nom or donnees.get("version") != version:
            continue
        spdx, brut = L.spdx_depuis_package_json(donnees.get("license"), donnees.get("licenses"))
        sortie[f"{nom}@{version}"] = {
            "spdx": spdx, "brut": brut, "niveau": "metadonnees_locales" if spdx else "non_verifiee",
            "source": "S-PNPM", **({} if spdx else {"raison": "champ license absent ou non SPDX"}),
        }
    return sortie


def main(argv: list[str] | None = None) -> int:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("--date", required=True, help="date du relevé (AAAA-MM-JJ), consignée telle quelle")
    a.add_argument("--pypi", action="append", default=[], type=Path)
    a.add_argument("--pnpm", type=Path)
    a.add_argument("--sortie", type=Path, default=L.FICHIER_CONSTATS)
    args = a.parse_args(argv)

    existant = json.loads(args.sortie.read_text(encoding="utf-8")) if args.sortie.exists() else {}
    racine = L.RACINE
    py = set(L.lire_uv_lock(racine / "uv.lock"))
    for f in ("requirements-runtime.lock.txt", "requirements-embeddings-local.lock.txt",
              "requirements-ingestion-pdf.lock.txt"):
        py |= set(L.lire_exigences(racine / f))
    resultat = dict(existant)
    resultat["schema"] = "opsys.conformite.constats/v1"
    resultat["date_releve"] = args.date
    if args.pypi:
        resultat["pypi"] = dict(sorted(releve_pypi(args.pypi, py).items()))
    if args.pnpm:
        prod, tous = L.lire_pnpm_lock(racine / "core" / "pnpm-lock.yaml")
        resultat["npm-core"] = dict(sorted(releve_pnpm(args.pnpm, tous).items()))
    args.sortie.write_text(json.dumps(resultat, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"pypi : {len(resultat.get('pypi', {}))} relevés ; npm-core : {len(resultat.get('npm-core', {}))} relevés")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

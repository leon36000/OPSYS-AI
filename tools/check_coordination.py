#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path, PurePosixPath

ACTIVE = {"ACTIVE", "REVIEW", "READY_TO_MERGE"}
OWNERS = {"CODEX", "CLAUDE", "CHATGPT", "NATHAN", "UNASSIGNED"}
STATUSES = {"QUEUED", "ACTIVE", "BLOCKED", "REVIEW", "READY_TO_MERGE", "MERGED", "TRANSFER"}
CORE_RE = re.compile(r"^C(?:0\d|1\d|2[0-4])-\d{3}$")
CLAUDE_RE = re.compile(r"^(?:ISS-|AUD-|BUG-|R4-)")
HEADER = ["Work ID", "Owner", "Branch", "Path scope", "Status", "Updated UTC", "Next"]
# SonarCloud python:S1192 : "task spec exact" apparaissait 3 fois en litteral.
SCOPES_HORS_COLLISION = {"read-only", "task spec exact"}


def parse_rows(path: Path) -> tuple[list[dict[str, str]], list[str], bool]:
    out: list[dict[str, str]] = []
    errors: list[str] = []
    header_found = False
    lines = path.read_text(encoding="utf-8").splitlines()
    for lineno, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells == HEADER:
            # Fixture : fichier sans aucune table -> pack COORDINATION_OK rows=0 exit 0
            # (a tort). Exiger que la ligne suivante soit une vraie separation evite
            # aussi qu'une simple citation de l'en-tete en prose ne compte comme table.
            next_line = lines[lineno].strip() if lineno < len(lines) else ""
            if next_line.startswith("|---"):
                header_found = True
            continue
        if len(cells) != 7:
            errors.append(f"MALFORMED_ROW:{lineno}:{len(cells)}")
            continue
        out.append(dict(zip(["work_id", "owner", "branch", "scope", "status", "updated", "next"], cells)))
    return out, errors, header_found


def valid_scope(scope: str) -> bool:
    if scope in SCOPES_HORS_COLLISION:
        return True
    if not scope.strip():
        return False
    for item in [x.strip() for x in scope.split(";") if x.strip()]:
        p = PurePosixPath(item)
        if p.is_absolute() or ".." in p.parts or item.startswith("~"):
            return False
    return True


def overlaps(a: str, b: str) -> bool:
    if a in SCOPES_HORS_COLLISION or b in SCOPES_HORS_COLLISION:
        return False
    # casse + separateur normalises ici, coherent avec MODULE_CODE_DURING_CORE plus bas.
    # Fixture : scopes "Coordination"/"coordination" (ou "a\b"/"a/b"), branches distinctes
    # -> pack COORDINATION_OK exit 0 (collision reelle manquee).
    pa = PurePosixPath(a.replace("\\", "/").rstrip("/").casefold())
    pb = PurePosixPath(b.replace("\\", "/").rstrip("/").casefold())
    return pa == pb or pa in pb.parents or pb in pa.parents


def validate(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    data, errors, header_found = parse_rows(path)
    if not header_found:
        # Plancher de non-vacuite : un chemin errone ou un fichier tronque/vide n'a
        # aucune ligne d'en-tete et ne doit pas rendre le meme succes qu'une vraie
        # table vide (en-tete + separateur, zero ligne, gabarit legitime).
        errors.append("HEADER_MISSING")
    seen: set[str] = set()
    for row in data:
        wid = row["work_id"]
        owner = row["owner"]
        status = row["status"]
        branch = row["branch"]
        if not wid:
            errors.append("WORK_ID_EMPTY")
        if wid in seen:
            errors.append(f"DUPLICATE_WORK:{wid}")
        seen.add(wid)
        if owner not in OWNERS:
            errors.append(f"OWNER:{wid}:{owner}")
        if status not in STATUSES:
            errors.append(f"STATUS:{wid}:{status}")
        if not valid_scope(row["scope"]):
            errors.append(f"SCOPE:{wid}:{row['scope']}")
        if status in ACTIVE and branch.lower() in {"main", "master", ""}:
            errors.append(f"BRANCH:{wid}")
        normalized_scope = row["scope"].replace("\\", "/").casefold()
        if status in ACTIVE and (normalized_scope == "modules m" or normalized_scope.startswith("modules m/")):
            errors.append(f"MODULE_CODE_DURING_CORE:{wid}")
        if CORE_RE.match(wid) and owner not in {"CODEX", "UNASSIGNED"} and status != "TRANSFER":
            errors.append(f"CORE_OWNER:{wid}:{owner}")
        if CLAUDE_RE.match(wid) and owner not in {"CLAUDE", "UNASSIGNED"} and status != "TRANSFER":
            errors.append(f"ISSUE_OWNER:{wid}:{owner}")

    active = [r for r in data if r["status"] in ACTIVE]
    for idx, left in enumerate(active):
        for right in active[idx + 1 :]:
            if left["branch"] == right["branch"]:
                errors.append(f"BRANCH_COLLISION:{left['work_id']}:{right['work_id']}")
            for sa in [x.strip() for x in left["scope"].split(";") if x.strip()]:
                for sb in [x.strip() for x in right["scope"].split(";") if x.strip()]:
                    if overlaps(sa, sb):
                        errors.append(f"PATH_COLLISION:{left['work_id']}:{right['work_id']}:{sa}:{sb}")
    return data, errors


def _chemin_sur(brut: str, *, pour_ecriture: bool = False) -> Path:
    """Resout et valide un chemin AVANT tout acces disque (SonarCloud S8707,
    new_security_rating C sur ce fichier neuf : deux lectures/ecritures d'un
    chemin argv sans validation prealable, lignes 21 et 129 avant ce correctif).

    Pas de confinement a l'arborescence du depot : mesure deja faite au tour
    precedent, `daily_start.py` du pack appelle ce validateur sur des chemins
    hors depot (son propre gabarit) — confiner casserait l'installation neuve.
    La validation porte donc sur la forme et la nature de la cible : octet nul
    refuse, `..`/liens symboliques aplatis par resolve(), puis existence et
    type verifies. Leve OSError (deja intercepte aux deux appels) plutot qu'une
    classe dediee : le contrat d'exit 2 / LECTURE_IMPOSSIBLE / SORTIE_IMPOSSIBLE
    ne change pas.
    """
    if "\x00" in brut:
        raise OSError("le chemin contient un octet nul")
    chemin = Path(brut).resolve(strict=not pour_ecriture)
    if pour_ecriture:
        if not chemin.parent.is_dir():
            raise OSError(f"repertoire de sortie inexistant : {chemin.parent}")
        if chemin.exists() and not chemin.is_file():
            raise OSError(f"la cible existe et n'est pas un fichier regulier : {chemin}")
    elif not chemin.is_file():
        raise OSError(f"n'est pas un fichier regulier : {chemin}")
    return chemin


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ownership")
    parser.add_argument("--json-output")
    args = parser.parse_args()
    try:
        data, errors = validate(_chemin_sur(args.ownership))
    except (OSError, UnicodeDecodeError) as exc:
        # exit 2 = aucun verdict de conformite exploitable, la table n'a jamais ete lue.
        # Sans interception, l'exception remontait non captee : exit 1 avec traceback,
        # indiscernable pour un appelant qui teste `== 1` d'une table lue et non
        # conforme. Fixture : chemin = repertoire, ou contenu non UTF-8 -> pack plante
        # (traceback, exit 1) au lieu de signaler proprement.
        print(f"LECTURE_IMPOSSIBLE:{exc}")
        return 2
    result = {"rows": len(data), "active": sum(r["status"] in ACTIVE for r in data), "errors": errors}
    if args.json_output:
        try:
            chemin_sortie = _chemin_sur(args.json_output, pour_ecriture=True)
            chemin_sortie.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except OSError as exc:
            # Meme raison que ci-dessus : sans interception, une table lue ET conforme
            # rendait quand meme exit 1 (traceback) si --json-output etait inscriptible.
            print(f"SORTIE_IMPOSSIBLE:{exc}")
            return 2
    if errors:
        print("\n".join(errors))
        return 1
    print(f"COORDINATION_OK rows={result['rows']} active={result['active']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

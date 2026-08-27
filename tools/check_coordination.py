#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path, PurePosixPath

ACTIVE = {"ACTIVE", "REVIEW", "READY_TO_MERGE"}
OWNERS = {"CODEX", "CLAUDE", "CHATGPT", "NATHAN", "UNASSIGNED"}
STATUSES = {"QUEUED", "ACTIVE", "BLOCKED", "REVIEW", "READY_TO_MERGE", "MERGED", "TRANSFER"}
CORE_RE = re.compile(r"^C(?:0[0-9]|1[0-9]|2[0-4])-\d{3}$")
CLAUDE_RE = re.compile(r"^(?:ISS-|AUD-|BUG-|R4-)")
HEADER = ["Work ID", "Owner", "Branch", "Path scope", "Status", "Updated UTC", "Next"]
# Une ligne de separation Markdown valide : "|---|---|", "| --- | --- |",
# avec ou sans ":" d'alignement, au moins 3 tirets par colonne.
TIRETS_MINIMUM_SEPARATEUR = 3
MARQUEURS_BLOC_CODE = ("```", "~~~")


def est_ligne_separatrice(ligne: str) -> bool:
    """Vraie pour une ligne de separation Markdown du type `|---|:---:|---|`.

    Ecrit sans quantificateur imbrique, deliberement. La forme regex naturelle
    `^\\|(\\s*:?-{3,}:?\\s*\\|)+$` repete un groupe qui commence ET finit par `\\s*`,
    motif super-lineaire que SonarCloud classe en point chaud de securite (S5852)
    et qui a fait tomber la Security Rating de cette PR en C.

    Mesure honnete : sur des entrees realistes (jusqu'a 22 groupes valides suivis
    d'une queue non conforme) aucune explosion combinatoire n'a ete reproduite —
    l'ancrage par `-{3,}` et `\\|` limite les decoupages possibles. Le defaut est
    donc le MOTIF, pas un exploit demontre. Il est corrige quand meme : le
    decoupage explicite ci-dessous est lineaire par construction, se lit plus
    clairement, et supprime le point chaud sans rien couter.
    """
    ligne = ligne.strip()
    if len(ligne) < 2 or not ligne.startswith("|") or not ligne.endswith("|"):
        return False
    cellules = ligne[1:-1].split("|")
    return bool(cellules) and all(_est_cellule_separatrice(c) for c in cellules)


def _est_cellule_separatrice(cellule: str) -> bool:
    """Vraie pour une cellule de separation du type `---`, `:---`, `---:`, `:---:`.

    Ecrit sans regex, deliberement, comme est_ligne_separatrice au-dessus. Toute
    forme `\\s*...\\s*` autour d'un coeur de longueur variable est un motif que
    SonarCloud classe en point chaud de securite (S5852), et deux tentatives de
    reecriture regex n'ont pas suffi a faire repasser la Security Rating en A.
    Un decoupage explicite ferme la question : il est lineaire par construction
    et ne laisse aucun motif a analyser.
    """
    noyau = cellule.strip()
    noyau = noyau.removeprefix(":").removesuffix(":")
    return len(noyau) >= TIRETS_MINIMUM_SEPARATEUR and set(noyau) == {"-"}


def parse_rows(path: Path) -> tuple[list[dict[str, str]], list[str], bool]:
    out: list[dict[str, str]] = []
    errors: list[str] = []
    header_found = False
    lines = path.read_text(encoding="utf-8").splitlines()
    in_fence = False
    for lineno, raw in enumerate(lines, 1):
        line = raw.strip()
        if line.startswith(MARQUEURS_BLOC_CODE):
            in_fence = not in_fence
            continue
        if in_fence:
            # Un document qui documente le format (ex. README, ou cette meme table
            # citee en exemple) peut reciter l'en-tete ou une ligne de table dans un
            # bloc de code : ce n'est pas une table de coordination reelle, ne pas la
            # compter. Ecart corrige : avant ce commit, une ligne "== HEADER" comptait
            # partout, y compris ici, et un document qui ne fait que documenter le
            # format passait a tort en COORDINATION_OK rows=0.
            continue
        if not line.startswith("|") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells == HEADER:
            # Une ligne egale a l'en-tete ne suffit pas non plus hors bloc de code :
            # elle peut etre citee en prose (une phrase qui la mentionne entre
            # backticks au fil du texte) sans qu'aucune table ne suive. Exiger que la
            # ligne suivante soit une vraie ligne de separation avant de considerer
            # qu'une table de coordination commence ici.
            next_line = lines[lineno].strip() if lineno < len(lines) else ""
            if est_ligne_separatrice(next_line):
                header_found = True
            continue
        if len(cells) != 7:
            errors.append(f"MALFORMED_ROW:{lineno}:{len(cells)}")
            continue
        out.append(dict(zip(["work_id", "owner", "branch", "scope", "status", "updated", "next"], cells)))
    if in_fence:
        # Fail-closed. Le suivi de bloc de code est une bascule : un fence non
        # referme fait ignorer EN SILENCE toutes les lignes suivantes, donc les
        # collisions de branche et de chemin qu'elles porteraient. Mesure : une
        # table valide suivie d'un `~~~` orphelin puis d'une ligne en collision
        # rendait COORDINATION_OK exit 0, la ou la version d'avant ce garde-fou
        # rendait BRANCH_COLLISION + PATH_COLLISION exit 1. Le durcissement du
        # bloc de code avait donc ouvert un chemin fail-open dans le controle
        # qu'il pretendait renforcer. Un fence orphelin est une faute de frappe
        # banale dans un fichier Markdown edite a la main, que les rendus
        # absorbent sans rien signaler : il doit rougir, pas passer.
        errors.append("UNTERMINATED_FENCE")
    return out, errors, header_found


def valid_scope(scope: str) -> bool:
    if scope in {"read-only", "task spec exact"}:
        return True
    if not scope.strip():
        return False
    for item in [x.strip() for x in scope.split(";") if x.strip()]:
        p = PurePosixPath(item)
        if p.is_absolute() or ".." in p.parts or item.startswith("~"):
            return False
    return True


def overlaps(a: str, b: str) -> bool:
    if a in {"read-only", "task spec exact"} or b in {"read-only", "task spec exact"}:
        return False
    # casefold() ici pour la meme raison que MODULE_CODE_DURING_CORE plus bas, qui
    # compare deja les scopes casefold(). Sans ce casefold, deux scopes actifs
    # "Coordination" et "coordination" ne collisionnaient jamais ici (chemins
    # distincts au sens strict de PurePosixPath) alors que MODULE_CODE_DURING_CORE les
    # traite comme identiques quelques lignes plus loin dans validate() : incoherence
    # interne heritee du pack amont, corrigee ici pour que les deux controles de scope
    # partagent la meme notion de "meme chemin" : meme normalisation de casse ET
    # de separateur, comme MODULE_CODE_DURING_CORE le fait deja.
    pa = PurePosixPath(a.replace("\\", "/").rstrip("/").casefold())
    pb = PurePosixPath(b.replace("\\", "/").rstrip("/").casefold())
    return pa == pb or pa in pb.parents or pb in pa.parents


def validate(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    data, errors, header_found = parse_rows(path)
    if not header_found:
        # Plancher de non-vacuité : un mauvais chemin, un fichier tronqué ou vidé
        # n'ont aucune ligne "| Work ID | Owner | ... |" et ne doivent pas rendre le
        # même succès qu'une vraie table avec zéro ligne de données (gabarit neuf,
        # légitime : cf. tools/daily_start.py). L'en-tête, pas le nombre de lignes,
        # est le signal fiable — une table vide MAIS avec en-tête reste valide.
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ownership")
    parser.add_argument("--json-output")
    args = parser.parse_args()
    data, errors = validate(Path(args.ownership))
    result = {"rows": len(data), "active": sum(r["status"] in ACTIVE for r in data), "errors": errors}
    if args.json_output:
        Path(args.json_output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if errors:
        print("\n".join(errors))
        return 1
    print(f"COORDINATION_OK rows={result['rows']} active={result['active']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

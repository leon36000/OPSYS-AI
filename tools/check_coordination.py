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
    # Antislash normalise avant PurePosixPath -- comme overlaps() et
    # MODULE_CODE_DURING_CORE, revue scellee -- sinon "foo\..\modules m\M7"
    # (un seul composant PurePosixPath, ".." absent de .parts) passe ce
    # controle puis echappe aussi a MODULE_CODE_DURING_CORE apres son propre
    # remplacement ("foo/../modules m" jamais egal a "modules m").
    if scope in SCOPES_HORS_COLLISION:
        return True
    if not scope.strip():
        return False
    items = [x.strip() for x in scope.split(";") if x.strip()]
    # "scope.strip()" seul ne suffit pas : une cellule ";" ou "; ;" n'est pas
    # vide (le ";" est un caractere reel) mais ne decompose en AUCUN item --
    # la boucle ci-dessous ne s'executait alors jamais, et la fonction rendait
    # True sans avoir rien valide. Fail-open trouve en revue scellee : ce
    # scope vide passait ensuite PATH_COLLISION et MODULE_CODE_DURING_CORE
    # (le seul interdit dur de l'ADR-0004) inaperçu, faute d'item a comparer.
    if not items:
        return False
    for item in items:
        p = PurePosixPath(item.replace("\\", "/"))
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
        # Deux fail-opens fermes ici sur le meme interdit dur de l'ADR-0004 ("aucun
        # code metier M avant handoff Core"), trouves par deux revues scellees
        # independantes. (1) "coordination;modules m/M7" sur une ligne ACTIVE ne
        # declenchait rien : le test portait sur la cellule ENTIERE, jamais sur ses
        # items separes par ";" comme le font deja valid_scope()/overlaps() ci-dessus.
        # (2) "./modules m/M7" ne declenchait rien non plus une fois (1) ferme : un
        # prefixe "./" — que valid_scope() accepte comme scope valide et qu'overlaps()
        # normalise deja via PurePosixPath — echappait a la comparaison de chaine
        # brute. Les deux fermes par le meme mecanisme que overlaps() : PurePosixPath
        # par element, egalite ou parente avec "modules m".
        cible_module_m = PurePosixPath("modules m")
        scopes_normalises = [
            PurePosixPath(x.strip().replace("\\", "/").casefold())
            for x in row["scope"].split(";") if x.strip()
        ]
        if status in ACTIVE and any(
            s == cible_module_m or cible_module_m in s.parents for s in scopes_normalises
        ):
            errors.append(f"MODULE_CODE_DURING_CORE:{wid}")
        if CORE_RE.match(wid) and owner not in {"CODEX", "UNASSIGNED"} and status != "TRANSFER":
            errors.append(f"CORE_OWNER:{wid}:{owner}")
        if CLAUDE_RE.match(wid) and owner not in {"CLAUDE", "UNASSIGNED"} and status != "TRANSFER":
            errors.append(f"ISSUE_OWNER:{wid}:{owner}")

    active = [r for r in data if r["status"] in ACTIVE]
    for idx, left in enumerate(active):
        for right in active[idx + 1 :]:
            # "n/a" exempte, en miroir de SCOPES_HORS_COLLISION pour PATH_COLLISION.
            # Fail-open trouve en revue scellee : BRANCH (ligne 96 ci-dessus) autorise
            # "n/a" comme sentinelle des missions sans branche (read-only), mais
            # BRANCH_COLLISION comparait les branches brutes sans cette exemption --
            # deux missions read-only actives, toutes deux "n/a", devenaient
            # structurellement inexprimables alors que WORK-OWNERSHIP.md et
            # CODEX-QUEUE.md en livrent plusieurs.
            if left["branch"] == right["branch"] and left["branch"].strip().casefold() != "n/a":
                errors.append(f"BRANCH_COLLISION:{left['work_id']}:{right['work_id']}")
            for sa in [x.strip() for x in left["scope"].split(";") if x.strip()]:
                for sb in [x.strip() for x in right["scope"].split(";") if x.strip()]:
                    if overlaps(sa, sb):
                        errors.append(f"PATH_COLLISION:{left['work_id']}:{right['work_id']}:{sa}:{sb}")
    return data, errors


def _chemin_sur(brut: str, *, pour_ecriture: bool = False) -> Path:
    """Resout et valide un chemin AVANT tout acces disque (SonarCloud S8707,
    new_security_rating C sur ce fichier neuf : lecture et ecriture d'un
    chemin argv sans validation prealable, motif cite au point d'appel de
    chacune des deux dans main() plutot que par numero de ligne — un renvoi
    par ligne se refute des la prochaine edition de ce fichier).

    Pas de confinement a l'arborescence du depot : mesure deja faite au tour
    precedent, `daily_start.py` du pack appelle ce validateur sur des chemins
    hors depot (son propre gabarit) — confiner casserait l'installation neuve.
    La validation porte donc sur la forme et la nature de la cible : octet nul
    refuse, `..`/liens symboliques aplatis par resolve(), puis existence et
    type verifies. Leve OSError (deja intercepte aux deux appels) plutot qu'une
    classe dediee : le contrat d'exit 2 / LECTURE_IMPOSSIBLE / SORTIE_IMPOSSIBLE
    ne change pas.

    Lecture et ecriture n'exigent PAS la meme nature de cible, deliberement.

    REGRESSION mesuree et PARTIELLEMENT fermee ici, trouvee par revue scellee
    independante (3 sieges, convergents) : une premiere version de cette
    fonction exigeait `is_file()` en lecture, ce qui rejetait un FIFO,
    `/dev/stdin` ou une substitution de processus (`<(...)`) — des entrees
    legitimes et atteignables en ligne de commande que `read_text()` seul
    lisait deja sans encombre avant l'introduction de cette fonction.
    Retrecissement de comportement jamais annonce comme tel.

Fermee pour le FIFO nomme : `elif chemin.is_dir()` n'exclut plus que les
    repertoires — un FIFO resout normalement (c'est un vrai chemin existant)
    et n'est pas un repertoire, donc passe. `/dev/stdin` ne passe QUE sur
    redirection depuis un fichier regulier (`tool /dev/stdin < f`,
    `COORDINATION_OK`, mesure) : adosse a un tube (`cat f | tool /dev/stdin`,
    l'usage courant), il resout vers le meme `pipe:[N]` synthetique que la
    substitution de processus ci-dessous et echoue pareillement — PAS
    ferme, meme cause.

    PAS fermee pour la substitution de processus ni pour `/dev/stdin` sur
    tube, deliberement, apres un
    aller-retour reel avec la CI — a dire plutot qu'a cacher. Un premier
    essai ajoutait un repli sur le chemin NON resolu quand
    `resolve(strict=True)` echoue lui-meme sur ce type d'entree (mesure :
    `<(...)` resout vers un `pipe:[N]` synthetique, `FileNotFoundError`).
    Ce repli fonctionnait — `COORDINATION_OK` obtenu localement — mais
    SonarCloud a rouvert `pythonsecurity:S8707` sur le code REEL de ce
    depot, au point d'acces `read_text()` de `parse_rows()` : le chemin non
    resolu qui emprunte ce repli n'a, de fait, traverse AUCUNE validation
    avant d'atteindre l'acces disque, exactement le motif que ce fichier
    existe pour fermer. Verifie AVEC preuve avant de conclure : `sonar
    analyze` en local, `--depth DEEP` inclus, ne reproduit PAS ce
    diagnostic sur ce fichier — seule l'analyse serveur reelle (taint
    inter-fonctions) le voit. Ne pas prendre un local vert pour une preuve
    sur cette regle precise ; seule la CI reelle fait foi ici. Le repli est
    retire : `resolve(strict=True)` reste sans exception pour la lecture,
    la substitution de processus et `/dev/stdin` sur tube redeviennent
    `LECTURE_IMPOSSIBLE`, exit 2 — arbitrage assume entre un gate CI dur et
    des entrees legitimes mais jamais observees dans l'usage documente de
    cet outil (toujours invoque sur un chemin de fichier reel dans ce dépôt).

    En ecriture, la cible doit rester un fichier regulier ou un chemin
    inexistant : `--json-output` cree la sortie, un FIFO ou peripherique en
    cible d'ecriture est un cas d'usage distinct, plus risque, qu'aucune
    fixture ne demande d'ouvrir ici. `resolve(strict=False)` y reste sans
    repli particulier : la cible n'a PAS a exister d'avance (c'est elle que
    --json-output cree), seul son repertoire parent doit exister, verifie
    juste apres.
    """
    if "\x00" in brut:
        raise OSError("le chemin contient un octet nul")
    try:
        if pour_ecriture:
            chemin = Path(brut).resolve(strict=False)
        else:
            chemin = Path(brut).resolve(strict=True)
    except RuntimeError as exc:
        # resolve() leve RuntimeError (pas OSError) sur une boucle de liens
        # symboliques -- echappe aux deux except de main(), exit 1 + traceback,
        # stdout vide. Reconverti en OSError ici pour que le contrat exit 2
        # tienne sur CETTE classe d'entree aussi, sans elargir les except de
        # main() a RuntimeError (qui masquerait un bug distinct, sans rapport
        # avec un chemin, survenant plus loin dans validate()/parse_rows()).
        raise OSError(str(exc)) from exc
    if pour_ecriture:
        if not chemin.parent.is_dir():
            raise OSError(f"repertoire de sortie inexistant : {chemin.parent}")
        if chemin.exists() and not chemin.is_file():
            raise OSError(f"la cible existe et n'est pas un fichier regulier : {chemin}")
    elif chemin.is_dir():
        raise OSError(f"est un repertoire : {chemin}")
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
    # is not None, pas une verite tronquee : --json-output '' est une demande reelle
    # (argparse le distingue de l'absence, qui vaut None), pas une absence de demande.
    # Fail-open mesure et ferme ici : avec `if args.json_output:` seul, cette valeur
    # vide sautait le bloc entier en silence -- exit 0, COORDINATION_OK, rien ecrit --
    # exactement le fail-open que ce bloc existe pour fermer, en pire (exit 0 au lieu
    # de l'exit 1 du pack, indetectable meme par un appelant testant `!= 0`).
    if args.json_output is not None:
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

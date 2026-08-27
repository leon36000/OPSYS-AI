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
# avec ou sans ":" d'alignement, au moins 3 tirets par colonne. Les pipes de bord
# sont optionnels (GFM), comme pour les lignes de donnees : cf. est_ligne_separatrice.
TIRETS_MINIMUM_SEPARATEUR = 3
MARQUEURS_BLOC_CODE = ("```", "~~~")


def est_ligne_separatrice(ligne: str) -> bool:
    """Vraie pour une ligne de separation Markdown du type `|---|:---:|---|`.

    Les pipes de bord sont OPTIONNELS, comme le prevoit GFM et comme le fait deja
    le decoupage des lignes de donnees et de l'en-tete (`line.strip("|")`) plus bas.
    Exiger ici les deux pipes de bord alors que les lignes de donnees s'en passent
    creait deux notions de "bord de ligne" dans le meme fichier : une table
    parfaitement legitime ecrite sans pipe final voyait son en-tete reconnu comme
    tel, puis sa ligne de separation recomptee en ligne de donnees, et rendait
    `HEADER_MISSING` + `OWNER:---:---` + `STATUS:---:---`, exit 1, la ou la version
    du pack rend `COORDINATION_OK rows=1 active=1`, exit 0. Fixture et sorties des
    deux cotes dans coordination/CLAUDE-STATUS.md.

    Mode de defaillance de cet elargissement, nomme avant d'etre ecrit : un `---`
    seul (barre horizontale Markdown, delimiteur de front-matter YAML) ne doit PAS
    devenir une ligne de separation, sans quoi un en-tete cite en prose et suivi
    d'une barre horizontale passerait pour le debut d'une vraie table et annulerait
    le durcissement HEADER_MISSING. D'ou l'exigence d'au moins un `|` : `---` est
    refuse, `|---|` et `---|---` sont acceptes.

    Ecrit sans quantificateur imbrique, deliberement. La forme regex naturelle
    repete un groupe qui commence ET finit par `\\s*`, motif super-lineaire que
    SonarCloud classe en point chaud de securite (S5852) et qui a fait tomber la
    Security Rating de cette PR en C. Ce verdict-la vient du service et n'est pas
    re-mesurable depuis ce depot : il est cite comme le motif du changement, pas
    comme une mesure locale. Le decoupage explicite ci-dessous est lineaire par
    construction et ne laisse aucun motif a analyser.
    """
    ligne = ligne.strip()
    if "|" not in ligne:
        return False
    cellules = ligne.strip("|").split("|")
    return all(_est_cellule_separatrice(c) for c in cellules)


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


class CheminInvalide(ValueError):
    """Un chemin fourni en argument n'a pas passe la validation prealable."""


class LectureImpossible(ValueError):
    """La cible a passe la validation de chemin mais n'a pas pu etre lue ni decodee.

    Cas reel : un fichier regulier non decodable en UTF-8. Sans cette interception,
    `read_text` levait `UnicodeDecodeError`, l'interpreteur rendait exit 1 avec un
    traceback sur stderr et rien sur stdout — indiscernable, pour un appelant qui
    teste `== 1`, d'une table lue et non conforme. Or la table n'a jamais ete lue :
    c'est exit 2, comme un chemin refuse. Meme traitement pour un `OSError` a la
    lecture (permission, disparition de la cible entre la validation et la lecture).
    """


# L'ecriture de `--json-output` est interceptee directement dans main() et rend
# `SORTIE_IMPOSSIBLE:<raison>` + exit 2, pour la meme raison que LectureImpossible :
# sans interception, un OSError a l'ecriture rendait exit 1 avec traceback alors que
# la table etait lue ET conforme, ce qui contredit la signification annoncee de l'exit 1.


def _chemin_valide(brut: str, *, pour_ecriture: bool = False) -> Path:
    """Valide un chemin AVANT tout acces au systeme de fichiers.

    Motif : SonarCloud remonte le motif `pythonsecurity:S8707` sur ce module —
    « LLMs running this code with faulty CLI arguments can escape file system
    restrictions » — a la lecture (`Path(args.ownership)`) comme a l'ecriture
    (`Path(args.json_output).write_text(...)`). Les deux lignes viennent du pack
    amont, mais le fichier etant neuf dans ce depot, la totalite de son contenu
    compte comme new code. Comme pour S5852 ci-dessus, ce verdict vient du service
    et n'est pas re-mesurable depuis ce depot : motif du changement, pas mesure.

    Ce validateur ne peut PAS etre confine a l'arborescence du depot : le
    `daily_start.py` du pack l'appelle legitimement sur son propre gabarit, qui
    vit hors du depot (mesure : il l'invoque sur coordination/ du depot, et sur
    repo-overlay/coordination/ du pack quand la premiere cible n'existe pas
    encore). Confiner casserait l'installation neuve — le defaut qu'on
    cherche a eviter, en pire. Cette mesure-la, elle, est reproductible : elle se lit
    dans le source de tools/daily_start.py du pack.

    Codes de sortie : un chemin refuse rend `CHEMIN_INVALIDE:<raison>` et exit 2,
    distinct de l'exit 1 des erreurs de contenu et de l'exit 0 de COORDINATION_OK.
    Documente dans coordination/README.md et coordination/CLAUDE-STATUS.md.

    La validation porte donc sur la FORME et la NATURE de la cible, pas sur son
    emplacement : octet nul refuse, chemin resolu (les `..` et les liens
    symboliques sont aplatis avant tout acces), et la cible doit etre un fichier
    regulier existant en lecture, ou un chemin dont le parent est un repertoire
    existant en ecriture. Un lien symbolique menant hors d'un perimetre attendu
    devient ainsi visible dans le chemin resolu au lieu d'etre suivi a l'aveugle.
    """
    if "\x00" in brut:
        raise CheminInvalide("le chemin contient un octet nul")
    try:
        chemin = Path(brut).resolve(strict=not pour_ecriture)
    except (OSError, RuntimeError) as exc:
        raise CheminInvalide(f"chemin non resolvable : {exc}") from None
    if pour_ecriture:
        parent = chemin.parent
        if not parent.is_dir():
            raise CheminInvalide(f"repertoire de sortie inexistant : {parent}")
        if chemin.exists() and not chemin.is_file():
            raise CheminInvalide(f"la cible existe et n'est pas un fichier regulier : {chemin}")
    elif not chemin.is_file():
        raise CheminInvalide(f"n'est pas un fichier regulier : {chemin}")
    return chemin


def parse_rows(path: Path) -> tuple[list[dict[str, str]], list[str], bool]:
    out: list[dict[str, str]] = []
    errors: list[str] = []
    header_found = False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise LectureImpossible(f"contenu illisible : {exc}") from None
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
            # compter. Ecart corrige vis-a-vis du pack : dans la version amont, une
            # ligne "== HEADER" comptait partout, y compris ici, et un document qui ne
            # fait que documenter le format passait a tort en COORDINATION_OK rows=0.
            #
            # CONTREPARTIE ASSUMEE, fail-open non refermee : une PAIRE de fences
            # equilibree autour de vraies lignes de donnees les fait disparaitre en
            # silence, avec les collisions qu'elles porteraient. Mesure, fixture
            # "en-tete + separateur hors fence, deux lignes en collision entre
            # ```" : ce fichier-ci rend COORDINATION_OK rows=0 active=0 exit 0, la
            # ou la version du pack rend BRANCH_COLLISION + PATH_COLLISION exit 1.
            # C'est donc une regression fail-open de la detection de collision vis-a-vis
            # du pack, ecrite ici plutot que refermee : signaler ces lignes rouvrirait
            # exactement le faux positif que le suivi de fence existe pour supprimer
            # (un fichier qui documente son propre format dans un bloc de code
            # deviendrait non conforme). Un fence equilibre est un acte d'ecriture
            # delibere ; un fence orphelin est une faute de frappe — d'ou le
            # traitement different de ce dernier, plus bas.
            continue
        # Un seul et meme detecteur decide ce qu'est une ligne de separation, ici
        # comme dans le controle d'en-tete ci-dessous. La version du pack testait
        # `line.startswith("|---")`, litteralement, alors que le controle d'en-tete
        # utilise est_ligne_separatrice : deux notions de separateur dans le meme
        # fichier, dont une seule etait documentee. Une table ecrite
        # `| --- | --- |` ou `|:---|---:|` voyait donc son en-tete confirme, puis sa
        # propre ligne de separation recomptee en ligne de donnees —
        # `OWNER:---:---`, exit 1. Une table Markdown legitime, rejetee avec un
        # diagnostic trompeur.
        #
        # Mode de defaillance de ce correctif, nomme avant d'etre ecrit : elargir
        # ce qui est saute peut faire disparaitre EN SILENCE une vraie ligne de
        # donnees. Le sous-ensemble concerne est exactement celui des lignes dont
        # TOUTES les cellules sont `---`/`:---`/`---:`/`:---:` — aucune ne porte de
        # Work ID, donc aucune n'est une entree de coordination reelle.
        #
        # L'echange n'est PAS a sens unique, et la formulation "elargit sans rien
        # retirer" serait fausse en general : `|--- foo` etait saute par le prefixe
        # du pack et ne l'est plus par le detecteur. Ce qui tient sans dependre
        # d'aucun corpus, ce sont deux proprietes de construction :
        #  - une ligne NOUVELLEMENT sautee a toutes ses cellules faites de `-` et `:`
        #    seulement, donc pas de Work ID, donc ce n'est pas une entree reelle ;
        #  - une ligne qui PERD son saut retombe dans le controle de forme et devient
        #    MALFORMED_ROW ou une ligne de donnees validee — plus bruyante, jamais
        #    silencieusement verte.
        # Aucun decompte de corpus n'est fige ici : il serait invalide par la
        # prochaine edition d'un .md quelconque du depot. La commande de balayage est
        # dans coordination/CLAUDE-STATUS.md, a rejouer plutot qu'a croire.
        if not line.startswith("|") or est_ligne_separatrice(line):
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
        # rendait COORDINATION_OK exit 0, la ou la version du pack — qui ne suit pas
        # les blocs de code du tout — rend BRANCH_COLLISION + PATH_COLLISION exit 1.
        # Le durcissement du bloc de code avait donc ouvert un chemin fail-open dans
        # le controle qu'il pretendait renforcer. Un fence orphelin est une faute de frappe
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
    try:
        chemin_ownership = _chemin_valide(args.ownership)
        chemin_sortie = _chemin_valide(args.json_output, pour_ecriture=True) if args.json_output else None
    except CheminInvalide as exc:
        print(f"CHEMIN_INVALIDE:{exc}")
        return 2
    # Exit 2 = aucun verdict de conformite exploitable n'a ete produit. Trois causes,
    # trois prefixes distincts, jamais un traceback : chemin refuse avant tout acces
    # (CHEMIN_INVALIDE), cible illisible ou non decodable (LECTURE_IMPOSSIBLE),
    # sortie JSON non ecrite (SORTIE_IMPOSSIBLE). L'exit 1 est reserve a "table lue,
    # non conforme" ; sans ces interceptions il absorbait aussi les echecs de lecture
    # et d'ecriture, ce qui rendait faux le contrat annonce dans coordination/README.md.
    try:
        data, errors = validate(chemin_ownership)
    except LectureImpossible as exc:
        print(f"LECTURE_IMPOSSIBLE:{exc}")
        return 2
    result = {"rows": len(data), "active": sum(r["status"] in ACTIVE for r in data), "errors": errors}
    if chemin_sortie is not None:
        try:
            chemin_sortie.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"SORTIE_IMPOSSIBLE:ecriture impossible : {exc}")
            return 2
    if errors:
        print("\n".join(errors))
        return 1
    print(f"COORDINATION_OK rows={result['rows']} active={result['active']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

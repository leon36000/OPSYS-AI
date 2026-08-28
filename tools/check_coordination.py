#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath

ACTIVE = {"ACTIVE", "REVIEW", "READY_TO_MERGE"}
OWNERS = {"CODEX", "CLAUDE", "CHATGPT", "NATHAN", "UNASSIGNED"}
STATUSES = {"QUEUED", "ACTIVE", "BLOCKED", "REVIEW", "READY_TO_MERGE", "MERGED", "TRANSFER"}
CORE_RE = re.compile(r"^C(?:0\d|1\d|2[0-4])-\d{3}$")
CLAUDE_RE = re.compile(r"^(?:ISS-|AUD-|BUG-|R4-)")
# Ligne de separation GFM entiere -- pas un prefixe. Fail-open trouve en revue
# scellee : l'ancien test ("line.startswith(\"|---\")") sautait aussi toute ligne
# de DONNEES dont la premiere cellule commence par "---" (ex. Work ID "---X"),
# silencieusement exclue de la table -- MODULE_CODE_DURING_CORE et les collisions
# y compris. Mesure : "|---X | NATHAN | main | modules m/M7 | ACTIVE | ... | ... |"
# rendait COORDINATION_OK rows=0 active=0 avant ce correctif. Le motif entier
# (pas seulement la premiere cellule) evite aussi de faire regresser les deux
# limites deja documentees dans coordination/README.md : un separateur espace
# ("| --- |") ou porteur des deux-points d'alignement ("|:---|") ne matche pas
# davantage apres ce correctif qu'avant -- seul le prefixe "---" nu, sans espace
# ni deux-points, y compte comme separation, exactement le format que ce depot
# livre reellement (verifie dans les 4 fichiers de table du diff).
SEPARATOR_RE = re.compile(r"^\|(-+\|)+$")
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
        if not line.startswith("|") or SEPARATOR_RE.match(line):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells == HEADER:
            # Fixture : fichier sans aucune table -> pack COORDINATION_OK rows=0 exit 0
            # (a tort). Exiger que la ligne suivante soit une vraie separation evite
            # aussi qu'une simple citation de l'en-tete en prose ne compte comme table.
            next_line = lines[lineno].strip() if lineno < len(lines) else ""
            if SEPARATOR_RE.match(next_line):
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


def _touche_modules_m(scope: str) -> bool:
    # Trois fail-opens fermes ici sur le meme interdit dur de l'ADR-0004 ("aucun
    # code metier M avant handoff Core"), trouves par trois revues scellees
    # independantes. (1) "coordination;modules m/M7" sur une ligne ACTIVE ne
    # declenchait rien : le test portait sur la cellule ENTIERE, jamais sur ses
    # items separes par ";" comme le font deja valid_scope()/overlaps() ci-dessus.
    # (2) "./modules m/M7" ne declenchait rien non plus une fois (1) ferme : un
    # prefixe "./" — que valid_scope() accepte comme scope valide et qu'overlaps()
    # normalise deja via PurePosixPath — echappait a la comparaison de chaine
    # brute. (3) (tour 10) un scope "." ou "./" — valide pour valid_scope(), et qui
    # couvre pourtant TOUT l'arbre, "modules m/" compris — echappait encore : le test
    # ne verifiait que "modules m" == s ou "modules m" DESCEND de s (cible_module_m
    # in s.parents utilise a l'envers ne matche pas ici), jamais le sens inverse, "s
    # est un ANCETRE de modules m" -- alors que overlaps() juste au-dessus teste deja
    # les DEUX sens ("pa in pb.parents or pb in pa.parents"). Les trois fermes par le
    # meme mecanisme que overlaps() : PurePosixPath par element, egalite OU parente
    # dans les deux sens avec "modules m".
    cible_module_m = PurePosixPath("modules m")
    scopes_normalises = [
        PurePosixPath(x.strip().replace("\\", "/").casefold())
        for x in scope.split(";") if x.strip()
    ]
    return any(
        s == cible_module_m or cible_module_m in s.parents or s in cible_module_m.parents
        for s in scopes_normalises
    )


def _erreurs_structurelles(row: dict[str, str], seen: set[str]) -> list[str]:
    """Premier groupe des controles portant sur UNE seule ligne (WORK_ID_EMPTY,
    DUPLICATE_WORK, OWNER, STATUS, SCOPE, BRANCH) — extrait de validate() (revue
    scellee, AUD-QUAL-007, #594) pour reduire sa complexite cognitive sous le seuil
    SonarCloud (python:S3776, mesure 44 avant ce commit) ; comportement inchange,
    verifie contre la suite de non-regression de coordination/tests/ (#598 : chaque
    branche de ce controle y porte deja sa propre fixture) avant d'etre considere
    fait. ATTENTION, imprecision corrigee en revue scellee (tour 3 de #599, 3 sieges
    convergents) : SEUL DUPLICATE_WORK n'est PAS independant des autres lignes de la
    table — son verdict depend de `seen`, l'ensemble des work_id deja vus (mesure : la
    meme ligne rend [] si `seen` est vide, ['DUPLICATE_WORK:...'] si une ligne
    anterieure y a deja insere le meme work_id). Les cinq autres controles de ce
    groupe sont, eux, bien locaux a la ligne. Precision (tour 4, 3 sieges
    convergents), sur l'effet de bord SORTANT que la reecriture du tour 3 avait omis
    de reenoncer : `seen.add(wid)` est execute inconditionnellement par CETTE
    fonction, work_id vide compris — c'est le SEUL site d'ecriture de `seen` de tout
    le fichier, et c'est lui qui rend DUPLICATE_WORK detectable sur les lignes
    SUIVANTES. Pendant : _erreurs_de_propriete().
    """
    errors: list[str] = []
    wid = row["work_id"]
    if not wid:
        errors.append("WORK_ID_EMPTY")
    if wid in seen:
        errors.append(f"DUPLICATE_WORK:{wid}")
    seen.add(wid)
    if row["owner"] not in OWNERS:
        errors.append(f"OWNER:{wid}:{row['owner']}")
    if row["status"] not in STATUSES:
        errors.append(f"STATUS:{wid}:{row['status']}")
    if not valid_scope(row["scope"]):
        errors.append(f"SCOPE:{wid}:{row['scope']}")
    if row["status"] in ACTIVE and row["branch"].lower() in {"main", "master", ""}:
        errors.append(f"BRANCH:{wid}")
    return errors


def _erreurs_de_propriete(row: dict[str, str]) -> list[str]:
    """Second groupe des controles par ligne (MODULE_CODE_DURING_CORE, CORE_OWNER,
    ISSUE_OWNER) — meme extraction et meme raison que _erreurs_structurelles()
    ci-dessus, dont c'est le pendant. Ses trois controles sont, eux, tous
    independants des autres lignes de la table (pas de `seen` ni d'etat accumule).
    Precision (tour 4, 3 sieges convergents) sur le regroupement de la phrase
    precedente, qui laissait a tort lire les trois codes comme relevant tous de
    l'ADR-0004 : SEUL MODULE_CODE_DURING_CORE en est l'interdit dur (« aucun code
    metier M avant handoff Core », cf. _touche_modules_m() ci-dessus). CORE_OWNER et
    ISSUE_OWNER relevent d'un controle distinct, proprietaire vs MOTIF du Work ID —
    pas juste un « prefixe » pour les deux : CLAUDE_RE (^(?:ISS-|AUD-|BUG-|R4-)) est
    un vrai prefixe, non ancre a la fin, mais CORE_RE (^C(?:0\\d|1\\d|2[0-4])-\\d{3}$)
    est ancre aux DEUX bouts — une forme COMPLETE de Work ID, pas un simple prefixe.
    Mesure, voir test_core_re_et_claude_re_nont_pas_de_faux_positifs :
    "C05-0011" (4 chiffres, hors \\d{3}$) n'est PAS reconnu, la ou un vrai prefixe
    l'aurait ete.
    """
    errors: list[str] = []
    wid = row["work_id"]
    owner = row["owner"]
    status = row["status"]
    if status in ACTIVE and _touche_modules_m(row["scope"]):
        errors.append(f"MODULE_CODE_DURING_CORE:{wid}")
    if CORE_RE.match(wid) and owner not in {"CODEX", "UNASSIGNED"} and status != "TRANSFER":
        errors.append(f"CORE_OWNER:{wid}:{owner}")
    if CLAUDE_RE.match(wid) and owner not in {"CLAUDE", "UNASSIGNED"} and status != "TRANSFER":
        errors.append(f"ISSUE_OWNER:{wid}:{owner}")
    return errors


def _erreurs_de_ligne(row: dict[str, str], seen: set[str]) -> list[str]:
    """Assemble les deux groupes ci-dessus, DANS L'ORDRE ou validate() les emettait
    avant extraction (AUD-QUAL-007, #594/#599). A l'origine (revue scellee, tour 1 de
    #599, 3 sieges convergents), cet ordre etait un invariant TENU par le code mais
    NON epingle par aucune fixture — echanger cet appel en
    `_erreurs_de_propriete(row) + _erreurs_structurelles(row, seen)` laissait alors
    toute la suite verte. Ferme depuis (AUD-QUAL-008, #600/#601, docstring
    rafraichie en AUD-QUAL-009, #602/#603) :
    coordination/tests/test_check_coordination.py epingle desormais cet ordre precis
    par `test_ordre_erreur_structurelle_avant_erreur_de_propriete_sur_meme_ligne`
    (egalite exacte de `stdout.splitlines()`, pas seulement l'exit code et le
    prefixe) — la meme mutation d'echange y fait maintenant rougir ce test.

    La meme suite epingle aussi, au niveau de validate() plutot que de cette
    fonction, que les erreurs par ligne precedent les erreurs de paire
    (`test_ordre_erreurs_de_ligne_avant_erreurs_de_collision`) — mais SEULEMENT a
    l'arite que sa fixture exerce (2 lignes actives, UNE paire, l'erreur de ligne
    portee par le membre DROIT de cette paire), pas en general. Sur-generalisation
    trouvee et mesuree en revue scellee (tour 1 de #603, siege 2) : un entrelacement
    MIROIR de celui que ce test exclut deja pour le membre GAUCHE (voir son propre
    commentaire) — emettre, pour chaque ligne, ses erreurs de ligne PUIS les paires
    ou elle est le membre DROIT plutot que le membre GAUCHE — laisse cette fixture et
    les 70 tests d'alors verts, tout en faisant sortir, sur une table a 3 lignes
    actives ou la ligne en erreur n'appartient a aucune paire en collision, des
    erreurs DE PAIRE avant des erreurs DE LIGNE. Cette relation precise reste NON
    epingle a cette arite — suivi separe : #604.

    L'ordre INTERNE a chaque groupe ci-dessus (entre les controles d'UN MEME
    groupe), lui, reste NON epingle a ce jour — voir l'en-tete de
    coordination/tests/test_check_coordination.py pour le detail exact de ce qui est
    et n'est pas couvert.
    """
    return _erreurs_structurelles(row, seen) + _erreurs_de_propriete(row)


def _erreurs_de_paire(left: dict[str, str], right: dict[str, str]) -> list[str]:
    """BRANCH_COLLISION et PATH_COLLISION pour UNE PAIRE de lignes ACTIVES — extrait
    de la double boucle de validate() (meme raison que ci-dessus) pour que sa propre
    complexite cognitive ne cumule pas celle des deux boucles `for` englobantes.
    """
    errors: list[str] = []
    # "n/a" exempte, en miroir de SCOPES_HORS_COLLISION pour PATH_COLLISION.
    # Fail-open trouve en revue scellee : le controle BRANCH ci-dessus autorise
    # "n/a" comme sentinelle des missions sans branche (read-only), mais
    # BRANCH_COLLISION comparait les branches brutes sans cette exemption --
    # deux missions read-only actives, toutes deux "n/a", deviendraient
    # structurellement inexprimables. Mesure sur l'arbre livre, pas un decompte
    # fige : seul WORK-OWNERSHIP.md porte une ligne active "n/a" a ce jour
    # (LIVE-ISSUE-RECONCILIATION) ; CODEX-QUEUE.md n'a pas de colonne Branch et
    # n'est pas concerne par cette exemption -- l'exemption reste voulue pour
    # toute ligne future de ce type, pas seulement celle qui existe aujourd'hui.
    if left["branch"] == right["branch"] and left["branch"].strip().casefold() != "n/a":
        errors.append(f"BRANCH_COLLISION:{left['work_id']}:{right['work_id']}")
    for sa in [x.strip() for x in left["scope"].split(";") if x.strip()]:
        for sb in [x.strip() for x in right["scope"].split(";") if x.strip()]:
            if overlaps(sa, sb):
                errors.append(f"PATH_COLLISION:{left['work_id']}:{right['work_id']}:{sa}:{sb}")
    return errors


def _erreurs_de_collision(active: list[dict[str, str]]) -> list[str]:
    """Controles par PAIRE de lignes ACTIVES (BRANCH_COLLISION, PATH_COLLISION) —
    extrait de validate() pour la meme raison que ci-dessus ; ne fait plus que
    porter la double boucle, la logique par paire vit dans _erreurs_de_paire().
    """
    errors: list[str] = []
    for idx, left in enumerate(active):
        for right in active[idx + 1 :]:
            errors.extend(_erreurs_de_paire(left, right))
    return errors


def validate(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    data, errors, header_found = parse_rows(path)
    if not header_found:
        # Plancher de non-vacuite : un chemin errone ou un fichier tronque/vide n'a
        # aucune ligne d'en-tete et ne doit pas rendre le meme succes qu'une vraie
        # table vide (en-tete + separateur, zero ligne, gabarit legitime).
        errors.append("HEADER_MISSING")
    seen: set[str] = set()
    for row in data:
        errors.extend(_erreurs_de_ligne(row, seen))
    active = [r for r in data if r["status"] in ACTIVE]
    errors.extend(_erreurs_de_collision(active))
    return data, errors


def _chemin_sur(brut: str, *, pour_ecriture: bool = False) -> Path:
    """Resout et valide un chemin AVANT tout acces a son CONTENU (SonarCloud S8707,
    new_security_rating C sur ce fichier neuf : lecture et ecriture d'un
    chemin argv sans validation prealable). Les deux points d'appel, dans
    main(), ne repetent pas ce motif : ils commentent le contrat exit 2 /
    LECTURE_IMPOSSIBLE / SORTIE_IMPOSSIBLE qu'ils font tenir, pas la regle
    SonarCloud elle-meme -- un seul endroit a maintenir pour ce motif, pas
    par numero de ligne, qui se refuterait des la prochaine edition.

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
        if not chemin.parent.exists():
            # repr() (!r), pas str() nu : un chemin argv non-UTF-8 est deja decode avec
            # surrogateescape (PEP 383), donc `chemin` peut porter des surrogates bas
            # (\udcXX) -- str() les laisse tels quels, repr() les echappe. La securite
            # ASCII de STDOUT lui-meme (tout caractere inencodable, pas seulement les
            # surrogates) est assuree une seule fois, au debut de main() -- voir son
            # commentaire pour l'historique (tour 9 -> tour 10) de ce choix.
            raise OSError(f"repertoire de sortie inexistant : {chemin.parent!r}")
        if not chemin.parent.is_dir():
            # Distinct du cas ci-dessus (revue scellee, tour 9) : un parent qui EXISTE
            # mais n'est pas un repertoire (ex. --json-output vers un chemin dont un
            # segment intermediaire est un fichier regulier) rendait le meme message
            # "inexistant", faux -- is_dir() est False dans les deux cas, seule la
            # branche exists() distingue les deux causes reelles.
            raise OSError(f"le parent de la sortie n'est pas un repertoire : {chemin.parent!r}")
        if chemin.exists() and not chemin.is_file():
            raise OSError(f"la cible existe et n'est pas un fichier regulier : {chemin!r}")
    elif chemin.is_dir():
        raise OSError(f"est un repertoire : {chemin!r}")
    return chemin


def main() -> int:
    # Revue scellee (tour 10) : le correctif du tour 9 (formater les TROIS messages
    # construits a la main via ascii() plutot que repr(), pour un chemin argv non-ASCII
    # valide sous PYTHONIOENCODING=ascii) etait REEL mais INCOMPLET, et l'affirmation qui
    # l'accompagnait etait FAUSSE : "les OSError levees par le systeme n'ont jamais ce
    # probleme, leur str() interne repr deja le nom de fichier" -- vrai pour un chemin a
    # surrogates (mesure tour 8/9), FAUX pour un caractere non-ASCII VALIDE (ex. e accentue) :
    # repr() ne l'echappe PAS (seuls les surrogates et non-imprimables le sont), donc le
    # str() d'une FileNotFoundError/NotADirectoryError/PermissionError sur un tel chemin
    # porte le caractere tel quel. print(f"LECTURE_IMPOSSIBLE:{exc}") / SORTIE_IMPOSSIBLE
    # sur CE str()-la, et print("\n".join(errors)) si une CELLULE de la table (pas
    # seulement un chemin argv) porte un tel caractere, levaient donc UnicodeEncodeError
    # non intercepte sous PYTHONIOENCODING=ascii -- exit 1, stdout vide, traceback, le
    # fail-open que ce fichier existe pour fermer, sur des entrees que coordination/
    # README.md enumere lui-meme comme etant EN contrat (chemin inexistant, permission
    # refusee, sortie non inscriptible). Corrige une bonne fois a la source plutot qu'un
    # site d'impression a la fois -- ce que le tour 9 avait fait, en oubliant les sites
    # freres : reconfigurer stdout pour echapper (\xHH/\uHHHH), jamais planter, tout
    # caractere qu'il ne saurait encoder. Sans effet sous UTF-8 (le cas courant : aucun
    # caractere de ce fichier n'est jamais inencodable en UTF-8, mesure). !a redevient
    # inutile aux sites de _chemin_sur() ou il avait ete introduit au tour 9 -- revenu a
    # !r (repr(), plus lisible) pour ces sites-la (pas de decompte fige ici, `diff -u`
    # contre le pack restant la seule source qui ne devient jamais fausse en silence --
    # un grep suggere ICI pour les compter se compterait lui-meme, mesure : ce piege
    # precis a failli se reproduire au tour 12), la protection reelle vivant ici desormais, une seule fois, pour
    # tous les points d'impression de cette fonction sans exception.
    #
    # Regression introduite PAR ce correctif, fermee au tour 11 (revue scellee, 2 sieges
    # convergents) : reconfigure() est la toute premiere instruction de main(), or CPython
    # met sys.stdout a None quand le descripteur de sortie standard est deja ferme au
    # lancement (`... >&-`) -- reconfigure() levait alors AttributeError, non intercepte :
    # exit 1 + traceback, stdout vide, EXACTEMENT le fail-open que ce fichier existe pour
    # fermer, sur une entree qui ne l'atteignait pas avant ce commit (print() sur un flux
    # clos ne leve rien -- mesure sur les quatre print() de cette fonction, contre-epreuve
    # faite en retirant cette ligne). La garde ci-dessous restaure ce silence : rien a
    # reconfigurer quand il n'y a pas de flux, et rien de plus a faire.
    if sys.stdout is not None:
        sys.stdout.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser()
    parser.add_argument("ownership")
    parser.add_argument("--json-output")
    args = parser.parse_args()
    try:
        chemin_entree = _chemin_sur(args.ownership)
        data, errors = validate(chemin_entree)
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
            # Fail-open trouve en revue scellee (tour 9, elargi tour 10) : --json-output
            # pointant sur le MEME fichier que `ownership` (faute de frappe la plus simple)
            # rendait exit 0 / COORDINATION_OK en silence, apres avoir ECRASE la table qui
            # venait d'etre validee par le JSON de son propre resultat -- destruction
            # silencieuse, meme famille que celle documentee pour .claude/settings.json.
            # La seule egalite de Path (tour 9) attrape le meme chemin resolu -- lien
            # symbolique compris, deja aplati par _chemin_sur() -- mais pas un lien
            # PHYSIQUE (hardlink) : un second nom pour la meme inode, chemin different,
            # meme fichier. Mesure (tour 10) : --json-output vers un hardlink de
            # `ownership` -> exit 0, table source silencieusement reduite au JSON. Ferme
            # par identite de fichier (samefile(), stat (st_dev, st_ino)) en plus de
            # l'egalite de chemin -- `chemin_sortie` n'existe pas forcement encore, d'ou
            # la garde `exists()` avant `samefile()` (qui exige que les deux existent).
            if chemin_sortie == chemin_entree or (
                chemin_sortie.exists() and chemin_sortie.samefile(chemin_entree)
            ):
                raise OSError("la sortie --json-output ecraserait le fichier ownership lui-meme")
            chemin_sortie.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except OSError as exc:
            # Meme raison que ci-dessus : sans interception, une table lue ET conforme
            # rendait quand meme exit 1 (traceback) si --json-output n'etait PAS inscriptible
            # -- ou, depuis ce commit, si --json-output visait la table elle-meme.
            print(f"SORTIE_IMPOSSIBLE:{exc}")
            return 2
    if errors:
        print("\n".join(errors))
        return 1
    print(f"COORDINATION_OK rows={result['rows']} active={result['active']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

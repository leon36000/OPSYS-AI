# Tests de tools/check_coordination.py (issue AUD-QUAL-006, #592) — pas une énumération
# exhaustive de tout comportement du validateur (ex. le refus d'un octet nul dans le chemin
# argv n'a, lui, aucun test dédié : intestable au niveau CLI déclaré, execve/Python refusant
# un tel octet embarqué avant même le lancement du script — mesuré ; de même, les deux
# `.rstrip("/")` d'`overlaps()`, sur ses deux opérandes, n'ont aucune fixture dédiée —
# redondants avec `PurePosixPath` pour tout scope VALIDE, qui normalise déjà une barre
# oblique finale ; la seule graphie qui les rend observables, un scope entièrement composé
# de `/`, est de toute façon déjà refusée par `valid_scope()` avant que la collision
# n'entre en jeu — mesuré en revue scellée, tours 10 et 11 de #598, 4 sièges convergents
# sur 6, aucun ne rendant un faux COORDINATION_OK), mais chaque durcissement
# de la revue scellée qui a produit ce fichier (PR #564, 14 tours), AU NIVEAU DU CONTRAT CLI
# qu'il fait tenir — certains durcissements de `_chemin_sur()` partagent un même
# préfixe/exit avec un autre chemin de code (contrat préservé, message interne distinct non
# épinglé, mesuré en revue scellée : PAS le cas de la boucle de liens symboliques ni du FIFO
# nommé ci-dessous, dont le contrat CHANGE réellement sans test dédié — les deux en portent
# un) — ET chaque contrôle de ligne hérité du pack encore vivant dans le validateur réduit
# (MALFORMED_ROW, WORK_ID_EMPTY, DUPLICATE_WORK, OWNER, STATUS, BRANCH, CORE_OWNER,
# ISSUE_OWNER — mesurés par mutation en revue scellée, tour 1 de #598 : aucun test dédié
# avant ce commit, malgré une revendication de couverture ici même qui les omettait).
# `coordination/CLAUDE-STATUS.md` garde le détail narratif des durcissements, ce fichier en
# garde la preuve rejouable. Invocation en subprocess réel (comme
# scripts/tests/test_methode.py) : ce qui compte ici est le contrat CLI — exit code + préfixe
# sur stdout — pas l'appel direct des fonctions internes. Précision (AUD-QUAL-008, #600 ;
# étendue en AUD-QUAL-010, #604) : les fixtures dont le nom commence par `test_ordre_`
# (désignation par motif de nom, pas par décompte — un décompte figé serait faux à la
# prochaine addition, cf. coordination/README.md) épinglent en outre l'ORDRE RELATIF de
# plusieurs lignes d'erreur par égalité EXACTE de `stdout.splitlines()` (pas seulement
# leur préfixe ou leur présence) —
# ATTENTION, auto-contradiction corrigée en revue scellée (tour 2 de #601, siège 2) : une
# première version de cette phrase rangeait « les paires de _erreurs_de_collision() » parmi
# l'ordre NON épinglé, alors que l'ordre INTERNE à UNE paire (BRANCH_COLLISION avant
# PATH_COLLISION, dans `_erreurs_de_paire()`) EST épinglé en bonus par
# `test_ordre_erreurs_de_ligne_avant_erreurs_de_collision` (désignée par NOM, pas par
# position — un test inséré entre les fixtures d'ordre ci-dessous ne doit pas périmer ce
# renvoi silencieusement) — contredisant, dans le même commit, le commentaire de ce test-là.
# Précisément :
# l'ordre INTERNE à chaque groupe de contrôles PAR LIGNE (`_erreurs_structurelles()`,
# `_erreurs_de_propriete()`) reste hors contrat, non épinglé par ce fichier à ce jour — SAUF
# une relation, épinglée en bonus depuis AUD-QUAL-011 (#605) par
# `test_ordre_structurel_avant_propriete_avec_deux_erreurs_structurelles` : OWNER précède
# STATUS dans `_erreurs_structurelles()` (mesuré : les échanger fait rougir CE test, et lui
# seul). Ni les quatre autres contrôles de ce groupe (WORK_ID_EMPTY, DUPLICATE_WORK, SCOPE,
# BRANCH), ni aucun de `_erreurs_de_propriete()`, n'en sont concernés — mesuré : déplacer SCOPE
# ou BRANCH, ou échanger MODULE_CODE_DURING_CORE et CORE_OWNER, laisse la suite entière verte.
# Il en va de même pour l'ordre ENTRE plusieurs paires distinctes lorsque `_erreurs_de_collision()`
# en traite plus d'une (mesuré : inverser l'ordre de parcours des paires sur une table à 3
# lignes actives change l'ordre des blocs émis sans faire rougir aucun test). ATTENTION,
# sur-généralisation corrigée en revue scellée (tour 3 de #601, siège 2 ; reformulée tour 4,
# sièges 1/2/3 convergents) : une version précédente de cette phrase affirmait que « l'ordre
# INTERNE à _erreurs_de_paire() lui-même EST épinglé » sans réserve — faux, mesuré par
# contre-exemple direct. Seule UNE relation interne à cette fonction est réellement épinglée
# par `test_ordre_erreurs_de_ligne_avant_erreurs_de_collision`, et seulement à l'arité
# qu'elle exerce (une seule ligne
# PATH_COLLISION) : BRANCH_COLLISION précède la PATH_COLLISION de la paire. L'ordre RELATIF
# entre PLUSIEURS lignes PATH_COLLISION d'une même paire reste, lui, hors contrat — mesuré :
# il suffit qu'un item d'un SEUL côté recouvre plusieurs items de l'autre (scope multi-items
# séparés par « ; » — un seul côté suffit, pas nécessairement les deux) pour qu'inverser le
# parcours des listes d'items dans `_erreurs_de_paire()` change l'ordre des PATH_COLLISION
# émis (ex. mesuré : « coordination;tools » des deux côtés, les deux lignes PATH_COLLISION
# échangent leur position) sans faire rougir aucun test. Liste NON EXHAUSTIVE des ordres
# hors contrat ci-dessus : le groupement des blocs d'erreur PAR LIGNE (ordre entre lignes
# distinctes) et la position de HEADER_MISSING/MALFORMED_ROW n'y figurent pas non plus,
# et ne sont pas davantage revendiqués comme épinglés ailleurs dans ce fichier.
#
# Précision (AUD-QUAL-010, #604 ; revue scellée, tour 1 de #603, siège 2) : jusqu'ici, la
# relation ligne-avant-paire n'était épinglée que lorsque la ligne en erreur est elle-même
# membre de la paire concernée (cas de
# `test_ordre_erreurs_de_ligne_avant_erreurs_de_collision` ci-dessous).
# `test_ordre_ligne_avant_paire_quand_la_ligne_en_erreur_est_hors_de_la_paire` couvre en
# outre le cas où elle ne l'est PAS : une ligne hors de toute collision (ici hors de
# l'ensemble ACTIVE : statut MERGED), positionnée après une paire dans la table. Un
# entrelacement qui émettrait, pour chaque ligne, ses erreurs PUIS les paires dont elle
# est membre DROIT laissait ce cas-là vert avant ce test. Ni
# `test_ordre_erreurs_de_ligne_avant_erreurs_de_collision` ni ce test ne prétendent
# épuiser toutes les stratégies d'entrelacement possibles entre boucle par ligne et
# boucle par paire — au moins les deux stratégies mesurées ici sont effectivement
# exclues par ces deux fixtures.
#
# Lancer seul : python3 -m pytest coordination/tests/ (hors testpaths par défaut de
# pytest.ini — dont le contenu exact n'est pas recopié ici, voir coordination/README.md).
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent.parent / "tools" / "check_coordination.py"

HEADER = "| Work ID | Owner | Branch | Path scope | Status | Updated UTC | Next |\n"
SEP = "|---|---|---|---|---|---|---|\n"


def run(args, **kw):
    return subprocess.run(
        [sys.executable, "-B", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        **kw,
    )


def row(work_id="ISS-A", owner="CLAUDE", branch="br-a", scope="coordination",
        status="ACTIVE", updated="2026-01-01T00:00Z", next_="x"):
    return f"| {work_id} | {owner} | {branch} | {scope} | {status} | {updated} | {next_} |\n"


def table(*rows, header=True):
    out = (HEADER + SEP) if header else ""
    return out + "".join(rows)


def write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Chemin heureux et HEADER_MISSING (mandat #592, points 1-2)
# ---------------------------------------------------------------------------

def test_chemin_heureux_coordination_ok(tmp_path):
    p = write(tmp_path, "t.md", table(
        row(),
        row(work_id="ISS-B", branch="br-b", scope="tools"),
    ))
    r = run([str(p)])
    assert r.returncode == 0
    assert r.stdout.strip() == "COORDINATION_OK rows=2 active=2"


def test_gabarit_vide_legitime_rows_zero(tmp_path):
    # En-tête + séparateur, zéro ligne de données : un gabarit neuf, pas une table
    # tronquée — doit rester vert (plancher de non-vacuité, cf. HEADER_MISSING ci-dessous).
    p = write(tmp_path, "t.md", table())
    r = run([str(p)])
    assert r.returncode == 0
    assert r.stdout.strip() == "COORDINATION_OK rows=0 active=0"


def test_header_missing_sur_fichier_sans_table(tmp_path):
    p = write(tmp_path, "t.md", "Pas une table, juste de la prose.\n")
    r = run([str(p)])
    assert r.returncode == 1
    assert "HEADER_MISSING" in r.stdout


def test_header_missing_sur_en_tete_sans_vraie_separation(tmp_path):
    # L'en-tête cité en prose (sans séparateur GFM juste après) ne doit pas compter
    # comme une table réelle — fail-open du pack fermé par ce contrôle.
    p = write(tmp_path, "t.md", HEADER + "Du texte, pas un séparateur.\n")
    r = run([str(p)])
    assert r.returncode == 1
    assert "HEADER_MISSING" in r.stdout


def test_header_missing_sur_fichier_tronque_a_len_lines(tmp_path):
    # La borne `lineno < len(lines)` du lookahead de séparateur (parse_rows()) n'avait
    # aucune fixture avant ce correctif (revue scellée, tour 8 de #598, siège 1) :
    # aucune table construite dans ce fichier ne place la ligne d'en-tête en DERNIÈRE
    # ligne. Mesuré : muter cette borne en `<=` laisse les tests d'alors verts tout en
    # rendant stdout VIDE (IndexError non interceptée) au lieu du préfixe HEADER_MISSING
    # que ce fichier déclare pourtant comme faisant partie du contrat testé — le cas
    # exact du « fichier tronqué » que le commentaire HEADER_MISSING du validateur nomme
    # lui-même. Fail-closed (exit 1 dans les deux cas, jamais un faux COORDINATION_OK),
    # mais un traceback remplacerait silencieusement le préfixe attendu.
    p = write(tmp_path, "t.md", HEADER.rstrip("\n"))  # en-tête seul, aucune ligne suivante
    r = run([str(p)])
    assert r.returncode == 1
    assert r.stdout.strip() == "HEADER_MISSING"
    assert r.stderr == ""


def test_separateur_indente_juste_apres_len_tete_reste_reconnu(tmp_path):
    # `lines[lineno].strip()` — le lookahead qui décide si la ligne suivant l'en-tête
    # est une vraie séparation — n'avait aucune fixture avant ce correctif (revue
    # scellée, tour 8 de #598, siège 3) : mesuré, muter en `lines[lineno]` (sans
    # `.strip()`) laisse les tests d'alors verts tout en faisant passer un séparateur
    # GFM INDENTÉ juste après l'en-tête de COORDINATION_OK à HEADER_MISSING — fail-closed
    # (jamais un faux COORDINATION_OK), même famille que
    # test_ligne_de_donnees_indentee_reste_validee ci-dessous pour les lignes de DONNÉES.
    p = write(tmp_path, "t.md", HEADER + "  " + SEP + "| ISS-A | CLAUDE | br-a | coordination | ACTIVE | x | y |\n")
    r = run([str(p)])
    assert r.returncode == 0
    assert r.stdout.strip() == "COORDINATION_OK rows=1 active=1"


def test_separator_re_ne_confond_pas_une_ligne_de_donnees_avec_un_separateur(tmp_path):
    # Une ligne de DONNÉES dont la première cellule commence par "---" (Work ID "---X")
    # ne doit pas être prise pour une ligne de séparation et silencieusement exclue.
    #
    # Fixture écrite en LITTÉRAL, pas via row() : row() insère toujours un espace après
    # le pipe de tête ("| ---X | ..."), qui à lui seul évite déjà le regex vulnérable
    # d'avant #564 (`^\|---`, collé au pipe) — un test construit avec row() reste vert
    # que SEPARATOR_RE soit le motif entier corrigé ou l'ancien préfixe nu, donc ne
    # protège RIEN de ce fail-open précis (faux positif de couverture trouvé en revue
    # scellée, tour 1 de #598, mesuré par mutation avant correction). Seule la graphie
    # SANS espace ("|---X | ...", celle du commentaire historique de
    # tools/check_coordination.py) discrimine réellement les deux versions du motif.
    p = write(tmp_path, "t.md",
              HEADER + SEP + "|---X | NATHAN | main | modules m/M7 | ACTIVE | 2026-01-01T00:00Z | x |\n")
    r = run([str(p)])
    assert r.returncode == 1
    assert "MODULE_CODE_DURING_CORE:---X" in r.stdout


def test_separator_re_epingle_lancre_de_fin_et_les_deux_quantificateurs(tmp_path):
    # Pendant du test ci-dessus, jamais exercé avant ce correctif (revue scellée, tour 7
    # de #598, sièges 1/2/3 convergents — seule la sévérité diverge, MAJEURE au siège 1) :
    # SEPARATOR_RE = ^\|(-+\|)+$ n'était épinglé QUE sur son préfixe nu, jamais sur son
    # ancre "$" ni sur son quantificateur INTERNE "-+". Le Work ID "---X" ci-dessus a un
    # caractère APRÈS les tirets ; il ne discrimine donc ni l'un ni l'autre. Mesuré :
    # retirer "$" laisse les 60 tests d'alors verts tout en rendant un faux
    # COORDINATION_OK RÉEL — une ligne de donnée dont la PREMIÈRE cellule est
    # uniquement des tirets collés au pipe, le RESTE de la ligne dans la graphie
    # espacée normale du dépôt, passe de "BRANCH:---" + "MODULE_CODE_DURING_CORE:---"
    # exit 1 à "COORDINATION_OK rows=0 active=0" exit 0 : la ligne entière est
    # escamotée, interdit dur de l'ADR-0004 compris. Retirer "-+" (muté en "-*") laisse
    # pareillement passer une ligne dégénérée faite de pipes seuls de MALFORMED_ROW:3:1
    # à COORDINATION_OK. Classé non bloquant par 2 sièges sur 3 (la graphie
    # déclenchante — Work ID composé uniquement de tirets, ou ligne de pipes nus —
    # n'existe dans aucune table réelle de ce dépôt), mais fermé ici plutôt que reporté
    # une nouvelle fois : même famille que les six tours précédents, sur la regex à
    # laquelle ce fichier consacre déjà son plus long commentaire.
    p = write(tmp_path, "t.md",
              HEADER + SEP + "|---| NATHAN | main | modules m/M7 | ACTIVE | 2026-01-01T00:00Z | x |\n")
    r = run([str(p)])
    assert r.returncode == 1
    assert "BRANCH:---" in r.stdout
    assert "MODULE_CODE_DURING_CORE:---" in r.stdout

    p2 = write(tmp_path, "t2.md", HEADER + SEP + "|||||||\n")
    r2 = run([str(p2)])
    assert r2.returncode == 1
    assert "MALFORMED_ROW:3:1" in r2.stdout

    # Quantificateur EXTERNE (le groupe "(-+\|)+" lui-même, distinct du "-+" interne
    # ci-dessus) — trouvé UNANIME par les trois sièges du tour 10, seul survivant à
    # transition exit 1 -> exit 0 de leurs trois campagnes indépendantes : le nom
    # (« le quantificateur », au singulier) et la fixture ci-dessus ne discriminaient que
    # l'interne, jamais l'externe. Mesuré : muter "(-+\|)+$" en "(-+\|)*$" laisse les 67
    # tests d'alors verts, tout en faisant passer une ligne de DONNÉE réduite à un pipe
    # unique (0 répétition du groupe, donc matché par le "*" mais pas par le "+") de
    # "MALFORMED_ROW:3:1" à "COORDINATION_OK rows=0 active=0" — un vrai faux vert, mais
    # sur une ligne qui ne porte aucune donnée de travail, contrairement au cas de "$".
    p3 = write(tmp_path, "t3.md", HEADER + SEP + "|\n")
    r3 = run([str(p3)])
    assert r3.returncode == 1
    assert "MALFORMED_ROW:3:1" in r3.stdout


def test_separateur_espace_reste_non_reconnu_fail_closed(tmp_path):
    # Limite héritée du pack, documentée dans coordination/README.md, pas fermée ici :
    # un séparateur espacé n'est pas reconnu — mais le résultat est fail-closed (des
    # erreurs parasites, jamais un faux COORDINATION_OK), pas un fail-open.
    p = write(tmp_path, "t.md", HEADER + "| --- | --- | --- | --- | --- | --- | --- |\n")
    r = run([str(p)])
    assert r.returncode == 1
    assert "HEADER_MISSING" in r.stdout


def test_ligne_de_donnees_indentee_reste_validee(tmp_path):
    # `raw.strip()` de parse_rows() (avant le test `line.startswith("|")`) sans test
    # dédié jusqu'ici, signalé deux fois comme non bloquant (revue scellée, tours 4 et 5
    # de #598) : sans lui, une ligne de DONNÉES précédée d'espaces cesserait d'être
    # reconnue comme ligne de table — collisions et interdit dur de l'ADR-0004 compris,
    # silencieusement. GFM lui-même ne distingue pas une ligne de table indentée d'une
    # autre ; ce contrôle affirme que ce fichier non plus.
    p = write(tmp_path, "t.md", HEADER + SEP + "  | ISS-A | CLAUDE | br-a | modules m | ACTIVE | x | y |\n")
    r = run([str(p)])
    assert r.returncode == 1
    assert "MODULE_CODE_DURING_CORE:ISS-A" in r.stdout


# ---------------------------------------------------------------------------
# overlaps() — normalisation casse + séparateur (mandat #592, point 3)
# ---------------------------------------------------------------------------

def test_overlaps_normalise_la_casse(tmp_path):
    # Fail-open du pack fermé : "Coordination" vs "coordination" est une vraie collision,
    # une comparaison de chaîne brute la manquait. Les DEUX ordres de déclaration sont
    # exercés (revue scellée, tour 4 de #598, renvoi par nom plutôt que par numéro de
    # ligne — doctrine du fichier livré, cf. son propre docstring) : `overlaps(a, b)`
    # normalise séparément chaque opérande — un seul ordre ne teste que la moitié gauche
    # de cette paire de normalisations, comme l'a révélé la disjonction de parenté au
    # tour 3 pour un mécanisme voisin.
    p_gauche_anormale = write(tmp_path, "gauche_anormale.md", table(
        row(work_id="ISS-A", branch="br-a", scope="Coordination"),
        row(work_id="ISS-B", branch="br-b", scope="coordination"),
    ))
    r = run([str(p_gauche_anormale)])
    assert r.returncode == 1
    assert "PATH_COLLISION:ISS-A:ISS-B:Coordination:coordination" in r.stdout

    p_droite_anormale = write(tmp_path, "droite_anormale.md", table(
        row(work_id="ISS-A", branch="br-a", scope="coordination"),
        row(work_id="ISS-B", branch="br-b", scope="Coordination"),
    ))
    r = run([str(p_droite_anormale)])
    assert r.returncode == 1
    assert "PATH_COLLISION:ISS-A:ISS-B:coordination:Coordination" in r.stdout


def test_path_collision_sur_cellule_multi_items_avec_espace(tmp_path):
    # Même famille de faux positif de couverture que le test MODULE_CODE_DURING_CORE
    # voisin (revue scellée, tour 3 de #598, complétée tour 4) : sans .strip() après le
    # découpage sur ";", une collision réelle entre "tools" et un item "tools" niché dans
    # une cellule multi-items ESPACÉE ("coordination; tools") passait inaperçue — item
    # extrait " tools" (espace de tête compris) jamais égal à "tools" sans normalisation.
    # DEUX sites distincts portent ce .strip() dans la boucle PATH_COLLISION (`sa` à
    # gauche, `sb` à droite) : le tour 3 n'avait fermé que le premier, le second (`sb`)
    # restait un mutant survivant réel sur la graphie qu'emploie, à ce jour, la seule
    # table réelle de ce dépôt.
    p_gauche_espacee = write(tmp_path, "gauche_espacee.md", table(
        row(work_id="ISS-A", branch="br-a", scope="coordination; tools"),
        row(work_id="ISS-B", branch="br-b", scope="tools"),
    ))
    r = run([str(p_gauche_espacee)])
    assert r.returncode == 1
    assert "PATH_COLLISION:ISS-A:ISS-B:tools:tools" in r.stdout

    p_droite_espacee = write(tmp_path, "droite_espacee.md", table(
        row(work_id="ISS-A", branch="br-a", scope="tools"),
        row(work_id="ISS-B", branch="br-b", scope="coordination; tools"),
    ))
    r = run([str(p_droite_espacee)])
    assert r.returncode == 1
    assert "PATH_COLLISION:ISS-A:ISS-B:tools:tools" in r.stdout


def test_overlaps_normalise_le_separateur_antislash(tmp_path):
    # Les deux ordres de déclaration sont exercés, même raison que le test de casse
    # voisin (revue scellée, tour 4 de #598).
    p_gauche_anormale = write(tmp_path, "gauche_anormale.md", table(
        row(work_id="ISS-A", branch="br-a", scope="coordination\\sub"),
        row(work_id="ISS-B", branch="br-b", scope="coordination/sub"),
    ))
    r = run([str(p_gauche_anormale)])
    assert r.returncode == 1
    assert "PATH_COLLISION:ISS-A:ISS-B:coordination\\sub:coordination/sub" in r.stdout

    p_droite_anormale = write(tmp_path, "droite_anormale.md", table(
        row(work_id="ISS-A", branch="br-a", scope="coordination/sub"),
        row(work_id="ISS-B", branch="br-b", scope="coordination\\sub"),
    ))
    r = run([str(p_droite_anormale)])
    assert r.returncode == 1
    assert "PATH_COLLISION:ISS-A:ISS-B:coordination/sub:coordination\\sub" in r.stdout


def test_overlaps_detecte_la_parente_dans_les_deux_sens(tmp_path):
    # Sans test avant le tour 2 de #598 (mutant survivant) : retirer "pb in pa.parents"
    # de overlaps() laissait le cas ENFANT-PUIS-PARENT passer inaperçu. Mais le nom de
    # CE test promettait "les deux sens" sans exercer l'autre moitié — un test qui se
    # nomme "dans les deux sens" et n'en exerce qu'un seul, contrôle réel non tenu (revue
    # scellée, tour 3 de #598) : retirer "pa in pb.parents" laissait alors le cas
    # PARENT-PUIS-ENFANT (l'ordre le plus naturel de rédaction d'une table) passer
    # inaperçu SANS faire échouer ce test-là non plus. Les deux fixtures ci-dessous
    # exercent chacune un seul disjoint de `overlaps()` ; retirer l'un ou l'autre fait
    # échouer une des deux, jamais les deux à la fois.
    p_enfant_puis_parent = write(tmp_path, "enfant_puis_parent.md", table(
        row(work_id="ISS-A", branch="br-a", scope="coordination/sub"),
        row(work_id="ISS-B", branch="br-b", scope="coordination"),
    ))
    r = run([str(p_enfant_puis_parent)])
    assert r.returncode == 1
    assert "PATH_COLLISION:ISS-A:ISS-B:coordination/sub:coordination" in r.stdout

    p_parent_puis_enfant = write(tmp_path, "parent_puis_enfant.md", table(
        row(work_id="ISS-A", branch="br-a", scope="coordination"),
        row(work_id="ISS-B", branch="br-b", scope="coordination/sub"),
    ))
    r = run([str(p_parent_puis_enfant)])
    assert r.returncode == 1
    assert "PATH_COLLISION:ISS-A:ISS-B:coordination:coordination/sub" in r.stdout


def test_overlaps_ne_developpe_aucun_glob(tmp_path):
    # Documenté comme limite assumée : "**" est un composant de chemin ordinaire, pas
    # un joker — deux scopes qui ne collisionneraient QUE via une sémantique de glob
    # restent verts.
    p = write(tmp_path, "t.md", table(
        row(work_id="ISS-A", branch="br-a", scope=".github/workflows/**"),
        row(work_id="ISS-B", branch="br-b", scope=".github/workflows/ci.yml"),
    ))
    r = run([str(p)])
    assert r.returncode == 0


def test_overlaps_exemption_scopes_hors_collision(tmp_path):
    # SCOPES_HORS_COLLISION = {"read-only", "task spec exact"} n'avait aucun test dédié
    # avant ce correctif (revue scellée, tour 6 de #598) — la seule couverture incidente
    # (deux lignes "read-only" pour BRANCH_COLLISION) porte les DEUX opérandes exemptés à
    # la fois, donc ne discrimine ni l'un ni l'autre pris séparément. "read-only" et
    # "read-only/sub" ont une vraie relation parent-enfant au sens PurePosixPath — SANS
    # l'exemption, ces deux lignes collisionneraient réellement (mesuré par mutation).
    # Les deux ordres de déclaration sont exercés, plus le second membre du set.
    p_gauche_exemptee = write(tmp_path, "gauche_exemptee.md", table(
        row(work_id="ISS-A", branch="br-a", scope="read-only"),
        row(work_id="ISS-B", branch="br-b", scope="read-only/sub"),
    ))
    r = run([str(p_gauche_exemptee)])
    assert r.returncode == 0

    p_droite_exemptee = write(tmp_path, "droite_exemptee.md", table(
        row(work_id="ISS-A", branch="br-a", scope="read-only/sub"),
        row(work_id="ISS-B", branch="br-b", scope="read-only"),
    ))
    r = run([str(p_droite_exemptee)])
    assert r.returncode == 0

    p_task_spec = write(tmp_path, "task_spec.md", table(
        row(work_id="ISS-A", branch="br-a", scope="task spec exact"),
        row(work_id="ISS-B", branch="br-b", scope="task spec exact"),
    ))
    r = run([str(p_task_spec)])
    assert r.returncode == 0


# ---------------------------------------------------------------------------
# Contrôles de ligne hérités du pack, jamais touchés par la revue scellée de #564 mais
# toujours vivants dans le validateur réduit — sans test dédié avant ce correctif (revue
# scellée, tour 1 de #598 : mesuré par mutation, aucun des huit ne fait échouer les 32
# tests d'origine si on le retire, alors que l'en-tête de ce fichier prétendait couvrir
# « un contrôle par comportement réellement conservé »).
# ---------------------------------------------------------------------------

def test_malformed_row_compte_de_cellules(tmp_path):
    p = write(tmp_path, "t.md", HEADER + SEP + "| ISS-A | CLAUDE | br-a | coordination | ACTIVE | x |\n")
    r = run([str(p)])
    assert r.returncode == 1
    assert "MALFORMED_ROW:3:6" in r.stdout  # 3 = numéro de ligne, 6 = nombre de cellules


def test_malformed_row_borne_haute_egalement(tmp_path):
    # Pendant de la borne basse ci-dessus, jamais exercé avant ce correctif (revue
    # scellée, tour 6 de #598, siège 1) : "len(cells) != 7" n'a qu'un seul mutant
    # testé (6 cellules). Muter en "len(cells) < 7" laissait les tests d'alors verts —
    # une ligne à 8 cellules aurait alors été acceptée et validée sur ses 7 premières
    # seulement (zip() tronque en silence), fail-open sur un contrôle que l'en-tête
    # revendique couvrir.
    p = write(tmp_path, "t.md",
              HEADER + SEP + "| ISS-A | CLAUDE | br-a | coordination | ACTIVE | x | y | EXTRA |\n")
    r = run([str(p)])
    assert r.returncode == 1
    assert "MALFORMED_ROW:3:8" in r.stdout


def test_work_id_empty(tmp_path):
    p = write(tmp_path, "t.md", table(row(work_id="")))
    r = run([str(p)])
    assert r.returncode == 1
    assert "WORK_ID_EMPTY" in r.stdout


def test_duplicate_work(tmp_path):
    p = write(tmp_path, "t.md", table(
        row(work_id="ISS-A", branch="br-a", scope="coordination"),
        row(work_id="ISS-A", branch="br-b", scope="tools"),
    ))
    r = run([str(p)])
    assert r.returncode == 1
    assert "DUPLICATE_WORK:ISS-A" in r.stdout


def test_owner_invalide(tmp_path):
    # Work ID "XYZ-1" volontairement hors de CORE_RE et CLAUDE_RE (ne commence ni par
    # "C<0-24>-", ni par "ISS-"/"AUD-"/"BUG-"/"R4-") pour isoler ce seul contrôle — un
    # Work ID "ISS-*" déclencherait aussi ISSUE_OWNER pour le même owner invalide.
    p = write(tmp_path, "t.md", table(row(work_id="XYZ-1", owner="BADOWNER")))
    r = run([str(p)])
    assert r.returncode == 1
    assert "OWNER:XYZ-1:BADOWNER" in r.stdout


def test_status_invalide(tmp_path):
    p = write(tmp_path, "t.md", table(row(status="BADSTATUS")))
    r = run([str(p)])
    assert r.returncode == 1
    assert "STATUS:ISS-A:BADSTATUS" in r.stdout


def test_owners_legitimes_acceptes(tmp_path):
    # Pendant positif de test_owner_invalide, jamais exercé avant ce correctif (revue
    # scellée, tour 6 de #598, siège 1) : retirer "NATHAN", "CHATGPT" ou "UNASSIGNED" de
    # OWNERS = {"CODEX","CLAUDE","CHATGPT","NATHAN","UNASSIGNED"} laissait les tests
    # d'alors verts, faute d'une ligne affirmant chacun accepté. Work ID "XYZ-1" (même
    # raison que test_owner_invalide : hors CORE_RE et CLAUDE_RE) pour isoler ce seul
    # contrôle, CODEX et CLAUDE compris — sans lui, une valeur qui échappe pourtant à
    # OWNERS déclencherait quand même CORE_OWNER/ISSUE_OWNER pour la même mauvaise raison.
    for owner in ("CODEX", "CLAUDE", "CHATGPT", "NATHAN", "UNASSIGNED"):
        p = write(tmp_path, "t.md", table(row(work_id="XYZ-1", owner=owner)))
        r = run([str(p)])
        assert r.returncode == 0, owner
        assert "OWNER:" not in r.stdout, owner


def test_statuses_legitimes_acceptees(tmp_path):
    # Même pendant positif que ci-dessus, pour STATUSES = {"QUEUED","ACTIVE","BLOCKED",
    # "REVIEW","READY_TO_MERGE","MERGED","TRANSFER"} — retirer "BLOCKED" ou "MERGED"
    # laissait les tests d'alors verts (revue scellée, tour 6 de #598, sièges 1 et 3
    # convergents), alors que coordination/WORK-OWNERSHIP.md porte aujourd'hui des
    # lignes réelles dans ces deux statuts — référence datée (revue scellée, tour 8 de
    # #598, siège 2) : peut changer de statut à tout merge ordinaire, seul l'invariant
    # que STATUSES accepte les deux est stable. Branch "br-a" (jamais "main"/"master"/
    # vide) pour ne pas laisser BRANCH:ISS-A interférer sur les statuts actifs de la
    # boucle.
    for status in ("QUEUED", "ACTIVE", "BLOCKED", "REVIEW", "READY_TO_MERGE", "MERGED", "TRANSFER"):
        p = write(tmp_path, "t.md", table(row(status=status, branch="br-a")))
        r = run([str(p)])
        assert r.returncode == 0, status
        assert "STATUS:" not in r.stdout, status


def test_branch_main_ou_master_ou_vide_sur_ligne_active(tmp_path):
    # Le nom promet aussi le cas "vide" : sans lui, retirer "" de l'ensemble de refus
    # {"main", "master", ""} du validateur laissait ce test vert (mutant survivant,
    # trouvé en revue scellée, tour 2 de #598) alors que le comportement réel change.
    for branch in ("main", "master", "MAIN", ""):
        p = write(tmp_path, "t.md", table(row(branch=branch)))
        r = run([str(p)])
        assert r.returncode == 1, repr(branch)
        assert "BRANCH:ISS-A" in r.stdout, repr(branch)


def test_branch_arme_seulement_sur_ligne_active(tmp_path):
    # Pendant, pour ce contrôle, de test_module_code_during_core_arme_seulement_sur_
    # ligne_active plus bas : "status in ACTIVE" garde aussi BRANCH, jamais exercé avant
    # ce correctif (revue scellée, tour 6 de #598, siège 3) — la retirer survivait aux
    # tests d'alors faute d'une ligne QUEUED à branche "main" affirmée COORDINATION_OK.
    p = write(tmp_path, "t.md", table(row(branch="main", status="QUEUED")))
    r = run([str(p)])
    assert r.returncode == 0
    assert "BRANCH:ISS-A" not in r.stdout


def test_core_owner_hors_codex(tmp_path):
    # CORE_RE = ^C(?:0\d|1\d|2[0-4])-\d{3}$ porte TROIS alternatives de décennie — sans
    # ce test avant ce correctif (revue scellée, tour 6 de #598), seule 0\d était
    # exercée. Mesuré : retirer 1\d ou 2[0-4] de CORE_RE laissait les tests d'alors verts
    # tout en produisant un COORDINATION_OK à tort sur C15-.../C23-..., un fail-open réel
    # (pas seulement une asymétrie de couverture) sur le contrôle même que l'en-tête du
    # fichier revendique avoir fermé « mesuré par mutation ».
    for work_id in ("C05-001", "C15-001", "C23-001"):
        p = write(tmp_path, "t.md", table(row(work_id=work_id, owner="CLAUDE", scope="core/x")))
        r = run([str(p)])
        assert r.returncode == 1, work_id
        assert f"CORE_OWNER:{work_id}:CLAUDE" in r.stdout, work_id


def test_issue_owner_hors_claude(tmp_path):
    # CLAUDE_RE = ^(?:ISS-|AUD-|BUG-|R4-) porte QUATRE alternatives — même famille et
    # même gravité que le test CORE_OWNER voisin (revue scellée, tour 6 de #598) : seule
    # ISS- était exercée avant ce correctif, alors qu'AUD- est le préfixe qui DOMINE la
    # seule table réellement validée de ce dépôt (coordination/WORK-OWNERSHIP.md :
    # AUD-CI-002/003/004, AUD-CORE-005/006, AUD-CANON-001/002 — référence datée, comme
    # celle de test_module_code_during_core_cellule_multiple_avec_espace plus bas :
    # cette énumération peut changer d'identifiant ou de statut à tout merge ordinaire,
    # y compris depuis l'autre plateforme ; seul l'invariant qu'elle sert à justifier —
    # AUD- est un préfixe réellement porté par la table de ce dépôt — est stable).
    # Mesuré : retirer AUD-, BUG- ou R4- de CLAUDE_RE laissait les tests d'alors verts
    # tout en produisant un COORDINATION_OK à tort sur un Work ID de ce préfixe possédé
    # par CODEX.
    for work_id in ("ISS-A", "AUD-CORE-005", "BUG-001", "R4-001"):
        p = write(tmp_path, "t.md", table(row(work_id=work_id, owner="CODEX")))
        r = run([str(p)])
        assert r.returncode == 1, work_id
        assert f"ISSUE_OWNER:{work_id}:CODEX" in r.stdout, work_id


def test_core_et_issue_owner_transfer_exempte(tmp_path):
    # TRANSFER est l'exception explicite des deux contrôles ci-dessus (hand-off en cours).
    for wid, owner in (("C05-001", "CLAUDE"), ("ISS-A", "CODEX")):
        p = write(tmp_path, "t.md", table(row(work_id=wid, owner=owner, status="TRANSFER")))
        r = run([str(p)])
        assert r.returncode == 0, (wid, owner)


def test_core_owner_et_issue_owner_acceptent_leurs_proprietaires_legitimes(tmp_path):
    # Pendant positif des deux contrôles CORE_OWNER/ISSUE_OWNER, jamais exercé avant ce
    # correctif (revue scellée, tour 6 de #598, sièges 1 et 3 convergents) : retirer
    # "CODEX" de l'ensemble autorisé de CORE_OWNER, ou "UNASSIGNED" de celui de
    # CORE_OWNER ou d'ISSUE_OWNER ({"CODEX","UNASSIGNED"} et {"CLAUDE","UNASSIGNED"}),
    # survivait aux tests d'alors faute d'une ligne affirmant chacun accepté hors
    # TRANSFER — le seul cas déjà couvert ci-dessus.
    for wid, owner, scope in (
        ("C05-001", "CODEX", "core/x"),
        ("C05-001", "UNASSIGNED", "core/x"),
        ("ISS-A", "UNASSIGNED", "coordination"),
    ):
        p = write(tmp_path, "t.md", table(row(work_id=wid, owner=owner, scope=scope)))
        r = run([str(p)])
        assert r.returncode == 0, (wid, owner)


def test_core_re_et_claude_re_nont_pas_de_faux_positifs(tmp_path):
    # Pendant négatif des deux contrôles ci-dessus, jamais exercé avant ce correctif
    # (revue scellée, tour 7 de #598, siège 1) : les mutants qui ÉLARGISSENT CORE_RE ou
    # CLAUDE_RE ("$" retiré, ou "2[0-4]" assoupli en "2\d") survivent aux tests d'alors,
    # fail-closed (ils ajoutent des erreurs, jamais un faux COORDINATION_OK) donc non
    # bloquants — mais aucune fixture n'affirme explicitement qu'un Work ID hors de ces
    # motifs échappe bien à CORE_OWNER/ISSUE_OWNER même avec un owner qui violerait le
    # contrôle si le motif matchait à tort. "C25-001" (décennie hors 2[0-4]) et
    # "C05-0011" (4 chiffres, hors \d{3}$) hors CORE_RE ; "XC05-001" et "XISS-A" (préfixe
    # non en tête) hors des deux — CEUX-CI, en revanche, ne discriminent la présence
    # d'aucun mutant réel : imprécision corrigée en revue scellée (tour 8 de #598,
    # sièges 1 et 3 convergents) — retirer l'ancre "^" de ces trois regex est un mutant
    # STRICTEMENT ÉQUIVALENT, jamais un simple élargissement fail-closed, puisque les
    # trois ne sont consommées que par re.match(), qui ancre déjà en tête de chaîne quel
    # que soit le motif (mesuré : 0 différence observable sur retrait de "^" seul). Ces
    # deux fixtures restent utiles pour la lisibilité de l'intention et comme
    # défense-en-profondeur, mais — comme le .strip() déjà avoué de l'exemption n/a —
    # ne tuent aucun mutant que "$" et "2\d" ne tuent déjà.
    for wid in ("C25-001", "C05-0011", "XC05-001"):
        p = write(tmp_path, "t.md", table(row(work_id=wid, owner="CLAUDE", scope="core/x")))
        r = run([str(p)])
        assert r.returncode == 0, wid
        assert "CORE_OWNER:" not in r.stdout, wid

    p = write(tmp_path, "t.md", table(row(work_id="XISS-A", owner="CODEX")))
    r = run([str(p)])
    assert r.returncode == 0
    assert "ISSUE_OWNER:" not in r.stdout


# ---------------------------------------------------------------------------
# MODULE_CODE_DURING_CORE — seul interdit dur de l'ADR-0004 (mandat implicite : les
# fixtures qui ont justifié le durcissement du validateur, cf. contexte de l'issue)
# ---------------------------------------------------------------------------

def test_module_code_during_core_cellule_multiple(tmp_path):
    p = write(tmp_path, "t.md", table(row(scope="coordination;modules m/M7")))
    r = run([str(p)])
    assert r.returncode == 1
    assert "MODULE_CODE_DURING_CORE:ISS-A" in r.stdout


def test_module_code_during_core_cellule_multiple_avec_espace(tmp_path):
    # Sans ce test avant ce correctif (mutant survivant sur 3 des 4 sites de .strip() qui
    # suivent scope.split(";"), revue scellée, tour 3 de #598) : la seule fixture
    # multi-items du fichier ("coordination;modules m/M7", collée) ne discriminait rien,
    # car un .strip() en moins n'y change aucun contrat. C'est pourtant la graphie AVEC
    # espace après ";" qu'emploie, à ce jour, la seule table réelle de ce dépôt
    # (coordination/WORK-OWNERSHIP.md, ligne OPS-OVERLAY-INSTALL — référence datée : cette
    # ligne peut changer d'identifiant ou de statut à tout merge ordinaire) — retirer le
    # .strip() y laissait passer inaperçu un scope touchant modules m/, fail-open réel sur
    # le seul interdit dur de l'ADR-0004.
    p = write(tmp_path, "t.md", table(row(scope="coordination; modules m/M7")))
    r = run([str(p)])
    assert r.returncode == 1
    assert "MODULE_CODE_DURING_CORE:ISS-A" in r.stdout


def test_module_code_during_core_normalise_lantislash(tmp_path):
    # Le 4e des 4 sites de normalisation touchés par cette famille (revue scellée, tour 4
    # de #598) : `.replace("\\", "/")` dans la construction de `scopes_normalises`
    # n'avait, jusqu'ici, AUCUN test qui l'exerce réellement. La fixture antislash déjà
    # présente dans ce fichier (test_scope_traversee_refusee_antislash_et_slash, scope
    # "foo\..\modules m\M7") donne l'ILLUSION de couvrir cette graphie pour l'interdit
    # ADR-0004, mais elle porte aussi un ".." — imprécision de mécanisme corrigée ici
    # (revue scellée, tour 9 de #598, sièges 2 et 3 convergents) : validate() n'a AUCUN
    # court-circuit entre SCOPE et MODULE_CODE_DURING_CORE, ce sont deux `if` séquentiels
    # indépendants (mesuré : un scope "modules m/M7; /absolu" émet les DEUX en même temps,
    # SCOPE ET MODULE_CODE_DURING_CORE — un scope invalide ATTEINT donc bien l'interdit
    # ADR-0004). La cause réelle de la non-émission pour CETTE entrée précise est que
    # PurePosixPath ne normalise pas ".." : "foo/../modules m/m7" n'est ni égal, ni
    # parent, ni descendant de "modules m" (mesuré : sortie réelle "SCOPE:ISS-A:...",
    # MODULE_CODE_DURING_CORE jamais émis pour cette entrée-là spécifiquement — l'effet
    # observé reste exact, seule la cause invoquée changeait). Ce test-ci retire le ".." :
    # un scope antislash SANS traversée doit passer valid_scope() et être intercepté
    # uniquement par MODULE_CODE_DURING_CORE.
    p = write(tmp_path, "t.md", table(row(scope="modules m\\M7")))
    r = run([str(p)])
    assert r.returncode == 1
    assert "MODULE_CODE_DURING_CORE:ISS-A" in r.stdout


def test_module_code_during_core_prefixe_point_slash(tmp_path):
    p = write(tmp_path, "t.md", table(row(scope="./modules m/M7")))
    r = run([str(p)])
    assert r.returncode == 1
    assert "MODULE_CODE_DURING_CORE:ISS-A" in r.stdout


def test_module_code_during_core_scope_racine_couvrant_tout_larbre(tmp_path):
    # Sens ANCÊTRE (tour 10) : un scope "." couvre tout l'arbre, modules m/ compris,
    # même s'il n'est ni égal ni descendant de "modules m".
    for scope in (".", "./"):
        p = write(tmp_path, "t.md", table(row(scope=scope)))
        r = run([str(p)])
        assert r.returncode == 1, scope
        assert "MODULE_CODE_DURING_CORE:ISS-A" in r.stdout, scope


def test_module_code_during_core_scope_exactement_egal(tmp_path):
    # Sens ÉGALITÉ (revue scellée, tour 5 de #598) : le disjoint le plus direct de
    # `s == cible_module_m or cible_module_m in s.parents or s in cible_module_m.parents`
    # n'était exercé par AUCUNE des 52 fixtures — toutes retombaient sur le sens
    # descendant ("modules m/M7" et variantes) ou ancêtre ("." et "./"), jamais sur un
    # scope EXACTEMENT égal à "modules m" (aucun composant enfant, aucun préfixe "."). Le
    # disjoint homologue d'overlaps() (`pa == pb`), lui, était déjà couvert par 3 tests —
    # asymétrie non intentionnelle sur le seul interdit dur de l'ADR-0004, et sur la
    # graphie la plus directe de la violation que ce contrôle existe pour interdire.
    p = write(tmp_path, "t.md", table(row(scope="modules m")))
    r = run([str(p)])
    assert r.returncode == 1
    assert "MODULE_CODE_DURING_CORE:ISS-A" in r.stdout


def test_module_code_during_core_normalise_la_casse(tmp_path):
    # Sans test avant ce correctif (mutant survivant, revue scellée, tour 2 de #598) :
    # retirer le .casefold() de la normalisation de scope laissait ce cas passer
    # inaperçu — un fail-open réel sur le seul interdit dur de l'ADR-0004.
    p = write(tmp_path, "t.md", table(row(scope="Modules M/M7")))
    r = run([str(p)])
    assert r.returncode == 1
    assert "MODULE_CODE_DURING_CORE:ISS-A" in r.stdout


def test_module_code_during_core_scope_legitime_non_declenche(tmp_path):
    # Non-régression : un scope réel qui ne touche pas modules m/ ne doit jamais
    # déclencher ce contrôle — y compris un composant de chemin visuellement proche
    # ("modules-m", tiret et non espace) qui n'est ni égal ni parent/descendant réel
    # de "modules m" au sens PurePosixPath.
    for scope in ("coordination", "tools", "docs", "modules-m"):
        p = write(tmp_path, "t.md", table(row(scope=scope)))
        r = run([str(p)])
        assert r.returncode == 0, scope


def test_module_code_during_core_arme_seulement_sur_ligne_active(tmp_path):
    # Limite nommée, pas fermée (tour 13) : QUEUED/BLOCKED/MERGED/TRANSFER n'arment pas
    # le contrôle. Cohérent avec l'intention (rien n'est encore exécuté), documenté dans
    # coordination/CLAUDE-STATUS.md pour ne pas laisser croire à plus de protection.
    p = write(tmp_path, "t.md", table(row(scope="modules m/M7", status="QUEUED")))
    r = run([str(p)])
    assert r.returncode == 0
    assert r.stdout.strip() == "COORDINATION_OK rows=1 active=0"


def test_module_code_during_core_arme_bien_sur_review_et_ready_to_merge(tmp_path):
    # Pendant positif du test ci-dessus (revue scellée, tour 3 de #598) : celui-ci ne
    # confirme QUE le négatif (QUEUED n'arme pas) — retirer REVIEW ou READY_TO_MERGE de
    # l'ensemble ACTIVE = {"ACTIVE", "REVIEW", "READY_TO_MERGE"} y survivait sans faire
    # échouer aucun test, alors que coordination/WORK-OWNERSHIP.md porte aujourd'hui une
    # ligne REVIEW réelle — référence datée (revue scellée, tour 8 de #598, siège 2) :
    # peut changer de statut à tout merge ordinaire, seul l'invariant que ACTIVE compte
    # REVIEW et READY_TO_MERGE est stable.
    for status in ("REVIEW", "READY_TO_MERGE"):
        p = write(tmp_path, "t.md", table(row(scope="modules m/M7", status=status)))
        r = run([str(p)])
        assert r.returncode == 1, status
        assert "MODULE_CODE_DURING_CORE:ISS-A" in r.stdout, status


# ---------------------------------------------------------------------------
# valid_scope() — SCOPE:<id>:<valeur> (fixtures ayant justifié le durcissement)
# ---------------------------------------------------------------------------

def test_scope_absolu_refuse(tmp_path):
    p = write(tmp_path, "t.md", table(row(scope="/absolu")))
    r = run([str(p)])
    assert r.returncode == 1
    assert "SCOPE:ISS-A:" in r.stdout


def test_scope_tilde_refuse(tmp_path):
    # Garde item.startswith("~") sans test avant ce correctif (mutant survivant trouvé
    # en revue scellée, tour 2 de #598) : "~/secret" échappait aux deux autres gardes
    # (ni absolu au sens PurePosixPath, ni ".." dans ses parts).
    p = write(tmp_path, "t.md", table(row(scope="~/secret")))
    r = run([str(p)])
    assert r.returncode == 1
    assert "SCOPE:ISS-A:~/secret" in r.stdout


def test_scope_traversee_refusee_antislash_et_slash(tmp_path):
    for scope in ("foo/../modules m/M7", "foo\\..\\modules m\\M7"):
        p = write(tmp_path, "t.md", table(row(scope=scope)))
        r = run([str(p)])
        assert r.returncode == 1, scope
        assert "SCOPE:ISS-A:" in r.stdout, scope


def test_scope_multi_items_avec_espace_refuse_si_un_item_invalide(tmp_path):
    # Un des quatre contrats que le .strip() après scope.split(";") fait tenir sur la
    # graphie AVEC espace (revue scellée, tour 3 de #598 pour ce site précis et les deux
    # tests voisins de MODULE_CODE_DURING_CORE/PATH_COLLISION — PAS "le dernier" : le
    # tour 4 a dû fermer un 4e site de la même famille, .strip() côté droit de la boucle
    # PATH_COLLISION, qu'affirmer une famille close par erreur avait laissé passer
    # inaperçu) : sans ce .strip(), l'item " /absolu" (espace de tête compris) n'est ni
    # reconnu absolu par PurePosixPath ni comparé correctement — un item invalide caché
    # derrière un premier item valide dans une cellule multi-items espacée passait
    # inaperçu.
    p = write(tmp_path, "t.md", table(row(scope="foo; /absolu")))
    r = run([str(p)])
    assert r.returncode == 1
    assert "SCOPE:ISS-A:foo; /absolu" in r.stdout


def test_scope_degenere_uniquement_separateurs_refuse(tmp_path):
    # Fail-open fermé : une cellule "; ;" n'est pas vide au sens strip(), mais ne
    # décompose en aucun item — sans le garde-fou dédié, la boucle de validation ne
    # s'exécutait jamais et la fonction rendait True sans rien avoir vérifié.
    for scope in (";", "; ;"):
        p = write(tmp_path, "t.md", table(row(scope=scope)))
        r = run([str(p)])
        assert r.returncode == 1, scope
        assert "SCOPE:ISS-A:" in r.stdout, scope


# ---------------------------------------------------------------------------
# BRANCH_COLLISION — sentinelle n/a exemptée (fail-open réel fermé)
# ---------------------------------------------------------------------------

def test_branch_collision_detecte_sur_branche_identique(tmp_path):
    p = write(tmp_path, "t.md", table(
        row(work_id="ISS-A", branch="claude/x", scope="coordination"),
        row(work_id="ISS-B", branch="claude/x", scope="tools"),
    ))
    r = run([str(p)])
    assert r.returncode == 1
    assert "BRANCH_COLLISION:ISS-A:ISS-B" in r.stdout


def test_branch_collision_exempte_la_sentinelle_read_only(tmp_path):
    # Deux missions read-only actives, toutes deux "n/a", devaient rester exprimables —
    # sans cette exemption, la porte d'activation se bloquait sur un état légitime.
    # L'exemption est normalisée par .strip().casefold() (revue scellée, tour 4 de #598) :
    # "N/A" doit être exemptée au même titre que "n/a" — sans quoi une variante de casse
    # retombe à tort en BRANCH_COLLISION (fail-closed, pas un fail-open, mais la
    # normalisation restait non protégée par ce test avant). " n/a " (espaces de bord)
    # est incluse pour la lisibilité de l'intention, mais NE discrimine PAS le .strip()
    # de cette exemption à elle seule : parse_rows() strippe déjà chaque cellule avant
    # que BRANCH_COLLISION ne la voie (mesuré en revue scellée, tour 5 : muter
    # .strip().casefold() en .casefold() seul laisse ce test vert) — ce .strip() précis
    # est une garde défensive redondante avec un strip en amont, pas un contrat atteint
    # par cette fixture.
    for graphie in ("n/a", "N/A", " n/a "):
        p = write(tmp_path, "t.md", table(
            row(work_id="ISS-A", branch=graphie, scope="read-only"),
            row(work_id="ISS-B", branch=graphie, scope="read-only"),
        ))
        r = run([str(p)])
        assert r.returncode == 0, repr(graphie)


def test_collisions_armees_seulement_sur_lignes_actives(tmp_path):
    # Pendant, côté collisions, de test_branch_arme_seulement_sur_ligne_active et
    # test_module_code_during_core_arme_seulement_sur_ligne_active plus haut — jamais
    # exercé avant ce correctif (revue scellée, tour 7 de #598, sièges 1 et 3
    # convergents) : `active = [r for r in data if r["status"] in ACTIVE]` filtre déjà
    # BRANCH_COLLISION et PATH_COLLISION en amont de leur boucle commune ; le retirer
    # (muté en `list(data)`) laisse les tests d'alors verts, fail-closed (BRANCH_COLLISION
    # et PATH_COLLISION parasites sur un état légitime, jamais un faux COORDINATION_OK).
    # Deux lignes QUEUED de même branche et même scope, aujourd'hui vertes, referaient
    # échouer la validation.
    p = write(tmp_path, "t.md", table(
        row(work_id="ISS-A", branch="br-a", scope="coordination", status="QUEUED"),
        row(work_id="ISS-B", branch="br-a", scope="coordination", status="QUEUED"),
    ))
    r = run([str(p)])
    assert r.returncode == 0
    assert r.stdout.strip() == "COORDINATION_OK rows=2 active=0"


def test_scope_a_point_virgule_final_reste_vert(tmp_path):
    # Les trois filtres `if x.strip()` sur `scope.split(";")` (MODULE_CODE_DURING_CORE,
    # et sa/sb de la boucle PATH_COLLISION) n'avaient, avant ce correctif (revue scellée,
    # tour 7 de #598, siège 3), aucune fixture dédiée — les retirer laisse les tests
    # d'alors verts, fail-closed : un point-virgule final produit un item vide qui, non
    # filtré, devient PurePosixPath(".") — ancêtre de tout scope, donc collisions et
    # MODULE_CODE_DURING_CORE parasites sur un état légitime.
    #
    # Une ligne UNIQUE à point-virgule final suffit à épingler le filtre de
    # MODULE_CODE_DURING_CORE (mesuré), mais PATH_COLLISION n'a pas de second membre
    # actif à comparer sans une deuxième ligne — sa et sb restent alors non atteints,
    # même asymétrie gauche/droite que celle fermée ailleurs dans ce fichier pour
    # overlaps(). D'où DEUX lignes actives, chacune à point-virgule final : mesuré,
    # retirer le filtre de sa (gauche) SEUL ou celui de sb (droite) SEUL fait chacun
    # apparaître un PATH_COLLISION parasite sur cette fixture, réel sur le code livré.
    p = write(tmp_path, "t.md", table(
        row(work_id="ISS-A", branch="br-a", scope="coordination;"),
        row(work_id="ISS-B", branch="br-b", scope="docs;"),
    ))
    r = run([str(p)])
    assert r.returncode == 0
    assert r.stdout.strip() == "COORDINATION_OK rows=2 active=2"


# ---------------------------------------------------------------------------
# Lecture / écriture — LECTURE_IMPOSSIBLE, SORTIE_IMPOSSIBLE (mandat #592, points 4-5)
# ---------------------------------------------------------------------------

def test_lecture_impossible_sur_repertoire(tmp_path):
    r = run([str(tmp_path)])
    assert r.returncode == 2
    assert r.stdout.startswith("LECTURE_IMPOSSIBLE:")


def test_lecture_impossible_sur_chemin_inexistant(tmp_path):
    r = run([str(tmp_path / "n-existe-pas.md")])
    assert r.returncode == 2
    assert r.stdout.startswith("LECTURE_IMPOSSIBLE:")


def test_lecture_impossible_sur_contenu_non_utf8(tmp_path):
    p = tmp_path / "t.md"
    p.write_bytes(b"\xff\xfe" + HEADER.encode())
    r = run([str(p)])
    assert r.returncode == 2
    assert r.stdout.startswith("LECTURE_IMPOSSIBLE:")


def test_fifo_nomme_reste_lisible(tmp_path):
    """Régression réelle de #564, PAS un mutant équivalent (revue scellée, tour 2 de
    #598) : une version antérieure de _chemin_sur() exigeait `is_file()` en lecture, ce
    qui rejetait un FIFO — entrée légitime et atteignable en ligne de commande que
    `read_text()` seul lisait déjà sans encombre avant l'introduction de cette fonction
    (voir son docstring, "Fermée pour le FIFO nommé"). Contrairement aux mutants
    équivalents documentés plus haut dans ce fichier (message de cause différent, même
    exit + préfixe), réintroduire ce test précis change le CONTRAT observable : un FIFO
    réel passe de `COORDINATION_OK` (exit 0) à `LECTURE_IMPOSSIBLE` (exit 2) — mesuré,
    aucun des autres tests de ce fichier ne s'en aperçoit.
    """
    fifo = tmp_path / "table.fifo"
    os.mkfifo(fifo)
    # Écrivain en arrière-plan : un FIFO bloque à l'ouverture tant que personne n'écrit
    # ou ne lit de l'autre côté — le lancer avant `run()` (qui, lui, lit) évite le blocage
    # mutuel des deux extrémités.
    ecrivain = subprocess.Popen(
        ["sh", "-c", f'cat > "$1"', "sh", str(fifo)],
        stdin=subprocess.PIPE,
        text=True,
    )
    r = None
    try:
        ecrivain.stdin.write(table(row()))
        ecrivain.stdin.close()
        r = run([str(fifo)], timeout=10)
    finally:
        # `wait(timeout=...)` seul ne tue rien : si le lecteur n'ouvre jamais le FIFO
        # (exactement le cas ROUGE contre lequel ce test protège), `cat` reste bloqué
        # dans son propre open() et `wait()` lève TimeoutExpired en laissant le
        # processus orphelin — mesuré en revue scellée, tour 3 de #598. `kill()` avant
        # un second `wait()` (sans timeout, un processus tué se termine immédiatement)
        # garantit la récolte dans les deux cas.
        try:
            ecrivain.wait(timeout=10)
        except subprocess.TimeoutExpired:
            ecrivain.kill()
            ecrivain.wait()
    assert r is not None
    assert r.returncode == 0
    assert r.stdout.strip() == "COORDINATION_OK rows=1 active=1"


def test_boucle_de_liens_symboliques_en_lecture(tmp_path):
    """Durcissement documenté de #564 (docstring de _chemin_sur()) SANS test dédié
    jusqu'à ce correctif, alors que l'en-tête de ce fichier revendiquait à tort que
    "LECTURE_IMPOSSIBLE/SORTIE_IMPOSSIBLE en couvrent déjà le contrat" pour ce cas —
    faux, mesuré (revue scellée, tour 3 de #598) : `resolve(strict=True)` lève
    `RuntimeError` (pas `OSError`) sur une boucle de liens symboliques, qui échappe telle
    quelle aux deux `except` de `main()`. Sans la reconversion en `OSError` que
    `_chemin_sur()` fait explicitement pour cette classe d'entrée, une boucle réelle NE
    change pas seulement de message : elle change d'EXIT CODE ET DE PRÉFIXE, de
    `LECTURE_IMPOSSIBLE` exit 2 à un traceback non intercepté, exit 1, stdout vide —
    exactement le fail-open que ce fichier existe pour fermer. Ne bloque jamais
    (contrairement à un FIFO sans écrivain) : `resolve()` détecte l'ELOOP et échoue tout
    de suite, aucune précaution de nettoyage particulière requise.
    """
    a = tmp_path / "boucle_a"
    b = tmp_path / "boucle_b"
    a.symlink_to(b)
    b.symlink_to(a)
    r = run([str(a)], timeout=10)
    assert r.returncode == 2
    assert r.stdout.startswith("LECTURE_IMPOSSIBLE:")
    assert r.stderr == ""  # aucun traceback


def test_sortie_impossible_sur_repertoire_de_sortie_inexistant(tmp_path):
    p = write(tmp_path, "t.md", table(row()))
    r = run([str(p), "--json-output", str(tmp_path / "n-existe-pas" / "o.json")])
    assert r.returncode == 2
    assert r.stdout.startswith("SORTIE_IMPOSSIBLE:")


def test_sortie_impossible_sur_fifo_existant(tmp_path):
    # La garde "chemin.exists() and not chemin.is_file()" n'est PAS un mutant équivalent
    # au niveau du contrat, contrairement à ses deux voisines (répertoire, parent non-
    # répertoire) : sans elle, --json-output vers un FIFO déjà existant ne rend pas le
    # même SORTIE_IMPOSSIBLE exit 2 par un autre chemin — il BLOQUE indéfiniment, faute
    # de lecteur côté écriture (revue scellée, tour 3 de #598). `timeout=` borne le test
    # pour qu'une régression future échoue proprement au lieu de faire pendre pytest.
    fifo = tmp_path / "sortie.fifo"
    os.mkfifo(fifo)
    p = write(tmp_path, "t.md", table(row()))
    r = run([str(p), "--json-output", str(fifo)], timeout=10)
    assert r.returncode == 2
    assert r.stdout.startswith("SORTIE_IMPOSSIBLE:")


def test_json_output_ecrit_sur_chemin_conforme(tmp_path):
    p = write(tmp_path, "t.md", table(row()))
    out = tmp_path / "o.json"
    r = run([str(p), "--json-output", str(out)])
    assert r.returncode == 0
    assert out.exists()
    assert '"rows": 1' in out.read_text()


def test_json_output_porte_les_erreurs_sur_table_non_conforme(tmp_path):
    # coordination/README.md (fichier modifié par cette PR) affirme « (mesuré) » qu'une
    # table NON conforme voit quand même sa sortie --json-output écrite, portant alors
    # cette même liste d'erreurs dans son champ "errors" — aucune fixture ne le tenait
    # avant ce correctif (revue scellée, tour 8 de #598, siège 1) : seul le champ "rows"
    # sur une table CONFORME est épinglé ci-dessus, jamais le champ "errors" sur une
    # table non conforme, la moitié du contrat que le README revendique.
    p = write(tmp_path, "t.md", table(row(scope="modules m")))
    out = tmp_path / "o.json"
    r = run([str(p), "--json-output", str(out)])
    assert r.returncode == 1
    assert "MODULE_CODE_DURING_CORE:ISS-A" in r.stdout
    assert out.exists()
    assert json.loads(out.read_text()) == {
        "rows": 1,
        "active": 1,
        "errors": ["MODULE_CODE_DURING_CORE:ISS-A"],
    }


def test_json_output_vide_est_une_demande_reelle_pas_une_absence(tmp_path):
    # Fail-open fermé : `if args.json_output:` seul confondait "" avec None et
    # sautait l'écriture en silence — exit 0 au lieu du exit 2 attendu ici.
    p = write(tmp_path, "t.md", table(row()))
    r = run([str(p), "--json-output", ""])
    assert r.returncode == 2
    assert r.stdout.startswith("SORTIE_IMPOSSIBLE:")


# ---------------------------------------------------------------------------
# Garde anti-auto-écrasement — même chemin ET lien physique (fail-open réel fermé)
# ---------------------------------------------------------------------------

def test_json_output_refuse_le_meme_chemin_que_ownership(tmp_path):
    p = write(tmp_path, "t.md", table(row()))
    contenu_avant = p.read_text()
    r = run([str(p), "--json-output", str(p)])
    assert r.returncode == 2
    assert "ecraserait" in r.stdout
    assert p.read_text() == contenu_avant  # la table source n'a pas été détruite


def test_json_output_refuse_un_lien_physique_du_meme_fichier(tmp_path):
    p = write(tmp_path, "t.md", table(row()))
    contenu_avant = p.read_text()
    lien = tmp_path / "lien.md"
    os.link(p, lien)
    r = run([str(p), "--json-output", str(lien)])
    assert r.returncode == 2
    assert "ecraserait" in r.stdout
    assert p.read_text() == contenu_avant


# ---------------------------------------------------------------------------
# Sécurité d'encodage sur stdout (fail-open réel fermé, tour 10-11)
# ---------------------------------------------------------------------------

def test_cellule_accentuee_sous_stdout_ascii_ne_plante_pas(tmp_path):
    # Régression fermée : une simple cellule de table accentuée levait
    # UnicodeEncodeError sous un stdout non-UTF-8, exit 1 avec stdout vide et
    # traceback — indiscernable d'une table non conforme.
    p = write(tmp_path, "t.md", table(row(scope="/répertoire-accentué-hors-adr")))
    env = {**os.environ, "PYTHONIOENCODING": "ascii"}
    r = run([str(p)], env=env)
    assert r.returncode == 1
    assert "SCOPE:ISS-A:" in r.stdout
    assert r.stderr == ""  # aucun traceback


def test_cellule_accentuee_reste_lisible_sous_locale_non_utf8(tmp_path):
    # Pendant côté LECTURE du test ci-dessus, qui ne couvre que la SORTIE (stdout) —
    # jamais exercé avant ce correctif (revue scellée, tour 10 de #598, siège 2, contraste
    # personnellement reproduit après un premier essai infructueux au tour 9 : LC_ALL=C
    # SEUL ne suffit pas, PYTHONUTF8=0 est requis pour que Python renonce au repli UTF-8 de
    # la PEP 540). `path.read_text(encoding="utf-8")` dans parse_rows() n'avait aucune
    # fixture dédiée à son argument `encoding` : le retirer laisse les 67 tests d'alors
    # verts, tout en faisant échouer LA LECTURE d'une cellule accentuée — pourtant légitime
    # — sous une locale non-UTF-8 délibérée. Mesuré sur le validateur réel : sans le
    # correctif, `LC_ALL=C PYTHONUTF8=0` sur une table valide à scope accentué rend
    # `COORDINATION_OK` exit 0 ; muté, `LECTURE_IMPOSSIBLE:'ascii' codec can't decode
    # byte...` exit 2 — cible réaliste : `coordination/WORK-OWNERSHIP.md` porte des lignes
    # non-ASCII (français accentué) — référence datée (revue scellée, tour 11 de #598,
    # sièges 1/2/3 convergents : 15 aujourd'hui), un merge ordinaire ou le travail de
    # l'autre plateforme sur une autre branche peut faire varier ce décompte sans que
    # l'invariant lui-même (la table réelle en porte) cesse d'être vrai. Fail-closed
    # (jamais un faux COORDINATION_OK, seul contrat que ce fichier se donne) et hors de
    # tout usage documenté de cet outil (jamais invoqué sous une locale non-UTF-8 dans
    # ce dépôt), d'où non bloquant.
    p = write(tmp_path, "t.md", table(row(scope="coordination/répertoire-accentué")))
    env = {**os.environ, "LC_ALL": "C", "LANG": "C", "PYTHONUTF8": "0"}
    r = run([str(p)], env=env)
    assert r.returncode == 0
    assert r.stdout.strip() == "COORDINATION_OK rows=1 active=1"


def test_stdout_ferme_reste_silencieux_sans_lever_attributeerror(tmp_path):
    # Régression du tour 10 fermée au tour 11 : sys.stdout.reconfigure() plantait
    # (AttributeError) quand le descripteur de sortie standard était déjà fermé au
    # lancement. `stdout=DEVNULL` ne suffit PAS à reproduire : /dev/null reste un
    # descripteur ouvert, sys.stdout n'y vaut pas None — seul un shell fermant
    # réellement le descripteur (`>&-`) déclenche ce comportement CPython, mesuré
    # tout au long de la revue scellée qui a fermé cette régression.
    p = write(tmp_path, "t.md", table(row()))
    proc = subprocess.run(
        ["sh", "-c", f'exec "$1" -B "$2" "$3" >&-',
         "sh", sys.executable, str(SCRIPT), str(p)],
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.returncode == 0
    # Assertion volontairement restreinte à la signature de traceback, pas à une
    # égalité stricte avec la chaîne vide (revue scellée, tour 10 de #598, siège 1) :
    # `proc.stderr` capture le stderr du SHELL INTERMÉDIAIRE `sh -c`, pas seulement
    # celui du validateur — observé réellement en revue (répertoire courant supprimé
    # par un accès concurrent pendant l'exécution) : dash y émet alors « sh: 0:
    # getcwd() failed: ... », un bruit qui ne vient pas du script testé, et qu'une
    # égalité stricte imputerait à tort à une régression du validateur.
    assert "AttributeError" not in proc.stderr
    assert "Traceback" not in proc.stderr


# ---------------------------------------------------------------------------
# Ordre relatif des lignes d'erreur — validate() (AUD-QUAL-008, #600)
# ---------------------------------------------------------------------------

def test_ordre_erreur_structurelle_avant_erreur_de_propriete_sur_meme_ligne(tmp_path):
    # tools/check_coordination.py éclate désormais validate() (revue scellée,
    # AUD-QUAL-007, #594/#599) en _erreurs_structurelles() + _erreurs_de_propriete()
    # pour une même ligne, assemblées par _erreurs_de_ligne(). Cet ordre était
    # structurellement inviolable avant l'éclatement (un bloc linéaire unique, non
    # réordonnable sans réécrire tout le corps de la fonction) ; après, c'est un `+`
    # échangeable en un jeton — trouvé par les 3 sièges du tour 1 de la revue scellée
    # de #599, jamais épinglé par aucune fixture avant ce test. Mesuré : muter
    # l'assemblage en `_erreurs_de_propriete(row) + _erreurs_structurelles(row, seen)`
    # laisse toutes les fixtures d'alors vertes, faute d'une assertion sur l'ORDRE
    # (par opposition à la seule PRÉSENCE) des lignes d'erreur.
    #
    # OWNER (contrôle de _erreurs_structurelles) et CORE_OWNER (contrôle de
    # _erreurs_de_propriete) cumulés sur la MÊME ligne : Work ID "C05-001" (matche
    # CORE_RE) porté par un owner ni dans OWNERS ni exempté de CORE_OWNER, un seul
    # littéral impossible qui viole les deux contrôles à la fois.
    p = write(tmp_path, "t.md", table(row(work_id="C05-001", owner="BADOWNER", scope="core/x")))
    r = run([str(p)])
    assert r.returncode == 1
    assert r.stdout.splitlines() == [
        "OWNER:C05-001:BADOWNER",
        "CORE_OWNER:C05-001:BADOWNER",
    ]


def test_ordre_erreurs_de_ligne_avant_erreurs_de_collision(tmp_path):
    # Pendant du test ci-dessus, au niveau de validate() plutôt que de
    # _erreurs_de_ligne() : les erreurs PAR LIGNE (produites en appelant
    # _erreurs_de_ligne() sur chaque ligne) doivent précéder toutes les erreurs DE
    # PAIRE (produites par _erreurs_de_collision()), comme le faisait le bloc
    # linéaire unique avant l'éclatement — désignées par NOM de fonction plutôt que
    # par graphie de boucle, moins sensible à un refactor futur de validate() (revue
    # scellée, tour 1 de #601, siège 2). Mesuré : déplacer l'appel à
    # _erreurs_de_collision() avant la boucle par ligne dans validate() laisse
    # toutes les fixtures d'alors vertes, pour la même raison que le test ci-dessus
    # — aucune n'affirme un ordre entre les DEUX familles de contrôle.
    #
    # Deux lignes actives de même branche et même scope (BRANCH_COLLISION et
    # PATH_COLLISION, une paire) ; la SECONDE (ISS-B, membre DROIT de la paire) porte
    # en prime une erreur PAR LIGNE (OWNER, puis ISSUE_OWNER — Work ID "ISS-B" matche
    # CLAUDE_RE). Précision (revue scellée, tour 2 de #601, siège 1) : le membre DROIT
    # est nécessaire, pas arbitraire — une erreur portée par le membre GAUCHE (ISS-A)
    # ne distinguerait PAS validate() réel d'un refactor hypothétique qui entrelacerait
    # boucle par ligne et boucle par paire (traiter chaque ligne, émettre ses erreurs
    # PUIS les paires où elle est le membre gauche, avant de passer à la ligne
    # suivante) : sous cet entrelacement, ISS-A (première ligne) resterait émise avant
    # la paire dans les deux cas. Mesuré : cette mutation d'entrelacement laisse les
    # 70 tests d'alors verts avec l'erreur sur ISS-A, mais fait rougir CE test une fois
    # l'erreur déplacée sur ISS-B (la paire, dont ISS-A est le membre gauche, serait
    # alors émise AVANT les erreurs de ISS-B). Couverture bonus, non revendiquée par
    # le nom du test mais mesurée (revue scellée, tour 1 de #601, sièges 1 et 2) :
    # cette même égalité de liste épingle aussi que BRANCH_COLLISION précède les
    # PATH_COLLISION à l'intérieur de _erreurs_de_paire() — SEULEMENT cette relation-là,
    # pas « l'ordre interne » de la fonction en général : sur cette fixture à scopes
    # mono-item, il n'existe qu'une seule ligne PATH_COLLISION par paire, donc rien
    # n'épingle l'ordre RELATIF entre plusieurs lignes PATH_COLLISION d'une même paire
    # (cf. l'aveu explicite de l'en-tête, corrigé pour la même sur-généralisation en
    # revue scellée, tour 3 de #601, siège 2).
    p = write(tmp_path, "t.md", table(
        row(work_id="ISS-A", owner="CLAUDE", branch="claude/x", scope="coordination"),
        row(work_id="ISS-B", owner="BADOWNER", branch="claude/x", scope="coordination"),
    ))
    r = run([str(p)])
    assert r.returncode == 1
    assert r.stdout.splitlines() == [
        "OWNER:ISS-B:BADOWNER",
        "ISSUE_OWNER:ISS-B:BADOWNER",
        "BRANCH_COLLISION:ISS-A:ISS-B",
        "PATH_COLLISION:ISS-A:ISS-B:coordination:coordination",
    ]


def test_ordre_ligne_avant_paire_quand_la_ligne_en_erreur_est_hors_de_la_paire(tmp_path):
    # Complète test_ordre_erreurs_de_ligne_avant_erreurs_de_collision ci-dessus contre
    # un entrelacement MIROIR de celui qu'il exclut déjà (revue scellée, tour 1 de
    # #603, siège 2 ; AUD-QUAL-010, #604) : pour chaque ligne, émettre ses erreurs
    # PUIS les paires où elle est le membre DROIT plutôt que le membre GAUCHE. Ce
    # test-là place l'erreur de ligne sur ISS-B, membre DROIT de la SEULE paire de sa
    # fixture — ce qui exclut l'entrelacement membre GAUCHE, mais ne distingue PAS
    # validate() réel de son miroir : à cette arité (une seule paire, l'erreur de
    # ligne portée par un de SES membres), la sortie du miroir coïncide avec celle
    # de validate() réel.
    #
    # Ce test-ci isole la ligne en erreur de la paire : ISS-C ne participe à AUCUNE
    # collision (branche et scope propres à elle), et son statut MERGED l'exclut de
    # _erreurs_de_collision() (qui ne voit que les lignes ACTIVE) — donc de toute
    # paire, y compris comme membre. Positionnée APRÈS la paire ISS-A/ISS-B dans la
    # table, elle force la divergence : _erreurs_de_ligne() est appliquée à TOUTE la
    # table (ISS-C y contribue OWNER + ISSUE_OWNER), tandis que
    # _erreurs_de_collision() ne voit que les 2 lignes ACTIVE (ISS-A, ISS-B, seule
    # paire). Sous le mutant miroir, le « tour » d'ISS-B émet ses propres erreurs de
    # ligne (aucune ici) PUIS la paire dont il est membre DROIT (BRANCH_COLLISION,
    # PATH_COLLISION) — AVANT que le « tour » d'ISS-C, plus tardif dans la table,
    # n'émette ses erreurs de ligne. Mesuré (copie isolée, jamais le worktree
    # partagé) : cette mutation laisse les 70 tests d'alors verts (ISS-C n'étant
    # membre d'aucune paire, aucun test existant n'exerce ce cas) mais fait rougir CE
    # test — même ensemble de lignes que le réel, ordre différent : erreurs DE PAIRE
    # avant erreurs DE LIGNE, l'inverse exact de ce que le nom de ce test revendique.
    #
    # Instance retenue parmi les 2 mesurées en revue scellée, tour 1 de #603 (siège 2) et
    # reprises dans #604 (3 lignes ACTIVE ; 2 ACTIVE + 1 ligne hors de l'ensemble ACTIVE
    # après) : celle-ci, qui réduit le nombre de paires évaluées de 3 à 1. Ce choix n'est
    # PAS mécaniquement requis — sur-généralisation trouvée et mesurée en revue scellée
    # (tour 2 de #606, 3 sièges convergents) dans une précédente version de ce paragraphe,
    # qui l'affirmait à tort : status="ACTIVE" sur ISS-C fait diverger le mutant miroir à
    # l'identique (mesuré). Ce qui porte le mécanisme, tel que #604 et le docstring de
    # _erreurs_de_ligne() le formulent déjà (mais voir #607 : l'aveu de ce docstring «
    # reste NON epinglee a ce cas — suivi separe : #604 » devient lui-même périmé une fois
    # #604 fermée par cette PR — suivi séparé, pas de correctif ici) : ISS-C porte une
    # erreur de ligne et est positionnée, dans la table, APRÈS le membre DROIT d'une paire
    # en collision — pas plus. Sur-restriction trouvée et mesurée en revue scellée (tour 3
    # de #606, 3 sièges convergents) dans une autre précédente version de ce paragraphe,
    # qui ajoutait à tort la condition qu'ISS-C ne soit elle-même membre DROIT d'aucune
    # paire : mesuré par contre-exemple, donner à ISS-C À LA FOIS la même branche que
    # ISS-A/ISS-B ET le statut ACTIVE (les deux mutations sont nécessaires — sous MERGED
    # seul, ISS-C reste hors de _erreurs_de_collision() quelle que soit sa branche, donc
    # membre d'aucune paire, ce qui ne réfute rien) la rend membre DROIT de 2 paires en
    # collision supplémentaires (BRANCH_COLLISION:ISS-A:ISS-C,
    # BRANCH_COLLISION:ISS-B:ISS-C) — et le mutant miroir diverge toujours à l'identique :
    # c'est la présence de la paire (ISS-A,ISS-B), dont ISS-C n'a pas besoin d'être
    # membre, qui suffit. Ni l'appartenance d'ISS-C à ACTIVE, ni son statut de membre ou
    # non d'une paire, ne portent le mécanisme. Un statut hors ACTIVE reste néanmoins
    # préférable ici : il instancie la branche la plus distincte des 2 mesurées dans #604,
    # plutôt que de redire sous une troisième forme l'instance à 3 lignes ACTIVE déjà
    # documentée ailleurs (#604, instance 1 ; docstring de _erreurs_de_ligne()). MERGED
    # choisi parmi QUEUED, BLOCKED, MERGED — TRANSFER exclu, mesuré : la garde
    # `status != "TRANSFER"` de _erreurs_de_propriete() supprimerait ISSUE_OWNER, faisant
    # tomber cette fixture à 3 lignes au lieu des 4 assertées ; c'est la SEULE
    # contrainte que le statut retenu fait peser sur la sortie assertée.
    p = write(tmp_path, "t.md", table(
        row(work_id="ISS-A", owner="CLAUDE", branch="claude/x", scope="coordination"),
        row(work_id="ISS-B", owner="CLAUDE", branch="claude/x", scope="coordination"),
        row(work_id="ISS-C", owner="BADOWNER", branch="claude/z", scope="scripts", status="MERGED"),
    ))
    r = run([str(p)])
    assert r.returncode == 1
    assert r.stdout.splitlines() == [
        "OWNER:ISS-C:BADOWNER",
        "ISSUE_OWNER:ISS-C:BADOWNER",
        "BRANCH_COLLISION:ISS-A:ISS-B",
        "PATH_COLLISION:ISS-A:ISS-B:coordination:coordination",
    ]


def test_ordre_structurel_avant_propriete_avec_deux_erreurs_structurelles(tmp_path):
    # Complète test_ordre_erreur_structurelle_avant_erreur_de_propriete_sur_meme_ligne
    # ci-dessus contre un entrelacement en ZIP des deux groupes assemblés par
    # _erreurs_de_ligne() (revue scellée, tour 2 de #603, siège 3 ; précisée tour
    # 3, siège 3 ; AUD-QUAL-011, #605). Ce test-là n'exerce qu'UNE
    # erreur par groupe (OWNER, CORE_OWNER) — arité où concaténation et
    # entrelacement en zip coïncident. Mesuré : à l'arité (1 structurelle,
    # 2 propriété), le mutant reste indiscernable du réel ; c'est UNIQUEMENT à
    # partir de 2 erreurs côté STRUCTUREL (avec au moins 1 côté propriété) qu'il
    # diverge.
    #
    # Fixture à 2 erreurs structurelles (OWNER, STATUS) + 1 erreur de propriété
    # (CORE_OWNER) : Work ID "C05-001" (matche CORE_RE), owner "BADOWNER" (hors
    # OWNERS), status "BADSTATUS" (hors STATUSES), scope "core/x". Une fixture
    # préexistante (test_separateur_espace_reste_non_reconnu_fail_closed) exerce
    # déjà 2 erreurs structurelles (OWNER, STATUS) sur une même ligne, mais AUCUNE
    # erreur de propriété — arité (2,0) où `zip_longest` dégénère en la liste
    # structurelle seule, indiscernable de la concaténation. Mesuré (copie isolée,
    # jamais le worktree partagé) : le mutant zip laisse les 71 tests d'alors
    # verts mais fait rougir CE test — même ensemble de lignes que le réel, ordre
    # différent : CORE_OWNER (propriété) sort entre OWNER et STATUS (structurel)
    # au lieu de les suivre toutes deux.
    #
    # Couverture bonus, non revendiquée par le nom du test mais mesurée : cette
    # même égalité de liste épingle aussi que OWNER précède STATUS à l'intérieur
    # de _erreurs_structurelles() — voir l'en-tête de ce fichier pour la portée
    # exacte de cette exception (les autres contrôles de ce groupe et ceux de
    # _erreurs_de_propriete() restent hors contrat).
    #
    # Voir aussi #607 : la fermeture de #605 par ce commit périme DEUX clauses du
    # docstring de _erreurs_de_ligne() dans tools/check_coordination.py — celle
    # qui borne la relation structurel-avant-propriété à l'arité (1,1) (« reste...
    # NON epinglee a ce jour — suivi separe : #605 ») et celle sur l'ordre INTERNE
    # à chaque groupe (« reste NON epingle a ce jour ») — suivi séparé, pas de
    # correctif ici.
    p = write(tmp_path, "t.md", table(
        row(work_id="C05-001", owner="BADOWNER", scope="core/x", status="BADSTATUS"),
    ))
    r = run([str(p)])
    assert r.returncode == 1
    assert r.stdout.splitlines() == [
        "OWNER:C05-001:BADOWNER",
        "STATUS:C05-001:BADSTATUS",
        "CORE_OWNER:C05-001:BADOWNER",
    ]


# ---------------------------------------------------------------------------
# Limite héritée du pack, caractérisée explicitement — PAS un test qui la cache
# (mandat #592, point 2)
# ---------------------------------------------------------------------------

def test_ligne_privee_de_son_pipe_initial_est_un_faux_vert_connu(tmp_path):
    """Limite mesurée et documentée dans coordination/README.md, héritée du pack et
    délibérément PAS refermée dans cette PR : une ligne de données à laquelle il
    manque le `|` de tête n'est jamais reconnue comme une ligne de table (le test
    `line.startswith("|")` de parse_rows() l'exclut avant même le découpage en
    cellules) — donc jamais validée, collisions et interdit ADR-0004 compris.

    Ce test ne cache pas le défaut : il l'exerce et affirme le comportement actuel
    tel quel, pour qu'une future correction de ce fail-open se voie ICI (ce test
    échouera alors, signalant qu'il doit être mis à jour, pas que le code a régressé)
    plutôt que de rester un angle mort silencieux.
    """
    p = write(tmp_path, "t.md", HEADER + SEP + "ISS-A | CLAUDE | br-a | modules m/M7 | ACTIVE | x | y |\n")
    r = run([str(p)])
    assert r.returncode == 0
    assert r.stdout.strip() == "COORDINATION_OK rows=0 active=0"


# ---------------------------------------------------------------------------
# --help et argument manquant (contrat argparse documenté dans coordination/README.md)
# ---------------------------------------------------------------------------

def test_help_exit_zero_sans_coordination_ok(tmp_path):
    r = run(["--help"])
    assert r.returncode == 0
    assert "COORDINATION_OK" not in r.stdout
    assert "usage" in r.stdout.lower()


def test_argument_manquant_exit_deux_sans_prefixe(tmp_path):
    r = run([])
    assert r.returncode == 2
    assert r.stdout == ""
    assert "usage" in r.stderr.lower()

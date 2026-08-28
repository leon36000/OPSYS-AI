# Tests de tools/check_coordination.py (issue AUD-QUAL-006, #592) — pas une énumération
# exhaustive de tout comportement du validateur (ex. le message exact d'une boucle de liens
# symboliques n'a pas de test dédié : LECTURE_IMPOSSIBLE/SORTIE_IMPOSSIBLE en couvrent déjà le
# contrat), mais chaque durcissement de la revue scellée qui a produit ce fichier (PR #564,
# 14 tours) ET chaque contrôle de ligne hérité du pack encore vivant dans le validateur réduit
# (MALFORMED_ROW, WORK_ID_EMPTY, DUPLICATE_WORK, OWNER, STATUS, BRANCH, CORE_OWNER,
# ISSUE_OWNER — mesurés par mutation en revue scellée, tour 1 de #598 : aucun test dédié
# avant ce commit, malgré une revendication de couverture ici même qui les omettait).
# `coordination/CLAUDE-STATUS.md` garde le détail narratif des durcissements, ce fichier en
# garde la preuve rejouable. Invocation en subprocess réel (comme
# scripts/tests/test_methode.py) : ce qui compte ici est le contrat CLI — exit code + préfixe
# sur stdout — pas l'appel direct des fonctions internes.
#
# Lancer seul : python3 -m pytest coordination/tests/ (hors testpaths par défaut de
# pytest.ini — dont le contenu exact n'est pas recopié ici, voir coordination/README.md).
from __future__ import annotations

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


def test_separateur_espace_reste_non_reconnu_fail_closed(tmp_path):
    # Limite héritée du pack, documentée dans coordination/README.md, pas fermée ici :
    # un séparateur espacé n'est pas reconnu — mais le résultat est fail-closed (des
    # erreurs parasites, jamais un faux COORDINATION_OK), pas un fail-open.
    p = write(tmp_path, "t.md", HEADER + "| --- | --- | --- | --- | --- | --- | --- |\n")
    r = run([str(p)])
    assert r.returncode == 1
    assert "HEADER_MISSING" in r.stdout


# ---------------------------------------------------------------------------
# overlaps() — normalisation casse + séparateur (mandat #592, point 3)
# ---------------------------------------------------------------------------

def test_overlaps_normalise_la_casse(tmp_path):
    # Fail-open du pack fermé : "Coordination" vs "coordination" est une vraie collision,
    # une comparaison de chaîne brute la manquait.
    p = write(tmp_path, "t.md", table(
        row(work_id="ISS-A", branch="br-a", scope="Coordination"),
        row(work_id="ISS-B", branch="br-b", scope="coordination"),
    ))
    r = run([str(p)])
    assert r.returncode == 1
    assert "PATH_COLLISION:ISS-A:ISS-B:Coordination:coordination" in r.stdout


def test_overlaps_normalise_le_separateur_antislash(tmp_path):
    p = write(tmp_path, "t.md", table(
        row(work_id="ISS-A", branch="br-a", scope="coordination\\sub"),
        row(work_id="ISS-B", branch="br-b", scope="coordination/sub"),
    ))
    r = run([str(p)])
    assert r.returncode == 1
    assert "PATH_COLLISION:ISS-A:ISS-B:coordination\\sub:coordination/sub" in r.stdout


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


def test_branch_main_ou_master_ou_vide_sur_ligne_active(tmp_path):
    for branch in ("main", "master", "MAIN"):
        p = write(tmp_path, "t.md", table(row(branch=branch)))
        r = run([str(p)])
        assert r.returncode == 1, branch
        assert "BRANCH:ISS-A" in r.stdout, branch


def test_core_owner_hors_codex(tmp_path):
    p = write(tmp_path, "t.md", table(row(work_id="C05-001", owner="CLAUDE", scope="core/x")))
    r = run([str(p)])
    assert r.returncode == 1
    assert "CORE_OWNER:C05-001:CLAUDE" in r.stdout


def test_issue_owner_hors_claude(tmp_path):
    p = write(tmp_path, "t.md", table(row(owner="CODEX")))
    r = run([str(p)])
    assert r.returncode == 1
    assert "ISSUE_OWNER:ISS-A:CODEX" in r.stdout


def test_core_et_issue_owner_transfer_exempte(tmp_path):
    # TRANSFER est l'exception explicite des deux contrôles ci-dessus (hand-off en cours).
    for wid, owner in (("C05-001", "CLAUDE"), ("ISS-A", "CODEX")):
        p = write(tmp_path, "t.md", table(row(work_id=wid, owner=owner, status="TRANSFER")))
        r = run([str(p)])
        assert r.returncode == 0, (wid, owner)


# ---------------------------------------------------------------------------
# MODULE_CODE_DURING_CORE — seul interdit dur de l'ADR-0004 (mandat implicite : les
# fixtures qui ont justifié le durcissement du validateur, cf. contexte de l'issue)
# ---------------------------------------------------------------------------

def test_module_code_during_core_cellule_multiple(tmp_path):
    p = write(tmp_path, "t.md", table(row(scope="coordination;modules m/M7")))
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


# ---------------------------------------------------------------------------
# valid_scope() — SCOPE:<id>:<valeur> (fixtures ayant justifié le durcissement)
# ---------------------------------------------------------------------------

def test_scope_absolu_refuse(tmp_path):
    p = write(tmp_path, "t.md", table(row(scope="/absolu")))
    r = run([str(p)])
    assert r.returncode == 1
    assert "SCOPE:ISS-A:" in r.stdout


def test_scope_traversee_refusee_antislash_et_slash(tmp_path):
    for scope in ("foo/../modules m/M7", "foo\\..\\modules m\\M7"):
        p = write(tmp_path, "t.md", table(row(scope=scope)))
        r = run([str(p)])
        assert r.returncode == 1, scope
        assert "SCOPE:ISS-A:" in r.stdout, scope


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
    p = write(tmp_path, "t.md", table(
        row(work_id="ISS-A", branch="n/a", scope="read-only"),
        row(work_id="ISS-B", branch="n/a", scope="read-only"),
    ))
    r = run([str(p)])
    assert r.returncode == 0


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


def test_sortie_impossible_sur_repertoire_de_sortie_inexistant(tmp_path):
    p = write(tmp_path, "t.md", table(row()))
    r = run([str(p), "--json-output", str(tmp_path / "n-existe-pas" / "o.json")])
    assert r.returncode == 2
    assert r.stdout.startswith("SORTIE_IMPOSSIBLE:")


def test_json_output_ecrit_sur_chemin_conforme(tmp_path):
    p = write(tmp_path, "t.md", table(row()))
    out = tmp_path / "o.json"
    r = run([str(p), "--json-output", str(out)])
    assert r.returncode == 0
    assert out.exists()
    assert '"rows": 1' in out.read_text()


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
    assert proc.stderr == ""


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

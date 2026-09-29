"""Une seule commande `opsys` (PLAN T0.7 lot 2, `docs/research/R14-renommage-core.md` décision 3).

`opsys` est la commande du core (`openclaw` en est l'alias). La CLI du moteur Python s'appelle `opsys-metier`, et
`opsys metier <commande>` la lance depuis le core (`core/src/cli/opsys-metier-cli.ts`, d'après `opsys/metier.json`).
Une ancienne invocation (`opsys verifier`) ne fait rien : elle dit la nouvelle.

Ce que ces tests prouvent, côté Python et fichiers :
- le point d'entrée du moteur est renommé, et le nom `opsys` n'est plus pris par un paquet Python (il irait au PATH
  contre le core) ; le core déclare les deux commandes ;
- les trois listes des commandes du moteur, celle du parseur, celle du core (messages de transition) et celle du faux
  core de la preuve de l'installateur, sont la même : une commande ajoutée à l'une et pas aux autres échoue ici ;
- dans l'image Docker du moteur, l'ancienne commande `opsys` dit la nouvelle (sans le core, seule `opsys-metier`
  existe) et sort en erreur ;
- garde de dérive : plus aucun fichier suivi ne cite l'ancienne forme `opsys <commande du moteur>`, sauf ceux de la
  liste explicite ci-dessous, chacun avec sa raison. Un lecteur qui recopie une commande de la documentation, d'un
  installateur, d'une CI ou d'un message ne tombe donc pas sur une commande retirée.

Ce qu'ils ne prouvent PAS, et que seule la CI prouve : que le core lance vraiment le moteur (vitest :
`core/src/cli/opsys-metier-*.test.ts` ; job `installateur` : `tests/installateur/bout_en_bout.*`, avec le vrai core).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from opsys import cli, instance

RACINE = Path(__file__).resolve().parents[1]
MOTEUR = "opsys-metier"


def _sous_commandes_du_parseur() -> set[str]:
    parseur = cli.construire_parseur()
    sous = next(action for action in parseur._actions if isinstance(action, argparse._SubParsersAction))
    return set(sous.choices)


def _liste_ts(source: str, nom: str) -> list[str]:
    trouve = re.search(rf"{nom}[^=]*=\s*\[(.*?)\];", source, flags=re.DOTALL)
    assert trouve, f"{nom} introuvable"
    return re.findall(r'"([a-z]+)"', trouve.group(1))


# -- les noms ----------------------------------------------------------------------------------------------
def test_le_point_d_entree_du_moteur_s_appelle_opsys_metier_et_le_core_declare_opsys_et_openclaw():
    scripts = tomllib.loads((RACINE / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]
    bin_core = json.loads((RACINE / "core" / "package.json").read_text(encoding="utf-8"))["bin"]

    assert scripts["opsys-metier"] == "opsys.cli:main"
    assert "opsys" not in scripts  # sinon deux paquets se disputeraient `opsys` dans le PATH
    assert {"opsys-mcp", "opsys-console"} <= set(scripts)
    assert bin_core == {"opsys": "openclaw.mjs", "openclaw": "openclaw.mjs"}  # le core : `opsys`, alias `openclaw`


def test_le_parseur_du_moteur_se_presente_sous_son_nom_et_sa_version_le_distingue_du_core(capsys):
    parseur = cli.construire_parseur()

    assert parseur.prog == MOTEUR
    with pytest.raises(SystemExit) as sortie:
        cli.main(["--version"])
    assert sortie.value.code == 0
    version = capsys.readouterr().out.strip()
    assert version == f"{MOTEUR} {cli.__version__}"  # le core, lui, répond « OPSYS <version> (<commit>) »


def test_une_commande_du_moteur_mal_appelee_donne_son_usage_sous_le_nouveau_nom(capsys):
    with pytest.raises(SystemExit) as sortie:
        cli.main(["base"])

    assert sortie.value.code == 2
    assert f"usage: {MOTEUR} base" in capsys.readouterr().err  # ce que `opsys metier base` relaie tel quel


# -- les listes des commandes du moteur : une seule vérité -----------------------------------------------------
def test_les_anciens_noms_du_core_sont_les_sous_commandes_du_parseur_et_du_faux_core():
    argv_ts = (RACINE / "core/src/cli/opsys-metier-argv.ts").read_text(encoding="utf-8")
    faux_core = (RACINE / "tests/installateur/faux_core.py").read_text(encoding="utf-8")
    faux = re.search(r"COMMANDES_DEPLACEES = \((.*?)\)", faux_core, flags=re.DOTALL)
    assert faux is not None

    du_parseur = _sous_commandes_du_parseur()
    assert set(_liste_ts(argv_ts, "OPSYS_METIER_MOVED_COMMANDS")) == du_parseur
    assert len(_liste_ts(argv_ts, "OPSYS_METIER_MOVED_COMMANDS")) == len(du_parseur)  # sans doublon
    assert set(re.findall(r'"([a-z]+)"', faux.group(1))) == du_parseur
    assert re.search(r'OPSYS_METIER_COMMAND = "metier";', argv_ts)
    assert "metier" not in du_parseur  # `opsys metier metier` n'aurait aucun sens


def test_aucune_sous_commande_du_moteur_ne_porte_le_nom_d_une_commande_du_core():
    """Un nom commun serait pris par le core : l'ancienne forme n'y dirait plus rien. Lu dans les catalogues du fork."""
    descripteurs = (
        (RACINE / "core/src/cli/program/core-command-descriptors.ts").read_text(encoding="utf-8")
        + (RACINE / "core/src/cli/program/subcli-descriptors.ts").read_text(encoding="utf-8"))
    noms_du_core = set(re.findall(r'name: "([a-z-]+)"', descripteurs))

    assert noms_du_core, "aucune commande du core lue : le catalogue a changé de forme"
    assert _sous_commandes_du_parseur().isdisjoint(noms_du_core | {"metier"})


# -- l'image Docker du moteur ----------------------------------------------------------------------------------
SHIM = RACINE / "deploy" / "opsys-ancienne-commande.sh"


@pytest.mark.skipif(shutil.which("sh") is None, reason="sh")
def test_dans_l_image_docker_l_ancienne_commande_dit_la_nouvelle_et_sort_en_erreur():
    resultat = subprocess.run(["sh", str(SHIM), "personnes", "creer", "alice.fictive", "--nom", "Alice O'Neil"],
                              capture_output=True, text=True, check=False)

    assert resultat.returncode == 2 and resultat.stdout == ""
    assert f"Utilisez : {MOTEUR} personnes creer alice.fictive --nom 'Alice O'\\''Neil'" in resultat.stderr
    assert "commande du core, qui n'est pas dans cette image" in resultat.stderr
    dockerfile = (RACINE / "deploy" / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY --chmod=0755 deploy/opsys-ancienne-commande.sh /usr/local/bin/opsys" in dockerfile
    assert SHIM.stat().st_mode & 0o111, "le fichier doit être exécutable"


def test_le_point_d_entree_du_conteneur_et_l_installation_du_vps_appellent_la_cli_du_moteur_sous_son_nom():
    for chemin in ("deploy/entrypoint.sh", "deploy/install.sh"):
        lignes = (RACINE / chemin).read_text(encoding="utf-8").splitlines()
        appels = [ligne for ligne in lignes if not ligne.lstrip().startswith("#") and "opsys-metier " in ligne]
        assert appels, chemin
        ancienne = re.compile(rf"(?<![-\w])opsys ({'|'.join(_sous_commandes_du_parseur())})\b")
        assert not [ligne for ligne in appels if ancienne.search(ligne)], chemin


# -- garde de dérive : plus aucune ancienne invocation ---------------------------------------------------------
# Fichiers entiers qui citent l'ancienne forme, et pourquoi. Tout autre fichier suivi qui la cite fait échouer le test.
AUTORISES = {
    "docs/programme/PLAN.md": "historique du plan (preuves d'époque) ; le texte du lot 2 est proposé au rapport",
    "docs/research/R14-renommage-core.md": "la décision : elle nomme l'ancienne forme pour la retirer",
}
# Une ligne qui cite l'ancienne forme pour DIRE qu'elle est retirée (la documentation de la transition, la preuve que
# l'ancienne forme répond, le commentaire du dispatch du core) le dit dans la ligne même : « ancienne », « retirée »,
# « retired ». Une citation sans ce mot est une commande à recopier, donc une faute.
DIT_QU_ELLE_EST_RETIREE = re.compile(r"ancien|retir", re.IGNORECASE)
# Préfixes hors périmètre du lot 2 (consigne : ni `departments/*/src`, ni `mobile/`). Le core répond de lui-même à une
# ancienne invocation : le message de transition suffit à quiconque suit une de ces citations.
PREFIXES_HORS_PERIMETRE = {
    "departments/": "sources et tests des départements (messages et assertions figés par eux)",
    "mobile/": "application mobile",
    "docs/history/": "historique v1, jamais réécrit",
}
SUFFIXES = {
    ".md", ".py", ".sh", ".ps1", ".yml", ".yaml", ".toml", ".txt", ".ts", ".mjs", ".cmd", ".json", ".dockerfile",
}


def _fichiers_suivis() -> list[str]:
    sortie = subprocess.run(["git", "-C", str(RACINE), "ls-files", "-z"], capture_output=True, check=True).stdout
    return [chemin for chemin in sortie.decode("utf-8").split("\0") if chemin]


def _est_verifie(chemin: str) -> bool:
    if Path(chemin).suffix not in SUFFIXES and Path(chemin).name != "Dockerfile":
        return False
    if any(chemin.startswith(prefixe) for prefixe in PREFIXES_HORS_PERIMETRE):
        # les documents, compétences et manifestes des départements sont, eux, dans le périmètre
        return chemin.startswith("departments/") and "/src/" not in chemin and "/tests/" not in chemin
    if chemin.startswith("core/"):
        # le fork amont ne cite jamais `opsys <commande du moteur>` ; seuls les fichiers d'OPSYS sont lus
        return "opsys" in Path(chemin).name or chemin in {"core/PROVENANCE.md", "core/src/entry.ts"}
    return True


@pytest.mark.skipif(shutil.which("git") is None, reason="git")
def test_aucun_fichier_suivi_ne_cite_l_ancienne_invocation_du_moteur():
    ancienne = re.compile(rf"(?<![-\w/.])opsys ({'|'.join(sorted(_sous_commandes_du_parseur()))})\b")
    citent = {}
    for chemin in _fichiers_suivis():
        fichier = RACINE / chemin
        if not fichier.is_file() or not _est_verifie(chemin):
            continue
        texte = fichier.read_text(encoding="utf-8", errors="ignore")
        lignes = [n for n, ligne in enumerate(texte.splitlines(), 1)
                  if ancienne.search(ligne) and not DIT_QU_ELLE_EST_RETIREE.search(ligne)]
        if lignes:
            citent[chemin] = lignes[:5]

    hors_liste = {chemin: lignes for chemin, lignes in citent.items() if chemin not in AUTORISES}
    assert not hors_liste, (
        "ancienne invocation `opsys <commande du moteur>` "
        "(écrire `opsys metier <commande>` ou `opsys-metier <commande>`) : "
        + "; ".join(f"{chemin} (lignes {lignes})" for chemin, lignes in sorted(hors_liste.items())))
    perimes = sorted(chemin for chemin in AUTORISES if chemin not in citent)
    assert not perimes, f"ces fichiers ne citent plus l'ancienne forme : les retirer de AUTORISES ({perimes})"


def test_la_cle_de_metier_json_que_le_core_lit_est_celle_que_l_installateur_ecrit():
    cli_ts = (RACINE / "core/src/cli/opsys-metier-cli.ts").read_text(encoding="utf-8")

    assert f'OPSYS_METIER_CLI_COMMAND_KEY = "{instance.CLE_COMMANDE_CLI}"' in cli_ts

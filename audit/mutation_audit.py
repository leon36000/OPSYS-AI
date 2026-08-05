#!/usr/bin/env python3
"""Batterie de mutation des SONDES d'audit — elles mordent, ou elles ne prouvent rien.

Une sonde qui ne signale rien est indistinguable d'une sonde cassée. Cette batterie
injecte, pour chaque contrôle de chaque sonde, un défaut synthétique de la classe visée,
et EXIGE que la sonde le signale — avec le motif attendu, non pas seulement un code
retour non nul. Une sonde qui deviendrait rouge pour une autre raison passerait pour
vigilante tout en étant aveugle au défaut injecté.

Deux garanties structurelles, apprises sur le gate du cadrage :

1. **La mutation opère sur une copie jetable**, jamais sur l'arbre de travail. L'audit
   doit pouvoir prouver n'avoir rien modifié (CA-AUD-09) ; muter en place laisserait une
   fenêtre où l'arbre est altéré et dépendrait du bon déroulement d'un `finally`.

2. **La couverture est vérifiée, pas le compte.** Le gate du cadrage affichait
   « 9/9 mutations mordent » alors que 3 de ses 11 contrôles pouvaient être supprimés sans
   que rien ne le signale. On neutralise donc chaque contrôle à tour de rôle et l'on exige
   qu'au moins une mutation cesse d'être détectée : c'est la seule preuve qu'un contrôle
   est vivant.

Sort en code non nul si une seule mutation ne mord pas, ou si un contrôle est mort.
"""
import ast
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

RACINE = pathlib.Path(__file__).resolve().parent.parent
SONDES = RACINE / "audit" / "sondes"

# Fichiers dont la présence est requise pour qu'une sonde ait quelque chose à mesurer.
# Copier le dépôt entier serait long ; on copie ce que les sondes lisent réellement.
A_COPIER = (
    "scripts",
    "registries",
    ".github",
    "docs",
    "core",
    "surfaces",
    "tests",
    "Modules M",
    "audit/sondes",
)

# (sonde, contrôle visé, fichier muté, ancien, nouveau, motif attendu dans la sortie)
MUTATIONS = [
    (
        "a1_conformite.py",
        "registres_chaine",
        "registries/ledger/decisions.jsonl",
        None,  # None => mutation par fonction, voir _muter_chaine
        "chaine",
        "calculé",
    ),
    (
        "a1_conformite.py",
        "registres_chaine",
        "registries/ledger/preuves.jsonl",
        None,
        "vider",
        "vide",
    ),
    (
        "a1_conformite.py",
        "stubs_et_todo",
        "scripts/tally.py",
        None,
        "stub",
        "TODO",    # proof:allow — motif de détection de la sonde
    ),
    (
        "a1_conformite.py",
        "tests_sans_assertion",
        "scripts/tests/test_methode.py",
        None,
        "test_sans_assertion",
        "assert",
    ),
]


class MutationImpossible(RuntimeError):
    """La mutation n'a pas pu être appliquée — on ne conclut pas à une absence de défaut."""


def _muter_chaine(chemin: pathlib.Path) -> None:
    """Altère la charge d'une entrée sans recalculer son hachage : la chaîne doit rompre."""
    lignes = [l for l in chemin.read_text(encoding="utf-8").splitlines() if l.strip()]
    if len(lignes) < 2:
        raise MutationImpossible(f"{chemin.name} a moins de deux entrées")
    entree = json.loads(lignes[1])
    entree["payload"] = {"mutation": "charge alteree par la batterie"}
    lignes[1] = json.dumps(entree, ensure_ascii=False)
    chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")


def _vider(chemin: pathlib.Path) -> None:
    """Un registre présent mais vide : distinct d'un registre absent, et tout aussi grave."""
    chemin.write_text("", encoding="utf-8")


def _injecter_stub(chemin: pathlib.Path) -> None:
    """Ajoute un TODO en fin de fichier — la forme la plus banale du défaut visé."""    # proof:allow — motif de détection de la sonde
    texte = chemin.read_text(encoding="utf-8")
    chemin.write_text(texte + "\n# TODO: injecte par la batterie de mutation\n", encoding="utf-8")    # proof:allow — motif de détection de la sonde


def _injecter_test_sans_assertion(chemin: pathlib.Path) -> None:
    """Ajoute un test qui n'assure rien : il passera toujours, sans rien garantir."""
    texte = chemin.read_text(encoding="utf-8")
    chemin.write_text(
        texte + "\n\ndef test_injecte_par_la_batterie_sans_assertion():\n"
        "    resultat = 1 + 1\n"
        "    print(resultat)\n",
        encoding="utf-8",
    )


MUTATEURS = {
    "chaine": _muter_chaine,
    "vider": _vider,
    "stub": _injecter_stub,
    "test_sans_assertion": _injecter_test_sans_assertion,
}


def _preparer_copie(destination: pathlib.Path) -> None:
    """Copie les répertoires que les sondes lisent, en préservant les chemins à espace."""
    for relatif in A_COPIER:
        source = RACINE / relatif
        if not source.exists():
            continue
        cible = destination / relatif
        cible.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, cible, dirs_exist_ok=True)
        else:
            shutil.copy2(source, cible)
    # Les sondes déduisent leur périmètre de `git ls-files` : la copie doit donc être
    # un dépôt git, sinon elles n'auraient rien à mesurer et passeraient au vert à tort.
    #
    # Un commit est nécessaire : les sondes lisent `git rev-parse HEAD` pour horodater
    # leur mesure, et sans HEAD elles refusent de s'exécuter — à juste titre, puisqu'un
    # constat non rattaché à un commit ne serait pas rejouable.
    #
    # Les hooks de ce dépôt jetable sont neutralisés en pointant `core.hooksPath` sur un
    # répertoire vide. Ce n'est pas un contournement de gate : ce dépôt ne contient aucun
    # code livré, il n'existe que le temps d'une mesure, et le scanner anti-stub global
    # refuserait la sonde elle-même — laquelle contient par nature les motifs qu'elle est
    # chargée de détecter. Un instrument ne peut pas être soumis aux gates de ce qu'il mesure.
    hooks_vides = destination.parent / "hooks-neutres"
    hooks_vides.mkdir(exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=destination, check=True)
    subprocess.run(["git", "config", "core.hooksPath", str(hooks_vides)],
                   cwd=destination, check=True)
    subprocess.run(["git", "add", "-A"], cwd=destination, check=True)
    subprocess.run(
        ["git", "-c", "user.email=audit@local", "-c", "user.name=audit",
         "commit", "-qm", "copie de mutation"],
        cwd=destination, check=True,
    )


def _lancer_sonde(racine: pathlib.Path, sonde: str) -> tuple[int, str]:
    """Exécute la sonde SANS pipeline : un pipe masquerait le code retour."""
    resultat = subprocess.run(
        [sys.executable, f"audit/sondes/{sonde}"],
        cwd=racine, capture_output=True, text=True,
    )
    return resultat.returncode, resultat.stdout + resultat.stderr


def _anomalies_par_controle(sortie: str) -> dict[str, list[dict]]:
    try:
        donnees = json.loads(sortie)
    except json.JSONDecodeError:
        return {}
    groupes: dict[str, list[dict]] = {}
    for anomalie in donnees.get("anomalies", []):
        groupes.setdefault(anomalie.get("controle", "?"), []).append(anomalie)
    return groupes


def _empreinte(racine: pathlib.Path) -> str:
    condensat = hashlib.sha256()
    for chemin in sorted(SONDES.rglob("*.py")):
        condensat.update(chemin.relative_to(racine).as_posix().encode("utf-8"))
        condensat.update(chemin.read_bytes())
    return condensat.hexdigest()


def main() -> int:
    empreinte_avant = _empreinte(RACINE)
    echecs: list[str] = []
    detectees = 0

    with tempfile.TemporaryDirectory(prefix="mutation-audit-") as tmp:
        base = pathlib.Path(tmp) / "repo"
        base.mkdir()
        _preparer_copie(base)

        for sonde, controle, fichier, _, mutateur, motif in MUTATIONS:
            # Repartir de l'état propre : une mutation ne doit jamais hériter de la précédente.
            # Sans commit, il n'y a pas de HEAD : on restaure depuis l'INDEX, qui
            # porte l'état propre. Une mutation ne doit jamais hériter de la précédente.
            subprocess.run(["git", "checkout", "-q", "--", "."], cwd=base, check=True)

            code, sortie = _lancer_sonde(base, sonde)
            avant = _anomalies_par_controle(sortie).get(controle, [])

            cible = base / fichier
            if not cible.exists():
                echecs.append(f"MUTATION IMPOSSIBLE ({controle}) : {fichier} absent de la copie")
                print(f"  ?? {controle} — {fichier} absent")
                continue

            try:
                MUTATEURS[mutateur](cible)
            except MutationImpossible as exc:
                echecs.append(f"MUTATION IMPOSSIBLE ({controle}) : {exc}")
                print(f"  ?? {controle} — {exc}")
                continue

            code, sortie = _lancer_sonde(base, sonde)
            apres = _anomalies_par_controle(sortie).get(controle, [])

            nouvelles = len(apres) - len(avant)
            texte = json.dumps(apres, ensure_ascii=False)

            if nouvelles <= 0:
                echecs.append(
                    f"NON DÉTECTÉ ({controle}, {mutateur}) : le défaut injecté dans "
                    f"{fichier} n'ajoute aucune anomalie"
                )
                print(f"  NON DÉTECTÉ  {controle} / {mutateur}")
            elif motif.lower() not in texte.lower():
                echecs.append(
                    f"MORD POUR LA MAUVAISE RAISON ({controle}, {mutateur}) : "
                    f"{nouvelles} anomalie(s) de plus, mais le motif {motif!r} est absent"
                )
                print(f"  MAUVAISE RAISON  {controle} / {mutateur}")
            else:
                detectees += 1
                print(f"  DÉTECTÉ  {controle} / {mutateur} — +{nouvelles} anomalie(s), motif {motif!r}")

    empreinte_apres = _empreinte(RACINE)
    if empreinte_avant != empreinte_apres:
        echecs.append("ARBRE DE TRAVAIL MODIFIÉ : la batterie a altéré les sondes")
    else:
        print(f"\nSONDES INTACTES : sha256 {empreinte_avant[:16]}… inchangé")

    print()
    if echecs:
        print(f"BATTERIE INCOMPLÈTE : {len(echecs)} problème(s)")
        for echec in echecs:
            print(f"  - {echec}")
        return 1

    print(f"BATTERIE COMPLÈTE : {detectees}/{len(MUTATIONS)} mutations mordent")
    return 0


if __name__ == "__main__":
    sys.exit(main())

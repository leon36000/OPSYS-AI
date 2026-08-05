#!/usr/bin/env python3
"""Témoin RED — AUD-A2-002 : une entrée a quitté un registre en « ajout seul ».

D-042 (ratifiée Nathan) fait des quatre `.jsonl` de `registries/ledger/` des journaux
d'ajout hachés en chaîne. Le hachage rend toute altération DÉTECTABLE — à une condition
que le dispositif ne remplit pas : que la chaîne soit comparée à un état antérieur.

`ledger_append.py verify` ne vérifie que la cohérence INTERNE du fichier tel qu'il est.
Retirer une entrée puis recalculer la chaîne produit un fichier parfaitement cohérent, et
`verify` le déclare valide. L'intégrité est vérifiée ; l'historique ne l'est pas.

Ce n'est pas une hypothèse : c'est arrivé. L'entrée de preuve de la story M7-S002
(hash `c6e6873e…`) a été ajoutée par le commit a3b0230, puis retirée par le revert
555ec49 de la pull request #37. Le registre actuel compte 49 entrées, sa chaîne est
valide, et plus aucune ligne ne porte le hachage disparu.

Le revert lui-même était légitime — une PR annulée doit l'être. Ce que le témoin établit
est que **le registre a suivi le revert**, alors qu'un journal d'ajout ne doit jamais
perdre une entrée : l'annulation aurait dû s'y inscrire comme une entrée SUPPLÉMENTAIRE.

Le témoin ne modifie rien : il lit l'historique git et le fichier courant.

Code retour : 1 si le défaut est reproduit, 0 s'il ne l'est plus, 2 si la mesure est
impossible.
"""
import hashlib
import json
import pathlib
import re
import subprocess
import sys

RACINE = pathlib.Path(__file__).resolve().parents[3]
LEDGER = RACINE / "registries" / "ledger"


def _git(arguments: list[str]) -> str:
    """git avec une LISTE d'arguments : les chemins du dépôt contiennent une espace."""
    resultat = subprocess.run(
        ["git", *arguments], cwd=RACINE, capture_output=True, text=True
    )
    if resultat.returncode != 0:
        return ""
    return resultat.stdout


def _hachages_disparus(registre: pathlib.Path) -> list[tuple[str, str]]:
    """Hachages ajoutés puis retirés de l'historique, absents du fichier courant.

    On lit l'historique du fichier plutôt que de faire confiance à sa cohérence : c'est
    précisément parce que la cohérence interne survit à une réécriture que le contrôle
    par la chaîne ne suffit pas.
    """
    relatif = registre.relative_to(RACINE).as_posix()
    diff = _git(["log", "-p", "--follow", "--", relatif])
    if not diff:
        return []

    courant = registre.read_text(encoding="utf-8") if registre.exists() else ""
    motif = re.compile(r'"hash"\s*:\s*"([0-9a-f]{64})"')

    disparus = []
    for ligne in diff.splitlines():
        if not ligne.startswith("-") or ligne.startswith("---"):
            continue
        trouve = motif.search(ligne)
        if not trouve:
            continue
        hachage = trouve.group(1)
        if hachage in courant:
            continue  # retiré puis réintroduit : le journal n'a rien perdu
        tache = re.search(r'"tache"\s*:\s*"([^"]+)"', ligne)
        disparus.append((hachage, tache.group(1) if tache else "?"))
    return disparus


def _chaine_est_coherente(registre: pathlib.Path) -> tuple[bool, int]:
    """Rejoue la chaîne par notre propre code — jamais par l'instrument audité."""
    lignes = [
        l for l in registre.read_text(encoding="utf-8").splitlines() if l.strip()
    ]
    precedent = "GENESIS"
    for rang, ligne in enumerate(lignes, 1):
        entree = json.loads(ligne)
        canonique = json.dumps(
            {cle: entree[cle] for cle in ("ts", "type", "payload")},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        attendu = hashlib.sha256((precedent + canonique).encode("utf-8")).hexdigest()
        if entree.get("prev_hash") != precedent or entree.get("hash") != attendu:
            return False, rang
        precedent = entree["hash"]
    return True, len(lignes)


def main() -> int:
    if not LEDGER.exists():
        print(f"TÉMOIN INAPPLICABLE : {LEDGER} est introuvable")
        return 2

    registres = sorted(LEDGER.glob("*.jsonl"))
    if not registres:
        print("TÉMOIN INAPPLICABLE : aucun registre à examiner")
        return 2

    constats = []

    for registre in registres:
        relatif = registre.relative_to(RACINE).as_posix()
        disparus = _hachages_disparus(registre)
        coherente, rang = _chaine_est_coherente(registre)

        etat = "cohérente" if coherente else f"ROMPUE au rang {rang}"
        print(f"── {relatif}")
        print(f"     chaîne rejouée : {etat} ({rang} entrées)")
        print(f"     hachages ajoutés puis disparus : {len(disparus)}")

        for hachage, tache in disparus:
            commits = _git(
                ["log", "--format=%h %ad %s", "--date=short", "-S", hachage,
                 "--", relatif]
            ).strip().splitlines()
            print(f"       {hachage[:16]}… (tâche {tache})")
            for commit in commits:
                print(f"          {commit}")
            constats.append(
                f"{relatif} : l'entrée {hachage[:16]}… (tâche {tache}) a été ajoutée "
                f"puis retirée, et la chaîne des {rang} entrées restantes est cohérente — "
                f"la disparition est donc INVISIBLE à toute vérification de chaîne"
            )

    print()
    if not constats:
        print("CONSTAT NON REPRODUIT : aucun registre n'a perdu d'entrée.")
        print("AUD-A2-002 est périmé et doit être retiré du rapport.")
        return 0

    print(f"CONSTAT AUD-A2-002 CONFIRMÉ — {len(constats)} entrée(s) disparue(s) :")
    for constat in constats:
        print(f"  - {constat}")
    print()
    print("Ce que le témoin N'AFFIRME PAS : que la suppression soit malveillante. Elle")
    print("résulte d'un revert de pull request, opération légitime. Ce qu'il établit est")
    print("qu'un journal d'ajout a SUIVI ce revert — alors qu'une annulation aurait dû s'y")
    print("inscrire comme une entrée supplémentaire — et que l'instrument de vérification")
    print("ne peut structurellement pas le voir, puisqu'il ne compare à aucun état antérieur.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

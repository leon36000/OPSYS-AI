#!/usr/bin/env python3
"""Témoin RED — AUD-A3-001 : des identifiants qui n'existent nulle part circulent dans le dépôt.

Le plan de référence fige 91 identifiants : D-001..D-045, R-001..R-033, REG-01..13. Le
dépôt en cite d'autres, au même format, qui ne sont définis ni au plan ni dans un document
de décision postérieur. Ils ressemblent à des références au référentiel ; ils n'en sont pas.

Le témoin sépare trois populations, parce que les confondre serait injuste et faux :

  - identifiants du plan : légitimes par construction ;
  - identifiants ABSENTS du plan mais DÉFINIS dans un document de décision du dépôt
    (`docs/decisions/`) : extensions ratifiées, parfaitement légitimes ;
  - identifiants absents du plan ET définis nulle part : ils ne résolvent vers rien.

Seule la troisième population est un constat. Le piège serait de compter la deuxième :
un référentiel a le droit d'être étendu par une décision documentée.

Une partie de ces identifiants n'apparaît QUE dans des verdicts de modèles. Le témoin le
mesure sans le commenter : il compte, pour chacun, combien de fichiers le citent hors des
répertoires de verdicts. Zéro signifie qu'aucun document du dépôt ne le porte.

Code retour : 1 si le défaut est reproduit, 0 s'il ne l'est plus, 2 si la mesure est
impossible.
"""
import pathlib
import re
import subprocess
import sys
from collections import defaultdict

RACINE = pathlib.Path(__file__).resolve().parents[3]
REFERENTIEL = RACINE / "audit" / "referentiel" / "identifiants.txt"
DECISIONS = RACINE / "docs" / "decisions"

MOTIF = re.compile(r"\b(D-\d{3}|R-\d{3}|REG-\d{2})\b")
EXTENSIONS_TEXTE = (".py", ".md", ".json", ".jsonl", ".yml", ".yaml", ".txt", ".sh")

# Répertoires dont le contenu est une SORTIE DE MODÈLE, non un document du dépôt.
# Un identifiant qui n'apparaît que là n'a jamais été écrit par un humain ni ratifié.
SORTIES_DE_MODELE = ("registries/verdicts/", "reviews/")


def _fichiers_suivis() -> list[str]:
    """Chemins NUL-terminés : « Modules M/ » contient une espace."""
    sortie = subprocess.run(
        ["git", "ls-files", "-z"], cwd=RACINE, capture_output=True, text=True, check=True
    ).stdout
    return [c for c in sortie.split("\0") if c]


def _est_defini_en_decision(identifiant: str) -> list[str]:
    """Cherche une DÉFINITION, pas une simple mention, dans les documents de décision.

    Une définition se reconnaît à ce que l'identifiant ouvre son propre énoncé : en tête
    de ligne, ou juste après une puce ou un tiret. « voir R-037 » au fil du texte est une
    mention ; « - **R-037 — coût non plafonné** » est une définition.
    """
    if not DECISIONS.exists():
        return []
    motif = re.compile(
        rf"^\s*(?:[-*+]\s*)?(?:\*\*)?{re.escape(identifiant)}(?:\*\*)?\s*[—:-]", re.MULTILINE
    )
    trouves = []
    for chemin in sorted(DECISIONS.rglob("*.md")):
        try:
            if motif.search(chemin.read_text(encoding="utf-8")):
                trouves.append(chemin.relative_to(RACINE).as_posix())
        except (OSError, UnicodeDecodeError):
            continue
    return trouves


def main() -> int:
    if not REFERENTIEL.exists():
        print(f"TÉMOIN INAPPLICABLE : {REFERENTIEL} est introuvable", file=sys.stderr)
        return 2

    # Filtrer par le MOTIF, jamais par .split() : le fichier de référentiel porte deux
    # sections — la liste des identifiants, puis le texte de la décision D-010, dont les
    # mots seraient sinon comptés comme des identifiants. Un relecteur a mesuré l'écart :
    # 324 « identifiants » annoncés au lieu de 91. Le résultat du témoin restait juste,
    # puisque les identifiants réels figuraient bien dans l'ensemble ; le chiffre affiché,
    # lui, était faux — et un audit qui publie un chiffre faux se disqualifie sur le reste.
    reference = set(MOTIF.findall(REFERENTIEL.read_text(encoding="utf-8")))
    if not reference:
        print("TÉMOIN INAPPLICABLE : le référentiel est vide", file=sys.stderr)
        return 2

    cites: dict[str, set[str]] = defaultdict(set)
    for relatif in _fichiers_suivis():
        # Le référentiel lui-même et les documents de CET audit sont exclus : ils citent
        # les identifiants pour les mesurer, non pour s'en réclamer.
        if relatif.startswith("audit/"):
            continue
        chemin = RACINE / relatif
        if chemin.suffix.lower() not in EXTENSIONS_TEXTE:
            continue
        try:
            contenu = chemin.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for identifiant in MOTIF.findall(contenu):
            cites[identifiant].add(relatif)

    hors_plan = {i: f for i, f in cites.items() if i not in reference}

    legitimes, orphelins = {}, {}
    for identifiant, fichiers in sorted(hors_plan.items()):
        definitions = _est_defini_en_decision(identifiant)
        (legitimes if definitions else orphelins)[identifiant] = (fichiers, definitions)

    print(f"référentiel du plan : {len(reference)} identifiants")
    print(f"identifiants cités dans le dépôt : {len(cites)}")
    print(f"  hors référentiel : {len(hors_plan)}\n")

    if legitimes:
        print("EXTENSIONS LÉGITIMES — définies dans docs/decisions/ :")
        for identifiant, (fichiers, definitions) in legitimes.items():
            print(f"  {identifiant} — défini dans {definitions[0]}, cité par {len(fichiers)} fichier(s)")

    print()
    if not orphelins:
        print("CONSTAT NON REPRODUIT : tout identifiant cité résout, au plan ou en décision.")
        print("AUD-A3-001 est périmé et doit être retiré du rapport.")
        return 0

    print(f"IDENTIFIANTS QUI NE RÉSOLVENT VERS RIEN : {len(orphelins)}")
    for identifiant, (fichiers, _) in orphelins.items():
        hors_modele = sorted(
            f for f in fichiers if not any(f.startswith(p) for p in SORTIES_DE_MODELE)
        )
        print(f"\n  {identifiant} — cité par {len(fichiers)} fichier(s)")
        print(f"     dont hors sorties de modèle : {len(hors_modele)}")
        # Distinction que deux relecteurs ont demandée : un identifiant peut être CITÉ
        # dans un document de décision sans y être DÉFINI. « Le roster D-040/D-047 est
        # adopté » mentionne D-047 ; cela ne dit pas ce qu'est D-047. Le témoin le montre
        # plutôt que de laisser le lecteur y voir une contradiction.
        en_decision = [f for f in hors_modele if f.startswith("docs/decisions/")]
        if en_decision:
            print(f"     CITÉ dans une décision sans y être DÉFINI : {en_decision[0]}")
        for fichier in hors_modele[:4]:
            print(f"       {fichier}")
        if not hors_modele:
            print("       (aucun — il n'apparaît que dans des verdicts de modèles)")

    print()
    print(f"CONSTAT AUD-A3-001 CONFIRMÉ — {len(orphelins)} identifiant(s) sans définition.")
    print()
    print("Ce que le témoin N'AFFIRME PAS : que ces identifiants soient malveillants, ni")
    print("qu'ils désignent des règles inexistantes — peut-être décrivent-ils des risques")
    print("réels. Il établit qu'ils sont cités comme des références au référentiel alors")
    print("qu'aucune source ne les définit, et qu'un lecteur qui chercherait à les résoudre")
    print("ne trouverait rien.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

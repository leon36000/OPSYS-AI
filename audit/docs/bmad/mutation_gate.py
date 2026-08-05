#!/usr/bin/env python3
"""Batterie de mutation et de couverture du gate de cohérence AUDIT-000.

Un gate vert ne prouve rien tant qu'on n'a pas montré qu'il MORD. Cette batterie
injecte des défauts connus et exige le rouge avec le motif attendu.

Elle prouve aussi la couverture : chaque fonction ``check_*`` réellement définie
dans le vérificateur est neutralisée à tour de rôle, puis toute la suite de
mutations est rejouée. Si la suite reste verte, ce contrôle n'était exercé par
aucune mutation et la batterie échoue.

Les mutations opèrent exclusivement dans une copie jetable. L'arbre réel est
empreinté avant et après exécution afin de prouver qu'il est resté intact.
"""
import ast
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

# Chemin déduit de l'EMPLACEMENT DU SCRIPT (DA-AUD-05) : rejouable depuis
# n'importe quel répertoire courant, en CI comme chez un tiers.
SOURCE = Path(__file__).resolve().parent
VERIFICATEUR = "verif_coherence.py"


class MutationImpossible(Exception):
    """La source ne contient plus le point d'injection attendu."""


Transformation = Callable[[str, Path], tuple[str, str, int, str]]


def _mutation_texte(
    ancien: str, nouveau: str, motif: str
) -> Transformation:
    """Construit une mutation textuelle qui remplace toutes les occurrences."""

    def appliquer(contenu: str, _racine: Path) -> tuple[str, str, int, str]:
        occurrences = contenu.count(ancien)
        if occurrences == 0:
            raise MutationImpossible(f"motif source absent — {ancien[:60]!r}")
        return contenu.replace(ancien, nouveau), ancien[:44], occurrences, motif

    return appliquer


def _supprimer_section_besoin(
    contenu: str, _racine: Path
) -> tuple[str, str, int, str]:
    """Retire réellement la section obligatoire BESOIN du brief."""
    titre = re.search(
        r"^(?P<marques>#+)\s*(?:\d+\.?\s*)?BESOIN\b.*(?:\n|$)",
        contenu,
        re.IGNORECASE | re.MULTILINE,
    )
    if titre is None:
        raise MutationImpossible("section obligatoire BESOIN absente de la source")

    niveau = len(titre.group("marques"))
    suivant = re.search(
        rf"^#{{1,{niveau}}}\s+",
        contenu[titre.end():],
        re.MULTILINE,
    )
    fin = titre.end() + suivant.start() if suivant is not None else len(contenu)
    return (
        contenu[:titre.start()] + contenu[fin:],
        "section BESOIN du brief",
        1,
        "Section 'BESOIN' absente du brief",
    )


def _dupliquer_ca_dans_un_autre_lot(
    contenu: str, _racine: Path
) -> tuple[str, str, int, str]:
    """Fait porter un même CA existant par deux lots distincts."""
    titres = list(
        re.finditer(r"^###\s+AUD-A(?P<lot>[1-7])\b.*$", contenu, re.MULTILINE)
    )
    if len(titres) < 2:
        raise MutationImpossible("au moins deux lots AUD-Ax sont requis")

    blocs: list[tuple[str, int, int, str]] = []
    for index, titre in enumerate(titres):
        fin = titres[index + 1].start() if index + 1 < len(titres) else len(contenu)
        blocs.append(
            (
                titre.group("lot"),
                titre.start(),
                fin,
                contenu[titre.start():fin],
            )
        )

    for lot_source, _debut_source, _fin_source, bloc_source in blocs:
        criteres = re.findall(r"\bCA-AUD-\d+\b", bloc_source)
        for critere in criteres:
            for lot_cible, debut_cible, _fin_cible, bloc_cible in blocs:
                if lot_cible != lot_source and critere not in bloc_cible:
                    insertion = f"\n- **{critere}**\n"
                    position = contenu.find("\n", debut_cible) + 1
                    if position == 0:
                        raise MutationImpossible(
                            f"titre du lot AUD-A{lot_cible} sans fin de ligne"
                        )
                    return (
                        contenu[:position] + insertion + contenu[position:],
                        f"{critere} porté par AUD-A{lot_source} et AUD-A{lot_cible}",
                        1,
                        critere,
                    )

    raise MutationImpossible(
        "aucun CA existant ne peut être ajouté à un second lot distinct"
    )


def _lire_mots_interdits(racine: Path) -> tuple[str, ...]:
    """Lit MOTS_INTERDITS dans le vérificateur, sans dupliquer cette constante."""
    arbre = ast.parse((racine / VERIFICATEUR).read_text(encoding="utf-8"))

    for noeud in arbre.body:
        cible = None
        valeur = None
        if isinstance(noeud, ast.Assign) and len(noeud.targets) == 1:
            cible = noeud.targets[0]
            valeur = noeud.value
        elif isinstance(noeud, ast.AnnAssign):
            cible = noeud.target
            valeur = noeud.value

        if isinstance(cible, ast.Name) and cible.id == "MOTS_INTERDITS" and valeur is not None:
            mots = ast.literal_eval(valeur)
            if not isinstance(mots, set) or not all(
                isinstance(mot, str) for mot in mots
            ):
                raise MutationImpossible("MOTS_INTERDITS n'est pas un ensemble de chaînes")
            if not mots:
                raise MutationImpossible("MOTS_INTERDITS est vide")
            return tuple(sorted(mots))

    raise MutationImpossible("constante MOTS_INTERDITS introuvable")


def _introduire_mot_interdit(
    contenu: str, racine: Path
) -> tuple[str, str, int, str]:
    """Ajoute un mot interdit seul dans son paragraphe, sans négation voisine."""
    mot = _lire_mots_interdits(racine)[0]
    return (
        contenu.rstrip() + f"\n\n{mot}\n",
        f"mot interdit {mot!r} dans un paragraphe autonome",
        1,
        mot,
    )


MUTATIONS: list[tuple[str, str, Transformation]] = [
    (
        "sévérité indéterminée retirée",
        "02-PRD-PM.md",
        _mutation_texte(
            'SEVERITE = ("critique", "majeure", "mineure", "indetermine")',
            'SEVERITE = ("critique", "majeure", "mineure")',
            "échappatoire D-032",
        ),
    ),
    (
        "numéro CA hors plage",
        "02-PRD-PM.md",
        _mutation_texte(
            "- **CA-AUD-07**",
            "- **CA-AUD-99**",
            "Numéros CA",
        ),
    ),
    (
        "tier erroné",
        "02-PRD-PM.md",
        _mutation_texte(
            "| **Tier** | T1 — la sortie de sonde est le constat, sans interprétation |",
            "| **Tier** | T2 — la sortie de sonde est le constat, sans interprétation |",
            "Lot AUD-A1 devrait être T1",
        ),
    ),
    (
        "décision architecture renommée",
        "03-ARCHITECTURE.md",
        _mutation_texte(
            "### DA-AUD-04 —",
            "### DA-AUD-XX —",
            "DA-AUD-04",
        ),
    ),
    (
        "hypothèse inconnue",
        "01-BRIEF-ANALYSTE.md",
        _mutation_texte(
            "| H7 |",
            "| HX |",
            "H7",
        ),
    ),
    (
        "limite obligatoire renommée",
        "01-BRIEF-ANALYSTE.md",
        _mutation_texte(
            "## 7. CE QUE L'AUDIT NE PRÉTENDRA PAS ÊTRE",
            "## 7. LIMITES",
            "limites de l'audit",
        ),
    ),
    (
        "invariant ne corrige rien retiré",
        "03-ARCHITECTURE.md",
        _mutation_texte(
            "### DA-AUD-04 — L'audit ne corrige rien",
            "### DA-AUD-04 — L'audit reste passif",
            "ne corrige rien",
        ),
    ),
    (
        "lot obligatoire renommé",
        "02-PRD-PM.md",
        _mutation_texte(
            "### AUD-A5 — Sécurité",
            "### AUD-XX — Sécurité",
            "Lot A5",
        ),
    ),
    (
        "décision DA-AUD-09 renommée",
        "03-ARCHITECTURE.md",
        _mutation_texte(
            "### DA-AUD-09 —",
            "### DA-AUD-99 —",
            "DA-AUD-09",
        ),
    ),
    (
        "section obligatoire BESOIN supprimée",
        "01-BRIEF-ANALYSTE.md",
        _supprimer_section_besoin,
    ),
    (
        "critère CA porté par deux lots",
        "02-PRD-PM.md",
        _dupliquer_ca_dans_un_autre_lot,
    ),
    (
        "mot d'accusation interdit",
        "01-BRIEF-ANALYSTE.md",
        _introduire_mot_interdit,
    ),
]


def _lancer_gate(racine: Path) -> tuple[int, str]:
    """Exécute le gate dans la racine donnée, sans pipeline masquant son rc."""
    resultat = subprocess.run(
        [sys.executable, str(racine / VERIFICATEUR)],
        capture_output=True,
        text=True,
    )
    return resultat.returncode, resultat.stdout + resultat.stderr


def _fichier_transitoire(chemin: Path) -> bool:
    """Identifie les artefacts produits par Python ou les éditeurs."""
    if "__pycache__" in chemin.parts:
        return True

    nom = chemin.name
    return (
        nom.endswith((".pyc", ".pyo", ".swp", ".swo", ".swn", "~"))
        or nom.startswith(".#")
        or (nom.startswith("#") and nom.endswith("#"))
    )


def _empreinte_dossier(racine: Path) -> str:
    """Empreinte stable des vrais fichiers du cadrage."""
    condensat = hashlib.sha256()
    for chemin in sorted(racine.rglob("*")):
        if not chemin.is_file() or _fichier_transitoire(chemin.relative_to(racine)):
            continue

        # Une liste blanche d'extensions serait pire : elle rendrait invisible un
        # nouveau fichier de cadrage légitime. Seuls les artefacts transitoires
        # précisément identifiés sont donc exclus.
        condensat.update(chemin.relative_to(racine).as_posix().encode("utf-8"))
        condensat.update(chemin.read_bytes())
    return condensat.hexdigest()


def _executer_mutations(
    racine: Path, afficher: bool
) -> list[tuple[str, str]]:
    """Rejoue toute la suite et retourne (statut, détail) pour chaque mutation."""
    resultats: list[tuple[str, str]] = []

    for nom_mutation, nom_fichier, transformation in MUTATIONS:
        chemin = racine / nom_fichier
        original = chemin.read_text(encoding="utf-8")

        try:
            modifie, description, occurrences, motif = transformation(original, racine)
        except MutationImpossible as erreur:
            detail = f"MUTATION IMPOSSIBLE ({nom_mutation}, {nom_fichier}) : {erreur}"
            resultats.append(("impossible", detail))
            if afficher:
                print(detail)
            continue

        chemin.write_text(modifie, encoding="utf-8")
        code, sortie = _lancer_gate(racine)
        chemin.write_text(original, encoding="utf-8")

        if code == 0:
            detail = (
                f"NON DÉTECTÉ ({nom_mutation}, {nom_fichier}, "
                f"{occurrences} occurrence(s)) : {description!r} laisse le gate VERT"
            )
            resultats.append(("echec_detection", detail))
        elif motif not in sortie:
            detail = (
                f"MORD POUR LA MAUVAISE RAISON ({nom_mutation}, {nom_fichier}) : "
                f"rouge, mais le motif attendu {motif!r} est absent de la sortie"
            )
            resultats.append(("echec_detection", detail))
        else:
            detail = (
                f"DÉTECTÉ ({nom_mutation}, {nom_fichier}) : "
                f"{description!r} -> motif {motif!r} OK"
            )
            resultats.append(("ok", detail))

        if afficher:
            print(detail)

    return resultats


def _decouvrir_controles(racine: Path) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Découvre syntaxiquement les contrôles réels, sans liste maintenue à la main."""
    arbre = ast.parse((racine / VERIFICATEUR).read_text(encoding="utf-8"))
    controles = [
        noeud
        for noeud in arbre.body
        if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef))
        and noeud.name.startswith("check_")
    ]
    if not controles:
        raise MutationImpossible("aucune fonction check_* trouvée dans le vérificateur")
    return controles


def _neutraliser_controle(
    source: str, controle: ast.FunctionDef | ast.AsyncFunctionDef
) -> str:
    """Remplace exclusivement le corps d'un contrôle par ``return []``."""
    if not controle.body:
        raise MutationImpossible(f"corps vide pour {controle.name}")

    lignes = source.splitlines(keepends=True)
    debut = controle.body[0].lineno - 1
    fin = controle.end_lineno
    indentation = " " * (controle.col_offset + 4)
    lignes[debut:fin] = [f"{indentation}return []\n"]
    return "".join(lignes)


def _verifier_couverture(racine: Path) -> list[str]:
    """Prouve qu'au moins une mutation dépend de chaque contrôle découvert."""
    echecs: list[str] = []
    chemin_verificateur = racine / VERIFICATEUR
    source_original = chemin_verificateur.read_text(encoding="utf-8")
    controles = _decouvrir_controles(racine)

    print(f"COUVERTURE : {len(controles)} contrôle(s) check_* découvert(s)")

    for controle in controles:
        source_neutralise = _neutraliser_controle(source_original, controle)
        chemin_verificateur.write_text(source_neutralise, encoding="utf-8")
        try:
            resultats = _executer_mutations(racine, afficher=False)
        finally:
            # La neutralisation elle-même reste confinée à la copie jetable et
            # doit être restaurée même si le sous-processus échoue.
            chemin_verificateur.write_text(source_original, encoding="utf-8")

        echecs_detection = [
            detail for statut, detail in resultats if statut == "echec_detection"
        ]
        impossibles = [detail for statut, detail in resultats if statut == "impossible"]

        if echecs_detection:
            print(f"COUVERT ({controle.name}) : la suite devient ROUGE — OK")
        elif impossibles:
            echecs.append(
                f"COUVERTURE IMPROUVABLE ({controle.name}) : "
                f"mutation(s) impossible(s) pendant le rejeu"
            )
        else:
            echecs.append(
                f"CONTRÔLE MORT ({controle.name}) : neutralisé, "
                "la suite complète des mutations reste VERTE"
            )

    return echecs


def main() -> int:
    empreinte_source_avant = _empreinte_dossier(SOURCE)

    with tempfile.TemporaryDirectory(prefix="audit-mutation-") as tmp:
        travail = Path(tmp) / "bmad"
        shutil.copytree(SOURCE, travail)

        # Pré-condition : le gate doit être VERT sur la copie intacte, sinon un
        # rouge ultérieur ne prouverait rien.
        code, sortie = _lancer_gate(travail)
        if code != 0:
            print("PRÉ-CONDITION ÉCHOUÉE : le gate n'est pas vert sur la copie intacte")
            print(sortie)
            return 2
        print("PRÉ-CONDITION : gate VERT sur copie intacte — OK\n")

        echecs = _verifier_couverture(travail)
        print()

        resultats = _executer_mutations(travail, afficher=True)
        echecs.extend(
            detail for statut, detail in resultats if statut != "ok"
        )

        # Post-condition : la copie est revenue au vert après chaque restauration.
        code, sortie = _lancer_gate(travail)
        if code != 0:
            echecs.append("POST-CONDITION : la copie n'est pas revenue au VERT")
            print(sortie)

        nombre_controles = len(_decouvrir_controles(travail))

    # L'arbre de travail RÉEL n'a jamais été touché — on le prouve.
    empreinte_source_apres = _empreinte_dossier(SOURCE)
    if empreinte_source_avant != empreinte_source_apres:
        echecs.append(
            "ARBRE DE TRAVAIL MODIFIÉ : la batterie a altéré les sources "
            f"({empreinte_source_avant[:16]} -> {empreinte_source_apres[:16]})"
        )
    else:
        print(f"\nSOURCE INTACTE : sha256 {empreinte_source_avant[:16]}… inchangé")

    print()
    if echecs:
        print(f"BATTERIE INCOMPLÈTE : {len(echecs)} problème(s)")
        for echec in echecs:
            print(f"  - {echec}")
        return 1

    print(
        f"BATTERIE COMPLÈTE : {len(MUTATIONS)}/{len(MUTATIONS)} mutations mordent "
        f"— couverture {nombre_controles}/{nombre_controles} contrôles"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

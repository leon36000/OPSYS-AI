from __future__ import annotations

import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any


# Les extensions textuelles sont les seules pour lesquelles une lecture UTF-8
# est exigible : un binaire suivi par git ne constitue pas un texte illisible.
EXTENSIONS_TEXTE = {
    ".py",
    ".md",
    ".json",
    ".jsonl",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".txt",
    ".sh",
}

MOTIF_IDENTIFIANT = re.compile(
    rb"(?<![A-Z0-9-])(?:D-\d{3}|R-\d{3}|REG-\d{2})(?![A-Z0-9-])"
)
MOTIF_IDENTIFIANT_TEXTE = re.compile(
    r"(?<![A-Z0-9-])(?:D-\d{3}|R-\d{3}|REG-\d{2})(?![A-Z0-9-])"
)
MOTIF_DEFINITION_IDENTIFIANT = re.compile(
    r"(?im)^\s*(?:[-*+]\s+)?(?:\*\*)?"
    r"(?P<identifiant>D-\d{3}|R-\d{3}|REG-\d{2})"
    r"(?:\*\*)?\s*(?:—|:)"
)


def echouer(raison: str) -> int:
    print(raison, file=sys.stderr)
    return 2


def lancer_git(racine: Path, arguments: list[str]) -> bytes:
    try:
        resultat = subprocess.run(
            ["git", *arguments],
            cwd=racine,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        raise RuntimeError("git est introuvable") from None
    except subprocess.CalledProcessError as erreur:
        detail = erreur.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(detail or "la commande git a échoué") from None
    return resultat.stdout


def normaliser(valeur: str) -> str:
    """Uniformise les noms pour comparer un libellé humain à un chemin."""
    sans_accents = "".join(
        caractere
        for caractere in unicodedata.normalize("NFKD", valeur)
        if not unicodedata.combining(caractere)
    )
    return "".join(caractere for caractere in sans_accents.lower() if caractere.isalnum())


def est_test(chemin: str) -> bool:
    parties = Path(chemin).parts
    nom = Path(chemin).name.lower()
    return (
        any(partie.lower() in {"test", "tests"} for partie in parties)
        or nom.startswith("test_")
        or nom.endswith("_test.py")
    )


def categorie_fichier(chemin: str) -> str:
    # Un test Python reste un test : les catégories décrivent le lieu le plus
    # informatif, sans compter un même fichier deux fois.
    if est_test(chemin):
        return "test"
    suffixe = Path(chemin).suffix.lower()
    if suffixe == ".py":
        return "code"
    if suffixe == ".md":
        return "document"
    return "ailleurs"


def extraire_statut(texte: str) -> tuple[str | None, str | None]:
    """Conserve la ligne source afin de publier le statut effectivement lu."""
    motif = re.compile(
        r"^\s*(?:[-*]\s*)?(?:\*\*)?(?:statut|status|état|etat)(?:\*\*)?"
        r"\s*(?::|=|-)\s*(.+?)\s*$",
        re.IGNORECASE,
    )
    for ligne in texte.splitlines():
        correspondance = motif.match(ligne)
        if correspondance:
            valeur = correspondance.group(1).strip().strip("*").strip()
            return ligne.strip(), valeur
    return None, None


def statut_termine(statut: str | None) -> bool:
    if statut is None:
        return False
    valeur = normaliser(statut)
    return any(
        marqueur in valeur
        for marqueur in ("termine", "done", "complete", "completed", "acheve", "finished")
    )


def est_nom_service_conforme(nom: str) -> bool:
    """Écarte les fragments de colonnes voisines produits par pdftotext."""
    if (
        "," in nom
        or "(" in nom
        or '"' in nom
        or "«" in nom
        or "»" in nom
        or "+" in nom
    ):
        return False
    mots = re.findall(r"\S+", nom)
    return bool(mots) and len(mots) <= 4


def extraire_services_d010(texte: str) -> tuple[list[str], int]:
    """Lit les premières colonnes du tableau des services de D-010."""
    occurrences = list(re.finditer(r"\bD-010\b", texte, re.IGNORECASE))
    zone = ""

    # La liste d'identifiants peut aussi contenir D-010 ; on privilégie donc
    # l'occurrence dont le voisinage contient réellement l'en-tête du tableau.
    for occurrence in occurrences:
        candidat = texte[occurrence.start() : occurrence.start() + 12000]
        if re.search(r"(?im)^\s*\|?\s*service\s*(?:\|| {2,})", candidat):
            zone = candidat
            break

    if not zone:
        return [], 0

    lignes = zone.splitlines()
    debut = -1
    for index, ligne in enumerate(lignes):
        if re.match(r"(?i)^\s*\|?\s*service\s*(?:\|| {2,})", ligne):
            debut = index + 1
            break
    if debut < 0:
        return [], 0

    services: list[str] = []
    lignes_ecartees = 0
    for ligne in lignes[debut:]:
        # Les séparateurs et un prochain identifiant délimitent la décision.
        if ligne.strip().startswith("--") or re.search(r"\bD-0(?:0[1-9]|1[1-9])\b", ligne):
            break
        if not ligne.strip():
            if services:
                break
            continue
        if re.match(r"^\s*\|?\s*[-:| ]+\|?[-:| ]*$", ligne):
            continue

        premier_champ: str | None = None
        if "|" in ligne:
            champs = ligne.strip().strip("|").split("|")
            if len(champs) >= 2:
                premier_champ = champs[0]
        else:
            morceaux = re.split(r"\s{2,}", ligne.strip(), maxsplit=1)
            if len(morceaux) == 2:
                premier_champ = morceaux[0]

        if premier_champ is None:
            continue

        nom = re.sub(r"^[\s>*#-]+", "", premier_champ)
        nom = re.sub(r"[*`_]", "", nom).strip()
        if not nom or normaliser(nom) == "service":
            continue
        if not est_nom_service_conforme(nom):
            lignes_ecartees += 1
            continue
        services.append(nom)

    uniques: list[str] = []
    deja_vus: set[str] = set()
    for service in services:
        cle = normaliser(service)
        if cle and cle not in deja_vus:
            uniques.append(service)
            deja_vus.add(cle)
    return uniques, lignes_ecartees


def extraire_definitions_decisions(
    textes: dict[str, str | None],
) -> dict[str, set[str]]:
    """Indexe les identifiants qui ouvrent leur propre énoncé de décision."""
    definitions: dict[str, set[str]] = {}
    for fichier, texte in textes.items():
        chemin = Path(fichier)
        if (
            len(chemin.parts) != 3
            or chemin.parts[0] != "docs"
            or chemin.parts[1] != "decisions"
            or chemin.suffix.lower() != ".md"
            or texte is None
        ):
            continue
        for correspondance in MOTIF_DEFINITION_IDENTIFIANT.finditer(texte):
            identifiant = correspondance.group("identifiant")
            definitions.setdefault(identifiant, set()).add(fichier)
    return definitions


def extraire_statuts_registre(contenu: Any, source: str) -> list[tuple[str, str, str]]:
    """Accepte les formes JSON usuelles sans présumer du schéma du registre."""
    resultat: list[tuple[str, str, str]] = []

    def parcourir(noeud: Any, cle_parent: str | None = None) -> None:
        if isinstance(noeud, dict):
            identifiant = None
            for cle in ("module", "module_id", "nom", "name", "id"):
                valeur = noeud.get(cle)
                if isinstance(valeur, str):
                    identifiant = valeur
                    break
            if identifiant is None and cle_parent is not None:
                identifiant = cle_parent

            statut = None
            for cle in ("statut", "status", "état", "etat"):
                valeur = noeud.get(cle)
                if isinstance(valeur, str):
                    statut = valeur
                    break

            if identifiant is not None and statut is not None:
                resultat.append((identifiant, statut, source))

            for cle, valeur in noeud.items():
                if isinstance(valeur, (dict, list)):
                    parcourir(valeur, cle)
        elif isinstance(noeud, list):
            for valeur in noeud:
                parcourir(valeur, cle_parent)

    parcourir(contenu)
    return resultat


def main() -> int:
    racine = Path(__file__).resolve().parents[2]
    try:
        sortie_fichiers = lancer_git(racine, ["ls-files", "-z"])
        commit = lancer_git(racine, ["rev-parse", "HEAD"]).decode("ascii").strip()
    except RuntimeError as erreur:
        return echouer(f"A3 inexécutable : {erreur}")

    fichiers = sorted(
        morceau.decode("utf-8", "surrogateescape")
        for morceau in sortie_fichiers.split(b"\0")
        if morceau
    )
    reference = "audit/referentiel/identifiants.txt"
    if reference not in fichiers:
        return echouer(
            "A3 inexécutable : audit/referentiel/identifiants.txt est absent du périmètre git"
        )

    ouverts: list[str] = []
    octets: dict[str, bytes] = {}
    textes: dict[str, str | None] = {}
    anomalies: list[dict[str, str]] = []

    # Chaque fichier suivi est ouvert pour que le périmètre de citation soit
    # strictement celui de git ls-files, y compris les chemins avec espaces.
    for fichier in fichiers:
        chemin = racine / fichier
        try:
            donnees = chemin.read_bytes()
        except OSError as erreur:
            if chemin.suffix.lower() in EXTENSIONS_TEXTE:
                anomalies.append(
                    {
                        "controle": "lisibilite",
                        "objet": fichier,
                        "constate": f"lecture impossible : {erreur.strerror or erreur}",
                        "attendu": "fichier texte lisible",
                    }
                )
            continue

        ouverts.append(fichier)
        octets[fichier] = donnees
        if chemin.suffix.lower() in EXTENSIONS_TEXTE:
            try:
                textes[fichier] = donnees.decode("utf-8")
            except UnicodeDecodeError:
                textes[fichier] = None
                anomalies.append(
                    {
                        "controle": "lisibilite",
                        "objet": fichier,
                        "constate": "contenu non décodable en UTF-8",
                        "attendu": "fichier texte UTF-8 lisible",
                    }
                )

    texte_reference = textes.get(reference)
    if texte_reference is None:
        return echouer(
            "A3 inexécutable : le référentiel des identifiants ne peut pas être lu en UTF-8"
        )

    identifiants = set(MOTIF_IDENTIFIANT_TEXTE.findall(texte_reference))
    repartition = {
        "D": sum(identifiant.startswith("D-") for identifiant in identifiants),
        "R": sum(
            identifiant.startswith("R-") and not identifiant.startswith("REG-")
            for identifiant in identifiants
        ),
        "REG": sum(identifiant.startswith("REG-") for identifiant in identifiants),
    }
    if len(identifiants) != 91 or repartition != {"D": 45, "R": 33, "REG": 13}:
        return echouer(
            "A3 inexécutable : le référentiel ne contient pas exactement 45 D, 33 R et 13 REG"
        )

    trouves: dict[str, set[str]] = {identifiant: set() for identifiant in identifiants}
    non_resolvables: dict[str, set[str]] = {}

    # audit/ contient les tests et la documentation de la sonde : ses citations
    # ne constituent pas des revendications du dépôt audité.
    for fichier, donnees in octets.items():
        if fichier == "audit" or fichier.startswith("audit/"):
            continue
        for brut in MOTIF_IDENTIFIANT.findall(donnees):
            identifiant = brut.decode("ascii")
            if identifiant in identifiants:
                trouves[identifiant].add(fichier)
            else:
                non_resolvables.setdefault(identifiant, set()).add(fichier)

    citations: dict[str, dict[str, Any]] = {}
    for identifiant in sorted(identifiants):
        fichiers_cites = sorted(trouves[identifiant])
        compteurs = {"code": 0, "document": 0, "test": 0, "ailleurs": 0}
        for fichier in fichiers_cites:
            compteurs[categorie_fichier(fichier)] += 1
        citations[identifiant] = {
            "fichiers": fichiers_cites,
            "total": len(fichiers_cites),
            **compteurs,
        }
        if not fichiers_cites:
            anomalies.append(
                {
                    "controle": "citations",
                    "objet": identifiant,
                    "constate": "cité dans 0 fichier suivi",
                    "attendu": "au moins une citation dans le dépôt",
                }
            )

    definitions_decisions = extraire_definitions_decisions(textes)
    mesure_non_resolvables: dict[str, list[str]] = {}
    extensions_legitimes: dict[str, list[str]] = {}
    for identifiant in sorted(non_resolvables):
        fichiers_cites = sorted(non_resolvables[identifiant])
        fichiers_definitions = sorted(definitions_decisions.get(identifiant, set()))
        if fichiers_definitions:
            extensions_legitimes[identifiant] = fichiers_definitions
            continue
        mesure_non_resolvables[identifiant] = fichiers_cites
        anomalies.append(
            {
                "controle": "citations_non_resolvables",
                "objet": identifiant,
                "constate": (
                    f"cité dans {len(fichiers_cites)} fichier(s) : "
                    f"{', '.join(fichiers_cites)}"
                ),
                "attendu": "identifiant présent dans le référentiel",
            }
        )

    services, lignes_services_ecartees = extraire_services_d010(texte_reference)
    if not services:
        return echouer(
            "A3 inexécutable : aucun nom de service n'a pu être extrait du tableau de D-010"
        )

    services_mesures: dict[str, dict[str, Any]] = {}
    fichiers_core = [fichier for fichier in fichiers if fichier.startswith("core/")]
    for service in services:
        cle_service = normaliser(service)
        correspondants: list[str] = []
        for fichier in fichiers_core:
            composantes = Path(fichier).parts
            if any(cle_service in normaliser(composante) for composante in composantes[1:]):
                correspondants.append(fichier)
        correspondants.sort()
        services_mesures[service] = {
            "fichiers": correspondants,
            "total": len(correspondants),
        }
        if not correspondants:
            anomalies.append(
                {
                    "controle": "services_transversaux",
                    "objet": service,
                    "constate": "0 fichier sous core/ porte ce nom",
                    "attendu": "au moins un fichier ou répertoire correspondant sous core/",
                }
            )

    stories: dict[str, dict[str, Any]] = {}
    fichiers_stories = [fichier for fichier in fichiers if fichier.startswith("stories/")]
    ledger = "registries/ledger/preuves.jsonl"
    entrees_preuves: list[dict[str, Any]] = []

    if ledger in fichiers:
        texte_ledger = textes.get(ledger)
        if texte_ledger is not None:
            for numero_ligne, ligne in enumerate(texte_ledger.splitlines(), start=1):
                if not ligne.strip():
                    continue
                try:
                    entree = json.loads(ligne)
                except json.JSONDecodeError as erreur:
                    anomalies.append(
                        {
                            "controle": "stories_p0",
                            "objet": f"{ledger}:{numero_ligne}",
                            "constate": f"JSONL invalide : {erreur.msg}",
                            "attendu": "entrée JSON valide",
                        }
                    )
                    continue
                if isinstance(entree, dict):
                    entrees_preuves.append(entree)

    for numero in range(1, 11):
        identifiant = f"P0-{numero}"
        prefixe_story = f"{identifiant}-"
        candidats = [
            fichier
            for fichier in fichiers_stories
            if Path(fichier).name.startswith(prefixe_story)
        ]
        candidats.sort()

        ligne_statut: str | None = None
        valeur_statut: str | None = None
        fichier_story: str | None = candidats[0] if candidats else None
        if fichier_story is not None:
            texte_story = textes.get(fichier_story)
            if texte_story is not None:
                ligne_statut, valeur_statut = extraire_statut(texte_story)

        entrees = []
        for entree in entrees_preuves:
            payload = entree.get("payload")
            if isinstance(payload, dict) and payload.get("tache") == identifiant:
                entrees.append(payload)

        preuve_non_vide = any(
            isinstance(payload.get("preuve"), str) and bool(payload["preuve"].strip())
            for payload in entrees
        )
        stories[identifiant] = {
            "fichier": fichier_story,
            "statut_declare": valeur_statut,
            "ligne_statut": ligne_statut,
            "entrees_preuve": len(entrees),
            "preuve_non_vide": preuve_non_vide,
        }

        if fichier_story is None:
            anomalies.append(
                {
                    "controle": "stories_p0",
                    "objet": identifiant,
                    "constate": "fichier de story absent sous stories/",
                    "attendu": "story P0 présente",
                }
            )
        elif statut_termine(valeur_statut) and not entrees:
            anomalies.append(
                {
                    "controle": "stories_p0",
                    "objet": identifiant,
                    "constate": "statut terminé sans entrée de preuve",
                    "attendu": "au moins une entrée payload.tache avec cet identifiant",
                }
            )
        elif statut_termine(valeur_statut) and not preuve_non_vide:
            anomalies.append(
                {
                    "controle": "stories_p0",
                    "objet": identifiant,
                    "constate": "statut terminé avec preuve vide",
                    "attendu": "champ payload.preuve non vide",
                }
            )

    modules: dict[str, str] = {}
    for fichier in fichiers:
        parties = Path(fichier).parts
        if len(parties) >= 2 and parties[0] == "Modules M":
            modules.setdefault(parties[1], "")

    statuts_registre: list[tuple[str, str, str]] = []
    for fichier in fichiers:
        chemin = Path(fichier)
        if (
            len(chemin.parts) >= 2
            and chemin.parts[0] == "registries"
            and "module" in chemin.name.lower()
            and chemin.suffix.lower() in {".json", ".jsonl"}
            and textes.get(fichier) is not None
        ):
            texte = textes[fichier]
            assert texte is not None
            if chemin.suffix.lower() == ".json":
                try:
                    statuts_registre.extend(extraire_statuts_registre(json.loads(texte), fichier))
                except json.JSONDecodeError as erreur:
                    anomalies.append(
                        {
                            "controle": "statuts_modules",
                            "objet": fichier,
                            "constate": f"JSON invalide : {erreur.msg}",
                            "attendu": "registre JSON valide",
                        }
                    )
            else:
                for numero_ligne, ligne in enumerate(texte.splitlines(), start=1):
                    if not ligne.strip():
                        continue
                    try:
                        statuts_registre.extend(
                            extraire_statuts_registre(json.loads(ligne), fichier)
                        )
                    except json.JSONDecodeError as erreur:
                        anomalies.append(
                            {
                                "controle": "statuts_modules",
                                "objet": f"{fichier}:{numero_ligne}",
                                "constate": f"JSONL invalide : {erreur.msg}",
                                "attendu": "entrée de registre JSON valide",
                            }
                        )

    modules_mesures: dict[str, dict[str, Any]] = {}
    for module in sorted(modules):
        readme = f"Modules M/{module}/README.md"
        ligne_readme, statut_readme = (None, None)
        if readme in fichiers and textes.get(readme) is not None:
            texte_readme = textes[readme]
            assert texte_readme is not None
            ligne_readme, statut_readme = extraire_statut(texte_readme)

        valeurs_registre = [
            {"fichier": source, "statut": statut}
            for identifiant, statut, source in statuts_registre
            if normaliser(identifiant) == normaliser(module)
        ]
        modules_mesures[module] = {
            "readme": readme if readme in fichiers else None,
            "ligne_statut": ligne_readme,
            "statut_readme": statut_readme,
            "registre": valeurs_registre,
        }

        if readme not in fichiers:
            anomalies.append(
                {
                    "controle": "statuts_modules",
                    "objet": module,
                    "constate": "README.md absent",
                    "attendu": "README.md portant un statut",
                }
            )

        for valeur in valeurs_registre:
            if (
                statut_readme is not None
                and normaliser(statut_readme) != normaliser(valeur["statut"])
            ):
                anomalies.append(
                    {
                        "controle": "statuts_modules",
                        "objet": module,
                        "constate": f"README={statut_readme}, registre={valeur['statut']}",
                        "attendu": "statuts identiques entre README et registre",
                    }
                )

    resultat = {
        "lot": "A3",
        "commit_gele": commit,
        "fichiers_ouverts": ouverts,
        "referentiel": {"total": 91, "D": 45, "R": 33, "REG": 13},
        "mesures": {
            "citations": citations,
            "citations_non_resolvables": mesure_non_resolvables,
            "extensions_legitimes": extensions_legitimes,
            "services_transversaux": services_mesures,
            "services_transversaux_lignes_ecartees_non_conformes": lignes_services_ecartees,
            "stories_p0": stories,
            "statuts_modules": modules_mesures,
        },
        "anomalies": anomalies,
    }
    print(json.dumps(resultat, ensure_ascii=False, sort_keys=True))
    return 1 if anomalies else 0


if __name__ == "__main__":
    sys.exit(main())

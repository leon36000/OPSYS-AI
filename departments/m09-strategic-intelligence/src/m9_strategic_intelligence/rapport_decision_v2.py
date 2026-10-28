"""Rapport de décision M9.10 — schéma versionné à 21 sections, proposé à l'arbitrage de Nathan.

STATUT : ``PROPOSITION_NON_RATIFIEE``. La définition produit (§M9.10) annonce « un rapport en 21 sections » mais n'en
nomme que douze, et le prompt maître M9 du 9 juin 2026 n'est pas dans le dépôt (``docs/departements/M9-audit.md`` §2.6).
Cette énumération est donc une PROPOSITION d'ingénierie, jamais une exigence ratifiée : chaque section dit d'où elle
vient (``definition`` : citée par DEFINITION-PRODUIT ; ``historique`` : clé du contrat à 15 clés ; ``cahier`` :
exigée par le cahier de mission). Le contrat historique (``contrats.CHAMPS_RAPPORT_STRATEGIQUE`` et
``rapport_strategique``) reste intact ; ``vers_contrat_historique`` en donne la projection exacte à 15 clés.

Module pur (ADR-0009) : aucun import d'``opsys``. Le validateur ne juge jamais la VÉRITÉ d'un contenu ; il garantit la
forme, l'honnêteté des manques et l'ancrage : aucune recommandation, option, scénario, impact, risque, condition ou
action sans source ou hypothèse explicite (règle dure M9), vérifié de proche en proche (une référence ne pointe
que vers un identifiant déjà ancré, jamais en avant ni en boucle). Une section qui ne peut pas être renseignée le dit
(``NON_DISPONIBLE`` + raison) : le vide n'est jamais rempli par défaut.
"""

from __future__ import annotations

import hashlib
import json
import re

from . import contrats, rapport_strategique

SCHEMA = "opsys.m9.rapport_decision/v2-proposition"
STATUT_CONTRAT = "PROPOSITION_NON_RATIFIEE"
STATUTS_SECTION = frozenset({"RENSEIGNEE", "NON_DISPONIBLE", "NON_APPLICABLE"})

# (identifiant, libellé, origine, clé historique correspondante ou None, forme, ancrage requis)
# forme : "texte" = {"texte": …} ; "liste" = liste d'éléments {id, texte, refs, …}.
# ancrage : tout élément doit citer au moins une référence déjà ancrée (source ou hypothèse déclarée).
SECTIONS = (
    ("question", "Question posée", "definition", None, "texte", False),
    ("etat", "État consolidé de départ", "historique", "etat", "liste", False),
    ("donnees_utilisees", "Données utilisées (sources exactes)", "definition", "preuves", "liste", False),
    ("donnees_manquantes", "Données manquantes", "definition", None, "liste", False),
    ("contradictions", "Contradictions conservées", "cahier", None, "liste", False),
    ("hypotheses", "Hypothèses explicites", "definition", "hypotheses", "liste", False),
    ("incertitudes", "Incertitudes", "historique", "incertitudes", "liste", False),
    ("diagnostic", "Diagnostic", "historique", "diagnostic", "liste", True),
    ("options_alternatives", "Options et alternatives", "definition", None, "liste", True),
    ("scenarios", "Scénarios", "definition", "scenarios", "liste", True),
    ("impacts", "Impacts", "definition", "impacts", "liste", True),
    ("dependances", "Dépendances", "definition", None, "liste", True),
    ("risques", "Risques", "historique", "risques", "liste", True),
    ("priorites", "Priorités", "historique", "priorites", "liste", True),
    ("decision_recommandee", "Décision recommandée", "definition", "recommandations", "liste", True),
    ("conditions", "Conditions de la décision", "definition", None, "liste", True),
    ("validation", "Validation humaine requise", "definition", "validation", "liste", False),
    ("plan_action", "Plan d'action", "definition", "actions", "liste", True),
    ("taches_par_departement", "Tâches par département", "historique", "taches_par_departement", "liste", True),
    ("mesure_succes_suivi", "Mesure du succès et suivi", "definition", "suivi", "liste", True),
    ("memoire_m10", "Contexte et mémoire M10", "historique", "memoire_m10", "liste", False),
)
IDS_SECTIONS = tuple(section[0] for section in SECTIONS)
# Sections qui DÉCLARENT les identifiants citables (données et hypothèses : le socle d'ancrage).
_SOCLE = ("donnees_utilisees", "hypotheses")
_CITABLES_SANS_ANCRAGE = ("etat", "contradictions", "donnees_manquantes", "incertitudes")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:\-]{0,63}")
_MAX_TEXTE = 4000
_MAX_ELEMENTS = 200
_MAX_REFS = 32
_CHAMPS_ELEMENT = frozenset({"id", "texte", "refs", "valeur", "unite", "source_calcul"})
_CHAMPS_ENVELOPPE = frozenset({"schema", "statut_contrat", "rapport_id", "version", "sections", "limites"})
_LIMITES = (
    "Proposition de schéma non ratifiée : l'énumération des 21 sections attend l'arbitrage de Nathan.",
    "Validation de FORME et d'ancrage seulement : ni vérité, ni actualité, ni décision validée.",
    "Aucun chiffre calculé ici : toute valeur cite le propriétaire du calcul (M5, M4, M8…) ou reste absente.",
)


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


def mapping_historique() -> dict[str, str]:
    """Clé du contrat historique à 15 clés → identifiant de section v2 (correspondance exhaustive et injective)."""
    return {historique: section[0] for section in SECTIONS if (historique := section[3]) is not None}


def origines() -> dict[str, str]:
    return {section[0]: section[2] for section in SECTIONS}


def controler_enumeration() -> None:
    """Invariants de l'énumération elle-même : 21 sections distinctes ; les 15 clés historiques toutes couvertes."""
    if len(SECTIONS) != 21 or len(set(IDS_SECTIONS)) != 21:
        raise _refus("REJ-RAPPORT-V2-ENUMERATION", "21 sections distinctes attendues")
    correspondance = mapping_historique()
    if set(correspondance) != set(contrats.CHAMPS_RAPPORT_STRATEGIQUE) or len(set(correspondance.values())) != len(
        correspondance
    ):
        raise _refus(
            "REJ-RAPPORT-V2-COMPATIBILITE", "les 15 clés historiques doivent correspondre chacune à une section"
        )


def _json_fini(valeur: object) -> None:
    try:
        texte = json.dumps(valeur, ensure_ascii=False, allow_nan=False, sort_keys=True)
        if json.loads(texte) != valeur:
            raise ValueError
    except (TypeError, ValueError, RecursionError, OverflowError) as exc:
        raise _refus("REJ-RAPPORT-V2-STRUCTURE", "JSON fini et représentable sans conversion requis") from exc


def _texte(valeur: object, maximum: int = _MAX_TEXTE) -> bool:
    return type(valeur) is str and bool(valeur.strip()) and len(valeur) <= maximum


def _element(section: str, element: object, ids_vus: set[str]) -> dict:
    if type(element) is not dict or not set(element) <= _CHAMPS_ELEMENT or not {"id", "texte"} <= set(element):
        raise _refus("REJ-RAPPORT-V2-ELEMENT", f"{section} : élément {{id, texte, refs…}} requis")
    if type(element["id"]) is not str or not _ID.fullmatch(element["id"]) or element["id"] in ids_vus:
        raise _refus("REJ-RAPPORT-V2-ELEMENT", f"{section} : identifiant distinct et sobre requis")
    if not _texte(element["texte"]):
        raise _refus("REJ-RAPPORT-V2-ELEMENT", f"{section} : texte non vide borné requis")
    refs = element.get("refs", [])
    if type(refs) is not list or len(refs) > _MAX_REFS or any(type(r) is not str or not _ID.fullmatch(r) for r in refs):
        raise _refus("REJ-RAPPORT-V2-ELEMENT", f"{section} : refs = liste d'identifiants")
    if len(set(refs)) != len(refs):
        raise _refus("REJ-RAPPORT-V2-ELEMENT", f"{section} : références distinctes requises")
    if "valeur" in element:
        # Un chiffre n'a de sens qu'avec son unité et le propriétaire de son calcul : jamais produit ici.
        if (
            type(element["valeur"]) is not str
            or not _texte(element.get("unite", ""), 32)
            or not _texte(element.get("source_calcul", ""), 128)
        ):
            raise _refus("REJ-RAPPORT-V2-VALEUR", f"{section} : valeur textuelle + unité + source_calcul requises")
    elif "unite" in element or "source_calcul" in element:
        raise _refus("REJ-RAPPORT-V2-VALEUR", f"{section} : unité/source_calcul sans valeur")
    return element


def valider_rapport_decision_v2(rapport: object) -> tuple[bool, str | None]:
    """(True, None) ou (False, code REJ-RAPPORT-V2-…). Ne lève jamais pour une entrée mal formée."""
    try:
        _valider(rapport)
    except ValueError as exc:
        texte = str(exc)
        return False, texte.split(" : ", 1)[0] if texte.startswith("REJ-") else "REJ-RAPPORT-V2-STRUCTURE"
    return True, None


def _valider(rapport: object) -> None:
    controler_enumeration()
    if type(rapport) is not dict:
        raise _refus("REJ-RAPPORT-V2-STRUCTURE", "objet requis")
    _json_fini(rapport)
    if set(rapport) != _CHAMPS_ENVELOPPE:
        raise _refus("REJ-RAPPORT-V2-STRUCTURE", "enveloppe exacte requise")
    if rapport["schema"] != SCHEMA or rapport["statut_contrat"] != STATUT_CONTRAT:
        raise _refus("REJ-RAPPORT-V2-SCHEMA", "schéma et statut de contrat proposés requis (jamais présentés ratifiés)")
    if type(rapport["version"]) is not int or rapport["version"] < 1:
        raise _refus("REJ-RAPPORT-V2-VERSION", "version entière ≥ 1 requise")
    if type(rapport["limites"]) is not list or not rapport["limites"] or not all(_texte(x) for x in rapport["limites"]):
        raise _refus("REJ-RAPPORT-V2-LIMITES", "limites explicites requises")
    sections = rapport["sections"]
    if type(sections) is not dict or set(sections) != set(IDS_SECTIONS):
        raise _refus("REJ-RAPPORT-V2-SECTIONS", "les 21 sections exactes sont requises, sans section en trop")
    if rapport["rapport_id"] != identifiant(rapport):
        raise _refus("REJ-RAPPORT-V2-EMPREINTE", "rapport_id ne correspond pas au contenu")

    ancres: set[str] = set()
    ids_globaux: set[str] = set()
    for identifiant_section, _libelle, _origine, _historique, forme, ancrage in SECTIONS:
        bloc = sections[identifiant_section]
        if type(bloc) is not dict or set(bloc) - {"statut", "contenu", "raison"} or "statut" not in bloc:
            raise _refus("REJ-RAPPORT-V2-SECTION", f"{identifiant_section} : {{statut, contenu[, raison]}} requis")
        statut = bloc["statut"]
        if statut not in STATUTS_SECTION:
            raise _refus("REJ-RAPPORT-V2-SECTION", f"{identifiant_section} : statut inconnu")
        contenu = bloc.get("contenu")
        if statut != "RENSEIGNEE":
            if not _texte(bloc.get("raison"), 1000) or contenu not in (None, [], {}):
                raise _refus(
                    "REJ-RAPPORT-V2-MANQUE",
                    f"{identifiant_section} : un manque dit sa raison et ne porte aucun contenu inventé",
                )
            continue
        if "raison" in bloc:
            raise _refus("REJ-RAPPORT-V2-SECTION", f"{identifiant_section} : raison réservée aux manques")
        if forme == "texte":
            if type(contenu) is not dict or set(contenu) != {"texte"} or not _texte(contenu["texte"]):
                raise _refus("REJ-RAPPORT-V2-SECTION", f"{identifiant_section} : {{texte}} non vide requis")
            continue
        if type(contenu) is not list or not 1 <= len(contenu) <= _MAX_ELEMENTS:
            raise _refus("REJ-RAPPORT-V2-SECTION", f"{identifiant_section} : 1 à {_MAX_ELEMENTS} éléments requis")
        locaux: set[str] = set()
        for element in contenu:
            element = _element(identifiant_section, element, locaux)
            if element["id"] in ids_globaux:
                raise _refus("REJ-RAPPORT-V2-ELEMENT", f"{identifiant_section} : identifiant déjà déclaré ailleurs")
            refs = element.get("refs", [])
            if any(r not in ancres for r in refs):
                raise _refus(
                    "REJ-RAPPORT-V2-REFERENCE",
                    f"{identifiant_section} : référence vers un identifiant non ancré (inconnu, ultérieur, circulaire)",
                )
            if ancrage and not refs:
                raise _refus(
                    "REJ-RAPPORT-V2-SANS-ANCRAGE",
                    f"{identifiant_section} : jamais sans source ou hypothèse explicite (règle dure M9)",
                )
            locaux.add(element["id"])
        ids_globaux |= locaux
        # Données et hypothèses sont le socle ; un élément ancré devient à son tour citable par les suivantes.
        if identifiant_section in _SOCLE or ancrage or identifiant_section in _CITABLES_SANS_ANCRAGE:
            ancres |= locaux


def identifiant(rapport: dict) -> str:
    """Empreinte canonique du contenu (hors ``rapport_id``) : lie la version à ses octets."""
    sans_id = {cle: valeur for cle, valeur in rapport.items() if cle != "rapport_id"}
    return hashlib.sha256(json.dumps(sans_id, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def assembler(sections: dict, *, version: int = 1) -> dict:
    """Pose enveloppe, limites et ``rapport_id`` autour de sections déjà composées ; valide et rend le rapport."""
    rapport = {
        "schema": SCHEMA,
        "statut_contrat": STATUT_CONTRAT,
        "rapport_id": "",
        "version": version,
        "sections": sections,
        "limites": list(_LIMITES),
    }
    rapport["rapport_id"] = identifiant(rapport)
    _valider(rapport)
    return rapport


def vers_contrat_historique(rapport: dict) -> dict:
    """Projection EXACTE du v2 vers les 15 clés historiques ; refusée si le v2 est invalide ou si le résultat ne passe
    pas le validateur historique inchangé. Une section manquante reste ``None`` (jamais un contenu inventé)."""
    _valider(rapport)
    projection = {}
    for historique, section in mapping_historique().items():
        bloc = rapport["sections"][section]
        projection[historique] = bloc["contenu"] if bloc["statut"] == "RENSEIGNEE" else None
    valide, code = rapport_strategique.valider_rapport_strategique(projection)
    if not valide:
        raise _refus("REJ-RAPPORT-V2-COMPATIBILITE", f"projection refusée par le contrat historique ({code})")
    return projection

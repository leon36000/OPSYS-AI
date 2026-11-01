"""Contexte de la propriété et du site (M3.2, DEFINITION-PRODUIT §7 M3 : « adresse, distance, accès, historique »).

Ce module AGRÈGE les facteurs qui affectent une estimation : accès, hauteur, pente (rapport sur 12), âge du bâtiment,
matériaux existants, contraintes saisonnières, règles météo de l'entreprise pour le service, permis municipaux. Il ne
produit JAMAIS une valeur qu'on ne lui a pas donnée : un facteur sans source est « inconnu » (statut explicite, avec
ce qu'il faut collecter), un permis est une DONNÉE À VÉRIFIER (jamais « non requis » par défaut), deux sources qui se
contredisent sont un « conflit » à trancher par une personne, jamais résolu en silence.

Sources, par facteur (chacune sourcée : qui, quand, référence) :

* profil géospatial (``profil_geospatial``) : même forme que le profil de propriété, produit par
  ``geospatial.agreger`` ;
* profil de propriété de M2 (``profil_propriete``) : fourni par l'appelant. Le profil de propriété de M2 (M2.3)
  n'existe pas encore sur la ligne : ce module définit la FORME attendue (un port), pas son producteur ;
* déclarations (``facteurs_declares``) : une personne ou un agent qui cite sa source (``declare_par``, ``declare_le``) ;
* règles météo de l'entreprise (``meteo_service``) : lues par l'adaptateur dans ``opsys.meteo``. Ce sont les SEUILS
  que l'entreprise a déclarés pour ce service, pas une prévision.

Sortie versionnée (``schema`` ``m3.contexte_site/v1``) : ``version`` s'incrémente seulement si le contenu change
(``empreinte_contenu``), ``precedent`` chaîne les versions. ``hypotheses_estimation`` est la liste STRUCTURÉE des
hypothèses que l'estimation doit porter (données retenues, à collecter, conflits à trancher, vérifications) ; ce
module ne chiffre aucun effet de ces facteurs sur le prix : le chiffre vient des moteurs déterministes de
l'estimation.

Module pur : aucune horloge (``date_reference`` est fournie), aucun aléa, aucun réseau, aucun import ``opsys``.
Données fictives dans les tests. Les permis ne sont pas un avis juridique : à valider auprès de la municipalité et
d'un professionnel qualifié.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from . import journal_site, verdicts

__all__ = [
    "CHAMPS_FACTEURS",
    "CHAMPS_FACTEURS_DECLARABLES",
    "SCHEMA",
    "construire",
    "empreinte_contexte",
    "resume_hypotheses",
]

SCHEMA = "m3.contexte_site/v1"
MENTION = (
    "Contexte agrégé de sources déclarées, sans valeur inventée. Les permis municipaux sont des données à vérifier "
    "auprès de la municipalité : À valider auprès d'un professionnel qualifié."
)
CHAMPS_FACTEURS = (
    "acces",
    "hauteur",
    "pente",
    "age",
    "materiaux_existants",
    "contraintes_saisonnieres",
    "meteo",
    "permis_municipaux",
)
# Les six facteurs qu'une personne ou M2 peuvent donner ; « meteo » vient seulement des règles de l'entreprise et les
# permis municipaux ont leur propre entrée (`permis_municipaux`), jamais une valeur déclarée à la légère.
CHAMPS_FACTEURS_DECLARABLES = tuple(f for f in CHAMPS_FACTEURS if f not in ("meteo", "permis_municipaux"))

_CODE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
_IDENTIFIANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,119}$")
_MM_JJ = re.compile(r"^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$")
_TEXTE_MAX = 160
_NIVEAUX_ACCES = frozenset({"libre", "restreint", "difficile"})
_EXIGENCES = frozenset({"inconnue", "requise", "non_requise"})
_A_COLLECTER = {
    "acces": "Préciser l'accès au chantier (passage, stationnement, obstacles) avant tout prix final.",
    "hauteur": "Relever le nombre d'étages ou la hauteur à traiter avant tout prix final.",
    "pente": "Relever la pente (rapport sur 12) avant tout prix final.",
    "age": "Établir l'année de construction (rôle d'évaluation, propriétaire ou inspection).",
    "materiaux_existants": "Identifier les matériaux existants de chaque élément du bâtiment sur photo ou visite.",
    "contraintes_saisonnieres": "Demander à l'entreprise les périodes à éviter pour ce service.",
    "meteo": "Faire déclarer par l'entreprise les seuils météo de ce service (opsys-metier meteo).",
    "permis_municipaux": "Vérifier auprès de la municipalité si un permis est exigé pour ce service.",
}


class _Invalide(Exception):
    """Entrée refusée ; le message devient le détail du verdict."""


class _SourceAbsente(_Invalide):
    """Une valeur est affirmée sans dire d'où elle vient."""


def _refus(code: str, detail: str) -> dict[str, Any]:
    return verdicts.construire_verdict(code, detail)


def _texte(valeur: Any, nom: str, *, maximum: int = _TEXTE_MAX) -> str:
    if not isinstance(valeur, str) or not valeur.strip() or len(valeur) > maximum or not valeur.isprintable():
        raise _Invalide(f"{nom} : texte imprimable non vide de {maximum} caractères maximum attendu")
    return valeur.strip()


def _date(valeur: Any, nom: str) -> date:
    try:
        if isinstance(valeur, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", valeur):
            return date.fromisoformat(valeur)
    except ValueError:
        pass
    raise _Invalide(f"{nom} : date AAAA-MM-JJ attendue")


def _horodatage(valeur: Any, nom: str) -> str:
    try:
        if isinstance(valeur, str) and datetime.fromisoformat(valeur).tzinfo is not None:
            return valeur
    except ValueError:
        pass
    raise _Invalide(f"{nom} : horodatage ISO 8601 avec fuseau attendu")


def _entier(valeur: Any, nom: str, minimum: int, maximum: int) -> int:
    if type(valeur) is not int or not minimum <= valeur <= maximum:
        raise _Invalide(f"{nom} : entier de {minimum} à {maximum} attendu")
    return valeur


def _objet(valeur: Any, nom: str, permises: tuple[str, ...]) -> Mapping[str, Any]:
    if not isinstance(valeur, Mapping):
        raise _Invalide(f"{nom} : objet attendu")
    en_trop = sorted(set(valeur) - set(permises))
    if en_trop:
        raise _Invalide(f"{nom} : champs non admis {en_trop}")
    return valeur


def _acces(brut: Any, nom: str, _ref: date) -> dict[str, Any]:
    objet = _objet(brut, nom, ("niveau", "obstacles"))
    if objet.get("niveau") not in _NIVEAUX_ACCES:
        raise _Invalide(f"{nom}.niveau : {sorted(_NIVEAUX_ACCES)}")
    obstacles = objet.get("obstacles", [])
    if not isinstance(obstacles, list) or len(obstacles) > 8:
        raise _Invalide(f"{nom}.obstacles : liste de 8 codes au plus")
    codes = []
    for code in obstacles:
        if not isinstance(code, str) or not _CODE.fullmatch(code):
            raise _Invalide(f"{nom}.obstacles : code en minuscules attendu")
        codes.append(code)
    return {"niveau": objet["niveau"], "obstacles": sorted(set(codes))}


def _hauteur(brut: Any, nom: str, _ref: date) -> dict[str, Any]:
    objet = _objet(brut, nom, ("etages", "hauteur_m"))
    if not objet:
        raise _Invalide(f"{nom} : etages ou hauteur_m requis")
    sortie: dict[str, Any] = {}
    if "etages" in objet:
        sortie["etages"] = _entier(objet["etages"], f"{nom}.etages", 1, 10)
    if "hauteur_m" in objet:
        texte = objet["hauteur_m"]
        try:
            if not isinstance(texte, str) or not re.fullmatch(r"\d{1,2}(\.\d{1,2})?", texte):
                raise InvalidOperation
            valeur = Decimal(texte)
        except InvalidOperation:
            raise _Invalide(f'{nom}.hauteur_m : texte décimal (ex. "7.5") attendu') from None
        if not Decimal("1") <= valeur <= Decimal("60"):
            raise _Invalide(f"{nom}.hauteur_m : entre 1 et 60 m")
        sortie["hauteur_m"] = format(valeur.normalize(), "f")
    return sortie


def _pente(brut: Any, nom: str, _ref: date) -> dict[str, Any]:
    objet = _objet(brut, nom, ("pente_sur_12",))
    return {"pente_sur_12": _entier(objet.get("pente_sur_12"), f"{nom}.pente_sur_12", 0, 24)}


def _age(brut: Any, nom: str, ref: date) -> dict[str, Any]:
    objet = _objet(brut, nom, ("annee_construction",))
    return {"annee_construction": _entier(objet.get("annee_construction"), f"{nom}.annee_construction", 1700, ref.year)}


def _materiaux(brut: Any, nom: str, _ref: date) -> dict[str, Any]:
    objet = _objet(brut, nom, ("elements",))
    elements = objet.get("elements")
    if not isinstance(elements, list) or not elements or len(elements) > 20:
        raise _Invalide(f"{nom}.elements : 1 à 20 éléments attendus")
    vus: dict[str, str] = {}
    for position, element in enumerate(elements):
        e = _objet(element, f"{nom}.elements[{position}]", ("element", "materiau"))
        for cle in ("element", "materiau"):
            if not isinstance(e.get(cle), str) or not _CODE.fullmatch(e[cle]):
                raise _Invalide(f"{nom}.elements[{position}].{cle} : code en minuscules attendu")
        if e["element"] in vus and vus[e["element"]] != e["materiau"]:
            raise _Invalide(f"{nom}.elements : l'élément {e['element']} est décrit deux fois différemment")
        vus[e["element"]] = e["materiau"]
    return {"elements": [{"element": k, "materiau": v} for k, v in sorted(vus.items())]}


def _saisonnier(brut: Any, nom: str, _ref: date) -> dict[str, Any]:
    objet = _objet(brut, nom, ("periodes_a_eviter",))
    periodes = objet.get("periodes_a_eviter")
    if not isinstance(periodes, list) or not periodes or len(periodes) > 12:
        raise _Invalide(f"{nom}.periodes_a_eviter : 1 à 12 périodes attendues")
    sortie = []
    for position, periode in enumerate(periodes):
        p = _objet(periode, f"{nom}.periodes_a_eviter[{position}]", ("debut_mm_jj", "fin_mm_jj", "motif"))
        for cle in ("debut_mm_jj", "fin_mm_jj"):
            if not isinstance(p.get(cle), str) or not _MM_JJ.fullmatch(p[cle]):
                raise _Invalide(f"{nom}.periodes_a_eviter[{position}].{cle} : MM-JJ attendu")
        if not isinstance(p.get("motif"), str) or not _CODE.fullmatch(p["motif"]):
            raise _Invalide(f"{nom}.periodes_a_eviter[{position}].motif : code en minuscules attendu")
        sortie.append({"debut_mm_jj": p["debut_mm_jj"], "fin_mm_jj": p["fin_mm_jj"], "motif": p["motif"]})
    return {"periodes_a_eviter": sorted(sortie, key=lambda x: (x["debut_mm_jj"], x["fin_mm_jj"], x["motif"]))}


_NORMALISEURS = {
    "acces": _acces,
    "hauteur": _hauteur,
    "pente": _pente,
    "age": _age,
    "materiaux_existants": _materiaux,
    "contraintes_saisonnieres": _saisonnier,
}


def _source_declaration(brut: Any, nom: str) -> dict[str, Any]:
    d = _objet(brut, nom, ("valeur", "declare_par", "declare_le", "reference"))
    if "valeur" not in d:
        raise _Invalide(f"{nom}.valeur requise")
    try:
        par = _texte(d.get("declare_par"), f"{nom}.declare_par", maximum=80)
        le = _horodatage(d.get("declare_le"), f"{nom}.declare_le")
    except _Invalide as exc:
        raise _SourceAbsente(
            f"{nom} : la source de la déclaration (declare_par, declare_le) est requise : {exc}"
        ) from None
    reference = d.get("reference")
    if reference is not None and (not isinstance(reference, str) or not _IDENTIFIANT.fullmatch(reference)):
        raise _Invalide(f"{nom}.reference : identifiant sans espace attendu")
    return {"type": "declare", "reference": reference, "declare_par": par, "declare_le": le}


def _profil(
    brut: Any,
    nom: str = "profil_propriete",
    type_source: str = "profil_m2",
) -> tuple[dict[str, Any] | None, dict[str, Any], list[str]]:
    """``(source, faits normalisés, faits_ignores)`` d'un profil (propriété M2 ou géospatial), ou ``(None, {}, [])``."""
    if brut is None:
        return None, {}, []
    p = _objet(brut, nom, ("identifiant", "version", "recu_le", "faits"))
    identifiant = _texte(p.get("identifiant"), f"{nom}.identifiant", maximum=80)
    version = _texte(p.get("version"), f"{nom}.version", maximum=40)
    if not _IDENTIFIANT.fullmatch(identifiant) or not _IDENTIFIANT.fullmatch(version):
        raise _Invalide(f"{nom} : identifiant et version sans espace attendus")
    recu_le = _horodatage(p.get("recu_le"), f"{nom}.recu_le")
    faits = p.get("faits")
    if not isinstance(faits, Mapping):
        raise _Invalide(f"{nom}.faits : objet attendu")
    source = {"type": type_source, "reference": f"{identifiant}@{version}", "declare_le": recu_le}
    return source, dict(faits), sorted(set(faits) - set(CHAMPS_FACTEURS_DECLARABLES))


def _meteo(brut: Any, nom_service: str) -> dict[str, Any]:
    """Facteur météo : les règles que l'entreprise a DÉCLARÉES pour ce service (jamais une prévision)."""
    if brut is None:
        return {
            "facteur": "meteo",
            "statut": "inconnu",
            "valeur": None,
            "sources": [],
            "a_collecter": _A_COLLECTER["meteo"],
        }
    m = _objet(
        brut,
        "meteo_service",
        ("service", "profil_present", "reference", "fuseau", "risques_juges", "sans_objet", "a_decider"),
    )
    if m.get("service") != nom_service:
        raise _Invalide("meteo_service.service ne correspond pas au service du contexte")
    if type(m.get("profil_present")) is not bool:
        raise _Invalide("meteo_service.profil_present : booléen attendu")
    listes = {}
    for cle in ("risques_juges", "sans_objet", "a_decider"):
        valeur = m.get(cle, [])
        if not isinstance(valeur, list) or not all(isinstance(x, str) and _CODE.fullmatch(x) for x in valeur):
            raise _Invalide(f"meteo_service.{cle} : liste de codes attendue")
        listes[cle] = sorted(set(valeur))
    if not m["profil_present"] or not (listes["risques_juges"] or listes["sans_objet"]):
        return {
            "facteur": "meteo",
            "statut": "inconnu",
            "valeur": None,
            "sources": [],
            "a_collecter": _A_COLLECTER["meteo"],
        }
    source = {"type": "profil_meteo_entreprise", "reference": m.get("reference"), "declare_le": None}
    statut = "a_verifier" if listes["a_decider"] else "connu"
    fuseau = m.get("fuseau")
    return {
        "facteur": "meteo",
        "statut": statut,
        "valeur": {
            "fuseau": fuseau if isinstance(fuseau, str) else None,
            **listes,
            "nature": "regles_declarees_par_l_entreprise_pas_une_prevision",
        },
        "sources": [source],
        "a_collecter": _A_COLLECTER["meteo"] if statut != "connu" else None,
    }


def _permis(brut: Any, municipalite: str | None) -> dict[str, Any]:
    """Les permis municipaux sont des DONNÉES À VÉRIFIER : sans vérification complète, jamais « non requis »."""
    entrees = brut if brut is not None else []
    if not isinstance(entrees, list) or len(entrees) > 10:
        raise _Invalide("permis_municipaux : liste de 10 entrées au plus")
    verifies: list[dict[str, Any]] = []
    a_verifier: list[dict[str, Any]] = []
    sources = []
    for position, entree in enumerate(entrees):
        nom = f"permis_municipaux[{position}]"
        e = _objet(entree, nom, ("type_permis", "exigence", "verifie_par", "verifie_le", "reference"))
        type_permis = e.get("type_permis")
        if not isinstance(type_permis, str) or not _CODE.fullmatch(type_permis):
            raise _Invalide(f"{nom}.type_permis : code en minuscules attendu")
        exigence = e.get("exigence", "inconnue")
        if exigence not in _EXIGENCES:
            raise _Invalide(f"{nom}.exigence : {sorted(_EXIGENCES)}")
        if exigence == "inconnue":
            a_verifier.append({"type_permis": type_permis, "exigence": "inconnue"})
            continue
        try:
            par = _texte(e.get("verifie_par"), f"{nom}.verifie_par", maximum=80)
            le = _horodatage(e.get("verifie_le"), f"{nom}.verifie_le")
            reference = _texte(e.get("reference"), f"{nom}.reference", maximum=120)
        except _Invalide as exc:
            raise _SourceAbsente(
                f"{nom} : « {exigence} » exige la preuve de la vérification "
                f"(verifie_par, verifie_le, reference) : {exc}"
            ) from None
        verifies.append(
            {
                "type_permis": type_permis,
                "exigence": exigence,
                "verifie_par": par,
                "verifie_le": le,
                "reference": reference,
            }
        )
        sources.append(
            {"type": "verification_municipale", "reference": reference, "declare_le": le, "declare_par": par}
        )
    complet = bool(verifies) and not a_verifier
    valeur = {
        "municipalite": municipalite,
        "verifies": sorted(verifies, key=lambda x: x["type_permis"]),
        "a_verifier": sorted(a_verifier, key=lambda x: x["type_permis"]),
        "exhaustif": False,
        "nature": "donnee_a_verifier_aupres_de_la_municipalite",
    }
    statut = "connu" if complet and municipalite else "a_verifier"
    if statut != "connu" and not municipalite:
        valeur["manque"] = "municipalite"
    return {
        "facteur": "permis_municipaux",
        "statut": statut,
        "valeur": valeur,
        "sources": sources,
        "a_collecter": _A_COLLECTER["permis_municipaux"],
    }


def _fixer(valeur: Any) -> str:
    return journal_site.empreinte_canonique(valeur)


def _facteur_declarable(
    nom: str, ref: date, profils: list[tuple[str, dict | None, dict]], declares: Mapping[str, Any]
) -> dict[str, Any]:
    candidats: list[tuple[dict[str, Any], dict[str, Any]]] = []
    normaliser = _NORMALISEURS[nom]
    for nom_profil, profil_source, faits_profil in profils:
        if nom in faits_profil:
            assert profil_source is not None
            candidats.append((profil_source, normaliser(faits_profil[nom], f"{nom_profil}.faits.{nom}", ref)))
    if nom in declares:
        source = _source_declaration(declares[nom], f"facteurs_declares.{nom}")
        candidats.append((source, normaliser(declares[nom]["valeur"], f"facteurs_declares.{nom}.valeur", ref)))
    if not candidats:
        return {"facteur": nom, "statut": "inconnu", "valeur": None, "sources": [], "a_collecter": _A_COLLECTER[nom]}
    distincts = {_fixer(v) for _, v in candidats}
    sources = [s for s, _ in candidats]
    if len(distincts) == 1:
        return {"facteur": nom, "statut": "connu", "valeur": candidats[0][1], "sources": sources, "a_collecter": None}
    return {
        "facteur": nom,
        "statut": "conflit",
        "valeur": None,
        "sources": sources,
        "valeurs_en_conflit": [{"source": s, "valeur": v} for s, v in candidats],
        "a_collecter": "Deux sources se contredisent : une personne tranche (aucune n'est retenue par défaut).",
    }


def _hypotheses(facteurs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sortie = []
    for f in facteurs:
        nom, statut = f["facteur"], f["statut"]
        if statut == "connu":
            sortie.append(
                {
                    "facteur": nom,
                    "nature": "donnee_retenue",
                    "texte": "Donnée sourcée retenue ; l'effet sur le prix vient des moteurs d'estimation, "
                    "pas de ce contexte.",
                }
            )
        elif statut == "inconnu":
            sortie.append({"facteur": nom, "nature": "a_collecter", "texte": _A_COLLECTER[nom]})
        elif statut == "conflit":
            sortie.append({"facteur": nom, "nature": "conflit_a_trancher", "texte": f["a_collecter"]})
        else:
            sortie.append({"facteur": nom, "nature": "a_verifier", "texte": _A_COLLECTER[nom]})
    return sortie


def construire(
    entrees: Any, precedent: Mapping[str, Any] | None = None
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """``(contexte, None)`` ou ``(None, verdict)``.

    ``entrees`` : ``lead_id``, ``service`` (code), ``date_reference`` (AAAA-MM-JJ), et facultativement
    ``municipalite``, ``profil_propriete`` (M2), ``facteurs_declares`` (``{facteur: {valeur, declare_par, declare_le,
    reference?}}``), ``meteo_service`` (règles météo de l'entreprise), ``permis_municipaux``. ``precedent`` : le
    contexte de la version
    précédente du même lead (le numéro de version s'incrémente seulement si le contenu change)."""
    try:
        e = _objet(
            entrees,
            "entrees",
            (
                "lead_id",
                "service",
                "date_reference",
                "municipalite",
                "profil_propriete",
                "profil_geospatial",
                "facteurs_declares",
                "meteo_service",
                "permis_municipaux",
            ),
        )
        lead_id = _texte(e.get("lead_id"), "lead_id", maximum=80)
        service = e.get("service")
        if not isinstance(service, str) or not _CODE.fullmatch(service):
            raise _Invalide("service : code en minuscules attendu")
        ref = _date(e.get("date_reference"), "date_reference")
        municipalite = None if e.get("municipalite") is None else _texte(e["municipalite"], "municipalite", maximum=80)
        declares = e.get("facteurs_declares", {})
        if not isinstance(declares, Mapping):
            raise _Invalide("facteurs_declares : objet attendu")
        inconnus = sorted(set(declares) - set(CHAMPS_FACTEURS_DECLARABLES))
        if inconnus:
            raise _Invalide(f"facteurs_declares : facteurs non admis {inconnus}")
        for nom, d in declares.items():
            if not isinstance(d, Mapping):
                raise _Invalide(f"facteurs_declares.{nom} : objet attendu")
        profil_source, faits_profil, ignores = _profil(e.get("profil_propriete"))
        geo_source, faits_geo, ignores_geo = _profil(e.get("profil_geospatial"), "profil_geospatial", "port_geospatial")
        profils = [("profil_propriete", profil_source, faits_profil), ("profil_geospatial", geo_source, faits_geo)]
        ignores = sorted(set(ignores) | set(ignores_geo))
        facteurs = []
        for nom in CHAMPS_FACTEURS:
            if nom == "meteo":
                facteurs.append(_meteo(e.get("meteo_service"), service))
            elif nom == "permis_municipaux":
                facteurs.append(_permis(e.get("permis_municipaux"), municipalite))
            else:
                facteurs.append(_facteur_declarable(nom, ref, profils, declares))
    except _SourceAbsente as exc:
        return None, _refus("REJ-CONTEXTE-SOURCE-ABSENTE", str(exc))
    except _Invalide as exc:
        return None, _refus("REJ-CONTEXTE-ENTREE-INVALIDE", str(exc))
    contenu = {
        "schema": SCHEMA,
        "lead_id": lead_id,
        "service": service,
        "date_reference": ref.isoformat(),
        "municipalite": municipalite,
        "facteurs": facteurs,
        "inconnus": [f["facteur"] for f in facteurs if f["statut"] == "inconnu"],
        "a_verifier": [f["facteur"] for f in facteurs if f["statut"] == "a_verifier"],
        "conflits": [f["facteur"] for f in facteurs if f["statut"] == "conflit"],
        "faits_ignores": ignores,
        "hypotheses_estimation": _hypotheses(facteurs),
        "bloque_le_prix": False,
        "mention": MENTION,
    }
    empreinte_contenu = journal_site.empreinte_canonique(contenu)
    if precedent is not None:
        if precedent.get("lead_id") != lead_id or precedent.get("schema") != SCHEMA:
            return None, _refus("REJ-CONTEXTE-ENTREE-INVALIDE", "la version précédente n'est pas celle de ce lead")
        if precedent.get("empreinte_contenu") == empreinte_contenu:
            return copy.deepcopy(dict(precedent)), None
        version, hash_precedent = precedent["version"] + 1, precedent["empreinte"]
    else:
        version, hash_precedent = 1, None
    contexte = {**contenu, "version": version, "precedent": hash_precedent, "empreinte_contenu": empreinte_contenu}
    contexte["empreinte"] = journal_site.empreinte_canonique(contexte)
    return contexte, None


def empreinte_contexte(contexte: Mapping[str, Any]) -> str:
    """Recalcule l'empreinte d'un contexte (sans son champ ``empreinte``) : sert à détecter une retouche."""
    return journal_site.empreinte_canonique({k: v for k, v in contexte.items() if k != "empreinte"})


def resume_hypotheses(contexte: Mapping[str, Any]) -> dict[str, Any]:
    """Ce que l'estimation reprend du contexte : l'empreinte, la version, les hypothèses et les manques, rien
    d'autre."""
    return {
        "empreinte": contexte["empreinte"],
        "version": contexte["version"],
        "hypotheses_estimation": copy.deepcopy(contexte["hypotheses_estimation"]),
        "inconnus": list(contexte["inconnus"]),
        "a_verifier": list(contexte["a_verifier"]),
        "conflits": list(contexte["conflits"]),
    }

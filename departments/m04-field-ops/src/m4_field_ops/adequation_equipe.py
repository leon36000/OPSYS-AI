"""Indice d'adéquation ÉQUIPE ↔ INTERVENTION (M4.11) : transparent, explicable, déterministe, équitable.

CE QUE C'EST. Une PROPOSITION d'ordre des équipes admissibles pour une intervention, que l'humain accepte, change ou
refuse : M4 propose, la direction affecte. L'indice est celui d'un COUPLE (équipe, intervention) : il dit « cette
équipe est bien placée pour ce chantier », jamais « cette équipe (ou cette personne) est bonne ou mauvaise ». Aucune
note de performance d'un technicien, aucun classement de personnes, aucune sanction (DEFINITION-PRODUIT M4, garde-fous
humains ; SOUL.md M4 ; Loi 25).

LES ÉLÉMENTS.

* CONTRAINTES (filtre, pas de note) : l'équipe détient toutes les compétences que le profil exige du service ; la
  capacité libre de la semaine (heures de quart déclarées à la SEMAINE TYPE moins ce que la cédule appliquée a déjà
  planifié, voir ``capacite_equipe``) couvre la durée du service. Une capacité non calculable rend l'équipe « non
  évaluable », jamais zéro.
* CRITÈRES notés, tous dans [0, 1], en nombres rationnels exacts (``Fraction``) :
    ``capacite``  marge restante après le chantier : (libre - durée) / libre ;
    ``charge``    équilibre de charge : 1 - planifié / disponible (une équipe moins chargée est préférée) ;
    ``distance``  proximité du dépôt : 1 - min(d, d_ref) / d_ref (distance droite, ``d_ref`` déclarée) ;
    ``qualite``   part des chantiers terminés sans écart ouvert, SI l'historique est assez long ET l'équipe compte au
      moins deux
                  membres déclarés (jamais le dossier d'une personne seule).
* POIDS déclarés par l'entreprise (``configuration.adequation``), jamais devinés. Un critère n'est ACTIF que si la
  donnée existe pour TOUTES les équipes comparées : sinon il est écarté pour toutes (et le dit), pour qu'aucune équipe
  ne soit avantagée ou pénalisée par une donnée manquante. L'indice = somme des poids actifs x sous-indices / somme
  des poids actifs.

ÉQUITÉ. L'entrée est une liste fermée de champs d'équipe : compétences (codes), nombre de membres déclarés (jamais
leurs noms), dépôt, capacité, historique agrégé. Tout champ qui nomme un attribut personnel protégé (âge, sexe, genre,
origine, religion, langue, état civil, handicap, santé, opinions, famille…) ou une personne est REFUSÉ avec
``REJ-ADEQUATION-ATTRIBUT-INTERDIT``, avant toute note. L'indice est invariant à l'ordre des équipes et à leurs noms ;
seul l'ex aequo est départagé par l'identifiant d'équipe (ordre lexicographique, sans signification), et il est
signalé comme ex aequo.

EXPLICATION. Chaque équipe porte, par critère, sa valeur brute, son sous-indice, son poids effectif et sa
contribution, plus une phrase fixe en français. Aucun texte de modèle.

CALIBRATION. ``calibrer_poids`` cherche, sur une grille exacte, les poids qui reproduisent le mieux des choix humains
  sur des cas
FICTIFS (``fictif: true`` exigé : aucune donnée réelle). Il ne fixe rien : adopter des poids est une décision de
l'entreprise.

Module pur : stdlib seulement, aucun import ``opsys``, aucune horloge, aucun aléa, aucun réseau.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from decimal import ROUND_HALF_EVEN, Decimal
from fractions import Fraction
from typing import Any

from . import encodage, verdicts

__all__ = [
    "CRITERES",
    "VERSION",
    "calibrer_poids",
    "ordonner",
    "lire_parametres",
]

VERSION = "m4.adequation/1"
CRITERES = ("capacite", "charge", "distance", "qualite")
MISE_EN_GARDE = (
    "Proposition d'affectation pour CETTE intervention : elle ne note aucune personne et n'entraîne aucune sanction. "
    "L'humain affecte ; un engagement envers le client exige une approbation."
)
_CODE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
_IDENTIFIANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,79}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DECIMAL = re.compile(r"^\d{1,6}(\.\d{1,6})?$")
_JEU_EQUIPE = frozenset({"equipe_id", "competences", "membres_declares", "distance_m", "capacite", "historique"})
_JEU_INTERVENTION = frozenset({"intervention_id", "service", "date", "duree_min", "competences_requises"})
_QUANTUM = Decimal("0.0001")
# Attributs personnels protégés (Charte des droits et libertés de la personne, art. 10, et santé) et marqueurs de
# personne : un champ dont un JETON porte l'un de ces mots est refusé, quelle que soit sa valeur.
_JETONS_INTERDITS = frozenset(
    {
        "age",
        "ages",
        "sexe",
        "genre",
        "race",
        "couleur",
        "langue",
        "photo",
        "visage",
        "nom",
        "prenom",
        "medical",
        "casier",
        "technicien",
        "personne",
        "employe",
        "employes",
        "enfants",
        "enfant",
        "conjoint",
        "salaire",
        "revenu",
        "civil",
    }
)
# Racines de mots plus longs (masculin, féminin, pluriel) : un jeton qui COMMENCE par l'une d'elles est refusé.
_RACINES_INTERDITES = (
    "identit",
    "orientat",
    "grossess",
    "ethni",
    "nationalit",
    "citoyen",
    "origin",
    "relig",
    "conviction",
    "opinion",
    "politi",
    "handicap",
    "sant",
    "maladi",
    "invalid",
    "syndic",
    "judiciair",
    "famil",
    "naissanc",
)
# Clés qui, TELLES QUELLES, désignent des personnes (la liste nominative des membres) ; ``membres_declares`` (un
# nombre) est permis.
_CLES_PERSONNES = frozenset({"membres", "membre", "equipiers", "noms"})


def _refus(code: str, detail: str) -> dict[str, Any]:
    return verdicts.construire_verdict(code, detail=detail)


def _jetons(cle: str) -> list[str]:
    sans_accent = "".join(c for c in unicodedata.normalize("NFKD", cle) if not unicodedata.combining(c))
    return [t for t in re.split(r"[^a-z0-9]+", sans_accent.lower()) if t]


def _chercher_interdit(valeur: Any, chemin: str = "") -> str | None:
    """Chemin du premier champ (à toute profondeur) dont un jeton est un attribut protégé ou un marqueur de personne."""
    if isinstance(valeur, Mapping):
        for cle, sous in valeur.items():
            cle_t = str(cle)
            if "_".join(_jetons(cle_t)) in _CLES_PERSONNES or any(
                jeton in _JETONS_INTERDITS or jeton.startswith(_RACINES_INTERDITES) for jeton in _jetons(cle_t)
            ):
                return f"{chemin}{cle_t}"
            trouve = _chercher_interdit(sous, f"{chemin}{cle_t}.")
            if trouve:
                return trouve
    elif isinstance(valeur, (list, tuple)):
        for position, sous in enumerate(valeur):
            trouve = _chercher_interdit(sous, f"{chemin}[{position}].")
            if trouve:
                return trouve
    return None


def lire_parametres(brut: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """``(parametres, None)`` ou ``(None, verdict)``. Poids, distance de référence et historique minimal sont
    DÉCLARÉS."""
    detail = (
        "déclarer configuration.adequation : poids (capacite, charge, distance, qualite : textes décimaux >= 0, "
        "au moins un > 0), distance_reference_km (entier > 0) et historique_minimum (entier > 0)"
    )
    if not isinstance(brut, Mapping):
        return None, _refus("REJ-ADEQUATION-PARAMETRES-ABSENTS", f"paramètres absents : {detail}")
    if set(brut) - {"poids", "distance_reference_km", "historique_minimum"}:
        return None, _refus("REJ-ADEQUATION-PARAMETRES-ABSENTS", f"paramètres non admis : {detail}")
    poids = brut.get("poids")
    distance_ref, minimum = brut.get("distance_reference_km"), brut.get("historique_minimum")
    if (
        not isinstance(poids, Mapping)
        or set(poids) - set(CRITERES)
        or not poids
        or type(distance_ref) is not int
        or not 0 < distance_ref <= 2000
        or type(minimum) is not int
        or not 0 < minimum <= 1000
    ):
        return None, _refus("REJ-ADEQUATION-PARAMETRES-ABSENTS", f"paramètres absents ou invalides : {detail}")
    normalises = {}
    for critere in CRITERES:
        texte = poids.get(critere, "0")
        if not isinstance(texte, str) or not _DECIMAL.fullmatch(texte):
            return None, _refus("REJ-ADEQUATION-PARAMETRES-ABSENTS", f"poids.{critere} : texte décimal >= 0 attendu")
        normalises[critere] = Fraction(texte)
    if sum(normalises.values()) == 0:
        return None, _refus("REJ-ADEQUATION-PARAMETRES-ABSENTS", f"tous les poids sont nuls : {detail}")
    return {"poids": normalises, "distance_reference_m": distance_ref * 1000, "historique_minimum": minimum}, None


def _entier(valeur: Any, minimum: int, maximum: int) -> bool:
    return type(valeur) is int and minimum <= valeur <= maximum


def _valider_entrees(entrees: Any) -> dict[str, Any] | None:
    if not isinstance(entrees, Mapping) or set(entrees) != {"intervention", "equipes"}:
        return _refus("REJ-ADEQUATION-ENTREE-INVALIDE", "entrées : intervention et equipes (rien d'autre)")
    interdit = _chercher_interdit(entrees)
    if interdit:
        return _refus(
            "REJ-ADEQUATION-ATTRIBUT-INTERDIT",
            f"le champ « {interdit} » nomme un attribut personnel protégé ou une personne : l'adéquation est "
            "celle d'une équipe pour une intervention, elle n'en tient jamais compte",
        )
    i = entrees["intervention"]
    if (
        not isinstance(i, Mapping)
        or set(i) - _JEU_INTERVENTION
        or not set(i) >= _JEU_INTERVENTION
        or not isinstance(i["intervention_id"], str)
        or not _IDENTIFIANT.fullmatch(i["intervention_id"])
        or not isinstance(i["service"], str)
        or not _CODE.fullmatch(i["service"])
        or not isinstance(i["date"], str)
        or not _DATE.fullmatch(i["date"])
        or not _entier(i["duree_min"], 1, 1440)
        or not isinstance(i["competences_requises"], list)
        or len(i["competences_requises"]) > 20
        or not all(isinstance(c, str) and _CODE.fullmatch(c) for c in i["competences_requises"])
    ):
        return _refus("REJ-ADEQUATION-ENTREE-INVALIDE", "intervention mal formée")
    equipes = entrees["equipes"]
    if not isinstance(equipes, list) or not 1 <= len(equipes) <= 200:
        return _refus("REJ-ADEQUATION-ENTREE-INVALIDE", "equipes : 1 à 200 équipes attendues")
    vus = set()
    for e in equipes:
        if (
            not isinstance(e, Mapping)
            or set(e) - _JEU_EQUIPE
            or not {"equipe_id", "competences", "membres_declares"} <= set(e)
            or not isinstance(e["equipe_id"], str)
            or not _IDENTIFIANT.fullmatch(e["equipe_id"])
            or e["equipe_id"] in vus
            or not isinstance(e["competences"], list)
            or len(e["competences"]) > 50
            or not all(isinstance(c, str) and _CODE.fullmatch(c) for c in e["competences"])
            or not _entier(e["membres_declares"], 0, 50)
        ):
            return _refus("REJ-ADEQUATION-ENTREE-INVALIDE", "équipe mal formée, ou identifiant d'équipe répété")
        vus.add(e["equipe_id"])
        if e.get("distance_m") is not None and not _entier(e["distance_m"], 0, 20_000_000):
            return _refus("REJ-ADEQUATION-ENTREE-INVALIDE", "distance_m : entier de mètres attendu, ou absent")
        c = e.get("capacite")
        if c is not None and (
            not isinstance(c, Mapping)
            or set(c) != {"minutes_disponibles", "minutes_planifiees"}
            or not _entier(c["minutes_disponibles"], 0, 10**7)
            or not _entier(c["minutes_planifiees"], 0, 10**7)
        ):
            return _refus(
                "REJ-ADEQUATION-ENTREE-INVALIDE", "capacite : minutes_disponibles et minutes_planifiees entières"
            )
        h = e.get("historique")
        if h is not None and (
            not isinstance(h, Mapping)
            or set(h) != {"terminees", "avec_ecart"}
            or not _entier(h["terminees"], 0, 10**6)
            or not _entier(h["avec_ecart"], 0, 10**6)
            or h["avec_ecart"] > h["terminees"]
        ):
            return _refus(
                "REJ-ADEQUATION-ENTREE-INVALIDE",
                "historique : terminees et avec_ecart entiers, avec_ecart <= terminees",
            )
    return None


def _texte(valeur: Fraction) -> str:
    return format(
        (Decimal(valeur.numerator) / Decimal(valeur.denominator)).quantize(_QUANTUM, rounding=ROUND_HALF_EVEN), "f"
    )


def _sous_indices(
    equipe: Mapping[str, Any], duree: int, parametres: Mapping[str, Any]
) -> dict[str, tuple[Fraction | None, str]]:
    """Par critère : ``(sous-indice ou None si la donnée manque, valeur brute en texte)``."""
    sortie: dict[str, tuple[Fraction | None, str]] = {}
    cap = equipe.get("capacite")
    libre = None if cap is None else cap["minutes_disponibles"] - cap["minutes_planifiees"]
    sortie["capacite"] = (
        (None, "inconnue")
        if libre is None or libre <= 0
        else (Fraction(libre - duree, libre), f"{libre - duree} min libres après le chantier sur {libre}")
    )
    sortie["charge"] = (
        (None, "inconnue")
        if cap is None or cap["minutes_disponibles"] <= 0
        else (
            1 - Fraction(cap["minutes_planifiees"], cap["minutes_disponibles"]),
            f"{cap['minutes_planifiees']} min planifiées sur {cap['minutes_disponibles']}",
        )
    )
    d = equipe.get("distance_m")
    ref = parametres["distance_reference_m"]
    sortie["distance"] = (
        (None, "inconnue") if d is None else (1 - Fraction(min(d, ref), ref), f"{d} m du dépôt (référence {ref} m)")
    )
    h = equipe.get("historique")
    if h is None or h["terminees"] < parametres["historique_minimum"] or equipe["membres_declares"] < 2:
        sortie["qualite"] = (None, "non utilisable")
    else:
        sortie["qualite"] = (
            1 - Fraction(h["avec_ecart"], h["terminees"]),
            f"{h['avec_ecart']} écart(s) sur {h['terminees']} chantiers terminés",
        )
    return sortie


def ordonner(entrees: Any, parametres: Mapping[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """``(ordre, None)`` ou ``(None, verdict)``. ``parametres`` : la sortie de ``lire_parametres``."""
    verdict = _valider_entrees(entrees)
    if verdict is not None:
        return None, verdict
    intervention, equipes = entrees["intervention"], entrees["equipes"]
    requises = set(intervention["competences_requises"])
    exclues, non_evaluables, candidates = [], [], []
    for equipe in sorted(equipes, key=lambda e: e["equipe_id"]):
        manquantes = sorted(requises - set(equipe["competences"]))
        if manquantes:
            exclues.append(
                {
                    "equipe_id": equipe["equipe_id"],
                    "motifs": ["competence_manquante"],
                    "detail": "compétence(s) manquante(s) : " + ", ".join(manquantes),
                }
            )
            continue
        cap = equipe.get("capacite")
        if cap is None:
            non_evaluables.append(
                {
                    "equipe_id": equipe["equipe_id"],
                    "motifs": ["capacite_non_calculable"],
                    "detail": "capacité de la semaine inconnue (semaine type, congés ou cédule incomplets)",
                }
            )
            continue
        libre = cap["minutes_disponibles"] - cap["minutes_planifiees"]
        if libre < intervention["duree_min"]:
            exclues.append(
                {
                    "equipe_id": equipe["equipe_id"],
                    "motifs": ["capacite_insuffisante"],
                    "detail": f"{max(libre, 0)} min libres dans la semaine pour "
                    f"{intervention['duree_min']} min requises",
                }
            )
            continue
        candidates.append(equipe)
    base = {
        "schema": VERSION,
        "intervention_id": intervention["intervention_id"],
        "mise_en_garde": MISE_EN_GARDE,
        "decision": "humain",
        "exclues": exclues,
        "non_evaluables": non_evaluables,
    }
    if not candidates:
        base.update(
            {"ordre": [], "criteres_actifs": [], "criteres_ecartes": [], "motif_vide": "aucune équipe admissible"}
        )
        base["empreinte"] = encodage.empreinte(VERSION, base)
        return base, None
    notes = {e["equipe_id"]: _sous_indices(e, intervention["duree_min"], parametres) for e in candidates}
    actifs, ecartes = [], []
    for critere in CRITERES:
        poids = parametres["poids"][critere]
        manquent = sorted(eid for eid, s in notes.items() if s[critere][0] is None)
        if poids == 0:
            ecartes.append({"critere": critere, "raison": "poids nul"})
        elif manquent:
            ecartes.append(
                {"critere": critere, "raison": "donnée manquante ou inutilisable pour : " + ", ".join(manquent)}
            )
        else:
            actifs.append(critere)
    if not actifs:
        return None, _refus(
            "REJ-ADEQUATION-PARAMETRES-ABSENTS",
            "aucun critère pondéré n'a de donnée pour toutes les équipes comparées : "
            + "; ".join(f"{e['critere']} ({e['raison']})" for e in ecartes),
        )
    total_poids = sum(parametres["poids"][c] for c in actifs)
    lignes = []
    for equipe in candidates:
        eid = equipe["equipe_id"]
        details, indice = [], Fraction(0)
        for critere in CRITERES:
            sous, brut = notes[eid][critere]
            if critere in actifs:
                effectif = parametres["poids"][critere] / total_poids
                contribution = effectif * sous
                indice += contribution
                details.append(
                    {
                        "critere": critere,
                        "valeur": brut,
                        "sous_indice": _texte(sous),
                        "poids_effectif": _texte(effectif),
                        "contribution": _texte(contribution),
                        "actif": True,
                    }
                )
            else:
                details.append(
                    {
                        "critere": critere,
                        "valeur": brut,
                        "sous_indice": None,
                        "poids_effectif": "0.0000",
                        "contribution": "0.0000",
                        "actif": False,
                    }
                )
        lignes.append((indice, eid, details))
    lignes.sort(key=lambda t: (-t[0], t[1]))
    ordre = []
    rang_precedent, indice_precedent = 0, None
    for position, (indice, eid, details) in enumerate(lignes, start=1):
        rang = rang_precedent if indice == indice_precedent else position
        rang_precedent, indice_precedent = rang, indice
        ex_aequo = sum(1 for s, _, _ in lignes if s == indice) > 1
        phrase = (
            f"Équipe {eid} : adéquation {_texte(indice)} pour cette intervention ; "
            + " ; ".join(
                f"{d['critere']} {d['valeur']} (sous-indice {d['sous_indice']}, poids {d['poids_effectif']})"
                for d in details
                if d["actif"]
            )
            + "."
        )
        ordre.append(
            {
                "equipe_id": eid,
                "rang": rang,
                "adequation": _texte(indice),
                "ex_aequo": ex_aequo,
                "criteres": details,
                "explication": phrase,
            }
        )
    base.update(
        {
            "ordre": ordre,
            "criteres_actifs": actifs,
            "criteres_ecartes": ecartes,
            "departage": "ex aequo départagés par l'identifiant d'équipe (ordre lexicographique, sans signification)",
            "poids_declares": {c: _texte(parametres["poids"][c]) for c in CRITERES},
        }
    )
    base["empreinte"] = encodage.empreinte(VERSION, base)
    return base, None


def _grille(pas: int, n: int):
    """Tous les vecteurs d'entiers >= 0 de somme ``pas`` (poids = entier / pas), en ordre lexicographique, sans le
    vecteur nul."""
    if n == 1:
        yield (pas,)
        return
    for premier in range(pas + 1):
        for reste in _grille(pas - premier, n - 1):
            yield (premier, *reste)


def calibrer_poids(
    cas: Any, base_parametres: Mapping[str, Any], pas: int = 10
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Cherche, sur une grille exacte (pas = 1/``pas``), les poids qui reproduisent le mieux des choix humains FICTIFS.

    ``cas`` : liste de ``{fictif: true, entrees: {intervention, equipes}, choix_humain: equipe_id}``. Un cas est «
    réussi » si le ordre a une seule équipe en tête et que c'est le choix humain. Départage des poids de même accord :
    le plus proche de l'uniforme (somme des carrés minimale), puis l'ordre lexicographique. ``base_parametres``
    fournit ``distance_reference_km`` et
    ``historique_minimum`` (les poids sont ceux qu'on cherche)."""
    if type(pas) is not int or not 1 <= pas <= 20:
        return None, _refus("REJ-ADEQUATION-ENTREE-INVALIDE", "pas : entier de 1 à 20")
    if not isinstance(cas, list) or not 1 <= len(cas) <= 500:
        return None, _refus("REJ-ADEQUATION-ENTREE-INVALIDE", "cas : 1 à 500 cas attendus")
    for position, c in enumerate(cas):
        if not isinstance(c, Mapping) or set(c) != {"fictif", "entrees", "choix_humain"}:
            return None, _refus(
                "REJ-ADEQUATION-ENTREE-INVALIDE", f"cas[{position}] : fictif, entrees et choix_humain requis"
            )
        if c["fictif"] is not True:
            return None, _refus(
                "REJ-ADEQUATION-DONNEES-REELLES-REFUSEES",
                f"cas[{position}] n'est pas déclaré fictif : la calibration n'accepte aucune donnée réelle "
                "(consentement et EFVP Loi 25 requis avant)",
            )
        verdict = _valider_entrees(c["entrees"])
        if verdict is not None:
            return None, verdict
        if c["choix_humain"] not in {e["equipe_id"] for e in c["entrees"]["equipes"]}:
            return None, _refus(
                "REJ-ADEQUATION-ENTREE-INVALIDE", f"cas[{position}] : choix_humain hors des équipes du cas"
            )
    meilleur: tuple[Any, ...] | None = None
    evalues = 0
    for vecteur in _grille(pas, len(CRITERES)):
        if sum(vecteur) == 0:
            continue
        parametres, verdict = lire_parametres(
            {
                "poids": {
                    c: str(Fraction(v, pas).numerator)
                    if Fraction(v, pas).denominator == 1
                    else format(Decimal(v) / Decimal(pas), "f")
                    for c, v in zip(CRITERES, vecteur, strict=True)
                },
                "distance_reference_km": base_parametres["distance_reference_km"],
                "historique_minimum": base_parametres["historique_minimum"],
            }
        )
        if verdict is not None:
            return None, verdict
        evalues += 1
        reussis = 0
        for c in cas:
            ordre, verdict = ordonner(c["entrees"], parametres)
            if verdict is not None or not ordre["ordre"]:
                continue
            tete = ordre["ordre"][0]
            if tete["rang"] == 1 and not tete["ex_aequo"] and tete["equipe_id"] == c["choix_humain"]:
                reussis += 1
        cle = (-reussis, sum(v * v for v in vecteur), vecteur)
        if meilleur is None or cle < meilleur[0]:
            meilleur = (cle, vecteur, reussis)
    assert meilleur is not None
    _, vecteur, reussis = meilleur
    return {
        "schema": "m4.adequation.calibration/1",
        "fictif": True,
        "poids": {c: format(Decimal(v) / Decimal(pas), "f") for c, v in zip(CRITERES, vecteur, strict=True)},
        "accord": {"reussis": reussis, "cas": len(cas), "ratio": _texte(Fraction(reussis, len(cas)))},
        "grille": {"pas": pas, "vecteurs_evalues": evalues},
        "limite": (
            "calibration sur données fictives : elle prouve la mécanique, pas la réalité du terrain ; adopter "
            "des poids "
            "est une décision de l'entreprise (configuration.adequation), jamais de ce calcul"
        ),
    }, None

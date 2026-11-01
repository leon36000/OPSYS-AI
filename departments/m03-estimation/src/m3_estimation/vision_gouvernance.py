"""Gouvernance des mesures issues de la vision (M3.3, M3.5) : un candidat n'est JAMAIS une mesure.

LA RÈGLE. Une grandeur calculée à partir d'une sortie de modèle reste un CANDIDAT. Elle ne devient une mesure retenue
que par l'une de deux voies, et seulement si la politique de l'entreprise a été DÉCLARÉE :

1. une MESURE DE RÉFÉRENCE (mesure manuelle, plan, mesure géométrique plane de M3.6) de même unité, avec sa
  provenance, dont
   l'écart au candidat respecte la TOLÉRANCE déclarée (absolue et/ou relative : toutes celles qui sont déclarées
   doivent tenir) ;
2. la décision d'une PERSONNE (approbation N3 dans le sas OPSYS), qui valide, refuse ou CORRIGE la valeur.

Avant cela, un seuil de CONFIANCE déclaré écarte les candidats trop incertains (``rejetee_confiance``), et un candidat
sans échelle n'est pas une mesure du tout (``sans_echelle`` : plage ou hypothèse, jamais une dimension). Rien n'est
supposé : sans politique (seuil de confiance ET au moins une tolérance, avec qui les a déclarés et quand), le verdict
dit quoi déclarer.

Ce que « validé » veut dire : la grandeur peut alimenter l'estimation AVEC sa validation citée et sa tolérance comme
incertitude d'emploi. La garde de prix de M3 (photos suffisantes, référence d'échelle) s'applique toujours en amont :
valider un candidat ne débloque jamais un prix à lui seul.

Une décision par candidat, immuable : la rejouer à l'identique est un no-op ; une décision différente est un conflit.

Module pur : aucune horloge (les instants viennent de la décision approuvée), aucun aléa, aucun réseau, aucun import
``opsys``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from . import journal_site, verdicts
from .vision_contrat import empreinte_candidat, formater

__all__ = [
    "SCHEMA_DECISION",
    "SCHEMA_POLITIQUE",
    "decider_par_humain",
    "decider_par_reference",
    "evaluer",
    "lire_politique",
]

SCHEMA_POLITIQUE = "m3.vision.politique/v1"
SCHEMA_DECISION = "m3.vision.decision/v1"
_DECIMAL = re.compile(r"^\d{1,12}(\.\d{1,12})?$")
_IDENTIFIANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,119}$")
_SOURCES_REFERENCE = frozenset({"mesure_manuelle", "plan", "mesure_plan_m3_6"})


def _refus(code: str, detail: str) -> dict[str, Any]:
    return verdicts.construire_verdict(code, detail)


def _dec(texte: Any) -> Decimal | None:
    if not isinstance(texte, str) or not _DECIMAL.fullmatch(texte):
        return None
    try:
        return Decimal(texte)
    except InvalidOperation:  # pragma: no cover
        return None


def _instant(texte: Any) -> bool:
    try:
        return isinstance(texte, str) and datetime.fromisoformat(texte).tzinfo is not None
    except ValueError:
        return False


def lire_politique(brut: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """``(politique, None)`` ou ``(None, verdict)``. AUCUNE valeur par défaut : la politique est une décision de
    l'entreprise."""
    detail_declarer = (
        "déclarer la politique : seuil_confiance (texte décimal dans ]0, 1]), au moins une tolérance "
        "(tolerance_absolue, tolerance_relative), declaree_par et declaree_le"
    )
    if not isinstance(brut, Mapping):
        return None, _refus("REJ-VISION-POLITIQUE-ABSENTE", f"politique absente : {detail_declarer}")
    permises = {"seuil_confiance", "tolerance_absolue", "tolerance_relative", "declaree_par", "declaree_le"}
    if set(brut) - permises:
        return None, _refus(
            "REJ-VISION-POLITIQUE-ABSENTE", f"politique : champs non admis {sorted(set(brut) - permises)}"
        )
    seuil = _dec(brut.get("seuil_confiance"))
    absolue = _dec(brut["tolerance_absolue"]) if brut.get("tolerance_absolue") is not None else None
    relative = _dec(brut["tolerance_relative"]) if brut.get("tolerance_relative") is not None else None
    par, le = brut.get("declaree_par"), brut.get("declaree_le")
    if (
        seuil is None
        or not Decimal(0) < seuil <= Decimal(1)
        or (brut.get("tolerance_absolue") is not None and (absolue is None or absolue <= 0))
        or (
            brut.get("tolerance_relative") is not None and (relative is None or not Decimal(0) < relative <= Decimal(1))
        )
        or (absolue is None and relative is None)
        or not isinstance(par, str)
        or not _IDENTIFIANT.fullmatch(par)
        or not _instant(le)
    ):
        return None, _refus("REJ-VISION-POLITIQUE-ABSENTE", f"politique incomplète ou invalide : {detail_declarer}")
    politique = {
        "schema": SCHEMA_POLITIQUE,
        "seuil_confiance": formater(seuil),
        "tolerance_absolue": None if absolue is None else formater(absolue),
        "tolerance_relative": None if relative is None else formater(relative),
        "declaree_par": par,
        "declaree_le": le,
    }
    politique["empreinte"] = journal_site.empreinte_canonique(politique)
    return politique, None


def evaluer(candidat: Mapping[str, Any], politique: Mapping[str, Any]) -> dict[str, Any]:
    """État d'un candidat face à la politique, SANS décision : ``sans_echelle``, ``rejetee_confiance`` ou ``candidate``.
    Dans les trois cas, aucune valeur n'est retenue et rien n'est utilisable comme mesure."""
    raisons = []
    if candidat.get("sans_echelle") or candidat.get("valeur") is None:
        statut = "sans_echelle"
        raisons.append("aucune échelle : plage ou hypothèse seulement, pas de mesure")
    elif Decimal(candidat["confiance"]) < Decimal(politique["seuil_confiance"]):
        statut = "rejetee_confiance"
        raisons.append(f"confiance {candidat['confiance']} sous le seuil déclaré {politique['seuil_confiance']}")
    else:
        statut = "candidate"
        raisons.append("en attente d'une mesure de référence ou de la décision d'une personne")
    return {
        "candidat_id": candidat["candidat_id"],
        "statut": statut,
        "raisons": raisons,
        "valeur_retenue": None,
        "utilisable_comme_mesure": False,
        "politique": politique["empreinte"],
    }


def _precheck(candidat: Mapping[str, Any], politique: Mapping[str, Any]) -> dict[str, Any] | None:
    if empreinte_candidat(candidat) != candidat.get("empreinte"):
        return _refus("REJ-VISION-CANDIDAT-ALTERE", "l'empreinte du candidat ne correspond plus à son contenu")
    etat = evaluer(candidat, politique)
    if etat["statut"] != "candidate":
        return _refus(
            "REJ-VISION-DECISION-INVALIDE", f"un candidat {etat['statut']} ne se valide pas : {etat['raisons'][0]}"
        )
    return None


def _finaliser(corps: dict[str, Any]) -> dict[str, Any]:
    corps["schema"] = SCHEMA_DECISION
    corps["non_verite"] = (
        "la mesure retenue vient de cette validation citée, pas d'un modèle ; la garde de prix de M3 "
        "(photos, échelle) s'applique toujours"
    )
    corps["empreinte"] = journal_site.empreinte_canonique(corps)
    return corps


def decider_par_reference(
    candidat: Mapping[str, Any],
    politique: Mapping[str, Any],
    reference: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Valide (ou rejette pour écart) un candidat face à une mesure de référence. ``(decision, None)`` ou ``(None,
    verdict)``."""
    refus = _precheck(candidat, politique)
    if refus is not None:
        return None, refus
    cle = {"reference_id", "source", "valeur", "unite", "mesure_par", "mesure_le"}
    if (
        not isinstance(reference, Mapping)
        or set(reference) - cle - {"incertitude_absolue"}
        or not cle <= set(reference)
        or not isinstance(reference["reference_id"], str)
        or not _IDENTIFIANT.fullmatch(reference["reference_id"])
        or reference["source"] not in _SOURCES_REFERENCE
        or not isinstance(reference["mesure_par"], str)
        or not _IDENTIFIANT.fullmatch(reference["mesure_par"])
        or not _instant(reference["mesure_le"])
    ):
        return None, _refus(
            "REJ-VISION-DECISION-INVALIDE",
            "référence : reference_id, source, valeur, unite, mesure_par et mesure_le requis",
        )
    valeur_ref = _dec(reference["valeur"])
    if valeur_ref is None or valeur_ref <= 0 or reference["unite"] != candidat["unite"]:
        return None, _refus(
            "REJ-VISION-DECISION-INVALIDE",
            "référence : valeur décimale positive et même unité que le candidat attendues",
        )
    incertitude_ref = None
    if reference.get("incertitude_absolue") is not None:
        incertitude_ref = _dec(reference["incertitude_absolue"])
        if incertitude_ref is None:
            return None, _refus("REJ-VISION-DECISION-INVALIDE", "référence.incertitude_absolue : texte décimal attendu")
    valeur = Decimal(candidat["valeur"])
    ecart = abs(valeur - valeur_ref)
    manquements = []
    if politique["tolerance_absolue"] is not None and ecart > Decimal(politique["tolerance_absolue"]):
        manquements.append("tolerance_absolue")
    if politique["tolerance_relative"] is not None and ecart > Decimal(politique["tolerance_relative"]) * valeur_ref:
        manquements.append("tolerance_relative")
    accepte = not manquements
    corps: dict[str, Any] = {
        "candidat_id": candidat["candidat_id"],
        "candidat_empreinte": candidat["empreinte"],
        "voie": "reference",
        "statut": "validee_par_reference" if accepte else "rejetee_ecart_reference",
        "ecart": formater(ecart),
        "tolerances_manquees": manquements,
        "politique": politique["empreinte"],
        "reference": {
            "reference_id": reference["reference_id"],
            "source": reference["source"],
            "valeur": formater(valeur_ref),
            "unite": reference["unite"],
            "mesure_par": reference["mesure_par"],
            "mesure_le": reference["mesure_le"],
            "incertitude_absolue": None if incertitude_ref is None else formater(incertitude_ref),
        },
        "valeur_retenue": candidat["valeur"] if accepte else None,
        "unite": candidat["unite"],
        "origine_valeur": "vision_validee_par_reference" if accepte else None,
        "incertitude_emploi": None,
        "utilisable_comme_mesure": accepte,
    }
    if accepte:
        bornes = []
        if politique["tolerance_absolue"] is not None:
            bornes.append(Decimal(politique["tolerance_absolue"]))
        if politique["tolerance_relative"] is not None:
            bornes.append(Decimal(politique["tolerance_relative"]) * valeur_ref)
        corps["incertitude_emploi"] = formater(min(bornes))
    return _finaliser(corps), None


def decider_par_humain(
    candidat: Mapping[str, Any],
    politique: Mapping[str, Any],
    validation: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Décision d'une personne (approuvée dans le sas) : ``valider``, ``refuser`` ou ``valider`` avec
    ``valeur_corrigee``."""
    refus = _precheck(candidat, politique)
    if refus is not None:
        return None, refus
    cle = {"valide_par", "valide_le", "approbation_ref", "decision"}
    if (
        not isinstance(validation, Mapping)
        or set(validation) - cle - {"valeur_corrigee"}
        or not cle <= set(validation)
        or validation["decision"] not in ("valider", "refuser")
        or not isinstance(validation["valide_par"], str)
        or not _IDENTIFIANT.fullmatch(validation["valide_par"])
        or not isinstance(validation["approbation_ref"], str)
        or not _IDENTIFIANT.fullmatch(validation["approbation_ref"])
        or not _instant(validation["valide_le"])
    ):
        return None, _refus(
            "REJ-VISION-DECISION-INVALIDE",
            "validation : valide_par, valide_le, approbation_ref et decision (valider|refuser) requis",
        )
    corrigee = None
    if validation.get("valeur_corrigee") is not None:
        corrigee = _dec(validation["valeur_corrigee"])
        if corrigee is None or corrigee <= 0 or validation["decision"] != "valider":
            return None, _refus(
                "REJ-VISION-DECISION-INVALIDE",
                "valeur_corrigee : texte décimal positif, avec la décision « valider » seulement",
            )
    valide = validation["decision"] == "valider"
    retenue = candidat["valeur"] if corrigee is None else formater(corrigee)
    corps: dict[str, Any] = {
        "candidat_id": candidat["candidat_id"],
        "candidat_empreinte": candidat["empreinte"],
        "voie": "humain",
        "statut": "validee_par_humain" if valide else "rejetee_par_humain",
        "politique": politique["empreinte"],
        "humain": {
            "valide_par": validation["valide_par"],
            "valide_le": validation["valide_le"],
            "approbation_ref": validation["approbation_ref"],
        },
        "valeur_retenue": retenue if valide else None,
        "unite": candidat["unite"],
        "origine_valeur": None
        if not valide
        else ("vision_validee_par_humain" if corrigee is None else "humain_corrige"),
        "incertitude_emploi": candidat["incertitude"]["absolue"] if valide and corrigee is None else None,
        "utilisable_comme_mesure": valide,
    }
    return _finaliser(corps), None

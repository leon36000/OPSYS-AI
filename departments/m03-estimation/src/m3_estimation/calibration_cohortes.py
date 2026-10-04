"""Évaluation pure, bornée et inactive de cohortes temps estimé/réel de M3.

Les entrées sont des observations déjà préparées par un futur adaptateur de provenance.
Ce module ne lit aucun registre, n'admet pas à lui seul un fait client et n'applique
jamais la candidate. Les WCT sont comparables uniquement si les preuves M3/M4 jointes
portent explicitement les sémantiques et unités exigées ci-dessous.

Tous les calculs décimaux publics s'exécutent dans un contexte local fixe de 64 chiffres,
arrondi ROUND_HALF_EVEN et pièges bornés. Une division rationnelle périodique (par exemple
ajustement/quantité pour le taux descriptif) est arrondie à cette précision de calcul; cela
ne décrit pas une précision équivalente des mesures terrain.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import (
    ROUND_HALF_EVEN,
    Clamped,
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    FloatOperation,
    Inexact,
    InvalidOperation,
    Overflow,
    Underflow,
    localcontext,
)
from statistics import median
from typing import Any

__all__ = ["construire_rapport"]

_MAX_OBSERVATIONS = 2000
_MAX_CHANTIERS = 500
_MAX_TEXTE = 128
_MAX_DECIMAL = Decimal("1000000000")
_MAX_DUREE = Decimal("1000000")
_MAX_SCALE = 6
_MIN_TOTAL = 30
_MIN_TRAIN = 20
_MIN_HOLDOUT = 10
_MIN_SEGMENT_TRAIN = 12
_MIN_SEGMENT_HOLDOUT = 8
_SEMANTIQUE = "duree_ecoulee_intervention"
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_DECIMAL_TEXTE = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?\Z")
_CLES_OBSERVATION = frozenset({
    "wct_id", "chantier_id", "intervention_id", "devis_id",
    "horodatage_debut", "horodatage_completion", "statut",
    "duree_estimee_minutes", "duree_reelle_minutes", "type_service",
    "quantite", "unite_quantite", "taux_minutes_par_unite", "bareme_version", "preuve",
})
_CLES_OPTIONNELLES_OBSERVATION = frozenset({
    "empreinte_bareme", "calibration_version_id", "taux_minutes_par_unite_source",
})
_CLES_PREUVE = frozenset({
    "m3_source_hash", "m4_wct_hash", "liaison_exacte", "chaine_m3_valide",
    "schema_trace", "semantique_trace", "semantique_reel",
    "unite_duree_estimee", "unite_duree_reelle",
})
_PRECISION_DECIMALE = 64
_TRAPS_DECIMAUX = (Clamped, DivisionByZero, FloatOperation, InvalidOperation, Overflow, Underflow)
_CONTEXTE_DECIMAL = Context(
    prec=_PRECISION_DECIMALE,
    rounding=ROUND_HALF_EVEN,
    Emin=-999,
    Emax=999,
)
for _signal in _CONTEXTE_DECIMAL.traps:
    _CONTEXTE_DECIMAL.traps[_signal] = _signal in _TRAPS_DECIMAUX


def _texte(valeur: Any, *, max_chars: int = _MAX_TEXTE) -> bool:
    return (
        isinstance(valeur, str)
        and 0 < len(valeur) <= max_chars
        and valeur == valeur.strip()
        and all(caractere.isprintable() for caractere in valeur)
    )


def _decimal_positif(valeur: Any, *, limite: Decimal, champ: str) -> tuple[Decimal | None, str | None]:
    if isinstance(valeur, (bool, float)):
        return None, f"{champ}_type_invalide"
    if isinstance(valeur, str):
        if len(valeur) > 64 or _DECIMAL_TEXTE.fullmatch(valeur) is None:
            return None, f"{champ}_format_invalide"
        try:
            nombre = Decimal(valeur)
        except InvalidOperation:
            return None, f"{champ}_format_invalide"
    elif isinstance(valeur, Decimal):
        nombre = valeur
    else:
        return None, f"{champ}_type_invalide"
    if not nombre.is_finite() or nombre <= 0 or nombre > limite:
        return None, f"{champ}_hors_bornes"
    if max(0, -nombre.as_tuple().exponent) > _MAX_SCALE or len(nombre.as_tuple().digits) > 16:
        return None, f"{champ}_precision_invalide"
    return nombre.normalize(), None


def _minutes_reelles(valeur: Any) -> tuple[int | None, str | None]:
    if type(valeur) is not int:
        return None, "duree_reelle_type_invalide"
    if valeur <= 0 or valeur > int(_MAX_DUREE):
        return None, "duree_reelle_hors_bornes"
    return valeur, None


def _utc(valeur: Any, champ: str) -> tuple[datetime | None, str | None]:
    if not isinstance(valeur, str) or len(valeur) > 40:
        return None, f"{champ}_invalide"
    try:
        texte = valeur[:-1] + "+00:00" if valeur.endswith("Z") else valeur
        instant = datetime.fromisoformat(texte)
    except ValueError:
        return None, f"{champ}_invalide"
    if instant.tzinfo is None or instant.utcoffset() != timedelta(0):
        return None, f"{champ}_utc_requis"
    return instant.astimezone(UTC), None


def _date_iso(instant: datetime) -> str:
    return instant.isoformat().replace("+00:00", "Z")


def _normaliser_observation(source: Any) -> tuple[dict[str, Any] | None, list[str]]:
    raisons: list[str] = []
    if not isinstance(source, dict):
        return None, ["observation_forme_invalide"]
    if not set(source) >= _CLES_OBSERVATION or set(source) - _CLES_OBSERVATION - _CLES_OPTIONNELLES_OBSERVATION:
        raisons.append("cles_observation_incompletes_ou_inattendues")
    preuve = source.get("preuve")
    if not isinstance(preuve, dict) or set(preuve) != _CLES_PREUVE:
        raisons.append("preuve_forme_invalide")
        preuve = {}

    for champ in (
        "wct_id", "chantier_id", "intervention_id", "devis_id", "type_service",
        "unite_quantite", "bareme_version",
    ):
        if not _texte(source.get(champ)):
            raisons.append(f"{champ}_invalide")
    if source.get("statut") != "completed_verified":
        raisons.append("statut_non_verifie")

    debut, raison = _utc(source.get("horodatage_debut"), "horodatage_debut")
    if raison:
        raisons.append(raison)
    fin, raison = _utc(source.get("horodatage_completion"), "horodatage_completion")
    if raison:
        raisons.append(raison)
    if debut is not None and fin is not None and fin < debut:
        raisons.append("chronologie_invalide")

    estime, raison = _decimal_positif(source.get("duree_estimee_minutes"), limite=_MAX_DUREE, champ="duree_estimee")
    if raison:
        raisons.append(raison)
    reel, raison = _minutes_reelles(source.get("duree_reelle_minutes"))
    if raison:
        raisons.append(raison)
    quantite, raison = _decimal_positif(source.get("quantite"), limite=_MAX_DECIMAL, champ="quantite")
    if raison:
        raisons.append(raison)
    taux, raison = _decimal_positif(
        source.get("taux_minutes_par_unite"), limite=_MAX_DUREE, champ="taux_minutes_par_unite"
    )
    if raison:
        raisons.append(raison)
    if estime is not None and quantite is not None and taux is not None and estime != quantite * taux:
        raisons.append("duree_estimee_non_concordante_quantite_taux")

    for cle_hash in ("m3_source_hash", "m4_wct_hash"):
        if not isinstance(preuve.get(cle_hash), str) or _HASH.fullmatch(preuve[cle_hash]) is None:
            raisons.append(f"{cle_hash}_invalide")
    calibration_id = source.get("calibration_version_id")
    if calibration_id is not None and (
        not isinstance(calibration_id, str) or _HASH.fullmatch(calibration_id) is None
    ):
        raisons.append("calibration_version_id_invalide")
    taux_source: Decimal | None = None
    if source.get("taux_minutes_par_unite_source") is not None:
        taux_source, raison = _decimal_positif(
            source["taux_minutes_par_unite_source"], limite=_MAX_DUREE, champ="taux_minutes_par_unite_source"
        )
        if raison:
            raisons.append(raison)
    if type(preuve.get("liaison_exacte")) is not bool or not preuve.get("liaison_exacte"):
        raisons.append("liaison_exacte_non_prouvee")
    if type(preuve.get("chaine_m3_valide")) is not bool or not preuve.get("chaine_m3_valide"):
        raisons.append("chaine_m3_non_valide")
    if type(preuve.get("schema_trace")) is not int or preuve.get("schema_trace") not in (2, 3):
        raisons.append("schema_trace_non_qualifie")
    if preuve.get("schema_trace") == 3 and (calibration_id is None or taux_source is None):
        raisons.append("schema3_provenance_calibration_absente")
    if preuve.get("schema_trace") == 2 and calibration_id is not None:
        raisons.append("schema2_calibration_inattendue")
    if preuve.get("semantique_trace") != _SEMANTIQUE:
        raisons.append("semantique_trace_non_qualifiee")
    if preuve.get("semantique_reel") != _SEMANTIQUE:
        raisons.append("semantique_reel_non_qualifiee")
    if preuve.get("unite_duree_estimee") != "minute" or preuve.get("unite_duree_reelle") != "minute":
        raisons.append("unite_duree_non_qualifiee")

    if raisons:
        return None, sorted(set(raisons))
    if debut is None or fin is None or estime is None or reel is None or quantite is None or taux is None:
        return None, ["observation_interne_incomplete"]
    return {
        "wct_id": source["wct_id"],
        "chantier_id": source["chantier_id"],
        "intervention_id": source["intervention_id"],
        "devis_id": source["devis_id"],
        "debut": debut,
        "fin": fin,
        "estime": estime,
        "reel": Decimal(reel),
        "erreur": Decimal(reel) - estime,
        "type_service": source["type_service"],
        "quantite": quantite,
        "unite_quantite": source["unite_quantite"],
        "taux": taux,
        "taux_source": source.get("taux_minutes_par_unite_source"),
        "bareme_version": source["bareme_version"],
        "empreinte_bareme": source.get("empreinte_bareme"),
        "calibration_version_id": source.get("calibration_version_id"),
        "m3_source_hash": preuve["m3_source_hash"],
        "m4_wct_hash": preuve["m4_wct_hash"],
    }, []


def _canonique(observation: dict[str, Any]) -> str:
    normalisee = {
        cle: format(valeur, "f") if isinstance(valeur, Decimal)
        else _date_iso(valeur) if isinstance(valeur, datetime)
        else valeur
        for cle, valeur in observation.items()
    }
    return json.dumps(normalisee, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _id_exclusion(source: Any) -> str | None:
    if not isinstance(source, dict):
        return None
    valeur = source.get("wct_id")
    return valeur if _texte(valeur) else None


def _quantile_nearest_rank(valeurs: list[Decimal], pourcentage: int) -> Decimal:
    tries = sorted(valeurs)
    indice = (len(tries) * pourcentage + 99) // 100 - 1
    return tries[max(0, indice)]


def _observations_train_preregistre(
    observations: list[Any] | tuple[Any, ...], coupure: datetime,
) -> tuple[list[Any], str | None]:
    """Réduit le calcul préinscrit aux seuls WCT des chantiers entièrement terminés avant la coupure.

    Les faits futurs ne fournissent ni métriques, ni exclusions, ni compteurs au rapport candidat.
    Ils ne servent qu'à reconnaître un chantier traversant et à détecter une contradiction d'un
    WCT retenu dans le train.
    """
    valides: list[tuple[Any, dict[str, Any]]] = []
    par_chantier: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for brut in observations:
        ligne, _ = _normaliser_observation(brut)
        if ligne is not None:
            valides.append((brut, ligne))
            par_chantier[ligne["chantier_id"]].append(ligne)
    chantiers_train = {
        chantier for chantier, lignes in par_chantier.items()
        if max(ligne["fin"] for ligne in lignes) <= coupure
    }
    identites_train = {
        ligne["wct_id"] for _, ligne in valides if ligne["chantier_id"] in chantiers_train
    }
    par_wct: dict[str, str] = {}
    retenues: list[Any] = []
    for brut in observations:
        wct_id = _id_exclusion(brut)
        if wct_id not in identites_train:
            continue
        ligne, raisons = _normaliser_observation(brut)
        if ligne is None:
            return [], "wct_train_contradiction_connu"
        canon = _canonique(ligne)
        precedent = par_wct.get(wct_id)
        if precedent is not None and precedent != canon:
            return [], "wct_train_contradiction_connu"
        par_wct[wct_id] = canon
        retenues.append(brut)
    return retenues, None


def _stats(lignes: list[dict[str, Any]]) -> dict[str, Any]:
    erreurs = [ligne["erreur"] for ligne in lignes]
    absolues = [abs(valeur) for valeur in erreurs]
    centre = median(erreurs)
    deviations = [abs(valeur - centre) for valeur in erreurs]
    return {
        "chantiers": len({ligne["chantier_id"] for ligne in lignes}),
        "observations": len(lignes),
        "duree_estimee_minutes_mediane": format(median([ligne["estime"] for ligne in lignes]), "f"),
        "duree_reelle_minutes_mediane": format(median([ligne["reel"] for ligne in lignes]), "f"),
        "erreur_signee_minutes_mediane": format(centre, "f"),
        "erreur_absolue_minutes_mediane": format(median(absolues), "f"),
        "erreur_absolue_minutes_p80": format(_quantile_nearest_rank(absolues, 80), "f"),
        "mad_erreur_minutes": format(median(deviations), "f"),
        "erreur_minutes_p50": format(_quantile_nearest_rank(erreurs, 50), "f"),
        "erreur_minutes_p80": format(_quantile_nearest_rank(erreurs, 80), "f"),
        "quantite_min": format(min(ligne["quantite"] for ligne in lignes), "f"),
        "quantite_max": format(max(ligne["quantite"] for ligne in lignes), "f"),
    }


def _cle_segment(ligne: dict[str, Any]) -> tuple[str, str, str, str, str, str | None, str | None]:
    return (
        ligne["type_service"], ligne["unite_quantite"], ligne["bareme_version"],
        format(ligne["quantite"], "f"), format(ligne["taux"], "f"), ligne.get("empreinte_bareme"),
        ligne.get("calibration_version_id"),
    )


def _construire_rapport(
    observations: Any,
    *,
    coupure_utc: str,
    protocole_version: str,
    contexte_decimal: Context,
    train_only: bool = False,
) -> dict[str, Any]:
    """Construit un rapport pur avec split par chantier et candidate inactive.

    Les observations doivent être déjà préparées par un futur adaptateur de provenance;
    cette fonction ne prouve ni accès registre ni admission réelle des faits.
    Chaque entrée contient les identifiants WCT/chantier/intervention/devis, dates UTC de
    début/fin, statut vérifié, durée réelle en int et estimée en Decimal/texte, service,
    quantité/unité/taux de minutes par unité/version du barème. La durée estimée doit
    égaler quantité × taux. Un bloc ``preuve`` strict porte les hashes source M3/M4,
    jointure exacte, chaîne M3 valide, schema 2, sémantiques qualifiées et unités minute.
    Ces preuves sont des attestations du futur adaptateur; leur forme ne prouve pas leur
    authenticité à cette couche pure. La coupure UTC et la version de protocole sont
    obligatoires et aucune horloge n'est lue.
    """
    coupure, erreur_coupure = _utc(coupure_utc, "coupure_utc")
    if erreur_coupure or not _texte(protocole_version, max_chars=32):
        return {"statut": "refuse", "raisons": [erreur_coupure or "protocole_version_invalide"]}
    if not isinstance(observations, (list, tuple)):
        return {"statut": "refuse", "raisons": ["observations_sequence_requise"]}
    if len(observations) > _MAX_OBSERVATIONS:
        return {"statut": "refuse", "raisons": ["limite_observations_depassee"], "limite": _MAX_OBSERVATIONS}
    if coupure is None:
        return {"statut": "refuse", "raisons": ["coupure_utc_invalide"]}
    if train_only:
        observations, erreur_train = _observations_train_preregistre(observations, coupure)
        if erreur_train:
            return {"statut": "refuse", "raisons": [erreur_train], "candidate_active": False}

    exclusions: list[dict[str, Any]] = []
    par_wct: dict[str, dict[str, Any]] = {}
    identites_vues: dict[str, dict[str, Any] | None] = {}
    rejeux = 0
    conflits: set[str] = set()
    for source in observations:
        normalisee, raisons = _normaliser_observation(source)
        if normalisee is None:
            identite = _id_exclusion(source)
            exclusions.append({"wct_id": identite, "raisons": raisons})
            if identite is not None:
                if identite in identites_vues:
                    conflits.add(identite)
                    par_wct.pop(identite, None)
                else:
                    identites_vues[identite] = None
            continue
        wct_id = normalisee["wct_id"]
        if wct_id in identites_vues:
            precedente = identites_vues[wct_id]
            if precedente is not None and _canonique(precedente) == _canonique(normalisee):
                rejeux += 1
            else:
                conflits.add(wct_id)
                par_wct.pop(wct_id, None)
            continue
        identites_vues[wct_id] = normalisee
        par_wct[wct_id] = normalisee

    for wct_id in sorted(conflits):
        par_wct.pop(wct_id, None)
        exclusions.append({"wct_id": wct_id, "raisons": ["conflit_rejeu"]})

    par_chantier: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for ligne in par_wct.values():
        par_chantier[ligne["chantier_id"]].append(ligne)
    if len(par_chantier) > _MAX_CHANTIERS:
        return {"statut": "refuse", "raisons": ["limite_chantiers_depassee"], "limite": _MAX_CHANTIERS}

    train: list[dict[str, Any]] = []
    holdout: list[dict[str, Any]] = []
    traversants = 0
    for _chantier_id, lignes in sorted(par_chantier.items()):
        debut_chantier = min(ligne["debut"] for ligne in lignes)
        fin_chantier = max(ligne["fin"] for ligne in lignes)
        if debut_chantier <= coupure < fin_chantier:
            traversants += 1
            exclusions.extend(
                {"wct_id": ligne["wct_id"], "raisons": ["chantier_chevauche_coupure"]}
                for ligne in lignes
            )
        elif fin_chantier <= coupure:
            train.extend(lignes)
        elif debut_chantier > coupure:
            holdout.extend(lignes)
        else:
            traversants += 1
            exclusions.extend(
                {"wct_id": ligne["wct_id"], "raisons": ["chantier_non_classable_coupure"]}
                for ligne in lignes
            )

    train.sort(key=lambda ligne: (ligne["fin"], ligne["wct_id"]))
    holdout.sort(key=lambda ligne: (ligne["debut"], ligne["wct_id"]))
    train_chantiers = {ligne["chantier_id"] for ligne in train}
    holdout_chantiers = {ligne["chantier_id"] for ligne in holdout}
    if not train_chantiers.isdisjoint(holdout_chantiers):
        return {"statut": "refuse", "raisons": ["chantier_fuite_coupure"]}

    par_segment_train: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    par_segment_holdout: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for ligne in train:
        par_segment_train[_cle_segment(ligne)].append(ligne)
    for ligne in holdout:
        par_segment_holdout[_cle_segment(ligne)].append(ligne)

    compteurs = {
        "observations_recues": len(observations),
        "observations_distinctes_valides": len(par_wct),
        "rejeux_identiques": rejeux,
        "conflits_rejeu": len(conflits),
        "exclues": len(exclusions),
        "chantiers_train": len(train_chantiers),
        "chantiers_holdout": len(holdout_chantiers),
        "chantiers_chevauchant_coupure": traversants,
        "observations_train": len(train),
        "observations_holdout": len(holdout),
    }
    partitions = {ligne["wct_id"]: "train" for ligne in train}
    partitions.update({ligne["wct_id"]: "holdout" for ligne in holdout})
    contenu: dict[str, Any] = {
        "protocole_version": protocole_version,
        "coupure_utc": _date_iso(coupure),
        "unite_duree": "minute",
        "semantique_duree": _SEMANTIQUE,
        "compteurs": compteurs,
        "exclusions": sorted(exclusions, key=lambda item: (str(item.get("wct_id") or ""), item["raisons"][0])),
        "segments": [],
        "provenance_observations": [
            {
                "wct_id": ligne["wct_id"],
                "chantier_sha256": hashlib.sha256(ligne["chantier_id"].encode("utf-8")).hexdigest(),
                "m3_source_hash": ligne["m3_source_hash"],
                "m4_wct_hash": ligne["m4_wct_hash"],
                "partition": partitions[ligne["wct_id"]],
            }
            for ligne in sorted(train + holdout, key=lambda item: item["wct_id"])
        ],
        "candidate_active": False,
    }
    minimum_global = compteurs["chantiers_train"] >= _MIN_TRAIN if train_only else (
        (len(train) + len(holdout)) >= _MIN_TOTAL
        and compteurs["chantiers_train"] >= _MIN_TRAIN
        and compteurs["chantiers_holdout"] >= _MIN_HOLDOUT
    )
    if not minimum_global or conflits:
        contenu["statut"] = "insuffisant" if not conflits else "refuse"
        if conflits:
            contenu["raisons"] = ["conflit_rejeu"]
        else:
            contenu["raisons"] = ["minimum_global_non_atteint"]
    else:
        for cle in sorted(set(par_segment_train) | set(par_segment_holdout)):
            lignes_train = par_segment_train.get(cle, [])
            lignes_holdout = par_segment_holdout.get(cle, [])
            n_train = len({ligne["chantier_id"] for ligne in lignes_train})
            n_holdout = len({ligne["chantier_id"] for ligne in lignes_holdout})
            admissible = n_train >= _MIN_SEGMENT_TRAIN and (train_only or n_holdout >= _MIN_SEGMENT_HOLDOUT)
            ajustement = median([ligne["erreur"] for ligne in lignes_train]) if admissible else None
            division_taux_non_exacte = False
            if admissible:
                contexte_decimal.flags[Inexact] = False
                increment_taux = ajustement / lignes_train[0]["quantite"]
                division_taux_non_exacte = contexte_decimal.flags[Inexact]
                taux_candidat = lignes_train[0]["taux"] + increment_taux
            else:
                taux_candidat = None
            holdout_corrige = [
                {**ligne, "estime": ligne["estime"] + ajustement, "erreur": ligne["erreur"] - ajustement}
                for ligne in lignes_holdout
            ] if admissible and not train_only else []
            durees_corrigees_valides = all(ligne["estime"] > 0 for ligne in holdout_corrige)
            admissible = admissible and durees_corrigees_valides and taux_candidat is not None and taux_candidat > 0
            if n_train >= _MIN_SEGMENT_TRAIN and (train_only or n_holdout >= _MIN_SEGMENT_HOLDOUT):
                raisons_segment = (
                    [] if admissible else
                    ["taux_candidat_non_positif"] if taux_candidat is not None and taux_candidat <= 0 else
                    ["ajustement_duree_non_positive_holdout"]
                )
            else:
                raisons_segment = ["minimum_segment_non_atteint"]
            segment = {
                "type_service": cle[0],
                "unite_quantite": cle[1],
                "bareme_version": cle[2],
                "quantite_exacte": cle[3],
                "taux_minutes_par_unite_source": cle[4],
                "empreinte_bareme": cle[5],
                "calibration_version_id": cle[6],
                "division_taux_non_exacte": division_taux_non_exacte if admissible else None,
                "statut": "candidate" if admissible else "insuffisant",
                "raisons": raisons_segment,
                "train": _stats(lignes_train) if lignes_train else None,
                "holdout_reference": _stats(lignes_holdout) if lignes_holdout else None,
                "holdout_apres_candidate": _stats(holdout_corrige) if admissible and not train_only else None,
                "ajustement_descriptif_train_minutes": format(ajustement, "f") if admissible else None,
                "taux_minutes_par_unite_candidat": format(taux_candidat, "f") if admissible else None,
                "candidate_active": False,
            }
            contenu["segments"].append(segment)
        contient_candidate = any(segment["statut"] == "candidate" for segment in contenu["segments"])
        contenu["statut"] = "candidate" if contient_candidate else "insuffisant"
        if contenu["statut"] == "insuffisant":
            contenu["raisons"] = ["minimum_segment_non_atteint"]

    contenu["arithmetique_decimal"] = {
        "precision_significative": _PRECISION_DECIMALE,
        "arrondi": "ROUND_HALF_EVEN",
        "exposant_min": -999,
        "exposant_max": 999,
        "pieges_actifs": [signal.__name__ for signal in _TRAPS_DECIMAUX],
        "divisions_taux_non_exactes": any(
            segment["division_taux_non_exacte"] for segment in contenu["segments"]
            if segment["division_taux_non_exacte"] is not None
        ),
        "note": (
            "Une division non exacte est arrondie au contexte Decimal fixé; cette précision de calcul "
            "ne représente pas la précision terrain."
        ),
    }
    serialise = json.dumps(contenu, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return {**contenu, "rapport_sha256": hashlib.sha256(serialise.encode("utf-8")).hexdigest()}


def construire_rapport(
    observations: Any,
    *,
    coupure_utc: str,
    protocole_version: str,
    train_only: bool = False,
) -> dict[str, Any]:
    """Construit un rapport sous un contexte Decimal borné et indépendant de l'appelant."""
    try:
        with localcontext(_CONTEXTE_DECIMAL) as contexte:
            contexte.clear_flags()
            return _construire_rapport(
                observations,
                coupure_utc=coupure_utc,
                protocole_version=protocole_version,
                contexte_decimal=contexte,
                train_only=train_only,
            )
    except DecimalException:
        return {
            "statut": "refuse",
            "raisons": ["calcul_decimal_invalide"],
            "arithmetique_decimal": {
                "precision_significative": _PRECISION_DECIMALE,
                "arrondi": "ROUND_HALF_EVEN",
                "exposant_min": -999,
                "exposant_max": 999,
                "pieges_actifs": [signal.__name__ for signal in _TRAPS_DECIMAUX],
            },
        }

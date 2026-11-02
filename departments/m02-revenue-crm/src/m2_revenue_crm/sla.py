"""Moteur SLA du filet anti-perte (M2-C1 ; DEFINITION-PRODUIT §7 M2.13 « SLA et prévention de perte de leads »).

Module PUR : aucune entrée-sortie, aucune horloge, aucun aléa. L'instant de référence (`maintenant`), les réglages et
tous
les faits viennent de l'appelant (`filet.py` pour l'assemblage, `outils_integrite.py` pour les registres). Une même
entrée
donne toujours la même sortie. Le moteur ne LIT que : il n'écrit rien, n'envoie rien, ne change aucun statut.

SEPT RÈGLES, déclaratives, dans l'ordre de M2.13 :
  1. `prochaine_action_obligatoire` : tout lead ouvert a une prochaine action ;
  2. `lead_chaud_non_contacte` : un lead chaud (urgence déclarée) reçoit un contact humain vite ;
  3. `photos_non_recues` : un lead qualifié a des photos liées à son profil de propriété dans le délai ;
  4. `soumission_non_relancee` : un devis périmé est relancé dans le délai ;
  5. `plainte_non_escaladee` : un client insatisfait est pris en charge par une personne dans le délai ;
  6. `lead_sans_proprietaire` : un lead a un propriétaire ;
  7. `tache_en_retard` : la prochaine action échue est faite (ou remplacée) dans la tolérance.

LES SEUILS SONT DÉCLARÉS PAR LE PROPRIÉTAIRE, JAMAIS INVENTÉS. Chaque règle à délai lit sa clé de `configuration.sla` de
`department.yaml` (entier d'heures, au moins 1) ; la règle 4 lit aussi `jours_soumission_perimee` de
`configuration.segments`. Une clé absente ou invalide rend la règle « non évaluée » et dit exactement quoi déclarer
(fail-closed) : un rapport sans violation ne se lit alors jamais « tout va bien ». Les règles 1 et 6 ont une partie sans
délai (un lead qui n'est plus `nouveau` et n'a ni action ni propriétaire est une incohérence immédiate) : elle est
évaluée même sans réglage, et la règle est alors « partielle ».

FRONTIÈRES. Un délai est dépassé quand il est STRICTEMENT dépassé (`maintenant - départ > délai`) : pile à la limite, le
SLA est tenu. `depuis` est l'instant où la violation a commencé (départ + délai) et `ecoule_heures` le temps écoulé
depuis cet instant (0 pendant la première heure de violation). Aucune règle ne regarde le contact, le
nom ou le texte d'une note : seulement des instants, des statuts, des identifiants et des compteurs.

CE QUE LE MOTEUR NE SAIT PAS (dit, pas caché) : M2 n'a pas d'entité « tâche » ni d'accusé d'envoi. « Contacté » et
« escaladé » se lisent à la note qu'une PERSONNE écrit au dossier (`m2_enregistrer_interaction`) ; « tâche en retard »
est la
prochaine action échue sans activité humaine depuis son échéance ; « photos demandées » se lit à l'arrivée des photos
dans
le profil de propriété confirmé (M2 ne sait pas si la demande a été faite, seulement si les photos sont là).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any

from . import segments, statuts

__all__ = [
    "CHEMIN_SLA",
    "CLES_SLA",
    "ETAT_EVALUEE",
    "ETAT_NON_EVALUEE",
    "ETAT_PARTIELLE",
    "ORDRE_REGLES",
    "REGLES",
    "evaluer",
    "lire_reglages",
]

CHEMIN_SLA = "configuration.sla"
ETAT_EVALUEE = "evaluee"
ETAT_PARTIELLE = "partielle"
ETAT_NON_EVALUEE = "non_evaluee"

R_ACTION = "prochaine_action_obligatoire"
R_CHAUD = "lead_chaud_non_contacte"
R_PHOTOS = "photos_non_recues"
R_SOUMISSION = "soumission_non_relancee"
R_PLAINTE = "plainte_non_escaladee"
R_PROPRIETAIRE = "lead_sans_proprietaire"
R_RETARD = "tache_en_retard"
ORDRE_REGLES = (R_ACTION, R_CHAUD, R_PHOTOS, R_SOUMISSION, R_PLAINTE, R_PROPRIETAIRE, R_RETARD)

# Les clés déclarées par le propriétaire (`configuration.sla`) : un entier d'HEURES, au moins 1.
CLE_ASSIGNATION = "heures_assignation"
CLE_PREMIERE_ACTION = "heures_premiere_action"
CLE_LEAD_CHAUD = "heures_lead_chaud"
CLE_PHOTOS = "heures_demande_photos"
CLE_RELANCE_SOUMISSION = "heures_relance_soumission"
CLE_ESCALADE_PLAINTE = "heures_escalade_plainte"
CLE_TOLERANCE_RETARD = "heures_retard_tolerance"
CLES_SLA = (
    CLE_PREMIERE_ACTION,
    CLE_LEAD_CHAUD,
    CLE_PHOTOS,
    CLE_RELANCE_SOUMISSION,
    CLE_ESCALADE_PLAINTE,
    CLE_ASSIGNATION,
    CLE_TOLERANCE_RETARD,
)
# Une clé de `configuration.segments`, lue par la règle 4 en plus de sa clé d'heures.
CLE_JOURS_PERIMEE = segments.CLE_JOURS_PERIMEE

# Ce que chaque clé décide, en mots du propriétaire (pour dire quoi déclarer).
_SENS_DES_CLES = {
    CLE_PREMIERE_ACTION: "le nombre d'heures permises à un lead NOUVEAU avant d'avoir une prochaine action",
    CLE_LEAD_CHAUD: "le nombre d'heures permises à un lead chaud (urgence déclarée) avant un premier contact humain",
    CLE_PHOTOS: "le nombre d'heures permises à un lead qualifié avant que des photos soient liées à son profil",
    CLE_RELANCE_SOUMISSION: "le nombre d'heures permises après l'échéance d'un devis périmé avant sa relance",
    CLE_ESCALADE_PLAINTE: "le nombre d'heures permises à un client insatisfait avant la prise en charge par une "
    "personne",
    CLE_ASSIGNATION: "le nombre d'heures permises à un lead NOUVEAU avant d'avoir un propriétaire",
    CLE_TOLERANCE_RETARD: "le nombre d'heures de tolérance après l'échéance d'une prochaine action",
}

REGLES = {
    R_ACTION: (
        "Tout lead ouvert a une prochaine action. Un lead nouveau l'a dans le délai heures_premiere_action ; un lead "
        "qualifié ou plus avancé sans prochaine action est une incohérence immédiate (sans délai)."
    ),
    R_CHAUD: (
        "Un lead chaud (urgence déclarée à l'ingestion, nouveau ou qualifié) reçoit un contact humain (une note d'une "
        "personne au dossier) dans le délai heures_lead_chaud après son ingestion."
    ),
    R_PHOTOS: (
        "Un lead qualifié a au moins une photo liée au profil de propriété confirmé de son client dans le délai "
        "heures_demande_photos après sa qualification (M2 ne sait pas si la demande a été faite : il voit si les "
        "photos sont arrivées)."
    ),
    R_SOUMISSION: (
        "Un devis envoyé périmé (jours_soumission_perimee, configuration.segments) est relancé — relance préparée ou "
        "note d'une personne au dossier — dans le délai heures_relance_soumission après son échéance."
    ),
    R_PLAINTE: (
        "Un client qui a dit ne pas être satisfait à la fin d'un chantier (client_satisfait de m4.travaux_termines) "
        "est "
        "pris en charge par une personne (une note au dossier) dans le délai heures_escalade_plainte."
    ),
    R_PROPRIETAIRE: (
        "Tout lead ouvert a un propriétaire. Un lead nouveau l'a dans le délai heures_assignation ; un lead qualifié "
        "ou "
        "plus avancé sans propriétaire est une incohérence immédiate (sans délai)."
    ),
    R_RETARD: (
        "La prochaine action d'un lead ouvert est faite ou remplacée dans la tolérance heures_retard_tolerance après "
        "son échéance : sans activité humaine postérieure à l'échéance, l'action est en retard."
    ),
}

# Les clés dont chaque règle a besoin pour être évaluée en entier.
_CLES_DE_REGLE = {
    R_ACTION: (CLE_PREMIERE_ACTION,),
    R_CHAUD: (CLE_LEAD_CHAUD,),
    R_PHOTOS: (CLE_PHOTOS,),
    R_SOUMISSION: (CLE_RELANCE_SOUMISSION, CLE_JOURS_PERIMEE),
    R_PLAINTE: (CLE_ESCALADE_PLAINTE,),
    R_PROPRIETAIRE: (CLE_ASSIGNATION,),
    R_RETARD: (CLE_TOLERANCE_RETARD,),
}
# Les règles qui gardent une partie sans délai (incohérence immédiate d'un lead avancé).
_REGLES_A_PARTIE_STRUCTURELLE = (R_ACTION, R_PROPRIETAIRE)
# Les sources de faits dont chaque règle dépend (illisible : règle non évaluée).
_SOURCES_DE_REGLE = {R_PHOTOS: "photos", R_SOUMISSION: "devis", R_PLAINTE: "satisfaction"}
_MANQUE_SOURCE = {
    "photos": "la lecture des profils de propriété confirmés (registre profils_propriete)",
    "devis": "la lecture des devis et des relances préparées (registres devis_envoyes_recus, relances_devis_recues, "
    "relances_preparees)",
    "satisfaction": "la lecture de la satisfaction du client reçue de M4 (registre satisfactions_recues)",
}

_STATUTS_OUVERTS = tuple(s for s in statuts.STATUTS if s not in statuts.STATUTS_TERMINAUX)
_STATUT_NOUVEAU = "nouveau"
_STATUT_QUALIFIE = "qualifie"
_SECONDES_PAR_HEURE = 3600


# ---------------------------------------------------------------------------------------------------------
# Réglages : déclarés, jamais devinés
# ---------------------------------------------------------------------------------------------------------
def _heures_valides(valeur: Any) -> bool:
    """Un nombre entier d'heures, au moins 1. Un booléen n'est pas un nombre d'heures."""
    return isinstance(valeur, int) and not isinstance(valeur, bool) and valeur >= 1


def lire_reglages(brut_sla: Any, seuils_segments: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """`{clé: {"etat", "valeur"}}` des sept clés de `configuration.sla` et de `jours_soumission_perimee` (déjà lue par
    `segments.lire_seuils`). `etat` : `ok` (`valeur` la porte), `a_configurer` (clé absente ou nulle : le bloc est vide
    à
    dessein) ou `invalide` (tout le reste, dont un bloc qui n'est pas un dictionnaire). `valeur` est `None` hors `ok` :
    jamais un défaut. Une clé inconnue est ignorée."""
    bloc_illisible = brut_sla is not None and not isinstance(brut_sla, dict)
    reglages: dict[str, dict[str, Any]] = {}
    for cle in CLES_SLA:
        valeur = brut_sla.get(cle) if isinstance(brut_sla, dict) else None
        if bloc_illisible:
            etat = segments.ETAT_SEUIL_INVALIDE
        elif valeur is None:
            etat = segments.ETAT_SEUIL_A_CONFIGURER
        elif _heures_valides(valeur):
            etat = segments.ETAT_SEUIL_OK
        else:
            etat = segments.ETAT_SEUIL_INVALIDE
        reglages[cle] = {"etat": etat, "valeur": valeur if etat == segments.ETAT_SEUIL_OK else None}
    reglages[CLE_JOURS_PERIMEE] = dict(
        seuils_segments.get(CLE_JOURS_PERIMEE, {"etat": segments.ETAT_SEUIL_A_CONFIGURER, "valeur": None})
    )
    return reglages


def _manque_de_cle(cle: str, reglages: Mapping[str, Mapping[str, Any]]) -> str | None:
    """Ce qu'il faut déclarer pour la clé `cle`, ou `None` si elle est valide."""
    etat = reglages.get(cle, {}).get("etat", segments.ETAT_SEUIL_A_CONFIGURER)
    if etat == segments.ETAT_SEUIL_OK:
        return None
    chemin = segments.CHEMIN_SEUILS if cle == CLE_JOURS_PERIMEE else CHEMIN_SLA
    unite = "jours" if cle == CLE_JOURS_PERIMEE else "heures"
    sens = (
        "le nombre de jours après lequel un devis envoyé est périmé"
        if cle == CLE_JOURS_PERIMEE
        else _SENS_DES_CLES[cle]
    )
    if etat == segments.ETAT_SEUIL_INVALIDE:
        return f"{cle} invalide ({chemin} de department.yaml) : un entier d'{unite} supérieur ou égal à 1 est attendu"
    return (
        f"déclarer {cle} ({chemin} de department.yaml, entier d'{unite} ≥ 1) : {sens}. Aucune valeur n'est supposée : "
        "c'est une décision du propriétaire"
    )


def _etat_des_regles(
    reglages: Mapping[str, Mapping[str, Any]], sources: Mapping[str, bool]
) -> dict[str, dict[str, Any]]:
    """Pour chaque règle : son état (évaluée, partielle, non évaluée) et ce qui manque pour l'évaluer en entier."""
    etats: dict[str, dict[str, Any]] = {}
    for regle in ORDRE_REGLES:
        manques = [m for cle in _CLES_DE_REGLE[regle] if (m := _manque_de_cle(cle, reglages)) is not None]
        source = _SOURCES_DE_REGLE.get(regle)
        source_absente = source is not None and not sources.get(source, False)
        if source_absente:
            manques.append(f"la règle ne peut pas être évaluée sans {_MANQUE_SOURCE[source]}")
        if not manques:
            etat = ETAT_EVALUEE
        elif regle in _REGLES_A_PARTIE_STRUCTURELLE and not source_absente:
            etat = ETAT_PARTIELLE
        else:
            etat = ETAT_NON_EVALUEE
        etats[regle] = {"etat": etat, "manque": " ; ".join(manques) if manques else None}
    return etats


# ---------------------------------------------------------------------------------------------------------
# Instants
# ---------------------------------------------------------------------------------------------------------
def _instant(valeur: Any) -> datetime | None:
    """L'instant UTC d'un horodatage lisible, ou `None` (illisible, naïf ou absent : jamais le fuseau de la machine)."""
    try:
        return segments.instant_utc(valeur)
    except (ValueError, TypeError):
        return None


def _heures_ecoulees(depart: datetime, maintenant: datetime) -> int:
    return int((maintenant - depart).total_seconds() // _SECONDES_PAR_HEURE)


def _depasse(depart: datetime, delai_heures: int, maintenant: datetime) -> bool:
    """Vrai quand le délai est STRICTEMENT dépassé : pile à la limite, le SLA est tenu."""
    return (maintenant - depart) > timedelta(hours=delai_heures)


def _apres(instants: Iterable[Any], borne: datetime, *, strict: bool) -> bool:
    """Vrai si l'un des horodatages est après `borne` (ou à `borne` quand `strict` est faux)."""
    for texte in instants:
        instant = _instant(texte)
        if instant is not None and (instant > borne if strict else instant >= borne):
            return True
    return False


def _violation(
    regle: str,
    dossier: Mapping[str, Any],
    depuis: datetime | None,
    maintenant: datetime,
    *,
    raison: str,
    seuil: Mapping[str, Any] | None,
    donnee: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "regle": regle,
        "lead_id": dossier["lead_id"],
        "statut": dossier["statut"],
        "proprietaire": dossier.get("proprietaire"),
        "depuis": depuis.isoformat() if depuis is not None else None,
        "ecoule_heures": _heures_ecoulees(depuis, maintenant) if depuis is not None else None,
        "seuil": dict(seuil) if seuil is not None else None,
        "raison": raison,
        "donnee": dict(donnee),
    }


def _seuil(cle: str, reglages: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    return {"cle": cle, "valeur": reglages[cle]["valeur"]}


# ---------------------------------------------------------------------------------------------------------
# Les règles : une fonction par règle, un lead à la fois
# ---------------------------------------------------------------------------------------------------------
def _regle_action(d: Mapping[str, Any], rg: Mapping[str, Any], maintenant: datetime) -> list[dict[str, Any]]:
    if d["statut"] not in _STATUTS_OUVERTS or d.get("prochaine_action") is not None:
        return []
    if d["statut"] != _STATUT_NOUVEAU:
        return [
            _violation(
                R_ACTION,
                d,
                _instant(d.get("ingere_le")),
                maintenant,
                seuil=None,
                donnee={"structurel": True},
                raison=f"lead au statut {d['statut']} sans aucune prochaine action (incohérence : une prochaine "
                "action est exigée à la qualification)",
            )
        ]
    cle = CLE_PREMIERE_ACTION
    ingere = _instant(d.get("ingere_le"))
    if rg[cle]["etat"] != segments.ETAT_SEUIL_OK or ingere is None:
        return []
    if not _depasse(ingere, rg[cle]["valeur"], maintenant):
        return []
    depuis = ingere + timedelta(hours=rg[cle]["valeur"])
    return [
        _violation(
            R_ACTION,
            d,
            depuis,
            maintenant,
            seuil=_seuil(cle, rg),
            donnee={"structurel": False},
            raison=f"lead nouveau sans prochaine action depuis plus de {rg[cle]['valeur']} h",
        )
    ]


def _regle_chaud(d: Mapping[str, Any], rg: Mapping[str, Any], maintenant: datetime) -> list[dict[str, Any]]:
    cle = CLE_LEAD_CHAUD
    ingere = _instant(d.get("ingere_le"))
    if d["statut"] not in (_STATUT_NOUVEAU, _STATUT_QUALIFIE) or d.get("urgence_declaree") is not True:
        return []
    if ingere is None or rg[cle]["etat"] != segments.ETAT_SEUIL_OK:
        return []
    if _apres(d.get("interactions", ()), ingere, strict=False) or not _depasse(ingere, rg[cle]["valeur"], maintenant):
        return []
    depuis = ingere + timedelta(hours=rg[cle]["valeur"])
    return [
        _violation(
            R_CHAUD,
            d,
            depuis,
            maintenant,
            seuil=_seuil(cle, rg),
            donnee={"urgence_declaree": True},
            raison=f"lead chaud jamais contacté par une personne depuis plus de {rg[cle]['valeur']} h",
        )
    ]


def _regle_photos(d: Mapping[str, Any], rg: Mapping[str, Any], maintenant: datetime) -> list[dict[str, Any]]:
    cle = CLE_PHOTOS
    if d["statut"] != _STATUT_QUALIFIE or d.get("photos") != 0 or rg[cle]["etat"] != segments.ETAT_SEUIL_OK:
        return []
    qualifie = _instant(d.get("qualifie_le"))
    if qualifie is None or not _depasse(qualifie, rg[cle]["valeur"], maintenant):
        return []
    depuis = qualifie + timedelta(hours=rg[cle]["valeur"])
    return [
        _violation(
            R_PHOTOS,
            d,
            depuis,
            maintenant,
            seuil=_seuil(cle, rg),
            donnee={"photos_liees": 0},
            raison=f"aucune photo liée au profil depuis plus de {rg[cle]['valeur']} h après la qualification",
        )
    ]


def _regle_soumission(d: Mapping[str, Any], rg: Mapping[str, Any], maintenant: datetime) -> list[dict[str, Any]]:
    if d["statut"] != _STATUT_QUALIFIE:
        return []
    if (
        rg[CLE_RELANCE_SOUMISSION]["etat"] != segments.ETAT_SEUIL_OK
        or rg[CLE_JOURS_PERIMEE]["etat"] != segments.ETAT_SEUIL_OK
    ):
        return []
    jours, heures = rg[CLE_JOURS_PERIMEE]["valeur"], rg[CLE_RELANCE_SOUMISSION]["valeur"]
    en_retard: list[tuple[datetime, str, datetime]] = []
    for devis in d.get("devis") or ():
        if devis.get("statut_devis") != "envoye":
            continue
        envoi = _instant(devis.get("horodatage_devis"))
        if envoi is None:
            continue
        echeance = envoi + timedelta(days=jours)
        if not _depasse(echeance, heures, maintenant):
            continue
        if _apres(d.get("relances_preparees") or (), echeance, strict=False) or _apres(
            d.get("interactions", ()), echeance, strict=False
        ):
            continue
        en_retard.append((echeance, str(devis.get("devis_id")), envoi))
    if not en_retard:
        return []
    echeance, devis_id, envoi = sorted(en_retard)[0]
    depuis = echeance + timedelta(hours=heures)
    return [
        _violation(
            R_SOUMISSION,
            d,
            depuis,
            maintenant,
            seuil=_seuil(CLE_RELANCE_SOUMISSION, rg),
            donnee={"devis_id": devis_id, "horodatage_devis": envoi.isoformat(), "jours_soumission_perimee": jours},
            raison=f"devis périmé non relancé depuis plus de {heures} h après son échéance",
        )
    ]


def _regle_plainte(d: Mapping[str, Any], rg: Mapping[str, Any], maintenant: datetime) -> list[dict[str, Any]]:
    cle = CLE_ESCALADE_PLAINTE
    satisfaction = d.get("satisfaction") or {}
    if d["statut"] not in _STATUTS_OUVERTS or satisfaction.get("client_satisfait") is not False:
        return []
    if rg[cle]["etat"] != segments.ETAT_SEUIL_OK:
        return []
    fin = _instant(satisfaction.get("horodatage_completion"))
    if fin is None or _apres(d.get("interactions", ()), fin, strict=False):
        return []
    if not _depasse(fin, rg[cle]["valeur"], maintenant):
        return []
    depuis = fin + timedelta(hours=rg[cle]["valeur"])
    return [
        _violation(
            R_PLAINTE,
            d,
            depuis,
            maintenant,
            seuil=_seuil(cle, rg),
            donnee={"wct_id": satisfaction.get("wct_id"), "horodatage_completion": fin.isoformat()},
            raison=f"client insatisfait sans prise en charge par une personne depuis plus de {rg[cle]['valeur']} h",
        )
    ]


def _regle_proprietaire(d: Mapping[str, Any], rg: Mapping[str, Any], maintenant: datetime) -> list[dict[str, Any]]:
    if d["statut"] not in _STATUTS_OUVERTS or d.get("proprietaire"):
        return []
    if d["statut"] != _STATUT_NOUVEAU:
        return [
            _violation(
                R_PROPRIETAIRE,
                d,
                _instant(d.get("ingere_le")),
                maintenant,
                seuil=None,
                donnee={"structurel": True},
                raison=f"lead au statut {d['statut']} sans propriétaire (incohérence : un propriétaire est exigé à la "
                "qualification)",
            )
        ]
    cle = CLE_ASSIGNATION
    ingere = _instant(d.get("ingere_le"))
    if (
        rg[cle]["etat"] != segments.ETAT_SEUIL_OK
        or ingere is None
        or not _depasse(ingere, rg[cle]["valeur"], maintenant)
    ):
        return []
    depuis = ingere + timedelta(hours=rg[cle]["valeur"])
    return [
        _violation(
            R_PROPRIETAIRE,
            d,
            depuis,
            maintenant,
            seuil=_seuil(cle, rg),
            donnee={"structurel": False},
            raison=f"lead nouveau sans propriétaire depuis plus de {rg[cle]['valeur']} h",
        )
    ]


def _regle_retard(d: Mapping[str, Any], rg: Mapping[str, Any], maintenant: datetime) -> list[dict[str, Any]]:
    cle = CLE_TOLERANCE_RETARD
    action = d.get("prochaine_action")
    if (
        d["statut"] not in _STATUTS_OUVERTS
        or not isinstance(action, Mapping)
        or rg[cle]["etat"] != segments.ETAT_SEUIL_OK
    ):
        return []
    echeance = _instant(action.get("echeance"))
    if echeance is None or not _depasse(echeance, rg[cle]["valeur"], maintenant):
        return []
    if _apres([d.get("derniere_activite")], echeance, strict=True):
        return []
    depuis = echeance + timedelta(hours=rg[cle]["valeur"])
    return [
        _violation(
            R_RETARD,
            d,
            depuis,
            maintenant,
            seuil=_seuil(cle, rg),
            donnee={"echeance": echeance.isoformat()},
            raison=f"prochaine action échue depuis plus de {rg[cle]['valeur']} h sans activité humaine depuis "
            "son échéance",
        )
    ]


_FONCTIONS = {
    R_ACTION: _regle_action,
    R_CHAUD: _regle_chaud,
    R_PHOTOS: _regle_photos,
    R_SOUMISSION: _regle_soumission,
    R_PLAINTE: _regle_plainte,
    R_PROPRIETAIRE: _regle_proprietaire,
    R_RETARD: _regle_retard,
}


# ---------------------------------------------------------------------------------------------------------
# Le scan
# ---------------------------------------------------------------------------------------------------------
def evaluer(
    dossiers: Iterable[Mapping[str, Any]],
    *,
    maintenant: str,
    reglages: Mapping[str, Mapping[str, Any]],
    sources: Mapping[str, bool],
) -> dict[str, Any]:
    """Le scan SLA de tous les dossiers : `{"examines", "regles", "violations"}`.

    `dossiers` : un dict par lead — `lead_id`, `statut`, `proprietaire`, `ingere_le`, `qualifie_le`,
    `derniere_activite`, `prochaine_action` (`{description, echeance}` ou `None`), `urgence_declaree`, `interactions`
    (les instants des notes de PERSONNES), `devis` (les devis connus de ce lead), `relances_preparees` (les instants de
    préparation d'une relance de devis), `satisfaction` (`{}` ou le dernier fait de M4), `photos` (le nombre de photos
    liées au profil confirmé du client). `reglages` : `lire_reglages`. `sources` : `{"photos", "devis",
    "satisfaction"}` -> booléen « lisible » ; une source illisible rend ses règles non évaluées.

    `regles` : les sept règles dans l'ordre de `ORDRE_REGLES`, chacune `{regle, etat, manque, violations}` (`violations`
    vaut `None` pour une règle non évaluée : jamais un zéro). `violations` : triées par règle, puis par `depuis`, puis
    par
    `lead_id` — un ordre total, donc la même sortie quel que soit l'ordre des dossiers. `maintenant` sans fuseau ou
    illisible : `ValueError`."""
    instant = segments.instant_utc(maintenant)
    etats = _etat_des_regles(reglages, sources)
    violations: list[dict[str, Any]] = []
    examines = 0
    for dossier in dossiers:
        examines += 1
        for regle in ORDRE_REGLES:
            if etats[regle]["etat"] == ETAT_NON_EVALUEE:
                continue
            violations.extend(_FONCTIONS[regle](dossier, reglages, instant))
    rang = {regle: i for i, regle in enumerate(ORDRE_REGLES)}
    violations.sort(key=lambda v: (rang[v["regle"]], v["depuis"] or "", v["lead_id"]))
    regles = []
    for regle in ORDRE_REGLES:
        etat = etats[regle]
        regles.append(
            {
                "regle": regle,
                "etat": etat["etat"],
                "manque": etat["manque"],
                "violations": None
                if etat["etat"] == ETAT_NON_EVALUEE
                else sum(1 for v in violations if v["regle"] == regle),
            }
        )
    return {"examines": examines, "regles": regles, "violations": violations}

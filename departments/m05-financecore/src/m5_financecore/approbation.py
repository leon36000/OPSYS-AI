"""Registre interne F0-F7 (M5.1) — VESTIGIAL depuis PLAN T1.3-c, gardé comme bibliothèque pure et
testée, mais SANS AUCUN appelant dans `outils.py` : aucun outil agent n'expose plus
`creer_demande`/`approuver`/`refuser` de ce module. Les deux paliers F que M5 réalise concrètement
— l'envoi d'une facture (F4) et le paiement constaté (F6) — sont désormais des outils dédiés,
gardés par le socle (`opsys.approbations`, N4/N5, ADR-0009 §4/§5 ; voir `outils.py`,
`NIVEAU_POUR_PALIER`), jamais par ce registre : une demande créée ici n'exécute RIEN (ce module ne
connaît même pas `opsys`), donc elle ne pouvait déjà pas gater une écriture réelle. Conservé pour
ne pas perdre la couverture de tests existante (`tests/test_approbation.py`) et parce qu'une
décision humaine a jugé la suppression complète hors du périmètre de PLAN T1.3-c (voir le rapport
final de cette tâche) — un futur ménage devra soit le supprimer, soit le repositionner
explicitement en simple JOURNAL de lecture (jamais un second chemin d'approbation).

Module pur (ADR-0009, même règle que `registre.py`/`facturation.py`) : aucun import `opsys`,
aucune horloge interne, aucun accès réseau.
"""

from __future__ import annotations

import json
from datetime import datetime

from . import contrats, validation

_PALIERS_PREUVE_REQUISE = ("F6", "F7")
_CHAMPS_PREUVE_REQUIS = frozenset({"methode", "horodatage", "identifiant_approbateur"})


def _dernier_maillon(registre_cible, demande_id):
    dernier = None
    for maillon in registre_cible.lire():
        if maillon.get("type_entree") not in (
            "demande_creee",
            "transition_approbation",
        ):
            continue
        if maillon.get("demande_id") != demande_id:
            continue
        dernier = maillon
    return dernier


def statut_courant(registre_cible, demande_id):
    maillon = _dernier_maillon(registre_cible, demande_id)
    return maillon["statut"] if maillon is not None else None


def creer_demande(demande_id, palier, action, registre_cible, horodatage):
    if palier not in contrats.PALIER_APPROBATION:
        return None, validation.construire_verdict(
            "REJ-PALIER-INVALIDE", detail=f"palier inconnu : {palier!r}"
        )

    if statut_courant(registre_cible, demande_id) is not None:
        return None, validation.construire_verdict(
            "REJ-DEMANDE-DEJA-CREEE",
            detail=f"demande_id déjà utilisé : {demande_id!r}",
        )

    entree = {
        "type_entree": "demande_creee",
        "demande_id": demande_id,
        "palier": palier,
        "action": action,
        "statut": "EN_ATTENTE",
        "approbateur": None,
        "preuve": None,
        "horodatage": horodatage,
    }
    ligne_id = registre_cible.ajouter(entree)
    for maillon in registre_cible.lire():
        if maillon["ligne_id"] == ligne_id:
            return maillon, None
    raise RuntimeError("Maillon ajouté introuvable.")


def _est_texte_non_vide(valeur):
    return isinstance(valeur, str) and valeur.strip() != ""


def _preuve_structure_verifiable(preuve):
    """Structure minimale exigée d'une preuve F6/F7 : méthode, horodatage ISO 8601
    avec fuseau, identifiant d'approbateur — jamais un fournisseur MFA/CPA précis
    (l'intégration cryptographique réelle est hors périmètre v1, cf. PRD §3.2).

    Bug NEW-PROD corrigé ici : `preuve` acceptait auparavant n'importe quelle chaîne
    non vide (ex. "PV-COMITE-F6-001"). Elle doit désormais être une chaîne JSON
    encodant un objet portant EXACTEMENT ces trois clés, chacune non vide et
    l'horodatage effectivement parseable en ISO 8601 avec fuseau — sans quoi la
    « preuve » ne prouve structurellement rien.
    """
    try:
        contenu = json.loads(preuve)
    except (TypeError, ValueError):
        return False
    if not isinstance(contenu, dict) or set(contenu.keys()) != _CHAMPS_PREUVE_REQUIS:
        return False
    if not _est_texte_non_vide(contenu.get("methode")):
        return False
    if not _est_texte_non_vide(contenu.get("identifiant_approbateur")):
        return False
    horodatage_preuve = contenu.get("horodatage")
    if not isinstance(horodatage_preuve, str):
        return False
    try:
        analyse = datetime.fromisoformat(horodatage_preuve)
    except ValueError:
        return False
    return analyse.tzinfo is not None


def _transitionner(demande_id, statut_cible, approbateur, registre_cible, horodatage, preuve):
    dernier = _dernier_maillon(registre_cible, demande_id)
    if dernier is None:
        return None, validation.construire_verdict(
            "REJ-DEMANDE-INTROUVABLE", detail=f"demande inconnue : {demande_id!r}"
        )

    if dernier["statut"] != "EN_ATTENTE":
        return None, validation.construire_verdict(
            "REJ-TRANSITION-ILLEGALE",
            detail=(
                f"demande {demande_id!r} déjà au statut terminal "
                f"{dernier['statut']!r}"
            ),
        )

    if not _est_texte_non_vide(approbateur):
        return None, validation.construire_verdict(
            "REJ-APPROBATEUR-ABSENT", detail="approbateur requis, non vide"
        )

    preuve_retenue = None
    if statut_cible == "APPROUVE" and dernier["palier"] in _PALIERS_PREUVE_REQUISE:
        if not _est_texte_non_vide(preuve):
            return None, validation.construire_verdict(
                "REJ-PREUVE-ABSENTE",
                detail=(
                    f"preuve requise au palier {dernier['palier']!r} "
                    "pour APPROUVE"
                ),
            )
        if not _preuve_structure_verifiable(preuve):
            return None, validation.construire_verdict(
                "REJ-PREUVE-STRUCTURE-INVALIDE",
                detail=(
                    f"preuve au palier {dernier['palier']!r} doit être un JSON "
                    "portant methode, horodatage (ISO 8601 avec fuseau) et "
                    "identifiant_approbateur, tous non vides"
                ),
            )
        preuve_retenue = preuve

    entree = {
        "type_entree": "transition_approbation",
        "demande_id": demande_id,
        "palier": dernier["palier"],
        "action": dernier["action"],
        "statut": statut_cible,
        "approbateur": approbateur,
        "preuve": preuve_retenue,
        "horodatage": horodatage,
    }
    ligne_id = registre_cible.ajouter(entree)
    for maillon in registre_cible.lire():
        if maillon["ligne_id"] == ligne_id:
            return maillon, None
    raise RuntimeError("Maillon ajouté introuvable.")


def approuver(demande_id, approbateur, registre_cible, horodatage, preuve=None):
    return _transitionner(
        demande_id, "APPROUVE", approbateur, registre_cible, horodatage, preuve
    )


def refuser(demande_id, approbateur, registre_cible, horodatage):
    return _transitionner(
        demande_id, "REFUSE", approbateur, registre_cible, horodatage, None
    )

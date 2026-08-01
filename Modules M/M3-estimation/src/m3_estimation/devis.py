"""Assemblage du devis d'estimation gelé de M3.

Ce module produit le contrat ``EstimationV1`` complet et dérive son
``devis_id`` déterministe. L'encodage préfixé par les longueurs est injectif
pour les entrées admises ; le ``devis_id`` qui en résulte ne l'est pas, car
le SHA-256 est tronqué à seize caractères hexadécimaux, soit 64 bits : deux
encodages distincts peuvent donc collisionner. Cette troncature apporte une
résistance aux collisions, jamais une prétention d'injectivité.

``hash_maillon`` est fourni par l'appelant. Le registre qui le produit relève
de S008, dépendante de cette story : le calculer ici ou lui attribuer une
valeur serait fabriquer une donnée absente.

La priorité des verdicts est épinglée dans une séquence nommée. Une cause de
blocage prime sur une alerte de plancher, car cette alerte n'a de sens que
lorsqu'un prix a réellement été produit ; INDETERMINE reste l'échappatoire
des blocages seulement après les causes nommées.
"""

import hashlib

from . import contrats, verdicts

__all__ = ["deriver_devis_id", "assembler_estimation"]


_PREFIXE_DEVIS_ID = "M3-DEVIS-"
_FORMAT_LONGUEUR = "04d"
_LONGUEUR_MAXIMALE_ENCODABLE = 9999
_LONGUEUR_EMPREINTE = 64
_CARACTERES_HEXADECIMAUX_MINUSCULES = frozenset("0123456789abcdef")
_ABSENT = object()

_PRIORITE_VERDICTS = (
    contrats.VERDICT_CONTRAT_ENTREE_INVALIDE,
    contrats.VERDICT_QUALITE_ENTREE_INSUFFISANTE,
    contrats.VERDICT_REFERENCE_ECHELLE_ABSENTE,
    contrats.VERDICT_INDETERMINE,
    contrats.VERDICT_PLANCHER_RENTABILITE_FRANCHI,
    contrats.VERDICT_AUCUN_BLOCAGE,
)


def _est_nombre_fini(valeur):
    """Indique si valeur est un nombre fini qui n'est pas un booléen."""
    if isinstance(valeur, bool):
        return False
    if isinstance(valeur, int):
        return True
    if isinstance(valeur, float):
        return valeur == valeur and valeur != float("inf") and valeur != float("-inf")
    return False


def _empreinte_est_valide(empreinte):
    """Vérifie la forme canonique, sans jamais normaliser la casse."""
    return (
        isinstance(empreinte, str)
        and len(empreinte) == _LONGUEUR_EMPREINTE
        and all(
            caractere in _CARACTERES_HEXADECIMAUX_MINUSCULES
            for caractere in empreinte
        )
    )


def _rejet(detail):
    """Construit le rejet contractuel unique de l'assembleur."""
    return None, verdicts.construire_verdict(
        "REJ-CONTRAT-INVALIDE",
        detail=detail,
    )


def deriver_devis_id(lead_id, empreinte_marqueur_m2):
    """Dérive l'identifiant de devis gelé depuis le lead et son empreinte M2."""
    if not isinstance(lead_id, str) or not lead_id:
        raise ValueError("lead_id doit être une chaîne non vide")
    # Garde de SÉCURITÉ : au-delà de 9999, :04d écrit plus de quatre
    # chiffres et le format à largeur fixe perd son injectivité au décodage.
    if len(lead_id) > _LONGUEUR_MAXIMALE_ENCODABLE:
        raise ValueError("lead_id dépasse la longueur encodable sûre")
    if not _empreinte_est_valide(empreinte_marqueur_m2):
        raise ValueError(
            "empreinte_marqueur_m2 doit contenir 64 hexadécimaux minuscules"
        )

    encodage = (
        format(len(lead_id), _FORMAT_LONGUEUR)
        + lead_id
        + format(len(empreinte_marqueur_m2), _FORMAT_LONGUEUR)
        + empreinte_marqueur_m2
    )
    return _PREFIXE_DEVIS_ID + hashlib.sha256(
        encodage.encode("utf-8")
    ).hexdigest()[:16]


def _intervalle_est_valide(intervalle_confiance, prix_bloque):
    """Vérifie la forme fermée et les cohérences des bornes de l'intervalle."""
    if not isinstance(intervalle_confiance, dict):
        return False
    if set(intervalle_confiance) != set(contrats.CHAMPS_INTERVALLE_CONFIANCE):
        return False

    borne_basse = intervalle_confiance["borne_basse"]
    borne_haute = intervalle_confiance["borne_haute"]
    niveau = intervalle_confiance["niveau"]

    if not _est_nombre_fini(niveau):
        return False
    if prix_bloque:
        return borne_basse is None and borne_haute is None
    if not _est_nombre_fini(borne_basse) or not _est_nombre_fini(borne_haute):
        return False
    return borne_basse <= borne_haute


def _selectionner_verdict(verdicts_estimation):
    """Retourne le verdict le plus prioritaire parmi les verdicts admis."""
    if not isinstance(verdicts_estimation, tuple) or not verdicts_estimation:
        return None
    if any(verdict not in contrats.VERDICTS_ESTIMATION for verdict in verdicts_estimation):
        return None
    for verdict_prioritaire in _PRIORITE_VERDICTS:
        if verdict_prioritaire in verdicts_estimation:
            return verdict_prioritaire
    return None


def assembler_estimation(
    lead_id=_ABSENT,
    empreinte_marqueur_m2=_ABSENT,
    niveau_confiance=_ABSENT,
    verdicts_estimation=_ABSENT,
    bareme_version=_ABSENT,
    prix_bloque=_ABSENT,
    intervalle_confiance=_ABSENT,
    alerte_plancher=_ABSENT,
    raison_blocage=_ABSENT,
    graine_monte_carlo=_ABSENT,
    hash_maillon=_ABSENT,
    **champs_inconnus
):
    """Assemble une estimation conforme au contrat gelé, ou un rejet fermé."""
    # La liste blanche fermée refuse aussi les noms financiers ou temporels
    # anodins, qu'une liste noire lexicale ne pourrait pas reconnaître.
    if champs_inconnus:
        return _rejet("clé hors liste blanche du contrat EstimationV1")

    entrees = (
        lead_id,
        empreinte_marqueur_m2,
        niveau_confiance,
        verdicts_estimation,
        bareme_version,
        prix_bloque,
        intervalle_confiance,
        alerte_plancher,
        raison_blocage,
        graine_monte_carlo,
        hash_maillon,
    )
    if any(valeur is _ABSENT for valeur in entrees):
        return _rejet("champ obligatoire absent de l'assemblage")

    if not isinstance(prix_bloque, bool):
        return _rejet("prix_bloque doit être booléen")
    if not isinstance(alerte_plancher, bool):
        return _rejet("alerte_plancher doit être booléen")
    if not _est_nombre_fini(niveau_confiance):
        return _rejet("niveau_confiance doit être numérique et fini")
    if (
        isinstance(graine_monte_carlo, bool)
        or not isinstance(graine_monte_carlo, int)
        or graine_monte_carlo < 0
    ):
        return _rejet("graine_monte_carlo doit être un entier positif ou nul")
    if not isinstance(hash_maillon, str) or not hash_maillon:
        return _rejet("hash_maillon doit être une chaîne non vide")

    verdict_estimation = _selectionner_verdict(verdicts_estimation)
    if verdict_estimation is None:
        return _rejet("verdicts_estimation doit contenir des verdicts M3 connus")

    if not _intervalle_est_valide(intervalle_confiance, prix_bloque):
        return _rejet("intervalle_confiance incompatible avec le contrat")

    if prix_bloque:
        if bareme_version is not None:
            return _rejet("bareme_version doit être None quand le prix est bloqué")
        if not isinstance(raison_blocage, str) or not raison_blocage:
            return _rejet("raison_blocage non vide requise quand le prix est bloqué")
    else:
        if not isinstance(bareme_version, str) or not bareme_version:
            return _rejet(
                "bareme_version non vide requise quand le prix n'est pas bloqué"
            )
        if raison_blocage is not None:
            return _rejet("raison_blocage doit être None quand le prix est produit")

    try:
        devis_id = deriver_devis_id(lead_id, empreinte_marqueur_m2)
    except ValueError:
        return _rejet("lead_id ou empreinte_marqueur_m2 invalide")

    estimation = {
        "devis_id": devis_id,
        "lead_id": lead_id,
        "empreinte_marqueur_m2": empreinte_marqueur_m2,
        "niveau_confiance": niveau_confiance,
        "verdict_estimation": verdict_estimation,
        "bareme_version": bareme_version,
        "prix_bloque": prix_bloque,
        "intervalle_confiance": intervalle_confiance,
        "alerte_plancher": alerte_plancher,
        "raison_blocage": raison_blocage,
        "graine_monte_carlo": graine_monte_carlo,
        "hash_maillon": hash_maillon,
    }
    # estimation est un littéral : son ensemble de clés est fixé à l'analyse et un
    # contrôle dynamique ne pourrait jamais se déclencher. Sa correspondance avec
    # CHAMPS_ESTIMATION_V1 est verrouillée statiquement par
    # test_assembler_estimation_verrouille_statiquement_cles_litterales.
    return estimation, None


# Un contrôle qui ne peut jamais se déclencher n'est pas une garde

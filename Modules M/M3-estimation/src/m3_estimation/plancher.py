"""Confrontation de l'intervalle d'estimation au plancher rentable (M3-S006).

La confrontation au plancher est une ALERTE, pas un blocage : lorsque la
borne basse de l'intervalle tombe sous le plancher rentable, M3 SIGNALE une
marge possiblement négative et laisse la décision à l'humain. Le verdict
émis sur la voie d'alerte, ``PLANCHER_RENTABILITE_FRANCHI``, appartient au
catalogue fermé ``VerdictEstimation`` et n'est JAMAIS un verdict de rejet.

Le plancher est FOURNI par l'appelant à chaque appel : un plancher codé en
dur transformerait une politique commerciale — vouée à évoluer avec
l'entreprise — en constante de code, et la soustrairait à qui la fixe.

Le module est fail-closed : toute entrée invalide — intervalle non
dictionnaire, clé requise absente, borne basse nulle ou non numérique,
plancher non numérique, booléen, non fini ou négatif — rend
``(None, verdict)`` avec un code EXISTANT du catalogue M3, et aucune
exception ne s'échappe vers l'appelant.
"""

import math

from . import contrats, verdicts

__all__ = ["confronter_au_plancher"]


# Clés exigées de l'intervalle, dans la forme rendue par
# ``monte_carlo.simuler_intervalle`` : TROIS clés obligatoires.
_CLES_INTERVALLE_REQUISES = frozenset({"borne_basse", "borne_haute", "niveau"})

# Verdicts d'estimation émis par ce module — deux MEMBRES du catalogue fermé
# ``contrats.VERDICTS_ESTIMATION``, jamais des codes inventés.
_VERDICT_ALERTE = contrats.VERDICT_PLANCHER_RENTABILITE_FRANCHI
_VERDICT_SANS_ALERTE = contrats.VERDICT_AUCUN_BLOCAGE

# Garde de non-dérive : si le catalogue fermé cessait de porter l'un de ces
# deux verdicts, mieux vaut un refus franc au chargement qu'un constat hors
# catalogue servi en silence aux consommateurs aval.
if (
    _VERDICT_ALERTE not in contrats.VERDICTS_ESTIMATION
    or _VERDICT_SANS_ALERTE not in contrats.VERDICTS_ESTIMATION
):
    raise verdicts.CodeVerdictInconnu(
        "verdict_estimation hors catalogue VERDICTS_ESTIMATION"
    )


def _est_nombre_fini(valeur):
    """Retourne True si ``valeur`` est un nombre FINI, jamais un booléen.

    ``isinstance(True, int)`` est vrai en Python : le booléen doit être
    refusé EXPLICITEMENT, sinon ``True`` passerait pour le nombre 1 et
    ``True < plancher`` serait une comparaison syntaxiquement valide au
    résultat silencieusement faux. Tout entier est fini par construction ;
    seul le flottant doit être confronté à ``math.isfinite`` (inf, nan).
    """
    if isinstance(valeur, bool):
        return False
    if isinstance(valeur, int):
        return True
    if isinstance(valeur, float):
        return math.isfinite(valeur)
    return False


def confronter_au_plancher(intervalle, plancher_rentable):
    """Confronte la borne basse de ``intervalle`` au ``plancher_rentable``.

    Rend ``(constat, None)`` quand la confrontation a lieu, ``(None,
    verdict)`` quand une entrée est invalide. ``constat`` porte EXACTEMENT
    deux clés : ``alerte_plancher`` (booléen exact) et
    ``verdict_estimation`` (membre de ``contrats.VERDICTS_ESTIMATION``).

    ``plancher_rentable`` vient TOUJOURS de l'appelant : aucune valeur par
    défaut, aucun seuil codé en dur.
    """
    # --- Validation fail-closed, AVANT toute comparaison ---
    if not isinstance(intervalle, dict):
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            detail="intervalle non dictionnaire : confrontation impossible",
        )
    if not _CLES_INTERVALLE_REQUISES.issubset(intervalle):
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            detail=(
                "intervalle amputé d'au moins une des clés requises "
                "(borne_basse, borne_haute, niveau)"
            ),
        )
    borne_basse = intervalle["borne_basse"]
    if borne_basse is None:
        # Comparer None à un nombre lèverait TypeError en Python 3 : le
        # refus NOMMÉ d'un prix bloqué en amont vaut mieux que le plantage
        # chez l'appelant — la confrontation est ici IMPOSSIBLE.
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            detail="borne_basse None : le prix a été bloqué en amont",
        )
    if not _est_nombre_fini(borne_basse):
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            detail="borne_basse non numérique, booléenne ou non finie",
        )
    if not _est_nombre_fini(plancher_rentable):
        return None, verdicts.construire_verdict(
            "REJ-SEUILS-INVALIDES",
            detail="plancher_rentable non numérique, booléen ou non fini",
        )
    if plancher_rentable < 0:
        # Un plancher de rentabilité NÉGATIF n'a pas de sens : aucune borne
        # basse légitime ne tombe sous lui et l'alerte deviendrait un
        # décorum. Le plancher ZÉRO, lui, est acceptable — la frontière du
        # rejet est EXACTEMENT « négatif ».
        return None, verdicts.construire_verdict(
            "REJ-SEUILS-INVALIDES",
            detail="plancher_rentable négatif",
        )

    # --- La règle : comparaison STRICTE ---
    # Le cas d'ÉGALITÉ (borne_basse == plancher_rentable) ne déclenche PAS
    # l'alerte : une estimation exactement au plancher est rentable au sens
    # du contrat, et un « <= » la signalerait à tort.
    alerte = borne_basse < plancher_rentable

    # L'alerte NE BLOQUE PAS : la transformer en blocage — tuple de rejet
    # (None, verdict) ou clé de blocage ajoutée au constat — ferait refuser
    # une affaire simplement peu rentable, alors que la décision appartient
    # à l'humain. Le verdict PLANCHER_RENTABILITE_FRANCHI est un SIGNAL,
    # pas un verrou.
    constat = {
        "alerte_plancher": alerte,
        "verdict_estimation": _VERDICT_ALERTE if alerte else _VERDICT_SANS_ALERTE,
    }
    return constat, None

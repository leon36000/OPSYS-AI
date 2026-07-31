"""Garde anti-précision-inventée du module M3-estimation (cahier M3-S004).

Quand le niveau de confiance est INDETERMINE ou la qualité des entrées
insuffisante, M3 n'émet AUCUN chiffre : les bornes de l'intervalle sont
nulles (``None``, jamais zéro) et la raison du blocage est explicite.
Pourquoi : un intervalle produit sur des entrées qu'on ne sait pas
classifier serait une précision inventée, et un chiffre faux fait plus de
dégâts qu'une absence de chiffre assumée.

Ce module ne CALCULE aucun prix — il décide seulement du blocage ; le calcul
de l'intervalle est la story suivante. La décision est une fonction pure des
deux entrées : aucun réseau, aucun sous-processus, aucun modèle, aucun aléa,
aucune horloge (DA-M3-05).

R-020 : les raisons de blocage sont des constats sur les entrées, jamais des
accusations — aucun responsable n'est nommé. D-032 : INDETERMINE est
l'échappatoire « on ne sait pas pourquoi », retenu seulement quand aucune
cause nommable ne classifie le blocage.
"""

from . import hierarchie_echelle
from . import verdicts

# Niveau de confiance nominal ÉNONCÉ par l'architecture pour les intervalles
# de M3 : valeur déclarée en constante nommée, pas un chiffre inventé. Ce
# module ne CALCULE aucun intervalle — il décide du blocage — donc aucun
# chiffre n'est émis ici ; la constante est la source nommée unique de cette
# valeur pour le paquet, et le champ ``niveau`` de l'intervalle porte le
# niveau issu de la hiérarchie, pas une valeur numérique.
NIVEAU_CONFIANCE_NOMINAL = 0.90

# Verdicts d'estimation du jeu FERMÉ : le verdict qui nomme la cause, le
# verdict acceptable et l'échappatoire D-032. Aucune autre valeur n'est
# légitime dans une décision.
VERDICT_QUALITE_INSUFFISANTE = "QUALITE_ENTREE_INSUFFISANTE"
# La valeur est lue dans l'énuméré fermé ``VerdictEstimation`` (copie épinglée
# ``contrats.VERDICTS_ESTIMATION``, architecture section 2.5) : aucun verdict
# ne s'invente ici.
VERDICT_AUCUN_BLOCAGE = "AUCUN_BLOCAGE"
VERDICT_INDETERMINE = "INDETERMINE"

# Clés EXACTES du contrat produit par ``qualite_photos.qualifier_photos`` :
# liste FERMÉE — une clé en plus ou en moins signifie un contrat dérivé.
CHAMPS_QUALIFICATION = frozenset(
    {
        "photos_acceptables",
        "verdict_estimation",
        "prix_bloque",
        "elements_manquants",
    }
)


def _cles_fautives(cles_recues, cles_attendues):
    """Retourne la description triée des clés en plus ou en moins."""
    diff = set(cles_recues).symmetric_difference(cles_attendues)
    return ", ".join(str(cle) for cle in sorted(diff, key=str))


def _construire_raison(verdict_estimation, elements_manquants):
    """Construit la raison de blocage : un constat, jamais une accusation.

    R-020 : aucun responsable n'est nommé — la phrase décrit ce qui manque
    dans les entrées, pas qui l'aurait causé. Retourne toujours une chaîne
    non vide et non blanche.
    """
    if verdict_estimation == VERDICT_QUALITE_INSUFFISANTE:
        # Chaque élément manquant est repris TEL QUEL dans la raison : une
        # formulation générique n'aiderait personne à compléter le dossier —
        # la phrase doit NOMMER ce qui manque.
        if isinstance(elements_manquants, list) and elements_manquants:
            return (
                "Qualité des entrées insuffisante pour émettre un intervalle "
                "de confiance, éléments constatés manquants ou sous les "
                "seuils fournis : "
                + " ; ".join(str(element) for element in elements_manquants)
                + "."
            )
        return (
            "Qualité des entrées insuffisante pour émettre un intervalle de "
            "confiance."
        )
    # Blocage par le seul niveau INDETERMINE : les métadonnées fournies ne
    # permettent aucune classification dans les niveaux exploitables. La
    # raison le dit comme un constat — elle empêche à la fois le chiffre
    # optimiste par défaut et la mise en cause d'une personne.
    return (
        "Les métadonnées fournies ne permettent de classifier le niveau de "
        "confiance dans aucun des niveaux exploitables de la hiérarchie : "
        "aucun chiffre n'est émis plutôt qu'une précision inventée."
    )


def decider_blocage(niveau_confiance, qualification):
    """Décide si le prix est bloqué, et avec quel verdict d'estimation.

    Ordre ÉPINGLÉ : validation du niveau, validation de la qualification,
    décision enfin ; rien n'est produit si un contrôle échoue. Retourne
    ``(decision, None)`` quand les entrées sont reconnues, ``(None,
    verdict)`` sinon — JAMAIS une exception qui s'échappe.
    """
    # Empêche : un niveau hors du jeu fermé traité comme classifiable — il
    # est rejeté, pas deviné. L'appartenance est testée sur le tuple par
    # égalité, jamais par hachage : le contrôle est sûr pour tout type.
    if niveau_confiance not in hierarchie_echelle.NIVEAUX_CONFIANCE:
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            detail=(
                "niveau_confiance hors du jeu fermé : "
                + repr(niveau_confiance)
            ),
        )
    # Empêche : une qualification dérivée lue quand même — une clé absente
    # donnerait un KeyError nu, une clé en trop trahit un producteur qui ne
    # respecte plus le contrat de qualite_photos. Rejet contrôlé dans les
    # deux cas, avec un code du catalogue existant.
    if not isinstance(qualification, dict):
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            detail="qualification n'est pas un dictionnaire",
        )
    if set(qualification) != CHAMPS_QUALIFICATION:
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            detail=(
                "clé fautive : "
                + _cles_fautives(qualification, CHAMPS_QUALIFICATION)
            ),
        )

    qualite_insuffisante = (
        qualification["verdict_estimation"] == VERDICT_QUALITE_INSUFFISANTE
    )
    niveau_indetermine = niveau_confiance == VERDICT_INDETERMINE

    # Les bornes valent TOUJOURS None : ce module ne CALCULE aucun prix, il
    # décide du blocage — le calcul est la story suivante. Empêche : un
    # « 0 » lu comme un prix là où None dit l'absence de prix. Le champ
    # ``niveau`` porte le niveau issu de la hiérarchie ; le niveau de
    # confiance nominal énoncé par l'architecture (NIVEAU_CONFIANCE_NOMINAL)
    # n'est volontairement pas émis : aucun chiffre ne quitte un module qui
    # ne calcule rien.
    # Ce que la confusion produisait : le champ portait le NOM du niveau de
    # confiance là où le contrat attend le TAUX numérique de l'intervalle —
    # deux grandeurs différentes qui partagent un mot. Le contrat déclare
    # ``niveau: float`` ; la valeur émise est la constante nominale énoncée
    # par l'architecture, jamais la chaîne issue de la hiérarchie.
    intervalle_confiance = {
        "borne_basse": None,
        "borne_haute": None,
        "niveau": NIVEAU_CONFIANCE_NOMINAL,
    }

    # LA RÈGLE : bloqué si le niveau est INDETERMINE, OU si la qualification
    # conclut à une qualité d'entrée insuffisante.
    if qualite_insuffisante or niveau_indetermine:
        # ORDRE ÉPINGLÉ : le verdict qui NOMME la cause est éprouvé en
        # premier. L'ordre inverse rabattrait tout blocage à double cause sur
        # INDETERMINE — l'échappatoire « on ne sait pas pourquoi » (D-032) —
        # alors qu'une cause nommable existe : la raison exacte du blocage
        # serait perdue et remplacée par un aveu d'ignorance injustifié.
        if qualite_insuffisante:
            verdict_estimation = VERDICT_QUALITE_INSUFFISANTE
        else:
            verdict_estimation = VERDICT_INDETERMINE
        return {
            "prix_bloque": True,
            "verdict_estimation": verdict_estimation,
            "intervalle_confiance": intervalle_confiance,
            "raison_blocage": _construire_raison(
                verdict_estimation, qualification["elements_manquants"]
            ),
        }, None

    # Aucun blocage : le verdict est acceptable et la raison est None — mais
    # les bornes restent None : décider du non-blocage n'est pas calculer un
    # prix. Empêche : un blocage par défaut ou un verdict bloquant résiduel.
    return {
        "prix_bloque": False,
        "verdict_estimation": VERDICT_AUCUN_BLOCAGE,
        "intervalle_confiance": intervalle_confiance,
        "raison_blocage": None,
    }, None


__all__ = [
    "NIVEAU_CONFIANCE_NOMINAL",
    "decider_blocage",
]

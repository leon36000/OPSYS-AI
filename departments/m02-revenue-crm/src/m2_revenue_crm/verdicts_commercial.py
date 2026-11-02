"""Catalogue FERMÉ des refus typés des capacités commerciales de M2 : profil de propriété (M2.3), score de lead (M2.4),
coach de vente (M2.9), analytique et prévisions (M2.15).

À part de `verdicts.py` à dessein (même patron que `verdicts_calcul.py` de M5) : le catalogue historique de M2 est
épinglé par des tests et par un gel documentaire ; ces codes-ci vivent dans leur propre liste fermée. La forme du
verdict est la même (`code`, `statut`, `detail`) : un refus se lit pareil partout. Un code hors catalogue lève
`CodeVerdictInconnu` : jamais un refus à code inventé en cours de route.
"""

from __future__ import annotations

from .verdicts import CodeVerdictInconnu

__all__ = ["CODES_COMMERCIAL", "CODES_COMMERCIAL_LIST", "construire_verdict", "est_verdict"]

CODES_COMMERCIAL_LIST = [
    # -- Profil de propriété (M2.3)
    "REJ-PROP-ARGUMENT-INVALIDE",  # argument absent, mal typé ou hors bornes
    "REJ-PROP-CHAMP-INCONNU",  # champ hors de la liste blanche (minimisation, Loi 25)
    "REJ-PROP-VALEUR-INVALIDE",  # valeur hors énuméré, hors bornes ou mal formée
    "REJ-PROP-TEXTE-REFUSE",  # texte libre qui porte un contact, un lien, une adresse ou un prix
    "REJ-PROP-SOURCE-INVALIDE",  # source absente ou mal formée : tout fait de propriété est sourcé
    "REJ-PROP-INCONNUE",  # propriété inconnue pour ce client
    "REJ-PROP-CLIENT-INCONNU",  # client sans lead visible (ou inconnu), même refus
    "REJ-PROP-REVISION-PERIMEE",  # la révision lue n'est plus la courante
    "REJ-PROP-DEJA-DECIDEE",  # la proposition a déjà été confirmée ou écartée
    "REJ-PROP-AUCUNE-PROPOSITION",  # rien à confirmer
    "REJ-PROP-EXTRACTION-VIDE",  # le courriel ne contient aucun fait de propriété reconnu
    "REJ-PROP-ADRESSE-REQUISE",  # création d'une propriété sans adresse
    "REJ-PROP-QUOTA",  # trop de propriétés ou de révisions pour ce client
    "REJ-PROP-ONBOARDING-INCONNU",  # client importé inconnu
    # -- Score de lead (M2.4)
    "REJ-SCORE-CHAMP-INTERDIT",  # attribut protégé ou identifiant personnel proposé comme facteur
    "REJ-SCORE-LEAD-CLOS",  # lead terminal : rien à classer
    "REJ-SCORE-FAITS-INVALIDES",  # faits d'entrée mal formés (hors modèle)
    "REJ-SCORE-MODELE-INCONNU",  # version de modèle inconnue
    # -- Coach de vente (M2.9)
    "REJ-COACH-TEXTE-REFUSE",  # garde-fou de texte : prix, engagement, date promise, contact…
    "REJ-COACH-FAIT-INCONNU",  # une citation ne correspond à aucun fait du contexte du coach
    "REJ-COACH-SOURCE-INCONNUE",  # une source citée n'est pas une connaissance publiée lisible
    "REJ-COACH-SANS-FAIT",  # suggestion sans aucun fait du CRM cité
    "REJ-COACH-CONTEXTE-PERIME",  # l'empreinte de contexte citée n'est plus celle du dossier
    "REJ-COACH-SUGGESTION-INCONNUE",  # suggestion inconnue
    "REJ-COACH-DEJA-DECIDEE",  # suggestion déjà acceptée, modifiée ou rejetée
    "REJ-COACH-DECISION-INVALIDE",  # décision hors énuméré
    "REJ-COACH-ENVOI-INTERDIT",  # demande d'envoi : le coach ne prépare qu'un brouillon
    "REJ-COACH-ARGUMENT-INVALIDE",  # argument absent, mal typé ou hors bornes
    # -- Analytique et prévisions (M2.15)
    "REJ-PREV-ECHANTILLON-INSUFFISANT",  # sous le seuil déclaré : le calcul refuse, il ne devine pas
    "REJ-PREV-PARAMETRE-INVALIDE",  # méthode, fenêtre, lissage, horizon, niveau ou graine invalide
    "REJ-PREV-SERIE-DEGENEREE",  # historique constant : un intervalle n'aurait aucun sens
    "REJ-PREV-VALEUR-ABSENTE",  # valeur pondérée sans valeur déclarée
    "REJ-PREV-RECU-INVALIDE",  # reçu retouché, compact ou d'un moteur inconnu
    "REJ-PREV-VALEUR-INVALIDE",  # montant déclaré mal formé
    "REJ-PREV-BUS-INDISPONIBLE",  # registres durables indisponibles
    # -- Relances (M2-C5)
    "REJ-RELANCE-DEJA-PREPAREE",  # déjà préparée et que personne n'a notée au dossier : pas de seconde préparation
    # -- Filet anti-perte (M2-C1)
    "REJ-FILET-PERIMETRE-GLOBAL",  # le filet porte sur tous les leads : agent ou admin seulement
]
CODES_COMMERCIAL = frozenset(CODES_COMMERCIAL_LIST)


def est_verdict(code: object) -> bool:
    """Vrai si `code` est un code du catalogue commercial."""
    return code in CODES_COMMERCIAL


def construire_verdict(code: str, statut: str = "", detail: str = "") -> dict[str, str]:
    """Le verdict `{code, statut, detail}` ; lève `CodeVerdictInconnu` pour un code hors catalogue."""
    if not est_verdict(code):
        raise CodeVerdictInconnu(f"Code verdict commercial invalide : {code!r}")
    return {"code": code, "statut": statut, "detail": detail}

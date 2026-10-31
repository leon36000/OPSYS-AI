"""Contrats des propriétaires : ce que M9 sait lire, sans rien fabriquer.

Module pur. Pour chaque donnée que M9 attendait d'un propriétaire (capacité d'équipe M4, dépenses marketing M7, plaintes
structurées M1), ce module nomme le contrat et valide une charge contre le contrat RÉEL du propriétaire
(``charges_producteurs``, la même validation que la capture applique). Il ne produit aucune valeur ni ne complète
ou corrige rien : un nombre doit arriver en TEXTE décimal exact (un flottant est refusé), une valeur hors de l'énuméré
fermé est refusée, une absence est ``null`` avec un manque nommé, jamais un zéro.

L'état d'un contrat se lit sur le catalogue des lectures de M9 (``catalogue_producteurs``) : tant que la lecture
attendue n'y figure pas, le contrat est ``ABSENT_CHEZ_LE_PROPRIETAIRE`` et M9 le dit. Une extrapolation de M9
(``origine == "tendance_extrapolee"``) n'est jamais une prévision de propriétaire : ``refuser_extrapolation`` la refuse
si elle est présentée comme telle.

Le contrat M8 → M9 des définitions versionnées est dans ``preuves_definition`` (preuve propre à chaque observation).
"""

from __future__ import annotations

from collections.abc import Mapping

from . import catalogue_producteurs as cat
from . import charges_producteurs

ORIGINE_EXTRAPOLATION = "tendance_extrapolee"
# Catégories fermées de signaux de plainte de M1 (``opsys.taxonomie.CATEGORIES_SIGNAL_PLAINTE``) ; un test compare.
CATEGORIES_PLAINTE = frozenset(charges_producteurs.M1_CATEGORIES)

CONTRATS: dict[str, dict] = {
    "capacite_equipe": {
        "proprietaire": "m04-field-ops",
        "lecture_id": "m4.capacite_equipe",
        "outil_attendu": "m4_lire_capacite_equipe",
        "reel": {"enveloppe_accepte": True},
        "limite": "Branché sur le contrat réel de M4 (m4.capacite_equipe v1) : unité heures_declarees seulement, "
        "jamais convertie en jours-personnes ; borne basse sur les journées datées ; "
        "non calculable = aucune valeur. M9 ne déduit aucune capacité des interventions planifiées.",
    },
    "depenses_marketing": {
        "proprietaire": "m07-marketing",
        "lecture_id": "m7.depenses_marketing",
        "outil_attendu": "m7_lire_depenses_marketing",
        "reel": {"enveloppe_accepte": False},
        "limite": "Branché sur le contrat réel de M7 (schéma opsys.m7.depenses_marketing/v1) : un total n'existe que "
        "statut CONNUE ; NON_BRANCHEE ne donne aucun montant. M7 n'a encore aucune ingestion ni saisie réelle de "
        "relevés : tant qu'aucun relevé n'est inscrit, la lecture dit NON_BRANCHEE.",
    },
    "plaintes_structurees": {
        "proprietaire": "m01-front-office",
        "lecture_id": "m1.plaintes_structurees",
        "outil_attendu": "m1_lire_plaintes_structurees",
        "reel": {"enveloppe_accepte": True},
        "limite": "Branché sur le contrat réel de M1 (m1.plaintes_structurees v1) : NON_BRANCHEE = comptes null ; "
        "AUCUNE_DECLAREE_PAR_SOURCE se cite telle quelle, jamais comme « 0 plainte » ; aucun texte ni identité. Sans "
        "plainte déclarée, M9 ne crée aucun risque de réputation.",
    },
}


def etat(domaine: str) -> str:
    """``PUBLIE`` si la lecture attendue figure au catalogue de M9 ; sinon ``ABSENT_CHEZ_LE_PROPRIETAIRE``."""
    contrat = CONTRATS[domaine]
    return "PUBLIE" if contrat["lecture_id"] in cat.PAR_ID else "ABSENT_CHEZ_LE_PROPRIETAIRE"


def valider_charge(domaine: str, charge: object, arguments: Mapping | None = None) -> dict:
    """Conformité d'une charge candidate au contrat RÉEL du propriétaire (celui que la capture applique).

    ``manques`` est vide (le contrat réel nomme ses erreurs : un champ absent est une erreur). Rien n'est complété ni
    corrigé ; ``conforme`` n'est vrai que sans erreur ; une charge non objet n'est jamais conforme. ``arguments`` : la
    demande faite au producteur (période ou semaine), comparée à ce qu'il rend."""
    contrat = CONTRATS[domaine]
    if not isinstance(charge, Mapping):
        return {"domaine": domaine, "conforme": False, "manques": ["charge"], "erreurs": ["charge non objet"]}
    enveloppe = contrat["reel"]["enveloppe_accepte"]
    page = {"resultat": {"accepte": True, "resultat": charge}} if enveloppe else {"resultat": charge}
    erreurs = charges_producteurs.valider(contrat["lecture_id"], page, arguments)
    return {"domaine": domaine, "conforme": not erreurs, "manques": [], "erreurs": erreurs}


def refuser_extrapolation(charge: object, *, presentee_comme_prevision_de_proprietaire: bool) -> None:
    """Refuse qu'une tendance extrapolée par M9 soit présentée comme la prévision d'un propriétaire."""
    if (
        presentee_comme_prevision_de_proprietaire
        and isinstance(charge, Mapping)
        and charge.get("origine") == ORIGINE_EXTRAPOLATION
    ):
        raise ValueError("REJ-CONTRAT-EXTRAPOLATION : une tendance extrapolée n'est pas une prévision de propriétaire")


def resume() -> list[dict]:
    """Contrats attendus avec leur état, pour la documentation et les tests (aucune lecture, aucune valeur)."""
    return [
        {
            "domaine": domaine,
            "proprietaire": contrat["proprietaire"],
            "lecture_id": contrat["lecture_id"],
            "outil_attendu": contrat["outil_attendu"],
            "etat": etat(domaine),
            "limite": contrat["limite"],
        }
        for domaine, contrat in CONTRATS.items()
    ]

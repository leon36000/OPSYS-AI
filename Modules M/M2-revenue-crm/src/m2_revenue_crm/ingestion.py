# M2-S003 — Ingestion d'un lead qualifié
# Respecte l'ordre canonique : horodatage → structure → frontières → unicité → écriture → accusé.
import copy

from . import encodage
from . import horodatage as _horodatage
from . import verdicts
from . import contrats
from . import frontieres

STATUT_INITIAL = "nouveau"
TYPE_ENTREE = "lead_ingere"


def ingerer(contrat, registre_cible, horodatage) -> tuple[dict | None, dict | None]:
    """Ingère un contrat LeadQualifie dans le registre append-only.

    Retourne un couple (accuse, verdict) dont exactement un membre est non-None.
    """
    # Rappel : on garantit qu’un seul chemin renvoie l’un ou l’autre.
    def _construire(accuse=None, verdict=None):
        """Garantit par construction qu’exactement un des deux est fourni."""
        if (accuse is None) == (verdict is None):
            raise RuntimeError("Invariant interne brisé : un seul doit être fourni")
        return (accuse, verdict)

    # 1. Horodatage valide.
    # Le paramètre « horodatage » est fixé par les tests ; le module est
    # donc importé sous l’alias _horodatage pour éviter le masquage.
    try:
        _horodatage.valider_horodatage(horodatage)
    except ValueError as e:
        return _construire(
            verdict=verdicts.construire_verdict(
                "REJ-HORODATAGE-INVALIDE",
                detail=str(e),
            )
        )

    # 2. Structure.
    ok, code = contrats.valider_structure(contrat)
    if not ok:
        return _construire(verdict=verdicts.construire_verdict(code))

    # 3. Frontières de vérité (prix, date d’exécution…).
    ok, raison = frontieres.inspecter_contrat(contrat)
    if not ok:
        return _construire(
            verdict=verdicts.construire_verdict(
                "REJ-FRONTIERE-VIOLEE",
                detail=raison,
            )
        )

    # 4. Unicité d’identité — aucun lead_id déjà ingéré.
    for maillon in registre_cible.lire():
        if maillon.get("type_entree") == TYPE_ENTREE and maillon.get("lead_id") == contrat["lead_id"]:
            return _construire(verdict=verdicts.construire_verdict("REJ-LEAD-DEJA-INGERE"))

    # 5. Écriture : un seul appel, précédé d’une copie profonde du contrat.
    contrat_gelé = copy.deepcopy(contrat)
    empreinte_contrat = encodage.empreinte(contrat_gelé)

    entree = {
        "type_entree": TYPE_ENTREE,
        "horodatage": horodatage,
        "lead_id": contrat["lead_id"],
        "contrat": contrat_gelé,
        "empreinte_contrat": empreinte_contrat,
        "statut": STATUT_INITIAL,
    }

    ligne_id = registre_cible.ajouter(entree)

    # Relecture du maillon tel qu’inscrit (pas le dict passé).
    maillons = registre_cible.lire()
    maillon_inscrit = maillons[-1]
    empreinte_maillon = encodage.empreinte(maillon_inscrit)

    tete_chaine = registre_cible.tete()

    # 6. Accusé de réception vérifiable sans confiance.
    accuse = {
        "lead_id": contrat["lead_id"],
        "ligne_id": ligne_id,
        "statut": STATUT_INITIAL,
        "empreinte_contrat": empreinte_contrat,
        "empreinte_maillon": empreinte_maillon,
        "tete_chaine": tete_chaine,
        "horodatage": horodatage,
    }
    return _construire(accuse=accuse)

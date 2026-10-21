# M2-S003 — Ingestion d'un lead qualifié
# Respecte l'ordre canonique :
#   horodatage → structure → frontières → unicité → écriture → dédoublonnage → accusé.
import copy

from . import contrats, doublons, encodage, frontieres, verdicts
from . import horodatage as _horodatage

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
    # Version explicite (PLAN T0.13) : v1 gelée sans `schema_version`, v2 avec. Le détail du refus
    # dit quoi corriger, et quoi configurer quand le service n'est pas déclaré par l'instance.
    ok, code, detail = contrats.valider_structure_avec_detail(contrat)
    if not ok:
        return _construire(verdict=verdicts.construire_verdict(code, detail=detail))

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

    # 6. Dédoublonnage (correctif d'audit, PRD §2b parcours (b)) : chaque
    # ingestion doit comparer le nouveau lead aux leads déjà présents et
    # signaler un doublon probable. doublons.detecter est un READ pur (aucun
    # maillon écrit ici) : le signalement effectif (doublons.signaler, qui
    # écrit) reste une étape distincte, décidée par l'appelant — jamais de
    # fusion, jamais automatique à l'intérieur de l'ingestion elle-même.
    doublons_detectes = doublons.detecter(registre_cible, contrat["lead_id"])

    # 7. Accusé de réception vérifiable sans confiance.
    accuse = {
        "lead_id": contrat["lead_id"],
        "ligne_id": ligne_id,
        "statut": STATUT_INITIAL,
        "empreinte_contrat": empreinte_contrat,
        "empreinte_maillon": empreinte_maillon,
        "tete_chaine": tete_chaine,
        "horodatage": horodatage,
        "doublons_detectes": doublons_detectes,
    }
    return _construire(accuse=accuse)

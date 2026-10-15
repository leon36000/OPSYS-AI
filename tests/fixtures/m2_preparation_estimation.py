"""Données FICTIVES : préparation M2 réelle pour les tests durables M3.

Le domaine M2 écrit dans le registre canonique de la base temporaire du test.
Aucun remplacement du vérificateur ni événement ajouté au bus par la fixture.
Les permissions des outils M2 sont qualifiées séparément par leurs tests natifs.
"""

from m2_revenue_crm import ingestion, interactions, readiness, statuts
from m2_revenue_crm.registre import Registre

from opsys import stockage

FICTIF = True
HORODATAGE = "2026-09-28T10:00:00-04:00"


def marqueur_m2(lead_id, *, type_travaux="ravalement", ville="Quebec"):
    """Émet un marqueur courant ; ne réécrit pas un lead déjà prêt."""
    with stockage.transaction():
        registre = Registre(stockage.maillons("m02-revenue-crm", "principal"))
        statut = statuts.statut_courant(registre, lead_id)
        if statut is None:
            _, refus = ingestion.ingerer({
                "lead_id": lead_id, "conversation_id": f"conv-fictive-{lead_id}",
                "type_travaux": type_travaux, "ville": ville, "canal": "formulaire",
                "contact": {"nom": "Client FICTIF", "telephone": "5145550101"},
                "urgence_declaree": False,
            }, registre, HORODATAGE)
            assert refus is None, refus
            statut = "nouveau"
        if statut == "nouveau":
            _, refus = statuts.transitionner(
                lead_id, "qualifie", registre, HORODATAGE, owner="vendeur-fixture-fictif",
                prochaine_action={"description": "Visite FICTIVE", "echeance": HORODATAGE},
            )
            assert refus is None, refus
            _, refus = interactions.enregistrer(
                lead_id, "vendeur-fixture-fictif", "Qualification FICTIVE", registre, HORODATAGE,
            )
            assert refus is None, refus
        marqueur, refus = readiness.emettre_marqueur(registre, lead_id, HORODATAGE)
        assert refus is None and marqueur is not None, refus
        assert readiness.verifier_marqueur(marqueur, registre) is True
        return marqueur

"""Fixtures canoniques M2/M10 fictives, partagées sans import d'un module de tests."""
from __future__ import annotations

from opsys import stockage
from opsys.memoire import autorite


def lier_affaire(lead="LEAD-FICTIF-A", session="agent:m01-front-office:webchat:direct:fictif-A", associer=True):
    from m2_revenue_crm import clients, ingestion
    from m2_revenue_crm import registre as m2
    from m10_memoire import liaison
    from m10_memoire import registre as m10
    contrat = {"lead_id": lead, "conversation_id": "CONV-FICTIVE-" + lead,
        "contact": {"nom": "Client fictif " + lead, "telephone": "555-0101", "courriel": "fictif@example.test"},
        "type_travaux": "renovation_totale", "ville": "Québec", "urgence_declaree": False, "canal": "telephone"}
    instant = "2026-10-02T10:00:00+00:00"
    with stockage.transaction():
        journal = m2.Registre(stockage.maillons("m02-revenue-crm", "principal"))
        assert ingestion.ingerer(contrat, journal, instant)[1] is None
        if associer:
            assert clients.lier_lead(journal, lead, contrat, instant)[1] is None
        affaires = m10.Registre(maillons=stockage.maillons("m10-memoire", "affaires"))
        lien, refus = liaison.lier_session_affaire(session, lead, "owner_fictif", "admin", "appareil",
            "liaison de fixture fictive", instant, affaires)
        assert refus is None
    return session, clients.identifiant_client(contrat), lien


def emettre_ticket(policy, session, args):
    with stockage.transaction() as cnx:
        return autorite.emettre(cnx, policy, "m01-front-office", "m01-front-office", session, args)["ticket"]

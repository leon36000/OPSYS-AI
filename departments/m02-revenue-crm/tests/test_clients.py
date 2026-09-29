"""Client 360 (PLAN T2.2) : identité client, lien lead<->client, vue 360 compacte.

Module testé (`clients.py`) est PUR : ces tests n'importent que des modules purs du paquet
(jamais `outils.py`/`opsys`), même patron que `test_doublons.py`/`test_ingestion.py`.
"""

import pytest
from m2_revenue_crm import clients, ingestion, interactions, registre, statuts, verdicts


def _contrat_base():
    return {
        "lead_id": "lead-unique-1",
        "conversation_id": "conv-123",
        "contact": {"nom": "Dupont", "telephone": "0123456789", "courriel": "a@b.com"},
        "type_travaux": "renovation_totale",
        "ville": "Paris",
        "urgence_declaree": True,
        "canal": "telephone",
    }


def _ingerer(reg, lead_id, horodatage, **surcharges):
    """Ingère un lead PUIS le lie à son client (même ordre que outils._ingerer_et_lier, sans
    passer par outils.py) : retourne (accuse, lien_client)."""
    contrat = _contrat_base()
    contrat.update(surcharges)
    contrat["lead_id"] = lead_id
    accuse, verdict = ingestion.ingerer(contrat, reg, horodatage)
    assert verdict is None, f"ingestion refusée à tort : {verdict}"
    lien, verdict_client = clients.lier_lead(reg, lead_id, contrat, horodatage)
    assert verdict_client is None, f"lien client refusé à tort : {verdict_client}"
    return accuse, lien


class TestIdentifiantClient:
    def test_deux_contacts_identiques_produisent_le_meme_identifiant(self):
        contact = {"nom": "Zoé Leblanc", "telephone": "450-555-2222", "courriel": "zoe@example.test"}
        c1 = clients.identifiant_client({"contact": dict(contact)})
        c2 = clients.identifiant_client({"contact": dict(contact)})
        assert c1 == c2

    def test_deux_contacts_distincts_produisent_des_identifiants_distincts(self):
        c1 = clients.identifiant_client({"contact": {"nom": "A", "telephone": "1"}})
        c2 = clients.identifiant_client({"contact": {"nom": "B", "telephone": "2"}})
        assert c1 != c2

    def test_ordre_des_cles_du_contact_ne_change_pas_l_identifiant(self):
        c1 = clients.identifiant_client({"contact": {"nom": "A", "telephone": "1"}})
        c2 = clients.identifiant_client({"contact": {"telephone": "1", "nom": "A"}})
        assert c1 == c2

    @pytest.mark.parametrize("contact", [{}, None], ids=["contact_vide", "contact_absent"])
    def test_contact_non_exploitable_leve(self, contact):
        with pytest.raises(ValueError):
            clients.identifiant_client({"contact": contact} if contact is not None else {})

    def test_identifiant_ne_contient_jamais_le_contact_en_clair(self):
        """Loi 25 — minimisation : l'identifiant est une empreinte, jamais le contact lisible."""
        contact = {"nom": "Renseignement Personnel Distinctif", "telephone": "418-555-9999"}
        identifiant = clients.identifiant_client({"contact": contact})
        assert "Renseignement Personnel Distinctif" not in identifiant
        assert "418-555-9999" not in identifiant
        assert len(identifiant) == 64, "empreinte SHA256 hexadécimale attendue"


class TestLierLead:
    def test_premier_lien_ecrit_un_maillon(self):
        reg = registre.Registre()
        taille_avant = reg.taille()
        _accuse, lien = _ingerer(reg, "L1", "2026-06-15T09:00:00+00:00")
        assert lien["deja_associe"] is False
        assert reg.taille() == taille_avant + 2, "un maillon lead_ingere + un maillon client_associe"
        assert clients.client_de_lead(reg, "L1") == lien["client_id"]

    def test_lien_est_idempotent_pour_le_meme_lead(self):
        reg = registre.Registre()
        contrat = _contrat_base()
        ingestion.ingerer(contrat, reg, "2026-06-15T09:00:00+00:00")
        premier, verdict1 = clients.lier_lead(reg, "lead-unique-1", contrat, "2026-06-15T09:00:00+00:00")
        assert verdict1 is None
        taille_apres_premier = reg.taille()

        second, verdict2 = clients.lier_lead(reg, "lead-unique-1", contrat, "2026-06-15T09:05:00+00:00")
        assert verdict2 is None
        assert second["deja_associe"] is True
        assert second["client_id"] == premier["client_id"]
        assert reg.taille() == taille_apres_premier, "aucun second maillon client_associe écrit"

    def test_deux_leads_du_meme_contact_partagent_le_meme_client(self):
        contact = {"nom": "Marie Roy", "telephone": "581-555-1111", "courriel": "marie@example.test"}
        reg = registre.Registre()
        _a1, lien1 = _ingerer(reg, "D1", "2026-06-15T08:00:00+00:00", contact=dict(contact))
        _a2, lien2 = _ingerer(reg, "D2", "2027-01-10T08:00:00+00:00", contact=dict(contact))
        assert lien1["client_id"] == lien2["client_id"]
        assert sorted(clients.opportunites_du_client(reg, lien1["client_id"])) == ["D1", "D2"]

    def test_deux_leads_de_contacts_distincts_ont_des_clients_distincts(self):
        reg = registre.Registre()
        _a1, lien1 = _ingerer(
            reg, "E1", "2026-06-15T08:00:00+00:00",
            contact={"nom": "Client Un", "telephone": "1111111111"},
        )
        _a2, lien2 = _ingerer(
            reg, "E2", "2026-06-15T08:05:00+00:00",
            contact={"nom": "Client Deux", "telephone": "2222222222"},
        )
        assert lien1["client_id"] != lien2["client_id"]

    def test_horodatage_invalide_refuse_sans_ecriture(self):
        reg = registre.Registre()
        contrat = _contrat_base()
        ingestion.ingerer(contrat, reg, "2026-06-15T09:00:00+00:00")
        taille_avant = reg.taille()
        resultat, verdict = clients.lier_lead(reg, "lead-unique-1", contrat, "pas-une-date")
        assert resultat is None
        assert verdict["code"] == "REJ-HORODATAGE-INVALIDE"
        assert reg.taille() == taille_avant


class TestClientDeLead:
    def test_lead_inconnu_rend_none(self):
        reg = registre.Registre()
        assert clients.client_de_lead(reg, "INEXISTANT") is None

    def test_opportunites_du_client_inconnu_est_vide(self):
        reg = registre.Registre()
        assert clients.opportunites_du_client(reg, "client-inexistant") == []


class TestVue360:
    def test_client_id_introuvable_rend_un_verdict_nomme(self):
        reg = registre.Registre()
        vue, verdict = clients.obtenir_vue_360(reg, "client-inexistant")
        assert vue is None
        assert verdicts.est_verdict(verdict["code"])
        assert verdict["code"] == "REJ-TRANSITION-ILLEGALE"

    def test_vue_360_une_seule_opportunite(self):
        reg = registre.Registre()
        _accuse, lien = _ingerer(reg, "V1", "2026-06-15T09:00:00+00:00")
        vue, verdict = clients.obtenir_vue_360(reg, lien["client_id"])
        assert verdict is None
        assert vue["client_id"] == lien["client_id"]
        assert vue["contact"] == _contrat_base()["contact"]
        assert len(vue["opportunites"]) == 1
        opp = vue["opportunites"][0]
        assert opp["lead_id"] == "V1"
        assert opp["statut"] == "nouveau"
        assert opp["prochaine_action"] is None, "aucune transition encore : rien à inventer"
        assert vue["interactions_recentes"] == []

    def test_vue_360_plusieurs_opportunites_du_meme_client(self):
        contact = {"nom": "Client Répétitif", "telephone": "418-555-4444"}
        reg = registre.Registre()
        _ingerer(reg, "R1", "2026-01-10T09:00:00+00:00", contact=dict(contact))
        _ingerer(reg, "R2", "2026-08-20T09:00:00+00:00", contact=dict(contact))
        client_id = clients.client_de_lead(reg, "R1")
        vue, verdict = clients.obtenir_vue_360(reg, client_id)
        assert verdict is None
        leads_vus = sorted(o["lead_id"] for o in vue["opportunites"])
        assert leads_vus == ["R1", "R2"]

    def test_vue_360_reflete_la_prochaine_action_posee_par_une_transition(self):
        reg = registre.Registre()
        _ingerer(reg, "PA1", "2026-06-15T09:00:00+00:00")
        prochaine_action = {"description": "Rappeler", "echeance": "2026-06-20T09:00:00+00:00"}
        _, verdict_transition = statuts.transitionner(
            "PA1", "qualifie", reg, "2026-06-15T09:30:00+00:00",
            owner="Alice", prochaine_action=prochaine_action,
        )
        assert verdict_transition is None
        client_id = clients.client_de_lead(reg, "PA1")
        vue, _ = clients.obtenir_vue_360(reg, client_id)
        assert vue["opportunites"][0]["prochaine_action"] == prochaine_action

    def test_vue_360_interactions_recentes_triees_et_limitees_a_dix(self):
        reg = registre.Registre()
        _ingerer(reg, "IX1", "2026-06-15T09:00:00+00:00")
        # Douze interactions, insérées dans le DÉSORDRE chronologique, pour prouver le tri.
        horodatages = [f"2026-06-15T{9 + (i % 12):02d}:{(i * 7) % 60:02d}:00+00:00" for i in range(12)]
        for i, h in enumerate(horodatages):
            resultat, verdict = interactions.enregistrer("IX1", "Alice", f"Interaction {i}", reg, h)
            assert verdict is None, verdict
        client_id = clients.client_de_lead(reg, "IX1")
        vue, _ = clients.obtenir_vue_360(reg, client_id)
        assert len(vue["interactions_recentes"]) == 10, "compacte : au plus 10 interactions récentes"
        horodatages_vus = [item["horodatage"] for item in vue["interactions_recentes"]]
        assert horodatages_vus == sorted(horodatages_vus), "triées chronologiquement"

    def test_vue_360_ne_porte_aucun_champ_hors_du_contrat_deja_ingere(self):
        """Loi 25 — minimisation : la vue 360 ne fait que PROJETER des champs déjà présents dans
        le contrat ingéré ou déjà écrits ailleurs au registre (statut, interactions) — jamais un
        nouveau renseignement personnel."""
        reg = registre.Registre()
        _ingerer(reg, "M25-1", "2026-06-15T09:00:00+00:00")
        client_id = clients.client_de_lead(reg, "M25-1")
        vue, _ = clients.obtenir_vue_360(reg, client_id)
        opp = vue["opportunites"][0]
        contrat = _contrat_base()
        for champ in ("ville", "type_travaux", "canal"):
            assert opp[champ] == contrat[champ]
        # Champs optionnels absents du contrat de test : reflétés comme absents, jamais inventés.
        assert opp["source"] is None
        assert opp["campagne"] is None
        assert opp["utm"] is None

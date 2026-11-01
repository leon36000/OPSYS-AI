"""M2.3, M2.4, M2.9, M2.15 — le vendeur, l'admin et l'employé, par la VRAIE porte d'appareil (E2E moteur HTTP MCP).

Le scénario est celui de l'app : deux vendeurs appairés (`seller`), l'admin (Nathan) et l'employé (Étienne), sur le
moteur réel (`PorteAppareil`, la règle du core relue dans le fork, appliquée au vrai serveur HTTP MCP sur une base
temporaire).

Ce que ces tests prouvent : un vendeur classe, score et analyse SES leads seulement ; il propose puis CONFIRME en
personne le profil de propriété de SON client (un fait minimisé part au bus) ; il décide d'une suggestion du coach ;
l'employé est refusé (403) partout ; le coach lui-même (contexte, proposition) est FERMÉ à tous les appareils ; un
reçu de prévision se rejoue par la porte. Ce que ces tests ne prouvent PAS : l'écran (Jest, `mobile/`) ni le core
natif TypeScript (CI).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from harnais_e2e import Moteur, PorteAppareil, iso

from opsys.outils import executer_atomique

HORODATAGE = "2026-09-29T12:00:00-04:00"
ACTION = {"description": "Appeler le client (fictif)", "echeance": "2026-09-05T09:00:00-04:00"}
ADRESSE = {"ligne": "12 rue des Lilas", "ville": "Repentigny"}
SOURCE = {"type": "constate_vendeur", "reference": "visite-2026-09-20"}


def _m2(moteur: Moteur) -> dict[str, Any]:
    return {o.nom: o for o in moteur.departements["m02-revenue-crm"].charger_outils()}


def _lead(m2: dict[str, Any], lead_id: str, owner: str, minute: int) -> None:
    contrat = {
        "lead_id": lead_id,
        "conversation_id": f"conv-{lead_id}",
        "contact": {"nom": f"Client {lead_id} (fictif)", "courriel": f"{lead_id}@exemple-fictif.test"},
        "type_travaux": "renovation_totale",
        "ville": "Repentigny",
        "urgence_declaree": minute % 2 == 0,
        "canal": "telephone",
    }
    reponse = executer_atomique(
        m2["m2_ingerer_lead"], {"contrat": contrat, "horodatage": f"2026-09-01T09:{minute:02d}:00-04:00"}
    )
    assert reponse["ok"] and reponse["resultat"]["accepte"], reponse
    reponse = executer_atomique(
        m2["m2_transitionner_statut"],
        {
            "lead_id": lead_id,
            "statut_cible": "qualifie",
            "horodatage": "2026-09-02T09:00:00-04:00",
            "owner": owner,
            "prochaine_action": ACTION,
        },
    )
    assert reponse["ok"] and reponse["resultat"]["accepte"], reponse


@pytest.fixture
def vente(moteur, equipe, monkeypatch):
    moteur.creer_personne("vendeur.a", "Vendeur A (fictif)", ["seller"], monkeypatch)
    moteur.creer_personne("vendeur.b", "Vendeur B (fictif)", ["seller"], monkeypatch)
    portes = {"a": moteur.appairer("vendeur.a", "seller"), "b": moteur.appairer("vendeur.b", "seller")}
    m2 = _m2(moteur)
    for i in range(3):
        _lead(m2, f"lead-a-{i}", "vendeur.a", i)
    for i in range(2):
        _lead(m2, f"lead-b-{i}", "vendeur.b", 10 + i)
    return {**equipe, **portes}


def _invoquer(porte: PorteAppareil, outil: str, **args: Any):
    return porte.appeler(outil, {"horodatage": HORODATAGE, **args})


def _ecrire(moteur: Moteur, porte: PorteAppareil, outil: str, cle: str, **args: Any):
    """Une écriture d'appareil : clé d'idempotence et heure de l'appareil (celle de RÉCEPTION du serveur fait foi)."""
    return porte.appeler(
        outil, {"horodatage": HORODATAGE, **args}, cle=cle, horodatage_appareil=iso(moteur.horloge.maintenant)
    )


def test_le_vendeur_classe_et_score_ses_leads_seulement(moteur, vente):
    a, b = vente["a"], vente["b"]
    file_a = _invoquer(a, "m2_classer_file_leads")
    assert file_a.statut == 200 and file_a.metier["accepte"] is True
    assert file_a.mesure.tronque is False
    resultat = file_a.resultat
    assert sorted(e["lead_id"] for e in resultat["file"]) == ["lead-a-0", "lead-a-1", "lead-a-2"]
    assert resultat["total_ouverts"] == 3 and resultat["decision_humaine_requise"] is True
    brut = json.dumps(file_a.corps, ensure_ascii=False)
    assert "lead-b-" not in brut and "vendeur.b" not in brut
    assert sorted(e["lead_id"] for e in _invoquer(b, "m2_classer_file_leads").resultat["file"]) == [
        "lead-b-0",
        "lead-b-1",
    ]
    assert len(_invoquer(vente["admin"], "m2_classer_file_leads").resultat["file"]) == 5

    score = _invoquer(a, "m2_calculer_score_lead", lead_id="lead-a-0", avec_recu=True)
    assert score.statut == 200 and score.mesure.tronque is False
    recu = score.resultat["recu"]
    assert recu["format"] == "recu-calcul.v1" and recu["moteur"] == "score_lead"
    rejeu = a.appeler("m2_rejouer_recu_commercial", {"recu": recu})
    assert rejeu.statut == 200 and rejeu.resultat["identique"] is True

    autre = _invoquer(a, "m2_calculer_score_lead", lead_id="lead-b-0")
    assert autre.statut == 200 and autre.metier["accepte"] is False
    assert autre.metier["verdict"]["code"] == "REJ-LEAD-NON-ASSIGNE"


def test_l_employe_est_refuse_partout_et_le_coach_est_ferme_a_tous_les_appareils(moteur, vente):
    employe = vente["employe"]
    for outil, args in (
        ("m2_classer_file_leads", {}),
        ("m2_calculer_score_lead", {"lead_id": "lead-a-0"}),
        ("m2_lire_profil_propriete", {"lead_id": "lead-a-0"}),
        ("m2_analyser_pipeline", {}),
        ("m2_declarer_valeur_pipeline", {"lead_id": "lead-a-0", "montant": "100"}),
    ):
        refus = _invoquer(employe, outil, **args)
        assert refus.statut == 403 and "tool_out_of_scope" in refus.corps["error"]["message"], outil
    for porte in (vente["a"], vente["admin"], employe):
        for outil, args in (
            ("m2_contexte_coach", {"lead_id": "lead-a-0"}),
            (
                "m2_proposer_suggestion_coach",
                {
                    "lead_id": "lead-a-0",
                    "genre": "prochaine_action",
                    "texte": "Rappeler le client.",
                    "faits_cites": [],
                    "empreinte_contexte": "0" * 64,
                },
            ),
        ):
            refus = _invoquer(porte, outil, **args)
            assert refus.statut == 403 and "tool_out_of_scope" in refus.corps["error"]["message"], outil


def test_le_vendeur_propose_puis_confirme_en_personne_le_profil_de_son_client_et_le_fait_minimise_part_au_bus(
    moteur, vente
):
    a, b = vente["a"], vente["b"]
    brouillon = _ecrire(
        moteur,
        a,
        "m2_proposer_profil_propriete",
        "e2e-ventes-1",
        lead_id="lead-a-0",
        revision_attendue=0,
        champs={"adresse": ADRESSE, "type_batiment": "duplex", "etages": 2},
        source=SOURCE,
    ).resultat
    assert brouillon["etat"] == "brouillon_a_confirmer"
    pid = brouillon["propriete_id"]
    # le vendeur B ne voit ni ne confirme rien du client de A
    refus = _ecrire(
        moteur,
        b,
        "m2_confirmer_profil_propriete",
        "e2e-ventes-3",
        lead_id="lead-a-0",
        propriete_id=pid,
        revision_attendue=1,
        decision="confirmer",
    )
    assert refus.metier["accepte"] is False and refus.metier["verdict"]["code"] == "REJ-LEAD-NON-ASSIGNE"
    assert (
        _invoquer(b, "m2_lire_profil_propriete", lead_id="lead-a-0").metier["verdict"]["code"] == "REJ-LEAD-NON-ASSIGNE"
    )
    # le vendeur A confirme en personne : l'identité du jeton fait foi
    confirme = _ecrire(
        moteur,
        a,
        "m2_confirmer_profil_propriete",
        "e2e-ventes-4",
        lead_id="lead-a-0",
        propriete_id=pid,
        revision_attendue=1,
        decision="confirmer",
    )
    assert (
        confirme.statut == 200
        and confirme.resultat["decide_par"] == "vendeur.a"
        and confirme.resultat["voie"] == "appareil"
    )
    lu = _invoquer(a, "m2_lire_profil_propriete", lead_id="lead-a-0").resultat["proprietes"][0]
    assert (
        lu["profil_confirme"]["champs"]["type_batiment"]["valeur"] == "duplex" and lu["brouillon_a_confirmer"] is None
    )
    # le fait minimisé est au bus, sans adresse précise
    faits = [e for e in _evenements(moteur) if e["type_evenement"] == "m2.profil_propriete_confirme"]
    assert len(faits) == 1 and "Lilas" not in faits[0]["charge"] and "duplex" in faits[0]["charge"]


def _evenements(moteur: Moteur) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from opsys import stockage
    from opsys.stockage.schema import EVENEMENTS_SORTANTS

    with stockage.transaction() as cnx:
        return [dict(r._mapping) for r in cnx.execute(select(EVENEMENTS_SORTANTS))]


def test_un_rejeu_de_la_meme_confirmation_ne_publie_pas_un_second_fait(moteur, vente):
    a = vente["a"]
    pid = _ecrire(
        moteur,
        a,
        "m2_proposer_profil_propriete",
        "e2e-ventes-2",
        lead_id="lead-a-0",
        revision_attendue=0,
        champs={"adresse": ADRESSE},
        source=SOURCE,
    ).resultat["propriete_id"]
    arguments = dict(lead_id="lead-a-0", propriete_id=pid, revision_attendue=1, decision="confirmer")
    premiere = _ecrire(moteur, a, "m2_confirmer_profil_propriete", "cle-unique-1", **arguments)
    seconde = _ecrire(moteur, a, "m2_confirmer_profil_propriete", "cle-unique-1", **arguments)
    assert premiere.statut == seconde.statut == 200
    assert len([e for e in _evenements(moteur) if e["type_evenement"] == "m2.profil_propriete_confirme"]) == 1


def test_le_vendeur_declare_une_valeur_lit_l_analytique_de_son_perimetre_et_la_prevision_refuse_sous_le_seuil(
    moteur, vente
):
    a = vente["a"]
    valeur = _ecrire(moteur, a, "m2_declarer_valeur_pipeline", "e2e-ventes-7", lead_id="lead-a-0", montant="12500.00")
    assert valeur.statut == 200 and valeur.resultat["declare_par"] == "vendeur.a"
    analyse = _invoquer(a, "m2_analyser_pipeline")
    assert analyse.statut == 200 and analyse.mesure.tronque is False
    assert analyse.resultat["pipeline"]["total"] == 3 and analyse.resultat["perimetre"].startswith(
        "les leads de la personne"
    )
    assert analyse.resultat["taux_conversion_des_resolus"]["valeur"] is None, (
        "3 leads : sous le seuil, on ne conclut pas"
    )
    prevision = _invoquer(
        a, "m2_prevoir_pipeline", serie="leads_ingeres", methode="moyenne_mobile", fenetre=4, horizon=2
    )
    assert prevision.metier["accepte"] is False
    assert prevision.metier["verdict"]["code"] in ("REJ-PREV-ECHANTILLON-INSUFFISANT", "REJ-PREV-PARAMETRE-INVALIDE")


def test_le_journal_du_coach_se_lit_et_se_decide_par_la_porte_mais_se_remplit_par_l_agent(moteur, vente):
    a = vente["a"]
    m2 = _m2(moteur)
    ctx = executer_atomique(m2["m2_contexte_coach"], {"lead_id": "lead-a-0", "horodatage": HORODATAGE})
    assert ctx["ok"] and ctx["resultat"]["accepte"] is True
    contexte = ctx["resultat"]["resultat"]
    statut = next(f for f in contexte["faits"] if f["genre"] == "statut")
    propose = executer_atomique(
        m2["m2_proposer_suggestion_coach"],
        {
            "lead_id": "lead-a-0",
            "genre": "prochaine_action",
            "horodatage": HORODATAGE,
            "texte": "Rappeler le client pour reprendre ses préoccupations avant de proposer la suite.",
            "faits_cites": [statut["id"]],
            "empreinte_contexte": contexte["empreinte_contexte"],
        },
    )
    assert propose["ok"] and propose["resultat"]["accepte"] is True, propose
    sid = propose["resultat"]["resultat"]["suggestion_id"]
    liste = a.appeler("m2_lister_suggestions_coach", {"lead_id": "lead-a-0"})
    assert liste.statut == 200 and liste.resultat["total"] == 1 and liste.resultat["suggestions"][0]["envoye"] is False
    assert vente["b"].appeler("m2_lister_suggestions_coach", {"lead_id": "lead-a-0"}).metier["accepte"] is False
    decide = _ecrire(moteur, a, "m2_decider_suggestion_coach", "e2e-ventes-8", suggestion_id=sid, decision="accepter")
    assert decide.statut == 200 and decide.resultat["decide_par"] == "vendeur.a" and decide.resultat["envoye"] is False
    envoi = _ecrire(moteur, a, "m2_decider_suggestion_coach", "e2e-ventes-9", suggestion_id=sid, decision="envoyer")
    assert envoi.metier["accepte"] is False and envoi.metier["verdict"]["code"] in (
        "REJ-COACH-ENVOI-INTERDIT",
        "REJ-COACH-DEJA-DECIDEE",
    )
    assert (
        _ecrire(
            moteur, vente["b"], "m2_decider_suggestion_coach", "e2e-ventes-10", suggestion_id=sid, decision="rejeter"
        ).metier["accepte"]
        is False
    )

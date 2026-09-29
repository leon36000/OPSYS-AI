"""PLAN T4.9 : `liste_leads.evaluer`, les segments de chaque lead visible sans page ni filtre de segment.

Les relances (`relances.py`) tirent leurs relances dues des segments de T4.6 : elles lisent donc les mêmes fiches, avec
la même règle de chaque segment, dans le même ordre et pour les mêmes leads visibles que `m2_lister_leads`. Ce fichier
nourrit `evaluer` d'un VRAI registre en mémoire, rempli par les vraies fonctions de M2, et prouve : la forme de
l'évaluation, l'ordre (un instant, pas du texte), la visibilité (un lead invisible n'est ni évalué ni cité), le filtre
par statut, l'accord avec `lister` sur les segments, l'absence de lecture de la readiness, et ce qui manque pour tous
les leads. Données fictives (`fictif: true`). """

from __future__ import annotations

import copy
import json

import pytest
from m2_revenue_crm import (
    assignation,
    clients,
    ingestion,
    interactions,
    liste_leads,
    registre,
    segments,
    statuts,
)

FICTIF = True

MAINTENANT = "2026-09-29T12:00:00-04:00"
ACTION = {"description": "Appeler le client", "echeance": "2026-09-05T09:00:00-04:00"}
SEUILS_OK = segments.lire_seuils({"jours_inactivite_dormant": 30, "jours_soumission_perimee": 14})
SEUILS_VIDES = segments.lire_seuils({})
CLES_D_UN_LEAD = {"lead_id", "statut", "proprietaire", "client_id", "segments", "non_calculables"}


def _ingerer(reg, lead_id, horodatage="2026-09-01T09:00:00-04:00", *, contact=None):
    contrat = {
        "lead_id": lead_id, "conversation_id": f"conv-{lead_id}",
        "contact": contact or {"nom": f"Client {lead_id}", "courriel": f"{lead_id}@example.test"},
        "type_travaux": "renovation_totale", "ville": "Québec", "urgence_declaree": False, "canal": "telephone",
    }
    _, verdict = ingestion.ingerer(contrat, reg, horodatage)
    assert verdict is None, verdict
    _, verdict_client = clients.lier_lead(reg, lead_id, contrat, horodatage)
    assert verdict_client is None, verdict_client


def _qualifier(reg, lead_id, owner="vendeur.un", horodatage="2026-09-01T10:00:00-04:00"):
    _, verdict = statuts.transitionner(lead_id, "qualifie", reg, horodatage, owner=owner, prochaine_action=ACTION)
    assert verdict is None, verdict


def _evaluer(reg, *, visibles=None, relances=(), seuils=SEUILS_OK, horodatage=MAINTENANT, **options):
    evaluation, verdict = liste_leads.evaluer(
        reg.lire(), visibles=visibles, relances_devis=None if relances is None else list(relances), seuils=seuils,
        horodatage=horodatage, **options)
    assert verdict is None, verdict
    return evaluation


def _par_lead(evaluation):
    return {lead["lead_id"]: lead for lead in evaluation["leads"]}


def _noms(lead, cle="segments"):
    return [s["segment"] for s in lead[cle]]


@pytest.fixture
def reg():
    return registre.Registre()


@pytest.fixture
def equipe(reg):
    """Quatre leads : deux du vendeur un (l'un dormant, l'autre avec un devis envoyé), un du vendeur deux, un
    nouveau."""
    _ingerer(reg, "lead-dormant", "2026-08-01T09:00:00-04:00")
    _qualifier(reg, "lead-dormant", "vendeur.un", "2026-08-01T10:00:00-04:00")
    _ingerer(reg, "lead-devis", "2026-09-01T09:00:00-04:00")
    _qualifier(reg, "lead-devis", "vendeur.un", "2026-09-27T10:00:00-04:00")
    _ingerer(reg, "lead-autre", "2026-09-02T09:00:00-04:00")
    _qualifier(reg, "lead-autre", "vendeur.deux", "2026-09-28T10:00:00-04:00")
    _ingerer(reg, "lead-nouveau", "2026-09-28T09:00:00-04:00")
    return reg


DEVIS_ENVOYE = [{
    "devis_id": "devis-1", "lead_id": "lead-devis", "statut_devis": "envoye",
    "horodatage_devis": "2026-09-10T09:00:00-04:00",
}]


# ---------------------------------------------------------------------------------------------------------
# La forme
# ---------------------------------------------------------------------------------------------------------
def test_l_evaluation_porte_les_leads_ce_qui_manque_pour_tous_et_les_opportunites_par_client(equipe):
    evaluation = _evaluer(equipe)
    assert set(evaluation) == {"leads", "non_calculables_globaux", "opportunites_par_client"}
    for lead in evaluation["leads"]:
        assert set(lead) == CLES_D_UN_LEAD
    assert evaluation["non_calculables_globaux"] == segments.segments_non_calculables(SEUILS_OK, True)
    assert {n["segment"] for n in evaluation["non_calculables_globaux"]} >= {
        "needs_photos", "quote_sent", "high_value_customer", "referral_candidate", "complaint_risk",
        "seasonal_opportunity"}


def test_chaque_lead_dit_son_statut_son_proprietaire_et_son_client():
    reg = registre.Registre()
    _ingerer(reg, "lead-1")
    _qualifier(reg, "lead-1", "vendeur.un")
    _ingerer(reg, "lead-2")
    evaluation = _par_lead(_evaluer(reg))
    assert evaluation["lead-1"]["statut"] == "qualifie" and evaluation["lead-1"]["proprietaire"] == "vendeur.un"
    assert evaluation["lead-2"]["statut"] == "nouveau" and evaluation["lead-2"]["proprietaire"] is None
    for lead_id, lead in evaluation.items():
        assert lead["client_id"] == clients.client_de_lead(reg, lead_id) is not None


def test_le_proprietaire_courant_est_celui_de_la_derniere_assignation(reg):
    _ingerer(reg, "lead-1")
    _qualifier(reg, "lead-1", "vendeur.un")
    _, verdict = assignation.reassigner(
        reg, "lead-1", "vendeur.deux", "Le vendeur un part en congé.", "2026-09-10T09:00:00-04:00",
        "admin.fictif", "admin", "appareil")
    assert verdict is None
    assert _par_lead(_evaluer(reg))["lead-1"]["proprietaire"] == "vendeur.deux"


def test_deux_leads_du_meme_contact_partagent_un_client_et_les_opportunites_le_disent(reg):
    contact = {"nom": "Client fictif", "courriel": "client-fictif@example.test"}
    _ingerer(reg, "lead-1", contact=contact)
    _ingerer(reg, "lead-2", "2026-09-05T09:00:00-04:00", contact=contact)
    _ingerer(reg, "lead-3")
    evaluation = _evaluer(reg)
    par_lead = _par_lead(evaluation)
    assert par_lead["lead-1"]["client_id"] == par_lead["lead-2"]["client_id"] != par_lead["lead-3"]["client_id"]
    assert evaluation["opportunites_par_client"][par_lead["lead-1"]["client_id"]] == ["lead-1", "lead-2"]
    assert evaluation["opportunites_par_client"][par_lead["lead-3"]["client_id"]] == ["lead-3"]


# ---------------------------------------------------------------------------------------------------------
# L'ordre, la visibilité, le filtre par statut
# ---------------------------------------------------------------------------------------------------------
def test_l_ordre_est_celui_de_lister_un_instant_d_ingestion_pas_du_texte(reg):
    _ingerer(reg, "lead-a", "2026-09-01T09:00:00-04:00")  # 13:00Z
    _ingerer(reg, "lead-b", "2026-09-01T12:00:00+00:00")  # 12:00Z : plus tôt, mais « 12 » > « 09 » en texte
    _ingerer(reg, "lead-c", "2026-09-01T09:00:00-04:00")  # même instant que lead-a : lead_id départage
    ids = [lead["lead_id"] for lead in _evaluer(reg)["leads"]]
    assert ids == ["lead-b", "lead-a", "lead-c"]
    page, verdict = liste_leads.lister(
        reg.lire(), visibles=None, relances_devis=[], seuils=SEUILS_OK, horodatage=MAINTENANT, budget_caracteres=5900)
    assert verdict is None and [lead["lead_id"] for lead in page["leads"]] == ids


def test_sans_ensemble_visible_tous_les_leads_sont_evalues(equipe):
    assert [lead["lead_id"] for lead in _evaluer(equipe)["leads"]] == [
        "lead-dormant", "lead-devis", "lead-autre", "lead-nouveau"]


def test_un_lead_hors_de_l_ensemble_visible_n_est_ni_evalue_ni_cite(equipe):
    evaluation = _evaluer(equipe, visibles={"lead-dormant", "lead-devis"})
    assert [lead["lead_id"] for lead in evaluation["leads"]] == ["lead-dormant", "lead-devis"]
    texte = json.dumps(evaluation["leads"])
    for invisible in ("lead-autre", "lead-nouveau", "vendeur.deux"):
        assert invisible not in texte, invisible


def test_un_ensemble_visible_vide_n_evalue_aucun_lead(equipe):
    evaluation = _evaluer(equipe, visibles=set())
    assert evaluation["leads"] == []
    assert evaluation["non_calculables_globaux"], "ce qui manque pour tous reste dit"


def test_les_opportunites_d_un_client_comptent_ses_leads_invisibles_car_la_frequence_est_celle_d_une_personne(reg):
    contact = {"nom": "Client fictif", "courriel": "client-fictif@example.test"}
    _ingerer(reg, "lead-visible", contact=contact)
    _ingerer(reg, "lead-invisible", "2026-09-05T09:00:00-04:00", contact=contact)
    evaluation = _evaluer(reg, visibles={"lead-visible"})
    assert [lead["lead_id"] for lead in evaluation["leads"]] == ["lead-visible"]
    (opportunites,) = evaluation["opportunites_par_client"].values()
    assert opportunites == ["lead-visible", "lead-invisible"]


def test_le_filtre_par_statut_ne_garde_que_les_leads_de_ces_statuts(equipe):
    ouverts = _evaluer(equipe, statuts_retenus=("nouveau", "qualifie"))
    assert len(ouverts["leads"]) == 4
    seulement_nouveaux = _evaluer(equipe, statuts_retenus=("nouveau",))
    assert [lead["lead_id"] for lead in seulement_nouveaux["leads"]] == ["lead-nouveau"]
    aucun = _evaluer(equipe, statuts_retenus=("converti",))
    assert aucun["leads"] == []
    assert len(_evaluer(equipe, statuts_retenus=None)["leads"]) == 4


def test_le_filtre_par_statut_et_la_visibilite_se_combinent(equipe):
    evaluation = _evaluer(equipe, visibles={"lead-dormant", "lead-nouveau"}, statuts_retenus=("qualifie",))
    assert [lead["lead_id"] for lead in evaluation["leads"]] == ["lead-dormant"]


# ---------------------------------------------------------------------------------------------------------
# Les segments : les mêmes que ceux de `lister`
# ---------------------------------------------------------------------------------------------------------
def test_un_lead_dormant_a_son_segment_avec_sa_regle_et_sa_donnee(equipe):
    lead = _par_lead(_evaluer(equipe))["lead-dormant"]
    (dormant,) = [s for s in lead["segments"] if s["segment"] == "dormant_lead"]
    assert dormant["regle"] == "lead_ouvert_sans_activite"
    assert dormant["donnee"]["seuil_jours"] == 30 and dormant["donnee"]["jours_ecoules"] == 59
    assert dormant["donnee"]["derniere_activite"] == "2026-08-01T10:00:00-04:00"


def test_un_devis_envoye_perime_donne_quote_stale_a_partir_de_l_instant_de_l_envoi(equipe):
    lead = _par_lead(_evaluer(equipe, relances=DEVIS_ENVOYE))["lead-devis"]
    (perime,) = [s for s in lead["segments"] if s["segment"] == "quote_stale"]
    assert perime["donnee"] == {
        "devis_id": "devis-1", "statut_devis": "envoye", "horodatage_devis": "2026-09-10T09:00:00-04:00",
        "jours_ecoules": 19, "seuil_jours": 14,
    }


def test_les_segments_de_chaque_lead_sont_ceux_de_lister(equipe):
    evaluation = _par_lead(_evaluer(equipe, relances=DEVIS_ENVOYE))
    page, verdict = liste_leads.lister(
        equipe.lire(), visibles=None, relances_devis=list(DEVIS_ENVOYE), seuils=SEUILS_OK, horodatage=MAINTENANT,
        budget_caracteres=100_000)
    assert verdict is None
    for item in page["leads"]:
        assert evaluation[item["lead_id"]]["segments"] == item["segments"], item["lead_id"]
    assert {"dormant_lead", "quote_stale"} <= {s["segment"] for lead in evaluation.values() for s in lead["segments"]}


def test_sans_seuil_les_segments_datees_sont_non_calculables_pour_tous_et_le_disent(equipe):
    evaluation = _evaluer(equipe, seuils=SEUILS_VIDES, relances=DEVIS_ENVOYE)
    manques = {n["segment"]: n["manque"] for n in evaluation["non_calculables_globaux"]}
    assert "seuil à configurer" in manques["dormant_lead"] and "seuil à configurer" in manques["quote_stale"]
    for lead in evaluation["leads"]:
        assert not {"dormant_lead", "quote_stale"} & set(_noms(lead)), "jamais évalué avec une valeur devinée"


def test_sans_lecture_des_devis_quote_stale_est_non_calculable_pour_tous(equipe):
    evaluation = _evaluer(equipe, relances=None)
    manque = {n["segment"]: n["manque"] for n in evaluation["non_calculables_globaux"]}["quote_stale"]
    assert "relances_devis_recues" in manque
    assert all("quote_stale" not in _noms(lead) for lead in evaluation["leads"])


def test_estimate_ready_n_est_pas_calcule_et_la_readiness_n_est_pas_lue(equipe, monkeypatch):
    def _interdit(*args, **kwargs):
        raise AssertionError("evaluer ne doit pas lire la readiness (elle lit le profil d'entreprise)")

    monkeypatch.setattr(liste_leads.readiness, "evaluer", _interdit)
    evaluation = _par_lead(_evaluer(equipe))
    qualifie = evaluation["lead-devis"]
    assert "estimate_ready" not in _noms(qualifie)
    assert "estimate_ready" in _noms(qualifie, "non_calculables")


def test_lister_lit_toujours_la_readiness_d_un_lead_qualifie(equipe, monkeypatch):
    appels = []
    monkeypatch.setattr(liste_leads.readiness, "evaluer", lambda vue, lead_id: appels.append(lead_id) or True)
    page, verdict = liste_leads.lister(
        equipe.lire(), visibles=None, relances_devis=[], seuils=SEUILS_OK, horodatage=MAINTENANT,
        budget_caracteres=100_000, segment="estimate_ready")
    assert verdict is None and sorted(appels) == ["lead-autre", "lead-devis", "lead-dormant"]
    assert [lead["lead_id"] for lead in page["leads"]] == ["lead-dormant", "lead-devis", "lead-autre"]


# ---------------------------------------------------------------------------------------------------------
# Refus, déterminisme
# ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("horodatage", ["", "hier", "2026-09-29", "2026-09-29T12:00:00", None, 5])
def test_un_instant_sans_fuseau_ou_illisible_est_refuse(equipe, horodatage):
    evaluation, verdict = liste_leads.evaluer(
        equipe.lire(), visibles=None, relances_devis=[], seuils=SEUILS_OK, horodatage=horodatage)
    assert evaluation is None and verdict["code"] == "REJ-HORODATAGE-INVALIDE"


def test_evaluer_ne_modifie_pas_le_registre_et_donne_toujours_la_meme_evaluation(equipe):
    maillons = equipe.lire()
    avant = copy.deepcopy(maillons)
    premiere, _ = liste_leads.evaluer(
        maillons, visibles=None, relances_devis=list(DEVIS_ENVOYE), seuils=SEUILS_OK, horodatage=MAINTENANT)
    seconde, _ = liste_leads.evaluer(
        maillons, visibles=None, relances_devis=list(DEVIS_ENVOYE), seuils=SEUILS_OK, horodatage=MAINTENANT)
    assert premiere == seconde and maillons == avant


def test_un_registre_vide_donne_une_evaluation_vide():
    evaluation = _evaluer(registre.Registre())
    assert evaluation["leads"] == [] and evaluation["opportunites_par_client"] == {}


def test_une_interaction_d_une_personne_repousse_le_dormant_une_interaction_systeme_non(reg):
    _ingerer(reg, "lead-1", "2026-08-01T09:00:00-04:00")
    _qualifier(reg, "lead-1", "vendeur.un", "2026-08-01T10:00:00-04:00")
    assert "dormant_lead" in _noms(_par_lead(_evaluer(reg))["lead-1"])
    interactions.enregistrer("lead-1", "system:m3", "Devis sans réponse (fictif)", reg, "2026-09-25T09:00:00-04:00")
    assert "dormant_lead" in _noms(_par_lead(_evaluer(reg))["lead-1"]), "une écriture du système n'est pas une activité"
    interactions.enregistrer("lead-1", "vendeur.un", "Appel fait (fictif)", reg, "2026-09-25T09:00:00-04:00")
    assert "dormant_lead" not in _noms(_par_lead(_evaluer(reg))["lead-1"])
